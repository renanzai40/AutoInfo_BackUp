"""Issue #352.3 — fault injection harness for the product-generation seams.

A dev/test-only mechanism that forces LLM failure / timeout / truncation /
malformed-JSON / empty responses at the four product-generation seams so the
validation system can actively verify that the guards and deterministic
fallbacks fire correctly (previously such failures were only caught when
12-way concurrency coincidentally triggered them — #328).

Reads the ``AUTOINFO_FAULT_INJECT`` environment variable.  Never enabled in
production: when the variable is unset (the default) every hook is a no-op
and the seams behave byte-for-byte as before.

The variable accepts either a single kind (applied to every scope):

    AUTOINFO_FAULT_INJECT=fail

or comma-separated ``scope:kind`` pairs (applied per scope):

    AUTOINFO_FAULT_INJECT=digest:malformed_json,report:fail

Kinds
-----
- ``fail``          — :func:`maybe_fault` raises :class:`ConnectionError`.
- ``timeout``       — :func:`maybe_fault` raises :class:`TimeoutError`.
- ``truncate``      — :func:`maybe_fault_content` cuts *content* mid-JSON.
- ``malformed_json``— :func:`maybe_fault_content` returns a non-JSON string.
- ``empty``         — :func:`maybe_fault_content` returns ``""``.

Every seam calls the two helpers through the module-level names
(``fault_inject.maybe_fault`` / ``fault_inject.maybe_fault_content``) so
tests can patch them directly; the helpers keep the injection logic
centralized here.
"""

from __future__ import annotations

import os
from typing import Final

ENV_VAR: Final[str] = "AUTOINFO_FAULT_INJECT"

_SCOPES: Final[frozenset[str]] = frozenset(
    {"digest", "group", "summary", "report"}
)
_KINDS: Final[frozenset[str]] = frozenset(
    {"fail", "timeout", "truncate", "malformed_json", "empty"}
)


def _parse_config(value: str) -> dict[str, str]:
    """Parse the ``AUTOINFO_FAULT_INJECT`` value into a ``{scope: kind}`` map.

    A bare kind applies to every scope; ``scope:kind`` pairs apply per
    scope.  Unknown scopes/kinds are ignored (never raise), so an
    environment typo degrades to no fault rather than a crash.
    """
    config: dict[str, str] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            scope, kind = part.split(":", 1)
            scope = scope.strip()
            kind = kind.strip()
            if scope in _SCOPES and kind in _KINDS:
                config[scope] = kind
        elif part in _KINDS:
            for scope in _SCOPES:
                config[scope] = part
    return config


def _fault_kind_for(scope: str) -> str:
    """Return the configured fault kind for *scope* (``""`` when unset)."""
    value = os.environ.get(ENV_VAR, "")
    if not value:
        return ""
    return _parse_config(value).get(scope, "")


def maybe_fault(scope: str) -> None:
    """Raise the configured failure for *scope* (no-op when unset).

    ``fail`` raises :class:`ConnectionError`; ``timeout`` raises
    :class:`TimeoutError`; the content kinds are handled by
    :func:`maybe_fault_content` and do nothing here.
    """
    kind = _fault_kind_for(scope)
    if kind == "fail":
        raise ConnectionError(
            "FAULT_INJECT[fail]: injected connection failure at seam "
            f"'{scope}' — the caller must fall back deterministically"
        )
    if kind == "timeout":
        raise TimeoutError(
            "FAULT_INJECT[timeout]: injected timeout at seam "
            f"'{scope}' — the caller must fall back deterministically"
        )


def maybe_fault_content(scope: str, content: str) -> str:
    """Poison *content* with the configured fault for *scope*.

    ``truncate`` cuts the content halfway through (mid-JSON);
    ``malformed_json`` replaces it with a non-JSON string; ``empty``
    returns ``""``.  Any other kind (or an unset env var) returns
    *content* unchanged.
    """
    kind = _fault_kind_for(scope)
    if kind == "truncate":
        if len(content) > 4:
            return content[: len(content) // 2]
        return content[:1]
    if kind == "malformed_json":
        return "{not valid json"
    if kind == "empty":
        return ""
    return content
