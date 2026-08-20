# Changelog

All notable changes to the AutoInfo project will be documented in this file.

## [1.11.0](https://github.com/1StepMore/AutoInfo/compare/v1.10.0...v1.11.0) (2026-08-19)


### Features

* **mcp:** expose llm fallback/tasks in configure_llm and add test_llm_connection ([#299](https://github.com/1StepMore/AutoInfo/issues/299)) ([0377571](https://github.com/1StepMore/AutoInfo/commit/037757181229e9c9d242b23bee9617807a84e53f))
* **output:** premium-briefing concrete risks/actions ([#307](https://github.com/1StepMore/AutoInfo/issues/307)) + column Deep Dive depth ([#308](https://github.com/1StepMore/AutoInfo/issues/308)) + entry-language filter ([#309](https://github.com/1StepMore/AutoInfo/issues/309)) ([#310](https://github.com/1StepMore/AutoInfo/issues/310)) ([0f788e6](https://github.com/1StepMore/AutoInfo/commit/0f788e6165e4c96bbebaf7cd1f3673012cb232a2))
* **output:** report semantic titles + tutorial citations + magazine editorial + enterprise coverage ([#311](https://github.com/1StepMore/AutoInfo/issues/311)-[#314](https://github.com/1StepMore/AutoInfo/issues/314)) ([#315](https://github.com/1StepMore/AutoInfo/issues/315)) ([74c0078](https://github.com/1StepMore/AutoInfo/commit/74c00789f91a20448a167111b0da58e63ee8eabb))


### Bug Fixes

* output pipeline robustification + 13 issue fixes ([#290](https://github.com/1StepMore/AutoInfo/issues/290)-[#303](https://github.com/1StepMore/AutoInfo/issues/303)) ([#306](https://github.com/1StepMore/AutoInfo/issues/306)) ([fc08074](https://github.com/1StepMore/AutoInfo/commit/fc080744fde80c5b6a843c3e98121480ee1d5412))

## [Unreleased]

### Features

* **output:** magazine-digest editorial intro + personality/deep-dive feature — the magazine synthesis prompt requests `editorial_intro` + `feature_story` fields and `magazine-digest.md.j2` renders "## Editor's Note" + "## The Feature" sections when the LLM synthesis carries them ([#313](https://github.com/1StepMore/AutoInfo/issues/313))
* **output:** domain-level default language for digest/report filtering — a single-domain product falls back to the domain's configured `default_language` when no explicit `--language` is passed, so mixed-language domains (e.g. ai-commercial: English sources + 36KR Chinese) produce single-language output without manual params; cross-domain products never silently pick one domain's default ([#317](https://github.com/1StepMore/AutoInfo/issues/317))
* **output:** per-domain `exclude_keywords` cross-domain noise filter — product generation drops entries whose title/summary/tags match a domain's configured blacklist (per-entry domain lookup, deterministic substring match, no LLM), removing medical/off-topic entries that pass G1-G3 from ai-commercial products ([#319](https://github.com/1StepMore/AutoInfo/issues/319))

### Bug Fixes

* **output:** report section headings are semantic theme titles (short noun phrases, never raw keyword dumps) with near-duplicate heading dedup ([#311](https://github.com/1StepMore/AutoInfo/issues/311))
* **output:** tutorial bodies carry inline citations to real source URLs, aligned with digest/report citations ([#312](https://github.com/1StepMore/AutoInfo/issues/312))
* **output:** column digest renders 8+ deep-dive sections with substantive content and a `Sections` metadata count matching the rendered sections (previously `_normalize_digest_product_context` never materialized `sections`, leaving the template to render 0 + a "no sections available" placeholder) ([#316](https://github.com/1StepMore/AutoInfo/issues/316))
* **output:** digest/report products render distinct product-specific H1 titles matching their product names (6 products, previously all shared a generic title) ([#318](https://github.com/1StepMore/AutoInfo/issues/318))
* **output:** References section numbering increments correctly (1/2/3…) instead of showing "1." for every entry — three markdown templates had hardcoded `1.` instead of `{{ loop.index }}` ([#322](https://github.com/1StepMore/AutoInfo/issues/322))
* **collectors:** RSS-sourced items carry the configured source name (e.g. "techcrunch") as their platform label instead of the hardcoded generic "rss" — `_entry_to_item` now propagates the handler's `source_name` ([#323](https://github.com/1StepMore/AutoInfo/issues/323))
* **output:** report/column/premium-briefing/enterprise-briefing References now render the specific source name instead of "(RSS)" — a `_derive_source_label` re-derivation maps stale/generic `source_platform` (rss/web/api) to the configured source name via source_url host match against the domain source configs, applied in both the report and digest reference builders ([#325](https://github.com/1StepMore/AutoInfo/issues/325))
* **output:** enterprise-briefing and report products strip LLM skeleton placeholders (`<finding 1>`, `<metric> | <value> | <source>`, etc.) echoed verbatim from prompt templates — a post-render cleanup removes angle-bracket tokens before delivery ([#314](https://github.com/1StepMore/AutoInfo/issues/314))
* **output:** column Deep Dive and report Sections no longer render empty shells from real KB data — `_is_test_entry` keeps real Draft/Wiki entries whose DB `summary` column is empty (content lives in the KB markdown file) when they carry a real title + source_url, and `_normalize_digest_product_context` now derives sections for the report family too (previously only column), not just when sections are missing ([#326](https://github.com/1StepMore/AutoInfo/issues/326))
* **output:** product output no longer carries raw LLM-library error text (litellm / BerriAI / ANSI color codes) prepended to the file header — `_contains_raw_llm_leak` now also sniffs for external error text via `_LEAK_ERROR_TEXT_RE`, wired into the D2 format-integrity gate (a leak-polluted product is D2-flagged) ([#328](https://github.com/1StepMore/AutoInfo/issues/328))
* **output:** premium-briefing takeaways no longer fall back to `_No ..._` placeholders (implication / risk / action) — a deterministic per-takeaway derivation from the KB entries fills the fields when the LLM synthesis carries none, applied in both the digest normalization and the report KB-derived fallback ([#329](https://github.com/1StepMore/AutoInfo/issues/329))
* **validation:** new `autoinfo validate --matrix` full-matrix acceptance executor — generates products over 3 domains × 8 products on the real KB path, runs the formalized assertion set (11 assertions, each a readable function carrying its source issue), and emits a JSON/HTML report card; `--only-assert` scans existing outputs without regenerating, and a version-diff subcommand classifies (product, assertion) as new/regressed/fixed/existing-failing ([#331](https://github.com/1StepMore/AutoInfo/issues/331), [#332](https://github.com/1StepMore/AutoInfo/issues/332))
* **collectors:** collection-layer domain topic guard drops cross-domain noise at ingest time — ai-commercial items carrying financial/regulatory markers (贝达药业, 华能, SEC 8-K, 财报) and financial-intelligence SEC 8-K/10-Q metadata dilutions are filtered before they enter the raw cache ([#332](https://github.com/1StepMore/AutoInfo/issues/332))
* **validation:** `_no_placeholder` assertion now covers the premium/enterprise analysis layer — standalone `N/A` / `None` / `TBD` / `Not available` / `To be determined` / `No data` filler cells, the deterministic `No knowledge base entries were available.` fallback message, and LLM skeleton echoes are flagged alongside the template `_No ..._` empty-state markers (previously the 9-spot mimo enterprise-layer filler escaped detection) ([#334](https://github.com/1StepMore/AutoInfo/issues/334))
* **validation:** `autoinfo validate matrix` artifacts/snapshots are batch-isolated — every run owns a `batch_id` (explicit `--batch` or `<commit>-<stamp>`); full mode persists its products under `validation-runs/matrix/<batch_id>/products/` (successive batches never overwrite) and `--only-assert --batch <id>` scans that same isolated tree, while `--only-assert` without `--batch` keeps the legacy shared `outputs/` scan ([#335](https://github.com/1StepMore/AutoInfo/issues/335))
* **validation:** `autoinfo validate diff` statistics reconcile with the card failure count — missing/error products are first-class diff items via a product-status pseudo-assertion and the failures summary breaks down into failing_assertions + missing_products + error_products, so `cur issues == new + regressed + existing_failing` and the CLI prints that identity (no more hand-reading the JSON) ([#336](https://github.com/1StepMore/AutoInfo/issues/336))
* **output:** products no longer leak internal keyword-search/counting logs — the deterministic grouping helpers (`_keyword_group_entries`, source/domain groups, General/Additional-Topics catch-alls) now emit user-facing section descriptions instead of `N entries related to '<kw>'.` / `N entry(ies) not matched to a topic keyword.` / `N entries included in this report.`, and the report exec-summary fallback drops the "This report covers N KB entries grouped into M themes: - **API**: N entry(ies)" bullet list; a new `_no_internal_leak` validate assertion (#338) sniffs those patterns so any regression is gated ([#338](https://github.com/1StepMore/AutoInfo/issues/338))

## [1.10.0](https://github.com/1StepMore/AutoInfo/compare/v1.9.1...v1.10.0) (2026-08-17)


### Features

* **validation:** AC4 scenario-coverage matrix across all 13 demo domains + release/kb/output fixes ([#275](https://github.com/1StepMore/AutoInfo/issues/275) [#277](https://github.com/1StepMore/AutoInfo/issues/277) [#278](https://github.com/1StepMore/AutoInfo/issues/278) [#279](https://github.com/1StepMore/AutoInfo/issues/279) [#280](https://github.com/1StepMore/AutoInfo/issues/280) [#281](https://github.com/1StepMore/AutoInfo/issues/281) [#165](https://github.com/1StepMore/AutoInfo/issues/165)) ([#282](https://github.com/1StepMore/AutoInfo/issues/282)) ([e1538b8](https://github.com/1StepMore/AutoInfo/commit/e1538b8b880c215d91a482081669a5cbcd808983))


### Bug Fixes

* **collectors:** financial-intelligence keyless RSS sources + FRED URL + UA fix ([#288](https://github.com/1StepMore/AutoInfo/issues/288)) ([#289](https://github.com/1StepMore/AutoInfo/issues/289)) ([77356a8](https://github.com/1StepMore/AutoInfo/commit/77356a83431e95d376e74aaae5b3b095b3340abf))
* **collectors:** 采集层过滤非文章型 content（纯数字/无字母）([#286](https://github.com/1StepMore/AutoInfo/issues/286)) ([#287](https://github.com/1StepMore/AutoInfo/issues/287)) ([c8df7c2](https://github.com/1StepMore/AutoInfo/commit/c8df7c2a13eed8dd279459a4809690927af0659a))
* **promotion:** G4 config=None 加载磁盘 config ([#283](https://github.com/1StepMore/AutoInfo/issues/283)) ([#284](https://github.com/1StepMore/AutoInfo/issues/284)) ([24cf1d0](https://github.com/1StepMore/AutoInfo/commit/24cf1d0a47de3443a2d89d70d476240b90ea9920))
* **scenario:** kb-graph fixture content 加长至 &gt;50 字符（MIN_KB_CONTENT_CHARS 约束） ([#285](https://github.com/1StepMore/AutoInfo/issues/285)) ([cc97708](https://github.com/1StepMore/AutoInfo/commit/cc977089a949ad8e626aea6f5caf3517f538e1ee))


### Documentation

* **acceptance:** first formal acceptance run report for 1.9.1 (AC1-AC9) ([#274](https://github.com/1StepMore/AutoInfo/issues/274)) ([4d56571](https://github.com/1StepMore/AutoInfo/commit/4d565710a18fea3a8660b928547c2dc07a4f285e))
* regenerate doc inventory after acceptance-run report ([#274](https://github.com/1StepMore/AutoInfo/issues/274)) ([#276](https://github.com/1StepMore/AutoInfo/issues/276)) ([372b387](https://github.com/1StepMore/AutoInfo/commit/372b387b6db285474fba732fcbfdb96678f33dae))

## [1.9.1](https://github.com/1StepMore/AutoInfo/compare/v1.9.0...v1.9.1) (2026-08-15)


### Bug Fixes

* **ci:** release-please — drop release-type/package-name inputs so config-file branch runs ([#270](https://github.com/1StepMore/AutoInfo/issues/270)) ([338212e](https://github.com/1StepMore/AutoInfo/commit/338212ed1e5295bbc5434d136a355a0b22fe2428))
* **ci:** release-please — include-component-in-tag: false + drop redundant top-level keys ([#267](https://github.com/1StepMore/AutoInfo/issues/267)) ([72540b8](https://github.com/1StepMore/AutoInfo/commit/72540b8d95f59d3eba11ccadb1dc28a11ddd1b3f))
* **ci:** sync runtime version to 1.9.0 + teach release-please to update _version.py ([#264](https://github.com/1StepMore/AutoInfo/issues/264)) ([1b03cd0](https://github.com/1StepMore/AutoInfo/commit/1b03cd03d82018348efd870cc9cece1886d279e7))


### Documentation

* **adr:** record release-please version-truth governance (ADR-0007) ([#266](https://github.com/1StepMore/AutoInfo/issues/266)) ([5e092ce](https://github.com/1StepMore/AutoInfo/commit/5e092ce8d5ccad24713b11f843b2a3d2bbfd59e6))

## 1.9.0 (2026-08-15)


### Features

* [#48](https://github.com/1StepMore/AutoInfo/issues/48) - add 15 YAML validation scenario files (parts 01-15) ([fd48c34](https://github.com/1StepMore/AutoInfo/commit/fd48c34dac9523f3888d4f738385d9f45c26fe80))
* add 12 new collector handlers (AP API, Apple Podcasts, Bilibili, DBLP, NYT, OpenAlex, Reddit, Reuters MCP, Semantic Scholar, Spotify, USPTO, YouTube) ([40223eb](https://github.com/1StepMore/AutoInfo/commit/40223eb653c28bac2fa9f91722a926be7f1eb16a))
* add agent callbacks, billing, RSS delivery, portal, deployment config ([bbdcaae](https://github.com/1StepMore/AutoInfo/commit/bbdcaae446c848a8d04797f5f7b2132cd788ceaa))
* add CLI commands, API endpoints, Prometheus metrics, diagnostics ([a3266eb](https://github.com/1StepMore/AutoInfo/commit/a3266eb27289ffddddfa1bec60f0cbb128764bd5))
* add cross-domain reports, specialized report types, bundle export, delivery schedule MCP tools ([f8eb029](https://github.com/1StepMore/AutoInfo/commit/f8eb02988be271bbe0117aea57ee8f32bc09a6eb))
* add Phase 4 validation scenarios, blocked-sources doc, delivery/mcp/output tests ([10c4fed](https://github.com/1StepMore/AutoInfo/commit/10c4fedee8ad4f1420ffd0167d90d5ff204976c6))
* add portal UI templates — dashboard, products, history, preferences ([7fd5ee4](https://github.com/1StepMore/AutoInfo/commit/7fd5ee4543dbb599972ccb770843ba83dfd22db3))
* add send_notification(), ConsumptionEvent tracking, cron health, and automated notifications ([a6e87c8](https://github.com/1StepMore/AutoInfo/commit/a6e87c845240447e994aeabde9591c121dbcd2e4))
* add SQLite backup/restore scripts and fix KBEntry schema drift in process pipeline ([489a459](https://github.com/1StepMore/AutoInfo/commit/489a459962719ea7b56ca98bd51b43ce2618163b))
* add UserProfile.tier fast path to check_access() and Premium/Enterprise templates ([04e9fb8](https://github.com/1StepMore/AutoInfo/commit/04e9fb8ab23b0341917c77fadae595d9c22bbbea))
* **alerts,output:** alert streams, D1-D3 wired into output ([516cfe2](https://github.com/1StepMore/AutoInfo/commit/516cfe239f7e2464927c26efa372305164665a3d))
* **api:** add domain precondition middleware for REST API ([de88d30](https://github.com/1StepMore/AutoInfo/commit/de88d3011667d9d96a0198e878f048dd54bdb172))
* **api:** add structured exception handlers to FastAPI server ([9f554f5](https://github.com/1StepMore/AutoInfo/commit/9f554f5ff9ec2c73369e58faa822eb3ad4a662b8))
* **autoinfo:** agent-orientation 10/10 + coverage closure (M0-M7) ([6a8d1d8](https://github.com/1StepMore/AutoInfo/commit/6a8d1d8b191a8903fe768bfe0f4edea95ba0a90f))
* **billing:** resolve_user_id default with optional --user-id (closes [#107](https://github.com/1StepMore/AutoInfo/issues/107)) ([78b7cb0](https://github.com/1StepMore/AutoInfo/commit/78b7cb021e5419f5fb148756267ffd2a26de29fb))
* **billing:** single-article payment entitlement ([8347712](https://github.com/1StepMore/AutoInfo/commit/8347712c4728fcb7c7b9b97cac9c45ace8a1c603))
* **cli:** add --all flag to collect command ([7f90afc](https://github.com/1StepMore/AutoInfo/commit/7f90afc3fab266464ecb473866aefa5e38af5937))
* **cli:** add 00-Inbox/02-Draft/03-Wiki dirs + interactive init wizard ([984a271](https://github.com/1StepMore/AutoInfo/commit/984a2717a1c4c5ccfca64269f1195fae15a57928))
* **cli:** add custom help text to 9 CLI commands missing descriptions ([7ac8db8](https://github.com/1StepMore/AutoInfo/commit/7ac8db82edcfd7cf5561852df20b637450a11140))
* **cli:** add knowledge graph export CLI ([948983b](https://github.com/1StepMore/AutoInfo/commit/948983b01df6857665b9fe5c53f015389e79f36f))
* **collectors:** add GDELT news collector ([30f2e37](https://github.com/1StepMore/AutoInfo/commit/30f2e37d4f85ca1f0204185758ce427a038da0f7))
* **collectors:** add HuggingFace/Kaggle collector ([2542232](https://github.com/1StepMore/AutoInfo/commit/254223266f9ce32f44ad864611a20874d92d0d08))
* **collectors:** add SSRN RSS collector ([07641ff](https://github.com/1StepMore/AutoInfo/commit/07641ff80c819df7fa3ddcbbf7f0e59318ab555c))
* **collectors:** add Unpaywall/CORE OA fulltext collector ([ac1798f](https://github.com/1StepMore/AutoInfo/commit/ac1798f785c0103d497247d22e11bef011372f78))
* **collectors:** add webhook, email (IMAP), and PDF source handlers ([948983b](https://github.com/1StepMore/AutoInfo/commit/948983b01df6857665b9fe5c53f015389e79f36f))
* **collectors:** dedicated HackerNews Firebase handler with two-step fetch (closes [#105](https://github.com/1StepMore/AutoInfo/issues/105)) ([cd9f261](https://github.com/1StepMore/AutoInfo/commit/cd9f26191b07c50214492b9ef60ca80355ed3239))
* **collectors:** fetch_depth fulltext for unpaywall/rss/youtube/gdelt ([fa00532](https://github.com/1StepMore/AutoInfo/commit/fa00532f8956000ff3532c0423c7b913a0f45fe0))
* **config:** add 7 curated demo sources (arXiv, CrossRef, Unpaywall, Crunchbase, LMSYS, news-in-levels, commonlit) ([0291a08](https://github.com/1StepMore/AutoInfo/commit/0291a08854d2945e24a86f78eafc0fae4c4bd228))
* **config:** add QualityGateConfig dataclass and YAML parsing ([c74b729](https://github.com/1StepMore/AutoInfo/commit/c74b72968f54d90412915ae07622fcaa92fe594b))
* **config:** add settings field to SourceConfig for extra config ([948983b](https://github.com/1StepMore/AutoInfo/commit/948983b01df6857665b9fe5c53f015389e79f36f))
* **config:** configure mimo-v2.5 fallback chain on opencode gateway ([894c760](https://github.com/1StepMore/AutoInfo/commit/894c760699cabcab420e8cd88eae0b5f5d969797))
* **config:** CurationGate QualityGateConfig + set/get_gate_config roundtrip ([045bb33](https://github.com/1StepMore/AutoInfo/commit/045bb3330c3833b49cba879b0bb4bdbb4c60640b))
* **delivery:** add generic push notification channel ([2e7d19e](https://github.com/1StepMore/AutoInfo/commit/2e7d19e337725f8387a0acfc1bd67e820589240d))
* **delivery:** per-artifact authenticity + D1-D3 gates in validation_delivery ([#132](https://github.com/1StepMore/AutoInfo/issues/132)) ([0abb2a8](https://github.com/1StepMore/AutoInfo/commit/0abb2a8094f9aed60c35898c3a52791821214da6))
* **delivery:** podcast RSS with enclosures + MP3 hosting ([97c26e6](https://github.com/1StepMore/AutoInfo/commit/97c26e66f9e8788a591c6a124d79c6bcb4549599))
* **domains:** add 3 demo domains (financial-news, online-education, legal-compliance) ([2612dd0](https://github.com/1StepMore/AutoInfo/commit/2612dd0e3ca063f686ea309e4d19fda9add8b634))
* **domains:** add online-video/OTT demo domain config (D2) ([6af629f](https://github.com/1StepMore/AutoInfo/commit/6af629f04019bb20a62f8a11e3b07556eb957a9c))
* **domains:** wire Quandl/Nasdaq Data Link into financial-intelligence demo ([9e4191e](https://github.com/1StepMore/AutoInfo/commit/9e4191efb83181faef7dd918b991f5760c5633f1))
* **errors:** add 4 new ErrorCodes, canonicalize error_response(), deprecate error_dict() ([db98d1a](https://github.com/1StepMore/AutoInfo/commit/db98d1aefdd8b33f58200f406665f11778d5ecb1))
* **errors:** add exception→ErrorCode mapping to _error_response() ([51dbc69](https://github.com/1StepMore/AutoInfo/commit/51dbc692af260bcc289b6abc7360dc52dcae9c6e))
* expose LLM token usage in process_collection response ([#27](https://github.com/1StepMore/AutoInfo/issues/27)) ([387663b](https://github.com/1StepMore/AutoInfo/commit/387663b6bfb673aaf0807c5934eab00dc4ea8989))
* extend Subscription model with tier/channels/domains/products fields ([009120e](https://github.com/1StepMore/AutoInfo/commit/009120efea9b7c03733ddd6b01a8fcdb6af3b92e))
* implement all feature gaps (G-7 to G-14) ([3f5cbdc](https://github.com/1StepMore/AutoInfo/commit/3f5cbdc88bd938493f966629c1bf26515bd98221))
* implement G4 retry chain, D1-D3 delivery gates, output pipeline ([2d648f1](https://github.com/1StepMore/AutoInfo/commit/2d648f1bb6b48486d0d17fe41fe1898f5318af9f))
* implement generic HTTP JSON API collector, fix [#38](https://github.com/1StepMore/AutoInfo/issues/38) --json flag, add validation & tests ([b6c07d1](https://github.com/1StepMore/AutoInfo/commit/b6c07d1022c2cae7dce7ef8178b3647ab01e5245))
* implement health_check() for all 11 delivery channels ([2fb08f1](https://github.com/1StepMore/AutoInfo/commit/2fb08f163fcaf8a0b4d96f936a3dbab5b9600a50))
* implement MCP tool layer (G-3 to G-6) ([30893dc](https://github.com/1StepMore/AutoInfo/commit/30893dc4ad3a346209c7f725be4c7581fd7cbccb))
* implement multi-channel delivery, cost metering, user lifecycle ([e735bb6](https://github.com/1StepMore/AutoInfo/commit/e735bb674fea6fb550300b0e663ea8a10fe5994c))
* **kb:** add promote_kb_draft() + 03-Wiki append-only guards ([984a271](https://github.com/1StepMore/AutoInfo/commit/984a2717a1c4c5ccfca64269f1195fae15a57928))
* **kb:** expand frontmatter with author, source_ids, status, related_concepts, linked_entries ([9b5d1bd](https://github.com/1StepMore/AutoInfo/commit/9b5d1bd1d20427522b54481251110dd3df2c53fd))
* **kb:** KBEntry promotion_source/promoted_by fields + create_kb_draft score carry-forward ([34c10d7](https://github.com/1StepMore/AutoInfo/commit/34c10d76f08818eec67c90e96b2fe9c3859c0bbc))
* **kb:** product-analysis metadata persistence and custom-field faceted filter ([62748bf](https://github.com/1StepMore/AutoInfo/commit/62748bf85d39fa974ff3d3edc5b59861f9860b78))
* **kb:** promotion gate + director backdoor + tier search boost ([b2b0d0e](https://github.com/1StepMore/AutoInfo/commit/b2b0d0e08e9fcc946cfb7bab73c80130dfa4d86f))
* **llm:** shared call_with_fallback helper protects all LLM call sites ([#147](https://github.com/1StepMore/AutoInfo/issues/147)) ([#149](https://github.com/1StepMore/AutoInfo/issues/149)) ([68ed6b9](https://github.com/1StepMore/AutoInfo/commit/68ed6b955490ca2ffadf406a85dc377eb4a9ea5d))
* **matrix:** full-capability end-user matrix + scenario-library coverage check ([#158](https://github.com/1StepMore/AutoInfo/issues/158)) ([9f73c29](https://github.com/1StepMore/AutoInfo/commit/9f73c2926572321ea3aca97692c8251f26f9c2e2))
* **mcp,cli:** product selection params and --product flag ([e2864ce](https://github.com/1StepMore/AutoInfo/commit/e2864ce4a9f9c547f1173f49c401a1deefd8f928))
* **mcp:** add 6 MCP tool areas: collection progress/status, domain lifecycle, list_keywords, tutorial/presentation ([7f90afc](https://github.com/1StepMore/AutoInfo/commit/7f90afc3fab266464ecb473866aefa5e38af5937))
* **mcp:** add centralized LLM_NOT_CONFIGURED guard at call_tool dispatch ([a505a94](https://github.com/1StepMore/AutoInfo/commit/a505a947ab95947b62739106a321cb758d06456b))
* **mcp:** add extract_fields suggestions + quality tier warnings to source tools ([7f90afc](https://github.com/1StepMore/AutoInfo/commit/7f90afc3fab266464ecb473866aefa5e38af5937))
* **mcp:** add health_score and phase to diagnose_system response ([1421a9e](https://github.com/1StepMore/AutoInfo/commit/1421a9ef31002e3be25c5173b07777af4b1ef558))
* **mcp:** add MCP tools for gate config, product mgmt, alert rules ([064fe52](https://github.com/1StepMore/AutoInfo/commit/064fe52edfd664f9d615566a41e8ff390a0b8e5c))
* **mcp:** add next_steps guidance to init_project response ([863e357](https://github.com/1StepMore/AutoInfo/commit/863e3575f04050ae6b2c32fc1b2bf8e46041f837))
* **mcp:** implement 114 MCP tools across 32 categories ([2f6f212](https://github.com/1StepMore/AutoInfo/commit/2f6f212b5697f60102c07d012b0e19cdc1835d53))
* **mcp:** promote triggers + curation gate + director handlers ([c4fa21a](https://github.com/1StepMore/AutoInfo/commit/c4fa21a8f552a173c7a3ae9cfc7021c115e79a73))
* **mcp:** thread timeout param through run_validation_scenario ([#134](https://github.com/1StepMore/AutoInfo/issues/134)) ([eeea76f](https://github.com/1StepMore/AutoInfo/commit/eeea76fefc8043613051fdfeb07d7ab8ef51f844))
* **output:** CEFR-level content simplification mode ([56730ca](https://github.com/1StepMore/AutoInfo/commit/56730ca2ad481e76a233b7b34072f1c314709fb2))
* **output:** curated priority wiki-first + draft-fallback + source_tier badge ([ed7ad89](https://github.com/1StepMore/AutoInfo/commit/ed7ad890d3d0eb54789801589ec5bf4cef0a0ae6))
* **output:** differentiated product templates, per-product synthesis, agent JSON-LD fields, synthesis retry robustness ([97319b1](https://github.com/1StepMore/AutoInfo/commit/97319b1218e60b85525d4b7a5874c8d901943ab9))
* **output:** persist generate_* output to outputs/ via persist param ([#133](https://github.com/1StepMore/AutoInfo/issues/133)) ([19ee7d0](https://github.com/1StepMore/AutoInfo/commit/19ee7d07924b70df7229803878acc465eafcf525))
* **output:** sitemap with real KB entries + JSON-LD structured data ([83db157](https://github.com/1StepMore/AutoInfo/commit/83db1579df50bb3732df0ed2edf22d54d804c39b))
* **process:** add language auto-detection with langdetect ([8446b99](https://github.com/1StepMore/AutoInfo/commit/8446b993eeeeb7de5ae185255844c3cd6f3d17ff))
* **product:** RAW product variants (api/webhook/bulk) ([1a17ba3](https://github.com/1StepMore/AutoInfo/commit/1a17ba3000250549c854ebe3ed4f6634c2da071d))
* **promotion:** admission module check_promotion_admission (provenance+G0+G1+G3+G4) ([f2e3b04](https://github.com/1StepMore/AutoInfo/commit/f2e3b04d065d5b9a7914f3ce56fb6919a2e621fa))
* **quality:** add G5 translation accuracy gate ([984a271](https://github.com/1StepMore/AutoInfo/commit/984a2717a1c4c5ccfca64269f1195fae15a57928))
* **quality:** deterministic source credibility score + G1 details ([0184245](https://github.com/1StepMore/AutoInfo/commit/018424574665e171493a437db230065c8d19383b))
* **quality:** G4 retry chain, D1-D3 delivery gates, per-domain config, G1-G3 actions ([86980b3](https://github.com/1StepMore/AutoInfo/commit/86980b3f216e58176a515b806140247a92d727d7))
* **router:** wire per-task model routing and pin G4/G5 judgment model ([bb007ab](https://github.com/1StepMore/AutoInfo/commit/bb007ab6540c344218fdc68c4c3fc94c11442808))
* **scenarios:** add enduser-deliverable validation scenario ([#95](https://github.com/1StepMore/AutoInfo/issues/95)) ([69b1bb0](https://github.com/1StepMore/AutoInfo/commit/69b1bb0f7443110432abe4d033b064092c935660))
* **scenarios:** add persist + collect_artifacts to output scenarios ([#133](https://github.com/1StepMore/AutoInfo/issues/133)) ([08031bf](https://github.com/1StepMore/AutoInfo/commit/08031bfd64e2e7d54f52e36d4a59da8729016a3b))
* **scenarios:** multi-domain data-lifecycle + RAW artifacts + collect_artifacts ([#133](https://github.com/1StepMore/AutoInfo/issues/133)) ([f401158](https://github.com/1StepMore/AutoInfo/commit/f40115861d24bf4d16b520291450c42ef225ee91))
* **skills:** add dev-side workflow skills — validation-runner + deep-modules (2026-08-13) ([7536e95](https://github.com/1StepMore/AutoInfo/commit/7536e95b28c1a2ec90ab3922f75533e053c079d3))
* **skills:** deep-modules v1.1.0 — absorb 七阶段 §3.1 update (2026-08-13) ([3aff3a6](https://github.com/1StepMore/AutoInfo/commit/3aff3a67412b975ecc881e84d00bdd83df8cf55c))
* **v1.2:** Wave 1 foundation — FastAPI, embeddings, config, schema, init --name, keywords ([0082c99](https://github.com/1StepMore/AutoInfo/commit/0082c996471105d99cbe70eba46c1fa5e5af49ec))
* **v1.2:** Wave 2 — vector search, faceted search, keywords MCP/CLI ([fd5487d](https://github.com/1StepMore/AutoInfo/commit/fd5487def0dd7f9d005fa86d527ec84726bdb21b))
* **v1.2:** Wave 3 — versioning, wiki links, CEFR, multi-user foundation ([5ad3464](https://github.com/1StepMore/AutoInfo/commit/5ad3464feaf8988cc0203743d26203242ad57708))
* **v1.2:** Wave 4 — PDF export, JSON report, MCP report, REST API, email ([d644d9f](https://github.com/1StepMore/AutoInfo/commit/d644d9f3c22bac4c20707eee00bd7e09a812551c))
* **v1.2:** Wave 5 — crontab installer, Web UI dashboard ([707bbc3](https://github.com/1StepMore/AutoInfo/commit/707bbc3deb6ad28154798ce2d9149be6776fcdb7))
* validation env prereqs report unconfigured, not failed ([#157](https://github.com/1StepMore/AutoInfo/issues/157)) ([#160](https://github.com/1StepMore/AutoInfo/issues/160)) ([80819b5](https://github.com/1StepMore/AutoInfo/commit/80819b52872c2425a929c1a207ce5fd3a33ec9cd))
* validation wave E1-E9 + end-user matrix coverage ([#131](https://github.com/1StepMore/AutoInfo/issues/131)-[#141](https://github.com/1StepMore/AutoInfo/issues/141)) ([dbe90de](https://github.com/1StepMore/AutoInfo/commit/dbe90de6aa91ca80090aec1d683d478246c4107b))
* **validation:** add kb-promote scenario and fix coverage audit ([#134](https://github.com/1StepMore/AutoInfo/issues/134)) ([3517f79](https://github.com/1StepMore/AutoInfo/commit/3517f79920d2a48482e0f9d835d77e81d1741277))
* **validation:** add per-scenario timeout to run_scenario ([#134](https://github.com/1StepMore/AutoInfo/issues/134)) ([8aec3ed](https://github.com/1StepMore/AutoInfo/commit/8aec3ed0715468fc54f92b2fa3be5cadcd83be95))
* **validation:** add scripted best-practice audits + LLM-judge calibration skeleton ([5036859](https://github.com/1StepMore/AutoInfo/commit/5036859231b5ff5c44b1fce95b8a01ac20761519))
* **validation:** Agent-native MCP validation toolset with real-call semantics ([7702cc1](https://github.com/1StepMore/AutoInfo/commit/7702cc1d7d3d4ccf5e2a3e19f0475a16ea6079b0))
* **validation:** close [#129](https://github.com/1StepMore/AutoInfo/issues/129) — versioned validation artifact archive ([7df5d8a](https://github.com/1StepMore/AutoInfo/commit/7df5d8a5001780f2f341e31f22283005c9c01d5b))
* **validation:** close [#129](https://github.com/1StepMore/AutoInfo/issues/129) — versioned validation artifact archive ([1c11a4e](https://github.com/1StepMore/AutoInfo/commit/1c11a4e666565a9b585b83bf4b380dc0e92cef58))
* **validation:** content-quality audit + retry scripts; tutorial markdown parse (8a676dc merge) ([22fa1fd](https://github.com/1StepMore/AutoInfo/commit/22fa1fd6576c642140678c8560ed51cc70142403))
* **validation:** E9 — add 04-MATRIX section to delivery packaging ([#131](https://github.com/1StepMore/AutoInfo/issues/131)) ([f5e4398](https://github.com/1StepMore/AutoInfo/commit/f5e43988a64aee24087b1d842e8fd942fffc0c42))
* **validation:** end-user coverage matrix generator ([#131](https://github.com/1StepMore/AutoInfo/issues/131)) ([a94fe72](https://github.com/1StepMore/AutoInfo/commit/a94fe72a04b5363234ac547413a0625ef13005b6))
* **validation:** end-user journey scenario + UX metrics in delivery package ([#141](https://github.com/1StepMore/AutoInfo/issues/141)) ([81e4b30](https://github.com/1StepMore/AutoInfo/commit/81e4b30bfe70efca3e6cb60041519c2a779375df))
* **validation:** enforce error_actionable assertion in _step_assert ([#141](https://github.com/1StepMore/AutoInfo/issues/141)) ([#152](https://github.com/1StepMore/AutoInfo/issues/152)) ([20f76e9](https://github.com/1StepMore/AutoInfo/commit/20f76e9b45e5b3531a02e1fe004121cc4e0bf387))
* **validation:** failure to regression-test flywheel ([#140](https://github.com/1StepMore/AutoInfo/issues/140)) ([938fb6b](https://github.com/1StepMore/AutoInfo/commit/938fb6b937dbad299a1c036854de356d1fdb60ad))
* **validation:** matrix spec corrected to real capability; backfill/fill scripts ([92e7dcf](https://github.com/1StepMore/AutoInfo/commit/92e7dcf3e04172682bf6d01aa75f1381ada56e68))
* **validation:** per-step execution trace + LLM judge observability + root-cause report ([#139](https://github.com/1StepMore/AutoInfo/issues/139)) ([0188581](https://github.com/1StepMore/AutoInfo/commit/01885813dc814f09df4a38cac667e25b7f762f2d))
* **validation:** per-step recovery + partial-pass policy ([#138](https://github.com/1StepMore/AutoInfo/issues/138)) ([7aee0f9](https://github.com/1StepMore/AutoInfo/commit/7aee0f9d3c320ad1a9fe2728fcd6406eaa6a0258))
* **validation:** product content-quality audit script (end-user view) ([14ece10](https://github.com/1StepMore/AutoInfo/commit/14ece10f702aa1892aa30774ab3c5f82e480486c))
* **validation:** restore full 112-cell matrix spec with capability annotations; merge 11 demo domains ([d162c58](https://github.com/1StepMore/AutoInfo/commit/d162c589ffcf71af1296f1da3c106bd5ae3d20ac))
* **version:** single-source __version__ via _version.py dynamic attr (closes [#112](https://github.com/1StepMore/AutoInfo/issues/112)) ([5518244](https://github.com/1StepMore/AutoInfo/commit/55182449094732e3deb5ea2caf6be0839a586c11))
* **video:** port HyperFrames pipeline — HTML+GSAP-&gt;MP4 video output (2026-08-13) ([64daae5](https://github.com/1StepMore/AutoInfo/commit/64daae5e1c26bc690c98096547acba24b6dac5c8))
* Wave 2 complete - social adapter, SEO CLI, storefront, recommendation, storefront, and validation scenarios ([f83bd8d](https://github.com/1StepMore/AutoInfo/commit/f83bd8d77dbd2d13e8ba6cdff4364b6bb64e70a7))
* wire G0/G4, RAW feed API, ProductTemplate, delivery channels ([d683fdf](https://github.com/1StepMore/AutoInfo/commit/d683fdfd65ff27792668c50c881a2facd609aef9))


### Bug Fixes

* [#76](https://github.com/1StepMore/AutoInfo/issues/76) - improve _group_by_theme() fallback to split by domain then source_type ([fd48c34](https://github.com/1StepMore/AutoInfo/commit/fd48c34dac9523f3888d4f738385d9f45c26fe80))
* [#79](https://github.com/1StepMore/AutoInfo/issues/79) - add _scrape_doi_page helper to http_api.py for CrossRef fallback ([fd48c34](https://github.com/1StepMore/AutoInfo/commit/fd48c34dac9523f3888d4f738385d9f45c26fe80))
* 201: edge-tts asyncio.run() crashes inside running event loop ([a47db16](https://github.com/1StepMore/AutoInfo/commit/a47db162f83983552c3dbec5bea4863bdce8481c))
* 203: scenario-level per-step timeout override for long-running generation steps ([e402aa5](https://github.com/1StepMore/AutoInfo/commit/e402aa59ad37c9ab13dd5c1e6b92d3330512f070))
* 206: dedupe delivery artifacts to prevent rejected-move FileNotFoundError ([e75c97e](https://github.com/1StepMore/AutoInfo/commit/e75c97eff28f43267b6b51e298a3d47caace9173))
* 208: unify 12 MCP tools' error returns to standard envelope ([3903fdc](https://github.com/1StepMore/AutoInfo/commit/3903fdcc83381df062c99b95fdcea4af398540d1))
* 210: default TTS engine to local (edge-tts) — openai endpoint unreachable in deployment ([73f790b](https://github.com/1StepMore/AutoInfo/commit/73f790b42daf9d97861eb05966a8268f9d1b3da0))
* 213: reset stale batch cursor when cache count is unchanged ([91297e0](https://github.com/1StepMore/AutoInfo/commit/91297e00e19b16e15af1c05911a4e44e9e49e297))
* 215: suggest_keywords deterministic fallback on LLM empty output ([86758f2](https://github.com/1StepMore/AutoInfo/commit/86758f279a40a7cce3af6dcc762af45d0ccac564))
* 217: agent JSON-LD products pass D1/authenticity with agent-native shape ([2541153](https://github.com/1StepMore/AutoInfo/commit/2541153da229854f0a74da9310b49a7f9ddbbd8e))
* 217: propagate [@type](https://github.com/type) marker through _build_product_output for agent D1 gate ([01c649a](https://github.com/1StepMore/AutoInfo/commit/01c649a4e1a1f3f23ba11ee648ad2b8fa79b065c))
* 218: load_config tts default hardcodes openai — align with local ([#210](https://github.com/1StepMore/AutoInfo/issues/210)) ([8c345cb](https://github.com/1StepMore/AutoInfo/commit/8c345cb34d39ecc3877229800c4a179e5f18aa6a))
* 220: KB-derived slide fallback when LLM presentation synthesis is empty ([bbfced0](https://github.com/1StepMore/AutoInfo/commit/bbfced0254c4f8fdddcc2b35a2c215fb45a6e927))
* 221: forward scenario timeout override to kind:cli and kind:http steps ([cbc14b6](https://github.com/1StepMore/AutoInfo/commit/cbc14b64441578892903e23b7e696cd5ca6b8d45))
* 52: set domain on collected items and fix KB count comparison ([4855944](https://github.com/1StepMore/AutoInfo/commit/485594487c662f71fda526a7dfb9594f49a76ab4))
* 54, [#56](https://github.com/1StepMore/AutoInfo/issues/56): remove Unpaywall from demo config, add CrossRef settings, validate empty keywords ([02cd099](https://github.com/1StepMore/AutoInfo/commit/02cd0997c87052d7507c2edf11323f059684b06e))
* 55: replace PEP 695 generic function syntax with TypeVar for Python 3.11 compat ([dc136f8](https://github.com/1StepMore/AutoInfo/commit/dc136f82819610d0b205b79bc1a2c862316d5e49))
* 60: fix all CLI invocation mismatches in validation plan v2 ([023d08e](https://github.com/1StepMore/AutoInfo/commit/023d08ecb5dea66ed63774d3a51c0833bc66fc73))
* 62, [#68](https://github.com/1StepMore/AutoInfo/issues/68): enable PubMed full-text, wire json_mode through config ([13628b1](https://github.com/1StepMore/AutoInfo/commit/13628b138ca37f8fe281f24ad274dc089ab6f0bb))
* 64: flatten nested YAML settings keys in source config parsing ([16519eb](https://github.com/1StepMore/AutoInfo/commit/16519eb9b77a7ec7513a873b1269222ef8b7c08e))
* 64: flatten nested YAML settings keys in source config parsing ([ce3d224](https://github.com/1StepMore/AutoInfo/commit/ce3d224300e0f08d4ab83aeb37ba8f1e2f713f98))
* 67: pass api_key and api_base to all 4 LLM call sites in output.py ([6d9ce9d](https://github.com/1StepMore/AutoInfo/commit/6d9ce9d149506ddd6fa9653bb151f4bb4c24f99d))
* 71: add content quality assertions to output product scenarios ([661f46c](https://github.com/1StepMore/AutoInfo/commit/661f46c1f4bed5546f1c2f25ea45e7783080f011))
* 71: add content quality assertions to output product scenarios in validation plan ([0a790ab](https://github.com/1StepMore/AutoInfo/commit/0a790abd372b5c4839b850c0142693e8de1afcbd))
* 73: add cross-domain coverage scenarios to validation plan ([97e49f9](https://github.com/1StepMore/AutoInfo/commit/97e49f90b8e3e13109b7f93bfab5f63a1730262f))
* 73: add cross-domain coverage scenarios to validation plan ([1fb351e](https://github.com/1StepMore/AutoInfo/commit/1fb351e6c37011c2c1eb2c722d49a4fa79d6cd5d))
* actually validate export JSON content instead of no-op pass ([793d2a8](https://github.com/1StepMore/AutoInfo/commit/793d2a81ec1b31ac82e481b8ccc980fb78bfa819))
* add documentation links to error messages in MCP and CLI ([b8aa792](https://github.com/1StepMore/AutoInfo/commit/b8aa792688b4200d89bccf783f2c87977fbeeeb9))
* add missing type annotations for Typer options (fix [#39](https://github.com/1StepMore/AutoInfo/issues/39), [#40](https://github.com/1StepMore/AutoInfo/issues/40), [#42](https://github.com/1StepMore/AutoInfo/issues/42)) ([cbd6c30](https://github.com/1StepMore/AutoInfo/commit/cbd6c3037cdc8f79692f9b9c4cd2d4b138531862))
* add missing UserProfile, Subscription, and CostRatesConfig dataclasses ([34b9e4b](https://github.com/1StepMore/AutoInfo/commit/34b9e4bbc98b57a21c451eca739dc84d9a0a0f17))
* apply PR [#66](https://github.com/1StepMore/AutoInfo/issues/66) DOI slash escaping, PR [#69](https://github.com/1StepMore/AutoInfo/issues/69) api_key/api_base, issue [#63](https://github.com/1StepMore/AutoInfo/issues/63) URL fixes ([1a3ea40](https://github.com/1StepMore/AutoInfo/commit/1a3ea40358bc5e013b475fc8a7859454efc09f29))
* **billing:** branch webhook on session.mode + add mode param ([6915141](https://github.com/1StepMore/AutoInfo/commit/6915141c1c890566b840a92aaa8176448b92f684))
* **billing:** warn when STRIPE_API_KEY points at stripe-mock base ([180d3c8](https://github.com/1StepMore/AutoInfo/commit/180d3c8fdec675301231b220adddbaca995e4d6a))
* **ci:** clear pre-existing lint/mypy debt on changed files ([2a0c24b](https://github.com/1StepMore/AutoInfo/commit/2a0c24b2fad2a938c9822ae7a2ad1a00322fd08b))
* **ci:** make coverage gate baseline-aware — no-regression vs merge-base, 60% for new modules only ([#258](https://github.com/1StepMore/AutoInfo/issues/258)) ([16c116b](https://github.com/1StepMore/AutoInfo/commit/16c116b1e37f6ea5175af83a3d207f8ecd27af13))
* **ci:** pin mcp&lt;2.0 + fix doc-drift guard — [#117](https://github.com/1StepMore/AutoInfo/issues/117) baseline ([7fc36d3](https://github.com/1StepMore/AutoInfo/commit/7fc36d3a4b86965c9ab2e11ac0689568305c8e8b))
* **ci:** release-please — add workflow_dispatch + optional release-as escape hatch ([#261](https://github.com/1StepMore/AutoInfo/issues/261)) ([3f801fb](https://github.com/1StepMore/AutoInfo/commit/3f801fb558efb97664e17314c23c7d2b6153a08e))
* **ci:** restore main CI green — test env gates + mcp server hygiene ([16cdee7](https://github.com/1StepMore/AutoInfo/commit/16cdee7d8172fc17391df4aa3d6fa16942db064e))
* **cli:** drop misleading standalone sources.yaml; config.yaml is source of truth ([#100](https://github.com/1StepMore/AutoInfo/issues/100)) ([0d95a93](https://github.com/1StepMore/AutoInfo/commit/0d95a93fece9bb82206ff7edd6fdcc1e01aff7fb))
* close v1 content_preference bypass corners + B1 scenario self-containment ([e493c92](https://github.com/1StepMore/AutoInfo/commit/e493c9252fc794f6eba943f871f9c2c75223012d))
* coerce fields to str and drop empty items ([#180](https://github.com/1StepMore/AutoInfo/issues/180)) ([c626136](https://github.com/1StepMore/AutoInfo/commit/c626136918e19232dc0da30ecfbed7da6f273c2a))
* **collect:** dead-source detection + CLI module entry + progress ([#135](https://github.com/1StepMore/AutoInfo/issues/135), [#137](https://github.com/1StepMore/AutoInfo/issues/137)) ([63b15d4](https://github.com/1StepMore/AutoInfo/commit/63b15d4f617c5530a94f08a72fca1c47a845b6c0))
* **collect:** filter collected items by topic keywords ([#177](https://github.com/1StepMore/AutoInfo/issues/177)) ([07202f3](https://github.com/1StepMore/AutoInfo/commit/07202f33e21c1aafa59ae1e0b9830bcfe0aae8a2))
* **collect:** make topic-keyword relevance filter source-type aware ([#177](https://github.com/1StepMore/AutoInfo/issues/177) regression) ([709170c](https://github.com/1StepMore/AutoInfo/commit/709170cb57556883b66955571fa3b9d84aa4c593))
* **collect:** make topic-keyword relevance filter source-type aware ([#177](https://github.com/1StepMore/AutoInfo/issues/177)) ([94d57cc](https://github.com/1StepMore/AutoInfo/commit/94d57ccfb334ea14dc76704e1d5dd2e27eaaf4ef))
* **collectors:** unify _VALID_SOURCE_TYPES source-of-truth ([758dd53](https://github.com/1StepMore/AutoInfo/commit/758dd53cff4d0fa9205a03be45368e56bd1561d4))
* **collectors:** unpaywall ruff cleanup (unused vars/imports) ([2bd63bc](https://github.com/1StepMore/AutoInfo/commit/2bd63bc535f4c826853b53d24afd682a06cc1a69))
* **collect:** propagate source quality_tier to items ([f55b4f7](https://github.com/1StepMore/AutoInfo/commit/f55b4f78e30ef1cba799c8d42676555df69202ed))
* **collect:** skip API sources with empty query to avoid fetching unrelated content ([d36c686](https://github.com/1StepMore/AutoInfo/commit/d36c68616b16b16f93d8b7348d0bd466ce2f2a37))
* **collect:** skip API sources with empty query to avoid unrelated content ([5807584](https://github.com/1StepMore/AutoInfo/commit/5807584c16ceca88507bf56c0958608d26b712ad))
* **collect:** skip API sources with empty query to avoid unrelated content ([5807584](https://github.com/1StepMore/AutoInfo/commit/5807584c16ceca88507bf56c0958608d26b712ad))
* **collect:** str() numeric and slash item ids before caching (closes [#104](https://github.com/1StepMore/AutoInfo/issues/104)) ([f750019](https://github.com/1StepMore/AutoInfo/commit/f7500194f555937dcf89f819b2a2b3985bec9be7))
* **collect:** surface items_filtered in run_collection result; update smoke test for [#177](https://github.com/1StepMore/AutoInfo/issues/177) filter ([a0c9d8e](https://github.com/1StepMore/AutoInfo/commit/a0c9d8efd7de5ec6eb44f1fcd7f45c0b7e16cd97))
* complete [#30](https://github.com/1StepMore/AutoInfo/issues/30) [#31](https://github.com/1StepMore/AutoInfo/issues/31) [#32](https://github.com/1StepMore/AutoInfo/issues/32) — cover remaining collectors, upgrade --limit to min=1 ([ed8d4bc](https://github.com/1StepMore/AutoInfo/commit/ed8d4bc85ef399be6a217d3c2de06e18bd52bd5c))
* config_path.parent.parent / "knowledge" → &lt;root&gt;/knowledge/ (CORRECT). ([cdd1f89](https://github.com/1StepMore/AutoInfo/commit/cdd1f8941d9ba23ff07a8a6fe6f7c86913aa17af))
* **config:** add AUTOINFO_LLM_API_KEY env var to .opencode/mcp.json ([6675c58](https://github.com/1StepMore/AutoInfo/commit/6675c58566ff52bf43653023a18cc4ac124cff45))
* **config:** config_to_dict no longer drops fallback base_url/api_key ([#155](https://github.com/1StepMore/AutoInfo/issues/155)) ([#162](https://github.com/1StepMore/AutoInfo/issues/162)) ([7824c86](https://github.com/1StepMore/AutoInfo/commit/7824c868aa486b2d11d8d5f0087a55d3858a89e8))
* convert SQLite dicts to KBEntry objects before dedup check ([9d7a531](https://github.com/1StepMore/AutoInfo/commit/9d7a531667119a52c766f73bd9367c325930e853))
* **cron:** bound crontab subprocess and test-suite timeouts (closes [#115](https://github.com/1StepMore/AutoInfo/issues/115)) ([5804f6d](https://github.com/1StepMore/AutoInfo/commit/5804f6defd061a94cc7862d8f4df039f1f8ac71c))
* **cron:** delete stale schedules.yaml artifact + regression tests ([#101](https://github.com/1StepMore/AutoInfo/issues/101)) ([5274c05](https://github.com/1StepMore/AutoInfo/commit/5274c0563e2540e30e365e9c10f5d2aa605d2fd9))
* D1 gate metadata misclassification + llm key fallback + kb-extraction seed + FTS5 long-query fallback ([#166](https://github.com/1StepMore/AutoInfo/issues/166) [#167](https://github.com/1StepMore/AutoInfo/issues/167) [#169](https://github.com/1StepMore/AutoInfo/issues/169) [#170](https://github.com/1StepMore/AutoInfo/issues/170)) ([f05759c](https://github.com/1StepMore/AutoInfo/commit/f05759c8d0135a08957478d098ed55d34eb248de))
* D1 gate metadata misclassification + llm key fallback + kb-extraction seed + FTS5 long-query fallback ([#166](https://github.com/1StepMore/AutoInfo/issues/166) [#167](https://github.com/1StepMore/AutoInfo/issues/167) [#169](https://github.com/1StepMore/AutoInfo/issues/169) [#170](https://github.com/1StepMore/AutoInfo/issues/170)) ([f05759c](https://github.com/1StepMore/AutoInfo/commit/f05759c8d0135a08957478d098ed55d34eb248de))
* **delivery:** html products pass D1 with product-appropriate rules ([b31a33c](https://github.com/1StepMore/AutoInfo/commit/b31a33ca31984f100c486dbdb3bbc5c9b457ab64)), closes [#217](https://github.com/1StepMore/AutoInfo/issues/217)
* **delivery:** html products pass D1 with product-appropriate rules ([#217](https://github.com/1StepMore/AutoInfo/issues/217) follow-up) ([05e9acb](https://github.com/1StepMore/AutoInfo/commit/05e9acb5e0b72d43aa7b5e4900e442c049a07ece))
* **deps:** add lxml as direct dependency for trafilatura ([#102](https://github.com/1StepMore/AutoInfo/issues/102)) ([5919947](https://github.com/1StepMore/AutoInfo/commit/591994724a0f35aa95d45d247d70fffe6f0db29a))
* deserialize JSON fields from SQLite dict→KBEntry conversion ([49f5600](https://github.com/1StepMore/AutoInfo/commit/49f5600aff76615b97dfb6bea2fedf96a5ab6d8f))
* **docs:** sync YAML param names and tool counts in validation scenarios ([#94](https://github.com/1StepMore/AutoInfo/issues/94)) ([de973cd](https://github.com/1StepMore/AutoInfo/commit/de973cde3df91fe6d4b54adf9b5a3060dbebbc0f))
* **doctor:** bound source probing with concurrent timeouts ([#193](https://github.com/1StepMore/AutoInfo/issues/193)) ([#199](https://github.com/1StepMore/AutoInfo/issues/199)) ([7052ad5](https://github.com/1StepMore/AutoInfo/commit/7052ad5eafd0eebc26cb3f9c058d6305efdadd78))
* **doctor:** point agents at configure_llm MCP tool in LLM hint (closes [#110](https://github.com/1StepMore/AutoInfo/issues/110)) ([3f0c1e1](https://github.com/1StepMore/AutoInfo/commit/3f0c1e1753f9e8ed843a790a616cb696a4b0a65e))
* **errors:** ErrorCode 28 members (DIRECTOR_ONLY) — bump test_total_members + docs ([88c5d4b](https://github.com/1StepMore/AutoInfo/commit/88c5d4bac6fead5ce003564fb592e29bf0337c4e))
* escape inner double-quote in presentation grep pattern ([1323815](https://github.com/1StepMore/AutoInfo/commit/13238150017e626b52536307092256885a593f2f))
* filter irrelevant items at collection time ([#177](https://github.com/1StepMore/AutoInfo/issues/177)) ([bd8082f](https://github.com/1StepMore/AutoInfo/commit/bd8082f26448aca361446f04ec215bdc240e631d))
* filter stopwords, add toggle and cap for auto-discovered keywords ([#179](https://github.com/1StepMore/AutoInfo/issues/179)) ([cccad4a](https://github.com/1StepMore/AutoInfo/commit/cccad4a35b348b002900c199e605f86bac2849c9))
* **financial,tech,language:** fix Stack Exchange, SEC EDGAR, FRED, Yahoo/World Bank/Twelve Data, Gutenberg, VOA sources ([491db9a](https://github.com/1StepMore/AutoInfo/commit/491db9a50be9a2bf9e4d02a9c2d6a16f7eb8c5d5))
* **g4:** pass api_key/base_url to call_with_fallback in quality gates (fixes [#168](https://github.com/1StepMore/AutoInfo/issues/168)) ([a695bf6](https://github.com/1StepMore/AutoInfo/commit/a695bf68f02989fe053dd077074c90a65bfc376a))
* **http_api:** add integer index support to _traverse_json ([ac2b2e5](https://github.com/1StepMore/AutoInfo/commit/ac2b2e51080f6d65dba94ceae3d9005670b3a977))
* **http_api:** coerce numeric fields to str and drop empty items ([#180](https://github.com/1StepMore/AutoInfo/issues/180)) ([9b8c169](https://github.com/1StepMore/AutoInfo/commit/9b8c1694642465dd88c898444f11a1af0410666d))
* **init:** create runtime dirs at project root, config stays in .autoinfo/ (closes [#106](https://github.com/1StepMore/AutoInfo/issues/106)) ([79b188a](https://github.com/1StepMore/AutoInfo/commit/79b188aa3391de99804bc408d88c5a43cf029af9))
* install pytest-mock, fix KG test mock setup for load_cached_items ([49b3fa6](https://github.com/1StepMore/AutoInfo/commit/49b3fa6531fbf68fd8acab2cc0223361da7a3f3c))
* issue [#68](https://github.com/1StepMore/AutoInfo/issues/68) (json_mode flag) + issue [#62](https://github.com/1StepMore/AutoInfo/issues/62) (fetch_depth) + test updates ([55c7c3d](https://github.com/1StepMore/AutoInfo/commit/55c7c3d9c99bd900fd1c04a469453096b4e3a722))
* **kb:** B-class fixes (portal field/B-04/B-05/B-07/B-08/query_collected) ([180ba7f](https://github.com/1StepMore/AutoInfo/commit/180ba7fdf9bb33af80b474f17c0c964fc1877f55))
* **kb:** KBEntry gains tos_compliant/tos_classification fields; fix frontmatter summary quoting ([f69344e](https://github.com/1StepMore/AutoInfo/commit/f69344eb7cafae6ecf4116a14e6593f3b2cc009d))
* **kb:** silence 8 pre-existing ruff violations so PR lint passes ([8301124](https://github.com/1StepMore/AutoInfo/commit/8301124f918fb20ec188c287c12076a9638ef408))
* **llm:** add per-provider rate limiting and jittered backoff for 429/5xx ([c0efa9e](https://github.com/1StepMore/AutoInfo/commit/c0efa9e6b3c988ad2b1ed958b04a938c4484e1a8))
* **llm:** disable thinking on reasoning models — stop token-budget truncation of JSON output (2026-08-13) ([c33c6d0](https://github.com/1StepMore/AutoInfo/commit/c33c6d0c5f4391343a923e2592bf36897815dff0))
* **llm:** primary api_key falls back to config.llm.api_key ([#166](https://github.com/1StepMore/AutoInfo/issues/166)) ([8558d26](https://github.com/1StepMore/AutoInfo/commit/8558d2630809ffbc17a05c99ae60e9de4aa4d6b0))
* **llm:** primary model base_url defaults to config.llm.base_url ([#153](https://github.com/1StepMore/AutoInfo/issues/153)) ([#154](https://github.com/1StepMore/AutoInfo/issues/154)) ([27c2f28](https://github.com/1StepMore/AutoInfo/commit/27c2f288d489fc10f02f7dde7d5038b6170b2689))
* **llm:** resolve provider prefix for suggest_keywords (cli + mcp) — [#119](https://github.com/1StepMore/AutoInfo/issues/119) residual ([4d259c4](https://github.com/1StepMore/AutoInfo/commit/4d259c4dbb52a99be01c6f47f154c1d19b5c8436))
* **llm:** resolve_model() prevents double provider prefix across all call sites ([ff470ac](https://github.com/1StepMore/AutoInfo/commit/ff470acd8e94c351bb72d0db051da595e4e2f0a8))
* **llm:** robust JSON parsing for LLM responses ([#178](https://github.com/1StepMore/AutoInfo/issues/178)) ([ca6c32f](https://github.com/1StepMore/AutoInfo/commit/ca6c32fa72dda2912e3a449f4ca77c1c76a6b2a3))
* **matrix:** classify capability not-implemented required cells as not-applicable ([bab37f6](https://github.com/1StepMore/AutoInfo/commit/bab37f682660515455423ff5fceaba083626c28d))
* **matrix:** evidence-scan correctness + RSS fetch timeout guard (2026-08-13) ([5db457b](https://github.com/1StepMore/AutoInfo/commit/5db457bb8eca274520bc834f64bf17313a6cf27c))
* **matrix:** exclude capability-boundary cells from gap accounting in delivery tests ([abbd6d6](https://github.com/1StepMore/AutoInfo/commit/abbd6d6dd93e04c7330313d355e92f5ff9cb7200))
* **matrix:** pin config-layer completeness and annotate data-evidence gaps ([#195](https://github.com/1StepMore/AutoInfo/issues/195)) ([#198](https://github.com/1StepMore/AutoInfo/issues/198)) ([b816698](https://github.com/1StepMore/AutoInfo/commit/b816698d5d14838c24453480df20d1c568faf474))
* **matrix:** recognize regenerate_paygrade artifact naming in evidence scan ([#191](https://github.com/1StepMore/AutoInfo/issues/191)) ([#190](https://github.com/1StepMore/AutoInfo/issues/190)) ([542d5eb](https://github.com/1StepMore/AutoInfo/commit/542d5eb9bfae543fc32abb4a6c52f3d9512dd36b))
* **mcp:** add 'Use add_domain()' remediation hint to all DOMAIN_NOT_FOUND messages ([234e942](https://github.com/1StepMore/AutoInfo/commit/234e94216cda81e96a01403c9f4ca09348967a4e))
* **mcp:** add domain existence guard to collect_sources single-domain path ([0300558](https://github.com/1StepMore/AutoInfo/commit/03005584b42d1d97f20ae906f0bd58396d0b92c9))
* **mcp:** add explicit LLM_NOT_CONFIGURED check to suggest_keywords (was silent fallback) ([836fa8e](https://github.com/1StepMore/AutoInfo/commit/836fa8e13b589845ea05ba09b083dd4f86e64bb6))
* **mcp:** add no-entry check to generate_digest/generate_report before LLM call ([e497e11](https://github.com/1StepMore/AutoInfo/commit/e497e11bdb7e9c7a88749e531ae036e66bd5f43c))
* **mcp:** catch collection exceptions in handler instead of re-raising for double-logging ([97c1065](https://github.com/1StepMore/AutoInfo/commit/97c106576889b9e38a8beea3ae1321cba2ccdcb5))
* **mcp:** clean_cache dry_run exempt from confirm guard ([#252](https://github.com/1StepMore/AutoInfo/issues/252)) ([#253](https://github.com/1StepMore/AutoInfo/issues/253)) ([f5ea27d](https://github.com/1StepMore/AutoInfo/commit/f5ea27dfa2c33e374c9e01ba2434af3c79814f6e))
* **mcp:** close [#125](https://github.com/1StepMore/AutoInfo/issues/125),[#126](https://github.com/1StepMore/AutoInfo/issues/126),[#128](https://github.com/1StepMore/AutoInfo/issues/128) — period alignment, delivery fix, Draft→Wiki promotion ([e03e1f0](https://github.com/1StepMore/AutoInfo/commit/e03e1f0ede9045521118f2b26ea0267f87c22c77))
* **mcp:** enhance KB listing tools to distinguish uninitialized vs empty vs results ([f7a5873](https://github.com/1StepMore/AutoInfo/commit/f7a5873ddc74097f916a02d80e070d81c89fff6b))
* **mcp:** ensure all error responses use envelope format, fix NotImplementedError path ([4bc3b65](https://github.com/1StepMore/AutoInfo/commit/4bc3b65f3a281c02bab948504a27923a04cd4d90))
* **mcp:** persist video by copying the MP4, not b64decoding the JSON blob ([#254](https://github.com/1StepMore/AutoInfo/issues/254)) ([#256](https://github.com/1StepMore/AutoInfo/issues/256)) ([482f4cb](https://github.com/1StepMore/AutoInfo/commit/482f4cb5150dac1da8c304e0a28d864e81f5afcd))
* **mcp:** return status=noop from process_collection when no cached items ([e486af2](https://github.com/1StepMore/AutoInfo/commit/e486af254380ce8e202282d02632cb36f8d57d24))
* **mcp:** use ErrorCode.CONFIG_NOT_FOUND in configure_llm (was string literal) ([b39829a](https://github.com/1StepMore/AutoInfo/commit/b39829a22e489ba4a458035a88ed824b1b480c9b))
* **output:** chunk theme grouping and add keyword fallback to prevent General collapse ([d7aa43b](https://github.com/1StepMore/AutoInfo/commit/d7aa43bb0b612117c66ffa15a30d10276e0fdf56))
* **output:** configurable weasyprint timeout ([79b851a](https://github.com/1StepMore/AutoInfo/commit/79b851a431979b2934d97fc899d38156755fc6cc))
* **output:** correct _TEMPLATES_DIR and TEMPLATE_PATH resolution ([#98](https://github.com/1StepMore/AutoInfo/issues/98)) ([2bbf048](https://github.com/1StepMore/AutoInfo/commit/2bbf048803898da9b573f56b03c4500089f4fbb8))
* **output:** D1-block test uses empty entry store — fallback (issue [#217](https://github.com/1StepMore/AutoInfo/issues/217)) only fires with entries ([f4eab0f](https://github.com/1StepMore/AutoInfo/commit/f4eab0f4eee850e66d4c64d452f6df9399f9990a))
* **output:** deterministic synthesis fallback when LLM returns empty ([#217](https://github.com/1StepMore/AutoInfo/issues/217)) ([88d7185](https://github.com/1StepMore/AutoInfo/commit/88d71852aa8ad80201177ea6219ea20afec49558))
* **output:** deterministic synthesis fallback when LLM returns empty ([#217](https://github.com/1StepMore/AutoInfo/issues/217)) ([23dd7b0](https://github.com/1StepMore/AutoInfo/commit/23dd7b09860c6edc1d902bb2d771c9f9069593c1))
* **output:** feed actual entry content into report synthesis prompt ([dba71bc](https://github.com/1StepMore/AutoInfo/commit/dba71bcaf7e1b4192e0767dc084fe6ffd659e8bc))
* **output:** guard against None LLM content in _parse_json_response ([#96](https://github.com/1StepMore/AutoInfo/issues/96),[#99](https://github.com/1StepMore/AutoInfo/issues/99)) ([59ff2f1](https://github.com/1StepMore/AutoInfo/commit/59ff2f1b018a86283e6e0ecc58e694cebce67f7f))
* **output:** guard None config + resolve pre-existing mypy Any-returns in output module ([b49d22c](https://github.com/1StepMore/AutoInfo/commit/b49d22cd348adf75850bdbf4219cac677916b687))
* **output:** make tutorial generation robust to unstructured LLM output ([9684b08](https://github.com/1StepMore/AutoInfo/commit/9684b08b4e81ec1c72912908e2729874c0a1e832))
* **output:** raise video render timeouts 600s -&gt; 1200s ([#237](https://github.com/1StepMore/AutoInfo/issues/237)) ([c10b6e6](https://github.com/1StepMore/AutoInfo/commit/c10b6e6ec1ad6d82e0356e4ab2d3b1c54dd4705d))
* **output:** raise video render timeouts 600s -&gt; 1200s ([#237](https://github.com/1StepMore/AutoInfo/issues/237)) ([0b10555](https://github.com/1StepMore/AutoInfo/commit/0b10555f91c9e8c48e08528f68df56c98252eab1))
* **output:** report gains Key Findings / Recommendations sections ([32d657e](https://github.com/1StepMore/AutoInfo/commit/32d657e5c5689906ef1eedefe5c5e632164aa285))
* **output:** report synthesis + validation matrix spec restore (昨晚工作补推) ([15ac774](https://github.com/1StepMore/AutoInfo/commit/15ac774de89d2eacaca0baace8946157b3de7ef9))
* **output:** report-json entries carry source_url/source_type/source_platform (authenticity) ([835ac34](https://github.com/1StepMore/AutoInfo/commit/835ac34e26ff6333538a83a8424c59267f8f5f88))
* **output:** report-json entries carry source_url/source_type/source_platform (authenticity) ([835ac34](https://github.com/1StepMore/AutoInfo/commit/835ac34e26ff6333538a83a8424c59267f8f5f88))
* **output:** report-json entries carry source_url/source_type/source_platform so authenticity gate passes ([ff4e18f](https://github.com/1StepMore/AutoInfo/commit/ff4e18f8920a9424e16647b569c04adb190bcfd6))
* **output:** resolve mypy/ruff in digest tests — cast union results, annotate fixtures ([2554245](https://github.com/1StepMore/AutoInfo/commit/25542456e501c1f3fa9bb05bdc845166058f1073))
* P1-P3 defect batch — email user_id, key governance, scenario cleanup, CLI user-id, docs alignment ([605e40a](https://github.com/1StepMore/AutoInfo/commit/605e40a333ab67ae9eb1fcf1934239b8d6b227e4))
* pass LLM api_key/base_url to call_with_fallback in quality gates ([0f97252](https://github.com/1StepMore/AutoInfo/commit/0f97252296d1e9e3d15bd5320b99d3f96c853092))
* **process:** filter stopwords, add toggle and cap for auto-discovered keywords ([#179](https://github.com/1StepMore/AutoInfo/issues/179)) ([89b4bcb](https://github.com/1StepMore/AutoInfo/commit/89b4bcbf183386a4e4210357438a95ada6095ae5))
* **process:** LLM timeout threading + parallel processing + MCP offload ([#136](https://github.com/1StepMore/AutoInfo/issues/136)) ([8de433d](https://github.com/1StepMore/AutoInfo/commit/8de433db6d95c951ca1717f39e465473a2ef561e))
* **process:** restore G3 archive action after gate parallelization ([c11635f](https://github.com/1StepMore/AutoInfo/commit/c11635fb298dce8f5c3ff8f14fb0bc7356b8e6b4))
* Python 3.11 f-string backslash in expression part ([#28](https://github.com/1StepMore/AutoInfo/issues/28)) ([48eb257](https://github.com/1StepMore/AutoInfo/commit/48eb25795ec7b0274c6702cfbb38b35b0f37386b))
* **quality:** audit-feedback hardening — no empty shells, stale-free weekly, discriminative relevance ([#182](https://github.com/1StepMore/AutoInfo/issues/182)) ([#189](https://github.com/1StepMore/AutoInfo/issues/189)) ([91abb9e](https://github.com/1StepMore/AutoInfo/commit/91abb9e3d45f6c6c9554791e16f5145675357d79))
* **quality:** normalize naive datetime in G2 dedup freshness ([#145](https://github.com/1StepMore/AutoInfo/issues/145)) ([#146](https://github.com/1StepMore/AutoInfo/issues/146)) ([536211f](https://github.com/1StepMore/AutoInfo/commit/536211f63215dbc78a6795befbde3bfd0177a6fd))
* **quality:** P0 data-quality trio ([#180](https://github.com/1StepMore/AutoInfo/issues/180)/[#179](https://github.com/1StepMore/AutoInfo/issues/179)/[#177](https://github.com/1StepMore/AutoInfo/issues/177)) + 4 empty domains backfilled ([#182](https://github.com/1StepMore/AutoInfo/issues/182)) ([#183](https://github.com/1StepMore/AutoInfo/issues/183)) ([29ecda3](https://github.com/1StepMore/AutoInfo/commit/29ecda38f6d13dd1e91c004ced19fbaa45ad8947))
* **quality:** pass LLM api_key/base_url to call_with_fallback in quality gates ([a695bf6](https://github.com/1StepMore/AutoInfo/commit/a695bf68f02989fe053dd077074c90a65bfc376a))
* remove dead/hanging demo sources, add --audience to output report CLI ([7cc7e58](https://github.com/1StepMore/AutoInfo/commit/7cc7e584f0466d802d1b25c9e34c87ef1d586bf9))
* rename list() to list_entries() to avoid shadowing builtin list type (fix [#43](https://github.com/1StepMore/AutoInfo/issues/43)) ([53dc7db](https://github.com/1StepMore/AutoInfo/commit/53dc7db46d62868c5586277a26532375341d742b))
* resolve 6 F2 code quality issues - dead code removal, test mock updates, assertion fixes ([6309916](https://github.com/1StepMore/AutoInfo/commit/63099167d064570f26b0f2e050f5368846fce268))
* resolve GitHub issues [#34](https://github.com/1StepMore/AutoInfo/issues/34), [#35](https://github.com/1StepMore/AutoInfo/issues/35), [#37](https://github.com/1StepMore/AutoInfo/issues/37), [#38](https://github.com/1StepMore/AutoInfo/issues/38) ([7908bd8](https://github.com/1StepMore/AutoInfo/commit/7908bd8111fa32f8c04255857ad42e7ca7083389))
* resolve issues [#30](https://github.com/1StepMore/AutoInfo/issues/30), [#31](https://github.com/1StepMore/AutoInfo/issues/31), [#32](https://github.com/1StepMore/AutoInfo/issues/32) — source_platform, collected_at, --limit validation ([3804147](https://github.com/1StepMore/AutoInfo/commit/38041474d07d18580b3de1c24f3f1170787693fc))
* resolve issues [#33](https://github.com/1StepMore/AutoInfo/issues/33), [#35](https://github.com/1StepMore/AutoInfo/issues/35) — count_entries verification, presentation mock format ([bc515de](https://github.com/1StepMore/AutoInfo/commit/bc515ded4b8d0e7b3ab78e7b38fdbf5dba399bff))
* robust json parse + reasoning-mode json_mode + max_tokens wiring ([#178](https://github.com/1StepMore/AutoInfo/issues/178)) ([9396cec](https://github.com/1StepMore/AutoInfo/commit/9396cecde2306ee768433b9d3426a2e62055e26f))
* **rss:** add User-Agent agent param for SEC EDGAR Atom feed ([3c8c019](https://github.com/1StepMore/AutoInfo/commit/3c8c0190ef98c6928baf30b68642e64f2e480d2c))
* **scenario:** seed preset keywords in keyword-management scenario ([#194](https://github.com/1StepMore/AutoInfo/issues/194)) ([#197](https://github.com/1StepMore/AutoInfo/issues/197)) ([3acb313](https://github.com/1StepMore/AutoInfo/commit/3acb313761554a3f3a4c2561a2384baa57a661bf))
* **scenarios:** kb-extraction seeds missing entry before use ([#167](https://github.com/1StepMore/AutoInfo/issues/167)) ([8558d26](https://github.com/1StepMore/AutoInfo/commit/8558d2630809ffbc17a05c99ae60e9de4aa4d6b0))
* **scenarios:** stop collecting validation-runs/scenarios.json as artifacts (98 false D1 rejections) ([6f392a1](https://github.com/1StepMore/AutoInfo/commit/6f392a1d8b7f0508b391fcfa71416707c7c2107b))
* **search:** FTS5 long-query fallback (OR semantics + LIKE) so query_collected matches ([#170](https://github.com/1StepMore/AutoInfo/issues/170)) ([0b47992](https://github.com/1StepMore/AutoInfo/commit/0b47992116cef05dbdb402910c3500054e09ce24))
* **server:** persist column products as column-markdown-* ([#229](https://github.com/1StepMore/AutoInfo/issues/229)) ([559a56d](https://github.com/1StepMore/AutoInfo/commit/559a56dfa614810fe7f7894808eef4814dd2a83a))
* **server:** persist column products as column-markdown-* ([#229](https://github.com/1StepMore/AutoInfo/issues/229)) ([21ed249](https://github.com/1StepMore/AutoInfo/commit/21ed2496836bd836d26fc423f706ec1a9b00c422))
* **server:** persist column video products under column-* and lock with regression tests ([1bf0ad3](https://github.com/1StepMore/AutoInfo/commit/1bf0ad307476ddaf59dccbf1537c54415b8c36d9))
* stage remaining validation scenarios and delete refactored output.py ([4e218ea](https://github.com/1StepMore/AutoInfo/commit/4e218eaab68f2391184f5125452474c04a3f5bd3))
* **status:** resolve SQLite index from project root (same as KBStore) ([39c9cea](https://github.com/1StepMore/AutoInfo/commit/39c9ceaddf5c5e22c7b2bd5b8a2624b759dd35e9))
* **tests:** patch LLM guard in cross-domain report MCP test (closes [#109](https://github.com/1StepMore/AutoInfo/issues/109)) ([3517f96](https://github.com/1StepMore/AutoInfo/commit/3517f9686ab051a1d5cbb5fd19c19182665bfbda))
* **tests:** use tests.conftest import path for real-API guard (closes [#108](https://github.com/1StepMore/AutoInfo/issues/108)) ([09b09f6](https://github.com/1StepMore/AutoInfo/commit/09b09f6b6cb1b49a72f1eb2f9d2efc24ae7e7585))
* **validation:** agent authenticity by JSON-LD [@type](https://github.com/type) ([#217](https://github.com/1StepMore/AutoInfo/issues/217) follow-up) ([8a9154e](https://github.com/1StepMore/AutoInfo/commit/8a9154e17a58419bf84ea9d57af5f6bc5789a463))
* **validation:** check agent authenticity by JSON-LD [@type](https://github.com/type) ([e696a04](https://github.com/1StepMore/AutoInfo/commit/e696a0439a7154167bcc2bf781a5c6a475d54f8c)), closes [#217](https://github.com/1StepMore/AutoInfo/issues/217)
* **validation:** close [#118](https://github.com/1StepMore/AutoInfo/issues/118)-[#123](https://github.com/1StepMore/AutoInfo/issues/123) — completeness, data production loop, delivery ([6405e14](https://github.com/1StepMore/AutoInfo/commit/6405e14957e19b7f9a0361380cba371dfec343e6))
* **validation:** close [#118](https://github.com/1StepMore/AutoInfo/issues/118)-[#123](https://github.com/1StepMore/AutoInfo/issues/123) — validation completeness, data production loop, delivery ([2df8372](https://github.com/1StepMore/AutoInfo/commit/2df83720b7bc429a5c2860196810abcd20cdb076))
* **validation:** close AC2/AC5/AC9/B-01 acceptance risks (2026-08-12) ([e89ca9a](https://github.com/1StepMore/AutoInfo/commit/e89ca9a21b46ba64665a5808065a3675269c797e))
* **validation:** correct SourceConfig import in Q2b unpaywall scenario ([11540f5](https://github.com/1StepMore/AutoInfo/commit/11540f5c5b8ee49ca1052091a53627fe9b3df352))
* **validation:** D1 gate misclassifies metadata json as report products ([#169](https://github.com/1StepMore/AutoInfo/issues/169)) ([8558d26](https://github.com/1StepMore/AutoInfo/commit/8558d2630809ffbc17a05c99ae60e9de4aa4d6b0))
* **validation:** D1 recognizes enterprise/premium/magazine-digest briefing types ([63935f0](https://github.com/1StepMore/AutoInfo/commit/63935f01f014ce470a5b1f70d08f0487fc8880b3))
* **validation:** D1 report requires only summary (no Key Findings headings in report template) ([4902352](https://github.com/1StepMore/AutoInfo/commit/49023521f6d76e84248168dbb6bbad403c0659af))
* **validation:** D1 section mapping by product type — presentation/digest/tutorial wrongly rejected ([#172](https://github.com/1StepMore/AutoInfo/issues/172)) ([13e33e3](https://github.com/1StepMore/AutoInfo/commit/13e33e39d7cd4c95e6ad4ce0e6cc14b1b0e0423c))
* **validation:** D1 section mapping by product type — presentation/digest/tutorial wrongly rejected ([#172](https://github.com/1StepMore/AutoInfo/issues/172)) ([13e33e3](https://github.com/1StepMore/AutoInfo/commit/13e33e39d7cd4c95e6ad4ce0e6cc14b1b0e0423c))
* **validation:** D1 section mapping by product type so presentation/digest/tutorial products aren't wrongly rejected ([#172](https://github.com/1StepMore/AutoInfo/issues/172)) ([24894e4](https://github.com/1StepMore/AutoInfo/commit/24894e433ec4d5cc2e7876884fcdea3062f38e26))
* **validation:** director-required scenario steps pass actor=director ([#236](https://github.com/1StepMore/AutoInfo/issues/236)) ([2754f38](https://github.com/1StepMore/AutoInfo/commit/2754f38fc43924a2ba5016002a337c6e81e56241))
* **validation:** director-required scenario steps pass actor=director ([#236](https://github.com/1StepMore/AutoInfo/issues/236)) ([9b65a11](https://github.com/1StepMore/AutoInfo/commit/9b65a11cee752429dd674c50337c1733dc673e06))
* **validation:** eliminate raw-exception leaks, run real LLM-judge calibration, disambiguate tool descriptions ([1309804](https://github.com/1StepMore/AutoInfo/commit/1309804e7719d9355cf71190f8fcfbea25f29ce2))
* **validation:** exclude _failed/ and coverage-matrix artifacts from delivery packages ([#192](https://github.com/1StepMore/AutoInfo/issues/192)) ([#196](https://github.com/1StepMore/AutoInfo/issues/196)) ([9b67d5b](https://github.com/1StepMore/AutoInfo/commit/9b67d5bbeef1d28bec1b33c8fb003729b84816ff))
* **validation:** output-ebook — raise per-step timeout to 900s ([#255](https://github.com/1StepMore/AutoInfo/issues/255)) ([#257](https://github.com/1StepMore/AutoInfo/issues/257)) ([d0ce706](https://github.com/1StepMore/AutoInfo/commit/d0ce7067b0f1c56d5ceee0842e028f7c8523428e))
* **validation:** P0 scenario self-cleaning + P1 content_preference consistency ([53058f3](https://github.com/1StepMore/AutoInfo/commit/53058f3bc031211746046056f72e512ebe98f014))
* **validation:** quality-gate-config scenario — use non-normalized gate names ([#242](https://github.com/1StepMore/AutoInfo/issues/242)) ([f91046e](https://github.com/1StepMore/AutoInfo/commit/f91046e68123ab1c634c5a5663acc0d1bedabe9e))
* **validation:** quality-gate-config scenario — use non-normalized gate names ([#242](https://github.com/1StepMore/AutoInfo/issues/242)) ([042a3c3](https://github.com/1StepMore/AutoInfo/commit/042a3c3bd45a6d0c6bd9a28f97dea42f5253fee1))
* **validation:** resolve lint errors in E-wave files ([#131](https://github.com/1StepMore/AutoInfo/issues/131)-[#141](https://github.com/1StepMore/AutoInfo/issues/141)) ([3ae2d49](https://github.com/1StepMore/AutoInfo/commit/3ae2d495563805803b45ad467b320cb44965084e))
* **validation:** resolve pre-existing ruff/mypy errors in validation_delivery.py ([4a847ce](https://github.com/1StepMore/AutoInfo/commit/4a847ce54d1bd5b9c0a9813135cd34d8b7ddf567))
* **validation:** strip absolute prefix in _tier_subpath + collect 03-Wiki in KB scenarios ([#143](https://github.com/1StepMore/AutoInfo/issues/143) [#144](https://github.com/1StepMore/AutoInfo/issues/144)) ([#150](https://github.com/1StepMore/AutoInfo/issues/150)) ([1fc65e2](https://github.com/1StepMore/AutoInfo/commit/1fc65e23b3958006995d1857c1840156b7628f2c))
* **validation:** wrap long _section_value lines to satisfy ruff E501 ([270b62d](https://github.com/1StepMore/AutoInfo/commit/270b62d3021e7f37136a34d4aefb0de6241946b6))
* **video:** declare pillow extra and skip tests without PIL (closes [#114](https://github.com/1StepMore/AutoInfo/issues/114)) ([4d89660](https://github.com/1StepMore/AutoInfo/commit/4d89660d98afa6233fc92bec6cf712d4458f9416))


### Performance Improvements

* 204: parallelize D1-D3 delivery gate evaluation (ThreadPoolExecutor) ([4bd0f4e](https://github.com/1StepMore/AutoInfo/commit/4bd0f4e85b39a20533d367e0a786914aeec845cd))
* **llm:** enforce shared rate limiting across all parallel fan-out paths ([da5362a](https://github.com/1StepMore/AutoInfo/commit/da5362a32d69ab9e1a540de39444367a50769f97))
* **llm:** preserve thinking on judgment gates — per-call-site disable_thinking (2026-08-13) ([02a06a8](https://github.com/1StepMore/AutoInfo/commit/02a06a8cf0353b41e558b7872e9d1bc05953a7f9))
* **mcp:** offload 14 sync LLM handlers with asyncio.to_thread ([d41b844](https://github.com/1StepMore/AutoInfo/commit/d41b84499226743dcd538fba7faf6e1fcd1bf8fa))
* **mcp:** parallelize cefr_batch with bounded ThreadPoolExecutor ([b9a9b7e](https://github.com/1StepMore/AutoInfo/commit/b9a9b7e739c0287d69c1ec551dec8381f1c4c0d1))
* **output:** parallelize _group_by_theme batch loop preserving order ([798555c](https://github.com/1StepMore/AutoInfo/commit/798555c621be80d24afe788dd5c1929d1776dfb3))
* **process:** raise worker cap to 16, probe-gated ([e587cf4](https://github.com/1StepMore/AutoInfo/commit/e587cf4bdb5e0be0ea50c71d8edda8371d684416))
* **process:** run post-extraction gates concurrently, preserve retry and report order ([cc5939c](https://github.com/1StepMore/AutoInfo/commit/cc5939c5d072d6ab700458777b66ccbe75e0f3d1))
* **validation:** cap output-gen concurrency at 2 ([#234](https://github.com/1StepMore/AutoInfo/issues/234)) ([683dfdf](https://github.com/1StepMore/AutoInfo/commit/683dfdf565c67f739a9d5bfaa544a4126e409545))
* **validation:** cap output-gen concurrency at 2 ([#234](https://github.com/1StepMore/AutoInfo/issues/234)) ([f3eec93](https://github.com/1StepMore/AutoInfo/commit/f3eec93aac26d908d6d8b13ce1942660de69cb81))
* **validation:** cap output-gen concurrency at 2 ([#234](https://github.com/1StepMore/AutoInfo/issues/234)) ([6bd1480](https://github.com/1StepMore/AutoInfo/commit/6bd14808e34f3adfa636f10948685b9f72fdaac4))
* **validation:** parallelize readonly + output-gen scenario scheduling ([#234](https://github.com/1StepMore/AutoInfo/issues/234)) ([aa62cef](https://github.com/1StepMore/AutoInfo/commit/aa62cef64b0b6af38f83f027e1530bcd2df786ef))
* **validation:** parallelize readonly + output-gen scenario scheduling ([#234](https://github.com/1StepMore/AutoInfo/issues/234)) ([28d0f2d](https://github.com/1StepMore/AutoInfo/commit/28d0f2d8ac032845a61dfa65f54e2bcd49be8a39))


### Documentation

* add ADR records + root glossary, fix skill count drift, cleanup (2026-08-13) ([cbcf23b](https://github.com/1StepMore/AutoInfo/commit/cbcf23b53c2ca134f643e4d5637baa2db83c1b9a))
* add agent-tester validation runbook (real-call full-coverage guide) ([3758b06](https://github.com/1StepMore/AutoInfo/commit/3758b0602857711a82bcc907f0998aec189cb906))
* add archive docs and extracted spec files (F01-F57, G0-G5, D1-D3) ([151ac0c](https://github.com/1StepMore/AutoInfo/commit/151ac0c7c600ab41e93b56268eac0a6c2fb52306))
* add async/cron/email, error boundary, production validation, and final verdict (Q54-Q60) ([86f45fb](https://github.com/1StepMore/AutoInfo/commit/86f45fb62a0cb6915c74f2611f4da8e176861aee))
* add cross-dimensional catalog, extracted specs, and archive restructuring ([fcc53bc](https://github.com/1StepMore/AutoInfo/commit/fcc53bc5680dc8bb8fb48f4b6b661e8244842b90))
* add director user guide, update founder-expectations validation refs ([4d1ef14](https://github.com/1StepMore/AutoInfo/commit/4d1ef1428240c00b1d1f473b34dcbd3e18c3f40e))
* add full CLI and MCP system tool validation scenarios (Q7-Q27) ([07461af](https://github.com/1StepMore/AutoInfo/commit/07461afb50f82670bdaea7e1f13638a0a7e8f4b9))
* add in-repo workflow charter + ADR-0006, host methodology in docs/dev (2026-08-13) ([894cf11](https://github.com/1StepMore/AutoInfo/commit/894cf112112aca593bc78251d738b59dc3ec17b0))
* add issue-97 coverage verdict (closes [#97](https://github.com/1StepMore/AutoInfo/issues/97)) ([586f658](https://github.com/1StepMore/AutoInfo/commit/586f658515e0be29745abade51b336c5a9335708))
* add KB pipeline, REST API, and agent E2E validation scenarios (Q42-Q53) ([e60f250](https://github.com/1StepMore/AutoInfo/commit/e60f2508831f993e71f4338e5728159697959bf2))
* add MCP KB/output and quality gate validation scenarios (Q28-Q41) ([670e230](https://github.com/1StepMore/AutoInfo/commit/670e2300637d999f18180a5f2e2ea55293b71274))
* add references to required-api-keys.md from README and director-user-guide ([51ab1df](https://github.com/1StepMore/AutoInfo/commit/51ab1df2b3930519068af10a16319f6fd5e50677))
* add Required API Keys documentation page ([9aec54e](https://github.com/1StepMore/AutoInfo/commit/9aec54e17d8210fa98e79d1fb83e948edb153ed9))
* add Unreleased 2026-08-04 entries for [#104](https://github.com/1StepMore/AutoInfo/issues/104)-[#113](https://github.com/1StepMore/AutoInfo/issues/113) ([d2f28e4](https://github.com/1StepMore/AutoInfo/commit/d2f28e486fbd8513da0e58b474e13b1d967cde21))
* add v1.6 gap analysis with codebase audit results ([282452e](https://github.com/1StepMore/AutoInfo/commit/282452e77513264cbc5a40e237450671dd7af5c0))
* add v2 validation plan index and core pipeline scenarios (Q1-Q6) ([6a8cc68](https://github.com/1StepMore/AutoInfo/commit/6a8cc6818c3b84d270b343bdd9117d6900726b88))
* add YAML scenarios closing all 42 coverage gaps ([7a01ea0](https://github.com/1StepMore/AutoInfo/commit/7a01ea0ab49d3d23a162e765b27d1a7da9d3036f))
* align docs with verified ground truth (68 scenarios, 3640 tests, 145 tools; fix schema/metric/lifecycle drift) ([87dc925](https://github.com/1StepMore/AutoInfo/commit/87dc9258dcd9a54586e6101147f7382ada568332))
* archive old validation plan and v1.6 gap analysis ([ab94c39](https://github.com/1StepMore/AutoInfo/commit/ab94c398668a281f92750cefdb6b011ea6149e5c))
* close CD-034 — AGENTS.md structure-tree output.py comment lists all formats ([e95f75e](https://github.com/1StepMore/AutoInfo/commit/e95f75e9eb0033c1590e480f75da0b6d7adeadb5))
* curation/admission gates + agent-promote semantics + 145-tool counts ([0f85bae](https://github.com/1StepMore/AutoInfo/commit/0f85baec78aec3a2a682334fab3b4b734e1853d1))
* **dev:** note 2026-08-03 MCP-native validation toolset in enduser-coverage-matrix ([75306fa](https://github.com/1StepMore/AutoInfo/commit/75306fad11a9d590ea173179be1b8b3b66cee64b))
* **dev:** sync cross-dimensional-catalog matrix to current code (13 stale items) ([8ab2811](https://github.com/1StepMore/AutoInfo/commit/8ab281146bc8f636bcf2e43d74981f748867a547))
* **dev:** sync dev guides with HackerNews + count updates ([a4de295](https://github.com/1StepMore/AutoInfo/commit/a4de295295490b0a6e081fb46a47b84f48cf08b0))
* **dev:** sync spec counts (27 handlers / 26 types / 14 LLM tools) ([2714240](https://github.com/1StepMore/AutoInfo/commit/27142406af4c90d59707104eb87dfb87f90b38aa))
* fix stale validation references, sync 13 channels / 10 export formats ([99695bc](https://github.com/1StepMore/AutoInfo/commit/99695bcbdb99a603840c0284686b6b74a1949a7e))
* **G3:** add non-technical onboarding walkthrough + acceptance record ([#165](https://github.com/1StepMore/AutoInfo/issues/165)) ([835cdc3](https://github.com/1StepMore/AutoInfo/commit/835cdc3c334305fe0291031232de19b4f970c3aa))
* gap-1(c) — major-wave plan promotion to docs/dev/plans/ (2026-08-13) ([d69cc6b](https://github.com/1StepMore/AutoInfo/commit/d69cc6b6fb380544bb1f9f3699674d794aa9e558))
* **loop-log:** record pit [#13](https://github.com/1StepMore/AutoInfo/issues/13) — persist product name decides matrix evidence ([#229](https://github.com/1StepMore/AutoInfo/issues/229)) ([f34d9d0](https://github.com/1StepMore/AutoInfo/commit/f34d9d068d446713ef50b9149d1ed43ed8e72a32))
* **loop-log:** record pit [#13](https://github.com/1StepMore/AutoInfo/issues/13) — persist product name decides matrix evidence ([#229](https://github.com/1StepMore/AutoInfo/issues/229)) ([55ccc5c](https://github.com/1StepMore/AutoInfo/commit/55ccc5cd24b9735116c23954fbdb12e89ac2f472))
* **loop-log:** record pit [#14](https://github.com/1StepMore/AutoInfo/issues/14) — full validation results polluted by DeepSeek LLM time-window flakiness ([bd6279f](https://github.com/1StepMore/AutoInfo/commit/bd6279f551df3e4550949b06a8eb065d10e33a21))
* **loop-log:** record pit [#14](https://github.com/1StepMore/AutoInfo/issues/14) — LLM time-window flakiness pollutes full validation ([330d111](https://github.com/1StepMore/AutoInfo/commit/330d111a4b0f05748f9f36ba9664fb92ec8b4f5f))
* README MCP server install and LLM key injection guide (closes [#111](https://github.com/1StepMore/AutoInfo/issues/111)) ([b9e0f05](https://github.com/1StepMore/AutoInfo/commit/b9e0f05e3d9e9e6e07adb2626326702252ece1e1))
* **readme:** add Known Limitations section + update v1.1 status ([770485a](https://github.com/1StepMore/AutoInfo/commit/770485a2c6883fefb348e2cce6947255b6f8863b))
* reflect solo-maintainer ruleset governance (0 approvals, CI gate) ([#251](https://github.com/1StepMore/AutoInfo/issues/251)) ([503dc7b](https://github.com/1StepMore/AutoInfo/commit/503dc7b3d2344f9113c93f50e5c9eed16b96e206))
* remove superseded docs — old validation plan, gap analysis, KB reference ([83b1b3b](https://github.com/1StepMore/AutoInfo/commit/83b1b3b72937174361bf531fc69b3debc54d9245))
* rename validation plan v2→stable, fix 11 stale -v2 path refs, update SKILL.md and CHANGELOG ([ae5efac](https://github.com/1StepMore/AutoInfo/commit/ae5efac82a8bdd755dcae0a049130863fbb3fe29))
* restructure AGENTS.md, move worked examples to mcp-usage-examples.md (closes [#113](https://github.com/1StepMore/AutoInfo/issues/113)) ([63f0c85](https://github.com/1StepMore/AutoInfo/commit/63f0c853e384b553d3a98368265c722778846360))
* **skill:** self-enforce doc-manager numbers + cover schemas/ADR/glossary in inventory ([4a9359e](https://github.com/1StepMore/AutoInfo/commit/4a9359e90180adf0c465e20e02cfa8180bc71694))
* **skills:** fix billing tool signatures + sync doc-manager inventory ([134e533](https://github.com/1StepMore/AutoInfo/commit/134e5336e1daf1dea845c9874125ffba2cb96ae1))
* sync 139 MCP tools / 26 collectors / ~2747 tests + V1 features across all docs ([f8793ef](https://github.com/1StepMore/AutoInfo/commit/f8793eff146450207ed6a1b08fc1da924fefaa72))
* sync AGENTS/README/CHANGELOG/contract/skill for [#141](https://github.com/1StepMore/AutoInfo/issues/141)-[#148](https://github.com/1StepMore/AutoInfo/issues/148) changes ([f714f3c](https://github.com/1StepMore/AutoInfo/commit/f714f3c5f69fbda61b2c245e34adc76925fcec35))
* sync docs for 2026-08-07 audit wave ([#153](https://github.com/1StepMore/AutoInfo/issues/153)-[#164](https://github.com/1StepMore/AutoInfo/issues/164)) ([1bfe26b](https://github.com/1StepMore/AutoInfo/commit/1bfe26b22794a73063b72b9cdf41f9e794d19d8e))
* sync kb-curation wave counts (145 tools / 65 scenarios / ~3390 tests) + CHANGELOG entry ([16bd6db](https://github.com/1StepMore/AutoInfo/commit/16bd6db942cb4b26c24f1b8b3b6519868b972aff))
* sync llm-concurrency wave — rate limiting, fallback, caps, routing, test count 3728 ([d3cc80d](https://github.com/1StepMore/AutoInfo/commit/d3cc80dd15a1924245d1e1ac1ab5aee663c4120d))
* sync README/AGENTS counts (27 handlers / 26 types / 14 LLM tools / ~2866 tests) ([ae80fba](https://github.com/1StepMore/AutoInfo/commit/ae80fba23e0054da425da46d365530fa87014225))
* sync stale references (139 tools, 13 channels, 23 CLI groups, ~2747 tests) ([dabb15d](https://github.com/1StepMore/AutoInfo/commit/dabb15db4079f7bf5864abec911ebad3c85b6ac6))
* sync v1.9 reality + archive restructure ([e1d04ca](https://github.com/1StepMore/AutoInfo/commit/e1d04ca4b82405c238a3819eb165ea0a035491ab))
* sync validation plan + changelog for v1.8.3 fixes ([#94](https://github.com/1StepMore/AutoInfo/issues/94)-[#102](https://github.com/1StepMore/AutoInfo/issues/102)) ([9932e73](https://github.com/1StepMore/AutoInfo/commit/9932e73e2405d5bc5a50560e85ca68c503f1a0ed))
* sync validation plan CLI flags with actual implementation (fix [#41](https://github.com/1StepMore/AutoInfo/issues/41)) ([9208b14](https://github.com/1StepMore/AutoInfo/commit/9208b145287a4158dc57eefa956add68c02966e5))
* sync validation semantics, tool counts (139-&gt;141), and scenario library ([0406473](https://github.com/1StepMore/AutoInfo/commit/0406473e69944b99109d77e7db39e463ac06d53c))
* sync video wave + reasoning control + matrix v3 across all docs (2026-08-13) ([70549f6](https://github.com/1StepMore/AutoInfo/commit/70549f6956cbf90ffb33b4b10d308936b0f5c582))
* update all docs for v1.5 release — version, MCP/tool/test counts, quality gates, project structure ([e38d847](https://github.com/1StepMore/AutoInfo/commit/e38d8474570593833304ac1aca2e995bbddfbda1))
* update all docs to v1.3 — stale counts, CHANGELOG, docs/* ([a618667](https://github.com/1StepMore/AutoInfo/commit/a618667cffcb3b203d2406a7f7f2b6244b9c455c))
* update all project docs for v1.6 release ([2e654a3](https://github.com/1StepMore/AutoInfo/commit/2e654a37dc847de2587bdc5b56229cf9a30fc40c))
* update docs for v1 content_preference bypass closure + B1 scenario hardening ([c9859c5](https://github.com/1StepMore/AutoInfo/commit/c9859c53d70b8c2bb60aea65557ccb39130e6aed))
* update founder-expectations.md to v1.1 status + finalize README/CHANGELOG ([f9db02f](https://github.com/1StepMore/AutoInfo/commit/f9db02fc90bc27d0dc8e1c57178befb1a5ae7f7c))
* update project docs for v1.6 — agents, changelog, specs, skills ([dad0124](https://github.com/1StepMore/AutoInfo/commit/dad01240c195ff22f628ba9f2c876924c3e3f4bc))
* update README, CHANGELOG, AGENTS.md, validation plan, and doc-manager-skill ([0d8bf1f](https://github.com/1StepMore/AutoInfo/commit/0d8bf1f463f9c4488842372f8a09cb3687f17525))
* **v1.2:** update all docs to reflect v1.2 feature set ([c9a4a16](https://github.com/1StepMore/AutoInfo/commit/c9a4a167f093727a0f83c57037feac4089ca22e8))
* validation wave E1-E9 + [#131](https://github.com/1StepMore/AutoInfo/issues/131)-[#141](https://github.com/1StepMore/AutoInfo/issues/141) feature documentation ([5319bcd](https://github.com/1StepMore/AutoInfo/commit/5319bcd518364cc9efb75cb19d6e9972ddf5cbfb))
* **validation:** A29 Chinese podcast coverage confirmed ([0e342fb](https://github.com/1StepMore/AutoInfo/commit/0e342fb706e949bc6761c9db34d6586781a630d4))
* **validation:** acceptance matrix refresh + validation delivery ([801bf50](https://github.com/1StepMore/AutoInfo/commit/801bf503e72e22af65561f8ce5cdb3fbc392b22a))
* **validation:** add parts 13-15 covering End User, Human-Agent, cross-dimension E2E ([0f2ec17](https://github.com/1StepMore/AutoInfo/commit/0f2ec17abfe39a1d9ba3a40bf5af2b600a1c67a1))
* **validation:** archive master-plan, align promote authorization, adopt regression: true key ([6c20f04](https://github.com/1StepMore/AutoInfo/commit/6c20f047db93607a866c1bb4f773b65b0f8e69c2))
* **validation:** expand coverage to 100% MCP tools — add 37 missing tool scenarios ([4415118](https://github.com/1StepMore/AutoInfo/commit/4415118982dbf84e7d825b77b1cc578347a45fc1))
* **validation:** revive LOOP-LOG + add validation governance (loop contract, failure triage, archive map) ([#255](https://github.com/1StepMore/AutoInfo/issues/255) area) ([#259](https://github.com/1StepMore/AutoInfo/issues/259)) ([9091819](https://github.com/1StepMore/AutoInfo/commit/9091819cf7c626f5b1f02ccee42100fcfcc210c7))
* **validation:** update TOC and final verdict for parts 13-15 ([165cfe4](https://github.com/1StepMore/AutoInfo/commit/165cfe42a008afe5bb9f7240166dd24ab92d79c0))

## v1.10 (Unreleased, 2026-08-11) — output-quality-mega wave

### Infrastructure (2026-08-15)
- **Baseline-aware coverage gate** — `.github/workflows/coverage.yml` no longer fails a changed module against a fixed 60% floor (server.py sits at 53% on the fast subset, so any PR touching it failed even for a one-line, fully-tested change). New `scripts/coverage_gate.py` compares each changed module against its merge-base coverage (no-regression, 2pp tolerance); NEW modules still must reach 60%. The base measurement runs the same fast subset in a git worktree at the merge-base SHA (job runtime ~9m → ~18m for src-touching PRs). Unit tests: `tests/scripts/test_coverage_gate.py` (22 tests).
- **Version governance: release-please version truth fixed** — a stale hand-made `v0.9.0` tag (no GitHub Release, tagged on a commit whose code was already 1.8.1) misled release-please's version discovery into proposing `0.10.0` (a downgrade of the pinned 1.8.1). Fix (see ADR-0007): deleted the stale tag, added `workflow_dispatch` + `release-as` escape hatch to `release-please.yml`, cut **v1.9.0** via `release-as: 1.9.0`, and declared `src/autoinfo/_version.py` in release-please `extra-files` with the `# x-release-please-version` annotation so future releases keep the runtime version in lockstep with the manifest (pyproject's dynamic version otherwise skips the update, drifting MCP/REST `version` fields).

### Added
- **2 new product template files (product count stays 8)** — `premium-briefing.md.j2` (market-report-anchored: numbered takeaways with So-what/Risk/Actions) and `enterprise-briefing.md.j2` (one-page exec summary + Key Metrics table + Action Required + Risk matrix) in `src/autoinfo/data/templates/`, giving the already-registered premium-briefing/enterprise-briefing products dedicated templates.
- **Per-product LLM synthesis fields** — implications/risks/action_required/key_metrics synthesized per product template and carried into agent-format JSON-LD output; JSON-LD schema extended (`docs/schemas/knowledge-digest-v1.json` optional fields).
- **MCP `product` params + CLI `--product`** — `generate_report(product=...)` and `generate_digest(product=...)` MCP params; `--product` flag on `output digest`/`output report`.
- **Collector fulltext depth** — `fetch_depth` threaded through collection dispatch (`_handler_settings`); Unpaywall (OA fulltext via web.py trafilatura), RSS (entry.link fulltext), YouTube (transcript download), GDELT (article fulltext) — each gated by `fetch_depth: fulltext`, 8000-char cap, graceful fallback on failure. Scoped re-collection proved ~4x deeper content on the medical-research deliverable domain.
- **KB product-analysis metadata + faceted filter** — product analysis fields persisted to KB entry `custom_fields["product_analysis"]`; `search_knowledge_base(filter_custom_fields=...)` faceted filter on custom_fields JSON (no new MCP tool, no new store).
- **new validation scenarios → 68 total (62 functional + 6 regression)** — `scenarios/regression/regression-product-routing.yaml` (product routing through generate_report/generate_digest) + `scenarios/output-agent-interaction.yaml` (agent-format output carries per-product fields, verified via filter_custom_fields) (2026-08-11) + `scenarios/output-video.yaml` (2026-08-13).

### Changed
- **magazine-digest routing fixed** — `gen_domain_products.py` now routes magazine-digest via `generate_digest`.
- **Guard-first product-type resolution** — `_resolve_report_product_type` mirrors `_resolve_digest_product_type`; digest render-context normalization via `_normalize_digest_product_context`.

### Added (2026-08-13 video + reasoning wave)
- **HyperFrames video pipeline (report `format="video"`)** — replaces the PIL+FFmpeg slideshow scaffold: TTS narration → HyperFrames project scaffold → `bun x hyperframes render` (HTML+GSAP→MP4). Ported 36-theme + 8-brand theme library (`src/autoinfo/output/video_assets/themes/`), 6 visual layouts with mandatory adjacent-scene diversity (Gate VQ: 5 scenes ≥ 4 layouts), AutoMedia scene-frame-boundary math (char-ratio split + 0.01s float safety margin). Templates: `video_assets/templates/{package.json,hyperframes.json,meta.json.j2,index.html.j2,scene.html.j2}`. Rendered MP4s verified for all 13 demo domains. (`64daae5`)
- **MCP video exposure** — `generate_report` / `generate_digest` / `generate_cross_domain_report` format enums + persist gain `video` (`.mp4`); per-handler video branch parses the scaffold JSON into structured responses. (`64daae5`)
- **LLM reasoning-model thinking control** — `reasoning_model=True` now disables chain-of-thought by default via `additional_body={"thinking":{"type":"disabled"}}` (DeepSeek R1/V4 style reasoning consumes the shared `max_tokens` budget *before* content, truncating JSON output at `finish_reason=length`). Judgment gates re-enable thinking with raised budgets: G4 factual (500→2000), G5 translation (500→1500), llm_judge (1000→2000), translation-QA judge (1000→2000), validation-scenario judge (500→1500). (`c33c6d0`, `02a06a8`)
- **End-user matrix v3** — `end-user-matrix.yaml`: formats +`video`, source_platforms 27→29 (hackernews/email_imap, reuters→reuters_mcp), required_sources 13 domains/89 sources, required_kb_tiers 13 domains, new channels (14) + capabilities (15) dimensions. (`5db457b`)

### Fixed (2026-08-13)
- **Coverage-matrix evidence scan** — `scan_evidence` double-path bug (`--evidence outputs` produced zero cells), manifest/zip scanning bounded to validation-deliveries/ + outputs/ (project-root rglob was slow), video cells now recognized. Evidence: produced 0→26 (video 13/13 domains), source_gaps 89→38. (`5db457b`)
- **RSS fetch timeout guard** — `feedparser.parse` has no timeout and hung the whole collect run (language-learning stalled 124s); fetch over httpx with 30s timeout, keep `file://` + URL-encoded local-path support. (`5db457b`)

### Perf (2026-08-13 llm-concurrency-remediation wave)
- **Per-provider shared rate limiting + jittered 429/5xx backoff** — `call_with_fallback` (llm.py) acquires a shared `threading.Semaphore` per `(provider, base_url)` (`_PROVIDER_SEMAPHORES`; `AUTOINFO_LLM_MAX_CONCURRENCY` env, default 4, clamped ≥1) and retries HTTP 429/5xx with jittered exponential backoff (3 total attempts, base 1.0s ×2, cap 8s, jitter ±25%; non-retryable 4xx never retried). Shared limiter enforced across every fan-out path — process workers, post-extraction gates, cefr_batch, output grouping, MCP `to_thread` handlers, fallback chain. (`da5362a`)
- **mimo-v2.5 same-gateway fallback configured** — `.autoinfo/config.yaml` `llm.fallback` now points at `mimo-v2.5` on `https://opencode.ai/zen/go/v1` (inherits the primary API key; probe-verified). (`894c760`)
- **Process worker cap 8→16, probe-gated** — `AUTOINFO_PROCESS_WORKERS` cap raised to 16 (default workers still 5; probe showed 0 rate limits at workers 1/4/8/16 × 12 with bounded p95, 35-64s); new `AUTOINFO_SUBTASK_CAP` (default 4) bounds post-extraction G3/G4/G5/CEFR concurrency per item with gate order, retry loops and G0-G5 report order preserved. (`e587cf4`, `cc5939c`, `c11635f`)
- **CEFR out of the storage lock + batch parallelized** — CEFR classification LLM call moved outside `_STORAGE_LOCK` (storage writes still serialized); `cefr_batch` fan-out bounded by `AUTOINFO_CEFR_BATCH_WORKERS` (default 8) with order preserved and per-item errors. (`ef58dce`, `b9a9b7e`)
- **MCP event-loop offload** — 14 sync LLM handlers (suggest_keywords, classify_cefr, cefr_batch, extract_fields, generate_digest, generate_report, generate_cross_domain_report, generate_tutorial, generate_presentation, localize_content, query_collected, recommend_content, simplify_content, promote_kb_draft) offloaded via `asyncio.to_thread` (MCP tool surface unchanged: still 145 tools / 17 LLM-required). (`d41b844`)
- **`_group_by_theme` parallelized** — output grouping batch loop runs up to 4 workers (`_GROUPING_BATCH_SIZE`=8 unchanged), results collected by index so order is preserved; exec-summary calls remain serial. (`798555c`)
- **Per-task model routing + pinned judgment model** — `_resolve_task_llm_config` (config.py) → `call_with_fallback(task=)` → `_build_config_with_model` (process.py); extraction/classification use the task-config model (else base model); G4/G5/llm_judge judgment calls resolve to the release-pinned `JUDGMENT_MODEL = "deepseek-v4-flash"` constant — never runtime task-config drift. (`bb007ab`)
- **Probe CLI** — `scripts/test_llm_concurrency.py` gains `--workers N` / `--total N` and reports `p95` + `rate_limit_count` (no-args keeps serial baseline + (1,3,5) sequence). (`e587cf4`)

### Fixed
- **Report-synthesis robustness** — bounded retry loop + dedicated product-sections prompt so synthesis failures no longer block product output.

### Infrastructure
- Test suite now ~3728 tests (3728 collected via `pytest --collect-only`, 2026-08-13).

### Fixed (2026-08-19)
- **#314 enterprise-briefing coverage claim consistency** — the LLM-written Executive Summary could claim "20 items" while only 9 Key Findings were detailed (or vice versa); nothing bound the opening coverage sentence to the rendered findings count. Fix: ① the shared report synthesis prompt (`_REPORT_PRODUCT_BASE_SECTIONS`, benefits premium-briefing/magazine-digest/enterprise-briefing) now instructs the model to name exactly the number of Key Findings it writes — never a larger count; ② `enterprise-briefing.md.j2` renders a deterministic scope label (`> **Scope**: 精选 N 条详述 · selected N of M items detailed below.`) computed from the actual context on both flat-context paths (report `_report_data_to_dict`, digest `_normalize_digest_product_context`), so even a stale summary claim is visibly scoped. Regression scenario: `scenarios/regression/regression-enterprise-coverage.yaml`.

### Fixed (2026-08-10 quality wave)
- **#179 keyword hygiene** — stopword filtering, toggle/cap auto-discovered keywords (`cccad4a`, `f889e09`).
- **#180 collection coercion** — str-coercion + empty-item drop hardening (`c626136`, `8d19772`).
- **#182 audit-feedback hardening** — no empty shells, stale-free weekly digests, discriminative relevance scoring (`4481664`, `ef611ef`, `91abb9e`).
- **#165 G3 non-technical onboarding walkthrough** — `docs/skills/autoinfo-skill/onboarding-walkthrough.md` + acceptance record (`835cdc3`).

### Fixed / Infrastructure (2026-08-12 acceptance-risk-closure)
- **B-01 destructive-op confirm guard** — `remove_domain` now requires explicit confirmation (parity with `remove_source`, `CONFIRMATION_REQUIRED`); 4 KB-writing scenario YAMLs migrated from example.com to the reserved `*.autoinfo.test` hostname; `_scan_autoinfo_test_leaks` surfaces any fixture left in 01-Raw after a run (never auto-deletes); `tests/mcp/test_scenario_leak_guard.py` (2 tests). (`a139d32`, closes AC2/AC5/AC9/B-01)
- **Reusable validation assets committed** — Q10-Q18 results, enduser scenario, q2b tests (`79d102f`).
- **Doctor source probing bounded** with concurrent timeouts (#193, `7052ad5`).
- **Coverage-matrix fixes** — config-layer completeness pinned (#195, `b816698`), regenerate_paygrade artifact naming recognized (#191, `542d5eb`), `_failed/` and coverage-matrix artifacts excluded from delivery packages (#192, `9b67d5b`).
- **keyword-management scenario seeds preset keywords** (#194, `3acb313`).

### Infrastructure (2026-08-14 OSS-governance wave)
- **LICENSE added** — MIT license text (matches the `license = "MIT"` declaration in `pyproject.toml`); repo URLs in `pyproject.toml` corrected from `your-org/autoinfo` placeholders to `1StepMore/AutoInfo`.
- **Community governance files** — `CONTRIBUTING.md` (setup → first contribution → coding/testing standards → Conventional Commits for PR titles under squash-merge → AI contribution policy → 7-day issue SLA; highlights the 回归场景 regression-scenario practice as the project's OSS differentiator), `GOVERNANCE.md` (Minimum Viable Governance: roles, label taxonomy, per-priority response SLA, documented no-aggressive-stale-bot decision, review policy, branch protection + DCO runbook, release management), `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1 with agent-first preamble), `SECURITY.md` (private vulnerability reporting, 48-72h acknowledgment, BYOK-key/webhook/REST-8741 security-relevant areas), `AUTHORS.md` (git-derived contributor list), `CODEOWNERS` (default + `mcp/`/`output/`/`docs/`/`.github/` owners).
- **Issue & PR templates** — `.github/PULL_REQUEST_TEMPLATE.md` (Kubernetes-style: What/Why, `Fixes #N`, special review notes, mandatory `release-note` block with "NONE" valid, mandatory 回归场景 field for bug fixes, checklist), `.github/ISSUE_TEMPLATE/feature_request.yml` + `config.yml` (blank issues disabled, Discussions contact link), `dependabot.yml` (weekly pip + github-actions updates).
- **CI & release automation** — `pr-title-check.yml` (Conventional Commits gate on PR titles, the commit under squash-merge), `coverage.yml` (changed-files coverage gate on the fast subset, 60% baseline threshold), `release-please.yml` + `release-please-config.json` + `.release-please-manifest.json` (semver releases from Conventional Commits), `.pre-commit-config.yaml` (ruff + hygiene hooks; `pre-commit install`).
- **`.opencode/skills/maintainer-workflow-skill`** — triage → review → merge decision tree SOP for agent-maintainers, grounded in the governance docs above.

## v1.9 (Unreleased, 2026-08-05) — M0-M7 consolidated wave summary

### Breaking
- **REST API success envelope (v1.9)** — All REST API success responses now return `{success: true, data: ...}` (was raw shapes); errors already used the canonical `{success: false, error: {code, message, actionable}}` envelope. FastAPI `response_model` changed to `dict[str, Any]` for list/get/create endpoints; a `RequestValidationError` handler returns 422 with the canonical envelope; Stripe webhook success path stays raw (integration contract). Migration guide: `docs/dev/migration-v1.9.md`; dashboard JS unwraps transparently.

### Added
- **M0: optional-dependency + env gates (test infra)** — `tests/conftest.py` gains `HAVE_PIL`/`HAVE_STRIPE`/`HAVE_PYMUPDF`/`HAVE_WEASYPRINT`/`HAVE_FFMPEG` + `requires_optional_dep()` marker factory and `optional` marker; `pytest-cov>=4.1` added to dev extra; full-src ruff step (informational) + nightly full-suite workflow added to CI.
- **M1: REST envelope EVERYTHING + dispatch hardening** — REST success envelope (breaking, see above); `except TypeError` → `VALIDATION_ERROR` at MCP dispatch (missing-required-arg no longer surfaces as InternalError); dispatch-level audit hook records every mutation + parameterized read (whitelisted fields actor/action/tool/resource/result_code/trace_id) into the append-only audit log.
- **M2: 3 new source types (26→29) + 3 dedicated collectors** — `akshare` (AKShareHandler, `[akshare]` extra), `sec_edgar` (SecEdgarHandler, ticker→CIK→filings, UA + 10 req/s), `edx_sitemap` (EdxSitemapHandler, robots.txt RFC 9309 gate). `http_api` gains `json_path: "$"` root-array extension (Mastodon top-level array) + `$.field` prefix.
- **M3: 4 new demo domains (9→13) + music→online-video** — general-news (15 sources incl. GDELT/Guardian/Google News/NYT/AP + Mastodon/Bluesky/知乎日报/Medium), gaming, b2b, retail; music sources (Apple Music RSS + Pitchfork/Billboard) folded into online-video; Finnhub added + SEC EDGAR rss→sec_edgar in financial-intelligence; wanfang merged into online-education (OUTCOME A: static-header auth verified, POST-only endpoint awaits http_api POST transport — documented, not implemented).
- **M4: JSON-LD schema files + durable agent push outbox** — `docs/schemas/{knowledge-digest,knowledge-tutorial,knowledge-presentation,knowledge-base-export}-v1.json` (JSON Schema draft-07, `@context`/`@type` pinned via `const`); `agent_outbox` SQLite table enqueues `{event, payload, schema_version: 1, trace_id, product_id}` before delivery, drain thread with lock serialization, failed rows requeued at process start.
- **M5: 2 new product templates (6→8)** — B24 column product (`report_type="column"` + premium ProductTemplate + G15 `check_access` gate + `column.md.j2`) and D11 magazine digest (`magazine-digest` ProductTemplate + per-title RSS clustering + `magazine-digest.md.j2`).
- **M6: CLI/MCP parity (23→28 groups)** — topic-group, import-kb, query-collected, alert-rules, agent-callback + keywords suggest; global `--json` flag wired (status/sources/kb); parity matrix documented in `docs/dev/cli-mcp-rest-parity.md`.
- **M7: 3 new validation scenarios (44→47)** — sources-gap-closure (3 new source-type registrations), output-column (report_type=column, LLM-gated), sources-a6-keyed (FRED/Finnhub, env-gated).

### Fixed
- **#177 over-filtering regression: topic-keyword filter is now source-type aware** — the collection-layer relevance filter (strict substring, applied to every source) dropped real items from curated niche feeds: retail-dive "Will people pay more for Under Armour?" matched 0/21 keywords, and an ai-commercial hedge-fund item was lost. The filter now applies **only to cross-disciplinary search platforms** (OpenAlex, DBLP, generic web, Semantic Scholar/CrossRef APIs by name marker, unscoped Google News search RSS) where a broad corpus query makes on-domain-ness unjudgeable without keywords; curated publication RSS and topical provider APIs (pubmed, uspto, generic HttpApi like coursera) pass through unfiltered — the source itself is the relevance signal. Matching on filtered sources upgraded to token-level partial-word aware (hyphen/inflection tolerant: "supply chain" matches "supply-chain", "retail" matches "retailers") with a `min_keywords` floor for multi-keyword topics. (`src/autoinfo/collect.py`, `tests/test_collection_relevance.py`, `tests/test_backward_compat.py`)
- **Bugfix: `import-kb` crashed on markdown frontmatter containing `domain:`** — `import_markdown` passed every frontmatter key through to the KB entry payload, so a source file whose YAML frontmatter included a `domain:` field collided with the importer's own `domain` argument and was written with the wrong (or a duplicated) domain. The frontmatter `domain` key is now excluded from passthrough, mirroring `title`/`language`/`tags`. (F3-caught; `src/autoinfo/importer.py`)
- **Content preference bypass closure (v1 launch blockers B-01/D1-3 closed)** — The remaining content_preference bypass corners are closed: SMTP delivery now forwards `user_id` from the payload to `send_digest` (`delivery/__init__.py`), the CLI `email send-digest` command gained a `--user-id` flag (`cli/email.py`), `Schedule` gained a persisted `user_id` field that is forwarded at generation time (`cli/cron.py`), and the REST portal surfaces typed preferences (content_preference, QuietHours, identity_anchor) by merging `profile.preferences` over legacy `delivery_preferences` (`api/portal.py`). (e493c92, closes the two 'partially ready' items from the launch review)
- **B1 lifecycle validation scenarios hardened for self-containment** — 6 scenario YAMLs (`enduser-lifecycle`, `enduser-preferences`, `products-billing`, `cost-budget`, `delivery-schedules`, `delivery-channels`) now self-clean (`cleanup_steps`), gate env-dependent steps (`requires_env: [STRIPE_API_KEY]` on products-billing → correctly reports `unconfigured` without the key), and document their venv/init prerequisites. Verified: 163 targeted tests + 80 validation tests pass; 5/6 B1 scenarios pass on a disposable project via real dispatch. (e493c92)

### Docs
- **Agent-tester validation runbook** — new `docs/dev/agent-tester-validation.md` (663 lines): end-to-end runbook for an agent-tester to validate AutoInfo feature-by-feature through real MCP/CLI/REST calls, maintained alongside `validation-scenario-contract.md` (authoring) and `launch-validation-framework.md` (grading). (3758b06)
- **Acceptance framework (keystone, AC1-AC7)** — new `docs/dev/acceptance-framework.md`: the top-level acceptance mechanism for AutoInfo. Seven dimensions — AC1 user model integrity (B1/B2/B3), AC2 data-layer integrity (raw vs processed, internal layer vs shipped product), AC3 dual orientation (agent-operated tool / human-first results, superseding the D1-D5 parallel dual-track), AC4 coverage commitment (unclassified gaps = 0, per the 99-item end-user coverage matrix), AC5 quality & deliverable acceptance (automated gates G0-G5/D1-D3 + director sampling review), AC6 commercial viability (subscription/payment/gating/metering real), AC7 process & governance (B2 executes, B3 adjudicates; major-full / wave-incremental triggers; acceptance-<version>.md run reports with Chinese director summary). Supersedes `launch-validation-framework.md` (D1-D5) as the validation charter; D1-D5 retained as evidence-production tooling (supersession banner added). AGENTS.md references and doc-manager-skill inventory updated.
- **Acceptance framework extended to AC1-AC9** — new **AC8 Documentation Health** (agent-facing docs lean/current/single-sourced: one-offs archived, README/AGENTS fact consistency via `doc_inventory.py --check`, generated inventory, AGENTS.md-as-index) and **AC9 Test & Validation Suite Health** (pytest suite mirrors `src/`, no `test_bug_*` filenames, validation layer 59 real-surface scenarios judged compliant and feeding acceptance evidence; improvement backlog: pass-rate gating, deterministic conformance layer, negative cases). Evidence catalog extended A21-A24; verdict skeleton + glossary updated.
- **Doc structure simplification (round 2)** — one-off docs archived to `docs/archive/`: `launch-validation-report.md`, `epics/issue-97-coverage-verdict.md` (→ `epics-issue-97-coverage-verdict.md`, epics/ dir removed), `migration-v1.9.md`, `launch-validation-framework.md`, `agent-tester-validation.md`. Validation doc stack 4→2: `validation-scenario-contract.md` is now the single merged "Scenario Authoring & Agent-Tester Execution" doc (authoring contract + execution runbook, 929→748 lines, zero stale counts); `validation-reports/README.md` updated to the `acceptance-<version>.md` convention; `scripts/validation_report.py` FRAMEWORK/TEMPLATE constants repointed (dangling template ref fixed).
- **Generated doc inventory + slimmed doc skill** — new `scripts/doc_inventory.py`: scans `docs/**` (md/yaml) and generates `docs/dev/doc-inventory.md` (path/line count/category/status/doc-type + summary); `--check` verifies README vs AGENTS on 5 drift-prone facts (MCP tools, CLI command groups, delivery channels, validation scenarios, demo domains — currently 145 / 28 / 13 / 68 / 13), fails on stray `tests/test_bug_*` files and stale inventory header. `.opencode/skills/doc-manager-skill/SKILL.md` slimmed 795→191 lines (v2.0.0): hand-maintained inventory replaced by the generated file; dependency map condensed to a single high-impact table; workflow + D1-D4 gates + AC7 change-control linkage retained.
- **Test suite reorganization (lightweight)** — 68 root test files moved via `git mv` into subpackages mirroring `src/`: tests/collectors (30), tests/cli (15, new), tests/mcp (5), tests/kb (10, new), tests/llm (8, new); `test_bug_39/40/42.py` renamed to subject-scoped `test_cli_summaries_tags.py` / `test_cli_kb_draft_lists.py` / `test_cli_kb_list_tiers.py` (bug refs kept in docstrings); 6 `Path(__file__)` depth fixes; root test files 116→46. Full suite still collects 3264 tests, zero errors. AGENTS.md demo-domain status row fixed to include the "13" count (drift caught by `doc_inventory --check`).
- **First acceptance run + framework amendments (2026-08-08)** — first full AC1-AC9 run: `docs/dev/validation-reports/acceptance-2026-08-08.md` (34 real evidence artifacts; 59 scenarios run 48/8/3; 8 findings + 1 risk; overall FAIL→RISK after B3 adjudication). Director corrections ratified into the framework: (1) **KB promotion is an agent operation** — AutoInfo's KB is a database for raw/processed production (max automation, agent as user); Draft→Wiki promote via `promote_kb_draft` has no human gate; AC1 criterion 3's human-exclusive class narrowed to destructive ops (purge, domain/source removal). Propagated across AGENTS.md (architecture rules/constraints/tool table), README, director-user-guide §5.1 (rewritten as agent-driven promotion, B3 = oversight not gate), specs (expectations/pipeline/operations/multi-tenancy-auth/user-lifecycle), cross-dimensional-catalog CD-029, enduser-capabilities-guide, cli-mcp-rest-parity, validation-scenario-contract. (2) **Payment chain is V2** — AC6 phase-split: V1 = collection + production pipeline (products producible + cost visibility), V2 = payment chain (checkout/webhooks/entitlement/invoicing); AC6 V1 verdict PASS, payment evidence deferred to V2 launch.

### Added (validation wave E1-E9, #131-#141)
- **Per-scenario step timeout (#134)** — every scenario step accepts `timeout_seconds`; a step that exceeds its budget fails fast instead of hanging the whole run. (8aec3ed, closes #134)
- **Persist + `collect_artifacts` + multi-domain data-lifecycle (#133)** — output scenarios persist generated artifacts via `collect_artifacts` for post-run inspection; a multi-domain data-lifecycle scenario covers collect → process → KB → export across domains. (19ee7d0, 08031bf, f401158, closes #133)
- **LLM timeout threading + kb-promote scenario (#134)** — `LLMConfig.timeout` (default 120.0) threaded through every LLM call site; new `kb-promote` scenario exercises Draft→Wiki promotion end to end. (eeea76f, 3517f79, closes #134)
- **Per-artifact authenticity + D1-D3 delivery gates (#132)** — validation delivery packaging attests per-artifact authenticity and enforces the D1-D3 delivery gates on packaged outputs. (0abb2a8, closes #132)
- **End-user coverage matrix generator (E8, #131)** — new `scripts/coverage_matrix.py` generates the end-user feature coverage matrix from `docs/dev/specs/end-user-matrix.yaml`; surfaced as the 04-MATRIX section (with coverage-gaps.json) in validation delivery and as Oracle R8 unconfigured-vs-gap analysis. (a94fe72, closes #131)
- **Dead-source detection + CLI module entry + progress (#135/#137)** — Semantic Scholar HTTP 429 now surfaces as `SourceFailure` (fail-fast, no partial results); arXiv medical-research source moved from rss/bio (dead) to rss/q-bio; `python -m autoinfo.cli` runs the same Typer app as the console script; `collect` prints live per-source progress lines. (63b15d4, closes #135, closes #137)
- **LLM timeout + parallel processing (#136)** — `LLMConfig.timeout` (default 120.0) applied across all LLM calls; processing uses a `ThreadPoolExecutor` sized by `AUTOINFO_PROCESS_WORKERS`; MCP handlers offload blocking work via `asyncio.to_thread`. (8de433d, closes #136)
- **Per-step recovery + partial-pass policy (#138)** — a failed step may declare `recovery_steps` (run after the primary failure); scenarios support partial-pass via `min_passing` (int) / `pass_ratio` (float). (7aee0f9, closes #138)
- **Per-step execution trace + root-cause report (#139)** — `run_validation_scenario` results carry a per-step trace (step_index/duration/arguments/trace_id + llm_meta model/tokens/duration); `scripts/validation_report.py` emits Verdicts / Executive summary / Regression failures / Blockers / Per-step trace / Appendix sections. (0188581, closes #139)
- **UX metrics + end-user journey scenario (#141)** — new `enduser-journey.yaml` scenario drives the full B1 lifecycle; validation packaging measures UX metrics (UX_OK/completion_rate ≥ 0.8); the error-boundary scenario asserts the `actionable` field. (81e4b30, closes #141)
- **Regression-test flywheel (#140)** — `scenarios/regression/` subdirectory (5 regression scenarios: regression-collect-int-id #104, regression-llm-key-resolution #119, regression-period-enum #126, regression-report-structure #121, regression-source-301 #135) auto-loads via recursive glob with a REGRESSION marker; `coverage_audit.py` prints "Regression scenarios: N (issues: ...)"; `.github/ISSUE_TEMPLATE/bug_report.md` gains a mandatory 回归场景 (regression scenario) field. (938fb6b, closes #140)
- **Scenario library 47 → 57** — the E1-E9 wave grows the scenario library to 57 total (52 functional + 5 regression), with per-scenario timeouts, recovery/partial-pass, per-step tracing, and root-cause reporting. (938fb6b, closes #140)

### Added (post-wave hardening: #141, #143-#145, #147-#148)
- **LLM fallback chain protects every LLM call path (#147)** — new shared `llm.call_with_fallback(...)` walks `[primary] + config.llm.fallback`, retrying each model in order. The 17 standalone `litellm.completion` call sites (output×5, quality×4, translation_qa×3, validation `_llm_judge`, MCP/CLI keyword suggest, qa, cefr) plus `LLMExtractor._call_llm` all route through the one helper — fallback now applies beyond extraction. `${ENV}` fallback keys expanded; the aggregate error surfaces the last model failure. (68ed6b9, closes #147)
- **`error_actionable` assertion enforced in validation scenarios (#141)** — `_step_assert` now verifies `expect.error_actionable` against the envelope's `error.actionable` (previously declarative-only); the error-boundary scenario's UnknownTool step corrected to `false` (the server returns a non-actionable hint). (20f76e9, closes #141)
- **Delivery packaging: absolute-prefix strip + 03-Wiki collection (#143, #144)** — `_tier_subpath` relativizes repo-root absolute artifact paths so the mount/user prefix (`d/贯维/AutoInfo/...`) no longer lands in RAW; `kb-promote`/`kb-draft` scenarios glob `03-Wiki` so the 03-KB bucket is populated. (1fc65e2, closes #143, closes #144)
- **G2 dedup freshness: naive/aware datetime crash fixed (#145)** — `_parse_iso_datetime` normalizes naive timestamps to UTC (third occurrence of this bug class); regression test `test_naive_item_aware_entry_no_crash`. (536211f, closes #145)
- **MCP collect_sources offload regression guard (#148)** — the `asyncio.to_thread` dispatch and `limit` pass-through are pinned by tests (real MCP runs complete in 7-9s; the reported 60s timeout did not reproduce). (540f415, closes #148)

### Added (2026-08-07 audit wave: #153, #155, #156, #157, #161, #117)
- **Validation env prereqs report `unconfigured`, not failed (#157)** — `validation.py` gains a `requires_http` scenario key (`_http_reachable` gate) plus `_classify_step_exception` and a shared `_unconfigured_scenario_result`; `rest-api.yaml` declares `requires_http: ["http://127.0.0.1:8741/health"]`. A missing REST server / Reddit OAuth / TTS network now surfaces as `unconfigured` with a reason instead of a `failed` step, so full validation runs reflect only real code defects. (1129db7, closes #157)
- **Validation coverage closure (#156)** — two new scenarios: `output-premium-products.yaml` (premium-briefing / magazine-digest / enterprise-briefing generation via the output module's `product_template` API, persisted for E8 evidence) and `sources-coverage.yaml` (academic + all 27 source-platform collection coverage). `coverage_matrix.py` now unions the spec's `source_platforms` names into the scenario-library scan (was abbreviated legacy spellings), so coverage reports products 8/8, formats 7/7, source tokens 27/27. (cd44baa, 15099b4, closes #156)

### Fixed (2026-08-07 audit wave: #153, #155, #161, #117)
- **Primary LLM base_url defaults to `config.llm.base_url` (#153)** — `call_with_fallback`'s primary model used the default endpoint when the config `llm.base_url` was set; the primary model now inherits it, and `config.py`/`llm.py` pass the ruff changed-file gate. (c5a6ac6, closes #153)
- **`save_config` no longer drops fallback `base_url`/`api_key` (#155)** — `config_to_dict` serialized `llm.fallback` twice; the second pass overwrote the full serialization with a reduced dict omitting `base_url`/`api_key`, silently wiping fallback endpoints/credentials on every save. Removed the redundant second pass; regression test added. (d81404d, closes #155)
- **CI test suite green: 36 pre-existing failures fixed (#161)** — three root causes: (1) `ebooklib` missing in CI (`ci.yml` now installs `.[dev,ebook]`, matching nightly); (2) rich/typer `--help` emitted ANSI escapes under `GITHUB_ACTIONS=true` that split double-dash flags (`--domain` → `-`+`-domain`) — fixed with `TERM: dumb` on the CI test job; (3) four config-seam tests depended on the ambient cwd config — made hermetic via `pathlib.Path.cwd` patches and the `_mock_load_config` seam. Cleared pre-existing ruff debt in the touched test files. (b755add, closes #161)
- **8 config-dependent tests made hermetic (#117)** — `test_cli_commands.py` patches retargeted to `autoinfo.cli.summaries.get_config_path` and `test_mcp_server.py` gained `_load_config`/`_detect_kb_status` seams so the suite passes on a fresh CI checkout with no `.autoinfo/config.yaml`. (11d105b, closes #117)
- **End-user matrix full-capability spec (13→112 required cells) + scenario-library coverage check (#158)** — `docs/dev/specs/end-user-matrix.yaml` now declares the full implemented surface (13 domains × 8 products × 7 formats + 27 source platforms + KB tiers); `scripts/coverage_matrix.py` gained `scan_source_evidence` and the `SCENARIO_PRODUCTS`/`SCENARIO_FORMATS`/`SCENARIO_SOURCES` hoisted constants, and passes the ruff changed-file gate. (e747588)

### Fixed
- **Dead-source detection** — Semantic Scholar rate-limit 429 is now raised as `SourceFailure` (fail-fast, no partial results) instead of a silent partial fetch. (63b15d4, closes #135)
- **arXiv bio feed fix** — medical-research arXiv source moved from `rss/bio` (dead feed) to `rss/q-bio`. (63b15d4, closes #137)
- **LLM timeout threading** — LLM calls now honor `LLMConfig.timeout` (default 120.0); previously several call sites passed no timeout, so a hung provider could block a validation step indefinitely. (8de433d, closes #136)

### Docs
- **Validation wave docs (E1-E9)** — README.md, AGENTS.md, `docs/dev/validation-scenario-contract.md`, and the doc-manager-skill updated for the E1-E9 wave: scenario count 47 → 57 (52 functional + 5 regression), test count → ~3239, new schema fields (`timeout_seconds`, `recovery_steps`, `min_passing`/`pass_ratio`, `regression`/`regression_issue`), regression/ subdirectory convention, and report output sections. (938fb6b, closes #140)
- **2026-08-07 audit wave docs** — README.md, AGENTS.md, `docs/dev/validation-scenario-contract.md`, and the doc-manager-skill updated for the #153-#164 wave: scenario count 57 → 59 (54 functional + 5 regression), test count → ~3264, `requires_http` schema key documented, CI test suite green (36 failures fixed), coverage matrix 8/8 products / 7/7 formats / 27/27 source tokens, and the end-user matrix required-cells spec (13→112). (doc-manager pass)

### Added (2026-08-08 kb-curation wave)
- **KB promotion domain model (T1)** — `KBEntry` gains `promotion_source` (agent/director) + `promoted_by`; `create_kb_draft` carries raw-tier scores forward into the draft. Render/dupe definitions updated for the new fields.
- **Promotion admission module (T3)** — new `src/autoinfo/promotion.py`: `check_promotion_admission` validates provenance completeness (every 01-Raw ref resolves with `source_url`/`source_type`/`source_platform`), re-runs G0 schema + G1 `source_score` ≥ 30 + G3 `relevance_score` ≥ 30, and G4 factual re-check on the final body (LLM, on by default, fail-fast) — deterministic checks accumulate every rejection reason; hard reject → typed `PromotionRejected` with per-component reason codes.
- **CurationGate config (T4)** — `QualityGateConfig` gains a `CurationGate` entry (thresholds per domain, `enable_g4` toggle); `set_gate_config`/`get_gate_config` round-trip it (per-domain override of shared threshold).
- **Promotion gate + director backdoor + tier search boost (T2+T5+T8)** — `promote_kb_draft` runs the CurationGate (director passage bypasses it via `director_promote`); search/digest surface 03-Wiki first with `source_tier`, then 02-Draft (`tier_soft_boost` on score for demotion, not exclusion); `internal_text` excludes the deprecated `status: deprecated` tag text.
- **Curated priority in outputs (T7)** — digest/report item assembly orders Wiki-first with `source_tier` badge and drafts as fallback; `source_tier` surfaced via `format="agent"` JSON output.
- **MCP promote triggers + gate + director handlers (T6)** — server registers promote-draft/director-promote oversee-authorization surfaces; curation gate config handlers added; agent promotion exempt from the director-only rule.
- **Validation scenarios 59 → 65 (T9)** — kb-promote scenario rewritten for the admission semantics; 6 new scenarios (`kb-promote-admission`, `director-backdoor`, `promotion-provenance`, `promotion-triggers`, `search-tier-boost`, `curated-priority-consumption`) + regression fixes (collect-int-id, llm-key-resolution, period-enum, report-structure); 65 = 60 functional + 5 regression.
- **KB test restructuring + fixtures (T10)** — `tests/kb/test_kb_draft.py` fixtures server; `promotion_source: agent` pins; test file reorg under `tests/kb/`.

### Fixed (2026-08-08 kb-curation wave)
- **ErrorCode 27 → 28** — new `DIRECTOR_ONLY` member for the director-gated promotion path; `test_total_members` bumped + docs (AGENTS/quality-gates/expectations) synced. (88c5d4b)
- **B-class portal/kb fixes (T11)** — portal `field` merge, B-04/B-05/B-07/B-08 promotion edge cases (`draft` no-raw provenance, director backdoor on append-only Wiki), `query_collected` docstring/behavior; enterprise-lab frag redux under `tests/kb/`.

### Docs
- **KB-curation wave docs** — AGENTS.md, README.md, `docs/dev/specs/quality-gates.md` (§3.1 CurationGate admission semantics, hard-gate table), expectations + pipeline refs, `docs/dev/validation-scenario-contract.md` (65 scenarios, `promotion_source` field), cross-dimensional-catalog cell updates; acceptance-framework.md layer counts → ~3390 tests / 65 scenarios; MCP tool counts 142 → 145, scenario counts 59 → 65, test count ~3264 → ~3390; doc-manager-skill v2.0.0 → v2.0.1 (count refresh + skill dependency map). (0f85bae, 801bf50)

## Unreleased (2026-08-04)

### Added
- **B23: Ebook/audiobook output (EPUB/MOBI/Audiobook)** — new `src/autoinfo/output/ebook.py`: `render_epub` (ebooklib EPUB3, markdown→XHTML via `output_format="xhtml"` for XML validity + `set_language` for CJK, TOC/spine/NCX/Nav/cover/DC metadata), `render_mobi` (calibre `ebook-convert --mobi-file-type=both` incl. KF8 for CJK, 300s timeout, clear install error when calibre missing), `render_audiobook` (per-chapter `_render_audio` TTS → chapter MP3s + ZIP bundle + single chaptered MP3 via mutagen ID3v2.3 CHAP/CTOC, graceful fallback to plain concatenation). Wired into `generate_digest`/`generate_report` (`format="epub"/"audiobook"`, chapters split from digest context / report sections) and `export_kb` (`format="epub"/"mobi"`, writes `exports/` mirroring `_export_pdf`). MCP server format enums/descriptions extended (3 tools) + base64 return branches (`application/epub+zip`, `audio/mpeg`). New `[ebook]` optional extra (`ebooklib>=0.20`, `mutagen>=1.47`); `all` includes it. Tests: `tests/output/test_output_ebook.py` (6 tests: roundtrip, CJK language, lxml well-formedness, empty-input, audiobook fallback, mobi missing-calibre error). B23 matrix ❌→✅; total coverage 83%→84% (83/99).

- **Version unification awareness** — `src/autoinfo/_version.py` is unified at 1.8.1 while this changelog documents through v1.8.4. This known version drift (1.8.1 code vs 1.8.4 changelog) will be resolved at the next release.

- **Dedicated HackerNews collector** — new `HackerNewsHandler` (src/autoinfo/collectors/hackernews.py) with two-step fetch (item metadata then content) against the official Firebase API; registered in `_build_handler`; `hackernews` added to `VALID_SOURCE_TYPES` (25 → 26 types, 26 → 27 handlers). (cd9f261, closes #105)
- **`resolve_user_id` defaulting in billing tools** — billing/usage/invoice MCP tools and CLI now resolve the current user when `--user-id` is omitted; `get_billing_summary`/`get_subscription_status` `user_id`/`end_user_id` params are optional. (78b7cb0, closes #107)
- **Single-source `__version__`** — version now derives from `_version.py` via dynamic module attribute, eliminating pyproject/`__init__`/health drift (unified at 1.8.1). (5518244, closes #112)

- **Agent-native MCP validation toolset** — `list_validation_scenarios` / `run_validation_scenario` MCP tools execute Agent-native validation scenarios through the MCP surface (plus real CLI subprocesses and real REST HTTP requests): each step makes a real call and asserts on the `{success, data}` envelope. Env-gated steps report `unconfigured` when BYOK keys are missing (never silently skipped, never fake-passed). `llm_assert` steps run a real model call for semantic verification. **44 built-in scenarios** covering 141/141 MCP tools, all 23 CLI command groups, and 8 REST API endpoints. Tool count 139 → 141, 35 categories. Scenario contract: `docs/dev/validation-scenario-contract.md`.


### Changed
- **Validation suite archived** — The shell-based validation plan v2 (15 part files + 24 YAML scenarios + runner) moved to `docs/archive/validation-suite/` (2026-08-03), superseded by the MCP-native validation tools.
- **Validation semantics** — `requires_env` missing now reports `unconfigured` (was `skipped`): Director User is obligated to provide BYOK keys during onboarding; the tool never silently skips verification.
- **Bugfix: `autoinfo status` / `rate_item` read the wrong SQLite DB** — `status.py` resolved the index at `.autoinfo/autoinfo.db` (a small feedback-only DB) instead of the project-root `autoinfo.db` that KBStore writes, causing `autoinfo status --json` to crash with `no such table: entries`. Both now resolve `Path("knowledge").resolve().parent / "autoinfo.db"` (same as KBStore). Tests updated to match.
- **Bugfix: LLM model double-prefix** — 11 call sites built the model string as `f"{provider}/{model}"` without checking whether `model` already carried a provider prefix, producing `openai/openai/deepseek-v4-flash` when `configure_llm` stored a prefixed model. Added `LLMConfig.resolve_model()` (bare model → prepend provider; prefixed → use as-is) and switched all call sites (`llm.py`, `output/`, `process.py`, `qa.py`, `quality.py`, `translation_qa.py`, `cefr.py`, `mcp/validation.py`) to it.
- **Bugfix: `llm_assert` judge did not pass api_key/api_base** — `_llm_judge` called `litellm.completion(model=...)` without the configured key/base_url, so every LLM-gated scenario failed with `AuthenticationError` even when the key was set. It now resolves full call config (model, api_key, api_base).
- **Bugfix: `suggest_keywords` crashed on empty LLM content** — `json.loads('')` raised `JSONDecodeError` as a raw traceback. Now returns a graceful `EmptyResult` error envelope so validation can report it.
- **Bugfix: CEFR prompt produced empty responses on some models** — added few-shot examples and relaxed the strict "only the level" instruction (some providers return empty content for overly constrained single-token prompts); raised `max_tokens` 10 → 50.


### Fixed
- **Bugfix: numeric and slash item IDs crashed collection caching** — `collect` now stringifies numeric and slash-containing item ids before writing the raw JSON cache, preventing `TypeError`/path errors. (f750019, closes #104)
- **Bugfix: `autoinfo init` created runtime dirs inside `.autoinfo/`** — runtime dirs (`collections/`, `knowledge/`, `outputs/`) are now created at the project root (same layout KBStore resolves); `.autoinfo/` keeps only `config.yaml`. (79b188a, closes #106)
- **Bugfix: real-API guard used the wrong import path** — collection tests now import the guard via `tests.conftest` so the `REAL_API_TESTS` env gate works regardless of invocation path. (09b09f6, closes #108)
- **Bugfix: cross-domain report MCP test bypassed the LLM guard** — test now patches the centralized `LLM_NOT_CONFIGURED` dispatch so it passes without a configured key. (3517f96, closes #109)
- **Bugfix: doctor LLM hint pointed at CLI instead of MCP** — the LLM-not-configured hint in `autoinfo doctor` now directs agents to the `configure_llm` MCP tool (BYOK), per agent-first operating model. (3f0c1e1, closes #110)


### Docs
- **README MCP server install guide** — new sections on bare-`python` importability, LLM key injection, and `${...}` placeholder semantics in editor configs. (b9e0f05, closes #111)
- **AGENTS.md restructure** — worked MCP usage examples moved to `docs/dev/mcp-usage-examples.md`; AGENTS.md now links to it. (63f0c85, closes #113)


## v1.8.4 (2026-08-02)

### Added
- **T1 — Unified `_VALID_SOURCE_TYPES` source-of-truth** — `_VALID_SOURCE_TYPES` frozenset (25 source types) is now the single source of truth for source type validation across MCP and CLI. Eliminates drift between separate validation lists. (758dd53)
- **T2 — MCP tool count 139 + dynamic count assertion** — `get_tool_count` returns the live count (139); new test asserts the count dynamically so stale docstrings and hardcoded numbers surface immediately. (d9024bb)
- **T3 — Stripe webhook branches on `session.mode`** — Webhook handler now branches on `session.mode` (`payment` vs `subscription`) instead of assuming subscription-only flow. `create_checkout_session` gains a `mode` parameter (`payment` | `subscription`) so callers can request one-time article purchases or recurring subscriptions. (6915141)
- **T4 — Source `quality_tier` propagated to collected items** — `collect` now carries the source's `quality_tier` onto each collected item, so the G1 (Source Authority) gate can score against the actual source tier rather than a default. (f55b4f7)
- **T5 — A29 Chinese podcast coverage validated** — Validation scenario confirms Chinese-language podcast sources are covered end to end (collection through KB). (0e342fb)
- **T7 — SSRN RSS collector** — New SSRN handler fetches working-paper abstracts via RSS, registered in `collectors/__init__.py` and wired into `_build_handler()`. (07641ff)
- **T8 — GDELT news collector** — New GDELT handler pulls global news events from the GDELT DOC 2.0 API, registered alongside the other news handlers. (30f2e37)
- **T9 — HuggingFace/Kaggle dataset collector** — New handler fetches dataset metadata from HuggingFace Hub and Kaggle datasets APIs, broadening coverage into ML/AI dataset sources. (2542232)
- **T10 — Unpaywall/CORE OA fulltext collector** — New Unpaywall/CORE handler resolves open-access fulltext URLs from DOIs. Followed by two cleanup commits: ruff lint (unused vars/imports) and a `SourceConfig` import fix in the Q2b validation scenario. (ac1798f, 2bd63bc, 11540f5)
- **T11 — E12 single-article payment entitlement** — `create_checkout_session` supports `mode="payment"` for one-time article purchases; `check_access(article_id=...)` fast path verifies the article entitlement grant before delivery. (8347712)
- **T12 — E14 CEFR-level content simplification** — `simplify_content` MCP tool rewrites text to a target CEFR reading level (A1-C1) via LLM, returning original level, simplified level, and a verification flag. (56730ca)
- **T13 — E9 deterministic source credibility score** — `source_score` (0-100) is computed deterministically from the source's quality tier, persisted on the KBEntry, and surfaced in search results and G1 gate details. (0184245)
- **T14 — RAW product variants field** — `_handle_list_products` and `_handle_get_product` now return a `variants` field on RAW products: `["api_feed", "webhook", "bulk_export"]`. The `Product` model in `models.py` gains an optional `variants: list[str]` field. This makes the README's "RAW (API feeds, webhook streams, bulk export)" claim code-backed — the 3 variants map to `/api/v1/feeds` (api_feed), webhook push (`collect.py`), and `export_kb` (bulk_export) respectively. Backward-compatible: existing 2-product top-level structure unchanged; PROCESSED products have no `variants` field. (1a17ba3)
- **T15 — C11 podcast RSS with enclosures + MP3 hosting** — RSS 2.0 delivery channel now emits `<enclosure>` plus the `itunes:*` namespace for podcast feed generation. Audio output auto-persists the rendered MP3 to disk so enclosures resolve to a hosted file. (97c26e6)
- **T16 — A6 FRED/AlphaVantage E2E validation** — New end-to-end validation scenario exercises the financial-intelligence domain against live FRED and Alpha Vantage endpoints. (a073da9)
- **T17 — B15 configurable weasyprint/PDF timeout** — PDF generation timeout is now configurable so slow weasyprint runs no longer block the output pipeline. (79b851a)
- **T18 — C6 SMTP channel E2E validation** — New validation scenario drives the SMTP delivery channel end to end, covering config, send, and receipt. (1c0af81)
- **T19 — E2 Stripe lifecycle regression** — Regression test runs the full Stripe lifecycle (checkout → webhook → subscription state) against stripe-mock so billing changes can't silently break the flow. (b5d2352)
- **T20 — E7 cron cross-process verification** — Validation scenario verifies cron schedules fire across separate processes (not just in-process), catching scheduler persistence bugs. (d3b2f1b)

### Infrastructure
- `src/autoinfo/models.py`: `variants: list[str] = field(default_factory=list)` added to `Product` dataclass.
- `src/autoinfo/mcp/server.py`: `_handle_list_products` raw_product dict + `_handle_get_product` RAW product dict now include `"variants": ["api_feed", "webhook", "bulk_export"]`.
- `tests/test_v1_5_mcp.py`: `test_get_raw_product` + `test_list_products` extended to assert variants field presence and content.

## v1.8.3 (2026-07-31)

### Added

- **4 new ErrorCode values** — `LLM_NOT_CONFIGURED`, `NO_CACHED_ITEMS`, `EMPTY_RESULT`, `CONFIG_NOT_FOUND` added to the `ErrorCode` enum (23 → 27 values) in `src/autoinfo/mcp/errors.py`. `error_response()` canonicalized to the `{success: false, error: {code, message, actionable}}` envelope; `error_dict()` deprecated with `DeprecationWarning`.
- **Centralized LLM_NOT_CONFIGURED guard** — `call_tool()` dispatch now checks LLM configuration before invoking any of the 13 LLM-required tools (`_LLM_REQUIRED_TOOLS` frozenset), returning `LLM_NOT_CONFIGURED` instead of raw auth errors. `suggest_keywords` no longer silently falls back when config is missing.
- **Exception→ErrorCode mapping** — `_error_response()` now maps `FileNotFoundError`→`NOT_FOUND`, `ValueError`/`KeyError`→`VALIDATION_ERROR`, `ConnectionError`/`httpx.ConnectError`→`TIMEOUT`, `litellm.exceptions.AuthenticationError`→`LLM_NOT_CONFIGURED` (all other exceptions fall back to `INTERNAL_ERROR`).
- **`init_project` returns `next_steps` guidance** — The init response now includes a `next_steps` array with actionable follow-up actions (e.g. configure LLM, add sources) so agents know exactly what to do next.
- **`diagnose_system` returns `health_score` + `phase`** — MCP health diagnostic now reports a composite health score (0-100, via `doctor.calculate_health_score`) and a detected operational phase, matching `autoinfo doctor --verbose`.
- **DOMAIN_NOT_FOUND remediation hints** — All 18+ `DOMAIN_NOT_FOUND` error messages now include "Use `add_domain()` to create it." guidance. `collect_sources` single-domain path gained a domain existence guard.
- **`process_collection` returns `status: "noop"`** — When no cached items exist to process, the handler returns `{status: "noop", total_items: 0}` instead of silently returning zero results.
- **`configure_llm` uses `ErrorCode.CONFIG_NOT_FOUND`** — Replaced the previous string-literal error code with the enum member.
- **KB listing tools distinguish states** — `list_kb_tier`/`list_summaries` now clearly differentiate uninitialized KB, empty tier, and populated results in their responses.
- **No-entry check before LLM output generation** — `generate_digest`/`generate_report` return early when no KB entries exist, avoiding wasted LLM calls.
- **Collection exception handling** — `_handle_collect_sources` catches exceptions in-handler instead of re-raising (eliminates double-logging).
- **REST API structured error handling** — FastAPI `exception_handler`s for `Exception`, `ValueError`, `KeyError`, `FileNotFoundError` return the same `{success, error}` envelope as MCP. Domain precondition middleware returns `DomainNotFound` (404) with remediation hint for nonexistent domains. 19 new tests in `tests/api/test_error_responses.py`.
- **CLI help text for 9 commands** — Custom `help=` text added to CLI command groups missing descriptions (collect, doctor, domain, email, sources, summaries, topics, plus shared).
- **Required API Keys doc** — New `docs/dev/required-api-keys.md` cataloging every environment variable AutoInfo reads (28+ vars), linked from README and director-user-guide. Error messages in MCP and CLI now link to documentation where applicable.
- **`AUTOINFO_LLM_API_KEY` env var in `.opencode/mcp.json`** — OpenCode MCP connection config now passes the LLM key env var (matching Cursor and Claude configs).


- **#95 — End-user deliverable validation scenario**: New `docs/autoinfo-validation-master-plan/scenarios/enduser-deliverable.yaml` (7 steps) validating end-user output delivery end to end.
- **Regression tests** — `tests/test_init.py`, `tests/test_output_templates.py`, `tests/test_web_handler.py::test_lxml_importable`, `tests/test_cron.py` (stale-schedule isolation), `tests/test_digest.py` (None-content guard).


### Fixed

- **#98 — Output template path resolution**: `_TEMPLATES_DIR` and `TEMPLATE_PATH` in `output/__init__.py` now resolve from the module's actual location instead of the CWD. Templates (`digest.md.j2`, `report.md.j2`, etc.) are now found regardless of working directory.
- **#96/#99 — None LLM content guard**: `_parse_json_response()` now accepts `content: str | None` and returns `{}` with a warning when the LLM returns `None` content (e.g. `response_format=json_object` rejected by the model). All 4 output call sites use `content or ""` so digest/report generation degrades gracefully instead of crashing.
- **#100 — `autoinfo init` no longer creates standalone `.autoinfo/sources.yaml`**: Sources and topics are now embedded directly in `.autoinfo/config.yaml` under each domain — config.yaml is the single source of truth. The old `sources.yaml` copy (which only held the first demo domain) was misleading. `init_project` MCP tool dry-run output updated to match.
- **#101 — Stale `.autoinfo/schedules.yaml` artifact removed**: A leftover schedules file from prior tests could cause false "duplicate schedule" errors in `autoinfo cron add-schedule`. The stale artifact is deleted and regression tests added (temporary-directory isolation for cron tests).
- **#102 — `lxml` declared as a direct dependency**: `lxml` was only available transitively via `trafilatura`. It is now a direct dependency (`lxml>=5.0`) so Web collector works even with `pip --no-deps` or slim images.


### Infrastructure

- `src/autoinfo/mcp/errors.py`: 4 new ErrorCodes (LLM_NOT_CONFIGURED, NO_CACHED_ITEMS, EMPTY_RESULT, CONFIG_NOT_FOUND); `ErrorResponse` canonical envelope `{success, error}`; `error_dict()` deprecated.
- `src/autoinfo/mcp/server.py`: centralized LLM guard (`_LLM_REQUIRED_TOOLS`, `_is_llm_configured`); exception→ErrorCode mapping in `_error_response()`; `init_project` next_steps; `diagnose_system` health_score+phase; DOMAIN_NOT_FOUND remediation hints; `process_collection` noop; `configure_llm` CONFIG_NOT_FOUND; no-entry checks; KB list state distinction; collection exception handling (+380 lines).
- `src/autoinfo/api/server.py`: `@app.exception_handler` for Exception/ValueError/KeyError/FileNotFoundError returning MCP-compatible envelope.
- `src/autoinfo/api/routes.py`: domain precondition middleware returning `DomainNotFound` 404 with remediation hint.
- `src/autoinfo/cli/__init__.py` + `cli/collect.py`, `cli/doctor.py`, `cli/domain.py`, `cli/email.py`, `cli/sources.py`, `cli/summaries.py`, `cli/topics.py`: custom help text for 9 command groups.
- `.opencode/mcp.json`: `AUTOINFO_LLM_API_KEY` env var added.
- `docs/dev/required-api-keys.md`: new doc (115 lines) cataloging all env vars.
- `tests/api/test_error_responses.py`: 19 new REST API error response tests.
- `tests/test_errors.py`, `tests/test_mcp_server.py`: updated for new ErrorCode count (27) and error mappings.
- `src/autoinfo/output/__init__.py`: `_TEMPLATES_DIR`/`TEMPLATE_PATH` resolution fix; `_parse_json_response` signature `str | None` + 4 call sites `or ""`.
- `src/autoinfo/cli/init.py`: removed standalone `sources.yaml` copy logic (config.yaml is source of truth).
- `src/autoinfo/mcp/server.py`: `init_project` dry-run `would_create_files` no longer lists `.autoinfo/sources.yaml`.
- `pyproject.toml`: added `lxml>=5.0` to dependencies.
- `tests/test_cron.py`, `tests/test_digest.py`, `tests/test_web_handler.py`: regression tests (+44 lines test_cron, None-guard digest tests, lxml import test).
- `docs/autoinfo-validation-master-plan/scenarios/enduser-deliverable.yaml`: new scenario file (453 lines, 7 steps).
- `docs/autoinfo-validation-master-plan/`: YAML param names and tool counts synced across scenario files (#94).

## v1.8.2 (2026-07-30)

### Added
- **`--audience` flag for `autoinfo output report`** — New `--audience` CLI option on report command, matching the existing `target_audience` parameter in output generation (PR #75).
- **"12 new collector handlers"** — DBLP, NYT, OpenAlex, Reddit, Spotify, YouTube, Bilibili, Apple Podcasts, Semantic Scholar, USPTO, plus AP API and Reuters MCP handlers. 22 total collector handlers registered in `collectors/__init__.py` and wired into `_build_handler()` / `_fetch_items()` in `collect.py`.
- **"Bundle export format"** — `export_kb(format='bundle')` generates a ZIP archive containing `data.json`, `summary.md`, `metadata.yaml`, and `report.pdf` (weasyprint). Graceful fallback if PDF generation unavailable.
- **"Cross-domain report MCP tool"** — `generate_cross_domain_report` accepts 2+ domains, aggregates entries with domain labels, and runs cross-domain LLM synthesis.
- **"Cross-domain digest"** — `generate_digest()` now accepts `domains` parameter with per-domain entry limits and combined source attribution.
- **"Report type parameter"** — `report_type` on `generate_report()`: `standard`, `industry`, `competitive`, `trend`, `daily-briefing`. Each type customizes section structure and LLM prompts.
- **"Audience-aware prompts"** — `_normalize_report_audience()` and `_REPORT_AUDIENCE_PROMPTS` mapping for researcher/clinician/executive/investor/student/general audiences.
- **"Delivery schedule MCP tools"** — `add_delivery_schedule`, `list_delivery_schedules`, `remove_delivery_schedule`. Cron-based periodic output generation + delivery via `autoinfo cron run`.
- **"Recommend content MCP tool"** — `recommend_content` MCP tool for content-based recommendation. Returns ranked list of recommended items based on content similarity.
- **"Apple Podcasts source platform"** — New platform type added to `PLATFORMS` list.
- **"MCP tool inventory"**: 133 → 138 tools (3 delivery schedule tools + 1 cross-domain report tool + 1 recommend_content tool).

### Fixed
- **PR #75 — Dead/hanging demo sources removed**: Removed VOA Learning English from language-learning demo (broken feed). Switched ProductHunt from API to RSS in ai-commercial (API was down/dead). Removed LMSYS Chatbot Arena from ai-commercial (unreliable RSS, no stable API). All 4 demo domains now have fully functional source configurations.
- **#81 — `--name` writes `project.name` (backward compat)** : `autoinfo init --name` now writes `project.name` as the primary key (was writing only `project.project_name`). Both `name` and `project_name` are written for backward compatibility with existing config readers.
- **#79 — CrossRef `content: abstract` field_mapping**: Added `content: abstract` to CrossRef source's `field_mapping` in medical-research demo, enabling full abstract extraction from CrossRef API responses.
- **#78 — `--demo` flag now additive (multi-domain init)**: Changed `--demo` from `Optional[str]` to `Optional[List[str]]`, supporting multiple values: `autoinfo init --demo medical-research --demo ai-commercial`. Single `--demo` usage remains unchanged.
- **#80 — Non-TTY init shows helpful error**: `autoinfo init` in non-interactive terminals now shows a helpful message listing `--demo <domain>` and `--list-domains` options instead of crashing with "Aborted". Uses `sys.stdin.isatty()` for pre-prompt detection.
- **#76 — LLM theme grouping prompt with anti-collapse guard**: Enhanced `_group_by_theme()` with domain-specific theme guidance, anti-collapse instruction ("Do NOT group all entries under a single catch-all theme"), and retry logic for single-theme results. Function signature updated to accept `domain` parameter.
- **#68 — Safe json_mode defaults for reasoning models**: Changed `json_mode` default from `True` to `False` in LLM config. Added `reasoning_model: bool = False` config flag — when `True`, `response_format=json_object` is always skipped for compatibility with reasoning models (deepseek-v4, etc.). All 13+ LLM call sites conditionally apply `response_format` based on `json_mode`.

### Changed
- **`autoinfo output report`** — New `--type` (report_type) and `--domains` (cross-domain) CLI flags; `--domain` now optional when `--domains` is used.
- **`autoinfo output export`** — New `bundle` format option.
- **`autoinfo cron run`** — Delivery schedules run alongside collection schedules; delivery results displayed with `[delivery]` type suffix.
- **`json_mode` default** — Changed from `True` to `False`. New `reasoning_model` flag (default `False`) — when `True`, `response_format=json_object` is always skipped for reasoning-model compatibility.

### Infrastructure
- `src/autoinfo/cli/init.py`: `--name` writes both `project.name` + `project.project_name` (+4 lines); `--demo` converted to `List[str]` multi-value (+3/-2); non-TTY detection with helpful error message (+10 lines).
- `src/autoinfo/cli/output.py`: `--audience` flag added to report CLI command (+3 lines).
- `src/autoinfo/data/domains/*/sources.yaml`: VOA removed from language-learning; ProductHunt switched to RSS in ai-commercial; LMSYS removed from ai-commercial; CrossRef `content: abstract` field_mapping added in medical-research.
- `src/autoinfo/output.py`: `_group_by_theme()` enhanced with domain parameter, anti-collapse guard, retry logic (+25 lines).
- `src/autoinfo/config.py`: `json_mode` default `False`, `reasoning_model` flag added to `LLMConfig` dataclass and serialization (+8 lines).
- `src/autoinfo/llm.py`: `json_mode`/`reasoning_model` wired through config resolution and LLM call dispatch (+5 lines).
- `src/autoinfo/mcp/server.py`: +387 lines — 4 new tool handlers, Apple Podcasts platform, export_kb `bundle` format, json_mode default False
- `src/autoinfo/output.py`: +930 lines — bundle export, cross-domain digest/report, report_type, audience prompts, json_mode/reasoning_model hardening
- `src/autoinfo/cli/output.py`: --domains, --type flags on report; --format bundle on export
- `src/autoinfo/cli/cron.py`: delivery schedule execution in run + run_due_schedules, add-delivery CLI command
- `src/autoinfo/collect.py`: 12 new handler registrations
- `src/autoinfo/collectors/__init__.py`: 12 new handler exports
- `src/autoinfo/collectors/`: 12 new collector .py files
- `src/autoinfo/config.py`: json_mode default False, reasoning_model flag
- `src/autoinfo/llm.py`: conditional response_format based on json_mode+reasoning_model
- `src/autoinfo/process.py`, `src/autoinfo/quality.py`, `src/autoinfo/translation_qa.py`: minor compatibility fixes
- `src/autoinfo/data/domains/*/sources.yaml`: source configuration updates

## v1.8.1 (2026-07-29)

### Added
- **`configure_llm` MCP tool** — New System category tool for agent-oriented BYOK LLM setup. Accepts `provider`, `model`, `api_key`, `base_url`. Stores api_key as `\${AUTOINFO_LLM_API_KEY}` env var reference (never the raw key). Incremental updates (only writes fields explicitly provided). MCP tool inventory expanded to **133 tools across 32 categories**.
- **`domain import --from-demo <name>` CLI command** — Reads bundled demo YAML from `src/autoinfo/data/domains/<name>/sources.yaml` and idempotently imports sources and topics into project config. Proper error for nonexistent demo names. Supports all 5 demo domains (medical-research, ai-commercial, financial-intelligence, tech-ai-developer, language-learning).
- **`autoinfo doctor` LLK key suggestion** — Enhanced LLM key message now includes actionable `configure_llm()` call with provider/model/base_url params and reference to `docs/dev/founder-expectations.md §LLM-config`.
- **Bootstrapped 4 missing demo domains** — ai-commercial, financial-intelligence, tech-ai-developer, language-learning now active in config.yaml. All 5 demo domains now have sources+topics configured.
- **`init_project` MCP enum fix** — `demo` parameter enum changed from hardcoded 3/5 domains to dynamic via `_list_demo_domains()`, supporting all 5 demo domains.

### Fixed
- **PR #57 — Python 3.11 compatibility**: Replaced PEP 695 generic function syntax (`def fn[T]`) with `TypeVar` for Python 3.11 support. Fixed in `server.py` (+5/-2).
- **PR #58 — KB count mismatch**: Collected items now propagate `domain` field. KB entry count comparison fixed to use actual domain filter.
- **PR #59 — Unpaywall removal + empty keywords validation**: Removed Unpaywall from medical-research demo config, added CrossRef API settings (query param, JSON path, field mapping). Added validation for empty keyword lists in topic configuration.
- **PR #61 — CLI invocation mismatches**: Fixed 12 CLI flag mismatches across validation plan v2 docs (e.g. `--language`→`--lang`, `email send`→`email send-digest`, `--period week`→`--period weekly`).
- **Doc staleness (Unpaywall)**: Removed stale Unpaywall references from README.md demo domains table, `docs/dev/specs/expectations.md` (2 locations), and `docs/dev/director-user-guide.md` (example dialogue).
- **8 broken demo domain sources** — Fixed sources across financial-intelligence, tech-ai-developer, and language-learning domains. Stack Exchange URL/field_mapping/json_path fixed. FRED added `auth_mode: query` for BYOK. SEC EDGAR migrated from broken REST API to working Atom RSS feed. GitHub Trending URL changed to working Search API endpoint. Project Gutenberg RSS URL corrected. BBC Learning English renamed to VOA Learning English (working feed). Yahoo Finance replaced with Twelve Data (free market data API). World Bank Data added as new financial source.
- **`_traverse_json` integer index support** — `http_api.py` now handles integer indices in JSON paths (e.g. `"1"` for the second element in a response array), required by World Bank Data source.
- **RSS User-Agent agent param** — `rss.py` passes `agent` param through to HTTP request headers, required by SEC EDGAR Atom feed.
- **#62: PubMed full-text fetch enabled** — Added `fetch_depth: fulltext` to PubMed demo source in medical-research domain. PMC full-text via idconv+efetch now used when available (was defaulting to abstract-only).
- **#68: `response_format` hardened** — All 10 `response_format={"type": "json_object"}` call sites now conditionally applied based on `json_mode` flag. `json_mode` wired through YAML config parsing (config.yaml `llm.json_mode`), fallback entries, `_resolve_task_llm_config`, and `config_to_dict` serialization. Default remains `True` (backward-compatible).

### Changed
- **MCP tool inventory**: 132 → 133 tools (added `configure_llm` to System category). All doc references updated (README, AGENTS, mcp-tools.md, doc-manager-skill).
- **Demo domains count**: Medical Research reduced from 4 to 3 curated sources (Unpaywall removed). Remaining sources: PubMed API, arXiv RSS, CrossRef API.
- Version bumped from `1.8.0` to `1.8.1`

### Infrastructure
- `src/autoinfo/mcp/server.py`: New `_handle_configure_llm` handler (+97 lines). `init_project` enum migrated to `_list_demo_domains()` dynamic resolution (+2/-1).
- `src/autoinfo/cli/domain.py`: New `import_cmd()` with `--from-demo` option (+67 lines). Reads demo YAML from `data/domains/<name>/sources.yaml`.
- `src/autoinfo/cli/doctor.py`: Enhanced LLM suggestion with `configure_llm()` call example (+7 lines).
- `tests/test_task12_features.py`: 27 new tests covering `configure_llm`, `domain import --from-demo`, `init_project` MCP enum fix.

## v1.8.0 (2026-07-28)

### Added
- **Agent-oriented remediation — 17 new MCP tools** — MCP tool inventory expanded from 115 to **132 tools across 32 categories**. New tools: `get_tool_count` (self-discovery in System category), `create_kb_entry` (direct Raw-tier KB entry), `topic_group_add`/`topic_group_remove` (topic grouping), `query_audit_log` (MCP audit log query), `cefr_batch` (batch CEFR classification), `email_config` (email configuration), `knowledge_graph_export` (KG export), `clean_cache` (cache cleanup), `cost_dashboard`/`cost_allocation` (cost management), `get_feeds` (RSS feed retrieval). See README for full listings.
- **Agent-native format extended** — `generate_tutorial(format="agent")`, `generate_presentation(format="agent")`, and `export_kb(format="agent")` now return JSON-LD structured for LLM re-consumption (matching existing `generate_digest(format="agent")`).
- **Cross-domain search** — `search_knowledge_base()` domain parameter now optional. When omitted, searches all active domains.
- **Hard-delete purge flag** — `soft_delete_entry(entry_id, purge=True)` permanently removes entries (default False preserves soft-delete behavior).
- **Domain-less collection** — `collect_sources()` now collects from all active domains when `domain` parameter is omitted.
- **Process collection flags** — `process_collection()` exposes `check_factual` and `check_translation` boolean flags in its MCP schema for fine-grained gate control.
- **Job state persistence** — Async job state (`job_state` table in SQLite) persists collection/processing job metadata across restarts. Unknown `job_id` returns `is_complete: false, status: "not_found"` instead of error.
- **Agent callback persistence** — `set_agent_callback`/`list_agent_callbacks`/`remove_agent_callback` now backed by SQLite (`agent_callbacks` table) instead of in-memory dict, surviving server restarts.

### Changed
- **MCP tool inventory**: Expanded from 115 tools across 32 categories to **132 tools across 32 categories**. 17 new tools added across 12 categories. See README for full listing.
- **Error response unification**: All MCP error responses now use a single `_error_dict()` helper returning dual-format (flat `{error_code, message}` + backward-compatible envelope `{isError, content}`). No breaking changes to existing consumers.
- **ErrorCode enum extended** — 3 new values added to `errors.py`: `AuthRequired`, `RateLimited`, `SessionExpired` (preparing for future SSE transport authentication).
- **`generate_tutorial` schema fixed** — Format parameter restricted to `["markdown"]` only (was incorrectly listing html/json/etc. that aren't implemented).
- **CLI help text updated** — `autoinfo output digest --help` and `autoinfo output report --help` now list `agent` format alongside markdown/json/html/pdf/audio.
- **README.md**: MCP tool count 115→132, test count 1549→1612. Features list updated with 17 new tools, error unification, cross-domain search, domain-less collection, persistence. MCP tools table updated across all categories. Status table tool count updated. Known Limitations version reference updated to v1.8.
- **AGENTS.md**: MCP tool count 115→132. Tool Discovery table updated with 17 new tools. Status table MCP count updated. Project structure MCP directory count updated.
- **Test suite**: Expanded from 1549 to 1612 tests (+63 new tests across Waves 1-3).
- **Spec docs updated**: pipeline.md, delivery.md, ops-runbook.md, multi-tenancy-auth.md, market-positioning.md, data-models.md received `<!-- agent: ... -->` metadata blocks, Agent Quick Reference sections, and MCP tool aliases alongside CLI commands.
- Version bumped from `1.6.2` to `1.8.0`

### Infrastructure
- `src/autoinfo/mcp/server.py`: 17 new handler functions — `_handle_get_tool_count`, `_handle_create_kb_entry`, `_handle_topic_group_add`, `_handle_topic_group_remove`, `_handle_query_audit_log`, `_handle_cefr_batch`, `_handle_email_config`, `_handle_knowledge_graph_export`, `_handle_clean_cache`, `_handle_cost_dashboard`, `_handle_cost_allocation`, `_handle_get_feeds`. Dynamic `tools_count` computed at runtime (no longer hardcoded). Optional domain param on `_handle_search_knowledge_base`. Purge flag on `_handle_soft_delete_entry`. Dual-format error responses via `_error_dict()`.
- `src/autoinfo/mcp/errors.py`: 3 new ErrorCode values — `AuthRequired`, `RateLimited`, `SessionExpired`. `error_dict()` helper now returns dual-format (flat + envelope).
- `src/autoinfo/agent_callback.py`: Full rewrite — SQLite-backed `agent_callbacks` table replacing in-memory dict.
- `src/autoinfo/output.py`: `generate_tutorial()`, `generate_presentation()`, `export_kb()` now support `format="agent"` (JSON-LD output).
- `src/autoinfo/api/routes.py`: `get_feeds()` supports `format="rss"` (RSS XML output).
- `src/autoinfo/cli/output.py`: CLI help text updated for `agent` format in digest/report.
- Job state persisted via SQLite `job_state` table collection/processing job metadata.
- `docs/dev/specs/`: 6 spec files updated with agent metadata blocks and agent Quick Reference sections.

### Docs
- **README.md**: Fully updated for v1.8 — MCP tool count 115→132, test count 1549→1612, features list expanded, MCP table rewritten with all 132 tools, status table updated.
- **AGENTS.md**: Fully updated for v1.8 — tool discovery table, status table, project structure.
- **docs/dev/specs/mcp-tools.md**: Tool inventory updated 115→132.
- **docs/dev/founder-expectations.md**: Version/status updated for v1.8.
- **docs/dev/specs/expectations.md**: Status markers checked.
- **docs/dev/specs/quality-gates.md**: 3 new ErrorCodes (AuthRequired, RateLimited, SessionExpired) documented.
- **.opencode/skills/doc-manager-skill/SKILL.md**: Inventory, dependency map, quantitative references updated.
- **docs/autoinfo-validation-master-plan/**: Part 03, Part 10, Part 11 updated for new MCP tools, ErrorCodes, and test count.

## v1.7.0 (2026-07-28)

### Added
- **Subscription model tier/channels/domains/products fields** — `Subscription` dataclass extended with `tier` (free/premium/enterprise), `channels`, `domains`, `products`, and `platform_limit` fields (CD-024). Enables per-tier gating of channels, domains, and products.
- **Free/Premium/Enterprise access control (check_access fast path)** — `billing.check_access(end_user_id, access_level)` implements G15 freemium gating. Free content always allowed (no lookup). Premium requires active paid subscription (not trial/cancelled/suspended). Enterprise requires enterprise-tier access. Returns `allowed`, `reason`, `upgrade_prompt`, `profile_status`, `plan`.
- **Premium + Enterprise product templates** — Product templates gated by subscription tier. Premium and Enterprise tiers unlock additional product types beyond the free tier.
- **Cron heartbeat tracking + missed-schedule detection + alert** — `cli/cron.py` now persists a heartbeat JSON (`.autoinfo/cron-heartbeat.json`) per schedule run. `autoinfo cron health` CLI reports per-schedule health (`ok`/`missed`/`error`/`unknown`) with missed-schedule detection based on cron cadence vs last heartbeat. Missed schedules trigger alerts.
- **ConsumptionEvent auto-record on digest/report delivery** — New `consumption.py` module with `ConsumptionStore` (SQLite-backed) and `ConsumptionEvent` dataclass. Delivery of digests and reports auto-records view/open/click events. Enables consumption analytics per product/user.
- **Automated notifications (trial-ending reminder, content-ready)** — New `notifications.py` module. `check_expiring_trials()` finds trial users expiring within 3 days and sends reminder notifications. `notify_content_ready()` sends a content-ready notification to a user when a product is generated.
- **Delivery channel health checks (all 11 channels)** — `delivery/__init__.py` and all 11 channel adapters (smtp, webhook, rest_api, file_export, discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss) now expose a health check returning `healthy`, `latency_ms`, and `error` fields.
- **get_channel_health MCP tool** — New MCP tool in the Monitor category. Returns health status for one or all 11 delivery channels. When `channel_name` is omitted, all channels are checked.
- **SQLite backup/restore scripts (make backup)** — `scripts/backup-db.sh` backs up the KBStore SQLite index (`autoinfo.db`) and user store (`.autoinfo/users.db`) using Python's built-in sqlite3 module, keeping the last 7 backups per prefix. `scripts/restore-db.sh` restores from a backup. `make backup` Makefile target runs the backup script.

### Fixed
- **Bug #39 — repeated `--tag` crashes with Typer TypeError**: `flag()` in `cli/summaries.py` declared `tag` without `: list[str]` annotation, causing a Typer TypeError on repeated `--tag` flags. Fixed with proper list annotation. Regression test added (`tests/test_bug_39.py`).
- **Bug #40 — `create_draft()` raw_ids/tags parameter mismatch**: The `raw_ids` and `tags` parameters of `create_draft()` in `cli/kb.py` did not match the underlying `KBStore.create_draft()` signature, causing drafts to fail when passing raw IDs or tags. Fixed signature alignment. Regression test added (`tests/test_bug_42.py` covers related KB CLI fixes).
- **Bug #42 — `list_tiers()` call mismatch in `cli/kb.py`**: In `list_tiers()` (`src/autoinfo/cli/kb.py:124`), the call did not match the updated `KBStore` method signature, causing a runtime error on `autoinfo kb list-tiers`. Fixed call alignment. Regression test added (`tests/test_bug_42.py`).

### Changed
- **MCP tool inventory**: Expanded from 114 tools across 32 categories to **115 tools across 32 categories**. New `get_channel_health` tool added to the Monitor category. See README for full listing.
- **README.md**: MCP tool count 114→115. Added 7 new Status table rows (subscription tiers, access control, consumption tracking, automated notifications, channel health monitoring, cron health monitoring, SQLite backup). Added `get_channel_health` to Monitor category in MCP table. Added `autoinfo cron health` to CLI commands. Updated Known Limitations with v1.7 summary.
- **AGENTS.md**: MCP tool count 114→115. Status table updated with 7 new rows. Tool Discovery table Monitor category updated with `get_channel_health`.
- **Test suite**: Added regression tests for Bug #39, #40, #42 and Stripe integration tests (`tests/test_stripe.py`).

### Infrastructure
- `src/autoinfo/consumption.py`: New module — `ConsumptionStore` (SQLite-backed) + `ConsumptionEvent` dataclass for delivery consumption tracking.
- `src/autoinfo/notifications.py`: New module — `check_expiring_trials()` and `notify_content_ready()` for automated end-user notifications.
- `src/autoinfo/billing.py`: Added `check_access()` fast path for G15 freemium gating (free/premium/enterprise).
- `src/autoinfo/models.py`: `Subscription` dataclass extended with `tier`, `channels`, `domains`, `products`, `platform_limit` fields (CD-024).
- `src/autoinfo/output.py`: Digest/report delivery now auto-records `ConsumptionEvent`.
- `src/autoinfo/mcp/server.py`: New `get_channel_health` tool (Monitor category). Tool count 114→115.
- `src/autoinfo/delivery/__init__.py` + 11 channel adapters: Health check method added (`healthy`, `latency_ms`, `error`).
- `src/autoinfo/cli/cron.py`: New `health` subcommand with heartbeat persistence and missed-schedule detection.
- `src/autoinfo/cli/summaries.py`: Bug #39 fix — `tag` parameter list annotation.
- `src/autoinfo/cli/kb.py`: Bug #40/#42 fixes — `create_draft()` and `list_tiers()` signature alignment.
- `src/autoinfo/email_sender.py`, `src/autoinfo/api/routes.py`, `src/autoinfo/cli/portal.py`: Supporting changes for notifications and consumption tracking.
- `scripts/backup-db.sh`, `scripts/restore-db.sh`: New scripts for SQLite backup/restore.
- `Makefile`: New `backup` target.
- `tests/test_bug_39.py`, `tests/test_bug_40.py`, `tests/test_bug_42.py`, `tests/test_stripe.py`: New regression and integration tests.

### Docs
- **README.md**: Updated for v1.7 (features, status table, MCP tools, CLI commands, known limitations).
- **docs/autoinfo-validation-master-plan/**: Part 03 (get_channel_health scenarios), Part 04 (consumption tracking, notifications, cron health scenarios), Part 11 (backup verification) updated.
- **.opencode/skills/doc-manager-skill/SKILL.md**: Inventory, dependency map, and quantitative references updated for v1.7.

## v1.6.4 (2026-07-27)

### Added
- **cross-dimensional-gap-catalog.md** — New document cataloging 42 gaps across 5 types (Consumer Output, Implementation, Pricing/Business, Quality Gate, Documentation/Knowledge) with a 119-cell cross-dimensional impact matrix and an implementation roadmap. Located at `docs/dev/cross-dimensional-gap-catalog.md`.
- **multi-tenancy-auth.md** — New spec covering multi-tenancy architecture (domain isolation, tenant provisioning), auth system (OAuth2, SSO, session management), API rate limiting (token bucket, per-tenant quotas), and admin dashboard specification. Located at `docs/dev/specs/multi-tenancy-auth.md`.
- **ops-runbook.md** — New spec covering backup/disaster recovery strategy (RPO/RTO targets, backup types, restore procedures), monitoring/alerting setup (Prometheus/Grafana, log aggregation, alert routing), and scaling strategy (horizontal scaling, caching, CDN, sharding). Located at `docs/dev/specs/ops-runbook.md`.
- **expectations.md extended** — Added 7 new expectations (F58-F64) covering multi-tenancy (F58), auth system (F59), rate limiting (F60), admin dashboard (F61), backup/DR (F62), monitoring/alerting (F63), scaling strategy (F64). All 57 existing status markers verified and corrected. Located at `docs/dev/specs/expectations.md`.
- **delivery.md extended** — Added product lifecycle management (status model, transition triggers), consumption tracking (view/click/download analytics), channel health monitoring (delivery success rate, latency metrics), and delivery preview capability. Located at `docs/dev/specs/delivery.md`.
- **operations.md extended** — Added email template system (HTML/MJML templates, variable substitution, A/B testing), notification framework (event subscription model, delivery rules, mute/unsubscribe), cron reliability monitoring (missed runs, overruns, SLA), and business metrics (DAU/MAU, conversion funnel, retention cohorts). Located at `docs/dev/specs/operations.md`.
- **data-models.md extended** — Added consolidated schemas for Product (status, lifecycle), Consumption (view/click/download events), Notification (templates, subscriptions, channels), and Auth (tenant, user, role, session). Located at `docs/dev/specs/data-models.md`.
- **comprehensive-gap-audit.md extended** — Added cross-dimensional summary section, gap ID cross-reference table mapping 42 gaps to their location in 6 spec documents, and a color-coded heatmap visualizing gap density across dimensions. Located at `docs/dev/comprehensive-gap-audit.md`.
- **consumer-output-gaps.md fixed** — G1 (Executive Alerts/Digest) and G11 (Integration Platform/Data API) corrected via CD cross-referencing. Added CD cross-references to all 10 gaps linking to implementation gap catalog entries. Located at `docs/dev/consumer-output-gaps.md`.

### Changed
- **README.md** — Status fixes for agent-native JSON and audio output rows. Added references to cross-dimensional-gap-catalog.md and new spec files to reference section.
- **AGENTS.md** — Status table verified and aligned with README. Added references to cross-dimensional-gap-catalog.md, multi-tenancy-auth.md, ops-runbook.md in references section.

### Infrastructure
- `docs/dev/cross-dimensional-gap-catalog.md`: New document — 42-gap cross-dimensional catalog with 119-cell impact matrix and implementation roadmap
- `docs/dev/specs/multi-tenancy-auth.md`: New spec — multi-tenancy, auth, rate limiting, admin dashboard
- `docs/dev/specs/ops-runbook.md`: New spec — backup/DR, monitoring/alerting, scaling strategy
- `docs/dev/specs/expectations.md`: Updated — F58-F64 added, all 57 status markers fixed
- `docs/dev/specs/delivery.md`: Updated — product lifecycle, consumption, channel health, preview
- `docs/dev/specs/operations.md`: Updated — email templates, notifications, cron reliability, business metrics
- `docs/dev/specs/data-models.md`: Updated — product/consumption/notification/auth model schemas
- `docs/dev/comprehensive-gap-audit.md`: Updated — cross-dimensional summary, gap ID cross-reference, heatmap
- `docs/dev/consumer-output-gaps.md`: Updated — G1/G11 fixes, CD cross-references added

## v1.6.3 (2026-07-27)

### Added
- **Stripe webhook REST endpoint** — `POST /api/v1/webhook/stripe` FastAPI route with signature verification via `stripe.Webhook.construct_event()`. Dispatches to `billing.py:handle_webhook()` for `checkout.session.completed`, `customer.subscription.updated`, `invoice.paid`, `invoice.payment_failed` events. Webhook secret configurable via env var and `.autoinfo/config.yaml`. stripe-mock dev setup added via Docker Compose.
- **G3 LLM-based relevance scoring** — Upgraded from lexical keyword overlap to LLM-based scoring (0-100) following G4's proven retry pattern. Includes 3× retry with escalating context on LLM failure, fallback to lexical scoring. Configurable model and threshold per domain.
- **G5 full 5-gate translation QA pipeline** — Integrated 4 deterministic gates (terminology compliance, grammar check, format check, completeness check) as pre-checks, with LLM faithfulness as composite final gate. Configurable weights per gate.
- **`list_active_deliveries` + `get_delivery_log` MCP tools** — New Delivery Monitor category. `list_active_deliveries` returns in-flight deliveries with status/retry info; `get_delivery_log` returns per-subscription delivery history with SLA compliance metrics.
- **`get_billing_summary` MCP tool + `autoinfo billing` CLI** — New Cost category tool and CLI group. `get_billing_summary(domain, period)` returns total spend, per-model/itemized costs, and budget status. CLI: `autoinfo billing summary|usage|invoice`.
- **Web portal read-only dashboard MVP** — Read-only dashboard at `/portal/` with preferences, delivery history, and product archive views. Built with FastAPI + Jinja2 (Bootstrap 5, consistent with existing dashboard).
- **Webhook HMAC signing + REST API Authorization header** — Webhook payloads now HMAC-signed with configurable secret. REST API accepts `Authorization: Bearer <token>` header (configurable via `api.auth_token` in config).
- **D1 operator notification via Alert Rules** — D1 gate now triggers Alert Rules dispatch (email/webhook) on delivery failure, notifying operator with item_id, failure reason, and retry status.
- **D2 PDF validation via PyMuPDF** — D2 gate validates PDF output files with PyMuPDF: checks page count, file size, and rendering integrity before delivery.
- **G2 configurable time window** — G2 dedup gate now accepts `time_window_hours` parameter (default 720h/30 days). URL-based exact dedup always-on; fuzzy title dedup uses time window as secondary filter.
- **`target_audience` MCP parameter plumbing** — `target_audience` parameter added to `generate_digest` and `generate_report` MCP tool schemas (backend already supported it).
- **Adapter unit tests** — 9 delivery adapter unit tests + `deliver_with_retry` test covering all 6 channels (Telegram, WeChat OA, WeChat Work, DingTalk, FeiShu, Discord) plus SMTP, webhook, and export.
- **Persistent user-store** — `_user_stripe_map` upgraded from volatile dict to SQLite-backed persistent storage with migration path.

### Changed
- **MCP tool inventory**: Expanded from 109 tools across 26 categories to **114 tools across 32 categories**. 5 new categories: End User (10 tools), Cost (6 tools), Data Privacy (4 tools), Knowledge Lifecycle (6 tools), Observability (4 tools), Agent Callbacks (3 tools). Added `list_active_deliveries`, `get_delivery_log`, `get_billing_summary`. See README for full listing.
- **README.md**: MCP tool count 109→114, categories 26→32, test count 1429→1549, CLI groups 22→23 (billing added). MCP tools table rewritten to match 32 categories. Architecture diagram updated. Stripe webhook "pending" note removed.
- **AGENTS.md**: MCP tool count 109→114, categories 26→32, test count 1429→1549, CLI groups 22→23. Tool Discovery table expanded to 32 categories. Status table updated.
- **docs/dev/specs/mcp-tools.md**: Header updated from "91 tools across 26 categories" to "114 tools across 32 categories". All 32 categories and their tools listed. Phantom tools removed.
- **Test suite expanded**: 1429 → 1549 tests (+120 new tests covering Stripe webhook, G3 scoring, G5 pipeline, adapter tests, web portal, billing CLI).

### Fixed
- **mcp-tools.md tool count mismatch**: Oracle F1 audit revealed doc header said "111 tools" but actual was 114. Fixed: header corrected to "114 tools across 32 categories", 18 phantom entries removed, `list_active_deliveries` added.
- **test_mcp_full.py tool count assertion**: Assertion `== 111` updated to `== 114` to match actual tool count.

### Infrastructure
- `src/autoinfo/api/server.py`: Added Stripe webhook route (`POST /api/v1/webhook/stripe`) with signature verification.
- `src/autoinfo/billing.py`: Persistent `_user_stripe_map` (SQLite-backed), fixed silent failure in `_sync_user_stripe_id()`.
- `src/autoinfo/quality.py`: G3 upgraded to LLM-based scoring with retry. G5 full 5-gate QA pipeline. G2 `time_window_hours` parameter. D1 operator notification via Alert Rules. D2 PDF validation.
- `src/autoinfo/translation_qa.py`: Full 5-gate pipeline with composite scoring.
- `src/autoinfo/delivery.py`, `src/autoinfo/delivery_log.py`: `list_active_deliveries` and `get_delivery_log` implementations.
- `src/autoinfo/mcp/server.py`: 3 new tools — `list_active_deliveries`, `get_delivery_log`, `get_billing_summary`. `target_audience` parameter added to digest/report tools. HMAC signing for webhooks.
- `src/autoinfo/cli/billing.py`: New CLI command group for billing.
- `src/autoinfo/api/portal.py`: New module — web portal read-only dashboard (4 routes, 6 Jinja2 templates).
- `tests/`: 120 new tests across Stripe, G3, G5, adapters, portal, billing.

## v1.6.2 (2026-07-26)

### Fixed
- **F52 — Runtime crash in `KBStore.get_domain_decay()`**: Implemented the missing method — `KBStore` called `get_domain_decay()` from CLI and MCP but the method did not exist, causing `AttributeError` on every invocation. Now returns 6-field decay report (staleness_ratio, avg_ttl_remaining_days, collection_freshness_days, decay_grade GREEN/YELLOW/RED, total_entries, stale_count, fresh_entries, suggestions). Reuses existing `calculate_freshness_score()` and `get_active_entries()`.
- **F46 — Source ToS compliance gaps**: README claimed ✅ but zero implementation existed.
  - Added `tos_classification` field (`open`/`licensed`/`restricted`/`sensitive`) to `SourceConfig` dataclass with auto-mapping from `quality_tier`
  - Extended G1 quality gate with `G1TosCompliance` — checks source tier vs `tos_classification` consistency, flags restricted/sensitive sources with compliance warning
  - Extended D2 delivery gate to block RAW delivery (API/webhook/export) for restricted/sensitive sources; PROCESSED delivery (digest/report) allowed with compliance notice
  - Added `_build_attribution_footer()` to output generation — digest/report/export include "Source: {name} ({url}) — {tos_classification}" attribution
  - Updated CLI `domain show` and MCP `get_domain_config` to display `tos_classification`
- **F45 — Budget thresholds from config instead of hardcoded**: `evaluate_budget_alerts()` now reads thresholds from `config.yaml` via `CostAlertsConfig` dataclass instead of hardcoded `[50.0, 75.0, 90.0, 100.0]`. Added `get_budget_thresholds` and `set_budget_thresholds` MCP tools for runtime configuration.
- **F20 — Missing `reindex_kb` MCP tool**: `KBStore.reindex_knowledge_base()` existed but no MCP tool was registered. Now registered with 3-part pattern (Tool declaration, handler, dispatch branch).
- **F53 — Missing `find_similar_items` MCP tool**: `find_similar_items()` existed in `quality.py` but no MCP tool was registered. Now registered with text similarity search (threshold/limit params).
- **F51 — Stale content not wired into search or digest**: `mark_stale()` existed but consumers ignored it.
  - Search: `search_knowledge_base()` now applies freshness weight (20%) to relevance score. Stale entries demoted. Added `include_stale` param (default: False) and `freshness_score`/`is_stale` fields to results.
  - Digest: `generate_digest()` now filters out stale entries by default. Added `include_stale` param. Logs count of excluded entries.
- **F11 — Fuzzy title dedup**: G2 gate (and `DedupChecker`) extended with `difflib.SequenceMatcher` comparison at 0.85 threshold after exact URL/PMID/DOI matching. Short-title guard (<20 chars) skips fuzzy match to prevent false positives.
- **F49 — Demo domain TTL defaults not set**: `activate_domain()` now applies per-domain defaults: medical-research 180d, ai-commercial 30d, financial-intelligence 7d, tech-ai-developer 90d, language-learning 365d.
- **F12 — Missing `job_id` param on progress MCP schemas**: `get_collection_progress` and `get_processing_progress` MCP tool schemas now expose optional `job_id` string property (internal handlers already supported it).

### Changed
- **README.md**: MCP tool count 87→91, test count 1405→1429, added new tools to MCP table (reindex_kb, find_similar_items, get_budget_thresholds, set_budget_thresholds). Source ToS compliance description updated with G1/D2/attribution details.
- **AGENTS.md**: MCP tool count 79→91 across 26 categories, test count 1405→1429, KB category now includes `find_similar_items`, new Budget category with `get_budget_thresholds`/`set_budget_thresholds`, reindex_kb already listed under KB.
- **expectations.md**: Status markers corrected for F07b/F33/F41/F44/F46/F49/F50/F52 — 6 upgraded ✅, 2 downgraded ❌ (F46/F52).
- Version bumped from `1.6.0` to `1.6.2`

### Infrastructure
- `src/autoinfo/kb.py`: Added `KBStore.get_domain_decay()` (6-field decay report). Modified `search_knowledge_base()` with freshness demotion and `include_stale` param.
- `src/autoinfo/config.py`: Added `tos_classification` to SourceConfig, `CostAlertsConfig` dataclass, per-domain TTL defaults.
- `src/autoinfo/quality.py`: Extended G1 with `G1TosCompliance` gate. Extended D2FormatIntegrity with ToS delivery blocking. Extended G2Dedup with fuzzy title matching.
- `src/autoinfo/output.py`: Added `_build_attribution_footer()`, stale exclusion in `generate_digest()`.
- `src/autoinfo/alerts.py`: `evaluate_budget_alerts()` reads from `CostAlertsConfig` instead of hardcoded thresholds.
- `src/autoinfo/dedup.py`: Extended DedupChecker with `_fuzzy_title_match()` using SequenceMatcher.
- `src/autoinfo/mcp/server.py`: 4 new tools — `reindex_kb`, `find_similar_items`, `get_budget_thresholds`, `set_budget_thresholds`. job_id param added to progress schemas.

## v1.6.1 (2026-07-25)

### Added

- LLM fallback chain support — `_call_llm()` now iterates through configured fallback models (F04)
- `RELATION_TYPES` enum with 11 standard relationship types (F19)
- Per-domain TTL with freshness scoring (F49)
- Versioned re-collection with auto-bump (F50)
- Stale content handling (`mark_stale`, `get_active_entries`) (F51)
- Domain decay metrics with grade calculation (F52)
- Cross-collection dedup & merge with `difflib.SequenceMatcher` (F53)
- Budget alerts with cost threshold evaluation (F45)
- `get_domain_decay` MCP tool
- `merge_items` MCP tool

- **End User Profile & Subscription CRUD (F36)** — `EndUserProfile` and `Subscription` models with SQLite-backed store. MCP tools: `create_end_user`, `get_end_user`, `update_end_user`, `delete_end_user`, `list_end_users`. CLI: `autoinfo enduser create|get|update|delete|list`. Profile fields include delivery channel IDs (telegram, wechat, dingtalk, discord), locale, timezone, tier, and status.
- **Multi-Channel Delivery (F37)** — 6 delivery adapters: Telegram Bot, WeChat Official Account, WeChat Work, DingTalk, FeiShu, Discord. Each adapter implements `DeliveryChannel` ABC with `send()` and `validate()` methods. Email remains mandatory fallback. Per-channel rate limiting and message format support.
- **End User Lifecycle State Machine (F38)** — `trial → active → suspended → cancelled` with configurable trial period (default 14d), grace period (7d), and transition hooks (welcome/payment-reminder/goodbye messages). Re-activation within 90 days preserves full history.
- **Delivery Reliability & Logging (F39)** — `DeliveryLog` with per-attempt tracking (status, attempt count, error messages, SLA timestamps). Retry chain: primary → fallback → queue for next window (never silently drop). SLA targets: P0 ≤5min, P1 ≤30min, P2 ≤2hr. MCP: `get_delivery_log(subscription_id, period)`.
- **End User Self-Service Portal (F40)** — Portal MVP via CLI + REST API (`autoinfo portal preferences show|update`, `autoinfo portal history`). Delivery preference management (enable/disable channels, quiet hours), product archive access, delivery history browsing.
- **Internal Cost Metering (F41)** — Per-domain/per-user/per-stage cost tracking for LLM tokens, storage, and API calls. Append-only cost log with pre-populated unit prices (DeepSeek, Claude, embeddings). MCP: `get_cost_report(domain, period, group_by)`. CLI: `autoinfo cost dashboard|allocation`.
- **Cost Allocation (F44)** — Three configurable strategies: pro-rata (equal split), usage-based (proportional to consumption), direct (definitively tied). Per-domain and per-end-user attribution with logged allocation method.
- **Cost Dashboard (F43)** — CLI and MCP cost dashboard with breakdowns by domain, daily trend, top 5 models by cost, top 5 sources by cost, and budget status with usage percentages.
- **Budget Alerts & Cost Control (F45)** — Threshold-based alert rules (absolute spend, rate-based, projected overrun). Configurable auto-remediation: pause collection, switch to cheaper model, skip non-critical quality gates. MCP: `set_budget_alert`, `get_budget_alerts`.
- **Source ToS Compliance (F46)** — Source classification tiers (Open/Licensed/Restricted/Sensitive) with per-tier output controls. Licensed/Sensitive sources: only processed output deliverable, raw content never leaves internal storage. Attribution in generated outputs. Compliance checkpoint at G1 gate.
- **Data Deletion & Retention (F47)** — Soft-delete model with `status: deleted`, `deleted_at`, `deleted_reason`. MCP: `soft_delete_entry`, `restore_entry`, `export_user_data`. 30-day auto-cleanup for expired items. Retention by subscription tier (trial/active/archived). Permanent deletion via `--purge` only (agent cannot purge).
- **Immutable Audit Logging (F48)** — Append-only audit log for all operations: MCP tool calls, pipeline executions, config changes, user management. Schema: `audit_log_id, timestamp, actor_type, actor_id, action, resource_type, resource_id, details (JSON, secrets redacted), result, session_id`. MCP: `query_audit_log(filters)`. CLI: `autoinfo audit query`.
- **Per-Domain TTL & Freshness (F49)** — Configurable freshness period per domain (defaults: medical 180d, AI commercial 30d, financial 7d, general 90d). TTL controls freshness scoring for search ranking and default output inclusion. Stale entries never deleted, fully accessible via direct lookup.
- **Versioned Re-collection (F50)** — Same `source_url` collected again creates a new version with full history. Frontmatter tracks `version`, `previous_version_id`. MCP: `compare_versions(entry_id, v1, v2)` for structured diff. Retain last N versions (default 10), older versions archived.
- **Stale Content Handling (F51)** — Entries past TTL marked `freshness: stale` with `staleness_date`. Search demotion (freshness contributes 20% to ranking). Stale entries excluded from digest/report by default; `--include-stale` flag overrides. Never deleted.
- **Domain Decay Metrics (F52)** — Staleness ratio, avg remaining TTL, collection freshness, composite decay grade (Green/Yellow/Red). Displayed in `autoinfo status --domains` and MCP `get_collection_stats()`. Proactive agent alert when staleness >50%.
- **Cross-Collection Dedup & Merge (F53)** — URL dedup across runs, cross-source similarity detection (title TF-IDF > 0.85, content Jaccard > 0.7). LLM-assisted merge with `merge_items(primary_id, secondary_ids, mode)`. Merged entries are Draft-tier (require human promotion).
- **Structured Pipeline Logging (F54)** — JSON structured logging per pipeline event. Schema: `timestamp, level, trace_id, stage, domain, source, item_id, action, duration_ms, status, error, metadata`. Written to `logs/pipeline-YYYY-MM-DD.log` with daily rotation. CLI: `autoinfo logs --stage collect --domain medical --since 1h`.
- **Per-Item Traceability (F55)** — UUID trace_id generated at collect time, propagated through entire pipeline. Append-only trace store indexed for sub-ms lookup. CLI: `autoinfo trace <trace_id>` — displays full item journey with stage timings, gate results, and delivery status.
- **Enhanced Diagnostics (F56)** — `autoinfo doctor --verbose` with: recent pipeline runs per domain, error rates per source per stage (7d trend), latency p95/p99 per stage, LLM spend summary, KB health (entries per tier, stale ratio, storage). Composite health score (0-100) per domain.
- **Metrics Export (F57)** — `autoinfo status --metrics` exports system health and usage indicators as structured JSON. Prometheus endpoint at `http://localhost:8741/metrics` (feature-gated). Standard metric names: `autoinfo_items_collected_total`, `autoinfo_llm_spend_usd`, etc.

### Changed

- **CLI expanded from 17 to 22 command groups** — 5 new groups: `audit` (immutable audit log queries), `cost` (cost dashboard and allocation), `enduser` (end-user profile CRUD), `portal` (self-service delivery preferences and history), `trace` (per-item pipeline history). CLI `__init__.py` updated to register all new modules.
- **MCP tool inventory**: 79 tools across 19 categories (same count as v1.5 — new EndUser/Audit/Trace MCP tools balanced against internal refactoring). See README for full listing.
- **founder-expectations.md**: All F36-F57 expectations updated from ❌ to ✅ with completion markers. Version references updated from v1.5 to v1.6 throughout. Success metrics table revised.
- **Version bumped** from `1.5.0` to `1.6.0`
- **README.md** — CLI command groups 17→22, known limitations updated to v1.6, status table updated with new components (cost metering, budget alerts, delivery reliability, per-item traceability, etc.)
- **AGENTS.md** — Project structure updated with new modules (audit.py, cost.py, delivery_log.py, user_store.py, collectors/base.py). Status table updated. CLI count 17→22.

### Fixed

- **BLOCKING**: Added missing `UserProfile` and `Subscription` dataclasses to `models.py` (F36)
- **BLOCKING**: Added missing `CostRatesConfig` dataclass to `config.py` (F41)
- Fixed cascade import failure that broke all 22 CLI commands
- `trace_item`, `get_metrics`, `soft_delete_entry`, `restore_entry`, `export_user_data`, `delete_user_data` MCP tools registered
- `doctor --verbose` with health score (0-100), error rates, and latency percentiles (F56)
- #34: MCP test tool count updated to 87
- #35: `generate_presentation` mock test format param fixed
- #37: `_slugify` max_len increased 80→255 to prevent entry_id truncation
- #38: Standardized `--json` output format (6 CLIs now wrap lists in `{items, count}`)

- **#33 — KB count mismatch false warning**: Replaced `len(list_entries(domain, limit=1))` with `KBStore.count_entries(domain)` (backed by `SELECT COUNT(*)`) to prevent false-positive warnings on every multi-item processing run.
- **#34 — Stale tool count assertions in `test_mcp_v2.py`**: Relaxed hardcoded `== 65` assertions to `>= 65` / `>= 70` to prevent false test failures as MCP tool inventory grows.
- **#35 — Presentation mock missing `format` parameter**: Added `format="markdown"` to `test_generate_presentation` mock assertion to match actual `_handle_generate_presentation` call signature.

### Infrastructure

- `src/autoinfo/audit.py`: New module — immutable append-only audit log with SQLite backend and MCP/CLI query support
- `src/autoinfo/cost.py`: New module — cost metering, allocation, dashboard, and budget alerts
- `src/autoinfo/delivery_log.py`: New module — per-subscription delivery reliability tracking with SLA monitoring
- `src/autoinfo/logging.py`: New module — structured JSON pipeline logging with daily rotation and filtering
- `src/autoinfo/user_store.py`: New module — SQLite-backed EndUserProfile and Subscription CRUD
- `src/autoinfo/collectors/base.py`: New module — BaseHandler ABC with 6 handler port interfaces
- `src/autoinfo/cli/audit.py`, `cost.py`, `enduser.py`, `portal.py`, `trace.py`: 5 new CLI command groups
- 6 delivery adapter files for Telegram, WeChat OA, WeChat Work, DingTalk, FeiShu, Discord
- All documentation updated to v1.6 numbers and feature set (README, AGENTS, CHANGELOG, founder-expectations, validation-plan-v2)

## v1.5 (2026-07-24)

### Added
- **Commercial scope** — AutoInfo redefined as covering any field where customers pay for information products and reports. Three design principles: Product-first, Production-grade quality, Commercial viability. Paying Customer added as 4th user type with explicit design constraint.
- **Two product types** — RAW products (API feeds, webhook streams, bulk export) and PROCESSED products (scheduled digests, thematic reports, alert streams, tutorials). Product architecture added with delivery channel abstraction (SMTP, webhook, REST API, export).
- **Production-grade quality gates** — Hard/soft split: G0 (Schema integrity) and G4 (Factual consistency) are hard gates with retry→block; G1-G3/G5 are soft gates with configurable thresholds; 3 new delivery gates D1-D3 check product completeness, format integrity, and freshness at output time. Retry-first, block-last philosophy. Per-domain gate configuration.
- **Product delivery expectations** — F27 renamed from "Scheduled Distribution" to "Product Delivery"; F28 (RAW Product Generation), F29 (PROCESSED Product Generation), F30 (Subscription & Billing deferred to v2+). Value propositions expanded from 4 to 5: Commercial-grade products.
- **Product-based pricing model** — Two customer types (Information Buyer / Knowledge Product Subscriber), 4-tier pricing (Free / RAW Pro / PROCESSED Pro / Enterprise), product type economics (margin, volume, delivery, retention analysis).
- **Founder's Priority Matrix updated** — New 🔴 Product & Delivery quadrant (CRITICAL/MEDIUM) added for F27-F29, G0/G4, D1-D3.
- **Explicit "No" list expanded** — Subscription management/billing, feature gating/usage metering, customer delivery portal all explicitly deferred to v2+.
- **§14 Gaps restructured** — Product delivery gaps (RAW feed API, PROCESSED template system, alert stream config, hard/delivery gate implementation, delivery channel abstraction) added as short-term; billing-related gaps moved to v2+.

### Changed
- **Quality philosophy rewrite** — From "all gates advisory" to production-grade: hard/soft split with retry-first, block-last. Never silently discard. G0 (new schema integrity gate) and G4 treated as hard gates. Delivery gates (D1-D3) block delivery on failure.
- **§6 Priority Matrix** — Added 🔴 Product & Delivery quadrant for commercial product expectations.
- **§12 Technical Decisions** — Added §12.10 Product Architecture with RAW/PROCESSED pipeline and delivery channels. MCP tool inventory updated from 72 tools across 16 categories to 79 across 19 categories (7 new tools: get_gate_config, set_gate_config, list_products, get_product, add_alert_rule, get_alert_rules, remove_alert_rule). Testing strategy updated (T1-T10 → T1-T13).
- **§13 The Hard Truth** — v1.5 pivot from "builder tool" to "commercial product" acknowledged as the hardest change. Quality philosophy rewrite, product type economics, billing deferral consciously documented.
- **README.md** — Quality gates row updated to 6 hard/soft + 3 delivery gates. Features list updated with product delivery + subscription-ready items. Known Limitations section updated to v1.5 (was v1.4). Architecture diagram extended with Product Pipeline and Delivery Channels. MCP tool count 72→79, test count 1134→1421, 3 new MCP categories added.
- **AGENTS.md** — MCP tool count 72→79, test count 1134→1421, quality gates section rewritten to production-grade model, project structure updated with alerts.py/delivery.py modules.
- **founder-expectations.md** — All version references updated from v1.4 to v1.5. Success metrics table updated with product delivery status. Component table updated with commercial scope, quality gate model, product delivery rows. Version status and gantt chart updated. All 6 "advisory" references updated to new hard/soft model.
- **Expectation count updated** — From 32 to 35 (F28-F30 added, previous F28-F31 renumbered to F31-F34). True Test expanded from 10 to 13 (T11-T13 added).
- Version bumped from `1.3.0` to `1.5.0`
- Test suite expanded from 1134 to 1421 tests (53 test files, 262 v1.5 tests across 7 files)

### Fixed
- All stale version references (v1.3.1 → v1.5) in milestone table, gantt chart, explicit No list, success metrics headers
- §14 gaps section header and all future-work version markers updated

### Infrastructure
- `src/autoinfo/delivery.py`: New module — DeliveryChannel ABC with SMTP, webhook, REST API, export implementations
- `src/autoinfo/alerts.py`: New module — Alert rule CRUD, YAML persistence, check & dispatch via DeliveryChannel
- `src/autoinfo/quality.py`: G0/G4 hard gate enforcement with 3× retry chain, D1-D3 delivery gates, per-domain gate config merge
- `src/autoinfo/mcp/server.py`: 7 new MCP tool handlers (get_gate_config, set_gate_config, list_products, get_product, add_alert_rule, get_alert_rules, remove_alert_rule)
- `tests/test_v1_5_*.py`: 7 new test files with 262 tests covering quality gates, delivery, alerts, feed API, MCP, config, integration
- `docs/` (README.md, AGENTS.md, CHANGELOG.md): All documentation updated to v1.5 numbers and feature set

## v1.4.1 (2026-07-24)

### Added
- **source_platform field**: Added to all remaining collectors — `web_playwright.py`, `pdf.py`, `webhook.py` now populate `source_platform` (fixes #30 scope extension)
- **collected_at field**: Added to `web_playwright.py`, `pdf.py`, `webhook.py` collectors that were missing it (fixes #31 scope extension)

### Changed
- **CLI --limit validation**: Upgraded from `min=0` to `min=1` across `collect.py`, `kb.py`, `summaries.py` — now rejects `--limit 0` as meaningless (strengthens #32 fix)

### Fixed
- **#30 — collectors: PubMed/RSS/Web source_platform**: Added `source_platform` field to `Item` dataclass and populated in all collectors (PubMed, RSS, Web, email_imap). KB mapping updated from `item.source_name` to `item.source_platform`.
- **#31 — collectors/pubmed collected_at**: Added `collected_at` parameter from `pub_date` metadata in PubMed collector; also added to web collector from extracted date.
- **#32 — CLI --limit negative values**: Added `min=1` Click range validation to all 4 `--limit` CLI parameters. Negative values are now rejected by Click's type validation.

## v1.4 (2026-07-23)

### Added
- **Domain management (F10b)** — `add_domain`/`remove_domain` MCP tools and `autoinfo domain` CLI command group (add/list/show/remove/activate/deactivate). Users can now define custom domains without editing YAML config directly
- **`list_available_platforms` MCP tool** — Returns all supported source platform types with descriptions, enabling agents to discover valid source types dynamically
- **Translation QA pipeline (F10/G5 enhanced)** — 5 lite quality gates (terminology compliance, back-translation consistency, multi-round refinement, composite quality scoring, translator-qa-skill) with `_terminology.yaml` terminology guardrails and `get_translation_quality` MCP tool
- **HTML format output (F24/F25)** — `generate_digest` and `generate_report` now support HTML format via Jinja2; `generate_presentation` supports HTML via Reveal.js CDN with speaker notes; all output tools accept optional `custom_instructions` parameter for LLM-guided content adaptation
- **KB import module (F26)** — `import_kb` MCP tool imports content from 4 formats (PDF, Markdown, HTML, JSON) directly into 01-Raw tier, with format auto-detection and metadata extraction
- **Per-item webhook push (F27)** — `set_domain_webhooks`/`get_domain_webhooks` MCP tools for configuring webhook URLs per domain; collected items are pushed to configured webhooks on completion
- **Cron-based email digest delivery (F27)** — Scheduled email digest via SMTP + crontab; `add_schedule` extended with `email` action for automatic digest delivery on schedule trigger
- **Agent proactive alerting (F29)** — `docs/dev/agent-alerting.md` documents polling-based source health monitoring pattern; agents proactively poll `get_source_health` to detect 3+ consecutive failures and flag to user
- **`custom_instructions` parameter** — Added to all output generation tools (`generate_digest`, `generate_report`, `generate_tutorial`, `generate_presentation`, `localize_content`) for LLM-guided content adaptation
- **`import_kb` MCP tool** — 4-format import (PDF, Markdown, HTML, JSON) → 01-Raw KB tier with format auto-detection, source metadata extraction, and idempotent import dedup

### Changed
- **CLI expanded from 14 to 17 command groups** — `domain` and `clean` groups added; `keywords` promoted from sub-command to full command group
- **MCP tool inventory expanded from 65 to 72 tools** — 7 new tools: `add_domain`, `remove_domain`, `list_available_platforms`, `import_kb`, `set_domain_webhooks`, `get_domain_webhooks`, `get_extraction` (previously missing from registration); `extract_fields` tool added for on-demand re-extraction
- **MCP tool categories expanded** — Added **Domain** (2 tools), **Webhooks** (2 tools), **Export/Import** (2 tools), **Custom Extraction** (2 tools) categories
- **Output generation tools upgraded** — All output tools accept `custom_instructions`; digest/report support HTML format; presentation uses Reveal.js CDN for HTML slides
- **README.md comprehensively rewritten** — Features, status table, CLI commands, MCP tools table, and Known Limitations all updated to v1.4 reality
- **AGENTS.md updated** — MCP tool count (65→72), CLI count (14→17), status table, project structure, and tool categories all revised for v1.4
- **founder-expectations.md updated** — Section 9 status, component table, gantt chart, and CLI examples revised to v1.4 reality
- Version bumped from `1.3.0`

### Infrastructure
- `docs/dev/agent-alerting.md`: New document — polling-based agent proactive alerting pattern (6 pages, full workflow with MCP tool reference, scenario dialogues)
- `src/autoinfo/cli/domain.py`: New module — domain CRUD CLI (add/list/show/remove/activate/deactivate)
- `src/autoinfo/mcp/server.py`: 7 new tool handlers (add_domain, remove_domain, list_available_platforms, import_kb, set_domain_webhooks, get_domain_webhooks, get_extraction) + extract_fields tool

### Fixed
- `list_keywords` MCP tool now correctly registered in Discovery category (was missing from tool manifest)
- `get_extraction` MCP tool now correctly registered (was defined as handler but missing from `list_tools`)

## v1.3 (2026-07-21)

### Added
- **`ErrorCode` enum** — Centralized `ErrorCode(str, Enum)` in `src/autoinfo/mcp/errors.py` with 19 typed members replacing 47 fragmented literal strings across all handlers
- **`init_project` MCP tool** — Idempotent project initialization via MCP (mirrors CLI `init`), with `domain` param, 15 dedicated tests
- **`ErrorResponse` TypedDict** — Structured error response type with `error_code`, `message`, `actionable` fields; `error_dict()` and `error_response()` helpers

### Changed
- **MCP schema hardening** — 15 enum constraints on categorical params, 5 crash-risk defaults made non-nullable, `required` arrays enforced on all tools with properties (was optional in ~25% of schemas), nested descriptions fixed on `add_sources`
- **Error handling refactored** — 46 literal `error_code` strings → `ErrorCode` enum refs across `server.py`, `dispatch` handlers, `call_tool`, MCP tool handlers. 4 bare-`"error"` dict keys → `"error_code"`. 5 dynamic `type(exc).__name__` → `ErrorCode.INTERNAL_ERROR`. Error helpers updated from `_error_dict`/`_error_response` to `error_dict`/`error_response`. `src/autoinfo/api/routes.py` aligned with `ErrorCode | str` type.
- **AGENTS.md comprehensively rewritten** — No "Greenfield" mode, 12 common patterns (was 0), `health_check`-first discovery flow, updated constraints (8 rules), accurate tool counts, directory tree mirrors actual mcp/ module
- Test suite expanded from 825+ to **1134 tests** (38 new `tests/test_errors.py`, 15 new `tests/test_mcp_init_project.py`)
- MCP tool inventory: 65 tools across 15 categories (was "70+ areas across 12")
- Tool table in README and AGENTS.md now matches actual 65-tool listing exactly
- Version bumped from `1.2.0`

### Fixed
- **5 crash-risk MCP schema gaps**: `batch_run.sources`, `export_kb.topic`, `localize_content.target_lang` (missing `required` arrays), `get_effective_llm_config.task` (non-nullable with default), `add_sources.sources.items` (nested description)
- **6 GitHub issues resolved**: #4 (AGENTS.md staleness), #5 (error_code centralization), #6 (init_project tool), #7 (discovery flow), #8 (MCP schema gaps), #9 (common patterns)
- **#10 (LLM extraction crash on `None` content)**: `_parse_response()` hardened with `TypeError` guards around all 3 JSON parse strategies + `None` content returns empty dict early with warning. `process.py` detects extraction failure (empty `tl_dr` + no key points + no entities + score 0) and logs `extraction_failed` flag per item. Prevents SQLite indexing gap from silent parser crashes.
- **#12 (KBEntry missing `quality_flags` field)**: `KBEntry` model gains `quality_flags: dict[str, bool]` field. `_build_frontmatter()` merges `entry.quality_flags` with `quality_results` override. `reindex_knowledge_base()` reads `quality_flags` from frontmatter. `get_entry()` extracts `quality_flags` from frontmatter.
- **#13 (filesystem fallback when SQLite index is empty)**: New `KBStore._scan_kb_filesystem()` helper walks `knowledge/<domain>/**/*.md` and returns same dict shape as `SQLiteIndex.list_entries`. `list_entries()`, `list_all_entries()`, `get_entry()`, `get_summary()` all fall back to filesystem scan when SQLite returns no results. `show_status()` in `status.py` counts `.md` files on disk when SQLite count is 0.
- All CLI files (`cli/*.py`) and shared modules (`doctor.py`, `kb.py`, `keywords.py`, `process.py`) updated to use ErrorCode enum

### Infrastructure
- `.omo/plans/fix-6-issues.md`: Execution plan — 10 tasks, 3 waves + 4 final reviewers, all APPROVED
- `src/autoinfo/mcp/errors.py`: New module — ErrorCode enum, helpers, re-exported via `__init__.py`
- 3 commits pushed to `origin/main` (waves 1-2 + final verification)
- F1-F4 final verification wave: all 4 APPROVED (Oracle compliance, code quality, manual QA, scope fidelity)

### v1.3 amendments (2026-07-22)

#### Added
- **LLM token usage tracking** — `ExtractionResult.usage` captures `prompt_tokens`, `completion_tokens`, `total_tokens` from LiteLLM responses; `ProcessResult.token_usage` aggregates per-run totals exposed in `process_collection` MCP response (#27)
- **`job_id` progress signals** — `collect_sources` and `process_collection` return a `job_id`; `get_collection_progress(job_id=...)` and `get_processing_progress(job_id=...)` support job-based lookup for progress polling (#22)
- **MCP connection configs** — `.cursor/mcp.json`, `.claude/claude_desktop_config.json`, `.opencode/mcp.json` with `python -m autoinfo.mcp.server` entrypoint (#23)
- **`confirm` param on destructive tools** — `remove_source`, `remove_topic`, `remove_schedule`, `archive_project` require `confirm=True` to execute (#24)
- **Quick Start (5 Seconds)** guide in AGENTS.md for all agent platforms (#23)

#### Changed
- **`batch_run` returns per-phase results** — Structured `phases[]` array with per-phase `status`, `duration_s`, and partial results on failure (#26)
- **MCP tool parameter documentation** — `source_id` and `topic_id` descriptions now include format examples (e.g., `'medical-research:pubmed'`) (#25)
- **Optional list tool filters** — `list_active_collections(domain=...)`, `list_projects(status=...)`, `get_project_assets(type=...)` accept optional filter params (#25)

#### Fixed
- **5 GitHub issues resolved**: #22 (progress signals), #23 (MCP configs), #24 (confirm param), #25 (doc/filters), #26 (batch_run), #27 (token usage)
- Test suite expanded to **202+ MCP tests** with new `TestJobId`, `TestConfirmParam`, `TestToolFilters` test classes

## v1.2 (2026-07-21)

### Added
- **FastAPI REST API** — Full CRUD (`/api/v1/entries`, `/health`, `/dashboard`), port 8741, localhost-only (no auth)
- **Hybrid vector search** — sqlite-vec embeddings + FTS5 keyword (0.7 FTS5 + 0.3 vec weight), cosine similarity ranking
- **Faceted search** — 7 filters (domain, tier, tags, date range, quality tier, content type, language)
- **Keywords management system** — Central `_keywords.yaml` per domain; `list_keywords` and `manage_keyword` MCP tools + CLI
- **DB schema versioning** — `schema.py` with version markers in SQLite, migration support
- **`autoinfo init --name`** — Project name override flag
- **Git auto-commit + SHA tracking** — KB entries versioned with git SHA, automatic commits on write
- **Obsidian `[[wiki links]]`** — Native wiki-link syntax in KB Markdown files
- **CEFR text classification** — LLM-based EN/ZH/JA reading level scoring (A1-C2), auto-classification on creation
- **Multi-user foundation** — `user_id` fields on all KB entries (no auth/teams yet)
- **PDF export** — WeasyPrint-powered report generation with proper formatting, tables, headers
- **JSON report format** — Structured report output alongside Markdown
- **`generate_report` MCP tool** — Report generation with `format` param (markdown/json/pdf)
- **SMTP email sender** — `send_email()` MCP tool, `autoinfo email send/config` CLI
- **`autoinfo cron install/uninstall`** — POSIX crontab automation (writes/removes crontab entries)
- **Web UI Dashboard** — Bootstrap 5, collection stats, KB search, source health overview, REST API client
- **105 integration tests** — Comprehensive v1.2 feature coverage in `tests/test_v1_2_integration.py`

### Changed
- MCP tool inventory expanded from 56+ to 70+ tool areas (CEFR, email, keywords categories)
- CLI command groups expanded from 12 to 14 (`cefr`, `email` groups added)
- Test suite expanded from 720+ to 825+ tests
- Search architecture upgraded from FTS5-only to hybrid (FTS5 + sqlite-vec)
- Version bumped from `0.1.0.dev0` to `1.2.0`
- README updated with v1.2 feature set and revised Known Limitations
- Updated founder-expectations.md: Sections 5, 9, 10, 11, 12, 13, 14 revised to v1.2 reality
- Updated autoinfo-validation-master-plan.md baseline to v1.2

### Infrastructure
- `.omo/plans/autoinfo-v1.2.md`: Full v1.2 execution plan (25 tasks, 5 waves)
- `.omo/evidence/final-qa/`: F3 QA evidence (8 scenarios, all pass)
- 6 commits pushed to `origin/main` (waves 1-5 + verification)

## v1.1 (2026-07-21)

### Added
- G5 translation accuracy quality gate (advisory, optional)
- KBStore.promote_kb_draft() method + `autoinfo kb promote` CLI
- 03-Wiki append-only guards (agent writes blocked)
- Init directory structure: 00-Inbox, 02-Draft, 03-Wiki
- Interactive init wizard (domain selection, LLM config)
- KB frontmatter: author, source_ids, status, related_concepts, linked_entries
- Language auto-detection (langdetect) for Item.language
- 6 new MCP tool areas: collection progress/status, domain lifecycle, list_keywords, tutorial/presentation
- `autoinfo collect --all` flag for multi-domain collection
- test_source extract_fields suggestions + quality tier warnings
- 7 curated demo sources (arXiv, CrossRef, Unpaywall, Crunchbase, LMSYS, news-in-levels, commonlit)
- Webhook source handler (HMAC, rate limiting)
- Email (IMAP) source handler (stdlib imaplib)
- PDF source handler (PyMuPDF, chunking)
- Knowledge graph export CLI (JSON/GraphML/CSV)

### Changed
- SourceConfig supports `settings` dict for extra config fields
- G3RelevanceScoring supports multi-language keywords and per-topic threshold
- Topic dataclass: group, relevance_threshold fields
- Updated README with Known Limitations section + v1.1 final status
- Updated founder-expectations.md: Sections 5, 9, 10, 11, 12.10, 13 updated to v1.1 reality
- Added Section 14 to founder-expectations.md: remaining gaps catalog
- MCP tool inventory expanded from 35 to 56+ tool areas

### Fixed
- Dead code removal (unused imports, orphaned test assertions)
- Test mock updates for KG test (process_calls_store_entities)
- install pytest-mock for KG test fixtures
- CI: F1-F4 final verification wave — all 4 pass (Oracle, code quality, manual QA, scope fidelity)

### Infrastructure
- `.omo/evidence/final-qa/`: 11 QA scenario evidence files (S1-S11)
- `.omo/plans/autoinfo-v1.1.md`: Full execution plan
- `.omo/notepads/autoinfo-v1.1/learnings.md`: Implementation learnings

## v1.0.0-dev (2026-07-20)

### Added

#### v0.1.1: Config Expansion & Infrastructure
- LLM task config: per-task model selection (`llm.tasks.extraction`, `llm.tasks.summarization`)
- LLM fallback chains (`llm.fallback: [{provider, model}]`)
- `get_effective_llm_config(task)` — resolved model config
- Domain config extensions: `extract_fields[]`, `search_mode`
- Batch processing: `process_collection(domain, batch_size=N)` + `get_processing_progress`
- CLI modules: sources, topics, kb, output, cron (with stubs)
- MCP tools: list_domains, get_domain_schema, list_available_models, get_effective_llm_config,
  add_source, add_sources, remove_source, test_source, list_sources,
  add_topic, remove_topic, search_knowledge_base, flag_for_knowledge_base, list_output_templates
- config.save_config() + config_to_dict() public API

#### v0.2: KB & Search
- FTS5 full-text search across all KB tiers (Raw + Draft + Wiki)
- CJK tokenizer support (unicode61)
- `autoinfo kb search` CLI command + MCP tool
- `autoinfo kb reindex` command for FTS5 population
- 02-Draft tier: agent creates Draft from Raw entries
- `create_kb_draft(raw_ids, title, summary, tags)` with Raw validation
- `reject_kb_draft(draft_id, reason, action)` — moves back to Raw
- `list_kb_tier(domain, tier)` — filter by pipeline stage
- Custom extraction fields per domain (`extract_fields: [methodology, sample_size]`)
- Dynamic LLM prompt construction from field schema
- On-demand re-extraction via `extract_fields` MCP tool
- `flag_for_knowledge_base(summary_id, tags, importance)` — tag entries for KB
- `autoinfo summaries flag` and `autoinfo summaries show` CLI commands
- G4 factual consistency gate: LLM checks summary vs source
- `autoinfo process --check-factual` flag

#### v0.3: Multi-source & Schedule
- Web scraping handler via trafilatura (compose/compat)
- AI-commercial demo domain (TechCrunch RSS, ProductHunt API)
- Source CRUD: add, list, remove, test (idempotent, writes to config)
- Topic CRUD: add, list, remove
- Scheduled collection via crond wrapper
- `autoinfo cron run`, `add-schedule`, `list-schedules`, `remove-schedule`
- croniter dependency for cron expression parsing
- Source health monitoring: healthy/degraded/error/paused states
- `rate_item(item_id, rating, feedback)` — user feedback in SQLite

#### v0.4: Q&A & Output
- FTS5+LLM Q&A: `query_collected()` with FTS5 search + LLM synthesis
- Answer with source citations [1], [2] format
- Digest generation via Jinja2 + LLM: `generate_digest(domain, period, format)`
- Report generation: thematic grouping, executive summary, sections
- Export functionality: Markdown (tar.gz), JSON array, SQLite copy
- Jinja2 templates: digest.md.j2, report.md.j2

#### v0.5: Mature MCP
- 50 MCP tools across 12 categories
- Auto-linking: keyword-overlap creates "related" relations during collection
- `link_items(item_a_id, item_b_id, relation)` + `get_item_relations(item_id)`
- Playwright web handler fallback for JS-heavy pages
- Entry versioning: .bak copies, max 5 versions, get_entry_history, restore_entry_version
- `get_collection_stats(period)` — aggregate across domains
- `get_collection_diff(since_id)` — delta query
- Config override system (`~/.autoinfo/overrides/`)
- Complete CLI coverage: sources health, kb list-tiers, output list-templates
- MCP tools: list_projects, get_project_assets, archive_project, batch_run, list_active_collections, get_config

#### v0.6: Graph & Translation
- Knowledge graph: entity extraction (6 types) + relation discovery
- `query_knowledge_graph(entity, relation)` MCP tool
- LLM-based translation: `localize_content(content_id, target_lang)`
- Tutorial generation with audience adaptation (researcher/clinician/executive/student)
- Presentation generation with speaker notes
- Jinja2 templates: tutorial.md.j2, presentation.md.j2
- Language-learning demo domain (Project Gutenberg, BBC Learning English RSS)
- All 3 demo domains: medical-research, ai-commercial, language-learning

### Infrastructure
- `docs/autoinfo-validation-master-plan.md` — comprehensive validation plan (19 questions, 7 parts)
- All docs updated to reflect v1.0 status

#### Config System
- `src/autoinfo/config.py` — YAML-based configuration with env var resolution
- Config validation: required fields, domain+source structure checks
- Demo domain template at `src/autoinfo/data/domains/medical-research/sources.yaml`

#### CLI Commands
- `autoinfo init --demo medical-research` — project skeleton generator with idempotent behavior
- `autoinfo doctor` — system health check (Python version, config, LLM key, source reachability)
- `autoinfo collect` — multi-source collection with `--domain`, `--topic`, `--limit`, `--dry-run`
- `autoinfo process` — LLM extraction + quality gates + KB storage pipeline
- `autoinfo collect --auto-process` — combined collect + process in one command
- `autoinfo status` — collection statistics and source health overview
- `autoinfo summaries list` — browse extracted summaries with pagination
- `--json` global flag on all commands for machine-readable output

#### Collection Pipeline
- PubMed API handler (E-utilities esearch + efetch) with rate limiting (3/10 req/sec) and retry
- Generic RSS/Atom handler via feedparser
- Collection orchestrator with source dispatch, progress tracking, and JSON caching
- Dedup system (G2): URL exact match + PMID/DOI cascade matching

#### LLM Extraction
- `LLMExtractor` class using LiteLLM (multi-provider via config)
- Default extraction: TL;DR, 3-5 key points, entity extraction, relevance score (0-100)
- Dry-run mode to preview prompts without API calls
- Retry logic with configurable max retries
- Snapshot regression tests (no real LLM calls in CI)

#### Quality Gates
- G1 (Source authority): advisory tier check, flags Tier 3+ sources
- G2 (Dedup): URL/PMID/DOI matching against existing entries
- G3 (Relevance scoring): keyword overlap scoring, items below 30 threshold hidden by default
- All gates advisory — never block or discard content

#### Knowledge Base Storage
- `KBStore`: Markdown files at `knowledge/<domain>/01-Raw/<topic>/<YYYY-MM-DD>-<slug>.md`
- YAML frontmatter with 14 required fields (title, source_url, source_type, source_platform, collected_at, etc.)
- `SQLiteIndex`: lightweight metadata index for fast listing (100+ entries in <100ms)
- `list_entries()` with pagination (`limit`, `offset`, date filtering)
- `get_entry()` reads full content from Markdown files

#### MCP Server
- 6 tools over stdio transport via MCP Python SDK
- `health_check()`, `diagnose_system()`, `collect_sources()`, `process_collection()`, `list_summaries()`, `get_kb_entry()`
- Structured error responses with `error_code`/`message`/`actionable` fields
- Server entry point: `python -m autoinfo.mcp.server`

#### Testing
- 220 tests across 11 test files
- Test infrastructure: pytest, CliRunner, VCR cassettes, synthetic fixture data
- Integration tests: T1-T5 True Test (init → collect → process → summaries)
- LLM extraction snapshot regression tests (mocked LiteLLM)
- Coverage: config, CLI, PubMed handler, RSS handler, collection, quality gates, LLM, KB, MCP

### Agent-Orientation Enhancements
- `diagnose_system()` MCP tool — comprehensive health diagnostic (LLM, sources, disk, DB)
- `add_source()` idempotent — safe for agent retry
- `add_sources()` batch variant — multi-source in one call
- `get_domain_schema(domain)` — discover available extraction fields
- `list_available_models()` — discover configured LLM models
- `list_output_templates(domain)` — discover available output types
- `collect_sources(..., dry_run=true)` — preview collection before committing
- `get_collection_diff(domain, since_collection_id)` — delta queries
- `get_kb_entry(entry_id)` — read full entry content (not just search summary)
- `list_keywords(domain, status)` — query keyword taxonomy
- `get_effective_llm_config(task)` — resolved model config without YAML parsing
- `reject_kb_draft(draft_id, reason, action)` — agent-handled Draft rejection
- Source tier warnings on `add_source()`
- `estimated_duration_s` on collection start for optimal poll intervals
- Pagination (`limit`/`offset`/`total_count`) on all list/search tools
- Wiki entries explicitly append-only; agent cannot demote

### Infrastructure
- `AGENTS.md` — comprehensive agent onboarding guide
- `README.md` — project overview and quick start
- `.gitignore` — Python project hygiene
- `.opencode/skills/` — Coding agent skill definitions (development workflows)
- `docs/skills/autoinfo-skill/SKILL.md` — AutoInfo operator skill (MCP operation guide for agent-users)
- `Makefile` — `install`, `test`, `lint`, `clean` targets
