# MCP Tool Inventory

> Extracted from `founder-expectations.md §12.11`. References: all F-numbers — every feature has a corresponding MCP tool surface.
> **Keystone matrix:** [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) — MCP tools are the B2 (Direct Agent) interface to every A1-A7 pipeline capability. The CD catalog's B2 row shows which stages have full tool coverage and which have gaps.

**146 tools across 35 categories**. Phase 4 adds 1 new category (Delivery Schedule) and 4 new tools: `generate_cross_domain_report`, `add_delivery_schedule`, `list_delivery_schedules`, `remove_delivery_schedule`. v1.8.1 added `configure_llm` to the System category for agent-oriented BYOK setup, plus `simplify_content` (Simplification category, E14 CEFR-parameterized content simplification). `test_llm_connection` (System category) probes LLM connectivity through the configured fallback chain. v1.8.0 added 12 tools + 1 new category (Audit): `get_tool_count`, `topic_group_add`, `topic_group_remove`, `clean_cache`, `create_kb_entry`, `knowledge_graph_export`, `cefr_batch`, `email_config`, `get_feeds`, `cost_dashboard`, `cost_allocation`, `query_audit_log`. v1.5 added 3 categories (Quality Gate Config, Product, Alert Rules). v1.6 adds 5 categories (End User, Cost, Data Privacy, Knowledge Lifecycle, Observability). v1.6.2 adds 12 tools: `reindex_kb`, `find_similar_items`, `get_budget_thresholds`, `set_budget_thresholds`, `list_active_deliveries`, `get_delivery_log`, `get_billing_summary`, `get_enduser_history`, `get_enduser_products`, `get_enduser_usage`, `get_enduser_invoice`, `query_delivery_log`.

---

| Category | Tools |
|----------|-------|
| **System** | `health_check`, `diagnose_system`, `get_config`, `list_available_models`, `get_tool_count`, `configure_llm`, `test_llm_connection` |
| **Discovery** | `list_domains`, `list_available_platforms`, `get_domain_schema`, `get_effective_llm_config`, `list_output_templates`, `activate_domain`, `deactivate_domain`, `get_domain_config` |
| **Domain** | `add_domain`, `remove_domain` |
| **Source** | `add_source` (idempotent), `add_sources` (batch), `remove_source`, `test_source` (with extract_fields + tier warnings), `list_sources`, `get_source_health`, `get_feeds` |
| **Topic** | `add_topic`, `remove_topic`, `list_topics`, `list_keywords`, `approve_keyword`, `reject_keyword`, `suggest_keywords`, `topic_group_add`, `topic_group_remove` |
| **Collection** | `collect_sources` (with dry_run, domain-less), `get_collection_progress`, `get_collection_status`, `process_collection` (with batch, check_factual, check_translation), `get_processing_progress`, `batch_run`, `clean_cache` |
| **KB** | `search_knowledge_base` (hybrid: FTS5+vector, paginated; `filter_custom_fields` faceted filter — dict of dot-paths into `custom_fields`, `""` = presence, non-empty = exact match, path-injection validated), `get_kb_entry`, `list_summaries`, `get_summary`, `create_kb_entry` (direct Raw-tier with source metadata), `create_kb_draft` (from Raw only), `reject_kb_draft`, `promote_kb_draft` (agent promotion Draft→Wiki), `demote_kb_wiki` (director-only), `force_promote` (director-only), `promote_pending`, `list_kb_tier`, `reindex_kb`, `flag_for_knowledge_base` |
| **KB Relations** | `link_items`, `get_item_relations` |
| **KB Versioning** | `get_entry_history`, `restore_entry_version` |
| **KB Monitor** | `get_collection_stats`, `get_collection_diff` |
| **KB Graph** | `query_knowledge_graph`, `knowledge_graph_export` |
| **Output** | `list_output_templates`, `generate_digest` (with `product` param — selects a differentiated product template, e.g. `magazine-digest`), `generate_report` (Markdown/JSON/HTML/Audio/Agent/Video/EPUB/Audiobook; `product` param for `premium-briefing` / `enterprise-briefing`; `video` renders via HyperFrames HTML+GSAP→MP4), `generate_cross_domain_report`, `generate_tutorial`, `generate_presentation`, `localize_content` |
| **Export/Import** | `export_kb`, `import_kb` |
| **CEFR** | `classify_cefr` (EN/ZH/JA LLM-based classification), `cefr_batch` (batch classification) |
| **Keywords** | `approve_keyword`, `reject_keyword`, `suggest_keywords` |
| **Email** | `send_email_digest`, `email_config` |
| **Q&A** | `query_collected` (FTS5 + LLM synthesis with source citations) |
| **Custom Extraction** | `extract_fields`, `get_extraction` |
| **Cron** | `list_schedules`, `add_schedule`, `remove_schedule`, `run_schedules`, `get_schedule_status` |
| **Source Health** | `get_source_health`, `rate_item`, `get_feeds` (RSS feeds, supports format="rss") |
| **Projects** | `init_project`, `list_projects`, `get_project_assets`, `archive_project` |
| **Monitor** | `list_active_collections`, `list_active_deliveries`, `get_channel_health` |
| **Webhooks** | `set_domain_webhooks`, `get_domain_webhooks` |
| **Quality Gate Config** | `get_gate_config`, `set_gate_config` |
| **Product** | `list_products`, `get_product` |
| **Alert Rules** | `add_alert_rule`, `get_alert_rules`, `remove_alert_rule` |
| **End User** | `send_to_enduser`, `get_enduser_history`, `get_enduser_products`, `query_delivery_log`, `get_delivery_log`, `activate_trial`, `check_trial_expiry`, `update_preferences`, `get_preferences`, `get_subscription_status`, `enduser_create`, `enduser_get`, `enduser_update`, `enduser_delete`, `enduser_list` |
| **Cost** | `get_billing_summary`, `get_budget_thresholds`, `set_budget_thresholds`, `create_checkout_session`, `get_enduser_usage`, `get_enduser_invoice`, `cost_dashboard`, `cost_allocation` |
| **Data Privacy** | `soft_delete_entry` (with purge flag), `restore_entry`, `export_user_data`, `delete_user_data` |
| **Knowledge Lifecycle** | `compare_versions`, `find_similar_items`, `merge_items`, `get_domain_decay`, `mark_stale`, `calculate_freshness_score`, `recommend_content`, `simplify_content` |
| **Observability** | `trace_item`, `get_metrics`, `get_prometheus_metrics`, `diagnose_system` |
| **Audit** | `query_audit_log` (immutable audit log query) |
| **Agent Callbacks** | `set_agent_callback`, `list_agent_callbacks`, `remove_agent_callback` |
| **Delivery Schedule** | `add_delivery_schedule`, `list_delivery_schedules`, `remove_delivery_schedule` |
| **Validation** | `list_validation_scenarios` (list available Agent-native scenarios; 110 built-in across all MCP categories, CLI, and REST API surfaces — 64 functional + 46 regression), `run_validation_scenario` (execute a scenario in-process: each step makes a real MCP/CLI/HTTP call and asserts on the `{success, data}` envelope; `llm_assert` steps run a real model call; env-gated steps report `unconfigured` when BYOK keys are missing — parameters: scenario (required), steps (optional, 1-based indices)). Scenarios in `src/autoinfo/mcp/scenarios/`; authoring contract in `docs/dev/validation-scenario-contract.md`. |

All tools accept `domain` parameter where applicable. Pagination (`limit`/`offset`/`total_count`) on all list/search tools.

## Collector Handlers (30 total)

`list_available_platforms` advertises all 29 `VALID_SOURCE_TYPES`. The 30 collector handlers (in `src/autoinfo/collectors/`) cover:

| Handler | Source Type(s) | Notes |
|---------|---------------|-------|
| `pubmed.py` | `api` (name contains "pubmed") | PubMed E-utilities REST API |
| `rss.py` | `rss` | Generic RSS/Atom feeds |
| `web.py` | `web` | trafilatura-based web scraping |
| `web_playwright.py` | `web` (Playwright) | JS-rendered pages |
| `webhook.py` | `webhook` | Inbound HMAC webhook (no `_build_handler` dispatch) |
| `email_imap.py` | `email` | IMAP email ingestion |
| `pdf.py` | `pdf` | PyMuPDF PDF parsing |
| `http_api.py` | `http_api` | Generic REST API (Alpha Vantage, FRED, SEC EDGAR, etc.) |
| `semantic_scholar.py` | `semantic_scholar` | Semantic Scholar API |
| `dblp.py` | `dblp` | DBLP computer science bibliography |
| `openalex.py` | `openalex` | OpenAlex scholarly works |
| `uspto.py` | `uspto` | USPTO patent search |
| `nyt.py` | `nyt` | NYT API |
| `reddit.py` | `reddit` | Reddit posts |
| `spotify.py` | `spotify` | Spotify podcasts |
| `youtube.py` | `youtube` | YouTube videos |
| `bilibili.py` | `bilibili` | Bilibili videos |
| `apple_podcasts.py` | `apple_podcasts` | Apple Podcasts (iTunes Search API) |
| `ap_api.py` | `ap_api` | Paid AP API |
| `reuters_mcp.py` | `reuters_mcp` | Reuters MCP |
| `quandl.py` | `quandl` | Quandl/Nasdaq Data Link |
| `yahoo_finance.py` | `yahoo_finance` | Yahoo Finance |
| `ssrn.py` | `ssrn` | SSRN working papers (HTML search, no REST API) — **v1.8.1** |
| `gdelt.py` | `gdelt` | GDELT DOC 2.0 news events — **v1.8.1** |
| `hackernews.py` | `hackernews` | Hacker News official Firebase API (two-step fetch) — **v1.8.2** |
| `huggingface.py` | `huggingface` / `kaggle` | HuggingFace Hub + Kaggle datasets (dual provider) — **v1.8.1** |
| `unpaywall.py` | `unpaywall` / `core` | Unpaywall + CORE OA fulltext (dual provider) — **v1.8.1** |
| `akshare.py` | `akshare` | AKShare open financial data (no key) — **M2 (2026-08-05)** |
| `sec_edgar.py` | `sec_edgar` | SEC EDGAR filings (ticker→CIK→filings, no key) — **M2 (2026-08-05)** |
| `edx_sitemap.py` | `edx_sitemap` | edX course sitemap crawl (robots.txt RFC 9309 gate, no key) — **M2 (2026-08-05)** |
