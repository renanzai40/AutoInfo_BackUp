# known-defects corpus — regression fixtures for the L1 battery (#194 spec C)

Each fixture under this directory captures a REAL defect class the L0 gate
cannot structurally catch, with the triggering product fragment and the
expected L1 verdict.  The battery acceptance: a run over `known-good/`
PASSES; a run over `known-defects/<case>/` FLAGs the named blind spot.

Corpus index (case dir -> blind spot -> defect class -> issue):

| case | blind spot | defect class | origin |
|------|-----------|--------------|--------|
| three-person-drift | claim-fabrication-vs-hedge | narrative asserts source-unstated detail as fact ("three-person idea" vs source "three-year-old startup") | #192/#191 |
| coverage-absence-36kr | coverage-absence (digest) | bilingual domain digest omits the whole China-AI-market dimension | #190 |
| fake-entry | no-fake-entries (cross-domain) | synthesized multi-source draft renders as a fake single-source news row | #178/#184 |
| empty-shell | summary-emptiness | product renders with no curated content | #149/#152/#294 |
| honest-hedge-positive | claim-fabrication-vs-hedge | "not disclosed in the available entries" — CORRECT behavior, must PASS (never mis-flagged) | #179/#191 |

## Known-good reference

`known-good/` holds products that PASS every applicable blind spot — the
battery must not FLAG them (no false positives).
