"""Unit tests for run_doctor()'s bounded source probing (GitHub issue #193).

The source-probe loop used to walk every active domain source serially with a
10s per-request connect timeout — ~70 sources could take minutes and blow the
validation-scenario timeout.  These tests pin the bounded behaviour without
touching the network: ``_check_source`` is monkeypatched with stubs that block
far beyond the configured budgets, and the config layer is stubbed out.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import autoinfo.doctor as doctor_mod
from autoinfo.doctor import run_doctor

_BLOCK_S = 5.0


def _blocking_check_source(url: str, name: str) -> dict:
    """Probe stub that hangs far beyond any test-configured budget."""
    time.sleep(_BLOCK_S)
    return {"name": name, "status": "ok", "latency_ms": 1.0, "status_code": 200}


def _fast_check_source(url: str, name: str) -> dict:
    """Probe stub that completes immediately."""
    return {"name": name, "status": "ok", "latency_ms": 0.5, "status_code": 200}


def _fake_config(num_domains: int = 5) -> SimpleNamespace:
    """Minimal config stub exposing the attributes run_doctor() reads."""
    domains = [
        SimpleNamespace(
            active=True,
            sources=[
                SimpleNamespace(url=f"http://host{i}/feed", name=f"src{i}"),
            ],
        )
        for i in range(num_domains)
    ]
    return SimpleNamespace(
        domains=domains,
        llm=SimpleNamespace(provider="", model="", api_key=""),
    )


def _patch_env_and_config(monkeypatch: pytest.MonkeyPatch, num_domains: int = 5) -> None:
    """Wire run_doctor()'s config layer to a stub so probing is exercised."""
    monkeypatch.setattr(doctor_mod, "get_config_path", lambda: "stub/config.yaml")
    monkeypatch.setattr(doctor_mod, "load_config", lambda _path: _fake_config(num_domains))
    monkeypatch.setattr(doctor_mod, "validate_config", lambda _cfg: [])


def test_run_doctor_bounded_when_probes_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_doctor() must return within the total probe budget even when every
    probe blocks — serial probing would take N × probe time (25s+ here)."""
    monkeypatch.setattr(doctor_mod, "_check_source", _blocking_check_source)
    _patch_env_and_config(monkeypatch)
    monkeypatch.setenv("AUTOINFO_DOCTOR_SOURCE_TIMEOUT", "0.2")
    monkeypatch.setenv("AUTOINFO_DOCTOR_TOTAL_TIMEOUT", "1.0")

    start = time.monotonic()
    results = run_doctor()
    elapsed = time.monotonic() - start

    # Serial probing of 5 blocking probes would take >= 5 * 5s = 25s.
    assert elapsed < 4.0, f"run_doctor() took {elapsed:.2f}s — probing is unbounded"

    sources = results["sources"]
    assert len(sources) == 5, "every source must still be reported"
    for entry in sources:
        assert set(entry) >= {"name", "status", "latency_ms"}
        if entry["status"] != "ok":
            assert "timed out" in entry["detail"] or "deadline" in entry["detail"]


def test_run_doctor_total_deadline_skips_report_every_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the total deadline fires before a probe's own budget, sources are
    reported as skipped rather than dropped."""
    monkeypatch.setattr(doctor_mod, "_check_source", _blocking_check_source)
    _patch_env_and_config(monkeypatch)
    monkeypatch.setenv("AUTOINFO_DOCTOR_SOURCE_TIMEOUT", "5.0")
    monkeypatch.setenv("AUTOINFO_DOCTOR_TOTAL_TIMEOUT", "0.3")

    results = run_doctor()

    sources = results["sources"]
    assert len(sources) == 5
    assert all(entry["status"] == "error" for entry in sources)
    assert all("deadline" in entry["detail"] for entry in sources)


def test_run_doctor_fast_probes_keep_config_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fast probes complete normally, in configuration order, with defaults."""
    monkeypatch.setattr(doctor_mod, "_check_source", _fast_check_source)
    _patch_env_and_config(monkeypatch)
    monkeypatch.delenv("AUTOINFO_DOCTOR_SOURCE_TIMEOUT", raising=False)
    monkeypatch.delenv("AUTOINFO_DOCTOR_TOTAL_TIMEOUT", raising=False)

    results = run_doctor()

    sources = results["sources"]
    assert [entry["name"] for entry in sources] == [f"src{i}" for i in range(5)]
    assert all(entry["status"] == "ok" for entry in sources)
