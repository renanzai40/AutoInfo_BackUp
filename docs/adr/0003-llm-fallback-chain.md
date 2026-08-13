<!-- doc-type: adr -->
# 0003. LLM fallback chain — primary + ordered fallback walk

- **Status**: Accepted
- **Date**: 2026-08-09 (extended to every LLM call site; per-provider rate limiting 2026-08-13)
- **Author**: Agent (Sisyphus) + Director (B3)

## Context

Every LLM call path — extraction, validation judge, quality gates G4/G5,
translation QA, output generation, keyword suggest, Q&A, CEFR — depends on a
single provider. A provider outage, 429 rate limit, or 5xx degradation took
down the whole pipeline. Retrying the same provider is useless when the
failure domain is the provider itself. Early design had fallback only for
extraction; the other ~17 standalone call sites ran raw.

## Decision

**Shared `llm.call_with_fallback` walks `[primary] + config.llm.fallback` in
order; the first successful model wins.** The fallback list is configurable
(`llm.fallback` in `.autoinfo/config.yaml`), each entry carrying
provider/model and optional `base_url`/`api_key`. Every LLM call site uses the
shared helper — none may call a provider directly (this is enforced by review,
and per-provider rate limiting + jittered backoff for 429/5xx protect the
primary leg).

## Alternatives considered

- **Single provider, retry-only**: rejected — same failure domain; a provider
  outage is not survivable, and naive retries amplify rate-limit pressure.
- **Fallback only for extraction**: rejected — quality gates and output
  generation are equally critical; a mid-pipeline provider failure still
  blocks delivery (D1/D2 gate philosophy).
- **Parallel fan-out (call all, take first success)**: rejected — token cost
  multiplier and non-deterministic behavior; ordered walk keeps cost
  predictable and model quality preferences explicit.

## Consequences

- Pipeline survives provider degradation; `LLM_NOT_CONFIGURED` still surfaces
  when no key is present (via the LLM guard, before any call).
- Cost is bounded by the ordered list — cheapest/primary model is first.
- All error paths aggregate: the surfaced error is the last failure, not a
  random one, which keeps diagnostics deterministic.