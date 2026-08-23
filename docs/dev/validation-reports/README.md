# Acceptance Run Reports

Versioned acceptance run reports per `docs/dev/acceptance-framework.md` (AC1-AC9, §7.5/§10).

## Layout

| Path | Content |
|------|---------|
| `validation-runs/<date>/scenarios.json` | Persisted scenario results per run (`run_validation_scenario(save_results=true)` or `validation_delivery.py`) |
| `validation-runs/<date>/evidence/` | A1-A24 evidence files collected during the run (git-tracked via `.gitignore` whitelist) |
| `validation-runs/latest.txt` | Pointer to the newest run directory |
| `docs/dev/validation-reports/acceptance-<version>-<date>.md` | Executive acceptance run report generated from a run's `scenarios.json` |
| `validation-deliveries/<date>/` | Delivery zips from `validation_delivery.py` (fixed archive location) |
| `docs/dev/validation-reports/evidence-backup-issues-3-4.md` | Active closure evidence for backup issues #3/#4 (regression 351/325) |
| `validation-runs/coverage/coverage-<date>.json` | Timestamped coverage audit output from `scripts/coverage_audit.py` |

> Naming history: reports were previously `launch-validation-<version>.md` under the D1-D5 framework
> (`docs/archive/launch-validation-framework.md`, archived 2026-08-08). The convention is now
> `acceptance-<version>.md` per the acceptance framework §7.5.

## Workflow

```bash
# 1. Run scenarios, persisting results (MCP: pass save_results=true)
python3 scripts/validation_delivery.py --skip-llm-scenarios   # also persists + zips

# 2. Generate a versioned run report
python3 scripts/validation_report.py --version 1.9

# 3. Diff two runs for regression trends
python3 scripts/validation_diff.py                # latest vs previous

# 4. Timestamped tool-coverage audit
python3 scripts/coverage_audit.py

# 5. Documentation inventory + consistency check (AC8)
python3 scripts/doc_inventory.py --check
```

## Durability

`.omo/` remains gitignored; the repo-root `validation-runs/` directory is
**runtime state and is NOT git-tracked** (gitignored). Only the named audit
evidence JSONs under `validation-runs/coverage/` (tool-desc, tool-similarity,
error-message, llm-judge-calibration, scenario-outcome) are treated as
semi-durable evidence — preserve them across cleanups. Run evidence worth
keeping is promoted into `docs/dev/validation-reports/` (git-tracked), e.g.
`evidence-backup-issues-3-4.md`.

## Closure status

The 2026-08-08 first-run and 2026-08-12 second-run acceptance reports
(`acceptance-2026-08-08.md`, `acceptance-2026-08-12.md`) are **archived**
under `docs/archive/` (2026-08-23 doc-architecture wave) — historical run
evidence per acceptance-framework §7.5. Summary of the closed state: the
KB-curation gap-closure wave (2026-08-08) closed B-03..B-08 plus the
query_collected CWD trap and FRED_API_KEY doc gap; the second run closed
all 7 first-run FAIL blockers (B-01..B-07) and R-01, overall verdict PASS
(sign-off candidate). Active closure evidence: `evidence-backup-issues-3-4.md`.
