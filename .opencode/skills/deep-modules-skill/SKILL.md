---
name: deep-modules-skill
description: AutoInfo deep-module refactoring practice (from the 七阶段 methodology, Ousterhout's Philosophy of Software Design). Load when refactoring src/autoinfo/, adding a feature that crosses multiple modules, or reviewing module shape — find shallow module clusters, merge into deep modules, lock behavior with module-boundary integration tests.
author: AutoInfo
version: 1.0.0
---

# AutoInfo Deep Modules Skill

> **Deep module** = small public interface + large hidden implementation
> (John Ousterhout). Agents cannot "remember" the codebase — every session
> rebuilds the map. Deep modules let an agent read the interface and navigate
> without tracing import/export chains. Shallow modules (interface ≈
> implementation, lots of thin glue) make agents get lost and make changes
> accidentally break structure.

## When to load

- Refactoring `src/autoinfo/` — especially merging "small, scattered, coupled"
  module groups.
- Adding a feature that touches 2+ existing modules (check whether the new
  code should be one deep module instead of three thin ones).
- Reviewing module shape before a large change (the AX-first lens: module
  shape IS agent experience).
- Writing the module-sketch section of a plan/PRD.

## Procedure

1. **Map the interface surface.** For each candidate module: public API
   (functions/classes/tools exposed) vs implementation size. AutoInfo's
   interface truth lives in `docs/dev/specs/mcp-tools.md` (145 tools),
   `docs/dev/specs/data-models.md` (schemas), and `AGENTS.md` Project
   Structure. If a module's *interface* is as complex as its *implementation*,
   it is shallow.
2. **Find shallow clusters.** Look for: thin pass-through modules (import →
   re-export), groups of small coupled helpers split across files, modules
   whose only job is glue between two real modules. AutoInfo watch-list:
   `cli/` (28 groups mirroring MCP — a deliberately thin adapter layer, keep
   it thin *by design*), `collectors/` (30 handlers sharing a protocol —
   consolidate shared plumbing, not handlers), `output/` (subpackage: digest/
   report/ebook/video share templates + rendering — look for duplicated
   render/synthesis helpers).
3. **Merge into deep modules.** Combine the cluster behind ONE small interface.
   Good AutoInfo exemplars already deep: `kb.py`, `llm.py`, `quality.py`,
   `delivery.py`, `promotion.py` — small public functions over large logic.
4. **Lock behavior at the module boundary.** Write **integration tests that
   exercise the module's public interface** (input → observable output/effect),
   NOT unit tests per merged internal function. The MCP/CLI tool surface is the
   ultimate boundary test: a tool call asserting on `{success, data}`.
5. **Verify + sync.** Full test suite green (`make test`), `lsp_diagnostics`
   clean on changed files, then the doc layer: if the public interface changed,
   update `docs/dev/specs/data-models.md` / `mcp-tools.md` and regenerate the
   doc inventory (`python3 scripts/doc_inventory.py --check`).

## Guardrails

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