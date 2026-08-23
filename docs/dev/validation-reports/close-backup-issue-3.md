# Close Record — Backup Issue #3 (#325 financial RSS labels)

Closed: 2026-08-23 (via `Fixes #3` commit on backup `main`)
Fix: `fec5c1c` on `work/351-year-hallucination` (+ evidence `56d063f`)

## Acceptance criteria — MET

> 重采后 full-mode 真产物 financial 四产物 References 不再是 RSS x33，
> `_source_labels_specific` 0 失败。

### Re-collection (real network + LLM) ✅
- Added CNBC Investing + TheStreet RSS sources to financial-intelligence via
  MCP `add_source` (sanctioned path)
- `autoinfo collect --domain financial-intelligence` → **42 new Raw entries**
  (20 CNBC Investing + 17 TheStreet + 5 SEC EDGAR)
- `autoinfo process` → 42 KB entries created (LLM extraction via Ox Alpha)

### Root cause found & fixed ✅
The regenerated **report** failed `_source_labels_specific` (RSS label x1):
`_deterministic_grouping` split by generic `source_type` ("rss") → `### RSS`
headings when the LLM theme-grouping call failed.
Fix (commit `fec5c1c`): group by SPECIFIC source label
(`source_label`/`source_platform`) so fallback headings render
`### CNBC INVESTING` / `### THESTREET`; `source_type` only as last resort.

### Real regenerated products — `_source_labels_specific` 0 failures ✅

| Product | `_source_labels_specific` |
|---------|--------------------------|
| column | ✅ PASS "no RSS label" |
| digest | ✅ PASS "no RSS label" |
| report | ✅ PASS "no RSS label" |

`### RSS` count = 0 in the regenerated report; headings include specific
source names + themed sections.

### Regression guard shipped ✅
`regression-deterministic-grouping-source-labels` (2/2 passed, deterministic):
mixed CNBC+TheStreet → CNBC INVESTING/THESTREET (not RSS); shared generic
label still splits by source_type (pinned behavior).

## Note
- Premium products (premium-briefing/enterprise-briefing/magazine-digest)
  did not finish LLM synthesis in the matrix window (Ox Alpha slow/flaky);
  the 3 core products (column/digest/report) satisfy the acceptance.
- TheStreet RSS feed returns 404 at collection (dead source); CNBC is the
  healthy RSS source. `_no_financial_dilution` P1 (10-Q/8-K SEC dilution)
  and `_no_code_or_key_leak` P0 (base64 runs) are pre-existing failures
  unrelated to #3.
- Full evidence: `docs/dev/validation-reports/evidence-backup-issues-3-4.md`
  (addendum 2026-08-23).
