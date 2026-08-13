<!-- doc-type: adr -->
# 0004. Reasoning models: never send `response_format`, disable thinking by default

- **Status**: Accepted
- **Date**: 2026-08-13 (commits `c33c6d0`, `02a06a8`)
- **Author**: Agent (Sisyphus)

## Context

Switching the default LLM to a reasoning model (DeepSeek R1/V4 style) broke
every structured-output call: JSON extraction, gate judgments, and output
generation returned truncated or empty results with `finish_reason=length`.
Root cause: reasoning models consume the shared `max_tokens` budget **on
thinking before any content is generated** — with CoT enabled, the token
budget is exhausted by reasoning, truncating the JSON payload. Additionally,
reasoning providers outright reject the `response_format={"type":"json_object"}`
parameter (`BadRequest`), so `json_mode` could not be sent at all.

## Decision

When `reasoning_model: True` in LLM config: (1) **`response_format` is always
skipped** — never send it, regardless of `json_mode`; (2) **chain-of-thought is
disabled by default** via `additional_body={"thinking":{"type":"disabled"}}`.
Judgment gates (G4 factual, G5 translation, `llm_judge`, translation-QA judge,
validation-scenario judge) **re-enable thinking** with a raised `max_tokens`
(`disable_thinking=False`), because their verdict quality depends on reasoning
and they are not token-budget-capped the same way.

## Alternatives considered

- **Just raise `max_tokens`**: rejected — reasoning still consumes a
  proportional share; token cost grows linearly with the fixed overhead, and
  long outputs keep truncating.
- **Exclude reasoning models from JSON tasks**: rejected — they are the best
  extraction quality we have; the fix is to control the inference budget, not
  to avoid the model.
- **Parse partial JSON from truncated output**: rejected — fragile, loses
  fields silently, and violates the G0 (schema integrity) hard-gate spirit.

## Consequences

- Structured JSON output from reasoning models is deterministic and
  truncation-free; `json_mode` parameter semantics are now model-class-aware.
- Judgment gates keep full reasoning power where it matters, at a predictable
  cost premium (documented per-call-site).
- Any future model that is *not* reasoning-class must keep `reasoning_model`
  off or it will silently change thinking behavior — the flag is a
  per-configuration contract.