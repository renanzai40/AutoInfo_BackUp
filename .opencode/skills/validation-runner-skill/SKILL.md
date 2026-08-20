---
name: validation-runner-skill
description: AutoInfo dev-side validation workflow — run scenario waves, author regression scenarios, capture RED→GREEN evidence, produce acceptance reports. Load whenever fixing a bug (must ship a regression scenario), adding/authoring validation scenarios, running an acceptance wave, or preparing validation-reports evidence.
author: AutoInfo
version: 1.0.0
---

# AutoInfo Validation Runner Skill

The QA loop for developing AutoInfo. Canonical depth lives in
`docs/dev/validation-scenario-contract.md` (Part 1 = scenario authoring
contract, Part 2 = full-coverage agent-tester runbook, 768 lines) and
`docs/dev/acceptance-framework.md` (AC1-AC9 grading authority). This skill is
the loadable procedure — read the contract doc when authoring scenarios.

## When to load

- **Fixing a bug** → must produce a regression scenario (mandatory 回归场景
  field in `.github/ISSUE_TEMPLATE/bug_report.md`) + RED→GREEN evidence.
- **Feature wave done** → run the affected scenario group before declaring done.
- **Authoring a new scenario** → follow Part 1 contract, drop YAML into
  `src/autoinfo/mcp/scenarios/` (regression ones into `scenarios/regression/`
  with `category: regression` + `regression: true` keys; recursive glob
  auto-loads them).
- **Acceptance run** → produce `docs/dev/validation-reports/acceptance-*.md`.

## Scenario library (108 = 64 functional + 44 regression)

Functional (`src/autoinfo/mcp/scenarios/*.yaml`): system-health, discovery,
domain-management, source-management, topic-management, keyword-management,
collection, collectors-e2e, collection-monitor, collect-failure-recovery,
processing, kb-access, kb-draft, kb-promote, kb-promote-admission,
promotion-provenance, promotion-triggers, director-backdoor, kb-extraction,
kb-graph, kb-import-export, kb-lifecycle, kb-versioning, search-tier-boost,
kb-curation (as kb-* group), cli-core, cli-content, cli-extra, cli-llm,
cli-ops, rest-api, error-boundary, meta-validation, output-digest-report,
output-column, output-premium-products, output-ebook, output-video,
output-tutorial-presentation, output-simplify-recommend, output-agent-interaction,
output-discovery, delivery-channels, delivery-schedules, cron-schedules,
webhooks-alerts, agent-callbacks, enduser-journey, enduser-lifecycle,
enduser-preferences, products-billing, projects-config, cost-budget,
data-privacy, data-lifecycle-e2e, llm-gated, llm-failure-recovery,
observability, quality-gate-config, curated-priority-consumption,
sources-coverage, sources-a6-keyed, sources-gap-closure, … (64 total — run `list_validation_scenarios()` for the live list).

Regression (`src/autoinfo/mcp/scenarios/regression/`, `regression: true` key):
collect-int-id (#104), llm-key-resolution (#119), period-enum (#126),
report-structure (#121), source-301 (#135), regression-product-routing,
regression-financial-sources (#288), regression-290-init-fallback (#290),
regression-291-demo-merge (#291), regression-292-web-ua (#292),
regression-293-test-entry-filter (#293), regression-294-empty-summary (#294),
regression-295-db-lock (#295), regression-296-multi-source (#296),
regression-297-audience-validation (#297), regression-297-preview-fallback (#10),
regression-298-delivery-gates (#298), regression-301-bundle-nonempty (#301),
regression-302-render-defects (#302), regression-303-empty-shell-notes (#303),
regression-report-theme-titles (#311), regression-tutorial-citations (#312),
regression-magazine-editorial (#313), regression-enterprise-coverage (#314),
regression-column-sections (#316), regression-domain-language-default (#317),
regression-product-h1-titles (#318), regression-crossdomain-noise-filter (#319),
regression-references-numbering (#322), regression-source-label-rss (#323),
regression-enterprise-skeleton (#314), regression-source-label-nondigest (#325),
regression-sections-real-path (#326), regression-error-leak-header (#328),
regression-premium-takeaway-placeholders (#329), regression-validation-matrix (#331),
regression-collection-noise-guard (#332).
(38 total — run `list_validation_scenarios()` for the live list).

## Execution discipline

1. **Real surface, no mock** (principle P3): every step makes a real MCP/CLI/REST
   call and asserts on the `{success, data}` envelope; `llm_assert` steps run a
   real model call. Env-gated steps report `unconfigured` — **never** a pass.
2. **RED→GREEN**: capture the honest failing state BEFORE the fix (call fails /
   `unconfigured` / artifact absent), then the verified positive state AFTER
   (call succeeds AND artifact exists). Both captured or it didn't happen.
3. Run: `list_validation_scenarios()` → `run_validation_scenario(scenario=…,
   save_results=true)`. Persisted results land in `validation-runs/<date>/scenarios.json`.
   Per-step trace + root-cause report (`## Blockers` / `## Per-step trace`) is part of the output.
4. A failing scenario may declare `recovery_steps`; scenarios can partial-pass
   via `min_passing` / `pass_ratio`; `requires_http` gates need a live REST
   server on port 8741 (reports `unconfigured` when offline).

## Bug → regression flywheel (mandatory)

Every bug fix ends with a new regression scenario named after the issue
(`regression-<issue>-<slug>`), marked `regression: true`, in `scenarios/regression/`.
It stays green forever (recursive-glob auto-load). `scripts/coverage_audit.py`
prints the "Regression scenarios: N" metric — keep it climbing. This is the
process-improvement loop of the 七阶段 methodology's Review stage.

## Evidence & reports

```bash
# Persist + zip a run (skips LLM scenarios when flagged)
python3 scripts/validation_delivery.py --skip-llm-scenarios
# Versioned acceptance report from a run's scenarios.json
python3 scripts/validation_report.py --version <ver>
# Regression trend diff (latest vs previous run)
python3 scripts/validation_diff.py
# Tool-coverage audit
python3 scripts/coverage_audit.py
# Doc consistency gate (AC8)
python3 scripts/doc_inventory.py --check
```

Evidence layout: `validation-runs/<date>/evidence/` (A1-A24, git-whitelisted),
`docs/dev/validation-reports/acceptance-<version>-<date>.md` (executive report),
`validation-deliveries/<date>/` (delivery zips).

## Grading & change control

- Verdicts: PASS / FAIL / RISK / `unconfigured` per AC1-AC9; grading authority
  is `docs/dev/acceptance-framework.md` (evidence catalog A1-A24).
- **AC7**: changing the acceptance framework or its evidence catalog requires
  B3 (director) approval — never self-approve. Evidence for a run is recorded
  in `docs/dev/validation-reports/` per §7.5/§10.