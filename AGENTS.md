# AutoInfo — Agent Guide

## What Is AutoInfo

AutoInfo is a **universal information tracking and knowledge base platform**. You configure sources and topics; AutoInfo handles collection, LLM-based structured extraction, summarization, and builds a queryable knowledge base.

**Key principle**: Domain-agnostic. The thirteen demo domains (medical-research, ai-commercial, financial-intelligence, tech-ai-developer, language-learning, online-video, financial-news, online-education, legal-compliance, general-news, gaming, b2b, retail) are configurations, not hardcoded features. Users define their own domains.

## Agent Operating Model

AutoInfo is designed **agent-first**:

```
Director-user (human) ──NL──> Agent ──MCP tools──> AutoInfo MCP Server
                                ↑                           │
                                └──── structured JSON-RPC ───┘
```

1. **You (the agent)** connect to AutoInfo's MCP server over stdio (SSE transport is future work)
2. **All capabilities** are exposed as MCP tools (145 tools across 35 categories)
3. **CLI mirrors MCP** — `--domain X --topic Y` flags map 1:1 to tool parameters
4. **Human director** communicates intent to you in natural language; you translate to tool calls
5. **Human can also use CLI directly** as a fallback, but the primary interface is through you

## Quick Start (5 Seconds)

Connect your AI agent to AutoInfo immediately:

**Cursor**: `.cursor/mcp.json` is already committed to the repo -- restart Cursor
and the `autoinfo` MCP server is ready to use.

**Claude Desktop**: Copy `.claude/claude_desktop_config.json` from this repo to
`claude_desktop_config.json` in your Claude config directory:
- **Linux**: `~/.config/Claude/claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**OpenCode**: `.opencode/mcp.json` is already committed -- OpenCode discovers it
automatically via project-level configuration.

**Manual (any platform)**:
```bash
python -m autoinfo.mcp.server
```

## Running the CLI

The CLI is the human-facing entry point — same capabilities as MCP, with
`--domain X --topic Y` flags mapping 1:1 to tool parameters. Two equivalent
invocations run the same Typer app (`src/autoinfo/cli/__init__.py`):

| Entry | Command | How it's wired |
|-------|---------|----------------|
| **Console script (primary)** | `autoinfo <cmd>` | `pip install -e .` / `make install` creates it from `pyproject.toml` `[project.scripts] autoinfo = "autoinfo.cli:app"` |
| **Module entry (equivalent)** | `python -m autoinfo.cli <cmd>` | Runs the same app via `src/autoinfo/cli/__main__.py` |

Do **not** confuse the CLI with the MCP server: `python -m autoinfo.mcp.server`
starts the MCP stdio server (agent-facing, protocol over stdio — never use it
interactively). The CLI prints human output; the MCP server speaks JSON-RPC.

First commands:

```bash
autoinfo --help                              # or: python -m autoinfo.cli --help
autoinfo init --demo medical-research        # scaffold a demo domain
autoinfo collect --domain medical-research   # fetch items (live per-source progress lines)
autoinfo process --domain medical-research   # LLM extraction + quality gates
```

## Project Structure

```
AutoInfo/
├── AGENTS.md                       # ← You are here
├── README.md                       # Project overview
├── pyproject.toml                  # Python packaging
├── Makefile                        # Build automation
├── .gitignore
├── docs/
│   ├── dev/
│   │   ├── founder-expectations.md # Index doc (simplified; full content in specs/)
│   │   ├── specs/                  # Extracted spec files (2026-07-26 restructuring)
│   │   │   ├── expectations.md     # F01-F57 expectation catalog (57 expectations, 12 phases)
│   │   │   ├── quality-gates.md    # G0-G5, D1-D3 gate catalog & configuration + testing strategy
│   │   │   ├── pipeline.md         # Collection pipeline, KB pipeline, LLM config, extraction, search, performance targets
│   │   │   ├── delivery.md         # Output generation, delivery channels, end user lifecycle
│   │   │   ├── operations.md       # Cost, data privacy, knowledge lifecycle, observability
│   │   │   ├── market-positioning.md # Priority matrix, competitive landscape, pricing, personas
│   │   │   ├── mcp-tools.md        # 145 MCP tools across 35 categories
│   │   │   ├── data-models.md      # Consolidated data model schemas
│   │   │   ├── user-lifecycle-definition.md # Foundational user type definitions (B1/B2/B3)
│   │   │   ├── multi-tenancy-auth.md    # Multi-tenancy and authorization spec
│   │   │   └── ops-runbook.md           # Operations runbook spec
│   │   ├── cross-dimensional-catalog.md # Cross-dimensional catalog — keystone product matrix (A1-A7 × B1/B2/B3, supersedes archived gap docs)
│   │   ├── archive/                  # Archived/historical docs
│   │   ├── director-user-guide.md    # Human-Agent interaction lifecycle
│   └── skills/                     # AutoInfo operator skills (for agent-users of AutoInfo)
│       ├── autoinfo-skill/SKILL.md # Operating AutoInfo via MCP tools
│       └── translator-qa-skill/    # Translation QA workflow
├── .opencode/
│   └── skills/                     # Coding agent skills (for developing AutoInfo)
├── src/
│   └── autoinfo/
│       ├── cli/                     # 28 CLI command groups
│       ├── mcp/                     # MCP server (145 tools)
│       ├── api/                     # REST API (FastAPI, port 8741)
│       ├── kb.py                    # Knowledge base pipeline (4-tier KB pipeline)
│       ├── collectors/              # 30 collector handlers (PubMed, Semantic Scholar, DBLP, OpenAlex, USPTO, NYT, Yahoo Finance, Quandl, RSS, Web, webhook, email, PDF, Reddit, Spotify, YouTube, Bilibili, Apple Podcasts, AP API, Reuters MCP, SSRN, GDELT, HuggingFace/Kaggle, Unpaywall/CORE, HackerNews, AKShare, SEC EDGAR, edX sitemap)
│       ├── llm.py                   # LLM extraction engine
│       ├── output/                   # Output generation package (digest, report, tutorial, presentation, export; formats: Markdown/HTML/JSON/PDF/Audio/Agent/EPUB/MOBI/Audiobook/Video) — __init__.py + ebook.py (B23: EPUB/MOBI/audiobook) + video.py (HyperFrames HTML+GSAP→MP4, 36+8 themes) + video_assets/ (themes + templates) + seo.py
│       ├── data/                     # Domain configs (domains/*/sources.yaml) + 8 output product templates (incl. premium-briefing.md.j2, enterprise-briefing.md.j2)
│       ├── cefr.py                  # CEFR classification (EN/ZH/JA)
│       ├── quality.py               # Quality gates G0-G5, D1-D3 delivery gates
│       ├── delivery.py              # Delivery channel abstraction (13 channels)
│       ├── delivery/scheduler.py    # Delivery schedule management (cron integration)
│       ├── alerts.py                # Alert rule CRUD, YAML persistence, check & dispatch
│       └── ...                      # email_sender, keywords, qa, etc.
```

## Architecture Rules

Hard constraints derived from `founder-expectations.md`. Violating them produces incorrect behavior.

### KB Pipeline

```
Collected Item → 01-Raw → 02-Draft → 03-Wiki
     ↑             ↑          ↑           ↑
  Auto-ingest    Sole       Agent can   Agent
                 entry      process &   promotes
                 point      create      Draft → Wiki
```

| Rule | Why |
|------|-----|
| **01-Raw is the sole entry point** for all collected content | Every collected item must have complete source provenance. No skipping. |
| **Agent cannot create Draft from outside** — only from 01-Raw | Prevents garbage entries. Raw→Draft→Wiki is sequential. |
| **Agent promotes Draft→Wiki via `promote_kb_draft`** | AutoInfo's KB is a **database** for raw/processed data production, not a human-curated knowledge base (director decision 2026-08-08). Promotion is a production step, executed by the agent with no human gate — maximum automation, agent as user. A human promote/approval step would cripple production throughput. |
| **03-Wiki is append-only** | Once promoted, entries stay. Agent cannot demote or delete Wiki entries. Deprecation (tag `status: deprecated`) only upon explicit human command. |
| **Source metadata is mandatory** | Every Raw entry must have `source_url`, `source_type`, `source_platform`. |
| **Product-analysis metadata** | Per-product analysis fields persist in entry `custom_fields["product_analysis"]` — uses the existing custom_fields metadata dict (no schema/rule change); filterable via `search_knowledge_base(filter_custom_fields=...)`. |

### Collection Pipeline

Two phases, separable in time:

```
Phase 1 — Fetch:     autoinfo collect --domain medical
  → Source handlers fetch items in parallel
  → Raw JSON cached to collections/
  → Dedup (URL → DOI → fuzzy title → semantic)
  → Collection log written

Phase 2 — Process:   autoinfo process --domain medical [--model deepseek-chat]
  → Reads cached raw items
  → LLM extraction (configurable model per task)
  → Quality gates (G1-G5)
  → Creates 01-Raw KB entries
```

### Quality Gates (Production-Grade)

Hard/soft split with retry-first, block-last philosophy. G0 (Schema Integrity) and G4 (Factual Consistency) are **hard gates** — 3× retry then block. G1-G3 and G5 are **soft gates** with configurable thresholds and actions (archive/flag/pass). 3 delivery gates (D1-D3) check product completeness, format integrity, and freshness at output time.

| Gate | Type | Priority | Action on Failure |
|------|------|----------|-------------------|
| G0: Schema integrity | 🔴 Hard | 🔴 P0 | 3× retry → block (item written to `_failed/`) |
| G1: Source authority (tier check) | 🟡 Soft | 🔴 P0 | Configurable: archive/flag/pass |
| G2: Dedup (URL + fuzzy title) | 🟡 Soft | 🔴 P0 | Configurable: archive/flag/pass |
| G3: Relevance scoring (0-100) | 🟡 Soft | 🔴 P0 | Configurable: archive/flag/pass (below threshold) |
| G4: Factual consistency | 🔴 Hard | 🟡 P1 | 3× retry with escalating context → block |
| G5: Translation accuracy | 🟡 Soft | 🟡 P1 | Configurable: archive/flag/pass |
| D1: Product completeness | 🔴 Hard | 🔴 P0 | Blocks delivery |
| D2: Format integrity | 🔴 Hard | 🔴 P0 | Blocks delivery |
| D3: Freshness | 🟡 Soft | 🟡 P1 | Configurable threshold |

## Agent Constraints (MUST NOT)

| Action | Reason |
|--------|--------|
| **Run `init_project` MCP tool** | Use `init_project` MCP tool for agent workflows instead of CLI `init`. CLI `init` remains available for humans. |
| **Do not manage raw API keys** | Use `configure_llm()` MCP tool for BYOK setup — stores env var reference (`\${AUTOINFO_LLM_API_KEY}`), never the raw key. Never store, generate, or transmit keys. |
| **Do not demote or delete Wiki entries** | 03-Wiki is append-only. Promotion Draft→Wiki is an **agent operation** (`promote_kb_draft`, no human gate); demotion/deletion are not agent operations. |
| **Do not create Draft from outside** | Draft must come from 01-Raw. |
| **Do not demote Wiki entries** | Wiki is append-only. Tag `deprecated` only upon human command. |
| **Do not delete source or domain config** | Human decides what sources/domains to remove. |
| **Do not modify `.autoinfo/config.yaml` directly** | Use MCP tools (`add_source`, `add_topic`). |
| **Do not run `autoinfo doctor`** | Use `diagnose_system()` MCP tool instead — returns structured health data. |

## Tool Discovery Guidance

145 MCP tools across 35 categories:

| Category | Key Tools |
|----------|-----------|
| **System** | `health_check`, `diagnose_system`, `get_config`, `list_available_models`, `get_tool_count`, `configure_llm` |
| **Discovery** | `list_domains`, `list_available_platforms`, `get_domain_schema`, `get_effective_llm_config`, `list_output_templates`, `activate_domain`, `deactivate_domain`, `get_domain_config` |
| **Domain** | `add_domain`, `remove_domain` |
| **Source** | `add_source` (idempotent), `add_sources` (batch), `remove_source`, `test_source`, `list_sources`, `get_source_health`, `get_feeds` |
| **Topic** | `add_topic`, `remove_topic`, `list_topics`, `list_keywords`, `approve_keyword`, `reject_keyword`, `suggest_keywords`, `topic_group_add`, `topic_group_remove` |
| **Collection** | `collect_sources` (with dry_run, domain-less), `get_collection_progress`, `get_collection_status`, `process_collection` (with batch, check_factual, check_translation), `get_processing_progress`, `batch_run`, `clean_cache` |
| **KB** | `search_knowledge_base` (hybrid, cross-domain, faceted `filter_custom_fields` on custom_fields JSON), `get_kb_entry`, `list_summaries`, `get_summary`, `create_kb_entry`, `create_kb_draft`, `reject_kb_draft`, `promote_kb_draft` (agent promotion Draft→Wiki), `list_kb_tier` (01-Raw/02-Draft/03-Wiki), `reindex_kb`, `flag_for_knowledge_base` |
| **KB Relations** | `link_items`, `get_item_relations` |
| **KB Versioning** | `get_entry_history`, `restore_entry_version` |
| **KB Monitor** | `get_collection_stats`, `get_collection_diff` |
| **KB Graph** | `query_knowledge_graph`, `knowledge_graph_export` |
| **Output** | `list_output_templates`, `generate_digest` (format=md/html/json/agent, `product=` premium-briefing/magazine-digest/...), `generate_report` (format=md/json/html/audio/agent/video/epub/audiobook, `product=` premium-briefing/enterprise-briefing/...), `generate_cross_domain_report`, `generate_tutorial` (format=md/agent), `generate_presentation` (format=md/agent), `localize_content` |
| **Delivery Schedule** | `add_delivery_schedule`, `list_delivery_schedules`, `remove_delivery_schedule` |
| **Export/Import** | `export_kb` (format=md/json/sqlite/pdf/csv/graphml/agent/bundle), `import_kb` |
| **CEFR** | `classify_cefr`, `cefr_batch` |
| **Keywords** | `approve_keyword`, `reject_keyword`, `suggest_keywords` |
| **Email** | `send_email_digest`, `email_config` |
| **Q&A** | `query_collected` |
| **Custom Extraction** | `extract_fields`, `get_extraction` |
| **Cron** | `list_schedules`, `add_schedule`, `remove_schedule`, `run_schedules`, `get_schedule_status` |
| **Source Health** | `get_source_health`, `rate_item` |
| **Projects** | `init_project`, `list_projects`, `get_project_assets`, `archive_project` |
| **Monitor** | `list_active_collections`, `list_active_deliveries`, `get_channel_health` |
| **Webhooks** | `set_domain_webhooks`, `get_domain_webhooks` |
| **Quality Gate Config** | `get_gate_config`, `set_gate_config` |
| **Product** | `list_products`, `get_product` |
| **Alert Rules** | `add_alert_rule`, `get_alert_rules`, `remove_alert_rule` |
| **End User** | `send_to_enduser`, `get_enduser_history`, `get_enduser_products`, `query_delivery_log`, `get_delivery_log`, `activate_trial`, `check_trial_expiry`, `update_preferences`, `get_preferences`, `get_subscription_status` |
| **Cost** | `get_billing_summary`, `get_budget_thresholds`, `set_budget_thresholds`, `create_checkout_session`, `get_enduser_usage`, `get_enduser_invoice`, `cost_dashboard`, `cost_allocation` |
| **Data Privacy** | `soft_delete_entry` (with purge flag), `restore_entry`, `export_user_data`, `delete_user_data` |
| **Knowledge Lifecycle** | `compare_versions`, `find_similar_items`, `merge_items`, `get_domain_decay`, `mark_stale`, `calculate_freshness_score`, `recommend_content`, `simplify_content` |
| **Observability** | `trace_item`, `get_metrics`, `get_prometheus_metrics`, `diagnose_system` |
| **Agent Callbacks** | `set_agent_callback`, `list_agent_callbacks`, `remove_agent_callback` (push delivers canonical `{event, payload, schema_version: 1, trace_id, product_id}` via durable SQLite outbox) |
| **Audit** | `query_audit_log` |
| **Validation** | `list_validation_scenarios`, `run_validation_scenario` (68 scenarios = 62 functional + 6 regression in `scenarios/regression/`; M7T52: sources-gap-closure + output-column + sources-a6-keyed; E8 wave: per-scenario timeout, recovery_steps + partial-pass, per-step trace + root-cause report, regression flywheel, enduser-journey + UX metrics; #157: requires_http env gate; #156: premium-briefing/magazine-digest/enterprise-briefing + full source coverage; output-quality-mega wave: regression-product-routing + output-agent-interaction) |

**Discovery flow**: `health_check()` → `tools/list` (MCP auto-discovery) → `list_domains()` → `get_domain_schema(domain)` → `list_available_models()` → `list_output_templates(domain)`.

**Response format**: All tools return `{success: true, data: ...}` on success and `{success: false, error: {code, message, actionable}}` on failure. `actionable` is a boolean flag; the remediation guidance itself lives in `message`. Error codes: `src/autoinfo/mcp/errors.py` (`ErrorCode` enum, 28 values). LLM-required tools return `LLM_NOT_CONFIGURED` when no key is configured. REST API uses the same envelope.

## Common Patterns

Full step-by-step worked examples live in `docs/dev/mcp-usage-examples.md`.
The table indexes every pattern; the five most-used are inlined below.

| Pattern | What it does |
|---------|--------------|
| Track a new topic | add topic → collect → process → flag to KB (see below) |
| What changed since last week | collection stats + diff |
| Check system health | `diagnose_system()` returns health_score + phase (see below) |
| Configure the LLM (BYOK) | `configure_llm()` stores env var reference (see below) |
| Create a custom domain | add_domain → add_source → add_topic → collect |
| Initialise a project | `init_project()` scaffolds + returns next_steps |
| Save an article to the KB | flag → create_kb_draft → promote_kb_draft (agent promotes Draft→Wiki, no human gate) |
| Set up and run a cron schedule | add_schedule → cron_install → run |
| Generate and send a digest email | generate_digest → send_email |
| Classify content by CEFR level | `classify_cefr(text, language)` |
| Search (hybrid / vector / faceted) | `search_knowledge_base(mode=...)` (see below) |
| Export KB to PDF | `export_kb(format="pdf")` |
| Manage keywords | list → suggest → approve/reject |
| Generate agent-native JSON | `generate_digest(format="agent")` → JSON-LD |
| Subscribe to agent push delivery | `set_agent_callback(url, events)` → receives `{event, payload, schema_version, trace_id, product_id}` |
| Generate and deliver digest email | generate_digest(html) → send_email_digest |
| Use the REST API | FastAPI on port 8741, same error envelope |
| Handle MCP error responses | read error.code → follow actionable hint (see below) |
| Generate cross-domain report | `generate_report(domains=[...])` |
| Set up a delivery schedule | `add_delivery_schedule(cron, output_type, channel)` |
| Export KB as bundle | `export_kb(format="bundle")` → ZIP |
| Generate a specialized report | `generate_report(report_type, target_audience)` |
| Generate a differentiated product briefing | `generate_report(product="premium-briefing")` / `generate_digest(product="magazine-digest")` — dedicated template + per-product synthesis fields |
| Run MCP-native validation | `list_validation_scenarios` / `run_validation_scenario` |
| Monitor long-running jobs | poll `get_collection_progress(job_id)` |

**Track a new topic**: `add_topic(domain, name, keywords)` → `collect_sources(domain, topic, dry_run=true)` → `collect_sources(...)` → `process_collection(domain)` → `list_summaries(domain, topic)` → `flag_for_knowledge_base(summary_id, tags)`.

**Check system health**: `diagnose_system()` → returns `health_score` (0-100) + `phase` (`uninitialized` / `llm_unconfigured` / `no_sources` / `ready_to_collect` / `operational`). On degraded status, inspect `phase`.

**Configure the LLM (BYOK)**: `configure_llm(api_key, provider, model)` stores an env var reference (`${AUTOINFO_LLM_API_KEY}`), never the raw key. If missing, the 17 LLM-required tools return `LLM_NOT_CONFIGURED` at dispatch. Full variable catalog: `docs/dev/required-api-keys.md`.

**Search KB**: `search_knowledge_base(domain, query, mode="hybrid")` (FTS5 + vector), `mode="vector"` (semantic only), or `mode="faceted"` with `filters={...}`; `filter_custom_fields={...}` facets on custom_fields JSON (e.g. `{"product_analysis.action_required": ""}`). Omit `domain` to search across all domains.

**Handle MCP errors**: All tools return `{success, error: {code, message, actionable}}`. Read `error.code`, follow the remediation hint in `error.message` (`actionable: true` marks that a hint exists, e.g. `DOMAIN_NOT_FOUND` says "Use `add_domain()`"). `process_collection` with no cached items returns `{status: "noop"}`, not an error.

## LLM Configuration

AutoInfo uses LiteLLM under the hood. Standard OpenAI-format providers work.

| Config | Default | Notes |
|--------|---------|-------|
| provider | openrouter | Use "openai" for OpenAI-compatible endpoints |
| model | deepseek/deepseek-chat | Any LiteLLM-supported model |
| base_url | (none) | Required for non-OpenRouter endpoints |
| api_key | ${AUTOINFO_LLM_API_KEY} | Set via env var or config |
| json_mode | False | `response_format={"type":"json_object"}` sent only when `json_mode` is True AND `reasoning_model` is False (reasoning providers reject the param). |
| reasoning_model | False | Mark the model as a reasoning model (DeepSeek R1/V4 style). When True: (1) `response_format` is always skipped, (2) chain-of-thought is disabled by default via `additional_body={"thinking":{"type":"disabled"}}` — reasoning consumes the shared `max_tokens` budget *before* content, so leaving it on truncates JSON output (finish_reason=length). Judgment gates (G4 factual, G5 translation, llm_judge, translation QA judge, validation-scenario judge) re-enable thinking with raised `max_tokens` via `disable_thinking=False`. |
| fallback | [] | Ordered `llm.fallback` list — each entry: `provider`, `model`, optional `base_url`/`api_key`. Every LLM call path (extraction, validation judge, quality gates, translation QA, output generation, keyword suggest, Q&A, CEFR) walks `[primary] + fallback` via `llm.call_with_fallback`; the first successful model wins. |

**Precedence** (highest to lowest):
1. MCP tool parameter (e.g. `init_project(llm_provider="openai")`)
2. Config file `.autoinfo/config.yaml` → `llm.provider`, `llm.model`
3. Environment variable `AUTOINFO_LLM_API_KEY`
4. Default values (openrouter/deepseek/deepseek-chat)

**Custom endpoint** (e.g. OpenCode Go, Ollama, Azure): set `provider="openai"`, `base_url` to your endpoint, `api_key` via env var, `model` to your model name.

**Fallback example** (`.autoinfo/config.yaml`):
```yaml
llm:
  provider: openai
  model: deepseek-v4-flash
  base_url: https://opencode.ai/zen/go/v1
  fallback:
    - model: mimo-v2.5
      base_url: https://opencode.ai/zen/go/v1
```

## `.omo/` Workspace

The `.omo/` directory is the **agent-orchestrator workspace** used by Sisyphus-style workflows (plans, notepads, evidence, drafts, run-continuation, scripts, `boulder.json`). It is agent runtime scratch space, not AutoInfo product data.

- Agents may **read** `.omo/` to recover orchestrator context (plans, evidence, notepads).
- Do **not** treat `.omo/` contents as KB entries, sources, or product output. Not part of the collection pipeline or 4-tier KB.
- Do **not** modify `.omo/` from AutoInfo MCP tools. It is owned by the orchestrator layer above AutoInfo.
- `.omo/` is gitignored runtime state, not a source-of-truth directory.

## Runtime Artifacts vs Source Files

AutoInfo generates runtime state at execution time. Distinguish from source:

| Path | Type | Notes |
|------|------|-------|
| `src/` | **Source** | Code, the only source of truth for behavior |
| `tests/` | **Source** | Test suite |
| `docs/` | **Source** | Documentation |
| `AGENTS.md`, `README.md`, `pyproject.toml`, `Makefile` | **Source** | Project metadata |
| `collections/` | Runtime | Raw JSON cache from `collect`, gitignored |
| `knowledge/` | Runtime | 4-tier KB pipeline output (01-Raw, 02-Draft, 03-Wiki), gitignored |
| `outputs/` | Runtime | Generated digests, reports, exports, gitignored |
| `autoinfo.db` | Runtime | SQLite KB + user + cost stores, gitignored |
| `logs/` | Runtime | Structured pipeline logs, gitignored |
| `.autoinfo/` | Runtime | Project config (`config.yaml`), gitignored — modify via MCP tools, not by hand |
| `.omo/` | Runtime | Agent-orchestrator workspace, gitignored (see above) |

Never hand-edit runtime artifacts to fix behavior — fix the source.

## Status

| Component | Status |
|-----------|--------|
| Config system | ✅ LLM task config, per-task model, fallback chains, schema versioning |
| CLI | ✅ 28 command groups (init, doctor, collect, process, status, summaries, sources, topics, topic-group, domain, audit, kb, output, cron, knowledge, cefr, email, keywords, clean, cost, billing, enduser, portal, trace, import-kb, query-collected, alert-rules, agent-callback) |
| Collection | ✅ 30 collector handlers (PubMed, Semantic Scholar, DBLP, OpenAlex, USPTO, NYT, Yahoo Finance, Quandl, RSS, Web, webhook, email, PDF, Reddit, Spotify, YouTube, Bilibili, Apple Podcasts, AP API, Reuters MCP, SSRN, GDELT, HuggingFace/Kaggle, Unpaywall/CORE, HackerNews, AKShare, SEC EDGAR, edX sitemap), scheduled via crond; `fetch_depth: fulltext` threading (unpaywall/rss/youtube/gdelt, 8000-char cap) |
| LLM extraction | ✅ Custom extraction fields, TL;DR, key points, entities, G4 factual consistency, token usage tracking |
| Translation QA pipeline | ✅ 5 lite quality gates, back-translation verification, terminology guardrails, composite scoring, translator-qa-skill |
| Quality gates | ✅ 6 hard/soft (G0-G5: G0/G4 hard, G1-G3/G5 soft) + 3 delivery gates (D1-D3) + per-domain config |
| KB pipeline | ✅ 4-tier KB pipeline (00-Inbox → 01-Raw → 02-Draft → 03-Wiki; note: 00-Inbox is scaffolded but deprecated — 01-Raw is the sole entry point), git versioning + SHA tracking |
| KB import | ✅ 4 formats (PDF, Markdown, HTML, JSON) → 01-Raw via `import_kb` MCP tool |
| Search | ✅ Hybrid (FTS5 keyword + sqlite-vec vector), faceted (7 filters + `filter_custom_fields` on custom_fields JSON) |
| Q&A | ✅ FTS5 + LLM synthesis with source citations |
| Output generation | ✅ Digest (Markdown/HTML/JSON/Agent/Audio/EPUB/Audiobook), report (Markdown/JSON/HTML/Audio/Agent/Video/EPUB/Audiobook), tutorial (Markdown), presentation (Markdown), export (Markdown/JSON/SQLite/PDF/RSS/CSV/GraphML/Agent/Bundle/Sitemap/EPUB/MOBI) (Jinja2 + LLM, Reveal.js CDN, ebooklib EPUB3 + calibre MOBI); 8 product templates incl. premium-briefing/enterprise-briefing + per-product LLM synthesis |
| Agent-native JSON output | ✅ `format="agent"` returns JSON-LD (`@type: KnowledgeDigest`) for LLM re-consumption |
| JSON-LD schemas | ✅ `docs/schemas/{knowledge-digest,knowledge-tutorial,knowledge-presentation,knowledge-base-export}-v1.json` (JSON Schema draft-07) pin `@context`/`@type` via `const`; validated by M4T35 round-trip tests |
| Audio output | ✅ TTS-rendered digest/report as MP3 (OpenAI TTS); `format="audiobook"` = chaptered MP3 + ZIP (ID3v2.3 CHAP/CTOC via mutagen) |
| Video output | ✅ HyperFrames HTML+GSAP→MP4 (`report format="video"`): TTS narration + themed scene compositions, 36+8 themes, 6 layouts with adjacent-scene diversity, scene durations from TTS length (char-ratio + 0.01s float safety); MCP `generate_report`/`generate_cross_domain_report` expose `video` |
| Translation | ✅ LLM-based source→target |
| Knowledge graph | ✅ Entity extraction + relation discovery |
| REST API | ✅ FastAPI CRUD (port 8741, /api/v1/entries, /health, /dashboard) |
| Web UI Dashboard | ✅ Bootstrap 5, collection stats, KB search, source health |
| MCP server | ✅ 145 tools across 35 categories |
| Domain management | ✅ `add_domain`/`remove_domain` MCP tools, `autoinfo domain` CLI (add/list/show/remove/activate/deactivate) |
| Webhook push | ✅ Per-item webhook notification on collection via `set_domain_webhooks`/`get_domain_webhooks` |
| Scheduled digest | ✅ Cron-based email digest delivery (SMTP + crontab schedule) |
| Agent alerting | ✅ Config-based alert rules with YAML persistence, check & dispatch via DeliveryChannel |
| Obsidian wiki links | ✅ `[[wiki links]]` in KB Markdown files |
| CEFR classification | ✅ LLM-based EN/ZH/JA (language-learning domain) |
| Email sending | ✅ SMTP sender (digest delivery) |
| Multi-channel delivery | ✅ 13 channels: smtp, webhook, rest_api, file_export, discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss, social_publish, push |
| End user lifecycle | ✅ Profile + Subscription CRUD. State machine: trial→active→suspended→cancelled |
| Delivery reliability | ✅ Per-subscription DeliveryLog with SLA tracking, retry chain |
| End user portal | 🟡 CLI-based self-service: preferences (untyped JSON) + history; REST API portal surfaces typed preferences (content_preference, QuietHours, identity_anchor) via merge with legacy; no typed preference editor or product archive in portal CLI |
| Immutable audit log | ✅ Append-only; dispatch-level MCP tool calls with whitelisted fields (actor/action/tool/resource/result_code/trace_id); read-probes (health_check, get_tool_count, list_*) excluded; GDPR-exempt (operations.md §2.1) |
| Structured pipeline logging | ✅ JSON structured logging per pipeline event |
| Per-item traceability | ✅ UUID trace_id from collection through delivery, CLI trace |
| Cost metering | ✅ LLM tokens, storage, API calls per domain/user |
| Cost allocation | ✅ Pro-rata, usage-based, direct allocation strategies |
| Cost dashboard | ✅ CLI + MCP dashboard with daily trends, top models, budgets |
| Budget alerts | ✅ Threshold-based alerts with auto-remediation |
| Source ToS compliance | ✅ Source classification tiers, per-tier output controls |
| Data deletion & retention | ✅ Soft-delete, restore, GDPR export, 30-day auto-cleanup |
| Per-domain TTL | ✅ Configurable freshness per domain with stale marking |
| Versioned re-collection | ✅ Version tracking with structured diff between versions |
| Stale content handling | ✅ Search demotion, digest exclusion, never deleted |
| Domain decay metrics | ✅ Staleness ratio, avg TTL, decay grade (Green/Yellow/Red) |
| Cross-collection dedup & merge | 🟡 URL dedup + cross-source similarity (find_similar_items); no LLM-assisted merge (merge_items in quality.py has only simple/title_first strategies) |
| Enhanced diagnostics | ✅ `doctor --verbose` with health score, error rates, latency |
| Prometheus metrics | ✅ `http://localhost:8741/metrics` endpoint (configurable) |
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
| Agent callback persistence | ✅ SQLite-backed callback registration survives restarts; pushes canonical `{event, payload, schema_version: 1, trace_id, product_id}` via durable outbox (fire-and-forget, `failed` rows requeued on restart) |
| Agent push outbox | ✅ Durable SQLite outbox (`agent_outbox` table) enqueues before delivery attempt; requeue_undelivered at process start; failed → `delivery_failures_total` metric; callers never blocked |
| Dispatch-level audit | ✅ Every MCP tool call (mutations + parameterized reads) audited at dispatch with whitelisted fields (actor/action/tool/resource/result_code/trace_id); read-probes excluded |
| Cross-domain search | ✅ search_knowledge_base searches all domains when domain omitted |
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
| Demo domains | ✅ 13 demo domains (medical-research, ai-commercial, financial-intelligence, tech-ai-developer, language-learning, online-video, financial-news, online-education, legal-compliance, general-news, gaming, b2b, retail) |
| Validation scenarios | ✅ 68 scenarios (62 functional + 6 regression in `scenarios/regression/`, REGRESSION marker, recursive-glob auto-load) |
| Validation execution | ✅ Per-step `timeout_seconds`; per-step `recovery_steps` (run after primary failure) + partial-pass (`min_passing`/`pass_ratio`); per-step trace (step_index/duration/arguments/trace_id + llm_meta model/tokens/duration); `expect.error_actionable` envelope assertion; root-cause report (`## Blockers` / `## Per-step trace` / `## Regression failures`) |
| Regression flywheel | ✅ `scenarios/regression/` (regression-collect-int-id #104, regression-llm-key-resolution #119, regression-period-enum #126, regression-report-structure #121, regression-source-301 #135, regression-product-routing) + `coverage_audit.py` "Regression scenarios: N (issues: ...)" + `.github/ISSUE_TEMPLATE/bug_report.md` mandatory 回归场景 field |
| Validation delivery | ✅ `scripts/validation_delivery.py` builds 01-RAW/02-PROCESSED/03-KB/04-MATRIX (E8 matrix + coverage-gaps.json, Oracle R8 unconfigured-vs-gap)/06-REJECTED + validation-report.md + manifest.json (per-file authenticity + D1-D3 gates + UX metrics) |
| End-user coverage matrix (E8) | ✅ `scripts/coverage_matrix.py` + `docs/dev/specs/end-user-matrix.yaml` |
| End-user journey validation | ✅ `enduser-journey.yaml` scenario; UX metrics UX_OK/completion_rate ≥ 0.8; error-boundary asserts `actionable` field |
| LLM timeout + parallel processing | ✅ `LLMConfig.timeout` (default 120.0) threaded through LLM calls; `AUTOINFO_PROCESS_WORKERS` ThreadPoolExecutor; MCP `asyncio.to_thread` offload |
| LLM fallback chain | ✅ Shared `llm.call_with_fallback` — every LLM call site (extraction + 17 standalone) walks `[primary] + config.llm.fallback`; first successful model wins, aggregate error surfaces last failure |
| Dead-source detection | ✅ Semantic Scholar 429 → `SourceFailure` (fail-fast); arXiv rss/bio → rss/q-bio fix |
| CLI module entry | ✅ `python -m autoinfo.cli` runs the same Typer app; `collect` live per-source progress printer |
| Test suite | ✅ ~3640 tests collected (incl. order-dependency fixes landed 2026-08-12; includes validation wave E1-E9 scenarios + regression suite + #141-#164 regression guards + kb-curation wave + hermetic config-seam fixes) |
| Delivery schedules | ✅ add_delivery_schedule, list_delivery_schedules, remove_delivery_schedule MCP tools, cron-integrated |
| Standardized error envelope | ✅ All MCP + REST API errors return `{success: false, error: {code, message, actionable}}`; 28 ErrorCode values; `error_dict()` deprecated |
| REST success envelope | ✅ REST API success responses return `{success: true, data: ...}` (breaking change v1.9; migration: `docs/archive/migration-v1.9.md`); dashboard JS unwraps transparently |
| LLM guard | ✅ Centralized `LLM_NOT_CONFIGURED` at `call_tool` dispatch (17 LLM-required tools) — no more raw auth errors |
| Actionable guidance | ✅ `init_project` returns `next_steps`; `diagnose_system` returns `health_score` (0-100) + `phase`; DOMAIN_NOT_FOUND includes "Use add_domain()" |
| CLI help text | ✅ 16 of 28 CLI command groups have custom help descriptions |
| CLI/MCP parity groups | ✅ 6 parity groups added M6 (topic-group, import-kb, query-collected, alert-rules, agent-callback + keywords suggest) — 28 CLI groups mirroring MCP tool params; parity matrix: `docs/dev/cli-mcp-rest-parity.md` |
| Required API keys doc | ✅ `docs/dev/required-api-keys.md` catalogs all env vars; linked from error messages |
| Content simplification (E14) | ✅ `simplify_content` MCP tool — CEFR-parameterized text simplification (A1-C1) with LLM rewrite + verification |
| Single-article payment (E12) | ✅ `create_checkout_session` mode="payment" for one-time article purchases; `check_access(article_id=...)` entitlement fast path |
| Source credibility score (E9) | ✅ Deterministic `source_score` (0-100) from quality tier, persisted on KBEntry, surfaced in G1 gate + search |
| RAW product variants (E11) | ✅ RAW product carries `variants: ["api_feed", "webhook", "bulk_export"]` field |
| Podcast RSS publishing (C11) | ✅ RSS 2.0 delivery channel with `<enclosure>` + `itunes:*` namespace; audio output auto-persists MP3 |
| Column product (B24) | ✅ `generate_report(report_type="column")` + premium ProductTemplate + G15 `check_access` gate + `column.md.j2` |
| Magazine digest (D11) | ✅ `generate_digest` magazine-digest ProductTemplate + `magazine-digest.md.j2` per-title RSS clustering (templates 6→8) |
| Validated source types | ✅ `VALID_SOURCE_TYPES` frozenset (29 types) as single source of truth for source type validation |

## References

- `docs/dev/mcp-usage-examples.md` — Full worked MCP tool workflow examples (moved from Common Patterns)
- `docs/dev/required-api-keys.md` — Full catalog of API keys and environment variables
- `docs/dev/founder-expectations.md` — D3 index (simplified after split; see `docs/archive/founder-expectations-pre-split.md` for full original)
- `docs/dev/specs/` — Extracted spec files (11 files: expectations.md, quality-gates.md, pipeline.md, delivery.md, operations.md, market-positioning.md, mcp-tools.md, data-models.md, user-lifecycle-definition.md, multi-tenancy-auth.md, ops-runbook.md)
- `docs/archive/kb-pipeline-reference.md` — Reference KB pipeline model (archived)
- `docs/dev/cross-dimensional-catalog.md` — **Keystone**: A1-A7 Pipeline × B1/B2/B3 Users (42 cells, 5 gap types). Supersedes archived gap-audit docs.
- `docs/dev/enduser-coverage-matrix.md` — End-user feature coverage matrix (keystone reference)
- `docs/dev/acceptance-framework.md` — **Acceptance mechanism (keystone, AC1-AC9)**: user model integrity, data-layer integrity, dual orientation (agent-operated tool / human-first results), coverage commitment, quality, commercial viability, process governance, documentation health (AC8), test & validation suite health (AC9). Supersedes `launch-validation-framework.md` as the top-level validation charter (D1-D5 now archived at `docs/archive/launch-validation-framework.md`; evidence machinery retained as tooling).
- `docs/dev/validation-scenario-contract.md` — Scenario authoring **and agent-tester execution** how-to (real MCP/CLI/REST calls, real artifacts); authoring + execution merged into one doc 2026-08-08 (former runbook archived at `docs/archive/agent-tester-validation.md`); graded against `acceptance-framework.md` (AC1-AC9)
- `docs/adr/` — Architecture Decision Records: the *why* behind architecture rules (01-Raw sole entry, agent promotion without human gate, LLM fallback chain, reasoning-model JSON control, unified envelope). Template: `docs/adr/TEMPLATE.md`.
- `docs/glossary.md` — Project glossary (Ubiquitous Language): the authoritative definitions of KB pipeline, gates, user types, and agent/tooling terms.
