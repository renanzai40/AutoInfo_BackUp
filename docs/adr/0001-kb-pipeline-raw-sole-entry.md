<!-- doc-type: adr -->
# 0001. 01-Raw is the sole entry point for all collected content

- **Status**: Accepted
- **Date**: 2026-07 (operating since the 4-tier pipeline; formally ratified during the 2026-08-08 kb-curation wave)
- **Author**: Director (B3)

## Context

The KB pipeline has four tiers: 00-Inbox → 01-Raw → 02-Draft → 03-Wiki. Early
design scaffolded 00-Inbox as a landing zone. But AutoInfo is an
agent-operated production pipeline (agent as direct user, maximal automation):
every collected item is processed by LLM extraction and quality gates before it
becomes knowledge. If content could skip or enter at a higher tier, provenance
would silently degrade — an item could reach Wiki without ever having passed a
gate, breaking auditability and the reliability contract.

## Decision

**01-Raw is the sole entry point.** Every collected item must land in 01-Raw
with complete source provenance (`source_url`, `source_type`,
`source_platform`). 00-Inbox is deprecated (scaffolded but unused). The path
Raw → Draft → Wiki is sequential and unskippable — an agent cannot create a
Draft from outside, only from a 01-Raw entry.

## Alternatives considered

- **00-Inbox as the landing tier**: rejected — it duplicated provenance
  bookkeeping, risked entries bypassing gates, and added a tier with no
  behavioral value.
- **Direct ingest to 02-Draft/Wiki**: rejected — garbage-in-garbage-out;
  Draft/Wiki must only contain content that passed extraction and quality gates.
- **Ad-hoc KB entry at any tier with a flag**: rejected — makes every consumer
  (search, digest, export) reason about provenance per entry instead of once.

## Consequences

- Search, digests, and exports can trust tier placement without per-entry checks.
- Import (`import_kb`) and webhook/email/PDF ingestion all funnel through 01-Raw.
- 00-Inbox remains in scaffolding only; removing it entirely is deferred to
  avoid churn in KB tooling name references (`list_kb_tier` still lists it).