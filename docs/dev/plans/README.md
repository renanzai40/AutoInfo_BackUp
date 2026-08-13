<!-- doc-type: plan-index -->
# Wave Plan Archive (docs/dev/plans/)

> **What this is**: the durable home for **major-wave** development plans.
> Per ADR-0006 + the workflow charter, wave-level planning normally lives in
> the gitignored orchestrator workspace (`.omo/plans/`) — ephemeral by design.
> **Major waves promote here on completion** (or on interruption, so a future
> session can resume them). This directory is the "PRD → durable" destination
> for the methodology's stage 4-5 artifacts.

## When a wave is "major" (promotion criteria)

Promote a wave plan to this directory when ANY of these holds:

1. **Cross-module blast radius** — the wave touches 2+ modules (e.g. a change
   spanning `collectors/` and `mcp/`, or `cli/` and `output/`).
2. **Public interface change** — MCP tool surface, CLI command groups, REST
   envelope, storage schema, or LLM call paths that other code depends on.
3. **Multi-session work** — the wave is expected to span multiple agent
   sessions (high interruption risk; the decomposition must be reconstructable).

Small single-module waves stay in `.omo/plans/` — their value is distilled into
the ADR + CHANGELOG when done (stage-7 backfill), and promoting them adds noise.

## How to promote

1. Copy the finished plan from `.omo/plans/<wave>.md` to
   `docs/dev/plans/<wave>.md` (kebab-case, dated prefix optional).
2. Add the `<!-- doc-type: plan -->` marker to the head.
3. Append a short **Outcome** section: what shipped (commits/PR refs), what
   changed vs the plan, and which lessons backfilled where (ADR/skill/glossary).
4. If the wave was interrupted instead of finished: keep the plan as-is but
   mark clearly in the front matter (`<!-- status: interrupted -->`) and list
   the next un-done step at the top.
5. Regenerate the doc inventory: `python3 scripts/doc_inventory.py` + `--check`
   (must exit 0).

## Relationship to other docs

| Doc | Answers |
|-----|---------|
| `docs/dev/workflow-charter.md` | The 7-stage process; where each stage's artifacts land |
| `docs/adr/0006-dev-process-workflow-charter.md` | Why this workflow was adopted |
| `.omo/plans/` | Runtime scratch for all waves (gitignored) — the un-promoted majority |

## Archive

| Wave | Type | Outcome | Status |
|------|------|---------|--------|
| *(none yet)* | | | |