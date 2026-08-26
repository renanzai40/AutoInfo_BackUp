# Close evidence — backup issue #38 (product-level localization)

**Opened**: 2026-08-25 · **Implemented**: 2026-08-26 · **Commits**: `3b0b0c0`, `d1f54ce`, `f8bfed8`, `bb5e16f`, `2370aaf`, `12e8577`, `0056a78`, `2636170`

## What was verified (pre-fix state)

`autoinfo output translate` (single-item localize_content) + `translation_qa.py` (back_translate / llm_judge / refine) existed; **no product-level end-to-end pipeline** — no way to produce a whole digest/report in a target language while preserving URLs/structure/placeholders.

## What changed

New module `src/autoinfo/output/localize.py` + CLI `autoinfo output localize`:

```
autoinfo output localize --domain D --product digest --period weekly \
    --target-lang zh [--source-lang en] [--max-items N] [--include-stale] \
    [--out-dir outputs/localized]
```

Pipeline (light plan per issue #38):
1. Generate the product markdown (digest/report/column/premium-briefing/enterprise-briefing/magazine-digest; tutorial/presentation rejected).
2. Segment markdown — protected: URLs/link-targets/code fences+spans/frontmatter/table rows/placeholders (sentinelized, never reach the translator); translatable: heading text, paragraphs, list items.
3. Translate segments via `localize_content` (content mode, domain terminology guardrails).
4. QA gate: stride-sampled back-translation pipeline (deterministic sample), **faithfulness** as the gate score (the composite formula drags a 90-faithful pair to 36 — measured; see `2636170`), one refinement pass on failure.
5. Output `<out-dir>/<target-lang>/<product>-<lang>.md` + `manifest.json` entry recording language/source_lang/period/qa.

## Bugs found and fixed while wiring the real run

| Bug | Fix |
|---|---|
| `localize_content` can return a **list** `translated_body` → `'list' object has no attribute 'strip'` crash | non-str bodies count as failed translations (`12e8577`) |
| back-translate picks `pool[1]` unconditionally; dead free providers zeroed every QA score | QA pool pinned to config primary (`0056a78`) |
| QA read `quality_score`, pipeline returns `composite_score` — and composite weights unmeasured dims at ~25% each | gate reads `faithfulness` (`2636170`) |
| per-segment QA tripled LLM cost; large products exceeded run budgets | stride-sampled QA (`d1f54ce`) |
| weekly-period digests pull ~1 entry on stale KBs | `--include-stale` + language backfill |

## Live-environment evidence

Real run on the medical-research KB (73 entries, en → zh):

```
$ autoinfo output localize --domain medical-research --product digest \
    --period weekly --target-lang zh --max-items 25 --include-stale
Localized medical-research/digest -> zh: outputs/localized/zh/digest-zh.md \
    (qa=passed, avg=98.3, refined=2, failed=0)
```

- `outputs/localized/zh/digest-zh.md` (6,220 B): translated title/exec-summary/key findings/entries; PubMed URLs, table structure, and markdown intact; spot-checked translations high fidelity.
- `outputs/localized/manifest.json`: entry records `{"product": "digest", "domain": "medical-research", "language": "zh", "qa": {"gate": "passed", "avg_score": 98.3, "refined_count": 2, "failed_count": 0, ...}}`.

## Tests

- `tests/output/test_localize_product.py` — 10 tests: segmentation protection, sentinelization, reassembly round-trip, faithfulness-priority gate, composite fallback, refine-on-low-score, file+manifest contract, non-str body guard, product rejection.
- `tests/cli/test_cli_output_localize.py` — 3 CLI surface tests.
- Full localize/CLI/language-filter/theme suites green; ruff clean on new files.

## Notes

- Provider reality on 2026-08-25/26: the CLI's back-translation QA uses the config primary model pool; multi-model back-translation re-engages automatically when >1 provider is healthy.
- MCP parity (`localize_product` tool) deliberately deferred — not in the issue acceptance; CLI is the sanctioned surface.
- OmniLocalizer optional enhancement (en↔zh/ja/ko) untouched, per issue selection.