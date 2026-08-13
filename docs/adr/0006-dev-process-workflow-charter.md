<!-- doc-type: adr -->
# 0006. Adopt the 7-stage agent-driven development workflow

- **Status**: Accepted
- **Date**: 2026-08-13
- **Author**: Agent (Sisyphus), directed by B3

## Context

AutoInfo is developed **agent-first**: a human director communicates intent in
natural language, an agent translates it into tool calls and implements.
Without an explicit development process, sessions drift — each agent improvises
its own order of operations, and the *process* knowledge (grilling → PRD →
issues → AFK → review) never becomes a durable, queryable asset.

The founding workflow originally lived in an **external, machine-specific
location** (`D:\贯维\Vibe\...`) — invisible to any agent session that starts
from this repo. On 2026-08-13 the canonical methodology was copied **in-repo**
as `docs/dev/七阶段AI开发流程-用CodingAgent交付成品的方法论.md` (KB-derived,
phase: wiki, Chinese), so the repo is now self-sufficient.

## Decision

Adopt the 7-stage development workflow (grilling → research → prototyping →
PRD → issue breakdown → AFK implementation → review/backfill) plus its three
support methods (Grill with Docs, Deep Modules, AX-first) as AutoInfo's
development process, and **institutionalize it inside the repo**:

- `docs/dev/七阶段AI开发流程-用CodingAgent交付成品的方法论.md` — the canonical
  methodology, now in-repo (authoritative source; the external vault doc is
  its upstream origin).
- `docs/dev/workflow-charter.md` — the distilled English operating index
  (7 stages with artifact mapping, 3 support methods, nonlinearity warning,
  in-repo vs runtime artifact split).
- The practice is encoded in `.opencode/skills/` — `doc-manager-skill`
  (documentation governance), `validation-runner-skill` (validation flywheel),
  `deep-modules-skill` (code structure) — so agents load process as skills,
  not as prose.

The workflow is **nonlinear**: stages are a mental model, not a checklist.
Small changes skip most stages; the rule that always holds is the stage-7
backfill: *any lesson that would help the next iteration must land in an
in-repo durable artifact* (ADR, glossary term, spec change, quality gate, or
skill).

## Alternatives considered

- **Keep the process only in the external vault**: rejected — machine-specific
  path, invisible to repo-starting agent sessions; contradicts AX-first (the
  agent must be able to self-orient from the repo). Resolution: the canonical
  methodology itself was copied in-repo (2026-08-13), vault remains upstream.
- **Rely only on the distilled charter, without the full methodology in-repo**:
  rejected — the charter is an operating index, not the source of the
  methodology's reasoning; agents needing the full 7-stage detail (course
  observations, anti-patterns) must read the canonical doc. Both live in-repo:
  methodology (canonical) + charter (index).
- **Encode process only in AGENTS.md**: rejected — AGENTS.md is the operational
  rulebook, not the process narrative; skills are the right carrier for
  loadable practice (they activate on demand, not at every session).

## Consequences

- **Easier**: new sessions self-orient on process; the stage-7 backfill loop
  has a home; skills are discoverable as loadable practice; the repo is
  self-sufficient (no dependency on a machine-specific vault path).
- **Harder**: now three sources of truth must stay in sync — the canonical
  methodology, the distilled charter, and the upstream vault. The charter and
  the methodology's structure must be updated together whenever the workflow
  changes (detected via doc-manager-skill change workflow).
- **Follow-up obligations**: when the methodology next changes, re-run the
  comparison and update the charter + affected skills (as done 2026-08-13
  for deep-modules-skill v1.1.0).
