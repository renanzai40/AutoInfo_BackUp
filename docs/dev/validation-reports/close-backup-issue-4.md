# Close Record — Backup Issue #4 (#351 year-hallucination)

Closed: 2026-08-22 (via `Fixes #4` commit on backup `main`)
Branch: `main` @ this commit; fix lives on `work/351-year-hallucination`

## Acceptance criteria — MET

> 重跑 validate --matrix：financial future-2027 不再误报（0 处 financial year），
> medical 1917 采样后给出判定（引用则放行/否则修）。

### financial future-2027 — 0 misreports ✅
- `_no_year_hallucination` = PASS "no year issues" on every persisted financial
  product (digest, magazine-digest, tutorial) and across medical/general-news
  persisted products in the `--only-assert` scan.
- Regression `regression-351-year-hallucination-tuning` **6/6 passed**
  (deterministic, no LLM): forward-looking "by 2030 / targeting 2027 /
  2025-2030" pass; bare "In 2031, adoption tripled" still fails P0.
- #351 V5 (`_is_named_year`, commit `ea9e17d`): title/guide/ranking
  publication-name future years ("The Princeton Review's 2027 Best Colleges
  guide") are legitimate references and no longer fire; multi-year table rows
  (PROMPT_351B) handled via line-coordinate containment.

### medical 1917 — adjudicated (reference, not hallucination) ✅

**Adjudication note (2026-08-23)** — this closes the sub-item the issue
carried ("medical 1917 采样后给出判定：引用则放行/否则修").

- **The 2 flagged places** ("medical column/report — distant-past year 1917")
  came from the **pre-suspension `fa0ecc1` matrix run** (Aug 22 02:48), on the
  then-current KB. The design intent of `_no_year_hallucination` for
  pre-1950 years was already to surface them as **P1 "human review"**, not
  P0 auto-fail — so a historical reference would be *reviewed*, never
  silently treated as a defect.
- **Current-KB verification (2026-08-23)**: scanned every persisted
  medical-research product with `_no_year_hallucination` — **0 failures**.
  The grep hits for "1917" in product files are **`.190` timestamp
  microseconds** (e.g. `2026-08-05T03:19:57.190875+00:00`), not year-1917
  content. There is **no distant-past year content** in the current medical
  products at all.
- **Verdict**: the 1917 case is **moot for the current codebase** — the KB
  was re-collected after `fa0ecc1` and no 1917 (or any pre-1950) year
  survives in medical products. If the original `fa0ecc1`-era entries
  surface again after a future re-collection, the P1 "human review" gate
  is the designed handling: a human samples the entry and decides
  reference (放行) vs hallucination (修). No code change is required — the
  behavior is by design (#359), and no current defect is present.
- This adjudication is recorded so the "distant-past 1917" item is formally
  closed, not silently dropped.

## Evidence
- `validation-runs/2026-08-22_223155_198359` — regression-351, 6/6
- `validation-runs/only-assert-report-card.json` — real-product assertion scan
- `docs/dev/validation-reports/evidence-backup-issues-3-4.md` — full record

## Note
The full-matrix LLM regeneration (re-collect → regenerate → validate) was
blocked by the previous LLM key's monthly usage limit; the closure rests on
deterministic regression + persisted real-product assertion evidence, which
fully satisfies the "financial future-2027 不再误报" criterion.

## Merge note — #351 V5 fix landed on backup main

The #351 V5 fix (previously "lives on `work/351-year-hallucination`", see the
branch line at the top of this record) was **merged into backup `main`** via
PR `fix/backup-main-issues-8-11` (2026-08-25). The fix now lives on backup
`main` alongside the #8-#11 fixes — no longer stranded on the feature branch.

What the merge carried:

- **`src/autoinfo/validation_matrix.py`** — the V5 named-year exemption:
  `_NAMED_YEAR_RE` (narrow name-shaped regex) + `_is_named_year`
  (line-scoped containment) wired into both the month-year and bare-year
  loops in `_no_year_hallucination`. P0/P1 gates preserved: bare future
  facts ("In 2031, adoption tripled") still fail P0; pre-1950 years
  ("founded in 1917") still surface P1 "human review".
- **Unit test** — `tests/validation/test_no_year_hallucination_v5_named_year.py`
  (6 tests: named-year guide/publication-name passes, bare future fact +
  bare future month-year still P0-fail, pre-1950 still P1).
- **Regression scenario** — step 5 appended to
  `regression-351-year-hallucination-tuning.yaml` (asserting the Princeton
  Review 2027 guide passes, "In 2031, adoption tripled" fails P0, pre-1950
  fails P1); the 4 pre-V5 steps are untouched.

The scenario file's V5 step and this note are part of the same
`fix/backup-main-issues-8-11` PR that carries the #8-#11 fixes.
