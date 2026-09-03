# Example 3 — ESCALATE (value/intent judgment beyond machine reach)

A SIGNED example of an ESCALATE verdict.  ESCALATE means "a human must
decide" — either the LLM channel was unreachable (fail-loud, NEVER a silent
PASS — #127/#195) or the question is a product-intent/value call that no
deterministic rule or model should终裁.

---

## Verdict

- **family**: premium-briefing
- **file**: outputs/b2b/premium-briefing.md
- **blind_spot**: value-hierarchy
- **verdict**: `ESCALATE`
- **evidence**: premium renders 4 items (oMLX, a16z, VAST, 中科大) while the
  free digest renders 8.  Two premium items (VAST 85, 中科大 65) are NOT in
  the digest's top-8 — a deliberate sub-selection.  Whether dropping the
  digest's #3 and #4 by relevance for two deeper-premium-only picks is
  "differentiated value" or "inverted hierarchy" is a product-positioning
  call.
- **note**: The selection is not a strict subset (so not the mechanical
  inversion defect), but the intent behind it (deeper-analysis tradeoff) is
  not machine-judgeable from the file alone.  Escalate to the director.

## Honesty declaration

- **What was reviewed**: premium item list vs digest item list + per-item
  relevance (both files read fully)
- **What was NOT reviewed**: whether the premium-only items carry genuinely
  deeper analysis (would require reading each source entry)
- **Channel**: LLM channel unreachable this run (timeout after 3 attempts) —
  fail-loud: this is ESCALATE, not PASS
