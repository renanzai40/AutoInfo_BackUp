<!-- doc-type: adr -->
# 0002. Agent promotes Draft→Wiki with no human gate

- **Status**: Accepted
- **Date**: 2026-08-08 (director decision; commits `b2b0d0e`, `f2e3b04`, `34c10d7`)
- **Author**: Director (B3)

## Context

AutoInfo's KB is a **database for raw/processed data production**, not a
human-curated knowledge base. The agent is the direct user (B2) and operates
on behalf of the human director (B3). Draft→Wiki promotion is a production
step that happens continuously. An early assumption was that a human should
approve promotions ("safety"). But every human gate in the pipeline becomes a
throughput throttle: the director would be required for each entry, crippling
agent-driven production and recreating the "monitor chat loop" that
goal-programming/AFK workflows exist to eliminate.

## Decision

**`promote_kb_draft` is an agent operation with no human approve step.**
Admission is enforced by an automated gate (`check_promotion_admission`:
provenance + quality gates G0/G1/G3/G4) and `promotion_source=agent` is pinned
on every promoted entry. 03-Wiki is **append-only**: the agent cannot demote or
delete Wiki entries; deprecation (tag `status: deprecated`) happens only on
explicit human command.

## Alternatives considered

- **Human approve step before promotion**: rejected (2026-08-08 director
  decision) — cripples production throughput; agent-as-user model does not
  scale with a synchronous human gate.
- **Agent full CRUD on Wiki (incl. demote/delete)**: rejected — append-only
  integrity is the trust anchor for consumers; the cost of a bad deletion
  outweighs the convenience.
- **Machine-pass with rate limit on promotions**: rejected — adds operational
  complexity without protecting the actual invariant (admission quality).

## Consequences

- Promotion is high-throughput and unattended; admission quality is carried by
  the automated gates, not by a human reviewer.
- Wiki entries are immutable via agent paths — any correction flows through a
  new Draft→Wiki cycle or an explicit human deprecation command.
- `promotion_source`/`promoted_by` fields make every promoted entry auditable
  back to the promoting agent.