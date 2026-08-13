---
name: deep-modules-skill
description: AutoInfo deep-module refactoring practice (from the 七阶段 methodology, Ousterhout's Philosophy of Software Design). Load when refactoring src/autoinfo/, adding a feature that crosses multiple modules, or reviewing module shape — find shallow module clusters, merge into deep modules, lock behavior with module-boundary integration tests.
author: AutoInfo
version: 1.1.0
---

# AutoInfo Deep Modules Skill

> **Deep module** = small public interface + large hidden implementation
> (John Ousterhout). Agents cannot "remember" the codebase — every session
> rebuilds the map. Deep modules let an agent read the interface and navigate
> without tracing import/export chains. Shallow modules (interface ≈
> implementation, lots of thin glue) make agents get lost and make changes
> accidentally break structure.
>
> **Why now (human side)**: in the AI era the human's cognitive load is
> *rising* — the agent changes code constantly, so the "internal code map"
> you maintain in your head keeps invalidating. Any strategy that lowers
> cognitive load improves your AI experience directly. Deep modules are such
> a strategy: remember the interface, not the implementation map.

## When to load

- Refactoring `src/autoinfo/` — especially merging "small, scattered, coupled"
  module groups.
- Adding a feature that touches 2+ existing modules (check whether the new
  code should be one deep module instead of three thin ones).
- Reviewing module shape before a large change (the AX-first lens: module
  shape IS agent experience).
- Writing the module-sketch section of a plan/PRD.

## Procedure

Aligned with the methodology's 5-step "improved code-base architecture"
(预防: PRD-stage module sketch — new code starts deep; 治疗: this procedure —
fix existing bad modules):

1. **Explore for friction points** (explore mode, targeted area or full-library
   scan). Record: how many small files must you jump to understand one concept?
   Which modules have interface ≈ implementation (shallow)? Which pure
   functions were extracted "for testability" but the bug lives at the call
   site? Which coupled modules carry integration risk?
2. **List candidates WITHOUT designing interfaces.** Circle clusters that
   *share a concept and are coupled*. Do not design interfaces yet — that comes
   after the user picks.
3. **User selects one candidate** (B3 decides).
4. **Parallel divergent interface design.** Spawn multiple subagents to
   independently produce **maximally divergent** interface proposals — diversity
   is the point (you can mix the best parts later). The convergence is a human
   judgment call, not a merge of the first two.
5. **Recommend / mix → refactor RFC.** Land the chosen interface as a GitHub
   issue/RFC → Kanban breakdown with blocking links (methodology stage 5: one
   issue = one verifiable commit).
6. **Merge into the deep module.** Combine the cluster behind ONE small
   interface. AutoInfo's interface truth: `docs/dev/specs/mcp-tools.md` (145
   tools), `docs/dev/specs/data-models.md` (schemas), `AGENTS.md` Project
   Structure. Watch-list: `cli/` (28 groups mirroring MCP — deliberately thin
   adapter layer, keep thin *by design*), `collectors/` (30 handlers sharing a
   protocol — consolidate shared plumbing, not handlers), `output/` (subpackage:
   digest/report/ebook/video share templates + rendering — look for duplicated
   render/synthesis helpers). Good exemplars already deep: `kb.py`, `llm.py`,
   `quality.py`, `delivery.py`, `promotion.py` — small public functions over
   large logic.
7. **Lock behavior at the module boundary + verify + sync.** Integration tests
   exercising the module's public interface (input → observable output/effect),
   NOT unit tests per merged internal function. The MCP/CLI tool surface is the
   ultimate boundary test: a tool call asserting on `{success, data}`. Then:
   full suite green (`make test`), `lsp_diagnostics` clean, doc layer synced
   (`data-models.md` / `mcp-tools.md` if the interface changed) + inventory
   (`python3 scripts/doc_inventory.py --check`).

## Guardrails

- **⚠️ The testability-extraction trap (LLM's most common bad refactor).**
  LLMs habitually say "let's extract this so it's testable" and pull out a
  pure function — but the real bug usually lives at the **call site** (how the
  frontend calls the backend, how the backend calls the CLI). Extracted small
  functions are shallow modules; the tests then lock the *shape*, not the
  *behavior*. Detection heuristic: **if after extraction you still need a pile
  of mocks to test it, you extracted wrong** — the direction should be the
  opposite: wrap the whole flow into one big service (a deep module), not peel
  off a testable fragment.
- **Never merge for merging's sake.** A module is shallow only if its
  interface fails to hide complexity from callers. Small single-responsibility
  modules that are easy to navigate are fine — the pathology is *scattered,
  coupled, thin* clusters.
- **Preserve the public contract.** `cli/` and `mcp/` surface shapes are
  parity-bound (`docs/dev/cli-mcp-rest-parity.md`) — internal merges must not
  change tool names, parameters, or the error envelope (ADR-0005).
- **Tests first for refactors** (characterization): pin current observable
  behavior with boundary tests BEFORE merging; keep them green throughout.
- **Deep-module tests prefer the boundary**, not internals — per the
  methodology, read tests instead of implementations (gray-box view).

## Relationship to other skills

- `doc-manager-skill` — after any refactor that changes a documented interface,
  follow its code-to-doc dependency map (§2).
- `validation-runner-skill` — add/update an integration scenario when the
  merge changes observable behavior (regression flywheel).