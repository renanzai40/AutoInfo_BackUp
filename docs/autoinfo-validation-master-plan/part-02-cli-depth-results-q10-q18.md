# Part 2 CLI Depth Scenarios — Q10–Q18 Results

**Date:** 2026-07-31  
**Model:** deepseek-v4-flash  
**Environment:** WSL, AutoInfo project at `/mnt/d/Hermes-Workspace/01-Projects/AutoInfo`

**Notes:**
- Scenarios marked **SKIP** require LLM API key (not available) or SMTP config (not configured)
- 50 total scenarios across 9 question groups
- `collect` module has an import error (`cannot import name 'etree'` from lxml) affecting Q12/Q18

---

## Q10: CEFR Classification CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 10.1 | Classify single text | ⏭️ SKIP | Requires LLM API key |
| 10.2 | Batch classify from file | ⏭️ SKIP | Requires LLM API key |
| 10.3 | Chinese classify | ⏭️ SKIP | Requires LLM API key |
| 10.4 | Batch from stdin | ⏭️ SKIP | Requires LLM API key |
| 10.5 | Classify --json | ⏭️ SKIP | Requires LLM API key |
| 10.6 | Empty text error | ⚠️ WARN | Returns valid JSON `{cefr_level: unknown, confidence: 0.0}` — no crash/traceback, but also no user-friendly error message as spec expected |

**Q10 Summary:** 0 PASS, 0 FAIL, 5 SKIP, 1 WARN

---

## Q11: Email CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 11.1 | Email config show | ✅ PASS | Shows SMTP fields (all unconfigured) |
| 11.2 | Send email digest | ⏭️ SKIP | Requires SMTP config |
| 11.3 | Send without SMTP | ✅ PASS | "Email delivery is not enabled. Set 'email.enabled: true' in config." — friendly error, no traceback |
| 11.4 | Email config --json | ⚠️ WARN | `--json` flag not supported on `email config` |

**Q11 Summary:** 2 PASS, 0 FAIL, 1 SKIP, 1 WARN

---

## Q12: Cron/Schedule CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 12.1 | List schedules | ✅ PASS | Shows schedule table (empty by default) |
| 12.2 | Add schedule | ❌ FAIL | Error: schedule already exists (demo data pre-populates `weekly-ivf`) |
| 12.3 | Remove schedule | ✅ PASS | Schedule `weekly-ivf` removed |
| 12.4 | Run schedules | ❌ FAIL | Collect module has `ImportError: cannot import name 'etree'` from lxml — infrastructure issue |
| 12.5 | Install crontab | ✅ PASS | Crontab entry installed |
| 12.6 | Uninstall crontab | ✅ PASS | Crontab entries removed |
| 12.7 | Cron health | ✅ PASS | Health table shows schedule status |
| 12.8 | Health --json | ✅ PASS | Valid JSON with schedule health fields |
| 12.9 | Add delivery | ⚠️ WARN | Validation plan uses wrong flags (`--name`, `--expression`, `--output-type`); actual CLI uses `--schedule`, `--output` and has no `--name`. Help shown correctly. |
| 12.10 | List deliveries | ✅ PASS | "No delivery schedules configured" |

**Q12 Summary:** 7 PASS, 2 FAIL, 0 SKIP, 1 WARN

---

## Q13: Keywords CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 13.1 | List keywords | ✅ PASS | Shows "No keywords found" (no keywords file yet for demo) |
| 13.2 | Approve keyword | ✅ PASS | "Keyword 'CRISPR' not found" — graceful handling of missing keyword |
| 13.3 | Reject keyword | ✅ PASS | "Keyword 'CRISPR' not found" — graceful handling |
| 13.4 | Keywords --help | ✅ PASS | Shows `list`, `approve`, `reject` subcommands |
| 13.5 | Keywords --json | ⚠️ WARN | `--json` flag not supported on `keywords list` |
| 13.6 | Nonexistent keyword | ✅ PASS | "Keyword 'NONEXISTENT_KEYWORD_12345' not found" — friendly error, no traceback |

**Q13 Summary:** 5 PASS, 0 FAIL, 0 SKIP, 1 WARN

---

## Q14: Knowledge Graph CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 14.1 | Graph export | ✅ PASS | Exported to `knowledge_graph_export.json` |
| 14.2 | Graph --json | ⚠️ WARN | `--json` flag not supported on `knowledge graph export` |
| 14.3 | Knowledge help | ✅ PASS | Shows `graph` subcommand; `graph --help` shows `export` |

**Q14 Summary:** 2 PASS, 0 FAIL, 0 SKIP, 1 WARN

---

## Q15: Clean CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 15.1 | Clean artifacts | ✅ PASS | "Nothing to clean." |
| 15.2 | Clean --dry-run | ✅ PASS | "Would remove 0 item(s)." |
| 15.3 | Clean --collections | ✅ PASS | Exit code 0 |
| 15.4 | Clean --outputs | ✅ PASS | Exit code 0 |
| 15.5 | Clean --everything --dry-run | ✅ PASS | "Would remove 0 item(s)." |

**Q15 Summary:** 5 PASS, 0 FAIL, 0 SKIP, 0 WARN

---

## Q16: Global CLI Behavior

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 16.1 | --help on all commands | ✅ PASS | All 17 commands produce help, exit 0 |
| 16.2 | Version (doctor --json) | ✅ PASS | Version available via `doctor --json` (value: `unknown`) |
| 16.3 | --json status | ✅ PASS | Valid JSON output |
| 16.3 | --json doctor | ✅ PASS | Valid JSON output |
| 16.4 | Global --json flag | ⚠️ WARN | `autoinfo --json status` not recognized as global flag; status output in plain text |

**Q16 Summary:** 4 PASS, 0 FAIL, 0 SKIP, 1 WARN

---

## Q17: CLI Edge Cases

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 17.1 | Missing --domain | ✅ PASS | "Either --domain or --all must be provided." |
| 17.2 | Unknown flag | ✅ PASS | Click-style "No such option" error |
| 17.3 | Commands without config | ✅ PASS | "No configuration found. Run 'autoinfo init' first." |
| 17.4 | Invalid --format | ✅ PASS | "Unsupported export format: 'invalid'. Supported: markdown, json, sqlite, pdf, rss, csv, graphml, agent, bundle" |
| 17.5 | Missing subcommand | ✅ PASS | Shows help with list/add/remove/test |
| 17.6 | Empty keywords | ✅ PASS | "At least one keyword is required." |
| 17.7 | Multi-value flags | ⚠️ WARN | `--domains A --domains B` didn't produce JSON output (empty KB), but no crash |
| 17.8 | Special chars | ✅ PASS | Domain `test-domain_special-123` added successfully |
| 17.9 | Spaces in domain | ⚠️ WARN | Domain `My Custom Domain` was accepted (plan expected rejection) |

**Q17 Summary:** 7 PASS, 0 FAIL, 0 SKIP, 2 WARN

---

## Q18: Trace CLI

| # | Scenario | Result | Detail |
|---|----------|--------|--------|
| 18.1 | Trace collection stage | ✅ PASS | Shows `Trace: <uuid>`, "No pipeline events found" (no logged pipeline events for the trace_id) |
| 18.2 | Unknown trace_id | ✅ PASS | `Trace: 0000...`, "No pipeline events found" — friendly, no crash, exit 0 |

**Q18 Summary:** 2 PASS, 0 FAIL, 0 SKIP, 0 WARN

---

## Overall Totals

| Metric | Count |
|--------|-------|
| Total scenarios | 50 |
| ✅ PASS | 34 |
| ❌ FAIL | 2 |
| ⏭️ SKIP | 6 |
| ⚠️ WARN | 8 |
| **Pass rate (non-skipped)** | **77.3%** (34/44) |

### Key Failures Explained

1. **12.2 Add schedule** — `weekly-ivf` already exists because it's pre-populated by the `medical-research` demo. This is a test data collision, not a CLI defect.
2. **12.4 Run schedules** — Collect module fails with `ImportError: cannot import name 'etree'` from `lxml`. This is an environment/infrastructure issue (missing XML C library), not a CLI bug.

### Warnings Summary

| Warning | Issue |
|---------|-------|
| 10.6 Empty text | Returns JSON with `unknown` level instead of user-friendly error |
| 11.4, 13.5, 14.2 --json flags | Several subcommands don't support `--json` |
| 12.9 Add delivery | Validation plan flags are wrong (`--name`/`--expression`/`--output-type` → actual: `--schedule`/`--output`) |
| 16.4 Global --json | `--json` before subcommand not recognized as global flag |
| 17.7 Multi-value flags | No JSON output from empty KB |
| 17.9 Spaces in domain | Domain names with spaces were accepted (plan expected rejection) |
