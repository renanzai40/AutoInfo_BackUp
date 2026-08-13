<!-- doc-type: workflow-charter -->
# AutoInfo Development Workflow Charter

> **Why this doc exists**: AutoInfo is developed agent-first — but a new agent
> session cannot know the *process* from the repo alone. The canonical
> methodology lives **in-repo**: `docs/dev/七阶段AI开发流程-用CodingAgent交付成品的方法论.md`
> (7-stage, Chinese, KB-derived — the authoritative source). This charter is the
> distilled English operating index so every session (and every future agent)
> can operate the workflow without re-reading the full methodology. ADR-0006
> records the adoption decision.

## The workflow: 7 stages + 3 support methods

The methodology is **nonlinear** — "you are totally free to do these in a
different order." The stages are a *mental model of the work*, not a checklist
to grind through linearly. A small change may only touch stages 5-7; a new
domain feature may loop 2-4 several times.

### The 7 stages

| # | Stage | Durable artifact (in-repo) | Process artifact (runtime) |
|---|-------|---------------------------|---------------------------|
| 1 | Grilling (需求拷问) | `docs/adr/` (decisions) | `.omo/notepads/` |
| 2 | Research (研究) | `docs/dev/research/`, `docs/archive/` | `.omo/notepads/` |
| 3 | Prototyping (原型) | validation scenarios (`src/autoinfo/mcp/scenarios/`) | `.omo/` scratch |
| 4 | PRD (需求规格) | `docs/dev/specs/` (expectations, pipeline, delivery, ...) | `.omo/plans/` |
| 5 | Issue breakdown (拆解) | GitHub issues + Kanban (blocking links) | `.omo/plans/` → **promote major waves** to `docs/dev/plans/` |
| 6 | AFK implementation (实现) | `src/` + `tests/` (commit per issue) | — |
| 7 | Review → next product (复盘) | acceptance runs (`docs/dev/validation-reports/`), `docs/glossary.md`, skills (`.opencode/skills/`) | `.omo/evidence/` |

Stage-7 rule: **whatever was learned that would help the next iteration is
back-filled** — an ADR, a glossary term, a quality gate, or a skill. The
"文档组成完备" answer to that stage is: ADR (why) + specs (what) + glossary
(language) + skills (how to work) + acceptance reports (proof).

### The 3 support methods

1. **Grill with Docs (文档化拷问)** — every design question ends in an ADR
   decision; every ADR must record rejected alternatives. The doc layer IS the
   answer to "why did we do this?" — see `docs/adr/README.md`.
2. **Deep Modules (深模块)** — small public interface, large hidden
   implementation (Ousterhout). Agents rebuild the code map every session;
   deep modules let them navigate via interface. Practice:
   `.opencode/skills/deep-modules-skill/SKILL.md` (v1.1.0: 5-step procedure,
   testability-extraction trap guardrail).
3. **AX-first (Agent Experience 优先)** — the agent is a first-class user.
   Every capability is an MCP tool; every agent-facing contract is enforced
   (parity matrix, error envelope ADR-0005, `AGENTS.md` constraints, validation
   flywheel). Practice: `.opencode/skills/validation-runner-skill/SKILL.md`.

## Where artifacts live

- **In-repo (durable, source of truth)**: `docs/` (specs, ADR, glossary,
  acceptance), `.opencode/skills/` (process practice), `src/` + `tests/`.
- **Runtime (gitignored, process-only)**: `.omo/plans/`, `.omo/notepads/`,
  `.omo/evidence/` — wave-level planning is intentionally ephemeral; value
  must be distilled into in-repo artifacts (per stage-7 rule).

## Relationship to other docs

| Doc | Answers |
|-----|---------|
| `docs/adr/0006-dev-process-workflow-charter.md` | **Why** this workflow was adopted |
| `docs/glossary.md` | **Language** — Ubiquitous Language of the project |
| `docs/dev/acceptance-framework.md` | **Proof** — acceptance charter (AC1-AC9) |
| `.opencode/skills/*/SKILL.md` | **How** — the practiced process (doc-manager, validation-runner, deep-modules) |
| `AGENTS.md` | **Rules** — operational musts for agents |
