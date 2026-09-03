# Example 2 — FLAG (known defect: the #192 three-person drift)

A SIGNED example of a FLAG verdict — the exact defect class quality_gate C6
catches deterministically AND the L1 semantic layer must also catch (and
rewrite-drift cases C6 cannot, where the wording changes but the entity is
paraphrased).  This is what a rejecting review looks like: the offending
sentence + the source truth it rewrites.

---

## Verdict

- **family**: magazine-digest
- **file**: outputs/ai-commercial/magazine-digest.md
- **blind_spot**: claim-fabrication-vs-hedge
- **verdict**: `FLAG`
- **evidence**: feature_story ¶1 "Its journey from a three-person idea"
  (magazine-digest.md:24) — the source entry says "a three-year-old
  startup" (e7, https://techcrunch.com/.../hardware-round).  "three-person
  idea" is source-unstated and asserted as fact.
- **note**: hedged alternatives would pass ("founded three years ago per the
  source"); this sentence asserts an invented founding detail.  Reject and
  regenerate once with the flagged sentence fed back as the constraint.

## Honesty declaration

- **What was reviewed**: claim-fabrication-vs-hedge on The Feature (all 4
  paragraphs, line 20-40)
- **What was NOT reviewed**: editorial_intro (no fabrication signal found in
  a 2-sentence skim, but not sentence-by-sentence)
- **Channel**: openai/deepseek-v4-flash via config.llm (json_mode)
