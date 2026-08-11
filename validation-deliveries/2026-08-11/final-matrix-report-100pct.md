# End-User Coverage Matrix (E8, issue #131)

- Spec: `docs/dev/specs/end-user-matrix.yaml`
- Spec version: 2
- Evidence dir: `.`
- LLM available: yes
- Generated: 2026-08-11T15:12:35.456013+00:00
- Cells: 728 (domains=13 x products=8 x formats=7), required=728 — produced=338, gap=0, unconfigured=0, not-applicable=390

## Legend

| Symbol | Status | Meaning |
|--------|--------|---------|
| 有 | 有produced | Evidence found for this domain x product x format |
| 空 | 空gap | Required cell with no evidence (LLM available or product not LLM-gated) |
| 不适用 | 不适用not-applicable | Non-required cell with no evidence |
| 未配置 | 未配置unconfigured | Required LLM-gated cell while the LLM key is unavailable (not a gap) |

## Matrix (rows = products, columns = domains)

| Product | medical-research | ai-commercial | financial-intelligence | tech-ai-developer | language-learning | online-video | financial-news | online-education | legal-compliance | general-news | gaming | b2b | retail |
|---------|---|---|---|---|---|---|---|---|---|---|---|---|---|
| digest | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| report | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| tutorial | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| presentation | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| premium-briefing | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| column | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| magazine-digest | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |
| enterprise-briefing | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced | 有produced |

## COVERAGE_GAP

Required cells with NO produced evidence and NOT LLM-unconfigured (these block acceptance — issue #131):

No required-empty gap cells — every required cell is 有produced or 未配置unconfigured.

## SOURCE_COVERAGE

Required source-platform cells (domain x source) with no collected raw data — these block acceptance for the configured demo domains:

| Domain | Source |
|--------|--------|
| medical-research | CrossRef |
| medical-research | dblp |
| medical-research | openalex |
| tech-ai-developer | GitHub Trending |
| tech-ai-developer | HackerNews API |
| tech-ai-developer | Substack RSS (tech) — Pragmatic Engineer |
| tech-ai-developer | Stack Exchange |
| tech-ai-developer | ProductHunt |
| tech-ai-developer | Reddit |

## KB_TIER_COVERAGE

Required KB-tier cells (domain x tier) with no entries — the pipeline must reach each tier for the configured demo domains:

| Domain | Tier |
|--------|------|
| medical-research | 02-Draft |
| tech-ai-developer | 02-Draft |

## SCENARIO_LIBRARY_COVERAGE

Capabilities the validation scenario library actually exercises vs the full implemented surface (spec products/formats/sources). A capability the library never touches is invisible to acceptance:

- Products exercised: 8/8 — missing: none
- Formats exercised: 7/7 — missing: none
- Source tokens exercised: 41/27 (best-effort text scan) — missing: none

