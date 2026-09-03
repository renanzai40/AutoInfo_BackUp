# L1 Agent-Review Verdict Template (issue #194)

One verdict block per blind-spot worklist item.  A verdict is **invalid without
`evidence`** — the evidence field is what makes the judgment reviewable and
the failure catchable.  Fill this EXACT shape; the battery assembler parses it.

---

## Verdict

- **family**: <product family, e.g. magazine-digest>
- **file**: <relative path to the product file under review>
- **blind_spot**: <id from blindspots.yaml, e.g. claim-fabrication-vs-hedge>
- **verdict**: `PASS` | `FLAG` | `ESCALATE`
- **evidence**: file:line or source URL that supports the verdict (REQUIRED —
  an empty evidence field invalidates the verdict)
- **note**: <1-3 sentences.  For FLAG: what drifted and what the source says.
  For PASS: what you checked.  For ESCALATE: why this needs a human.>

## Honesty declaration

- **What was reviewed**: <list the blind spots + files actually judged in
  this run>
- **What was NOT reviewed**: <anything skipped — unread sections, families
  outside the delivery dir, blind spots with no applicable product>
- **Channel**: <provider/model used, if any; or "deterministic only">

---

## Verdict semantics

| Verdict | Meaning | When |
|---------|---------|------|
| `PASS` | Product satisfies the blind spot | Evidence = what you checked / where the fact is grounded |
| `FLAG` | Product violates the blind spot | Evidence = the offending sentence + the source truth |
| `ESCALATE` | Cannot judge, or a value/intent call beyond machine reach | Evidence = why (LLM unreachable, missing context, product-intent tradeoff) |

**Fail-loud rule**: an unreachable/parse-failed LLM judgment is `ESCALATE`,
NEVER `PASS`.  Silent non-judgment is worse than a wrong judgment (#127/#195).
