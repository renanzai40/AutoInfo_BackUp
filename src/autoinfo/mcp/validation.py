"""Agent-native MCP validation toolset.

Provides scenario loading, listing, and execution for validating MCP tool
behavior at runtime.  Each scenario is a YAML file in ``scenarios/`` that
defines a sequence of tool-call steps with expected envelope assertions.

This module is standalone — it does NOT import from ``autoinfo.mcp.server``
to avoid circular dependencies.  Dispatch is injected as a callable.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from autoinfo.llm import call_with_fallback

SCENARIOS_DIR: Path = Path(__file__).resolve().parent / "scenarios"

# ---------------------------------------------------------------------------
# Versioned run persistence (fixes #129 P0-3).
# Scenario results are saved under validation-runs/<date>/ and can be diffed
# across runs to expose pass/fail regression trends.
# ---------------------------------------------------------------------------

VALIDATION_RUNS_DIR: Path = Path(__file__).resolve().parents[3] / "validation-runs"


def _runs_dir(runs_dir: Path | None = None) -> Path:
    """Resolve the base runs directory (default: repo-root ``validation-runs``)."""
    return runs_dir or VALIDATION_RUNS_DIR


def _run_stamp(dt: datetime.datetime | None = None) -> str:
    """Run timestamp used for the run directory: ``YYYY-MM-DD_HHMMSS_ffffff``.

    Microsecond resolution guarantees two runs in the same wall-clock second
    (fast local runs, script loops) never collide on the run directory name.
    """
    return (dt or datetime.datetime.now()).strftime("%Y-%m-%d_%H%M%S_%f")


def save_scenario_results(
    results: list[dict[str, Any]],
    runs_dir: Path | None = None,
) -> Path:
    """Persist scenario results to ``validation-runs/<date>/scenarios.json``.

    Each run gets its own directory keyed by timestamp, so successive runs
    never overwrite each other.  The single-run view (``latest.json``) is
    refreshed so tooling can find the newest run without globbing.

    Parameters
    ----------
    results:
        List of scenario result envelopes (as returned by ``run_scenario``).
    runs_dir:
        Base directory; defaults to repo-root ``validation-runs``.

    Returns
    -------
    Path
        The run directory that was written.
    """
    run_dir = _runs_dir(runs_dir) / _run_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_dir.name,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "scenarios": results,
    }
    (run_dir / "scenarios.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Refresh the pointer to the newest run.
    (run_dir.parent / "latest.txt").write_text(run_dir.name, encoding="utf-8")
    return run_dir


def list_validation_runs(runs_dir: Path | None = None) -> list[Path]:
    """Return run directories sorted newest-first (``validation-runs/<date>``)."""
    base = _runs_dir(runs_dir)
    if not base.is_dir():
        return []
    return sorted(
        (p for p in base.iterdir() if p.is_dir() and (p / "scenarios.json").exists()),
        key=lambda p: p.name,
        reverse=True,
    )


def load_scenario_results(run_dir: Path) -> dict[str, Any] | None:
    """Load ``scenarios.json`` from a run directory, or ``None`` if absent."""
    payload_path = run_dir / "scenarios.json"
    if not payload_path.exists():
        return None
    try:
        return json.loads(payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def diff_scenario_runs(
    base: Path,
    head: Path,
) -> dict[str, Any]:
    """Compare the scenario statuses of two runs (base = older, head = newer).

    Returns
    -------
    dict
        ``{"base": run_id, "head": run_id, "new_passes": [...],
        "new_failures": [...], "recovered": [...], "recovered_steps": {...},
        "regressed": [...], "unchanged": N, "head_passed": N,
        "head_failed": N}``.
    """
    base_data = load_scenario_results(base) or {"scenarios": []}
    head_data = load_scenario_results(head) or {"scenarios": []}
    base_status = {r.get("scenario"): r.get("status") for r in base_data["scenarios"]}
    head_status = {r.get("scenario"): r.get("status") for r in head_data["scenarios"]}
    head_by_name = {r.get("scenario"): r for r in head_data["scenarios"]}

    new_passes, new_failures = [], []
    recovered, regressed = [], []
    recovered_steps: dict[str, list[str]] = {}
    unchanged = 0
    for name, head_st in head_status.items():
        base_st = base_status.get(name)
        # Issue #138: a step that was failed in base but passed-with-recovery
        # in head surfaces in the `recovered` bucket (per-scenario step names
        # land in `recovered_steps`).  Such scenarios are reported as
        # recovered, never double-counted in new_passes/new_failures.
        head_rec_steps = [
            s.get("name", "")
            for s in head_by_name.get(name, {}).get("steps", [])
            if s.get("recovered")
        ]
        recovered_case = bool(head_rec_steps) and base_st == "failed"
        if recovered_case:
            recovered.append(name)
            recovered_steps[name] = head_rec_steps
        if head_st == "passed":
            if base_st != "passed" and not recovered_case:
                new_passes.append(name)
        elif head_st == "failed":
            if base_st == "passed":
                regressed.append(name)
            elif not recovered_case:
                new_failures.append(name)
        else:  # unconfigured / skipped / error
            if base_st == "passed":
                regressed.append(name)
            elif base_st in (None, "failed", "unconfigured", "skipped", "error"):
                unchanged += 1
        if base_st == head_st:
            unchanged += 1

    return {
        "base": base.name,
        "head": head.name,
        "new_passes": new_passes,
        "new_failures": new_failures,
        "recovered": recovered,
        "recovered_steps": recovered_steps,
        "regressed": regressed,
        "unchanged": unchanged,
        "head_passed": sum(1 for s in head_status.values() if s == "passed"),
        "head_failed": sum(1 for s in head_status.values() if s == "failed"),
        "head_total": len(head_status),
    }


def _kill_process_group(proc: subprocess.Popen[Any]) -> None:
    """SIGKILL the whole process group of *proc*.

    The CLI step runs in its own session/process group
    (``start_new_session=True``), so killing the group is the only reliable
    way to reap orphaned grandchildren (background children spawned by the
    ``shell=True`` wrapper) after a timeout.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _run_cli_step(command: str, timeout: float = 180.0) -> dict[str, Any]:
    """Execute a CLI command in a real subprocess and normalize to an envelope.

    Returns ``{"success": exit_code == 0, "data": {exit_code, stdout, stderr}}``.
    Real process execution — never mocked.  Raises on timeout.

    The subprocess is spawned in its own session (``start_new_session=True``)
    so that a timeout can SIGKILL the entire process group — including any
    background children the shell may have spawned — instead of leaving
    orphaned processes behind.
    """
    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        proc.wait()
        raise
    return {
        "success": proc.returncode == 0,
        "data": {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    }


def _run_http_step(
    method: str,
    url: str,
    timeout: float = 60.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Perform a real HTTP request and normalize to an envelope.

    Returns ``{"success": 2xx/3xx, "data": {status_code, json, text}}``.
    Real network call — never mocked.  Raises on connection error.
    """
    import httpx  # noqa: PLC0415 — deferred import

    resp = httpx.request(method.upper(), url, timeout=timeout, **kwargs)
    try:
        body = resp.json()
    except Exception:
        body = None
    return {
        "success": 200 <= resp.status_code < 400,
        "data": {
            "status_code": resp.status_code,
            "json": body,
            "text": resp.text,
        },
    }

# ---------------------------------------------------------------------------
# LLM semantic judging (llm_assert) — real calls only, never mocked.
# Unconfigured LLM ⇒ step reports ``unconfigured`` (Director User BYOK
# obligation), never silently skipped.
# ---------------------------------------------------------------------------


def _is_llm_configured() -> bool:
    """Return ``True`` when a real LLM API key is available.

    Mirrors ``server._is_llm_configured`` but resolves ``${ENV_VAR}``
    references in ``config.llm.api_key`` so a placeholder value without
    an actual environment variable does not count as configured.
    """
    from autoinfo.config import get_config_path, load_config  # noqa: PLC0415

    try:
        config_path = get_config_path()
        if config_path:
            config = load_config(config_path)
            key = config.llm.api_key
            if key:
                if isinstance(key, str) and key.startswith("${") and key.endswith("}"):
                    return bool(os.environ.get(key[2:-1]))
                return True
    except Exception:
        pass
    return bool(os.environ.get("AUTOINFO_LLM_API_KEY"))


def _configured_domain_names() -> list[str]:
    """Return the names of domains configured in the project config.

    Used by ``run_scenario`` to check ``requires_domain`` preconditions
    (fixes #120). Falls back to an empty list when no config exists or it
    cannot be read.
    """
    from autoinfo.config import Config, get_config_path, load_config  # noqa: PLC0415

    try:
        config_path = get_config_path()
        config = load_config(config_path) if config_path else Config()
        return [d.name for d in config.domains]
    except Exception:
        return []


def _http_reachable(url: str, timeout: float = 2.0) -> bool:
    """Return ``True`` when *url* answers with any server status code.

    Any 2xx-4xx HTTP response counts as reachable (the service is up).
    Connection-level failures (refused, timeout, DNS) return ``False``.
    """
    import httpx  # noqa: PLC0415 — deferred import

    try:
        resp = httpx.get(url, timeout=timeout)
    except Exception:
        return False
    return 200 <= resp.status_code < 500


def _classify_step_exception(exc: Exception) -> str | None:
    """Return an ``unconfigured`` reason for known environment-prereq gaps.

    Exceptions that mean the environment is not set up — missing Reddit
    OAuth credentials, an unreachable TTS service, connection failures,
    an unreachable network (fixes #157) — map to a reason string.  Genuine
    code defects (everything else) return ``None`` so the caller keeps the
    historic ``failed`` classification.
    """
    import httpx  # noqa: PLC0415 — deferred import

    if (
        isinstance(exc, ValueError)
        and "requires client_id and client_secret" in str(exc)
    ):
        return (
            "Reddit OAuth credentials missing (client_id/client_secret). "
            "Director User must configure them before running this scenario."
        )
    if isinstance(exc, RuntimeError) and str(exc).startswith(
        "OpenAI TTS network error"
    ):
        return (
            "OpenAI TTS network error — the TTS service is unreachable. "
            "Check network access and re-run."
        )
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return (
            f"connection failure: {exc}. The required service is not "
            "reachable; start it and re-run."
        )
    if isinstance(exc, OSError) and "network is unreachable" in str(exc).lower():
        return f"network unreachable: {exc}. Check network access and re-run."
    return None


def _resolve_llm_config() -> dict[str, Any]:
    """Resolve the LLM call config from the project config.

    Returns ``{"model", "api_key", "api_base"}``.  ``model`` keeps its
    configured form (already prefixed with provider when configured that
    way); ``api_key`` comes from the config (with ``${ENV}`` references
    resolved by the config loader) or the ``AUTOINFO_LLM_API_KEY`` env var.
    """
    from autoinfo.config import Config, get_config_path, load_config  # noqa: PLC0415

    try:
        config_path = get_config_path()
        config = load_config(config_path) if config_path else Config()
    except Exception:
        config = Config()

    provider = config.llm.provider or "openrouter"
    model = config.llm.model or "deepseek/deepseek-chat"
    if "/" not in model:
        model = f"{provider}/{model}"
    # Resolve api_key consistently (fixes #119): resolve ${ENV} placeholders,
    # fall back to AUTOINFO_LLM_API_KEY env var when config key is empty.
    api_key = config.llm.api_key or ""
    if (
        isinstance(api_key, str)
        and api_key.startswith("${")
        and api_key.endswith("}")
    ):
        api_key = os.environ.get(api_key[2:-1], "")
    if not api_key:
        api_key = os.environ.get("AUTOINFO_LLM_API_KEY", "")
    return {
        "model": model,
        "api_key": api_key,
        "api_base": config.llm.base_url or None,
    }


def _resolve_llm_model() -> str:
    """Resolve the LLM model string from config, falling back to defaults.

    Same pattern as ``quality._resolve_llm_model``.
    """
    return _resolve_llm_config()["model"]


def _parse_llm_verdict(content: str | None) -> dict[str, Any]:
    """Parse the judge LLM response into ``{"verdict", "reason"}``.

    Tolerates bare JSON and ```json fenced blocks.  Raises ValueError on
    unexpected content so a broken judge response surfaces as FAIL.
    """
    if not content:
        raise ValueError("LLM judge returned empty content")
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"LLM judge returned non-JSON: {content[:200]!r}")
    data = json.loads(text[start : end + 1])
    verdict = str(data.get("verdict", "")).strip().upper()
    if verdict not in ("PASS", "FAIL"):
        raise ValueError(f"Unexpected LLM verdict: {verdict!r}")
    return {"verdict": verdict, "reason": str(data.get("reason", ""))}


def _llm_judge(assertion: str, tool_output: Any) -> dict[str, Any]:
    """Judge tool output against a natural-language assertion using a real
    LLM call (LiteLLM completion — the same path G4/G5 use).

    Returns ``{"verdict": "PASS"|"FAIL", "reason": str, "model": str,
    "tokens": {"prompt_tokens": int|None, "total_tokens": int|None} | None,
    "duration": float}``.  ``model`` is the resolved LLM model that served
    the call; ``tokens`` carries the usage counters from the response when
    the provider reports them (``None`` otherwise); ``duration`` is the
    wall-clock seconds of the completion call itself (``time.monotonic``).

    Raises
    ------
    RuntimeError
        If litellm is unavailable or every configured model fails.
    ValueError
        If the judge response cannot be parsed.
    """
    llm_cfg = _resolve_llm_config()
    prompt = (
        "You are a validation judge for the AutoInfo platform. Determine "
        "whether the assertion holds for the given tool output.\n\n"
        f"ASSERTION:\n{assertion}\n\n"
        f"TOOL OUTPUT (JSON):\n{json.dumps(tool_output, ensure_ascii=False)[:8000]}\n\n"
        'Reply with JSON exactly: {"verdict": "PASS" or "FAIL", '
        '"reason": "one-sentence justification"}'
    )
    start = time.monotonic()
    response = call_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        model=llm_cfg["model"],
        max_tokens=500,
        temperature=0.0,
        base_url=llm_cfg["api_base"],
        api_key=llm_cfg["api_key"] or None,
    )
    duration = time.monotonic() - start
    content = response.choices[0].message.content  # type: ignore[union-attr]
    parsed = _parse_llm_verdict(content)
    usage = getattr(response, "usage", None)
    tokens: dict[str, Any] | None = None
    if usage is not None:
        tokens = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
    return {
        "verdict": parsed["verdict"],
        "reason": parsed["reason"],
        "model": llm_cfg["model"],
        "tokens": tokens,
        "duration": duration,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_envelope(env: dict[str, Any]) -> dict[str, Any]:
    """Normalize a potential flat response into the standard envelope shape.

    Some tools (notably ``health_check``) return a flat dict without a
    ``success`` key because they bypass the standard ``call_tool`` wrapping.
    This helper transparently wraps flat responses so that assertion logic
    always operates on a uniform ``{success, data|error}`` envelope.
    """
    if "success" in env:
        return env  # already canonical envelope

    # Health-like flat responses have a "status" key (e.g. health_check)
    # but no "success" key.  Treat these as implicit success.
    return {"success": True, "data": env}


def _step_assert(
    step_name: str,
    tool: str,
    env: dict[str, Any],
    expect: dict[str, Any],
) -> dict[str, Any]:
    """Run assertions on a single tool-call envelope and return a step result.

    Supports the canonical envelope fields (``success`` / ``data_has`` /
    ``error_code`` / ``error_actionable``) plus surface-specific fields:

    - CLI (``kind: cli``): ``exit_code``, ``stdout_has``, ``stderr_has``
    - HTTP (``kind: http``): ``status_code``, ``json_has``
    """
    expected_success = expect.get("success", True)

    if env.get("success") != expected_success:
        return {
            "name": step_name,
            "tool": tool,
            "status": "failed",
            "detail": (
                f"expected success={expected_success}, "
                f"got success={env.get('success')}: {env}"
            ),
        }

    if expected_success:
        data = env.get("data")

        data_has = expect.get("data_has")
        if data_has is not None:
            if not isinstance(data, dict):
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"expected data_has={data_has} but data is not a dict: "
                        f"got {type(data).__name__}"
                    ),
                }
            missing = [k for k in data_has if k not in data]
            if missing:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"data_has keys missing: {missing}. "
                        f"Available keys: {list(data.keys())}"
                    ),
                }

        exit_code = expect.get("exit_code")
        if exit_code is not None and isinstance(data, dict):
            actual = data.get("exit_code")
            if actual != exit_code:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"expected exit_code={exit_code}, got {actual}. "
                        f"stderr: {data.get('stderr', '')[:500]}"
                    ),
                }

        stdout_has = expect.get("stdout_has")
        if stdout_has is not None and isinstance(data, dict):
            stdout = data.get("stdout", "")
            missing = [s for s in stdout_has if s not in stdout]
            if missing:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"stdout missing substrings: {missing}. "
                        f"stdout: {stdout[:500]}"
                    ),
                }

        stderr_has = expect.get("stderr_has")
        if stderr_has is not None and isinstance(data, dict):
            stderr = data.get("stderr", "")
            missing = [s for s in stderr_has if s not in stderr]
            if missing:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"stderr missing substrings: {missing}. "
                        f"stderr: {stderr[:500]}"
                    ),
                }

        status_code = expect.get("status_code")
        if status_code is not None and isinstance(data, dict):
            actual = data.get("status_code")
            if actual != status_code:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"expected status_code={status_code}, got {actual}. "
                        f"body: {data.get('text', '')[:500]}"
                    ),
                }

        json_has = expect.get("json_has")
        if json_has is not None and isinstance(data, dict):
            body = data.get("json")
            if not isinstance(body, dict):
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"expected json_has={json_has} but body is not a dict: "
                        f"got {type(body).__name__}: {data.get('text', '')[:300]}"
                    ),
                }
            missing = [k for k in json_has if k not in body]
            if missing:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"json_has keys missing: {missing}. "
                        f"Available keys: {list(body.keys())}"
                    ),
                }
    else:
        # expected_success == False — check error_code if specified
        error_code = expect.get("error_code")
        if error_code is not None:
            error = env.get("error", {})
            actual = error.get("code") if isinstance(error, dict) else None
            if actual != error_code:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"expected error_code={error_code}, "
                        f"got {actual}: {env}"
                    ),
                }

        # error_actionable (issue #141) — verify the actionable boolean
        # hint agents use to remediate is present on the error envelope.
        expected_actionable = expect.get("error_actionable")
        if expected_actionable is not None:
            error = env.get("error", {})
            actual_actionable = (
                error.get("actionable") if isinstance(error, dict) else None
            )
            if actual_actionable != expected_actionable:
                return {
                    "name": step_name,
                    "tool": tool,
                    "status": "failed",
                    "detail": (
                        f"expected error_actionable={expected_actionable}, "
                        f"got {actual_actionable}: {env}"
                    ),
                }

    return {
        "name": step_name,
        "tool": tool,
        "status": "passed",
        "detail": env,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _validate_steps(
    steps: list[Any],
    file_name: str,
    field: str,
    require_non_empty: bool = True,
    step_label: str = "step",
) -> None:
    """Validate a list of step mappings (shared by ``steps`` / ``cleanup_steps``).

    Every step must be a mapping with ``name`` plus the dispatch target for
    its kind (``tool`` for mcp, ``command`` for cli, ``method``/``url`` for
    http).  Defaults for ``arguments`` and ``expect`` are set in place.

    Parameters
    ----------
    steps:
        The step list from a scenario YAML file.
    file_name:
        Scenario file name, used in error messages.
    field:
        The YAML key the steps came from (``steps`` or ``cleanup_steps``).
    require_non_empty:
        When ``True`` (default) an empty list raises.  ``cleanup_steps``
        is allowed to be empty (treated as no cleanup).

    Raises
    ------
    ValueError
        If any step violates the schema.
    """
    if not isinstance(steps, list):
        raise ValueError(
            f"Scenario file {file_name}: '{field}' must be a list"
        )
    if require_non_empty and len(steps) == 0:
        raise ValueError(
            f"Scenario file {file_name}: '{field}' must be a non-empty list"
        )
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(
                f"Scenario file {file_name}, {step_label}[{i}]: "
                f"must be a mapping, got {type(step).__name__}"
            )
        if "name" not in step:
            raise ValueError(
                f"Scenario file {file_name}, {step_label}[{i}]: "
                f"missing required field 'name'"
            )
        kind = step.get("kind", "mcp")
        if kind == "cli":
            if "command" not in step:
                raise ValueError(
                    f"Scenario file {file_name}, {step_label}[{i}] (kind=cli): "
                    f"missing required field 'command'"
                )
        elif kind == "http":
            for req in ("method", "url"):
                if req not in step:
                    raise ValueError(
                        f"Scenario file {file_name}, {step_label}[{i}] "
                        f"(kind=http): missing required field '{req}'"
                    )
        else:
            if "tool" not in step:
                raise ValueError(
                    f"Scenario file {file_name}, {step_label}[{i}] (kind=mcp): "
                    f"missing required field 'tool'"
                )

        step.setdefault("arguments", {})
        step.setdefault("expect", {})

        # Issue #138: per-step recovery steps.  Same shape as ``steps`` —
        # executed only when the primary step fails (assertion mismatch,
        # dispatch exception, or timeout).  Empty lists are allowed (treated
        # as no recovery); defaults for nested steps are set in place.
        recovery_steps = step.get("recovery_steps")
        if recovery_steps is not None:
            if not isinstance(recovery_steps, list):
                raise ValueError(
                    f"Scenario file {file_name}, {step_label}[{i}]: "
                    f"'recovery_steps' must be a list"
                )
            _validate_steps(
                recovery_steps,
                file_name,
                "recovery_steps",
                require_non_empty=False,
                step_label=f"{step_label}[{i}].recovery_steps",
            )


def load_scenarios(scenarios_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load all ``*.yaml`` scenario files, sorted by filename.

    Parameters
    ----------
    scenarios_dir:
        Directory containing scenario YAML files.  Defaults to the built-in
        ``scenarios/`` directory next to this module.

    Returns
    -------
    list[dict]
        Each dict has ``name``, ``description``, ``steps``, and optionally
        ``category`` / ``requires_env``.

    Raises
    ------
    ValueError
        If a YAML file cannot be parsed, or if a scenario is missing the
        required ``name``, ``description``, or ``steps`` fields, or if any
        step is missing ``name`` or ``tool``.
    """
    sd = scenarios_dir or SCENARIOS_DIR
    scenarios: list[dict[str, Any]] = []

    if not sd.is_dir():
        return scenarios

    for yaml_path in sorted(sd.rglob("*.yaml")):
        try:
            with open(yaml_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse {yaml_path.name}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Scenario file {yaml_path.name} must contain a YAML mapping "
                f"(got {type(data).__name__})"
            )

        # Validate required top-level fields
        for field in ("name", "description", "steps"):
            if field not in data:
                raise ValueError(
                    f"Scenario file {yaml_path.name} is missing required "
                    f"field: '{field}'"
                )

        _validate_steps(data["steps"], yaml_path.name, "steps")

        cleanup_steps = data.get("cleanup_steps")
        if cleanup_steps is not None:
            if not isinstance(cleanup_steps, list):
                raise ValueError(
                    f"Scenario file {yaml_path.name}: 'cleanup_steps' must be a list"
                )
            _validate_steps(
                cleanup_steps, yaml_path.name, "cleanup_steps",
                require_non_empty=False, step_label="cleanup_step",
            )
        else:
            data["cleanup_steps"] = []

        # Set defaults for optional fields
        data.setdefault("category", "general")
        data.setdefault("requires_env", [])
        data.setdefault("requires_domain", [])
        data.setdefault("requires_http", [])

        # Issue #138: partial-pass policy validation.  Both keys are optional;
        # when absent the scenario keeps ALL-or-nothing semantics.
        min_passing = data.get("min_passing")
        if min_passing is not None and (
            not isinstance(min_passing, int) or min_passing <= 0
        ):
            raise ValueError(
                f"Scenario file {yaml_path.name}: 'min_passing' must be a "
                f"positive integer, got {min_passing!r}"
            )
        pass_ratio = data.get("pass_ratio")
        if pass_ratio is not None and (
            not isinstance(pass_ratio, float) or not (0 < pass_ratio <= 1)
        ):
            raise ValueError(
                f"Scenario file {yaml_path.name}: 'pass_ratio' must be a "
                f"float in (0, 1], got {pass_ratio!r}"
            )

        scenarios.append(data)

    return scenarios


def list_scenarios(scenarios_dir: Path | None = None) -> dict[str, Any]:
    """Return a summary of all available validation scenarios.

    Returns
    -------
    dict
        ``{"scenarios": [{name, description, category, step_count, requires_env},
        ...], "count": N}``
    """
    scs = load_scenarios(scenarios_dir)
    return {
        "scenarios": [
            {
                "name": sc["name"],
                "description": sc["description"],
                "category": sc.get("category", "general"),
                "step_count": len(sc["steps"]),
                "requires_env": sc.get("requires_env", []),
                "requires_http": sc.get("requires_http", []),
            }
            for sc in scs
        ],
        "count": len(scs),
    }


def _decorate_step_result(
    sr: dict[str, Any],
    step_def: dict[str, Any],
    step_index: int,
    trace_id: str,
    duration: float,
) -> dict[str, Any]:
    """Attach the per-step execution trace fields to a step result.

    Adds ``step_index`` (1-based position of the step in its scenario),
    ``duration`` (wall-clock seconds of the execution, including any
    recovery steps, measured with ``time.monotonic``), ``arguments`` (the
    step's own arguments dict as invoked), and ``trace_id`` (the scenario-
    run UUID shared by every step of that run).  All pre-existing keys on
    *sr* (``name`` / ``tool`` / ``status`` / ``detail`` / ``llm_reason`` /
    ``recovery`` / ...) are preserved unchanged.
    """
    decorated = dict(sr)
    decorated["step_index"] = step_index
    decorated["duration"] = duration
    decorated["arguments"] = step_def.get("arguments", {})
    decorated["trace_id"] = trace_id
    return decorated


async def _execute_step(
    step_def: dict[str, Any],
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None,
    step_index: int,
    trace_id: str,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Execute a single scenario step (kind: mcp|cli|http) and return its result.

    The returned result carries the per-step execution trace fields
    ``step_index`` (1-based), ``duration`` (wall-clock seconds as a float),
    ``arguments`` (the step's own arguments dict as invoked) and
    ``trace_id`` (the scenario-run UUID) alongside the pre-existing
    ``name`` / ``tool`` / ``status`` / ``detail`` keys.  On the
    ``llm_assert`` path the judge observability is embedded as an
    ``llm_meta`` sub-dict (``model`` / ``tokens`` / ``duration``) while the
    top-level ``llm_reason`` key is preserved.

    Runs the same real-execution path used by the main loop (never mocked),
    including ``llm_assert`` judging when configured.  The caller derives
    pass/fail/unconfigured counts and overall status from the result.

    *timeout* (seconds) is forwarded to the subprocess runners so a
    scenario-level timeout override (#203) also applies to ``kind: cli``
    and ``kind: http`` steps — previously those defaulted to 180s/60s
    regardless of the scenario declaration.
    """
    start = time.monotonic()
    expect = step_def.get("expect", {})
    kind = step_def.get("kind", "mcp")
    tool_ref = step_def.get("tool") or step_def.get("command") or step_def.get("url", kind)

    try:
        if kind == "cli":
            env = await asyncio.to_thread(_run_cli_step, step_def["command"], timeout)
        elif kind == "http":
            env = await asyncio.to_thread(
                _run_http_step,
                step_def.get("method", "GET"),
                step_def["url"],
                timeout=timeout,
                **step_def.get("http_options", {}),
            )
        else:
            if dispatch is None:
                raise RuntimeError(
                    f"mcp step '{step_def['name']}' requires a dispatch callable"
                )
            env = await dispatch(step_def["tool"], step_def.get("arguments", {}))
            if isinstance(env, dict):
                env = _normalize_envelope(env)
    except Exception as exc:
        reason = _classify_step_exception(exc)
        status = "unconfigured" if reason is not None else "failed"
        detail = reason if reason is not None else f"dispatch exception: {exc}"
        return _decorate_step_result(
            {
                "name": step_def["name"],
                "tool": tool_ref,
                "status": status,
                "detail": detail,
            },
            step_def,
            step_index,
            trace_id,
            time.monotonic() - start,
        )

    sr = _step_assert(
        step_def["name"],
        tool_ref,
        env,
        expect,
    )

    llm_assert = expect.get("llm_assert")
    if sr["status"] == "passed" and llm_assert:
        if not _is_llm_configured():
            return _decorate_step_result(
                {
                    "name": step_def["name"],
                    "tool": tool_ref,
                    "status": "unconfigured",
                    "detail": (
                        "llm_assert requires a real LLM API key, but none is "
                        "configured. Director User must run configure_llm() / "
                        "set AUTOINFO_LLM_API_KEY during onboarding (BYOK)."
                    ),
                },
                step_def,
                step_index,
                trace_id,
                time.monotonic() - start,
            )
        try:
            verdict = await asyncio.to_thread(
                _llm_judge, llm_assert, env.get("data")
            )
            llm_meta = {
                "model": verdict.get("model"),
                "tokens": verdict.get("tokens"),
                "duration": verdict.get("duration"),
            }
            if verdict["verdict"] == "PASS":
                return _decorate_step_result(
                    {
                        "name": step_def["name"],
                        "tool": tool_ref,
                        "status": "passed",
                        "detail": env,
                        "llm_reason": verdict["reason"],
                        "llm_meta": llm_meta,
                    },
                    step_def,
                    step_index,
                    trace_id,
                    time.monotonic() - start,
                )
            return _decorate_step_result(
                {
                    "name": step_def["name"],
                    "tool": tool_ref,
                    "status": "failed",
                    "detail": (
                        f"llm_assert FAILED: {verdict['reason']}. "
                        f"Tool output: {json.dumps(env, ensure_ascii=False)[:2000]}"
                    ),
                    "llm_reason": verdict["reason"],
                    "llm_meta": llm_meta,
                },
                step_def,
                step_index,
                trace_id,
                time.monotonic() - start,
            )
        except Exception as exc:
            return _decorate_step_result(
                {
                    "name": step_def["name"],
                    "tool": tool_ref,
                    "status": "failed",
                    "detail": f"llm_assert error: {exc}",
                },
                step_def,
                step_index,
                trace_id,
                time.monotonic() - start,
            )

    return _decorate_step_result(
        sr,
        step_def,
        step_index,
        trace_id,
        time.monotonic() - start,
    )


async def _execute_step_timed(
    step_def: dict[str, Any],
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None,
    timeout: float,
    step_index: int,
    trace_id: str,
) -> dict[str, Any]:
    """Execute a step under a per-step timeout (issue #134).

    On ``asyncio.TimeoutError`` the step is reported as failed with the
    same result shape ``_execute_step`` uses (including the per-step trace
    fields), so callers' status derivation (fail if any step failed)
    applies unchanged.
    """
    start = time.monotonic()
    try:
        return await asyncio.wait_for(
            _execute_step(step_def, dispatch, step_index, trace_id, timeout=timeout),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        kind = step_def.get("kind", "mcp")
        tool_ref = (
            step_def.get("tool")
            or step_def.get("command")
            or step_def.get("url", kind)
        )
        return _decorate_step_result(
            {
                "name": step_def["name"],
                "tool": tool_ref,
                "status": "failed",
                "detail": f"timed out after {timeout}s",
            },
            step_def,
            step_index,
            trace_id,
            time.monotonic() - start,
        )


def _count_step_result(sr: dict[str, Any], counts: dict[str, int]) -> None:
    """Increment the matching pass/fail/unconfigured counter for a step result.

    A step whose primary failed but whose recovery_steps succeeded is counted
    as ``recovered`` — never as a plain failure (issue #138).
    """
    status = sr.get("status")
    if status == "passed":
        counts["passed"] += 1
    elif status == "unconfigured":
        counts["unconfigured"] += 1
    elif sr.get("recovered"):
        counts["recovered"] += 1
    else:
        counts["failed"] += 1


async def _execute_step_with_recovery(
    step_def: dict[str, Any],
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None,
    timeout: float,
    step_index: int,
    trace_id: str,
) -> dict[str, Any]:
    """Execute a step and, on failure, its ``recovery_steps`` (issue #138).

    When the primary step fails — assertion mismatch, dispatch exception, or
    per-step timeout — every declared recovery step runs in order, each with
    the same per-step timeout and its own ``expect`` assertions.  The primary
    result keeps its ``failed`` status (its own assertion did fail) and gains:

    - ``recovery``: the list of recovery step results (with statuses),
    - ``recovery_status``: ``"passed"`` if any recovery step passed,
    - ``recovered``: ``True`` iff ``recovery_status == "passed"``.

    The primary result's ``duration`` covers the whole wall-clock execution
    including the recovery steps; recovery results carry the primary's
    ``step_index`` and the run's ``trace_id``.

    Non-failed primary steps (``passed``/``unconfigured``) never trigger
    recovery and return unchanged.
    """
    start = time.monotonic()
    sr = await _execute_step_timed(step_def, dispatch, timeout, step_index, trace_id)
    if sr["status"] != "failed":
        return sr
    recovery_defs = step_def.get("recovery_steps")
    if not recovery_defs:
        return sr
    recovery_results = [
        await _execute_step_timed(rdef, dispatch, timeout, step_index, trace_id)
        for rdef in recovery_defs
    ]
    recovered = any(r["status"] == "passed" for r in recovery_results)
    sr = dict(sr)
    sr["recovery"] = recovery_results
    sr["recovery_status"] = "passed" if recovered else "failed"
    sr["recovered"] = recovered
    sr["duration"] = time.monotonic() - start
    return sr


def _unconfigured_scenario_result(
    scenario: dict[str, Any], trace_id: str, reason: str
) -> dict[str, Any]:
    """Build the whole-scenario ``unconfigured`` early-return result.

    Every step is marked ``unconfigured`` with the same *reason* and no
    step runs; the summary counts all steps as unconfigured.  Shared by
    the ``requires_env`` / ``requires_domain`` / ``requires_http``
    precondition blocks so they produce byte-identical result shapes
    (fixes #157).
    """
    unconfigured_steps = [
        _decorate_step_result(
            {
                "name": s["name"],
                "tool": s.get("tool") or s.get("command") or s.get("url", ""),
                "status": "unconfigured",
                "detail": reason,
            },
            s,
            idx,
            trace_id,
            0.0,
        )
        for idx, s in enumerate(scenario["steps"], start=1)
    ]
    result: dict[str, Any] = {
        "scenario": scenario["name"],
        "description": scenario["description"],
        "category": scenario.get("category", "general"),
        "status": "unconfigured",
        "unconfigured_reason": reason,
        "summary": {
            "passed": 0,
            "failed": 0,
            "unconfigured": len(unconfigured_steps),
            "recovered": 0,
            "total": len(unconfigured_steps),
        },
        "steps": unconfigured_steps,
        "trace_id": trace_id,
    }
    for _key in ("regression", "regression_issue"):
        if _key in scenario:
            result[_key] = scenario[_key]
    return result


def is_excluded_artifact(relpath: str) -> bool:
    """True when a relative artifact path is a non-deliverable file (#192).

    Rejects rejected KB promotion drafts under a ``_failed/`` directory
    segment (``knowledge/_failed/<domain>/**``) and internal coverage-matrix
    reports under a ``coverage-matrix`` directory segment
    (``outputs/coverage-matrix/**``) so end-user validation packages never
    contain them.
    """
    segments = Path(relpath).as_posix().split("/")
    return "_failed" in segments or "coverage-matrix" in segments


async def run_scenario(
    name: str,
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    steps: list[int] | None = None,
    scenarios_dir: Path | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Execute a named validation scenario against the given dispatch function.

    Parameters
    ----------
    name:
        Scenario name (must match the ``name`` field of exactly one scenario file).
    dispatch:
        Async callable ``(tool_name, arguments) -> envelope dict``.
        The returned dict is expected to be a parsed JSON envelope
        ``{success, data}`` or ``{success, error}``.  Flat responses
        (e.g. from ``health_check``) are transparently normalised.
    steps:
        Optional list of 1-based step indices to run.  When provided, only
        those steps are executed; summary counts reflect only the executed
        steps.
    scenarios_dir:
        Directory to load scenarios from.  Defaults to the built-in
        ``scenarios/`` directory.
    timeout:
        Per-step timeout in seconds (default 180).  Each step — including
        each cleanup step — may run for at most this long before it is
        reported as failed with a ``timed out after <timeout>s`` detail.
        Applied per step, not as a whole-scenario budget: a scenario with
        N steps can run up to ~N×timeout.

    Returns
    -------
    dict
        ``{"scenario", "description", "category", "status", "summary",
        "steps", "trace_id", ("cleanup"), ("unconfigured_reason")}``.  When
        the scenario declares ``cleanup_steps``, they run after the main
        steps regardless of outcome (best-effort) and are reported under
        ``cleanup`` — they never influence ``status``.

        Every step result carries the per-step execution trace fields
        ``step_index`` (1-based), ``duration`` (wall-clock seconds as a
        float, including recovery execution), ``arguments`` (the step's own
        arguments dict as invoked), and ``trace_id`` — one UUID per
        scenario run, shared by all steps of that run and surfaced on the
        top-level result under ``trace_id``.  ``llm_assert`` steps embed the
        judge observability (``model`` / ``tokens`` / ``duration``) in an
        ``llm_meta`` sub-dict while keeping the top-level ``llm_reason``.

        Steps that declare ``recovery_steps`` (issue #138) run them after
        a primary failure; the step keeps its ``failed`` status and gains
        ``recovery`` / ``recovery_status`` / ``recovered``.  ``summary``
        reports ``recovered`` (failed primaries that a recovery step
        fixed) separately from ``failed``.  Status stays ALL-or-nothing
        unless the scenario declares ``min_passing`` (int) or
        ``pass_ratio`` (float), in which case it passes as soon as that
        many primary steps succeeded (passed or recovered).

    Raises
    ------
    ValueError
        If *name* does not match any loaded scenario, or if a *steps* index
        is out of range.
    """
    trace_id = str(uuid.uuid4())
    scs = load_scenarios(scenarios_dir)
    scenario = next((sc for sc in scs if sc["name"] == name), None)

    if scenario is None:
        available = ", ".join(sorted(sc["name"] for sc in scs))
        raise ValueError(
            f"Unknown validation scenario: {name}. Available: {available}"
        )

    # Scenario-level per-step timeout override (#203): long-running steps
    # such as enterprise-briefing generation exceed the 180s default.
    # Scenarios may declare a top-level ``timeout`` (seconds) to raise the
    # cap for every step in that scenario.
    timeout = float(scenario.get("timeout", timeout))

    requires_env: list[str] = scenario.get("requires_env", [])
    missing_env = [v for v in requires_env if not os.environ.get(v)]
    if missing_env:
        return _unconfigured_scenario_result(
            scenario,
            trace_id,
            (
                f"missing required env var(s): {', '.join(missing_env)}. "
                "Director User must configure these during onboarding "
                "(BYOK — see docs/dev/required-api-keys.md)."
            ),
        )

    # Precondition check: scenarios may declare required domains (fixes #120).
    # If the project config does not have one of the required domains, the
    # scenario reports unconfigured with the missing domain names instead of
    # failing every step with DomainNotFound.
    requires_domain: list[str] = scenario.get("requires_domain", [])
    if requires_domain:
        configured_domains = _configured_domain_names()
        missing_domains = [
            d for d in requires_domain if d not in configured_domains
        ]
        if missing_domains:
            return _unconfigured_scenario_result(
                scenario,
                trace_id,
                (
                    f"missing required domain(s): {', '.join(missing_domains)}. "
                    "Run `autoinfo init --demo <domain>` or add_domain() to "
                    "configure them before running this scenario."
                ),
            )

    # Precondition check (fixes #157): scenarios may declare required HTTP
    # endpoints (e.g. the REST API server).  An unreachable endpoint means
    # the environment is not set up — report unconfigured, not failed.
    requires_http: list[str] = scenario.get("requires_http", [])
    unreachable = [u for u in requires_http if not _http_reachable(u)]
    if unreachable:
        return _unconfigured_scenario_result(
            scenario,
            trace_id,
            (
                f"required HTTP endpoint not reachable: {', '.join(unreachable)}. "
                "Start the service (e.g. uvicorn on port 8741) and re-run."
            ),
        )

    # Determine which steps to run
    if steps is not None:
        if not steps:
            raise ValueError("steps list must not be empty when provided")
        max_idx = len(scenario["steps"])
        for idx in steps:
            if idx < 1 or idx > max_idx:
                raise ValueError(
                    f"Step index {idx} out of range (1-{max_idx}) for "
                    f"scenario '{name}'"
                )
        selected = [(idx, scenario["steps"][idx - 1]) for idx in steps]
    else:
        selected = [(i + 1, s) for i, s in enumerate(scenario["steps"])]

    step_results: list[dict[str, Any]] = []
    counts = {"passed": 0, "failed": 0, "unconfigured": 0, "recovered": 0}

    for step_idx, step_def in selected:
        sr = await _execute_step_with_recovery(
            step_def, dispatch, timeout, step_idx, trace_id
        )
        _count_step_result(sr, counts)
        step_results.append(sr)

    # Status derivation (issue #138):
    # - Default (no threshold): ALL-or-nothing — any unrecovered step failure
    #   fails the scenario.  Steps that failed then recovered are counted as
    #   ``recovered``, not ``failed``, so a fully-recovered scenario passes.
    #   Existing scenarios declare no recovery_steps, so this branch is
    #   byte-for-byte the historic behavior for them.
    # - Partial policy: when ``min_passing`` (int) or ``pass_ratio`` (float)
    #   is declared, the scenario passes as soon as enough primary steps
    #   *succeeded* (passed or recovered) — e.g. 3/7 sources OK is a partial
    #   pass, not an overall failure.
    status: str
    min_passing = scenario.get("min_passing")
    pass_ratio = scenario.get("pass_ratio")
    if min_passing is None and pass_ratio is None:
        if counts["failed"] > 0:
            status = "failed"
        elif counts["unconfigured"] > 0:
            status = "unconfigured"
        else:
            status = "passed"
    else:
        if counts["unconfigured"] > 0:
            status = "unconfigured"
        else:
            succeeded = counts["passed"] + counts["recovered"]
            total = (
                counts["passed"] + counts["failed"]
                + counts["recovered"] + counts["unconfigured"]
            )
            threshold_met = min_passing is not None and succeeded >= min_passing
            if not threshold_met and pass_ratio is not None:
                threshold_met = total > 0 and (succeeded / total) >= pass_ratio
            status = "passed" if threshold_met else "failed"

    # --- collect_artifacts: gather real data files produced by the scenario ---
    # (fixes #123, #125). Scenarios may declare glob patterns; matching files
    # are collected BEFORE cleanup so they still exist on disk (self-cleaning
    # scenarios delete their own state, which would empty artifact globs).
    # Artifacts give the delivery layer real RAW/PROCESSED/KB data to package
    # for end-user quality review.
    artifacts: list[dict[str, Any]] | None = None
    collect_patterns = scenario.get("collect_artifacts", [])
    if collect_patterns:
        artifacts = []
        for pattern in collect_patterns:
            for path in sorted(Path.cwd().glob(pattern)):
                # #192: never collect non-deliverable artifacts (rejected
                # KB promotion drafts under _failed/, coverage-matrix reports).
                if path.is_file() and not is_excluded_artifact(str(path)):
                    artifacts.append({
                        "pattern": pattern,
                        "path": str(path),
                        "size": path.stat().st_size,
                        "name": path.name,
                    })

    # --- cleanup_steps: always run after the main steps (best-effort) ----
    # Cleanup is executed regardless of the main steps' outcome so that
    # state-mutating scenarios can remove what they created even when a
    # middle step failed.  Cleanup results are reported separately and do
    # NOT influence the scenario status.  The unconfigured early-return
    # above skips cleanup because no step ran and no state was created.
    cleanup: dict[str, Any] | None = None
    cleanup_defs = scenario.get("cleanup_steps", [])
    if cleanup_defs:
        cleanup_results: list[dict[str, Any]] = []
        cleanup_counts = {"passed": 0, "failed": 0, "unconfigured": 0, "recovered": 0}
        for step_idx, step_def in enumerate(cleanup_defs, start=1):
            sr = await _execute_step_with_recovery(
                step_def, dispatch, timeout, step_idx, trace_id
            )
            _count_step_result(sr, cleanup_counts)
            cleanup_results.append(sr)
        cleanup = {
            "summary": {
                "passed": cleanup_counts["passed"],
                "failed": cleanup_counts["failed"],
                "unconfigured": cleanup_counts["unconfigured"],
                "recovered": cleanup_counts["recovered"],
                "total": len(cleanup_results),
            },
            "steps": cleanup_results,
        }

    result: dict[str, Any] = {
        "scenario": name,
        "description": scenario["description"],
        "category": scenario.get("category", "general"),
        "status": status,
        "summary": {
            "passed": counts["passed"],
            "failed": counts["failed"],
            "unconfigured": counts["unconfigured"],
            "recovered": counts["recovered"],
            "total": len(step_results),
        },
        "steps": step_results,
        "trace_id": trace_id,
    }
    if cleanup is not None:
        result["cleanup"] = cleanup
    if artifacts is not None:
        result["artifacts"] = artifacts
    for _key in ("regression", "regression_issue"):
        if _key in scenario:
            result[_key] = scenario[_key]

    return result
