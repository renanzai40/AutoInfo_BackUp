# Example 1 — PASS (known-good product, fully grounded)

This is a SIGNED example of what a passing magazine-digest review looks like
(few-shot reference for the L1 battery / any reviewing agent).  The
feature_story asserts only entry-stated facts and honestly hedges what the
sources do not say (#179/#191 behavior — the CORRECT outcome).

---

## Verdict

- **family**: magazine-digest
- **file**: outputs/ai-commercial/magazine-digest.md
- **blind_spot**: claim-fabrication-vs-hedge
- **verdict**: `PASS`
- **evidence**: feature_story ¶2 "the company raised funding for hardware
  products" ↔ entry e7 source_url https://techcrunch.com/.../hardware-round;
  ¶3 "whose detailed backgrounds are not disclosed in the available entries"
  is an honest hedge, not fabrication
- **note**: The Feature names only companies/facts present in the entries
  (VAST round, 中科大 compute project).  Each number traces to a Reference
  URL.  The one unknown (founding-team background) is explicitly marked
  not-disclosed instead of invented.

## Honesty declaration

- **What was reviewed**: claim-fabrication-vs-hedge + feature-grounding on
  outputs/ai-commercial/magazine-digest.md (The Feature + Editor's Note)
- **What was NOT reviewed**: entry-relevance (blind spot not in the magazine
  worklist for this run); premium value-hierarchy (no premium product in dir)
- **Channel**: openai/deepseek-v4-flash via config.llm (json_mode)

---

## Verdict

- **family**: magazine-digest
- **file**: outputs/ai-commercial/magazine-digest.md
- **blind_spot**: feature-grounding
- **verdict**: `PASS`
- **evidence**: every Feature entity ("VAST", "中科大", "StartLux") appears
  in the digest Entries section or References
- **note**: quality_gate C6 already confirmed deterministic grounding; the
  semantic pass found no paraphrased-or-invented entity.

## Honesty declaration

- **What was reviewed**: feature-grounding on the Feature paragraphs
- **What was NOT reviewed**: cross-product entity consistency (single-file
  scan only)
- **Channel**: deterministic (no LLM — C6 parity check)
