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

`.omo/` remains gitignored, but `.omo/evidence/validation-runs/` and the
repo-root `validation-runs/` directory are whitelisted in `.gitignore`, so
run evidence and results are committed to git and survive clones/cleanups
instead of being ephemeral local files.

## Closure status

The 2026-08-08 first-run findings matrix is maintained in
`docs/dev/validation-reports/acceptance-2026-08-08.md`. The KB-curation
gap-closure wave (2026-08-08) closed B-03, B-04, B-05, B-06, B-07, B-08,
the query_collected CWD trap, and the FRED_API_KEY documentation gap — see
the "B-class Closure Status" section there. Per the second run
(`docs/dev/validation-reports/acceptance-2026-08-12.md`), all 7 first-run
FAIL blockers (B-01..B-07) and R-01 are now closed or adjudicated, and the
overall verdict is PASS (sign-off candidate); remaining items are B3 final
adjudication, AC5 sample human reading, and the non-blocking presentation
observation (OBS-1).
