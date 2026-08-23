<!-- doc-type: adr-index -->
# Architecture Decision Records (ADR)

> **Why**: Code + commit history cannot answer *"why did we do it this way?"* or
> *"what trade-offs were considered?"*. ADRs record those decisions so agents
> and humans can reconstruct the reasoning without re-litigating it. They are
> the durable output of grilling/design sessions and the evidence trail for
> architecture rules in `AGENTS.md` and the specs.

## When to write an ADR

Write one for any decision that:

- Changes an **architecture rule** (KB pipeline, collection pipeline, quality gates, delivery)
- Introduces a **non-obvious trade-off** that code alone does not explain
- Chooses between **two or more viable alternatives** (the losers deserve recording too)
- Has a **wide blast radius** (MCP surface, REST envelope, storage schema, LLM call paths)
- Later decisions would **re-open without a record**

Small, reversible choices do **not** need an ADR — a code comment suffices.

## How to write one

1. Copy `docs/adr/TEMPLATE.md` to `docs/adr/NNNN-kebab-slug.md` (next free number).
2. Fill **Context** (the situation), **Decision** (what we chose), and
   **Alternatives considered** (each with why it was rejected).
3. Set `Status` to `Accepted`, `Proposed`, or `Superseded by NNNN`.
4. Link it from the docs that encode the rule (`AGENTS.md`, specs) where helpful.
5. Regenerate the doc inventory: `python3 scripts/doc_inventory.py` + `--check`.

ADRs are **append-only in spirit**: never rewrite history inside an accepted ADR —
if the decision changes, write a new ADR and mark the old one `Superseded by NNNN`.

## Relationship to other docs

| Doc | Answers |
|-----|---------|
| `docs/adr/` (this directory) | **Why** — decisions and rejected alternatives |
| `docs/dev/specs/` | **What/How** — ratified behavior, derived from founders' expectations |
| `docs/glossary.md` | **Language** — the project's Ubiquitous Language (business terms) |
| `AGENTS.md` Architecture Rules | **Rules** — the operational musts agents must obey |

## Index

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-kb-pipeline-raw-sole-entry.md) | 01-Raw is the sole entry point for all collected content | Accepted |
| [0002](0002-draft-to-wiki-agent-promotion.md) | Agent promotes Draft→Wiki with no human gate (2026-08-08) | Accepted |
| [0003](0003-llm-fallback-chain.md) | LLM `call_with_fallback` — primary + ordered fallback walk | Accepted |
| [0004](0004-reasoning-model-json-mode-thinking.md) | Reasoning models: never send `response_format`, disable thinking by default | Accepted |
| [0005](0005-unified-success-error-envelope.md) | Unified `{success, data}` / `{success, error{code,message,actionable}}` envelope (v1.9) | Accepted |
| [0006](0006-dev-process-workflow-charter.md) | Adopt the 7-stage agent-driven development workflow (2026-08-13) | Accepted |
| [0007](0007-release-please-version-truth.md) | release-please owns version truth (2026-08-15) | Accepted |