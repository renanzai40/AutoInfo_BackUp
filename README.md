# AutoInfo

**Universal information tracking and knowledge base platform.**

Configure sources and topics. AutoInfo handles the rest: automated collection,
LLM-based structured extraction, summarization, and a queryable knowledge base.

> "AutoInfo is your information assistant — not helping you search, but
> automating the entire pipeline from collection to knowledge curation."
>
> Domain-agnostic. Agent-native. BYOK.

## Features

- **Multi-source collection** — RSS, REST APIs (PubMed E-utilities), web pages (trafilatura + Playwright), webhook (HMAC), email (IMAP), PDF (PyMuPDF)
- **Domain management** — Add, remove, list, activate/deactivate domains via CLI and MCP tools
- **LLM-powered extraction** — TL;DR, key points, entity extraction, relevance scoring, custom field extraction
- **Knowledge base (4-tier pipeline)** — 4-tier KB pipeline: 00-Inbox (deprecated) → 01-Raw (sole entry) → 02-Draft → 03-Wiki (Markdown + SQLite), with git versioning and `[[wiki links]]`
- **KB import** — Import content from 4 formats (PDF, Markdown, HTML, JSON) directly into 01-Raw
- **Hybrid search** — FTS5 keyword + sqlite-vec vector embeddings, faceted filtering
- **REST API** — Full CRUD over HTTP (FastAPI, port 8741), no auth (localhost security)
- **Web UI Dashboard** — Bootstrap 5, collection stats, KB search, source health overview
- **CEFR classification** — LLM-based EN/ZH/JA reading level scoring for language learning
- **Output formats** — Markdown, JSON, PDF, **HTML**, **EPUB/MOBI** (ebooklib EPUB3 + calibre MOBI via `format="epub"/"mobi"`), **Audiobook** (chaptered MP3 via `format="audiobook"`, ID3v2.3 CHAP/CTOC + ZIP bundle), **Video** (HTML+GSAP→MP4 via HyperFrames: TTS narration + themed scene compositions, 36+8 themes, 6 layouts with mandatory adjacent-scene diversity) (digest/report via Jinja2 + LLM, presentation via Reveal.js CDN); report section headings are SHORT SEMANTIC theme titles (concise noun phrases, never keyword dumps) with near-duplicate headings merged (#311)
- **Translation QA pipeline** — 5 lite quality gates, back-translation verification, multi-round refinement, terminology guardrails, composite quality scoring
- **Email sending** — SMTP-based digest delivery (manual and cron-scheduled)
- **Webhook push** — Per-item webhook notification on collected content
- **Quality gates** — 6 hard/soft gates (G0-G5: G0/G4 hard, G1-G3/G5 soft) + 3 delivery gates (D1-D3). Retry-first, block-last philosophy.
- **Product delivery** — Two product types: RAW (API feeds, webhook streams, bulk export) and PROCESSED (scheduled digests, thematic reports, alert streams via SMTP/webhook)
- **Multi-channel delivery** — 13 delivery channels: SMTP, Webhook, REST API, File Export, Discord, Telegram, WeChat Work, WeChat OA, DingTalk, FeiShu, RSS, Social Publish, Push. Email as mandatory fallback. Per-channel rate limiting and message formatting.
- **End user lifecycle management** — EndUserProfile + Subscription CRUD. Lifecycle state machine: trial → active → suspended → cancelled. Configurable trial and grace periods, transition hooks.
- **Delivery reliability** — Per-subscription delivery log with SLA tracking (P0 ≤5min, P1 ≤30min, P2 ≤2hr). Retry chain with fallback. Never silently drop products.
- **End user self-service portal** — CLI portal for delivery preference management (show/update) and delivery history; REST API portal (`/portal/{user_id}/...`) surfaces typed preferences (content_preference, QuietHours, identity_anchor) merged over legacy, plus product archive access.
- **Immutable audit logging** — Append-only audit log for all operations (MCP, CLI, pipeline). Queryable via MCP tool and CLI. Full actor/resource/action tracking.
- **Structured pipeline logging** — JSON structured logging per pipeline event with daily rotation. Configurable log levels per stage. Filter and tail via CLI.
- **Per-item traceability** — UUID trace_id propagated from collection through delivery. CLI displays full item journey: sources, gates, KB entries, delivery status.
- **Cost governance** — Internal cost metering (LLM tokens, storage, API calls) with per-domain/per-user allocation. Cost dashboard with daily trends, top models, budget alerts. CLI and MCP tools.
- **Budget alerts & cost control** — Threshold-based alerts (absolute, rate-based, projected overrun). Auto-remediation actions per alert. Configurable via MCP tools.
- **Source ToS compliance** — Source classification (Open/Licensed/Restricted/Sensitive) with per-tier output controls. Attribution in generated outputs. Compliance checkpoint at G1 gate.
- **Data deletion & retention** — Soft-delete with restore within retention window. Retention by subscription tier. 30-day auto-cleanup. GDPR-compliant data export. Permanent purge only via explicit flag.
- **Knowledge lifecycle management** — Per-domain TTL & freshness scoring. Versioned re-collection with structured diff. Stale content handling (demoted in search, excluded from digests). Domain decay metrics with proactive agent alerts. Cross-collection dedup & merge with LLM assistance.
- **Operational observability** — Enhanced diagnostics (`doctor --verbose`) with composite health score (0-100). Prometheus metrics export. Per-domain error rates, latency p95/p99, LLM spend summaries.
- **Agent-native** — 146 MCP tools across 35 categories. Agent operates, human directs.
- **Self-discovering tool count** — `get_tool_count` MCP tool returns dynamic tool count, no more hardcoded numbers
- **LLM configuration tool** — `configure_llm` MCP tool for agent-oriented BYOK setup (provider, model, api_key, base_url, `llm_fallback` chain, `llm_tasks` per-task routing); `test_llm_connection` verifies connectivity
- **Agent-oriented error responses** — Unified dual-format error responses (flat + envelope) for backward-compatible consumer migration
- **Cross-domain search** — `search_knowledge_base()` searches all active domains when domain is omitted
- **Domain-less collection** — `collect_sources()` collects from all active domains when no domain specified
- **Agent-native tutorial/presentation/export** — Tutorial, presentation, and KB export support `format="agent"` for JSON-LD output
- **Inline source citations in tutorials** — tutorial content bodies cite the real KB entry `source_url`s they synthesize (`(Source: <url>)`), aligned with the digest/report citation mechanism
- **Persistent job state** — Collection/processing job state survives server restarts via SQLite-backed storage
- **Persistent agent callbacks** — Agent callback registration persists across restarts via SQLite
- **Batch CEFR classification** — `cefr_batch` MCP tool for classifying multiple texts at once
- **Audit log MCP tool** — `query_audit_log` MCP tool for programmatic audit log access
- **Knowledge graph export** — `knowledge_graph_export` MCP tool for graph-structured KB export
- **Cost dashboards & allocation MCP tools** — `cost_dashboard` and `cost_allocation` MCP tools for cost governance
- **RSS feed MCP tool** — `get_feeds` MCP tool for RSS feed retrieval with RSS XML output
- **Hard-delete purge** — `soft_delete_entry(entry_id, purge=True)` for permanent entry removal
- **Fine-grained process control** — `process_collection()` exposes `check_factual` and `check_translation` flags
- **Topic grouping** — `topic_group_add`/`topic_group_remove` MCP tools for organizing topics into groups
- **Email config MCP tool** — `email_config` MCP tool for email configuration management
- **Cache cleanup MCP tool** — `clean_cache` MCP tool for temporary artifact cleanup
- **BYOK** — Bring your own LLM keys. Multi-provider via LiteLLM/OpenRouter.
- **Domain-agnostic** — 13 demo domains (medical, AI commercial, financial/business intelligence, tech/AI/developer, language learning, online video, financial news, online education, legal compliance, general news, gaming, B2B, retail). Any field with paying customers.
- **Subscription-ready** — Stripe integration with webhook endpoint (signature verification), stripe-mock dev setup, freemium gating, and usage metering
- **Subscription tiers** — Free, Premium, and Enterprise tiers with per-tier channels, domains, products, and platform limits on the Subscription model
- **Access control** — `check_access()` fast path gates content by tier (free always allowed, premium/enterprise require active paid subscription). Freemium gating (G15).
- **Consumption tracking** — `ConsumptionEvent` auto-record on digest/report delivery (view/open/click events) with SQLite-backed store
- **Automated notifications** — Trial-ending reminders (3-day window) and content-ready notifications dispatched to end users
- **Channel health monitoring** — `get_channel_health` MCP tool checks all 13 delivery channels (smtp, webhook, rest_api, file_export, discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss, social_publish, push) with latency and error status
- **Cron health monitoring** — `autoinfo cron health` CLI with heartbeat tracking and missed-schedule detection
- **SQLite backup** — `make backup` target plus `scripts/backup-db.sh` and `scripts/restore-db.sh` for automated KB and user-store backups (keeps last 7)
- **22 new collectors** — DBLP, NYT, OpenAlex, Reddit, Spotify, YouTube, Bilibili, Apple Podcasts, Semantic Scholar, USPTO, plus paid AP API and Reuters MCP handlers (v1.6), plus SSRN, GDELT, Yahoo Finance, Quandl, HuggingFace/Kaggle, Unpaywall/CORE (v1.8.4), plus HackerNews (Unreleased 2026-08-04), plus AKShare, SEC EDGAR, edX sitemap (2026-08-05). 30 total collector handlers across all source types.
- **Collector fulltext depth** — `fetch_depth: fulltext` threaded through collection dispatch: Unpaywall (OA fulltext via trafilatura), RSS (entry.link fulltext), YouTube (transcript download), GDELT (article fulltext) — 8000-char cap, graceful fallback on failure; scoped re-collection proved ~4x deeper content on the medical-research deliverable domain
- **Bundle export** — `export_kb(format="bundle")` creates a ZIP archive containing JSON data, Markdown summary, YAML metadata, and a weasyprint-rendered PDF report (with graceful fallback)
- **Cross-domain reports & digests** — `generate_report()` and `generate_digest()` accept a `domains` parameter for multi-domain synthesis. New MCP tool `generate_cross_domain_report` for cross-domain analysis.
- **Specialized report types** — `report_type` parameter: `industry`, `competitive`, `trend`, `daily-briefing` — each with customized section structure and LLM prompts
- **Differentiated product templates** — 8 product families with dedicated Jinja2 templates, incl. `premium-briefing` (market-report-anchored numbered takeaways with So-what/Risk/Actions), `enterprise-briefing` (one-page exec summary + Key Metrics table + Action Required + Risk matrix; renders a deterministic selection-scope label `精选 N 条详述 · selected N of M items` so the Executive Summary coverage claim always matches the detailed Key Findings count), and `magazine-digest` (per-title clusters + editorial intro + personality feature story). Guard-first product-type resolution + digest render-context normalization; `generate_report(product=...)` / `generate_digest(product=...)` / CLI `--product`
- **Per-product LLM synthesis** — implications/risks/action_required/key_metrics fields synthesized per product template and carried into agent-format JSON-LD output
- **Delivery schedule automation** — `add_delivery_schedule` MCP tool for cron-based periodic output generation + delivery. Integrates with `autoinfo cron run`.
- **Content simplification (E14)** — `simplify_content` MCP tool rewrites text to a target CEFR reading level (A1-C1) using LLM, with original/simplified level classification and verification flag
- **Single-article payment (E12)** — `create_checkout_session` supports `mode="payment"` for one-time article purchases; `check_access(article_id=...)` fast path verifies article entitlement grants
- **Source credibility score (E9)** — Deterministic `source_score` (0-100) derived from quality tier, persisted on KBEntry, surfaced in search results and G1 gate details
- **Product-analysis KB metadata** — per-product analysis fields (implications/risks/action_required/key_metrics) persisted to KB entry `custom_fields["product_analysis"]`; `search_knowledge_base(filter_custom_fields=...)` adds faceted filtering on custom_fields JSON
- **RAW product variants (E11)** — RAW product carries `variants: ["api_feed", "webhook", "bulk_export"]` field distinguishing the three RAW delivery modes
- **Podcast RSS publishing (C11)** — RSS 2.0 delivery channel with `<enclosure>` + `itunes:*` namespace for podcast feed generation; audio output auto-persists MP3 to disk
- **Validated source types** — `VALID_SOURCE_TYPES` frozenset (29 types) as single source of truth for source type validation across MCP and CLI
- **Agent-native validation** — `list_validation_scenarios` / `run_validation_scenario` MCP tools execute validation scenarios through the MCP surface (plus CLI subprocess and REST HTTP steps): each step makes a real call and asserts on the `{success, data}` envelope; env-gated steps report `unconfigured` (never silently skipped), and `llm_assert` runs a real model call for semantic checks. 124 scenarios (65 functional + 59 regression). Per-step `timeout_seconds` guards runaway steps; failed steps can declare `recovery_steps` (run after the primary failure); scenarios support partial-pass via `min_passing` (int) / `pass_ratio` (float); `requires_http` gates steps that need a live REST server (reports `unconfigured` when offline). Results carry a per-step execution trace (step_index/duration/arguments/trace_id + llm_meta model/tokens/duration); `run_validation_scenario` output includes a root-cause report with `## Blockers` and `## Per-step trace` sections.
- **Validation regression flywheel** — `scenarios/regression/` subdirectory (59 regression scenarios, `regression: true` key) auto-loads via recursive glob; `coverage_audit.py` prints a "Regression scenarios: N (issues: ...)" metric; `.github/ISSUE_TEMPLATE/bug_report.md` carries a mandatory 回归场景 (regression scenario) field so every bug ships with a scenario.
- **Validation delivery packaging** — `scripts/validation_delivery.py` builds 01-RAW / 02-PROCESSED / 03-KB / 04-MATRIX / 06-REJECTED plus `validation-report.md` and `manifest.json` with per-file authenticity, D1-D3 delivery gates, and UX metrics (UX_OK/completion_rate ≥ 0.8). Output scenarios persist `collect_artifacts` for post-run inspection.
- **End-user coverage matrix (E8)** — `scripts/coverage_matrix.py` generates the end-user feature coverage matrix from `docs/dev/specs/end-user-matrix.yaml` (v3: 8 products × 8 formats × 13 domains, 29 source platforms, 14 channels, 15 capabilities); surfaced as the 04-MATRIX section in validation delivery plus Oracle R8 unconfigured-vs-gap analysis. Scenario library currently exercises 8/8 products, 8/8 formats, 28/29 source platforms (email_imap not yet covered).
- **End-user journey validation** — `enduser-journey.yaml` scenario drives the full B1 lifecycle with UX metrics (UX_OK/completion_rate ≥ 0.8) measured in validation packaging; the error-boundary scenario asserts the `actionable` field of the error envelope.
- **LLM concurrency governance** — per-provider shared rate limiting (`AUTOINFO_LLM_MAX_CONCURRENCY`, default 4, clamped ≥1) via a `threading.Semaphore` per `(provider, base_url)` in `llm.call_with_fallback`, enforced across every fan-out path (process workers, post-extraction gates, cefr_batch, output grouping, MCP `to_thread` handlers, fallback chain); jittered exponential backoff on HTTP 429/5xx (3 attempts, base 1.0s ×2, cap 8s, jitter ±25%; non-retryable 4xx never retried); process worker cap raised 8→16 (probe-gated: 0 rate limits at workers 1/4/8/16 with bounded p95); post-extraction gates G3/G4/G5/CEFR run concurrently per item (`AUTOINFO_SUBTASK_CAP`, default 4); CEFR classification moved outside the storage lock; `cefr_batch` parallelized (`AUTOINFO_CEFR_BATCH_WORKERS`, default 8); `_group_by_theme` batch loop parallelized (max 4 workers, order preserved); 14 sync MCP LLM handlers offloaded via `asyncio.to_thread`; per-task model routing with release-pinned `JUDGMENT_MODEL = "deepseek-v4-flash"` for G4/G5/llm_judge judgment calls. (2026-08-13)
- **LLM timeout + parallel processing** — `LLMConfig.timeout` (default 120.0) threads through every LLM call; processing uses a `ThreadPoolExecutor` sized by `AUTOINFO_PROCESS_WORKERS` (default 5, env-clamped cap 16); MCP handlers offload blocking work via `asyncio.to_thread`.
- **LLM fallback chain on all paths** — shared `llm.call_with_fallback` helper; the configured `llm.fallback` list now protects every LLM call path (extraction, validation judge, quality gates, translation QA, output generation, keyword suggest, Q&A, CEFR), not just extraction. The actual fallback is `mimo-v2.5` on the same gateway (empty `provider`/`api_key` inherit the primary provider/key).
- **Dead-source detection** — Semantic Scholar HTTP 429 surfaces as `SourceFailure` (fail-fast, no partial results); arXiv rss/bio → rss/q-bio source config fix.
- **CLI module entry** — `python -m autoinfo.cli` runs the same Typer app as the `autoinfo` console script; `collect` prints live per-source progress lines.

## Status

| Component | Status |
|-----------|--------|
| Config system | ✅ LLM task config, per-task model, fallback chains, schema versioning |
| CLI | ✅ 28 command groups (init, doctor, collect, process, status, summaries, sources, topics, topic-group, domain, audit, kb, output, cron, knowledge, cefr, email, keywords, clean, cost, billing, enduser, portal, trace, import-kb, query-collected, alert-rules, agent-callback) |
| Collection | ✅ 30 collector handlers (PubMed, Semantic Scholar, DBLP, OpenAlex, USPTO, NYT, Yahoo Finance, Quandl, RSS, Web, webhook, email, PDF, Reddit, Spotify, YouTube, Bilibili, Apple Podcasts, plus paid AP API and Reuters MCP, plus SSRN, GDELT, HuggingFace/Kaggle, Unpaywall/CORE, HackerNews, AKShare, SEC EDGAR, edX sitemap), scheduled via crond; `fetch_depth: fulltext` threading (unpaywall/rss/youtube/gdelt, 8000-char cap) |
| LLM extraction | ✅ Custom extraction fields, TL;DR, key points, entities, G4 factual consistency, token usage tracking |
| Translation QA pipeline | ✅ 5 lite quality gates, back-translation verification, terminology guardrails, composite scoring, translator-qa-skill |
| Quality gates | ✅ 6 hard/soft (G0-G5: G0/G4 hard, G1-G3/G5 soft) + 3 delivery gates (D1-D3) + per-domain config |
| KB pipeline | ✅ 4-tier KB pipeline (00-Inbox → 01-Raw → 02-Draft → 03-Wiki; note: 00-Inbox is scaffolded but deprecated — 01-Raw is the sole entry point), git versioning + SHA tracking |
| KB import | ✅ 4 formats (PDF, Markdown, HTML, JSON) → 01-Raw via `import_kb` MCP tool |
| Search | ✅ Hybrid (FTS5 keyword + sqlite-vec vector), faceted (7 filters + `filter_custom_fields` on custom_fields JSON) |
| Q&A | ✅ FTS5 + LLM synthesis with source citations |
| Output generation | ✅ Digest (Markdown/HTML/JSON/Agent/Audio/EPUB/Audiobook), report (Markdown/JSON/HTML/Audio/Agent/Video/EPUB/Audiobook), tutorial (Markdown), presentation (Markdown), export (Markdown/JSON/SQLite/PDF/RSS/CSV/GraphML/Agent/Bundle/Sitemap/EPUB/MOBI) (Jinja2 + LLM, Reveal.js CDN, ebooklib EPUB3 + calibre MOBI); 8 product templates incl. premium-briefing/enterprise-briefing/magazine-digest (editorial intro + personality feature story, #313) + per-product LLM synthesis |
| Agent-native JSON output | ✅ `format="agent"` returns JSON-LD (`@type: KnowledgeDigest`) for LLM re-consumption |
| Audio output | ✅ TTS-rendered digest/report as MP3 (OpenAI TTS) via `format='audio'`; `format='audiobook'` = chaptered MP3 + ZIP (ID3v2.3 CHAP/CTOC via mutagen) |
| Video output | ✅ HyperFrames HTML+GSAP→MP4 (`report format="video"`): TTS narration + themed scene compositions, 36+8 themes, 6 layouts with adjacent-scene diversity; MCP `generate_report`/`generate_cross_domain_report` expose `video` |
| Translation | ✅ LLM-based source→target |
| Knowledge graph | ✅ Entity extraction + relation discovery |
| REST API | ✅ FastAPI CRUD (port 8741, /api/v1/entries, /health, /dashboard) |
| Web UI Dashboard | ✅ Bootstrap 5, collection stats, KB search, source health |
| MCP server | ✅ 146 tools across 35 categories |
| Domain management | ✅ `add_domain`/`remove_domain` MCP tools, `autoinfo domain` CLI (add/list/show/remove/activate/deactivate) |
| Webhook push | ✅ Per-item webhook notification on collection via `set_domain_webhooks`/`get_domain_webhooks` |
| Scheduled digest | ✅ Cron-based email digest delivery (SMTP + crontab schedule) |
| Agent alerting | ✅ Config-based alert rules with YAML persistence, check & dispatch via DeliveryChannel |
| Obsidian wiki links | ✅ `[[wiki links]]` in KB Markdown files |
| CEFR classification | ✅ LLM-based EN/ZH/JA (language-learning domain) |
| Email sending | ✅ SMTP sender (digest delivery) |
| Multi-channel delivery | ✅ 13 channels: SMTP, Webhook, REST API, File Export, Discord, Telegram, WeChat Work, WeChat OA, DingTalk, FeiShu, RSS, Social Publish, Push. Email as fallback. |
| End user lifecycle | ✅ Profile + Subscription CRUD. State machine: trial→active→suspended→cancelled. |
| Delivery reliability | ✅ Per-subscription DeliveryLog with SLA tracking, retry chain, fallback channels. |
| End user portal | 🟡 CLI-based self-service: preferences (untyped JSON) + history; REST API portal surfaces typed preferences (content_preference, QuietHours, identity_anchor) via merge with legacy; no typed preference editor or product archive in portal CLI |
| Immutable audit log | ✅ Append-only audit log for all operations. MCP + CLI query with full filters. |
| Structured pipeline logging | ✅ JSON structured logging per pipeline event with daily rotation. |
| Per-item traceability | ✅ UUID trace_id from collection through delivery. CLI trace command. |
| Cost metering | ✅ LLM tokens, storage, API calls per domain/per user. Append-only cost log. |
| Cost allocation | ✅ Pro-rata, usage-based, and direct allocation strategies. |
| Cost dashboard | ✅ CLI + MCP dashboard with daily trends, top models, top sources. |
| Budget alerts | ✅ Threshold-based alerts with auto-remediation actions. |
| Source ToS compliance | ✅ Source classification (Open/Licensed/Restricted/Sensitive) with per-tier output controls, G1 compliance gate, D2 delivery gate, and attribution templates |
| Data deletion & retention | ✅ Soft-delete, restore, GDPR export, 30-day auto-cleanup, tier-based retention. |
| Per-domain TTL | ✅ Configurable freshness per domain: medical 180d, AI 30d, financial 7d, general 90d. |
| Versioned re-collection | ✅ Version tracking with structured diff between versions. |
| Stale content handling | ✅ Search demotion, digest exclusion, never deleted. |
| Domain decay metrics | ✅ Staleness ratio, avg TTL, decay grade (Green/Yellow/Red). |
| Cross-collection dedup & merge | 🟡 URL dedup + cross-source similarity (find_similar_items); no LLM-assisted merge (merge_items in quality.py has only simple/title_first strategies) |
| Enhanced diagnostics | ✅ `doctor --verbose` with health score, error rates, latency p95/p99. |
| Prometheus metrics | ✅ `http://localhost:8741/metrics` endpoint (configurable). |
| Multi-user foundation | 🟡 Advisory user_id fields only (MultiUserConfig enabled=False); no auth/teams/RBAC |
| Export | ✅ Markdown, JSON, SQLite, PDF, CSV, GraphML |
| Schema versioning | ✅ DB schema version markers in SQLite |
| Subscription tiers | ✅ Free/Premium/Enterprise tiers with per-tier channels, domains, products, platform limits |
| Access control | ✅ `check_access()` fast path — free always allowed, premium/enterprise require active paid subscription (G15) |
| Consumption tracking | 🟡 `ConsumptionEvent` auto-record on delivery (SQLite store) exists; no consumption feedback loop |
| Automated notifications | 🟡 Trial-ending reminders + content-ready notifications; no unified notification bus (F63) |
| Channel health monitoring | 🟡 `get_channel_health` MCP tool exists (health + latency); no auto-suspend of unhealthy channels |
| Cron health monitoring | 🟡 Heartbeat tracking + missed-schedule detection (cli/cron.py); no backfill/execution history |
| SQLite backup | ✅ `make backup` + `scripts/backup-db.sh` / `scripts/restore-db.sh` (keeps last 7 backups) |
| Job state persistence | ✅ SQLite-backed collection/processing job state survives restarts |
| Agent callback persistence | ✅ SQLite-backed agent callback registration survives restarts |
| Cross-domain search | ✅ search_knowledge_base searches all active domains when domain omitted |
| Domain-less collection | ✅ collect_sources collects from all domains when domain omitted |
| Hard-delete purge | ✅ soft_delete_entry purge flag for permanent removal |
| Fine-grained process control | ✅ process_collection check_factual/check_translation flags |
| Batch CEFR | ✅ cefr_batch MCP tool for multi-text classification |
| Audit log MCP | ✅ query_audit_log MCP tool for programmatic audit access |
| Knowledge graph export | ✅ knowledge_graph_export MCP tool |
| RSS feed MCP | ✅ get_feeds MCP tool with RSS XML format |
| Cache cleanup | ✅ clean_cache MCP tool |
| Topic grouping | ✅ topic_group_add/topic_group_remove MCP tools |
| Email config MCP | ✅ email_config MCP tool |
| Cost dashboard MCP | ✅ cost_dashboard MCP tool |
| Cost allocation MCP | ✅ cost_allocation MCP tool |
| Demo domains | ✅ medical-research, ai-commercial, financial-intelligence, tech-ai-developer, language-learning, online-video, financial-news, online-education, legal-compliance, general-news, gaming, b2b, retail |
| Delivery schedules | ✅ add_delivery_schedule, list_delivery_schedules, remove_delivery_schedule MCP tools, cron-integrated |
| Validation scenarios | ✅ 124 scenarios (65 functional + 59 regression in `scenarios/regression/`, `regression: true` key, recursive-glob auto-load) |
| Validation execution | ✅ Per-step `timeout_seconds`; per-step `recovery_steps` + partial-pass (`min_passing`/`pass_ratio`); per-step trace (step_index/duration/arguments/trace_id + llm_meta); root-cause report (`## Blockers` / `## Per-step trace` / `## Regression failures`) |
| Regression flywheel | ✅ `scenarios/regression/` (59 regression scenarios) + `coverage_audit.py` "Regression scenarios: N" metric + `.github/ISSUE_TEMPLATE/bug_report.md` mandatory 回归场景 field |
| Validation delivery | ✅ `scripts/validation_delivery.py` builds 01-RAW/02-PROCESSED/03-KB/04-MATRIX/06-REJECTED + validation-report.md + manifest.json (per-file authenticity + D1-D3 gates + UX metrics UX_OK/completion_rate ≥ 0.8) |
| End-user coverage matrix (E8) | ✅ `scripts/coverage_matrix.py` + `docs/dev/specs/end-user-matrix.yaml`; surfaced as 04-MATRIX + coverage-gaps.json |
| End-user journey validation | ✅ `enduser-journey.yaml` scenario + UX metrics; error-boundary asserts `actionable` field |
| LLM timeout + parallel processing | ✅ `LLMConfig.timeout` (default 120.0) threaded through LLM calls; `AUTOINFO_PROCESS_WORKERS` ThreadPoolExecutor (default 5, env-clamped cap 16, probe-gated); post-extraction gates G3/G4/G5/CEFR concurrent per item (`AUTOINFO_SUBTASK_CAP` default 4); CEFR outside `_STORAGE_LOCK`; MCP `asyncio.to_thread` offload (14 sync LLM handlers) |
| LLM fallback chain | ✅ Shared `llm.call_with_fallback` — every LLM call site (extraction + 17 standalone) walks `[primary] + config.llm.fallback` (actual: `mimo-v2.5` same-gateway, empty `provider`/`api_key` inherit primary); first successful model wins; per-provider shared rate limiting (`AUTOINFO_LLM_MAX_CONCURRENCY`, default 4) + jittered 429/5xx backoff on every chain entry and all fan-out paths |
| Dead-source detection | ✅ Semantic Scholar 429 → `SourceFailure` (fail-fast); arXiv rss/bio → rss/q-bio fix |
| CLI module entry | ✅ `python -m autoinfo.cli` runs the same Typer app; `collect` live per-source progress printer |
| Test suite | ✅ ~4345 tests collected (incl. validation wave E1-E9 scenarios + regression suite + #141-#164 regression guards + kb-curation wave + hermetic config-seam fixes + llm-concurrency wave + baseline-aware coverage-gate tests + security-assertion group; order-dependency fixes landed 2026-08-12) |

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Initialize with demo domain
autoinfo init --demo medical-research

# Configure LLM key
export AUTOINFO_LLM_API_KEY="sk-..."
# See docs/dev/required-api-keys.md for the full list of API keys and environment variables

# Collect, process, and search
autoinfo collect --domain medical-research --topic "IVF breakthroughs" --limit 5
autoinfo process --domain medical-research
autoinfo kb search --query "embryo" --domain medical-research

# Generate output
autoinfo output digest --domain medical-research --period weekly
autoinfo output export --domain medical-research --format json
```

## TLDR — Agent-User / Agent-Tester (5 Seconds)

AutoInfo is agent-first: every capability is an MCP tool. Connect your agent
(Cursor / OpenCode / Claude Desktop configs are committed in-repo; or run
`python -m autoinfo.mcp.server` manually), then:

1. **Health** — `health_check()` → `{status, version, tools_count}`
2. **Discover** — `list_domains()` → `get_domain_schema("<domain>")` → `list_available_models()`
3. **Validate** — `list_validation_scenarios()` (124 scenarios: 65 functional + 59 regression) → `run_validation_scenario(scenario="system-health")`

Validation is the fastest way to prove the system works: each scenario makes
real MCP / CLI / REST calls and asserts on the `{success, data}` envelope.
Env-gated steps report `unconfigured` (never silently skipped); `llm_assert`
steps run a real model call. Every step carries a per-step execution trace
(step_index/duration/arguments/trace_id + llm_meta), and failing runs surface
a root-cause report (`## Blockers` / `## Per-step trace` / `## Regression
failures`). No LLM key yet? The 16 LLM-required tools return
`LLM_NOT_CONFIGURED` — set `AUTOINFO_LLM_API_KEY` or call `configure_llm()`.

Non-MCP testers can smoke-test over REST instead:

```bash
curl http://localhost:8741/health
curl http://localhost:8741/api/v1/entries?limit=5
```

## Run the AutoInfo MCP server

AutoInfo ships an MCP server (`python -m autoinfo.mcp.server`) that exposes
146 tools over stdio. Editor configs are already committed for Cursor
(`.cursor/mcp.json`), OpenCode (`.opencode/mcp.json`), and Claude Desktop
(`.claude/claude_desktop_config.json`). They all run
`python -m autoinfo.mcp.server` and pass `AUTOINFO_LLM_API_KEY` through from
your environment.

### 1. Install the package

The configs invoke bare `python`, so the `autoinfo` package must be
importable by whatever interpreter `python` resolves to on your PATH. From
the repo root:

```bash
pip install -e .
```

If you work inside a virtualenv, install into that interpreter instead:

```bash
.venv/bin/pip install -e .
# or, with uv
uv pip install -e .
```

Then verify the module resolves before wiring up the editor:

```bash
python -c "import autoinfo; print(autoinfo.__file__)"
```

If `python -m autoinfo.mcp.server` later fails with
`No module named autoinfo`, the package was installed into a different
interpreter than the one `python` points at. Activate the right environment
or adjust PATH so the editor finds the same `python`.

### 2. Provide the LLM API key

AutoInfo reads its LLM key from the `AUTOINFO_LLM_API_KEY` environment
variable. Export it in the shell that launches your editor, so the editor
process inherits it (not just your terminal session):

```bash
export AUTOINFO_LLM_API_KEY="sk-..."
```

AutoInfo does not load `.env` files automatically. The key has to be
present in the environment of whatever process spawns the MCP server. For
the full catalog of environment variables each source and feature expects,
see [`docs/dev/required-api-keys.md`](docs/dev/required-api-keys.md).

### 3. What the `${...}` placeholder in the configs means

Both `.cursor/mcp.json` and `.opencode/mcp.json` contain:

```json
"env": { "AUTOINFO_LLM_API_KEY": "${AUTOINFO_LLM_API_KEY}" }
```

The `${AUTOINFO_LLM_API_KEY}` is a placeholder that the editor (Cursor,
OpenCode, or Claude Desktop) interpolates from its own process environment
when it spawns the MCP server. AutoInfo never sees or expands this token
itself, and it is not shell variable expansion done by `python`. If the
variable is unset in the editor's environment, the server starts with an
empty key and every LLM-required tool returns `LLM_NOT_CONFIGURED` until
you fix it.

The same lookup rule applies to `"command": "python"`: the editor runs
whatever `python` is on PATH at launch time. If you installed `autoinfo`
into a virtualenv, make sure that virtualenv's `python` is the one the
editor finds. Either activate the virtualenv before launching the editor,
or change the config to point at the absolute interpreter path (for
example `/home/you/.venv/bin/python`).

## Architecture

```
Sources (RSS/API/Web)
        │
        ▼
   autoinfo collect ───→ collections/ (raw JSON cache)
        │
        ▼
   autoinfo process
        │
   ├── LLMExtractor (custom fields, entities, G4)
   ├── Quality Gates (G1-G5)
   └── KBStore (4-tier)
        │
        ▼
   knowledge/{Raw|Draft|Wiki}/ ───→ Markdown + SQLite + FTS5 + vector embeddings
        │
        ├── Product Pipeline (RAW + PROCESSED)
        │     ├── RAW feeds (API, webhook, bulk export)
        │     └── PROCESSED (digests, reports, alerts, tutorials)
        │
        ├── Delivery Channels (SMTP, webhook, REST API, export)
        ├── autoinfo summaries list | status | kb search
        ├── autoinfo output digest | report | tutorial | export
        ├── REST API (FastAPI, port 8741)
         ├── autoinfo audit | trace | cost | enduser | portal  # v1.6 new
         └── MCP server (146 tools)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python ≥ 3.11 |
| CLI | typer (28 command groups) |
| REST API | FastAPI + uvicorn (port 8741) |
| MCP server | mcp (Model Context Protocol) — 146 tools over stdio |
| LLM layer | LiteLLM — multi-provider (OpenRouter, OpenAI-compatible, Ollama, Azure) via BYOK |
| Storage | SQLite + FTS5 (keyword search) + sqlite-vec (vector embeddings) |
| KB files | Markdown + python-frontmatter, git-versioned |
| Collection | httpx, feedparser (RSS), trafilatura + lxml + beautifulsoup4 (web), Playwright (browser, optional), PyMuPDF (PDF, optional) |
| Output & templates | Jinja2, weasyprint (PDF, optional), edge-tts (TTS audio, optional), Reveal.js (presentations, CDN) |
| Web UI | Bootstrap 5 (built-in dashboard) |
| Billing | Stripe |
| Scheduling | croniter + crond |
| Config | PyYAML |
| Language detection | langdetect |
| Rate limiting | pyrate-limiter |
| Utilities | python-dateutil |
| Testing | pytest + pytest-asyncio + pytest-vcr + pytest-timeout |
| Lint & type checking | ruff + mypy (strict) |
| Secret scanning | gitleaks v8.18.4 pre-commit hook + local `no-credential-url` guard (blocks `https://token@github.com` / `ghp_`/`github_pat_` in staged files) + `gitleaks-action` in CI |

Optional extras: `pip install "autoinfo[web]"` (Playwright),
`"autoinfo[pdf]"` (PyMuPDF + weasyprint), `"autoinfo[tts]"` (edge-tts), or
`"autoinfo[all]"` for everything.

## CLI Commands (28 groups)

```bash
autoinfo init --name <project>      # Initialize project
autoinfo init --demo <domain>       # Initialize with demo domain
autoinfo doctor                      # System health check
autoinfo collect --domain <d> ...   # Collect from sources
autoinfo process --domain <d> ...   # LLM extraction + storage
autoinfo status                      # Collection stats
autoinfo summaries list|flag|show   # Browse summaries
autoinfo sources add|list|remove|test  # Source management
autoinfo topics add|list|remove     # Topic management
autoinfo topic-group add|remove     # Topic grouping (MCP topic_group_add/remove parity)
autoinfo domain add|list|show|remove|activate|deactivate|import  # Domain management (import --from-demo supports all 13 demo domains)
autoinfo audit query                # Query immutable audit log
autoinfo kb search|create-draft|promote|reject-draft|list-tiers|reindex
autoinfo output digest|report|tutorial|presentation|export|translate|list-templates  # digest/report accept --product; report accepts --type --domains
autoinfo cron run|list-schedules|add-schedule|remove-schedule|install|uninstall|health  # health = heartbeat + missed-schedule detection
autoinfo cefr classify|batch        # CEFR text classification
autoinfo email send-digest --user-id <id>|config  # SMTP email sending (--user-id for content_preference filtering)
autoinfo keywords list|approve|reject|suggest  # Keyword management
autoinfo knowledge graph            # Knowledge graph export
autoinfo clean                       # Clean temporary artifacts
autoinfo cost dashboard|allocation  # Cost tracking & allocation
autoinfo billing summary  # Billing & usage overview
autoinfo enduser create|get|update|delete|list  # End-user profile management
autoinfo portal preferences|history # End-user self-service portal
autoinfo trace <trace_id>           # Per-item pipeline trace
autoinfo import-kb --file <f>       # Import entries into 01-Raw (MCP import_kb parity)
autoinfo query-collected <query>    # Q&A over collected content (MCP query_collected parity)
autoinfo alert-rules add|list|remove  # Alert rule management (MCP parity)
autoinfo agent-callback add|list|remove  # Agent push callbacks (MCP parity)
```

## MCP Tools (146)

| Category | Tools |
|----------|-------|
| **System** | health_check, diagnose_system, get_config, list_available_models, get_tool_count, configure_llm, test_llm_connection |
| **Discovery** | list_domains, list_available_platforms, get_domain_schema, get_effective_llm_config, list_output_templates, activate_domain, deactivate_domain, get_domain_config |
| **Domain** | add_domain, remove_domain |
| **Source** | add_source (idempotent), add_sources (batch), remove_source, test_source (with extract_fields + tier warnings), list_sources, get_source_health, get_feeds |
| **Topic** | add_topic, remove_topic, list_topics, topic_group_add, topic_group_remove, list_keywords, approve_keyword, reject_keyword, suggest_keywords |
| **Collection** | collect_sources (with dry_run, domain-less), get_collection_progress, get_collection_status, process_collection (with batch, check_factual, check_translation), get_processing_progress, batch_run, clean_cache |
| **KB** | search_knowledge_base (hybrid, cross-domain, faceted `filter_custom_fields` on custom_fields JSON), get_kb_entry, list_summaries, get_summary, create_kb_entry, create_kb_draft (from Raw only), reject_kb_draft, promote_kb_draft (agent promotion Draft→Wiki), list_kb_tier (01-Raw/02-Draft/03-Wiki), reindex_kb, flag_for_knowledge_base |
| **KB Relations** | link_items, get_item_relations |
| **KB Versioning** | get_entry_history, restore_entry_version |
| **KB Monitor** | get_collection_stats, get_collection_diff |
| **KB Graph** | query_knowledge_graph, knowledge_graph_export |
| **Output** | list_output_templates, generate_digest (md/html/json/agent, `product=` premium-briefing/magazine-digest/...), generate_report (md/json/html/audio/agent/video/epub/audiobook, `product=` premium-briefing/enterprise-briefing/...), generate_cross_domain_report, generate_tutorial (md/agent), generate_presentation (md/agent), localize_content, export_kb (md/json/sqlite/pdf/csv/graphml/agent/bundle) |
| **Export/Import** | export_kb, import_kb |
| **CEFR** | classify_cefr (EN/ZH/JA), cefr_batch |
| **Keywords** | approve_keyword, reject_keyword, suggest_keywords |
| **Email** | send_email_digest, email_config |
| **Audit** | query_audit_log |
| **Q&A** | query_collected (FTS5 + LLM synthesis with source citations) |
| **Custom Extraction** | extract_fields, get_extraction |
| **Cron** | list_schedules, add_schedule, remove_schedule, run_schedules, get_schedule_status |
| **Source Health** | get_source_health, rate_item |
| **Projects** | init_project, list_projects, get_project_assets, archive_project |
| **Monitor** | list_active_collections, list_active_deliveries, get_channel_health (health + latency for all 13 delivery channels) |
| **Webhooks** | set_domain_webhooks, get_domain_webhooks |
| **Quality Gate Config** | get_gate_config, set_gate_config |
| **Product** | list_products, get_product |
| **Alert Rules** | add_alert_rule, get_alert_rules, remove_alert_rule |
| **End User** | send_to_enduser, get_enduser_history, get_enduser_products, query_delivery_log, get_delivery_log, activate_trial, check_trial_expiry, update_preferences, get_preferences, get_subscription_status |
| **Cost** | get_billing_summary, get_budget_thresholds, set_budget_thresholds, create_checkout_session, get_enduser_usage, get_enduser_invoice, cost_dashboard, cost_allocation |
| **Data Privacy** | soft_delete_entry (with purge flag), restore_entry, export_user_data, delete_user_data |
| **Knowledge Lifecycle** | compare_versions, find_similar_items, merge_items, get_domain_decay, mark_stale, calculate_freshness_score, recommend_content, simplify_content |
| **Observability** | trace_item, get_metrics, get_prometheus_metrics, diagnose_system |
| **Agent Callbacks** | set_agent_callback, list_agent_callbacks, remove_agent_callback |
| **Delivery Schedule** | add_delivery_schedule, list_delivery_schedules, remove_delivery_schedule |
| **Validation** | list_validation_scenarios, run_validation_scenario |

## Demo Domains

| Domain | Sources | Priority | Status |
|--------|---------|----------|--------|
| **Medical Research** | PubMed (REST API), Semantic Scholar, arXiv, CrossRef, DBLP, OpenAlex, USPTO | 🔴 P0 | ✅ Implemented (7 curated sources) |
| **AI Commercial Intelligence** | TechCrunch RSS, ProductHunt RSS, Crunchbase, 36kr | 🟡 P1 | ✅ Implemented (4 curated sources) |
| **Financial/Business Intelligence** | Alpha Vantage, FRED, Finnhub, SEC EDGAR, Twelve Data, World Bank Data, Quandl/Nasdaq Data Link, CNBC Investing, TheStreet, MarketWatch Markets (DJ) | 🟡 P1 | ✅ Implemented (10 curated sources) |
| **Tech/AI/Developer** | GitHub Trending, HackerNews API, Substack RSS (tech), Stack Exchange, ProductHunt, Reddit, Spotify AI Podcasts, Bilibili, HN Algolia API, GitHub Blog | 🟡 P1 | ✅ Implemented (10 curated sources) |
| **Language Learning** | Project Gutenberg, news-in-levels, commonlit | 🟢 P2 | ✅ Implemented (3 curated sources) |
| **Online Video / OTT** | Variety, Hollywood Reporter, Netflix Tech Blog, Pitchfork, Billboard, Bilibili (popular), TheWrap | 🟡 P1 | ✅ Implemented (7 curated sources; YouTube/Apple Music GFW-blocked/dead, disabled) |
| **Financial News** | CNBC, Seeking Alpha, Microsoft Newsroom, WSJ RSS, MW RSS | 🟡 P1 | ✅ Implemented (5 curated sources; 5 dead/GFW feeds disabled) |
| **Online Education** | Coursera Blog, Open Culture, Coursera, 万方 (Wanfang) | 🟢 P2 | ✅ Implemented (4 curated sources; EdSurge/Class Central/Khan/dedao/ncpssd GFW-blocked/dead, disabled) |
| **Legal Compliance** | SCOTUSblog, Oyez, GDPR.eu | 🟢 P2 | ✅ Implemented (3 curated sources; IAPP/Law.com 404, disabled) |
| **General News** | Guardian Open Platform, AP API, 知乎日报, Wired, France24, NPR, Ars Technica, The Verge, Engadget, SpaceNews | 🟢 P2 | ✅ Implemented (10 curated sources; GDELT/Google News/NYT/Medium/Atlantic/Time/Mastodon/Bluesky GFW-blocked or throttled, disabled) |
| **Gaming** | IGN RSS, GamesIndustry.biz, 机核网 gcores, GameSpot, PC Gamer, Eurogamer | 🟢 P2 | ✅ Implemented (6 curated sources; Polygon/游研社-via-GoogleNews disabled) |
| **B2B / Enterprise** | ProductHunt, TechCrunch, Crunchbase News, HackerNews, SaaStr | 🟢 P2 | ✅ Implemented (5 curated sources; a16z feed 404, disabled) |
| **Retail / E-commerce** | Retail Dive, Modern Retail, Shopify News, Digiday | 🟢 P2 | ✅ Implemented (4 curated sources; 亿邦-via-GoogleNews disabled) |

## Development

```bash
pip install -e ".[dev]"
make test        # pytest -v
make lint        # ruff check + mypy
```

## Known Limitations

the #342 wave grew it to 108 (64 functional + 44 regression); the #332-B wave grew it to 109 (64 functional + 45 regression); the #325 wave grew it to 110 (64 functional + 46 regression); the #319 wave grew it to 111 (64 functional + 47 regression); the #348 wave grew it to 112 (64 functional + 48 regression); the #351/#357 security-assertions wave grew it to 116 (65 functional + 51 regression); the #9-reopened theme-blocklist fix grew it to 117 (65 functional + 52 regression); the #14-#18 output-quality wave grew it to 124 (65 functional + 59 regression). The following items remain explicitly deferred:

| Feature | Status | Notes |
|---------|--------|-------|
| Config override system (~/.autoinfo/overrides/) | 📋 Planned | Per-project config layering |
| Multi-user / collaboration (auth, teams) | 📋 Planned | user_id fields in place; full auth v2 |

> See `docs/dev/founder-expectations.md` §14 for the full deferred-items catalog.
> Cross-dimensional catalog (keystone product matrix): `docs/dev/cross-dimensional-catalog.md` (42 cells, 5 gap types across A1-A7 Pipeline × B1/B2/B3 Users).
> Some high-value sources (Bloomberg, Reuters Eikon, WSJ) remain blocked by cost/policy — see `docs/known-limitations/blocked-sources.md`.

## License

MIT
