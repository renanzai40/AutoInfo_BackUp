# Backup Issue #8 / #9 / #10 / #11 Closure Evidence

<!-- doc-type: closure-evidence -->

Closes backup-repo issues
[#8](https://github.com/renanzai40/AutoInfo_BackUp/issues/8) (P0 —
`default_language` never syncs to runtime config for existing domains),
[#9](https://github.com/renanzai40/AutoInfo_BackUp/issues/9) (P1 —
ai-commercial theme grouping collapses to generic `### New` / `### Year` /
`### User` labels),
[#10](https://github.com/renanzai40/AutoInfo_BackUp/issues/10) (P2 —
premium/enterprise `Actions` too shallow),
and [#11](https://github.com/renanzai40/AutoInfo_BackUp/issues/11) (P2 —
references render uncapped).  This record ships in the same
`fix/backup-main-issues-8-11` PR that also merges the stranded #351 V5
named-year fix (see the merge note in `close-backup-issue-4.md`); the PR
body carries `Fixes #8 #9 #10 #11 #4` so GitHub auto-closes all five on
merge.

## What was verified (2026-08-25, worktree `fix/backup-main-issues-8-11`)

Every fix below was verified by running its test file(s) against the
worktree source (`PYTHONPATH=src`), plus a full `tests/output` suite pass.
All commands below are deterministic — no LLM key, no network.

| Suite | Result |
|-------|--------|
| `tests/output/test_language_filter.py` (incl. `TestResolveEffectiveLanguageSeed` + `TestAiCommercialEmptyAfterFilter`) | **20 passed** |
| `tests/output/test_domain_exclude_keywords.py` (fixture gained `language: "en"`) | **23 passed** |
| `tests/output/test_source_label_surfaces.py` (fixture gained `language: "en"`) | **21 passed** |
| `tests/output/test_theme_semantic_titles.py` + `tests/output/test_group_by_theme_parallel.py` (golden sequential baseline) | **15 passed** |
| `tests/output/test_premium_action_depth.py` (opt-in weak guard + enterprise-not-wired) | **10 passed** |
| `tests/output/test_reference_cap.py` (report + digest paths, `selected N of M` inversion) | **12 passed** |
| `tests/output/test_enterprise_briefing_coverage.py` | **9 of 20 preserved** |
| `tests/output` — full suite | **600 passed, 10 skipped, 1 pre-existing failure** (`test_video_integration` — WSL Chrome render, documented pre-existing env failure) |
| `tests/validation` (incl. `test_no_year_hallucination_v5_named_year.py`, 6 tests) | **287 passed**; 1 pre-existing failure (`test_coverage_matrix` — fails on unchanged HEAD too); 1 stale-count assertion `test_scenario_outcome_audit::test_total_steps` (446 → 447, see below) |
| `regression-351-year-hallucination-tuning.yaml` step 5 (V5 named-year, direct execution) | **`YEAR_HALLUCINATION_NAMED_YEAR_OK`** |

The `test_scenario_outcome_audit::test_total_steps` drift (446 → 447) is a
**fixture-count reconciliation**: todo 7 appended the V5 step (step 5) to
`regression-351-year-hallucination-tuning.yaml`, so the audited scenario
step total legitimately grew by one.  The closure doc records it so a
follow-up can bump the expected count; it is not a behavior regression.

## Issue #8 — `_resolve_effective_language` seed fallback (P0)

### What was changed

`src/autoinfo/output/__init__.py` — the runtime config read in
`_resolve_effective_language` (lines 559-601) now falls back to the
demo-domain seed when a project config file **exists** but its domain block
carries **no `default_language` key at all** (projects initialized before
the field existed — `init` only propagates it for new domains).  The fix
mirrors the #319 `exclude_keywords` pattern exactly:

- `_config_declares_default_language` (lines 604-619) — consults the raw
  config YAML to distinguish "key present but empty" from "key missing"
  (both parse to `""` on the dataclass).
- `_seed_domain_default_language` (lines 622-639) — reads
  `src/autoinfo/data/domains/<domain>/sources.yaml` (`default_language: en`
  for ai-commercial, line 8).

Precedence pinned: explicit `language` param > explicit runtime
`default_language` (even empty = "no filtering") > seed > `""`.
`cross_domain=True` still short-circuits to `""` before any read (line
587-588); a project with **no config file at all** stays `""` (line 590-591,
backward compatible) — the seed never engages on a missing config.

### Acceptance evidence

`tests/output/test_language_filter.py` `TestResolveEffectiveLanguageSeed`
(6 hermetic tests, config path patched — never touches the gitignored local
`.autoinfo/config.yaml`):

- **(a) discriminating case** — config present, ai-commercial block
  key-absent → `_resolve_effective_language("", "ai-commercial") == "en"`
  via seed (the ONLY case that discriminates pre-fix `""` from post-fix
  `"en"`).
- **(b)** explicit `default_language: ""` → `""` (empty wins over seed).
- **(c)** explicit `default_language: zh` → `"zh"`.
- **(d)** `cross_domain=True` → `""` regardless of config/seed.
- **(e)** no config file → `""` (no filtering).
- **(f)** unknown domain, config present, key absent → `""` (no seed).

### ⚠️ The ai-commercial empty-after-filter decision (documented)

**This is the highest-risk behavior change in the PR, and it is INTENDED
enforcement, not a regression.**

Once the seed "en" filter engages, ai-commercial products on the **current
KB** (6 zh-cn + 1 vi entries, **zero en**) come out **empty** — the issue's
own acceptance demands single-language output, and the current KB cannot
satisfy it.  Two behaviors are pinned by `TestAiCommercialEmptyAfterFilter`
in `test_language_filter.py`:

1. **Unit level** — `_filter_entries_by_language(zh_entries, "en") == []`
   (asserted directly, line 318).
2. **Full `generate_report` path** — with zero kept entries:
   - **without** `delivery_gate_configs` (the CLI/MCP default), the
     `if not entries` branch returns the **empty-shell string** (`"This
     edition has no curated items yet."` — the `_apply_min_content_guard`
     call sits inside the `delivery_gate_configs is not None` conditional
     and is skipped);
   - **with** `delivery_gate_configs={"D1": {"action": "block"}}`,
     `_apply_min_content_guard` runs and returns `delivery_blocked=True`
     with a min-content-guard warning.

Both sub-cases are asserted in the test (lines 324-377); `_group_by_theme`
and `_generate_executive_summary` are stubbed so no live LLM call happens.
**Consequence**: ai-commercial will render empty / block delivery until en
content exists, or until the 36kr feed is channel-split per language — the
issue's own P2.  Operators must NOT read an empty ai-commercial product as
a broken pipeline.

## Issue #9 — ai-commercial theme grouping → generic labels (P1)

### What was changed

Root cause (verified against `knowledge/ai-commercial/_keywords.yaml`, 601
lines): the auto-discovery keyword table is CJK tokens + ASCII n-gram
fragments (`意图经济`, `飞猪`, `lui`, `ota`, `gui`, sentence fragments) —
`_normalize_text` strips CJK to `""` and fragments either normalize-empty or
fall below the `len(nt) >= 3` filter, so keyword grouping either fails or
fires on garbage that produces generic labels.  Three-part fix, all in
`src/autoinfo/output/__init__.py`:

1. **Seed-MERGE (not fallback-when-empty)** — `_load_keyword_topics`
   (lines 6313-6351) unconditionally merges `_seed_topic_keywords(domain)`
   (lines 6354-6375, reads `topics[*].keywords` from
   `src/autoinfo/data/domains/<domain>/sources.yaml`) into the runtime
   keyword table, deduped.  "Fallback only when none usable" would never
   engage — the table has 84 usable topics that still never match English
   titles.  `src/autoinfo/data/domains/ai-commercial/sources.yaml` gains
   the 3 genuinely-new English keywords: **`model release`, `regulation`,
   `benchmark`** (the rest — AI startup, artificial intelligence, funding,
   series A, venture capital, seed round, AI product, launch, LLM, GPT,
   generative AI, machine learning — already exist).
2. **Generic-label blocklist** — `_GENERIC_THEME_LABELS`
   (lines 69-72: `new`, `year`, `the year`, `user`, `activity`, `growth`,
   `apps`, `market`, `update`, `summary`); `_merge_theme_groups`
   (lines 6496-6561) drops blocklisted groups after the exact-name +
   Jaccard near-dup passes and reassigns their entries to the nearest
   surviving group (Jaccard ≥ 0.3) or "Additional Topics" — **no entry is
   ever lost**.
3. **Synonym normalization** — `_THEME_SYNONYMS = {"year": "the year"}`
   (line 78) applied in `_normalize_theme_text` (lines 6398-6408) BEFORE
   the near-dup pass, so `Year` / `The Year` merge in the exact-name pass
   and then hit the blocklist together.

### Acceptance evidence

`tests/output/test_theme_semantic_titles.py` (issue #9 additions, lines
159-256):

- `test_generic_theme_labels_blocklisted_and_synonyms_merged` — Year + The
  Year merge into one surviving group; New / User dropped; all 4 entries
  preserved.
- `test_english_keyword_grouping_returns_groups_not_none` —
  `_keyword_group_entries(entries, domain="ai-commercial")` on English
  titles ("Series A funding round" / "GPT-5 model release") returns ≥ 2
  keyword groups with no generic labels.  **Pre-fix this returned `None`.**
- `test_fragment_keywords_do_not_create_generic_groups` — `lui` / `ota` /
  `gui` never create groups.
- `test_cjk_keyword_path_does_not_regress` — CJK-only keywords don't crash
  or create generic groups.
- `test_normalize_theme_text_merges_synonyms` — Year / The Year normalize
  to the same key.

**Regression guards**: `test_theme_semantic_titles.py` (15 passed incl.
`test_near_duplicate_theme_titles_merged`) and
`test_group_by_theme_parallel.py` (7 passed incl.
`test_golden_output_matches_sequential_baseline` at line 176) — medical /
financial report grouping unchanged.

## Issue #10 — premium/enterprise `Actions` too shallow (P2)

### What was changed

Two levers, both in `src/autoinfo/output/__init__.py`:

1. **Prompt-side WHAT/WHEN constraint** — `_REPORT_PRODUCT_BASE_SECTIONS`
   (lines 7942-7979, shared by premium-briefing and enterprise-briefing via
   `_REPORT_PRODUCT_SYNTHESIS_PROMPTS` at 7988-7994) now demands, under
   `## Action Required`, that each action name a **concrete object** (WHICH
   entity/product/model) and a **timeframe or trigger** (WHEN — date,
   milestone, or real-world event).  Bare single-line verbs are explicitly
   forbidden with examples: "Track AI model releases", "Monitor
   developments", "Reassess the market" carry no object and no WHEN.
   The WHO-actor requirement already existed (line 7962); the #10 gap was
   object + timeframe granularity.  Enterprise keeps the **checkbox
   contract** — prompt-side only, no guard wiring (scope narrowing, Oracle
   SF2).
2. **Opt-in weak-action guard (premium-only)** — `_fill_premium_takeaway_fields`
   (lines 4164-4240) gains a `weak: bool = False` predicate (default keeps
   the existing `_usable` behavior — fully backward compatible).  When
   `weak=True` and a takeaway's action line is flagged by
   `autoinfo.validation_matrix._is_weak_analysis` (< 40 chars / formulaic
   "Track "/"Monitor developments around" prefixes), it is replaced
   **per-index** from the KB-derived `_deterministic_takeaway_fields`
   fallback.  The `validation_matrix` import is **function-local** (line
   4196) to break the `output → validation_matrix` module-scope import
   cycle (validation_matrix imports `from autoinfo.output import` at
   function scope).  Enterprise is NOT wired into the guard (its flat
   `- [ ]` checkbox shape is what `_so_what_substantive` requires).

### Acceptance evidence

`tests/output/test_premium_action_depth.py` (10 tests):

- **Prompt**: `TestPromptActionGranularity` — both premium-briefing and
  enterprise-briefing prompt constants carry the WHAT/WHEN clauses
  ("concrete object", "which", "timeframe"/"when", "trigger", and the
  "Track" anti-example).
- **Weak guard**: `TestPremiumWeakActionFallback` — weak "Track AI model
  releases" replaced with the KB-derived "OpenAI GPT-5 ... by the next
  period" (index-aligned with entry 0); substantive LLM actions survive;
  per-index pairing never mis-pairs; the replacement equals the
  deterministic fallback at the same index; the guard is **opt-in**
  (default path keeps weak-but-non-empty actions untouched, empty slots
  still backfilled).
- **Regression parity**: `TestDefaultUsablePathUnchanged` — the default
  (no `weak`) path keeps #357 behavior byte-for-byte (mirrors
  `test_digest_context_normalization.py`).
- **Enterprise-not-wired**: `TestEnterpriseNotWired` — enterprise renders
  the flat `- [ ]` checkbox list (no deterministic-fallback phrasing) and
  `_so_what_substantive` passes on the rendered product; the `weak` param
  is documented as premium-only.

## Issue #11 — references render uncapped (P2)

### What was changed

`ref_limit` (default **60**, `OutputConfig.ref_limit`, config.py:459)
threaded through every surface and applied at the context-build site:

- `generate_report` (references built at lines 5368-5388) and
  `_normalize_digest_product_context` (digest-path products, lines
  4350-4370) cap the `references` list identically — no format/path
  divergence (markdown/html/json/agent/audio/epub/video all capped at the
  build site).
- **Sort before cap** — `_sorted_ref_entries` (lines 3024-3040) sorts the
  FULL entries list by (has non-empty summary desc, `relevance_score` desc)
  BEFORE the ref dicts are built (they drop summary/relevance), so
  title-only entries (e.g. ProductHunt) de-prioritize below
  summary-bearing ones.
- **`ref_limit` precedence** — explicit param > `OutputConfig.ref_limit`
  (config.py) > default 60, resolved via `_output_config_ref_limit` (lines
  3005-3021).
- **Threading** — CLI `--ref-limit` (cli/output.py:118-125 digest,
  233-238 report) and MCP `ref_limit` (server.py:3039 digest, 3183 report;
  schema at 9006/9102) both pass through to the generators.
- **Enterprise `selected N of M` inversion hole closed (decision a)** —
  `_cap_product_key_findings` (lines 3043-3057) caps the render-context
  `key_findings` to `min(12, len(references))` for the premium/enterprise
  families (digest path lines 4372-4381, report path lines 5539-5549), so
  a `ref_limit` below the LLM-produced findings count can never invert the
  label to `selected 9 of 8`.  The magazine report-path per-title clusters
  are built from the capped references (`_report_data_to_dict`, lines
  7199-7211) — accepted behavior, clusters bounded by the cap.

### Acceptance evidence

`tests/output/test_reference_cap.py` (12 tests):

- **Report path** — 80 entries (61 summary-bearing + 19 title-only) render
  exactly **60** references by default; first reference is the max-relevance
  entry; title-only entries excluded; `**References**: 60` in the output;
  the rendered order matches the deterministic sort.
- **Override** — `ref_limit=100` renders all 80 (title-only refs appear
  only after every summary-bearing ref).
- **Digest path** — `_normalize_digest_product_context` caps identically
  (60 default / 100 override), same order as the report path.
- **`selected N of M` never inverts** — `(k, m) ∈ {(1,12), (9,20),
  (12,60)}` all render `selected k of m`; the discriminating case
  `ref_limit=8` with 9 findings renders **`精选 8 条详述 · selected 8 of
  8`** (NEVER `selected 9 of 8`), on both the report and digest paths; the
  general invariant `len(key_findings) ≤ len(references)` holds.
- **Config precedence** — a config declaring `output.ref_limit: 30` drives
  the default; the explicit `ref_limit=50` param wins over it.

`tests/output/test_enterprise_briefing_coverage.py` — **9 of 20 preserved**
(regression guard that the enterprise product still renders its full
section coverage under the cap).

## Fixture reconciliation (side effect of the #8 en-seed)

The #8 seed activated the `#309` language filter for ai-commercial, which
drops entries with an empty/unknown `language`.  Two pre-existing test
fixtures predated the `language` field and gained `language: "en"`:

- `tests/output/test_domain_exclude_keywords.py` (`_entry`, line 105-107 —
  "Required by the #8 seed fallback + #309 language filter: untagged
  entries are dropped before synthesis").
- `tests/output/test_source_label_surfaces.py` (`_stale_entry`, line 85).

Both suites pass with the reconciled fixtures (**23** and **21** passed
respectively).

## Commits

The PR is **squash-merged**, so the 8 pre-squash commits are replaced by
one merge commit on `backup/main` (see `fix/backup-main-issues-8-11` →
backup `main`).  Both references are valid:

Pre-squash subjects (the `fix/backup-main-issues-8-11` branch history):

1. `fix(output): seed-fallback default_language in _resolve_effective_language (#8)`
2. `fix(output): seed-merge English theme keywords for ai-commercial grouping (#9)`
3. `fix(output): blocklist generic theme labels + synonym merge (#9)`
4. `fix(output): enforce action granularity in premium/enterprise synthesis (#10)`
5. `feat(output): cap references with ref_limit (default 60) (#11)`
6. `fix(validation): restore #351 V5 named-year exemption (#4)`
7. `docs(backup): closure evidence for #8-#11`
8. (labels + delivery are repo metadata / the merge itself)

Post-squash: **the final merge SHA on `backup/main`** (PR title
`fix(output): resolve #8-#11 + merge #351 V5 fix`) is the authoritative
commit reference.

Known pre-existing failure documented in `close-backup-issue-6-7.md`
(`test_release_workflow` — the backup mirror removed release-please.yml)
does not recur here; `test_video_integration` (WSL Chrome render) and
`test_coverage_matrix` (fails on unchanged HEAD) are the only
pre-existing environment failures in the suites above.
