<!-- doc-type: adr -->
# 0005. Unified `{success, data}` / `{success, error}` envelope

- **Status**: Accepted
- **Date**: 2026-08-05 (v1.9, breaking change; migration documented in `docs/archive/migration-v1.9.md`)
- **Author**: Agent (Sisyphus) + Director (B3)

## Context

AutoInfo exposes three surfaces: MCP tools (agent-facing), REST API
(human/agent HTTP), and CLI. Early on, MCP tools returned flat structs and
REST returned raw JSON with opaque error bodies — an LLM agent had to guess
whether a response was data or an error, and error messages carried no
remediation hint. `LLM_NOT_CONFIGURED` surfaced as raw auth errors at the
call site instead of being a first-class signal. The agent-native model (B2)
made unambiguous envelopes a correctness requirement, not a nicety.

## Decision

Every MCP tool and REST endpoint returns the **same envelope**:

- Success: `{success: true, data: ...}`
- Failure: `{success: false, error: {code, message, actionable}}`

`error.code` comes from the `ErrorCode` enum (28 values); `message` carries the
remediation guidance; `actionable` flags that a hint exists. The LLM guard
centralizes `LLM_NOT_CONFIGURED` at `call_tool` dispatch. `error_dict()` is
deprecated. Dashboard JS unwraps the envelope transparently.

## Alternatives considered

- **Keep flat success + ad-hoc error bodies**: rejected — LLM consumers cannot
  reliably distinguish data from errors; the whole point of agent-native is a
  parseable contract.
- **Error codes only (no message)**: rejected — machine codes without
  human/agent-readable remediation guidance fail the `actionable` goal that
  makes the envelope self-healing.
- **HTTP status codes as the only signal (REST-only)**: rejected — MCP has no
  HTTP, and the two surfaces must share one contract per the CLI/MCP/REST
  parity principle.

## Consequences

- One parse rule for all consumers: read `success`, branch on `data`/`error`.
- All 146 MCP tools and all REST endpoints follow the same schema (validated
  by validation scenarios asserting `{success, data}`); validation
  error-boundary scenarios assert `actionable` presence.
- Breaking change for v1.8 consumers — migration path documented and shipped
  with the v1.9 archive note (dashboard unwrapping transparent).