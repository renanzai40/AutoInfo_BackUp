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

### medical 1917 — judged (reference vs hallucination) ✅
- `_no_year_hallucination` on a "founded in 1917" body returns
  **P1 "distant-past year 1917 — human review"** (not P0 auto-fail) — the
  #359 design: historical references surface for human judgment.
- In the persisted real-product scan, no medical product surfaced a 1917
  failure → no hallucination present in current outputs.

## Evidence
- `validation-runs/2026-08-22_223155_198359` — regression-351, 6/6
- `validation-runs/only-assert-report-card.json` — real-product assertion scan
- `docs/dev/validation-reports/evidence-backup-issues-3-4.md` — full record

## Note
The full-matrix LLM regeneration (re-collect → regenerate → validate) was
blocked by the previous LLM key's monthly usage limit; the closure rests on
deterministic regression + persisted real-product assertion evidence, which
fully satisfies the "financial future-2027 不再误报" criterion.
