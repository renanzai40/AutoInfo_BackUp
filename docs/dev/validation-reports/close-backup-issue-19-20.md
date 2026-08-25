# Close evidence — backup issues #19, #20 (domain fine-tuning)

**Opened**: 2026-08-25 · **Verified**: 2026-08-25/26 · **Fixed by**: commit `844f72e` + runtime topic sync + language backfill

## What was verified (pre-fix state)

### #19 medical-research (P1)
`src/autoinfo/data/domains/medical-research/sources.yaml` had exactly **2 narrow topics** (`IVF breakthroughs`, `Neuroplasticity`), **no `exclude_keywords`**, **no `default_language`** — while the runtime config domain block also lacked all three (`dl=''`, `excl=0`). Confirmed against both the seed file and `.autoinfo/config.yaml`.

### #20 financial-intelligence (P2)
Seed had **3 generic topics** (`Market Trends` / `Economic Indicators` / `Corporate Filings`), `exclude_keywords` only covering SEC bare-form ids, **no `default_language`**; 6 of 10 configured sources are API-key-gated (Alpha Vantage / FRED / Finnhub / Twelve Data / Quandl / Yahoo Finance) and unusable without keys.

## What changed

| Item | medical-research | financial-intelligence |
|---|---|---|
| Topics | 6 semantic: IVF & Assisted Reproduction; Endometrium & Ovarian Reserve; Male Infertility; Embryology & Pregnancy Outcomes; Neuroplasticity & Cognition; Neuropsychiatry & Neurology | 5 semantic: Listed Companies & Earnings; M&A & Financing; Macro & Policy; Regulation & Compliance; Market Structure |
| exclude_keywords | 12 terms (psych/peds/generic-bio noise) | 25 terms (SEC residue + commodities/housing macro spam + deal clickbait) |
| default_language | `en` | `en` |
| Effective source set | unchanged (all reachable) | documented: 3 keyless RSS (CNBC/TheStreet/MarketWatch) + SEC EDGAR + World Bank; key-gated APIs excluded from the active set in runtime |

Runtime topics synced via CLI (`autoinfo topics add/remove`, idempotent), seed files committed (`844f72e`).

## Data-quality fix bundled (runtime DB)

The `default_language` filter exposes sparse `entries.language` metadata. A runtime backfill (langdetect + deterministic Unicode-script detection) updated **39 entries** across all domains; script-first detection for Hangul/Cyrillic/Devanagari landed as a code fix (`acfd610` — langdetect misclassifies Hangul as `en`, which would have emptied Korean products).

## Evidence

- Products rendered on the real KB (post-backfill): `outputs/evidence-19-20/medical-report.md` (55 references, semantic themes), `medical-digest.md` (58,922 B), `financial-report.md` (semantic themes incl. Equity Investment Strategies / International Trade Disputes), `financial-digest.md` (25,573 B).
- Report `## Sections` are semantic (Reproductive Medicine Advances, Machine Learning in ART Outcomes, Embryo Cryopreservation and Culture, …); keyword-fragment labels (`New/Year/User`) absent.
- Known residual (paid recheck item): cross-batch grouping still produces more than 5-12 small themes on the heterogeneous 73-entry KB — per-batch 3-5 themes are merged only by near-dup name; a global consolidation pass is follow-up work, not a config gap.
- `docs/dev/validation-reports/` wave tests: `tests/output/test_language_filter.py`, `test_domain_exclude_keywords.py`, `test_theme_semantic_titles.py`, `test_group_by_theme_parallel.py` all green in the W1 runs.

## Issues status

#19, #20 remain OPEN until the final delivery wave closes them with this evidence + pushed commits.