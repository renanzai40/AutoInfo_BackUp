# Expectations Catalog — F01 to F72

> © Extracted from `founder-expectations.md §3` (lines 119-963) on 2026-07-26.
> Updated 2026-07-27 with F58-F64 (Phase 13: Blank Spaces) from cross-dimensional gap analysis.
> Updated 2026-07-27 with F65-F72 (Phase 14-16: B1/B2/B3 Lifecycle Gaps) from the user lifecycle definition.
> This file is the source of truth for the founder's expectation catalog. The original
> `founder-expectations.md` retains a stub cross-referencing this file.

> References: F01-F57 as defined in `founder-expectations.md`. F58-F64 added 2026-07-27 from
> [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) Type 1
> gaps (CD-001..CD-006, CD-010). F65-F72 added 2026-07-27 from
> [`docs/dev/specs/user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2-§5
> (B1/B2/B3 lifecycle gaps). See
> [`docs/dev/specs/pipeline.md`](./pipeline.md) for pipeline details,
> [`docs/dev/specs/quality-gates.md`](./quality-gates.md) for gate details,
> [`docs/dev/specs/delivery.md`](./delivery.md) for end user lifecycle,
> [`docs/dev/specs/operations.md`](./operations.md) for cost/privacy/lifecycle/observability,
> [`docs/dev/specs/data-models.md`](./data-models.md) for schemas.

---

## 3. Expectation Catalog

**Status legend:** ✅ Fully implemented | 🟡 Partially implemented (basic version works, enhancements pending) | ❌ Not yet implemented

Each expectation is a statement of what the founder expects the project to do.
Expectations are grouped by journey phase.

> **Note on domains**: References to "medical", "AI commercial", and "language learning" throughout this catalog are **demo domain configurations**. The system is designed to support **any domain** a user defines. Demo domains ship with curated sources and templates to prove value. Users can define their own domains, sources, extraction schemas, and output formats.
>
> **Unified end-user definition** (binding throughout this catalog): "End User" refers collectively to all paying customer types — individual consumer, creator, publisher, enterprise buyer, institutional buyer, platform operator, and content licensor — plus their authorized agent delegates. AutoInfo treats all end users uniformly with a single lifecycle model. **No demographic or persona-based segmentation is applied.** Persona-aware output (`target_audience` parameter: researcher, clinician, executive, student) is a content-level feature, not a user-profile differentiation.
>
> **Three operating modes** define how the end user interacts with AutoInfo:
> - **B1 End User (Direct Consumer)** — interacts in NL, Agent+LLM translates to structured config per the NL→Config pipeline defined in [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.1. Consumes products directly (email, chat, RSS, portal).
> - **B2 Direct User (Agent Operator)**: An AI agent operates AutoInfo via MCP tools on behalf of the end user.
> - **B3 Director User (Human Commander)**: A human operator defines domains, configures sources, and monitors the system.
>
> **Current status (as of 2026-07-27): 54/72 ✅ fully implemented, 6/72 🟡 partially implemented (F30 Subscription & Billing, F42 External Billing, F70 Unified Director Configuration, F71 Director Monitoring & Dashboard, F72 Incident Intervention Workflow, plus partial scope in F38/F40 reactivation paths), 12/72 ❌ not implemented (F58-F69, blank spaces from cross-dimensional gap analysis and user lifecycle gaps — see [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) CD-001..CD-006, CD-010 and [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2-§5).** Note: this is a historical snapshot — several items have since progressed (e.g., G14-G16 billing and subscription features, automated notifications, and rate limiting foundations have been implemented post-snapshot).

### 3.1 Phase 1: Setup

> "I should be able to install and configure AutoInfo in minutes."

#### F01 — Installation ✅

| UX Detail | Specification |
|-----------|---------------|
| **Installation methods** | Multiple paths supported: `pip install autoinfo` (PyPI), `git clone + pip install -e .` (source/dev), or `docker pull` (Docker). README recommends ONE primary path. |
| **Expected dependency handling** | `autoinfo doctor` detects missing system dependencies (LLM API connectivity, database status) and reports them with install guidance. |
| **Expected UX on first install** | Install to first successful command under 5 minutes for a new user who can `pip install`. |
| **Agent perspective** | Agent does not install AutoInfo. Agent connects to a running MCP server (`python -m autoinfo.mcp.server`). The MCP server must be started by the human or systemd. |

#### F02 — First Command ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: `autoinfo` with no arguments** | Shows standard typer help text listing commands. No splash screen, no branding display. |
| **Agent: MCP server connection** | Agent connects to MCP server via stdio (SSE transport is future work). Calls `health_check` tool to verify connectivity. Tool manifest is auto-discovered via MCP protocol. |
| **Output format — human** | Plain text help. `--json` flag available globally for machine-readable output. |
| **Output format — agent** | JSON-RPC over stdio. All tools return structured dicts. Tool descriptions are self-documenting via MCP protocol. |
| **Error responses** | Unified dual-format (flat + envelope) for backward-compatible consumer migration. `ErrorCode` enum (30 values) covers NotFound, DomainNotFound, ValidationError, InternalError, and additional codes: `AuthRequired` (future SSE auth), `RateLimited` (future rate limiting), `SessionExpired` (future session management), `LLMNotConfigured` (LLM guard, v1.8.1), `NoCachedItems`, `EmptyResult`, `ConfigNotFound`, `DIRECTOR_ONLY`, `READ_ONLY_SERVER` (read-only server guard), `FreeTierLimit` (free-tier usage gating). Flat format returns `{error_code, message, actionable}`; envelope format returns `{success: false, error: {code, message, actionable}}`. |
| **Key info visible** | Human: commands, config location, version. Agent: tool list, resource list, server instructions. |

#### F03 — Configuration Initialization ✅

| UX Detail | Specification |
|-----------|---------------|
| **Config file location** | Two-tier: project `.autoinfo/` takes priority; `~/.autoinfo/` is fallback. If neither exists, `init` creates `.autoinfo/` in current directory. |
| **Init process — human** | Interactive wizard: asks user for domains of interest, LLM providers, and default source preferences. Offers to activate one or more demo domain configurations. |
| **Init process — agent** | Agent does not run `init`. Agent expects `.autoinfo/` to already exist with valid config. If missing, MCP tools return appropriate error. |
| **Re-running init** | Idempotent: creates any missing files but never overwrites existing config. To reset fully, delete `.autoinfo/` and re-run init. |
| **What init creates** | Full project skeleton: `.autoinfo/config.yaml` (domains with embedded `sources` + `topics` — config.yaml is the single source of truth; no standalone `sources.yaml`/`domains.yaml`/`topics.yaml`) + directory structure (`collections/`, `outputs/`, `knowledge/`). `knowledge/` contains the 4 pipeline tiers: `00-Inbox/` (scaffolded but deprecated — no code writes to it), `01-Raw/`, `02-Draft/`, `03-Wiki/`. If demo domains selected, ships demo source lists. |
| **Demo domains shipped** | Thirteen pre-configured domain templates: `medical-research`, `ai-commercial`, `financial-intelligence`, `tech-ai-developer`, `language-learning`, `online-video`, `financial-news`, `online-education`, `legal-compliance`, `general-news`, `gaming`, `b2b`, `retail`. Each includes curated default sources, suggested topics, and output templates. User can activate any subset. |

#### F04 — LLM Configuration (BYOK) ✅

| UX Detail | Specification |
|-----------|---------------|
| **Multi-provider** | Supports any LLM provider accessible via LiteLLM/OpenRouter: Claude, GPT-4o, DeepSeek, local models (Ollama/vLLM), etc. |
| **Configuration** | `config.yaml` under `llm:` section: provider, model, API key (from env var or file), base URL (for local/self-hosted). |
| **Default provider** | None — user must configure at least one. `init` wizard can help select and test. |
| **Key verification** | `autoinfo doctor` tests LLM connectivity on demand. Collection run gives friendly error if key is invalid. |
| **Fallback chain** | Configurable: `llm.fallback: [claude-sonnet, deepseek-chat]` — if primary fails, try fallback. |
| **Per-task model selection** | Default model for all tasks, with per-task overrides: `llm.tasks.summarization.model: deepseek-chat`, `llm.tasks.extraction.model: claude-sonnet`. |
| **BYOK principle** | User brings their own API keys. No bundled LLM credits. Full cost control. |
| **Minimum friction — human** | Single `export AUTOINFO_LLM_API_KEY="sk-..."` with provider selection. |
| **Minimum friction — agent** | Agent assumes MCP server has key configured. If not, agent reports back to human. |

#### F05 — Domain & Source Configuration ✅

| UX Detail | Specification |
|-----------|---------------|
| **Domain as config** | A domain = a named configuration with: source list, extraction schema (optional), topic list, output templates. Everything in YAML. No code changes needed to add a domain. |
| **Minimum required fields** | At least one domain with at least one active source. |
| **Demo domain: Medical Research** | Default sources: PubMed API (primary), arXiv (q-bio, cs.AI categories), CrossRef (DOI → metadata). User can add more (journal RSS feeds, preprint servers, custom APIs). |
| **Demo domain: AI Commercial Intelligence** | Default sources: ProductHunt API, Crunchbase (basic), TechCrunch RSS, benchmark leaderboards (LMSYS, Artificial Analysis), thought leader blogs, AI case study repositories. Supports cases, rankings, product launches, funding data as parallel extraction tracks. |
| **Demo domain: Language Learning** | Default sources: Project Gutenberg, VOA Learning English, leveled reader repositories, news-in-levels, public domain children's literature. |
| **Demo domain: Financial/Business Intelligence** | Default sources: Alpha Vantage (stock/crypto/forex, free tier 25 req/day), FRED (US macroeconomics, free), SEC EDGAR RSS (regulatory filings, free), Twelve Data (free market data API), World Bank Data (global indicators, free), Reuters Connect (enterprise news wire, requires subscription), CoinDesk/CoinTelegraph RSS (crypto, free). Supports multi-source pricing intelligence, regulatory filing monitoring, market news aggregation, and institutional-grade data feed production. **Note**: Bloomberg, Wind, Refinitiv, and FT require paid institutional subscriptions and are not included as default sources — they are available as user-configured premium sources under F08. |
| **Demo domain: Tech/AI/Developer** | Default sources: GitHub Trending (REST API + GraphQL, free), ProductHunt API (product launches, free tier), TechCrunch RSS (tech news, free), arXiv cs.AI/cs.CL/cs.LG categories (preprints, free API), Substack RSS (public tech newsletters, free), Hacker News (Firebase API, free), Stack Overflow RSS (Q&A trends, free), Semantic Scholar (AI-enhanced academic search, free API with key). Supports newsletter-style digests, trend analysis, and technology landscape tracking for technical audiences. |
| **Source types supported** | RSS/Atom feeds, REST APIs (JSON), web pages (with extraction rules), webhook push, email (incoming newsletters via IMAP), PDF endpoints. |
| **Universal extraction** | LLM-based flexible schema extraction: user describes what fields they want, LLM extracts them. No per-source coding needed. |
| **Validation** | `autoinfo doctor` validates source configuration. URLs/API endpoints tested for reachability. |
| **Agent: discover demo domains** | `list_domains()` → returns all defined domains. Use `get_domain_schema(domain)` to inspect a domain's extraction fields, output templates, and topics. |
| **Agent: activate domain** | `activate_domain(name="medical-research")` — loads demo configuration into user's `.autoinfo/`. |
| **Agent: deactivate domain** | `deactivate_domain(name="medical-research")` — removes domain config but preserves collected data. |
| **Agent: read domain config** | `get_domain_config(domain="medical-research")` — returns full domain configuration including sources, topics, extraction schema, and output templates. |
| **Agent: discover domain schema** | `get_domain_schema(domain="medical-research")` → returns `{extract_fields: [{name, type, description, required}], output_templates: ["digest", "report"], topics: [...]}`. Agent reads this to know what extraction fields are available without reading documentation. |

#### F06 — Setup Verification ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human verification** | `autoinfo doctor` — checks Python version, LLM API connectivity, source reachability, database/filesystem status. |
| **Agent verification** | `health_check` MCP tool returns `{status, version, uptime_s, tools_count}`. Basic connectivity check. |
| **Agent self-diagnosis** | `diagnose_system()` MCP tool returns comprehensive health: `{llm: {provider, key_valid, last_test_ms}, sources: [{name, reachable, latency_ms}], disk: {free_mb, total_mb, knowledge_dir_size_mb}, db: {fts5_ok, entry_count}, tools_all_available: bool}`. Agent can self-diagnose without human running `doctor`. |
| **Source check** | `doctor` pings each configured source and reports reachability with latency. Agent-equivalent via `diagnose_system()` sources array. |
| **Missing dep guidance** | For each missing dependency, `doctor` prints install instructions. |

### 3.2 Phase 2: Domain & Topic Configuration

> "I should be able to define what to track, from where, and how to structure it."

#### F07 — Demo Domain Source Libraries ✅

*The system ships with curated source lists for thirteen demo domains, proving value out of the box.*

| UX Detail | Specification |
|-----------|---------------|
| **Medical Research sources** | PubMed API (primary), arXiv (q-bio, cs.AI categories), CrossRef (DOI → metadata). Each with quality rating, update frequency, access method. |
| **AI Commercial sources** | ProductHunt API (products), Crunchbase basic API (companies/funding), TechCrunch RSS (news), LMSYS/Artificial Analysis (benchmarks), curated case study indices. |
| **Language Learning sources** | Project Gutenberg (classics, public domain), VOA Learning English (leveled news), news-in-levels, commonlit.org (free leveled reading), public domain children's literature. |
| **Source metadata** | Each default source includes: name, URL/API endpoint, domain, content type, update frequency, quality tier (1-4), language, access restrictions. |
| **Quality tiers** | Tier 1: official APIs, peer-reviewed databases. Tier 2: reputable news, curated databases. Tier 3: blogs, community sources. Tier 4: user-defined custom (no quality guarantee). |
| **Agent: list defaults** | `list_available_platforms()` → returns all supported source platform types (RSS, API, Web, Webhook, Email, PDF) with descriptions. Use `list_sources(domain)` to see currently-configured sources for a domain. |
| **Agent: activate sources** | `add_source(source_name="pubmed", domain="medical-research")` — activates a demo source. |

#### F07b — Source API Capability Matrix (NEW) ✅

> *Comprehensive API capability matrix for all curated demo domain sources, derived from the global information payment research report (2024-2026).*

This section provides a structured API capability catalog for every pre-configured and commonly available source across all demo domains. It serves as the reference for:
- **Agent decision-making**: which sources to prioritize for a given domain
- **Engineering feasibility**: which sources are freely automatable vs. require paid access
- **Cost estimation**: API pricing, rate limits, and data scope per source

##### Academic & Research Sources

| Source | API Available | Pricing | Rate Limit | Data Scope | Best For | Feasibility Rating |
|--------|-------------|---------|-----------|-----------|----------|-------------------|
| **PubMed (NCBI E-utilities)** | ✅ 9 APIs (esearch, efetch, elink, etc.) | Free, no key required | ≤3 req/s (recommended); IP ban if exceeded | 37M+ citations, titles, abstracts, MeSH terms, author metadata | Medical research, biomedical literature tracking | ⭐⭐⭐⭐⭐ |
| **arXiv** | ✅ REST, OAI-PMH, RSS | Free, no key required | 1 req/3s; 2026 added system-level throttling, 429 on burst | 2.9M+ preprints (8 categories), full PDF links, abstracts | CS/AI/math/physics preprint tracking | ⭐⭐⭐⭐⭐ |
| **CrossRef** | ✅ REST API | Free; polite pool registration for higher limits | Public: 50 req/s; polite: 100+ req/s (2025-12 adjustment) | 180M+ DOI records, titles, authors, reference lists, citation metadata | DOI resolution, citation graph, metadata enrichment | ⭐⭐⭐⭐⭐ |
| **Semantic Scholar** | ✅ Graph API v1.0 | Free (requires x-api-key); research API for academic use only | Rate-limited (higher for authenticated keys) | 200M+ papers, titles, abstracts, citation graph, TLDR summaries | AI-enhanced literature search, citation analysis | ⭐⭐⭐⭐ |
| **OpenAlex** | ✅ REST API | Free, no key required | Generous rate limits | 250M+ scholarly works, authors, institutions, concepts | Open scholarly metadata, broad coverage | ⭐⭐⭐⭐⭐ |
| **PubMed Central (PMC)** | ✅ OA full-text API | Free | Same as PubMed E-utilities | Full-text OA articles, bulk download via FTP | Full-text medical research, NLP datasets | ⭐⭐⭐⭐ |
| **CORE** | ✅ API | Freemium (free tier with limits) | Free tier: limited calls/day | Millions of OA papers aggregated | Central OA paper discovery | ⭐⭐⭐ |
| **Scopus (Elsevier)** | ✅ Scopus API | Paid subscription required (institutional) | Per licensing agreement | 100M+ records, complete citation data, author profiles | Institutional academic research | ⭐⭐ |
| **Web of Science (Clarivate)** | ✅ API | Paid subscription required (institutional) | Per licensing agreement | High-quality journal index, citation data | Citation analysis, research evaluation | ⭐⭐ |
| **IEEE Xplore** | ✅ API | Paid subscription required (institutional or personal) | Per licensing agreement | Engineering, computer science journals/conferences | Engineering research | ⭐⭐ |
| **CNKI (中国知网)** | ❌ No public API | Institutional subscription (~¥160K+/year per university) | Strong anti-crawl (CAPTCHA, IP rate-limit, dynamic token) | 280M+ articles, 10,689 journals (Chinese academic) | Chinese academic research | ⭐ (not automatable) |
| **SSRN (Elsevier)** | ⚠️ Limited (Elsevier integration) | Mostly free (OA papers); some paid | Insufficient data | 563K+ full-text downloads, social sciences/humanities | Social science, law, economics | ⭐⭐ |

##### Financial Data Sources

| Source | API Available | Pricing | Rate Limit | Data Scope | Best For | Feasibility Rating |
|--------|-------------|---------|-----------|-----------|----------|-------------------|
| **Bloomberg Terminal** | ✅ Private BLP API (terminal only) | **$2,665/user/mo** (~$32K/yr); API negotiable | Private protocol, hardware-bound auth | Real-time quotes, history, news, analytics (full-stack) | Institutional finance, real-time market data | ⭐ (prohibitively expensive) |
| **Refinitiv / LSEG Workspace** | ✅ Eikon/Workspace Data API | **$2,000-$8,000+/user/mo** (enterprise pricing) | OAuth license | Real-time + historical quotes, reference data, news | Professional finance, enterprise | ⭐ (prohibitively expensive) |
| **Wind (万得)** | ✅ Local COM/Python SDK | Institutional: tens of thousands RMB/yr; personal: ~¥680/mo (2024 discount) | Account + hardware lock | A-shares, bonds, funds, derivatives, macro, industry (China focus) | China A-share market, Chinese institutional finance | ⭐⭐ (paid, China-specific) |
| **东方财富 Choice** | ✅ Quant API | Institutional (lower entry than Wind) | Signature/token auth | A-shares, HK stocks, US stocks, funds, financial statements | Retail/individual investors in China | ⭐⭐ |
| **同花顺 iFinD** | ✅ SDK + HTTP API | Terminal from ¥8,000+/yr | Login + IP binding | Quotes, financials, news, macro | Retail investors in China | ⭐⭐ |
| **Quandl (Nasdaq Data Link)** | ✅ REST + Python/R packages | Freemium (free datasets + premium by source) | API key rate-limited | EOD, fundamentals, macro, alternative data | Developers, quantitative research | ⭐⭐⭐⭐ |
| **Alpha Vantage** | ✅ REST | Free: 25 req/day (5 req/min); Premium: $49.99-$79.99/mo | Rate-limited (free tier very restrictive) | Stocks, forex, crypto, technical indicators | Personal finance, prototyping, lightweight projects | ⭐⭐⭐ |
| **FRED (Federal Reserve)** | ✅ REST API | **Free** | Generous | US economic time series (millions of series) | US macroeconomic analysis, research | ⭐⭐⭐⭐⭐ |
| **Yahoo Finance** | ❌ No official API (shut down 2017) | — | Blocks automated requests | — (3rd party yfinance library exists, ToS-violating). A `yahoo_finance` collector handler IS shipped (`collectors/yahoo_finance.py`) — the handler provides access but the underlying data source carries ToS risk and is **not recommended for production use**. | ⭐ (ToS risk, handler exists) |
| **CEIC** | ⚠️ API available | High-price institutional subscription | Per contract | Global macroeconomics (200+ countries) | Global macro research | ⭐⭐ |

##### News & Media Sources

| Source | API Available | Pricing | Rate Limit | Data Scope | Best For | Feasibility Rating |
|--------|-------------|---------|-----------|-----------|----------|-------------------|
| **Reuters Connect** | ✅ Enterprise licensing | **$2K-$15K/mo** base; AI training/RAG: six-figure USD/yr | Enterprise contract + OAuth | Full text, images, video, live feeds | Enterprise news monitoring, AI training data | ⭐⭐ |
| **Associated Press (AP)** | ✅ AP Developer Portal | Requires API key (paid); free/subscription tiers | 100 calls/min/key default | Full text, headlines, authors, dates, multimedia | General news, wire content | ⭐⭐⭐ |
| **NYT** | ✅ Developer API | Free key + paid premium | 10 req/min; 1,000 req/h via RapidAPI mirror | Headlines, abstracts, authors, sections (non-full-text, 1980+) | Research, non-commercial analysis | ⭐⭐⭐ |
| **Bloomberg Media** | ❌ No public API | — | — | — | — | ⭐ (not accessible) |
| **Financial Times** | ❌ No public API | Personal sub: £75/mo; no API | Strong anti-crawl behind paywall | Full text (paywalled) | — | ⭐ (not accessible) |
| **新华社** | ❌ No public API | State news agency | — | — | — | ⭐ (not accessible) |
| **财新 (Caixin)** | ❌ No public API | Subscription: ¥498-¥998/yr | Strong anti-crawl | Full text (paywalled, Chinese financial news) | — | ⭐ (not accessible) |
| **WSJ** | ❌ No public API | $44.99/mo | — | — | — | ⭐ (not accessible) |

##### Knowledge & Paid Content Platforms

| Source | API Available | Pricing | Data Scope | Feasibility Rating |
|--------|-------------|---------|-----------|-------------------|
| **Substack** | ✅ Developer API (read-only) | Free (registration + LinkedIn verification) | Public profiles, post metadata; **no paid content** | ⭐⭐⭐⭐ |
| **Medium** | ❌ No public data API | Membership ($5-15/mo) | Public article metadata only (Cloudflare/UA verification) | ⭐⭐ |
| **知乎 (Zhihu)** | ❌ No open API (encrypted since 2025/3) | Salt membership | Public Q&A/column summaries (sliding window + token bucket + TLS fingerprint rate-limiting) | ⭐ (not accessible) |
| **得到 App** | ❌ No official API | Subscription ¥199-¥365/yr | Course/ebook metadata (HTTPS signing + anti-debug) | ⭐ (not accessible) |
| **微信公众号** | ❌ No official API | — | Public article HTML (strong anti-crawl: login/Referer/CSRF required) | ⭐ (not accessible) |
| **Patreon** | ✅ API | Creator subscription | Creator content, membership data | ⭐⭐⭐ |
| **小鹅通** | ✅ Open API | SaaS platform | User/order/course/learning data | ⭐⭐⭐ |

##### Social Media & UGC Sources

| Source | API Available | Pricing | Rate Limit | Data Scope | Feasibility Rating |
|--------|-------------|---------|-----------|-----------|-------------------|
| **X (Twitter)** | ✅ v2 API | Free: 1 post/day write only; Basic: $200/mo (15K reads); Pro: $5,000/mo; Enterprise: $125K-$210K/mo | Token + rate-limit quotas | Tweets, users, trends, search | ⭐⭐ |
| **Reddit** | ✅ OAuth API | Free: 100 req/min (OAuth); Commercial: $0.24/1K calls (pre-approval) | Strict rate-limiting | Posts, comments, subreddit metadata | ⭐⭐⭐⭐ |
| **YouTube Data API v3** | ✅ REST | Free: 10K units/day; Overage: $0.001-$0.01/unit | Quota-based | Videos, channels, comments, captions, analytics | ⭐⭐⭐⭐ |
| **TikTok** | ✅ Display/Login/Research API | Display: commercial; Research: academic (audited) | Device/UA/JS verification, strong anti-crawl | Videos, user metadata (limited) | ⭐⭐ |
| **微博 (Weibo)** | ✅ Open platform | Developer qualification + tiered pricing | Rate-limit + CAPTCHA | Weibo posts, comments, users (partial) | ⭐⭐ |
| **抖音/字节系** | ✅ Open platform | Base: ¥50/10K calls; Premium: ¥100/10K calls (2024/10 pricing) | Signature + token + IP rate-limit | Videos, live-streaming, IM, ecommerce | ⭐⭐ |
| **B站 (Bilibili)** | ✅ Open platform | App review required (free quota available) | Risk control + CAPTCHA | Videos, danmaku, comments, live-streaming | ⭐⭐⭐ |
| **小红书 (Xiaohongshu)** | ✅ Open platform (e-commerce/data only) | Merchant/partner qualification required | Signature + device fingerprint; v2 deprecated 2025/6 | Notes, products | ⭐⭐ |

##### Podcast & Audio Sources

| Source | API Available | Pricing | Data Scope | Feasibility Rating |
|--------|-------------|---------|-----------|-------------------|
| **Spotify** | ✅ Web API + oEmbed | Free (client credentials OAuth); Commercial via partner | Episodes/shows metadata; **no audio stream** | ⭐⭐⭐⭐ |
| **Apple Podcasts** | ✅ iTunes Search API (no auth) | Free | Episodes/shows metadata (1.58M shows globally) | ⭐⭐⭐⭐⭐ |
| **喜马拉雅 (Ximalaya)** | ❌ No public API | — | — | ⭐ (not accessible) |
| **小宇宙 (XYZ Podcast)** | ❌ No official API | — | — | ⭐ (not accessible) |

##### Data Automation Polarity Summary

The research report reveals a clear **polarization** between "engineering-feasible" and "non-engineering-feasible" sources:

| Category | Engineering-Feasible (Free/Open API) | Not Engineering-Feasible (No API or Extremely Expensive) |
|----------|-------------------------------------|--------------------------------------------------------|
| **Academic** | arXiv, PubMed, OpenAlex, CrossRef, Semantic Scholar, PMC, CORE (free tier) | CNKI, Scopus (paid), Web of Science (paid), IEEE (paid), SSRN (limited) |
| **Financial** | Alpha Vantage (free tier), FRED, Quandl (free tier) | Bloomberg, Refinitiv, Wind, FT, CEIC |
| **News** | AP (limited free tier), NYT (research only) | Bloomberg Media, WSJ, 财新, FT, 新华社, 人民日报 |
| **Social/UGC** | Reddit (non-commercial), YouTube, Apple Podcasts | TikTok, 微博, 抖音, 小红书, B站 (paid access) |
| **Chinese Knowledge** | — | 知乎, 得到, 微信公众号, 喜马拉雅, 小宇宙 |

**Strategic implication**: AutoInfo's engineering strategy prioritizes sources with open APIs (academic, selected financial, selected news) for the automated pipeline. High-value but walled sources (Bloomberg, Chinese platforms) are supported as "premium user-configured sources" under F08 — users configure their own paid access, AutoInfo provides the handler. This polarity directly informs domain selection and product pricing. |

*Users add any source, for any domain, without writing code.*

| UX Detail | Specification |
|-----------|---------------|
| **Human: add source** | `autoinfo sources add --name "My Blog" --url https://example.com/rss --type rss --domain custom-domain` |
| **Human: list sources** | `autoinfo sources list` — shows all sources with status, grouped by domain. |
| **Agent: add source** | `add_source(name="My Blog", url="https://...", type="rss", domain="custom-domain")`. **Idempotent**: calling with the same `(url, type, domain)` returns the existing source ID instead of error. Safe for agent retry. |
| **Agent: batch add sources** | `add_sources(sources=[{name, url, type, domain}, ...])` — add multiple sources in one call. Each source validated independently. Non-existent domains return error per source, not global failure. |
| **Source types** | `rss` (RSS/Atom), `api` (REST JSON), `web` (web page, auto-extract), `webhook` (push endpoint), `email` (IMAP inbox), `pdf` (PDF endpoint/directory). |
| **Extraction schema per source** | Optional: user can define `extract_fields: [title, author, date, content, custom_field_1, ...]`. LLM extracts these from each item. If no schema defined, defaults to generic: title, content, date, source. |
| **Source validation** | On add, system tests connectivity and attempts a sample fetch. Reports errors immediately. |
| **Agent: remove source** | `remove_source(source_id="pubmed")` — removes source from domain config. Does not delete already-collected data. |
| **Agent: test source** | `test_source(url="https://...", type="rss")` — fetches a sample, returns content preview, format detection, and suggested extract_fields. |
| **Agent: source warning** | `add_source` returns `{source_id, warnings: ["low quality tier: 3 — content may be unreliable"]}` when quality_tier ≥ 3. Advisory only — agent decides whether to notify human. |

#### F09 — Topic & Keyword Configuration ✅

| UX Detail | Specification |
|-----------|---------------|
| **Domain-scoped topics** | Each domain has its own topic list. Topics within a domain share the domain's source pool. |
| **Human: add topic** | `autoinfo topics add --domain medical-research --name "IVF 2026 breakthroughs" --keywords "IVF, embryo, implantation, in vitro fertilization"` |
| **Human: topic groups** | `autoinfo topics group --domain medical-research --name "IVF Research" --add ivf endometriosis` — hierarchical grouping |
| **Agent: manage topics** | `add_topic(domain="medical-research", name="IVF breakthroughs", keywords=["IVF", "embryo"])`. Remove with `remove_topic(domain="medical-research", topic_id="...")`. |
| **Topic → source mapping** | Each topic can be restricted to specific sources, or use all active sources in its domain. |
| **Multi-language keywords** | Topics support keywords in multiple languages. Useful for cross-lingual domains. |
| **Topic scoring & suggestions** | System can suggest keyword refinements based on initial collection results and LLM analysis. |

#### F10 — Multi-language & Localization ✅

*Content comes in many languages; the system handles it gracefully. Essential for the language learning demo domain and general usability.*

| UX Detail | Specification |
|-----------|---------------|
| **Source language auto-detection** | Auto-detect language of collected content. Store as metadata. |
| **Translation pipeline** | Built-in LLM-based translation for summarization. User configures source → target language pairs. |
| **Learning-specific localization (demo domain)** | For language-learning domain: level-appropriate simplification, glossaries, reading level classification (CEFR A1-C2, Lexile). |
| **Cross-lingual KB** | Knowledge base entries have multi-language fields: title (original + translated), summary (user's language), keywords (multi-lang). |
| **Use case: medical paper in Chinese** | "帮我翻译这篇摘要到英文" → `localize_content(content, source_lang="zh", target_lang="en")` |
| **Use case: English reading for kids** | "帮我把这篇文章按CEFR B1级别简化，标注生词" → `simplify_for_learning(content, level="B1", gloss_target="zh")` |
| **Agent: translate** | `localize_content(content_id="...", target_lang="en")` — returns translated version. |
| **Translation QA — back-translation verification** | After translation, the system performs back-translation: translate the result back to the source language and compare with the original via LLM. Mismatches are flagged with diff details. Reduces hallucination risk by 60%+ compared to single-pass translation. |
| **Translation QA — multi-round refinement** | If back-translation reveals issues, the system re-transmits with context from the first attempt: "Previous translation had issue X in paragraph Y. Re-translate focusing on Z." Supports up to 3 refinement rounds before falling back to the best attempt. |
| **Translation QA — domain terminology guard** | Per-domain terminology dictionary (maintained in `_keywords.yaml`). Terms like drug names, medical procedures, technical concepts are tagged `do_not_translate` or `preferred_translation`. The LLM prompt includes these guardrails to prevent mistranslation of critical terms. |
| **Translation QA — style & tone consistency** | LLM review verifies that translation maintains the original's tone (formal/academic/colloquial), register, and intent. Style violations are flagged separately from factual inaccuracies. |
| **Translation QA — prompt engineering** | Domain-specific translation prompts optimized through iterative testing. Each domain can define: `translation_prompt_template` (overrides the default), `terminology_glossary_path`, `style_guide`. Prompts are versioned and auditable. |
| **Translation QA — agent skill** | A dedicated translation quality skill (`translator-qa-skill`) that agents load for high-stakes translation workflows. The skill orchestrates: initial translation → back-translation check → terminology audit → style review → human review prompt → final approval. |
| **Translation QA — quality score** | Each translation gets a composite quality score (0-100) combining: faithfulness (G5), terminology accuracy, style consistency, readability. Scores below configurable threshold auto-flag for human review. |

#### F10b — User-Defined Domains & Consulting Platforms ✅

*The platform is domain-agnostic. Users define their own fields of interest and configure the information platforms (data sources) they want to track — no coding required.*

| UX Detail | Specification |
|-----------|---------------|
| **Domain as first-class entity** | A domain = named configuration with: sources, topics, extraction schema, output templates. Defined entirely in YAML. No code changes needed to add a domain. |
| **User-defined domains** | Users create new domains from scratch: `add_domain(name="my-custom-domain", description="...")` — generates a minimal domain skeleton with empty sources/topics, ready to populate via `add_source` and `add_topic`. |
| **Consulting platform concept** | A "consulting platform" is the information source/platform a domain monitors (e.g., PubMed for medical research, TechCrunch for AI commercial, Weibo for social trends). Users define which platforms their domain consults. Platforms map 1:1 to source configurations in the domain. |
| **Multi-platform domain** | A single domain can consult multiple platforms simultaneously. Example: "Medical Research" domain consults PubMed, arXiv, CrossRef, and 3 journal RSS feeds. |
| **Domain lifecycle** | `create` → `activate` / `deactivate` → `archive` (preserves data) → `delete` (destructive). Agent can manage full lifecycle. |
| **Domain schema** | Each domain defines: `extract_fields` (what LLM extracts from items), `output_templates` (digest/report/tutorial/presentation), `search_mode` (keyword/hybrid), `relevance_threshold`. |
| **Agent: create domain** | `add_domain(name="my-domain", description="...")` — creates a new domain with default config. Returns `{domain, sources: [], topics: [], status: "active"}`. Must be idempotent: calling with same name returns existing config. |
| **Agent: list domains** | `list_domains()` — returns `[{name, active, source_count, topic_count, platform_count}]`. |
| **Agent: get schema** | `get_domain_schema(domain="my-domain")` — returns `{extract_fields, output_templates, search_mode, platform_types_supported}`. Agent reads this to understand domain capabilities. |
| **Agent: activate/deactivate** | `activate_domain(name="...")` / `deactivate_domain(name="...")` — toggle domain active state without losing config or data. |
| **Agent: remove domain** | `remove_domain(name="...")` — removes domain config. Preserves already-collected data. |
| **CLI: domain management** | `autoinfo domain add|list|show|remove|activate|deactivate` — human-direct interface for domain lifecycle. |
| **Platform discovery** | `list_available_platforms()` — returns all supported source platform types (RSS, API, Web, Webhook, Email, PDF) with descriptions. Agent uses this to suggest platforms to users during domain creation. |

### 3.3 Phase 3: Information Gathering

> "I should be able to collect information and know what's happening."

#### F11 — One-Command Collection ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: collect one domain** | `autoinfo collect --domain medical-research` — collects from all active sources in the domain |
| **Human: collect one topic** | `autoinfo collect --domain medical-research --topic "IVF"` — filtered to topic |
| **Human: collect all** | `autoinfo collect --all` — collects from all active domains |
| **Agent: collect** | `collect_sources(domain="medical-research")` — single MCP tool call |
| **Agent: selective** | `collect_sources(domain="medical-research", sources=["pubmed"], keywords=["IVF"], limit=20)` |
| **Collection output** | Each item stored with: source, title, url, content, collected_at, language, domain, topic tags, quality score. |
| **Dedup (G2)** | URL-based dedup + fuzzy title dedup within configurable time window. Same article from multiple sources = one entry. |
| **Dry-run mode** | `collect_sources(..., dry_run=true)` — returns `{estimated_items: {pubmed: 12, arxiv: 5}, total_estimated: 17}` without fetching or storing. Agent previews collection impact before committing. |
| **Empty result handling** | If no new items found, report clearly: "No new items for [domain]. Last collection had [N] items." Not an error. |

#### F12 — Collection Progress Visibility ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: terminal output** | Per-source progress: source name, items found, items new (after dedup), errors, duration. |
| **Human: no silent gaps** | Between sources, continuous progress output so terminal never goes silent. |
| **Human: completion** | Summary: `✅ 收集完成 — PubMed: 12篇 (8新), arXiv: 5篇 (3新), 共 11 篇新内容` |
| **Agent: progress** | `collect_sources` returns `{collection_id, status: "started", estimated_duration_s: 30}` immediately. Agent divides by 4 for poll interval (e.g., 30s → poll every 7.5s, min 2s). Agent polls `get_collection_progress(collection_id)`. |
| **Agent: per-source detail** | `{source: "pubmed", status: "completed", items_found: 12, items_new: 8, errors: []}` |
| **Agent: processing** | After collection, `process_collection(domain="medical-research", model="deepseek/deepseek-chat")` — runs LLM extraction + quality gates on cached raw items. Separable from collection: collect now, process later. |
| **Agent: completion** | `get_collection_status(collection_id)` returns full collection result with all items. |

#### F13 — Source Type Handlers ✅

*Each supported source type has a dedicated handler. Handlers are pluggable — new source types can be added without changing core pipeline.*

| Source Type | Handler Behavior | Implementation Priority |
|-------------|-----------------|------------------------|
| **RSS/Atom** | Fetch feed XML → parse entries → extract content (full text if available, else summary) → store | 🔴 P0 |
| **REST API (JSON)** | Call endpoint with auth → parse JSON response → extract according to schema → store | 🔴 P0 |
| **Web page** | Fetch HTML → extract main content (trafilatura/readability) → clean → store | 🟡 P1 |
| **Webhook** | Receive POST → validate → store immediately | 🔵 P2 |
| **Email (IMAP)** | Connect to inbox → fetch unread from configured folder(s) → parse → store | 🔵 P2 |
| **PDF endpoint** | Download PDF → extract text (pypdf/LLM) → store | 🟡 P1 |

#### F14 — Scheduled Collection ✅

| UX Detail | Specification |
|-----------|---------------|
| **Scheduling mechanism** | External crond calls `autoinfo cron run` at configured intervals. AutoInfo has no built-in scheduler. |
| **Config format** | `cron.schedules: [{name: "daily-medical", expression: "0 8 * * *", domain: "medical-research", topic: "all"}]` |
| **Per-domain cadence** | Different schedules per domain: daily medical, weekly AI commercial. |
| **Agent: manage schedules** | `add_collection_schedule(expression="0 8 * * *", domain="medical-research")`. Full CRUD via MCP. |
| **On-demand + scheduled** | Both work. On-demand for immediate needs. Scheduled for regular updates. |

#### F15 — LLM-Based Extraction Pipeline ✅

*The core differentiator: LLM extracts structured fields from any collected content, for any domain.*

| UX Detail | Specification |
|-----------|---------------|
| **Universal extraction** | After collection, each item passes through an LLM extraction step. What gets extracted depends on the domain's `extract_fields` config. |
| **Default extraction** | If no custom schema: title, summary (TL;DR), key points (3-5), entities (people, organizations, concepts), relevance score to user's topics. |
| **Custom extraction** | User defines: `extract_fields: [methodology, sample_size, key_findings, limitations]` for medical domain. LLM extracts these from each paper. |
| **Extraction prompt** | Per-domain extraction prompt template. Default prompt is auto-generated from field names and descriptions. User can override. |
| **Extraction quality gate (G4)** | Post-extraction, LLM verifies: does the extracted summary contradict the source? Flags hallucination. |
| **Agent: extract** | `extract_fields(content_id="...", schema=["methodology", "findings"])` — on-demand re-extraction with custom schema. |
| **Agent: inspect extraction** | `get_extraction(content_id="...")` — see what was extracted for any item. |

### 3.4 Phase 4: Curation & Interaction

> "I can review, interact with, and curate the collected information."

#### F16 — Summary Review ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: browse summaries** | `autoinfo summaries list --domain medical-research --date today` — list all summaries from today, ranked by relevance |
| **Human: read full** | `autoinfo summaries show <summary-id>` — full summary with source link, extracted fields, quality score |
| **Human: flag for KB** | `autoinfo summaries flag <id> --tag important --add-to-kb` — tag for knowledge base inclusion |
| **Agent: list summaries** | `list_summaries(domain="medical-research", date_from="2026-07-01", limit=20)` |
| **Agent: read single summary** | `get_summary(summary_id="...")` — returns full summary detail with extracted fields, quality scores, full content, and source provenance. |
| **Agent: flag for KB** | `flag_for_knowledge_base(summary_id, tags=["ivf", "breakthrough"], importance=5)` |
| **Summary format** | Title (original + translated), source, collected_at, TL;DR, key points (3-5), relevance score, extracted fields. |
| **Batch review (agent-driven)** | Agent can present batch: "Today's medical digest: 15 new papers, 3 flagged as important. Key findings: [...]" |
| **Quality filtering (G3)** | Items below configurable relevance threshold are stored but hidden from default summary view. User can opt to see them. |

#### F17 — Interactive Q&A on Collected Content ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: ask about content** | "上一篇关于子宫内膜容受性的论文里，用了什么研究方法来测量？" → Agent searches collected content and answers with citations. |
| **Agent: Q&A tool** | `query_collected(query="method for endometrial receptivity measurement", domain="medical-research", content_ids=["..."])` — returns answer with source citations. |
| **Cross-item synthesis** | Answers can synthesize across multiple items: "比较这三篇IVF论文的成功率数据" → structured comparison table. |
| **Source-grounded** | All answers must cite specific collected items. No hallucination: if answer not in collected content, say so. |
| **Scope: Q&A on collection only** | Q&A is limited to already-collected content, not live web search. |
| **Conversation persistence** | Q&A context persists per topic/domain per session. |

#### F18 — Quality Rating & Filtering ✅

| UX Detail | Specification |
|-----------|---------------|
| **Source authority check (G1)** | Each source has a `quality_tier` (1-4). Items from Tier 3+ sources are flagged. User can set minimum tier: "only show Tier 1-2". |
| **Automatic relevance scoring (G3)** | Each item scored against user's topic keywords + LLM-based semantic relevance. Score range 0-100. |
| **User feedback loop** | User can rate items: `autoinfo summaries rate <id> --helpful` / `--not-relevant` → system adjusts topic weights and extraction focus. |
| **Agent: rate item** | `rate_item(item_id, rating=5, feedback="highly relevant to IVF protocol comparison")`. |
| **Auto-filter** | Items below configurable relevance threshold stored but hidden from default view. User can override per collection. |

#### F19 — Cross-reference & Linking ✅

| UX Detail | Specification |
|-----------|---------------|
| **Auto-linking** | System auto-links items sharing keywords, entities, authors, citations (where available), or topics. |
| **Manual linking** | Human or agent can manually link items: "这篇论文是对上一篇提到的技术的临床验证" → `link_items(item_a_id, item_b_id, relation="clinical_validation")`. |
| **Relation types** | `cites`, `cited_by`, `extends`, `contradicts`, `validates`, `implements`, `related`, `translation_of`, `simplified_for`, `custom`. |
| **Cross-domain linking** | Link across domains: "这篇AI论文的方法可以用于医学论文分析" → cross-domain link with rationale. |
| **Agent: query relations** | `get_item_relations(item_id)` → returns linked items with relation types and strength. |

### 3.5 Phase 5: Knowledge Base Building

> "Collected information transforms into a structured, searchable, reusable knowledge asset."

#### F20 — Knowledge Base Storage (4-tier Pipeline) ✅

*KB architecture follows the proven KB pipeline design (`docs/archive/kb-pipeline-reference.md`): a 4-level pipeline with sequential promotion.*

> **Lifecycle cross-ref:** Supports B3.3 Intervene — note: the promote Draft→Wiki operation is no longer a B3 intervention action (2026-08-08 director decision: promotion is an **agent operation**, the KB being a database for raw/processed production). See [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §5.3 (Error Escalation Path) for the remaining intervention model.

| UX Detail | Specification |
|-----------|---------------|
| **Pipeline model** | 4-level sequential pipeline, **no skipping allowed**:
  ```
  Collected Item → 01-Raw → 02-Draft → 03-Wiki
       ↑              ↑          ↑           ↑
    Auto-ingest    Raw is     Agent can    Agent
    from F11      the ONLY    process &    promotes
                  entry       create       Draft → Wiki
                  point       Draft.       03-Wiki reached
                              No direct     via promote_kb_draft
                              bypass to     (no human gate)
                              03-Wiki.
  ```
| **00-Inbox** ⚠️ deprecated | Scaffolded by `init` but **no code ever writes to it**. Items go directly to 01-Raw. Retained as an empty directory skeleton for backward compatibility. Corresponds to KB tier `00-Inbox/`. |
| **01-Raw** (auto, primary) | **Sole entry point** for all collected content. Every collected item (from F11) lands here automatically. **全量保留，不做取舍** — keep everything, filter later. File name = readable topic slug, not source ID. Corresponds to KB tier `01-Raw/`. |
| **02-Draft** (agent-writable) | Agent can create Draft entries from Raw: cleaned, merged, restructured, enriched. But agent **cannot** create Draft directly from outside — only from 01-Raw. User reviews Draft before promotion. Corresponds to KB tier `02-Draft/`. |
| **03-Wiki** (agent-promoted, append-only) | Final production tier — permanently stored knowledge. **No direct writes allowed** (hard rule); promotion happens only through `promote_kb_draft` (KB-tier guard). Agent promotes Draft→Wiki (2026-08-08 director decision: the KB is a database for raw/processed production — promotion is an agent production step with no human gate). **Append-only**: once promoted, entries stay. Agent cannot demote or delete Wiki entries. Agent may deprecate (tag `status: deprecated`) or annotate entries upon explicit human command. Corresponds to KB tier `03-Wiki/`. |
| **Directory structure** | `knowledge/<domain>/<tier>/<topic>/<YYYY-MM-DD>-<slug>.md`. Example: `knowledge/medical-research/01-Raw/ivf/2026-07-20-endometrial-receptivity.md`. |
| **Entry frontmatter** | `title`, `domain`, `tier` (raw/draft/wiki), `source_url` (必填), `source_type` (paper/article/video/…), `source_platform` (pubmed/arxiv/…), `author`, `collected_at`, `summary`, `source_ids[]`, `tags[]`, `status` (raw/processing/compiled), `priority` (1-5), `language`, `related_concepts[]`, `linked_entries[]`, `custom_fields: {key: value}`. |
| **Generic schema + custom fields** | All entries share base fields. Each domain defines `custom_fields`. Medical: `{doi, authors, journal, methodology, sample_size}`. AI: `{category, pricing, competitors}`. User-defined: anything. |
| **Keywords system** | Central `_keywords.yaml` per domain or global. Managed status: `verified` (human-confirmed), `auto_added` (LLM-extracted candidate), `merged`, `deprecated`. Prevents synonym proliferation. Modeled after external `_keywords.yaml` pattern (554 entries across the KB). |
| **Agent: list keywords** | `list_keywords(domain="medical-research", status="verified")` — returns `[{keyword, status, aliases, created_at}]`. Agent uses known keywords to refine search queries and topic suggestions. |
| **Source metadata mandatory** | Every Raw entry must have complete source provenance (`source_url`, `source_type`, `source_platform`). Future verification and回溯 depend on this. |
| **Auto-ingest to 01-Raw** | Collection pipeline (F11-F15) automatically creates 01-Raw entries. No user action needed for ingestion. |
| **Auto-extraction → Draft candidate** | LLM extraction (F15) + quality gates (G1-G3) produce a Draft candidate from Raw. Agent can present: "3 papers promoted to Draft-ready, review and promote to Wiki?" |
| **Agent: create Draft** | `create_kb_draft(raw_ids=["..."], title="...", summary="...", tags=[...])`. **Cannot** skip Raw. |
| **Agent: list tiers** | `list_kb_tier(domain="medical-research", tier="01-Raw")` — returns entries in a specific pipeline stage. |
| **Agent: promote Draft→Wiki** | `promote_kb_draft(draft_id="...")` — the only way to create Wiki entries. Promotion is an **agent production operation** (2026-08-08 director decision: the KB is a database for raw/processed production — no human gate). The CLI `autoinfo kb promote <entry-id>` is the human-facing equivalent. |
| **User: reject Draft** | `autoinfo kb reject <entry-id> --reason "needs more sources"` — sends back to Raw or archives. |
| **Agent: reject Draft** | `reject_kb_draft(draft_id="...", reason="needs more sources", action="back_to_raw")` — agent processes rejection on human instruction. Moves Draft back to Raw for revision. |

#### F21 — Knowledge Base Search & Retrieval ✅

| UX Detail | Specification |
|-----------|---------------|
| **Hybrid search** | Keyword (SQLite FTS5) + semantic (vector embeddings via LLM). Configurable weight via `search.mode: hybrid|keyword|semantic`. |
| **Faceted search** | Filter by: domain, tags, date range, source quality tier, content type, language. |
| **Agent: search KB** | `search_knowledge_base(query="endometrial receptivity biomarkers", domain="medical-research", limit=10, offset=0)` — returns paginated results with total count. |
| **Agent: read entry** | `get_kb_entry(entry_id="...")` — returns full entry content (title, all metadata, body, extracted fields, source provenance, linked entries). Required because search results are summaries only. Agent reads full entry to answer deep questions. |
| **Search results** | `[{entry_id, title, summary, relevance_score, matched_tags[], source_count, custom_fields}, total_count]`. |
| **Pagination** | All list/search tools accept `limit` (default: 20, max: 100) and `offset` (default: 0) for cursor-style pagination. Results include `total_count` for agent to determine if more pages exist. |
| **Cross-domain search** | Search across all domains or restrict to specific ones. Default: current domain context. |

#### F22 — Knowledge Graph ✅

| UX Detail | Specification |
|-----------|---------------|
| **Entity extraction** | LLM-based extraction of entities from KB entries: concepts, methods, people, organizations, drugs, technologies, custom per domain. |
| **Relationship mapping** | Auto-discovered + user-defined relationships between entities and entries. |
| **Graph export** | `autoinfo knowledge graph --domain medical-research` — outputs JSON for visualization (D3.js, Gephi). Also GraphML format. |
| **Agent: query graph** | `query_knowledge_graph(entity="IVF", relation="developed_by")` → returns related entities with relationship types and source references. |
| **Incremental building** | Each collection run updates the knowledge graph with new entities and relationships. |

#### F23 — Knowledge Base as Asset ✅

*The accumulated knowledge base has standalone value beyond the collection pipeline.*

| UX Detail | Specification |
|-----------|---------------|
| **Asset principle** | The KB is the primary long-term asset. Real-time feed is temporary; the KB is permanent and grows in value over time. |
| **External KB compatible** | AutoInfo's KB output (`03-Wiki`) is designed to merge into or be consumed by an existing external KB (`docs/archive/kb-pipeline-reference.md`). Same Markdown + YAML frontmatter format, same pipeline tiers. |
| **Obsidian-native** | Markdown files with `[[wiki links]]` are Obsidian-compatible out of the box. User can open `knowledge/` as an Obsidian vault directly. |
| **Entry-level versioning** | Changes tracked per entry (git). Rollback supported. |
| **Shareability** | KB collections exportable: Markdown bundle, JSON, SQLite dump. |
| **Third-party integration** | KB consumable by Obsidian (Markdown + [[links]]), Notion (import), custom apps (JSON API). |
| **REST API (read-only)** | KB queryable via REST API for embedding into other tools. |
| **Monetization potential** | Curated KB collections (e.g., "IVF Research 2026 Weekly Digest") as pre-built assets. Not for v1. |

### 3.6 Phase 6: Output & Asset Creation

> "The knowledge base can produce valuable outputs — reports, tutorials, presentations."

#### F24 — Digest & Report Generation ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: generate digest** | `autoinfo output digest --domain medical-research --period week` — weekly digest of important findings |
| **Human: custom report** | `autoinfo output report --collection "IVF Protocols 2026" --format markdown` |
| **Agent: generate digest** | `generate_digest(domain="medical-research", period="week", format="markdown")`. |
| **Agent: discover templates** | `list_output_templates(domain="medical-research")` → returns `["digest", "report", "tutorial", "presentation"]`. Agent discovers what outputs a domain supports without trial and error. |
| **Digest structure** | Title, period, domain, summary, key findings (ranked by importance), full entries, trends observed, source list. |
| **Format options** | Markdown, HTML, PDF, JSON. Future: audio (TTS-rendered digest for podcast consumption). |
| **Role-aware content** | Both digest and report accept `target_audience` parameter: `generate_digest(domain, period, target_audience="executive")`. Audience options: `researcher` (technical depth), `clinician` (practical application), `executive` (strategic summary, key takeaways), `student` (educational, foundational). Content depth, terminology, and emphasis adapt to audience. |
| **Audio-ready output** | When `format="audio"`, the system renders digest text through TTS pipeline and outputs MP3 file. Supports podcast-style delivery: intro, section-by-section narration, outro with source credits. Audio format drives new delivery channels (podcast RSS feed, voice messaging via Telegram/WeChat). |

#### F25 — Tutorial & Presentation Generation ✅

| UX Detail | Specification |
|-----------|---------------|
| **Human: generate tutorial** | `autoinfo output tutorial --collection "IVF Protocols 2026" --audience clinician --format markdown` |
| **Human: generate presentation** | `autoinfo output presentation --topic "Latest IVF Research" --slides 10` |
| **Agent: generate tutorial** | `generate_tutorial(collection_id="...", target_audience="clinician")`. |
| **Tutorial structure** | Learning objectives, core content (sourced from KB), key takeaways, further reading (linked KB entries). |
| **Presentation structure** | Title slide, agenda, key finding slides (each sourced from KB), summary, references. Exportable as Markdown (Marp/slides) or PPTX. |
| **Audience adaptation** | Content depth adapts to audience: `researcher` (technical), `clinician` (practical), `executive` (strategic), `student` (educational). |

#### F26 — Export & Interoperability ✅

| UX Detail | Specification |
|-----------|---------------|
| **Export formats** | JSON, Markdown (with YAML frontmatter), CSV, PDF, SQLite dump, GraphML. |
| **Export scope** | Single entry, collection, domain, or full KB. |
| **Import** | Import from supported formats (JSON, Markdown with frontmatter, OPML for source lists). |
| **External tool integration** | Obsidian (Markdown with `[[wiki links]]`), Anki (flashcard export for language learning), JSON API for custom integrations. |
| **Agent: export** | `export_kb(format="obsidian", collection_id="...")` — returns file path or content. |

#### F27 — Product Delivery ✅

| UX Detail | Specification |
|-----------|---------------|
| **Delivery channels** | Multiple channels supported: SMTP email (HTML+plain MIME multipart), webhook push (HTTP POST per-item), REST API (FastAPI CRUD), local file output, bulk export. Future: RSS feed delivery (scheduled feed generation, subscribable by RSS readers and AI agents), agent push (webhook callback to agent endpoint for proactive agent notification). |
| **Scheduling mechanism** | External crond calls `autoinfo cron run`. No built-in scheduler. Two schedule types: `collection` and `digest`. |
| **Configurable cadence** | Daily/weekly/monthly digests. Per-domain or per-collection. |
| **RAW product delivery** | REST API endpoints for raw feeds per domain/topic/time; webhook streams for real-time item push; bulk export (JSON, CSV, SQLite). |
| **PROCESSED product delivery** | Scheduled digest emails (SMTP), thematic report push (webhook), alert streams (configurable thresholds per topic). |
| **Agent: manage delivery** | `send_email_digest(domain, period, recipients)`, `set_domain_webhooks(urls)`, `list_schedules()`, `add_schedule(type="digest", ...)`. |
| **RSS delivery channel** | `export_kb(format="rss")` generates RSS/Atom feed for any domain/topic. Feeds are subscribable by humans (RSS readers, podcast apps) and AI agents (feed polling). Scheduled RSS feed generation via cron: `add_schedule(type="rss", domain="medical")`. Audio-capable RSS feeds (podcast RSS) drive podcast distribution. |
| **Agent push delivery** | Agent registers a webhook callback URL: `set_agent_callback(url, events=["new_digest", "new_report"])`. AutoInfo pushes structured JSON to the callback when a product is generated for a subscribed topic. Enables the "agent subscription" pattern: agent registers interest, AutoInfo pushes product when ready. |
| **Newsletter recipient control** | `send_email_digest` accepts per-recipient configuration: `recipients=[{email, name, format_preference}]`. No per-subscriber segmentation in v1 — all recipients receive same content. Per-recipient targeting deferred to v2. |

#### F28 — RAW Product Generation (NEW) ✅

| UX Detail | Specification |
|-----------|---------------|
| **Definition** | RAW products are the collected information itself — original papers, reports, articles — delivered as-is to paying customers. |
| **RAW feed per domain** | REST API endpoint provides structured access to all collected items per domain/topic/time range. |
| **RAW bulk export** | CLI `autoinfo output export --domain X --format json/csv/sqlite` and MCP `export_kb()` for full data dumps. |
| **RAW real-time stream** | Webhook push (per-item on collection) for live feed consumption. |
| **Source traceability** | Every RAW item includes full provenance: `source_url`, `source_type`, `source_platform`, `collected_at`. |
| **RSS Feed as RAW product** | `export_kb(format="rss", domain="...", topic="...")` — generates RSS/Atom feed XML for any domain/topic/collection. Feed can be subscribed to by humans (RSS readers) or consumed programmatically by AI agents. |
| **Agent: serve RAW product** | `search_knowledge_base()`, `get_kb_entry()`, `export_kb(format="json"|"rss")`, webhook push on collect. |
| **Agent-native RAW delivery** | Agent serves RAW items directly in conversation via MCP tool output. User queries "what's new in medical research" → agent calls `search_knowledge_base()` → returns structured results with source citations. No separate delivery channel needed. |
| **Agent-native JSON format** | `generate_digest(domain, period, format="agent")` returns structured JSON-LD optimized for LLM re-consumption. Schema includes: `@context`, `@type: "KnowledgeDigest"`, `uuid`, `generated_at`, `domain`, `period`, `entries: [{uuid, title, tl_dr, source_url, source_platform, collected_at, relevance_score, confidence_score, entities: [{name, type, relation}], key_points: [str], full_text_summary, citations: [{source, url, accessed_at}]}]`, `trends: [{topic, direction, evidence}]`, `metadata: {entry_count, total_tokens, generation_model, quality_gates: [{name, passed}]}`. This format enables agents to parse, re-synthesize, store in their own KB, or combine with other data sources. |

#### F29 — PROCESSED Product Generation (NEW) ✅

| UX Detail | Specification |
|-----------|---------------|
| **Definition** | PROCESSED products are value-added, synthesized outputs — digests, reports, tutorials, presentations, alert streams. |
| **Digest bundles** | Scheduled (daily/weekly) synthesis of important findings per domain. LLM-generated with source citations. Delivered via SMTP email or webhook. |
| **Thematic reports** | On-demand or scheduled deep-dive reports on specific topics. Structured: executive summary, findings, analysis, references. |
| **Alert streams** | Configurable threshold-based notifications: new items matching topic → push to subscriber via webhook or email. |
| **Custom instructions** | `generate_digest(domain, period, custom_instructions="focus on clinical trials")` — LLM adapts output to subscriber preferences. |
| **Audience adaptation** | Content depth adapts to audience: `researcher` (technical), `clinician` (practical), `executive` (strategic), `student` (educational). |
| **RSS Feed as PROCESSED product** | `export_kb(format="rss", product_type="processed", domain="...")` — generated RSS feed contains LLM-synthesized digest entries rather than raw collected items. Enables agent and human subscription to curated PROCESSED content. |
| **Agent: generate PROCESSED** | `generate_digest()`, `generate_report()`, `generate_tutorial()`, `generate_presentation()`, `localize_content()`. All accept format, audience, custom_instructions params. |
| **Agent-native PROCESSED delivery** | Agent generates PROCESSED products and delivers them directly in conversation via MCP tool output. User says "给我这周的AI商业情报摘要" → agent calls `generate_digest(domain="ai-commercial", period="week")` → returns structured digest as tool result. No separate email client or webhook needed. Agent also proactively pushes: "本周AI商业有新动态，需要我生成简报吗？" |
| **Stored preference integration** | `UserProfile.delivery_preferences` (F36) feeds into PROCESSED generation: preferred format, timezone, quiet hours, max daily digests, channel priority. When generating for a specific end user, `generate_digest(user_id=usr_xxx)` reads preferences from the user profile and applies them automatically — no per-call `custom_instructions` or `format` needed. User preferences serve as defaults; per-call parameters override them. |

#### F30 — Subscription & Billing Infrastructure ✅

*This expectation covers B1.2 Subscribe lifecycle stage — the subscription record created at subscribe time contains the config fields defined in [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.3. B1.5 Modify Config (config changes) is a separate lifecycle stage covered by F67.*

| UX Detail | Specification |
|-----------|---------------|
| **Current status** | Implemented. Stripe integration (`create_checkout_session`, `handle_webhook`, subscription status), freemium access gating (`check_access()` in `billing.py`, enforced in `output.py`), usage metering (CostMeter in `cost.py`), the Stripe webhook REST endpoint, and stripe-mock dev setup are all coded. **Implemented (2026-08-05):** `POST /api/v1/webhook/stripe` at `src/autoinfo/api/server.py:453` (signature verification; dispatches `checkout.session.completed` / `customer.subscription.updated` / `invoice.paid` / `invoice.payment_failed` to `billing.py:handle_webhook()`); stripe-mock via `docker-compose.yml` + `make stripe-mock`. |
| **Feature gating** | Partially implemented: `check_access()` enforces free/premium/enterprise tiers in `output.py` for `generate_digest`/`generate_report`. MCP tool layer does not enforce gating (user_id optional). |
| **Usage metering** | Implemented: CostMeter tracks LLM tokens, storage, API calls per domain/user. `get_enduser_usage()` and `get_enduser_invoice()` map internal units to billable line items. |
| **Billing integration** | Implemented: Stripe checkout sessions and webhook handling coded in `billing.py`; webhook REST endpoint `POST /api/v1/webhook/stripe` in `api/server.py`; stripe-mock dev setup via Docker Compose (`docker-compose.yml`, `make stripe-mock`). Proactive Stripe invoice/charge creation from CostMeter remains future work. |
| **Delivery tracking** | Implemented: DeliveryLog per subscription with SLA tracking, bounce handling, retry chain. |
| **Customer portal** | CLI-based portal exists (`autoinfo portal preferences|history`). Web-based portal not implemented. |

### 3.7 Phase 7: Monitor

> "I can see what's been collected and how the system is doing."

#### F31 — Collection Overview ✅

> **Lifecycle cross-ref:** Supports B2.5 Monitor — collection status data feeds into B2's monitoring of pipeline execution. See [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §3.2 (B2.5 Monitor stage).

| UX Detail | Specification |
|-----------|---------------|
| **Human: status** | `autoinfo status` — summary: items collected today/this week, new KB entries, source health by domain. |
| **Agent: overview** | `get_collection_stats(period="week")` → `{domains: [{name, items_collected, items_new, kb_entries_added, source_health}]}`. |
| **Agent: diff since last run** | `get_collection_diff(domain="medical-research", since_collection_id="...")` → `{new_items: [{id, title, source, collected_at}], total_new: 15, from_collection: "2026-07-19T08:00:00Z", to_collection: "2026-07-20T08:00:00Z"}`. Agent queries "what changed since last time?" in one call instead of comparing lists manually. |
| **Proactive reporting** | Agent periodically summarizes: "本周医学领域收集 45 篇论文，新增 KB 12 条。AI商业领域 23 条案例。" |
| **Status per source** | `healthy`, `degraded` (slow/incomplete), `error` (unreachable), `paused` (user-disabled). |

#### F32 — Source Health Monitoring ✅

| UX Detail | Specification |
|-----------|---------------|
| **Automatic health check** | Each collection run tests source reachability. Degraded sources logged. |
| **Human: source health** | `autoinfo sources health` — all sources with status, last successful fetch, error history, response time. |
| **Agent: source health** | `get_source_health(source_id="pubmed")` → `{status, last_success, error_count, avg_response_time_ms}`. |
| **Alert on failure** | 3 consecutive failures → agent proactively reports. |

### 3.8 Phase 8: Iterate

> "I can improve the system without breaking existing behavior."

#### F33 — Source Handler Isolation ✅

| UX Detail | Specification |
|-----------|---------------|
| **Isolation guarantee** | Each source handler is independent. Adding a new handler doesn't affect existing ones. One source failing doesn't block others. |
| **Handler pattern** | Source handlers implement `BaseSourceHandler` interface. New source type = new class + register. |
| **Failure isolation** | Timeout or error in one source does not crash collection pipeline. Errors logged, source skipped. |

#### F34 — Forward Compatibility ✅

| UX Detail | Specification |
|-----------|---------------|
| **Scope: v1** | New code can read old KB data. KB entry schema (YAML frontmatter + body) is stable. |
| **Readability guarantee** | KB format, collection output format, and config schema are versioned. New versions maintain backward compat. |
| **Breaking changes** | If structural changes necessary: (1) deprecation period with dual-format support, (2) migration tool. |

#### F36 — End User Profile & Subscription Registration ✅

*Covers B1.2 Subscribe. The NL→Config pipeline (B1 speaks NL → Agent + LLM parses → structured config) is the interaction layer; the profile/subscription records are the storage layer. See [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.1 for the full NL→Config pipeline design.*

| UX Detail | Specification |
|-----------|---------------|
| **End User identity** | End User = Paying Customer (same person). No distinction between "consumer" and "payer" — the subscriber pays for and consumes the product. |
| **Profile fields** | `user_id`, `name`, `email`, `telegram_id` (optional), `wechat_oa_openid` (optional), `wechat_work_userid` (optional), `dingtalk_userid` (optional), `discord_userid` (optional), `preferred_locale` (zh/en), `timezone`, `created_at`, `updated_at` |
| **Subscription intent fields** | `required_domains: list[str]` — which domains the user subscribes to (mandatory). `optional_platforms: list[str]` — delivery channels the user enables (empty = default channel only). Budget range or tier preference (free vs RAW Pro vs PROCESSED Pro vs Enterprise). |
| **CRUD** | MCP tools: `create_end_user`, `get_end_user`, `update_end_user`, `delete_end_user`, `list_end_users`. CLI equivalents for human direct-users. Bulk import for onboarding. |
| **Validation** | At least one delivery channel must be configured. At least one domain must be subscribed. Email is mandatory (fallback channel). |

#### F37 — Multi-Channel Delivery Configuration ✅

| UX Detail | Specification |
|-----------|---------------|
| **Supported channels** | Email (mandatory), Telegram Bot, WeChat Official Account, WeChat Work, DingTalk, Discord Bot |
| **Channel capability** | Email — Rich HTML, plain text fallback, attachments (PDF digests), threading by subject. Telegram — Markdown message, inline buttons for navigation, file uploads. WeChat OA — Rich article (图文消息), template message. WeChat Work — Markdown message, file upload, interactive card. DingTalk — Markdown message, action card, feed card. Discord Bot — Embed message, file attachment, slash command interaction. |
| **Per-channel opt-in** | End user selects which channels to activate. Each channel has its own configuration (e.g., Telegram chat_id, WeChat OA openid). Agent validates reachability before activation. |
| **Default channel** | Email is always active as the fallback delivery channel. At least one channel must remain active at all times. |
| **Product-to-channel mapping** | Certain products route to specific channels by type: short alerts → Telegram/WeChat Work/DingTalk (instant), daily digests → Email + optional push channel, weekly reports → Email (primary) + optional secondary channel. Configurable per subscription. |
| **Channel capacity limits** | Per-channel rate limits: Telegram (30 msg/s per bot), WeChat OA (unlimited via template), WeChat Work (unlimited), DingTalk (unlimited), Discord (5 msg/s per webhook). Agent queues and batches deliveries respecting each platform's constraints. |

#### F38 — End User Lifecycle State Machine ✅

| UX Detail | Specification |
|-----------|---------------|
| **States** | `trial` → `active` → `suspended` → `cancelled`. Transitions: `trial→active` (payment confirmed), `active→suspended` (payment failed / grace period), `active→cancelled` (explicit cancellation), `suspended→active` (payment resolved), `suspended→cancelled` (grace period expired). |
| **Trial period** | Configurable duration (default: 14 days). Full product access during trial with watermark/attribution on outputs. Direct User (agent) can extend trial per end user. |
| **Grace period** | 7 days after payment failure. Products continue delivery during grace. Alert sent to end user on day 1, 3, 7. After expiry → `cancelled`, all deliveries stop. |
| **State transition hooks** | On `trial→active`: send welcome message via all configured channels. On `active→cancelled`: send goodbye message, offer re-activation link. On `active→suspended`: send payment reminder with link. On `suspended→active`: send confirmation of restored delivery. |
| **Re-activation** | Cancelled users can re-activate within 90 days with full history preserved. After 90 days, profile is archived (data retained per GDPR/privacy policy). |

#### F39 — Delivery Reliability & Logging ✅

| UX Detail | Specification |
|-----------|---------------|
| **Delivery confirmation** | Each delivery attempt records: `subscription_id`, `product_id`, `channel`, `status` (queued/sent/delivered/failed/bounced), `attempted_at`, `confirmed_at`, `error_message`. Email: SMTP delivery receipt. Telegram: API response with message_id. Other channels: webhook callback or API response. |
| **Bounce & failure handling** | Hard bounce (invalid address) → mark channel inactive, alert end user and Direct User. Soft bounce (temporary) → retry 3x with exponential backoff (5min, 15min, 1hr). After 3 consecutive soft bounces → suspend delivery for that channel, attempt fallback channel. |
| **Retry chain** | If primary channel fails: try fallback channel (alternate channel from user's preferences). If all channels fail: queue product for next delivery window, alert Direct User. Never silently drop a product. |
| **Per-subscriber delivery log** | MCP tool `get_delivery_log(subscription_id, period)` — returns delivery history with status per product per channel. Agent can query for troubleshooting. End user can view via portal (F40). |
| **Delivery SLA targets** | P0 (digests, alerts): ≤5min from generation to first delivery attempt. P1 (reports, exports): ≤30min. P2 (bulk): ≤2hr. SLA tracking per subscription, alert agent on repeated SLA misses. |

#### F40 — End User Self-Service Portal ✅

| UX Detail | Specification |
|-----------|---------------|
| **Portal scope** | Web-based self-service: manage profile, update delivery preferences, view subscription status, browse delivery history, download past products, manage billing/payment methods. |
| **Authentication** | Email-based magic link (no password). Link expires in 15 minutes. Session token valid for 7 days. Optional: social login (WeChat OAuth, Telegram OAuth) for push-channel users. |
| **Delivery preference management** | End user can enable/disable channels, update channel IDs (e.g., new Telegram chat_id), change product-to-channel routing preferences, set quiet hours (don't deliver 22:00-08:00 in user's timezone). |
| **Product archive** | All delivered products accessible for 90 days (trial) or subscription duration + 30 days. Searchable by date, domain, product type, channel. Download in original format. |
| **Direct User (agent) overrides** | Agent can update any profile field or subscription state on behalf of the end user (with `updated_by: agent` audit trail). Agent cannot delete an end user — only deactivate. Human Director User can delete. |

### 3.9 Phase 9: Cost Governance

> "I can track and manage the costs of operating AutoInfo, both internally and for end users."

#### F41 — Internal Cost Metering ✅

| UX Detail | Specification |
|-----------|---------------|
| **Cost units tracked** | LLM tokens (input + output per model), storage bytes (KB entries + collections + indexes), API calls (source API calls, LLM API calls). These are internal metering units — NEVER exposed to end users as billing units. |
| **Metering granularity** | Per-domain, per-end-user (if attributable), per-pipeline-stage. LLM costs broken down by task type (extraction, summarization, synthesis, quality check, embedding). |
| **Storage model** | Append-only cost log: `cost_log_id, timestamp, domain, user_id?, stage, cost_unit, quantity, unit_price_estimate, total_cost_estimate`. Written asynchronously to avoid blocking pipeline. |
| **Unit prices** | Pre-populated default prices: DeepSeek Chat $0.15/M input $0.60/M output, Claude Sonnet $3/M input $15/M output, text-embedding-3-small $0.02/M. User can override in config to reflect actual provider pricing. |
| **MCP tool** | `cost_dashboard(period)` — returns totals by domain, daily trend, top models/sources, and budget status. Agent queries to answer "what did medical research cost me this month?" |
| **CLI** | `autoinfo cost --domain <domain> --period <period> --group-by <dimension>` — human-direct equivalent. |

#### F42 — External Billing Model ✅

| UX Detail | Specification |
|-----------|---------------|
| **Billing model** | Partially implemented. Hybrid base+overage model specified. CostMeter tracks usage per domain/user. `get_enduser_invoice()` generates invoice-like summaries. Actual Stripe invoice creation and automated charging not connected. |
| **Overage units** | Usage units (items, API calls, storage) tracked in `cost.py`. Not connected to actual overage billing or Stripe metering. |
| **Tier structure** | Free/trial → RAW Pro → PROCESSED Pro → Enterprise tiers specified. `check_access()` enforces in output generation. No subscription tier gating in MCP layer. **Implemented (2026-09 concierge wave):** configurable free-tier quotas (`free_tier` config section: max_domains=1, max_products=1, frequency=weekly) enforced at `generate_digest`/`generate_report` entry (only when user_id is non-empty) and at cron add-delivery via a frequency gate, returning `FREE_TIER_LIMIT` on violation; `check_access()` remains the boolean content gate. |
| **Conversion layer** | Partially implemented: CostMeter maps internal costs to product billing units. Conversion factors domain-configurable in `cost.py`. Not wired to Stripe pricing API. |
| **Invoice structure** | Partially implemented: `get_enduser_invoice()` itemizes charges. No automated monthly invoice generation or Stripe Invoice API calls. |
| **MCP tool** | `get_enduser_usage`, `get_enduser_invoice`, and `get_billing_summary` all exist. **Implemented (2026-08-05):** `get_billing_summary` registered at `src/autoinfo/mcp/server.py:9782`, dispatched at line 10560, handler `_handle_get_billing_summary` at line 5397. |
| **CLI** | `autoinfo billing summary|usage|invoice` implemented; `autoinfo cost dashboard` and `autoinfo cost allocation` also provide cost views. **Implemented (2026-08-05):** `billing` CLI group added. **Implemented (2026-09 concierge wave):** `autoinfo billing create-free --user-id X` provisions a free-tier user. |

#### F43 — End-User Cost Dashboard ✅

| UX Detail | Specification |
|-----------|---------------|
| **Dashboard scope** | Per-product itemized cost display within the self-service portal (F40). Shows current period charges, usage vs tier limits, and historical billing. |
| **Default view** | Aggregated: total current charges, next billing date, usage bars (collected items / storage / API calls) against tier limits. No drill-down required for typical users. |
| **Expandable detail** | Click to expand: per-domain charges, per-product-type charges, daily usage timeline. Individual line items for overage (e.g., "450 items over limit @ $0.02 = $9.00"). |
| **Data freshness** | Usage data updated daily (batch). Current-period charges are estimates until period-end invoice is final and binding. |
| **Agent assistance** | Agent can query and explain charges conversationally: "Your medical research digest overage was due to 500 items exceeding your 200-item tier limit." |
| **Cost transparency** | Dashboard always distinguishes between "base fee" (fixed) and "overage" (variable). Never hides overage charges. |

#### F44 — Cost Allocation ✅

| UX Detail | Specification |
|-----------|---------------|
| **Allocation model** | Shared costs (LLM API fees, storage, compute) attributed across domains and end users proportionally. Three configurable strategies: pro-rata (equal split across active domains), usage-based (proportional to consumption per domain), direct (cost definitively tied to specific domain/user). |
| **Per-domain attribution** | LLM extraction costs attributed to domain where item was processed. Shared LLM synthesis (digest generation) allocated across all domains that contributed items. Storage attributed by entry count per domain. |
| **Per-end-user attribution** | Direct costs (items collected for user's subscribed domains) attributed directly to end user. Shared costs (platform overhead, shared synthesis) allocated by subscription tier weight or pro-rata across active users. |
| **Configuration** | `cost_allocation.strategy: usage_based` in global config. Overridable per domain. Allocation method logged in cost audit trail. |
| **MCP tool** | `cost_allocation(domain, user_id, period)` — returns cost breakdown per domain and per end user with allocation method and rule identifier. |

#### F45 — Budget Alerts & Cost Control ✅

| UX Detail | Specification |
|-----------|---------------|
| **Threshold types** | Absolute spend limit (cost > $X), rate-based (spend/month > $Y), projected overrun (current run-rate extrapolated to period end > $Z). Thresholds per domain, per end user, or global. |
| **Alert channels** | Agent notification (MCP tool return warning with details), email to operator (scheduled, not real-time), dashboard banner in portal. Configurable per threshold rule. |
| **Alert events** | LLM spend approaching monthly budget (80%, 90%, 100% thresholds), storage nearing limit (80%, 90%, 100%), unexpected cost spikes (>2x previous period), end-user overage approaching subscription cap. |
| **Auto-remediation actions** | Configurable per alert: pause collection for domain, switch to cheaper LLM model for non-critical tasks, skip G4 quality check on low-priority items, notify agent with suggested actions. |
| **Configuration** | `cost_alerts:` block in config.yaml. List of alert rules with type, threshold, action, channel. Agent configures via `set_budget_thresholds` MCP tool. |
| **MCP tool** | `set_budget_thresholds(thresholds, auto_remediation_enabled, alert_webhook)` — update budget threshold percentages. `get_budget_thresholds()` — list active threshold configuration. |

### 3.10 Phase 10: Data Privacy

> "I can trust AutoInfo with sensitive or licensed data, knowing it handles sources and user information responsibly."

#### F46 — Source ToS Compliance ✅

| UX Detail | Specification |
|-----------|---------------|
| **Terms disclaimer** | On source creation, agent presents source terms: "PubMed API: research use only, attribution required." User acknowledges before collection begins. Acknowledgment recorded in audit log. |
| **Source classification** | Each source tagged with access tier: **Open** (public data, no restrictions) → full raw content redistributable. **Licensed** (API ToS applies, attribution required) → raw stored internally, only processed output delivered. **Restricted** (paywalled, credential required) → requires user credentials, only aggregated output. **Sensitive** (PII, internal data) → requires data handling acknowledgment, raw content encrypted at rest. |
| **Output control** | Licensed/Restricted/Sensitive sources: only processed output (summaries, structured extracts, aggregated insights) is deliverable to end users. Raw content never leaves internal storage. Enforced at delivery gate D2. |
| **Attribution in outputs** | Generated digests/reports from licensed sources include: "Content derived from [source] under their terms of service." Configurable attribution template per source type. |
| **Compliance checkpoint** | G1 gate extended: source tier classification verified at collection time. If source tier and output tier are incompatible (e.g., trying to deliver raw items from a Licensed source), the pipeline blocks with a clear compliance error. |

#### F47 — Data Deletion & Retention ✅

| UX Detail | Specification |
|-----------|---------------|
| **Soft-delete model** | Delete operations on KB entries mark `status: deleted` with `deleted_at` timestamp and `deleted_reason`. Data NOT physically removed — fully recoverable within retention window. |
| **MCP tools** | `soft_delete_entry(entry_id, reason)` — marks entry as deleted with audit reason. `restore_entry(entry_id)` — recovers entry within retention window. `export_user_data(user_id)` — exports all data for a user (GDPR compliance). |
| **Permanent deletion** | Only `--purge` flag on CLI or explicit Director User action triggers physical deletion. Agent cannot purge. `delete_user_data(user_id, scope)` — available for compliance requests with confirmation step. |
| **30-day auto-cleanup** | Soft-deleted entries older than 30 days auto-purged by scheduled cleanup job (`autoinfo clean --purge-expired`). Configurable retention period per domain. |
| **Retention by subscription tier** | Trial: 14-day post-cancellation retention. Active: full retention for subscription duration + 30 days. Archived: 90-day post-cancellation retention. Purged entries are logged in audit trail with deletion confirmation. |

#### F48 — Audit Logging ✅

| UX Detail | Specification |
|-----------|---------------|
| **Scope** | All agent operations logged: MCP tool calls (actor, tool, parameters, result), pipeline executions (collect/process/deliver per run), configuration changes (domain/source/topic CRUD), user management actions, billing/cost operations. |
| **Log schema** | `audit_log_id, timestamp, actor_type (agent|human|system), actor_id, action, resource_type, resource_id, details (JSON with secrets redacted), result (success|failure|blocked), session_id`. Immutable append-only log. |
| **Agent operations** | Every MCP tool call recorded: tool name, parameters (API keys and tokens redacted), result status, duration. Actor identity from MCP session metadata. |
| **Human operations** | CLI commands logged: command name, arguments (secrets redacted), exit code. Portal actions logged via FastAPI middleware. |
| **Retention** | Audit logs retained per tier (authoritative from `operations.md` §2.5): Free 90 days, Premium 90 days, Enterprise 180 days. Exportable via `query_audit_log()` or CLI `autoinfo audit`. |
| **MCP tool** | `query_audit_log(filters)` — search audit log by actor, action, resource, time range. Returns paginated results with total count. |
| **CLI** | `autoinfo audit --actor <actor> --action <action> --since <date>` — human-direct audit trail browsing with JSON output support. |

### 3.11 Phase 11: Knowledge Lifecycle

> "The knowledge base stays fresh and relevant — old content is gracefully aged, not forgotten."

#### F49 — Per-Domain TTL ✅

| UX Detail | Specification |
|-----------|---------------|
| **TTL definition** | Configurable freshness period per domain: how long a collected item remains "fresh" before being considered "stale." Measured from `collected_at` date. Configurable per topic within domain for finer granularity. |
| **Default TTLs** | Medical research: 180 days (seminal papers remain relevant for months). AI commercial intelligence: 30 days (rapidly evolving landscape). Financial intelligence: 7 days (time-sensitive data). General/default: 90 days. |
| **Configuration** | `ttl_days: 180` in domain config. Optional per-topic override: `topics: [{name: "IVF", ttl_days: 90}]`. |
| **TTL mechanics** | TTL does NOT delete entries. It controls freshness scoring for search ranking and default inclusion in output generation. An entry older than its domain TTL is "stale" but fully accessible via direct lookup or explicit flags. |
| **Expiration behavior** | Stale entries excluded from digest/report generation by default. Agent can explicitly include with `--include-stale` flag. Stale entries remain searchable but demoted (F51). |

#### F50 — Versioned Re-collection ✅

| UX Detail | Specification |
|-----------|---------------|
| **Version model** | Same `source_url` collected again → new version created automatically. Previous version retained with full history. Version tracking via git (already exists for 03-Wiki, extends to 01-Raw). |
| **Version metadata** | Each KB entry tracks: `version: int` (starting at 1), `previous_version_id: UUID?` (link to prior version), `collected_at: datetime`, `updated_at: datetime`. Frontmatter includes all version fields. |
| **Re-collection flow** | Collection pipeline detects existing entry with same `source_url` → creates versioned Raw entry (`knowledge/<domain>/01-Raw/<collection>/<slug>_v2.md`) → links to previous version in frontmatter (`previous_version: <uuid-v1>`). |
| **Version comparison** | MCP tool `compare_versions(entry_id, v1, v2)` — returns structured diff: title changes, summary changes, key point additions/removals. Agent uses to highlight "what changed since last collection." |
| **History pruning** | Retain last N versions per entry (configurable, default: 10). Older versions archived to compressed storage after 90 days. Never automatically deleted without explicit purge. |

#### F51 — Stale Content Handling ✅

| UX Detail | Specification |
|-----------|---------------|
| **Stale marking** | Entries past domain TTL are automatically marked `freshness: stale` with `staleness_date: <date>`. Marked during processing pipeline or on-demand via `refresh_staleness()` MCP tool. |
| **Search demotion** | Stale entries ranked lower in hybrid search. Freshness score contributes 20% to overall relevance ranking. Configurable via `search.freshness_weight: 0.2` in domain config. |
| **Preservation principle** | Stale entries are NEVER deleted. They remain fully accessible via direct entry lookup, explicit search with `--include-stale`, or archived KB view. User or agent must explicitly delete. |
| **Default visibility** | Standard views (digest generation, summary lists, API feeds) exclude stale entries by default. `--include-stale` flag overrides. Admin views display stale entries with visual indicator (e.g., 🟡 stale badge). |
| **Re-fresh on re-collection** | When same source is collected again (F50), the new version supersedes the old. The old entry's staleness status becomes irrelevant — it is superseded rather than stale. |

#### F52 — Domain Decay Metrics ✅

| UX Detail | Specification |
|-----------|---------------|
| **Staleness ratio** | `stale_entries / total_entries` per domain. Measures what fraction of the domain knowledge base is past its TTL. |
| **Avg remaining TTL** | Average days until entries in domain go stale: `sum(ttl_remaining_days) / total_entries`. Negative values indicate entries past their TTL. |
| **Collection freshness** | Days since domain was last collected: `now() - max(collected_at)`. Indicates whether the domain is being actively maintained. |
| **Decay grade** | Composite of staleness ratio + collection freshness: Green (healthy), Yellow (aging), Red (stale). Displayed in `autoinfo status --domains` and MCP `get_collection_stats()`. |
| **Agent alert** | When staleness ratio exceeds configurable threshold (default: 50%), agent proactively suggests re-collection: "Medical research domain is 60% stale. Recommend re-collection." |
| **MCP tool** | `get_domain_decay(domain)` — returns staleness ratio, avg remaining TTL, decay grade, and suggested actions. |

#### F53 — Cross-Collection Dedup & Merge ✅

| UX Detail | Specification |
|-----------|---------------|
| **URL dedup across runs** | Same source URL collected in different runs → detected via exact URL match. Existing entry gets versioned update (F50). |
| **Cross-source similarity detection** | Items from different sources covering same content → detected via: (1) title TF-IDF cosine similarity > 0.85, (2) content sentence-level Jaccard similarity > 0.7. Flagged as potential cross-source duplicates. |
| **LLM-assisted merge** | When cross-source duplicates confirmed, agent can invoke `merge_items(primary_id, secondary_ids, mode)` → LLM consolidates metadata (combines sources, reconciles field differences, preserves both source provenance URLs). |
| **Merge result** | New KB entry with `merged_from: [uuid1, uuid2]`, `sources: [source1, source2]`, consolidated title/summary/key points, combined entity list. Original entries marked `status: superseded` with `superseded_by: new_uuid`. |
| **Trust boundary** | Merged entries are Draft-tier (promoted by the agent via `promote_kb_draft`, no human gate). Agent cannot auto-merge into Wiki. Merge decision is logged in audit trail with full rationale. |
| **MCP tools** | `find_similar_items(entry_id, threshold)` — scan KB for similar entries by title + content similarity. `merge_items(primary_id, secondary_ids, mode)` — merge with auto (LLM-driven) or manual (keep primary) mode. |

### 3.12 Phase 12: Operational Observability

> "I can see what the system is doing, trace any item through the pipeline, and diagnose issues efficiently."

#### F54 — Structured Pipeline Logging ✅

| UX Detail | Specification |
|-----------|---------------|
| **Log format** | JSON structured log lines, one per pipeline event. Written to `~/.autoinfo/logs/pipeline-YYYY-MM-DD.json` with daily rotation. |
| **Log schema** | `{"timestamp": ISO8601, "level": "INFO"|"WARN"|"ERROR", "trace_id": "uuid", "stage": "collect"|"process"|"deliver", "domain": "medical", "source": "pubmed", "item_id": "uuid?", "action": "...", "duration_ms": 1234, "status": "success"|"failure", "error": null, "metadata": {...}}` |
| **Stage coverage** | Collect: item fetched from source, dedup result, cache written. Process: extraction start/complete, each quality gate result (pass/fail/retry with reason), KB write confirmation. Deliver: product generation, per-channel dispatch attempt, delivery confirmation or failure. |
| **Log level control** | Configurable per stage: `logging.collect.level: DEBUG`, `logging.process.level: INFO`. Default: INFO. DEBUG includes LLM request/response payloads (prompts, completions). |
| **Viewing** | `autoinfo logs --stage collect --domain medical --since 1h` — tail/filter structured logs with colorized output. `--json` for machine parsing. `--follow` for live tail. |
| **Retention** | 30 days of pipeline logs retained. Older logs automatically archived or deleted (configurable). |

#### F55 — Per-Item Traceability ✅

| UX Detail | Specification |
|-----------|---------------|
| **Trace ID** | UUID generated at collect time for each collected item. Propagated through entire pipeline: collect → cache → extract → quality gates → KB entry → product generation → delivery channel dispatch. |
| **Trace storage** | Append-only trace log: `trace_id, stage, timestamp, status, duration_ms, metadata`. Indexed by trace_id for sub-millisecond lookup. |
| **Trace visualization** | `autoinfo trace <trace_id>` — displays timeline of a single item's journey: when collected from which source, extraction duration, which gates passed or failed, which KB entry was created, which products included it, delivery status per channel. |
| **Error trace** | If item fails at any pipeline stage: trace includes error type, error message, retry attempts and outcomes, final resolution (skipped/blocked/failed). Failed item traces preserved for post-mortem diagnostics. |
| **MCP tool** | `trace_item(trace_id)` — returns full item trace with all stages, statuses, and timestamps. Agent uses for support: "Why wasn't paper X in yesterday's digest?" → trace shows it failed quality gate G3 (low relevance). |

#### F56 — Enhanced Diagnostics ✅

| UX Detail | Specification |
|-----------|---------------|
| **Command** | `autoinfo doctor --verbose` — comprehensive system diagnostics extending the basic health check. |
| **Verbose output** | Recent pipeline runs (last 10 per domain: collection + processing + delivery), error rates per source per stage (trend over 7 days), latency p95/p99 per stage per domain, cost summary (LLM spend per domain this period), KB health (entry count per tier, stale ratio, storage size in MB). |
| **Data sources** | Aggregated from: audit log (F48), pipeline logs (F54), trace store (F55), cost log (F41). |
| **Health score** | Composite health score (0-100) per domain and overall. Factors weighted: source availability (30%), error rate (25%), pipeline latency (20%), staleness ratio (15%), budget status (10%). |
| **MCP tool** | `diagnose_system(verbose=true)` — when `verbose=true`, returns full diagnostic report as structured JSON instead of basic health summary. |
| **Remediation suggestions** | `doctor --verbose` includes actionable suggestions derived from health data: "PubMed API returned 3 errors in 24h — check API key validity or network connectivity." "Medical research domain is 60% stale — consider re-collection (run `autoinfo collect --domain medical`)." |

#### F57 — Metrics Export ✅

| UX Detail | Specification |
|-----------|---------------|
| **Command** | `autoinfo status --metrics` — exports system health and usage indicators as structured JSON to stdout. |
| **Metrics schema** | `{"timestamp": ISO8601, "domains": [{"name": "medical", "items_collected_24h": 42, "items_processed_24h": 38, "kb_total": 1200, "kb_stale": 180, "avg_ttl_remaining_days": 85, "llm_spend_30d": 28.50, "error_rate_7d": 0.02, "p95_collect_latency_ms": 3400, "p95_process_latency_ms": 8500}], "global": {"total_items": 5200, "total_entries": 2800, "active_users": 5, "total_llm_spend_30d": 45.20, "pipeline_health": "healthy"}}` |
| **Prometheus endpoint** | Optional: `http://localhost:8741/metrics` in Prometheus text format. Feature-gated: `metrics.enable_prometheus: true` in config. Standard metric names (`autoinfo_items_collected_total`, `autoinfo_llm_spend_usd`, etc.). |
| **Use cases** | External monitoring (Grafana dashboards), automated cost tracking, SLA reporting to enterprise customers, capacity planning for storage and LLM budget. |
| **MCP tool** | `get_metrics(domain=None)` — returns metrics JSON for agent consumption. Agent uses for proactive reporting: "This month: 5200 items collected across 5 active domains, \$45.20 total LLM spend." |

### 3.13 Phase 13: Blank Spaces (Cross-Dimensional Gaps)

> "Concepts that were never designed — no spec, no code, no MCP tools. These are the blank spaces discovered during the cross-dimensional gap analysis (Dimension A: Pipeline Value Chain × Dimension B: User Types × Lifecycle Stages). Each maps to a Type 1 gap in the cross-dimensional gap catalog."
>
> **Source:** [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) §2, Type 1: Never Designed / Blank Spaces (CD-001..CD-006, CD-010).

#### F58 — Multi-Tenancy Isolation ❌

*No tenant isolation model. `user_id` fields exist on entries but there is no tenant context, no data isolation boundary, no cross-tenant access control. All KB entries share one SQLite database.*

> **Cross-ref:** CD-001 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md).

| UX Detail | Specification |
|-----------|---------------|
| **Context** | AutoInfo stores all users' KB entries in a single SQLite database. `user_id` fields exist on entry schemas but are advisory, not enforced. No query filters by tenant. No access control prevents one user from seeing another's data if a query is crafted to bypass the user_id filter. |
| **User flow** | Director User onboards a second tenant. Today: both tenants share the same KB, same collections, same search results. There is no way to partition data, no per-tenant config, no tenant-scoped source or topic isolation. |
| **Rationale** | Multi-tenant isolation is a prerequisite for commercial multi-customer deployment. Without it, AutoInfo can only serve a single tenant per instance. Enterprise customers require data isolation guarantees before adoption. |
| **Acceptance criteria** | (1) Tenant entity model with CRUD. (2) All KB entries, collections, sources, topics, subscriptions scoped to a tenant_id. (3) All MCP tools and REST API endpoints enforce tenant context — no cross-tenant data access. (4) Per-tenant config isolation (LLM keys, schedules, alert rules). (5) Tenant provisioning and deprovisioning workflow. |
| **Dependencies** | F59 (End-User Authentication) — tenant identity requires user identity. F20 (KB Storage) — schema migration to add tenant_id enforcement. Data model changes in `data-models.md`. |
| **Deferred scope** | Per-tenant compute quotas, per-tenant LLM cost caps, tenant-to-tenant data sharing APIs, tenant hierarchy (sub-tenants under a parent org). |

#### F59 — End-User Authentication ❌

*No authentication system. No login, no sessions, no OAuth, no magic links. The CLI portal uses no auth. The REST API has no auth (localhost security only). End users are identified by manual ID assignment.*

> **Cross-ref:** CD-002 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md). Related: AUD-05, G15.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | End users are identified by a direct `enduser_id` parameter passed to MCP tools. `activate_trial()` takes an `enduser_id` with no identity verification. `send_to_enduser` takes an ID with no session context. The REST API has no auth (localhost security only). The CLI portal (`autoinfo portal`) uses no authentication at all. |
| **User flow** | End user wants to access their portal. Today: they cannot. There is no login page, no magic link, no OAuth flow. An operator must manually pass the user's ID to every tool call. End users have no way to self-serve their profile, preferences, or delivery history without operator intervention. |
| **Rationale** | Without authentication, end users cannot self-serve. Every action requires operator intervention. This blocks the self-service portal (F40), the end-user cost dashboard (F43), and any consumer-facing product. Authentication is the identity foundation for the entire end-user lifecycle. |
| **Acceptance criteria** | (1) Email-based magic link authentication (no password). Link expires in 15 minutes, session token valid for 7 days. (2) Optional social login (WeChat OAuth, Telegram OAuth) for push-channel users. (3) Session management with token refresh. (4) All REST API endpoints require auth token (except `/health`). (5) MCP tools accept session context for user-scoped operations. (6) Password reset / magic link regeneration flow. |
| **Dependencies** | F58 (Multi-Tenancy Isolation) — auth resolves to a tenant + user. F40 (End User Self-Service Portal) — portal requires auth. Email sending (F27) for magic link delivery. |
| **Deferred scope** | SSO/SAML for enterprise tenants, MFA/2FA, role-based access control (RBAC) beyond admin vs end-user, API key management for programmatic access, session revocation admin UI. |

#### F60 — Rate Limiting & Abuse Prevention ❌

*No rate limiting on any API surface (MCP, REST API, CLI). No per-tenant or per-user request quotas. No backpressure mechanism. A single user can saturate all resources.*

> **Cross-ref:** CD-003 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md).

| UX Detail | Specification |
|-----------|---------------|
| **Context** | `collect_sources`, `process_collection`, and all MCP tools have zero rate limiting code. `batch_run` has no concurrency cap. The REST API has no rate limiting middleware. A single user or agent can trigger unlimited collection runs, exhausting LLM API quotas, source API rate limits, and local compute resources. |
| **User flow** | Agent calls `collect_sources` in a tight loop. Today: each call spawns a full collection run with no throttle. LLM API quota is exhausted. Source APIs (PubMed, arXiv) may IP-ban the instance. No backpressure tells the agent to slow down. |
| **Rationale** | Without rate limiting, a single misconfigured agent or abusive user can take down the entire instance. Source APIs (PubMed 3 req/s, arXiv 1 req/3s) will IP-ban AutoInfo if rate limits are exceeded. LLM API costs can spike uncontrollably. Rate limiting is a production prerequisite. |
| **Acceptance criteria** | (1) Per-user and per-tenant request quotas on MCP tools and REST API. (2) Per-source rate limiting respecting each source's ToS (PubMed 3 req/s, arXiv 1 req/3s, etc.). (3) `batch_run` concurrency cap (configurable, default 5). (4) Backpressure: 429 Too Many Requests with Retry-After header on REST API. (5) MCP tools return rate limit warnings in tool result metadata. (6) Configurable quotas per subscription tier. |
| **Dependencies** | F59 (End-User Authentication) — rate limits are per-user. F58 (Multi-Tenancy Isolation) — quotas are per-tenant. Source handler infrastructure (F13). |
| **Deferred scope** | Adaptive rate limiting based on system load, circuit breaker pattern for source APIs, per-IP rate limiting (vs per-user), distributed rate limiting (for multi-node deployment), rate limit bypass tokens for admin operations. |

#### F61 — Cron Reliability & Backup ❌

*Cron scheduling exists but there is no: missed-schedule detection, cron failure alerts, backup of cron jobs, fallback mechanism if cron daemon fails. No crond health monitoring.*

> **Cross-ref:** CD-004 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md).

| UX Detail | Specification |
|-----------|---------------|
| **Context** | `schedule.py` uses `croniter` + `subprocess` to install crontab entries. No health checks on cron execution. No `get_schedule_status` MCP tool (spec'd but not registered). If the cron daemon fails, scheduled collections silently stop. No alert is sent. No missed-schedule detection. No backup of cron job definitions. |
| **User flow** | Director User sets up a daily medical collection schedule. Cron daemon crashes or server reboots. Today: collection silently stops. No alert. The director discovers the gap weeks later when the KB is stale. No way to backfill missed runs. No way to know cron failed without manually checking. |
| **Rationale** | Scheduled collection is the backbone of automated information tracking. If cron fails silently, the KB goes stale, products stop delivering, and users churn. Cron reliability is a P0 operational requirement. Without it, the system cannot be trusted for production use. |
| **Acceptance criteria** | (1) `get_schedule_status` MCP tool registered and functional — returns last run, next run, last status, failure count. (2) Missed-schedule detection: if a schedule misses its window by >2x the interval, alert fires. (3) Cron failure alerts via notification framework (F63). (4) Cron job definition backup and restore. (5) Backfill mechanism for missed runs (`run_schedules --backfill-since <timestamp>`). (6) Crond health check in `diagnose_system()`. |
| **Dependencies** | F63 (Unified Notification Framework) — alerts need a notification system. F55 (Per-Item Traceability) — schedule execution should be traceable. F56 (Enhanced Diagnostics) — cron health in diagnostics. |
| **Deferred scope** | Distributed cron (multi-node with leader election), cron job dependencies (run B only after A succeeds), cron job versioning, cron execution sandboxing, per-tenant cron isolation. |

#### F62 — Admin Dashboard ❌

*No web-based admin console exists. The only dashboards are CLI (`autoinfo status`, `autoinfo cost dashboard`) and MCP tools. No visual overview of system health, user activity, collection status, delivery metrics.*

> **Cross-ref:** CD-005 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md).

| UX Detail | Specification |
|-----------|---------------|
| **Context** | No admin routes in the FastAPI server. The Web UI Dashboard (Bootstrap 5) exists but shows only collection stats and KB search — no admin functions. There is no visual overview of: system health, active users, collection status, delivery metrics, cost trends, error rates, source health across all domains. Directors must use CLI or MCP tools piecemeal. |
| **User flow** | Director User wants a system overview. Today: they run `autoinfo status`, `autoinfo cost dashboard`, `autoinfo doctor --verbose`, and call multiple MCP tools (`diagnose_system`, `get_collection_stats`, `get_metrics`). No single view. No visual trends. No way to see everything at a glance. |
| **Rationale** | Directors need operational visibility to manage the platform. CLI and MCP tools are powerful but require multiple commands and produce text output. A visual admin dashboard provides at-a-glance system health, enables faster incident response, and supports non-technical director users who cannot use CLI or MCP. |
| **Acceptance criteria** | (1) Web-based admin dashboard at `/admin` (auth required — F59). (2) System health overview: composite health score, per-domain status, error rates, latency p95. (3) User activity: active users, trial users, churned users, new signups. (4) Collection status: last run per domain, items collected, source health. (5) Delivery metrics: delivery success rate, SLA compliance, channel health. (6) Cost trends: LLM spend over time, per-domain cost breakdown. (7) Alert feed: recent alerts from budget, cron, source health monitoring. |
| **Dependencies** | F59 (End-User Authentication) — admin dashboard requires auth. F56 (Enhanced Diagnostics) — data source. F57 (Metrics Export) — data source. F63 (Unified Notification Framework) — alert feed. REST API (existing) — data transport. |
| **Deferred scope** | Real-time WebSocket updates, drag-and-drop dashboard customization, saved views per director, export dashboard as PDF report, multi-language admin UI, mobile-responsive admin layout. |

#### F63 — Unified Notification Framework ❌

*No unified notification system. Budget alerts exist in `alerts.py` but are separate from user lifecycle notifications (trial ending, digest ready). System alerts (cron failure, disk usage) don't exist. No notification templates, no notification preferences per user.*

> **Cross-ref:** CD-006 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md). Related: CD-038 (Architecture Gap — No Unified Notification Architecture).

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Notifications are handled ad-hoc per subsystem. Budget alerts exist in `alerts.py` with YAML persistence and DeliveryChannel dispatch. No email template for "trial ending" or "digest ready". No webhook for system events. No notification bus, no notification routing rules, no notification preferences in `EndUserProfile` or `Subscription`. System alerts (cron failure, disk usage, source down) do not exist at all. |
| **User flow** | End user's trial is about to expire. Today: no notification is sent. The trial silently expires, deliveries stop, and the user churns without warning. Budget alerts work but only for cost thresholds. There is no unified system to notify users about lifecycle events, system issues, or content availability. |
| **Rationale** | Notifications are the communication backbone between AutoInfo and its users. Without a unified framework, every subsystem invents its own notification mechanism (or none). This leads to inconsistent user experience, missed critical alerts, and duplicated effort. A unified framework enables: lifecycle emails (trial ending, payment failed), system alerts (cron down, source unreachable), content notifications (digest ready, new alert triggered), and user-configurable notification preferences. |
| **Acceptance criteria** | (1) `Notification` model with type, recipient, channel, template, status, sent_at. (2) Notification template engine (Jinja2) with templates for: welcome, trial-ending, digest-ready, payment-failed, cancellation-confirmed, cron-failure, source-unreachable, budget-threshold. (3) Notification routing rules: which events trigger which notifications to which users via which channels. (4) Per-user notification preferences: opt-in/opt-out per type, preferred channel per type, quiet hours. (5) MCP tools: `send_notification`, `list_notifications`, `get_notification_preferences`, `update_notification_preferences`. (6) Integration with existing budget alerts (`alerts.py`) — budget alerts route through the unified framework. |
| **Dependencies** | F59 (End-User Authentication) — notifications are per-user. F27 (Product Delivery) — delivery channels reused for notifications. F37 (Multi-Channel Delivery) — channel adapters reused. Email sending (existing `email_sender.py`). |
| **Deferred scope** | Push notifications (mobile), in-app notification center, notification digest (batch notifications into a daily summary), notification A/B testing, notification analytics (open rates, click rates), SMS notifications. |

#### F64 — Product Catalog / Storefront ❌

*No product discovery for end users. No storefront, no product listing page, no pricing page. End users have no way to browse available products.*

> **Cross-ref:** CD-010 in [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md). Related: G7 (consumer-facing gap: "no Substack-style discovery").

| UX Detail | Specification |
|-----------|---------------|
| **Context** | `list_products` MCP tool exists but returns products for agent use, not for end-user browsing. No public product catalog. No storefront page. No pricing page. End users have no way to discover what products are available, what they cost, or what domains they cover. Product templates (briefing, deep-dive, weekly-roundup, alert) exist in code but are invisible to end users. |
| **User flow** | Potential end user wants to see what AutoInfo offers. Today: they cannot. There is no product listing, no pricing page, no trial signup page. The only way to discover products is through an operator who calls `list_products` via MCP. End users cannot self-discover, self-select, or self-subscribe to products. |
| **Rationale** | Product discovery is the top of the funnel for end-user acquisition. Without a storefront, AutoInfo cannot acquire end users at scale. Every consumer product needs a discovery surface. The storefront is the difference between a platform that requires sales outreach and one that supports self-service signup. |
| **Acceptance criteria** | (1) Public product catalog page listing all available products with: name, description, domain, format, cadence, sample output, pricing tier. (2) Product detail pages with full description, sample output preview, pricing, and subscribe button. (3) Pricing page showing all tiers (Free, RAW Pro, PROCESSED Pro, Enterprise) with feature comparison. (4) Trial signup flow from product page. (5) Search and filter by domain, format, cadence, price. (6) REST API endpoint `/api/v1/catalog` for programmatic product discovery. (7) Product catalog managed via MCP tools (`list_products`, `get_product` extended with public-facing fields). |
| **Dependencies** | F59 (End-User Authentication) — signup and subscription require auth. F30 (Subscription & Billing) — checkout flow connects to billing. F58 (Multi-Tenancy Isolation) — catalog is per-tenant for white-label deployments. Product templates (existing `product.py`). |
| **Deferred scope** | Product reviews and ratings, product recommendations, product bundles, seasonal/limited-time products, affiliate product listings, multi-language product catalog, product A/B testing for catalog layout. |

### 3.14 Phase 14: B1 Lifecycle Gaps

> "End-User (B1) lifecycle stages not covered by F01-F64. These expectations close the gaps identified in the user lifecycle definition. Added 2026-07-27 to achieve 100% coverage of the B1 End User Lifecycle."
>
> **Source:** [`docs/dev/specs/user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2, B1 End User Lifecycle (B1.1-B1.7).

#### F65 — B1.1 End-User Product Discovery ❌

*B1 discovers AutoInfo via marketing, search, or referral. Includes a referral sub-path for existing B1 users to refer new B1 users.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.2 (B1.1 table row). F64 (Product Catalog/Storefront) is a sub-component of this lifecycle stage — F64 covers the storefront surface; F65 covers the full discovery journey including referral and trial signup.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today there is no end-user acquisition surface. F64 documents the missing storefront, but the full B1.1 discovery journey — including how a potential B1 finds AutoInfo via external channels (search, marketing, referral) and converts to a trial signup — has no spec and no code. The discovery funnel precedes the storefront: it spans external search visibility, inbound marketing pages, and the referral loop. |
| **Product catalog visibility** | Public product catalog page (extends F64) listing all available products with: name, description, domain, format, cadence, sample output, pricing tier. Catalog is the landing surface for B1.1 discovery — B1 browses, filters, and selects a product to trial. |
| **Referral link & reward mechanism** | Existing B1 users can generate a referral link (`https://autoinfo.app/r/<referral_code>`) from their portal. New B1 who signs up via the referral link receives a trial extension or discount; the referring B1 receives account credit or a free month. Reward rules are tier-dependent and configurable by B3 (F70). Referral attribution tracked from signup through first paid conversion. |
| **Trial signup flow** | B1 selects a product from the catalog → enters email → magic link auth (F59) → trial subscription created (F38 `trial` state) → onboarding begins (F66). No credit card required for trial. Trial duration configurable per product (default 14 days per F38). Watermark/attribution on trial outputs per F38. |
| **Sample output preview** | Each product in the catalog has a sample output preview — a real (anonymized or dated) example of what the product delivers. B1 can preview before signing up. Reduces trial-to-paid churn by setting expectations upfront. Preview rendered from the product template with sample data. |
| **User flow** | Potential B1 discovers AutoInfo via search/marketing/referral → lands on product catalog → previews sample outputs → selects a product → trial signup with email → magic link → trial active → onboarding (F66). |
| **Rationale** | Product discovery is the top of the B1 acquisition funnel. Without a complete discovery journey — including the referral loop and sample preview — AutoInfo cannot acquire B1 users at scale. F64 covers the storefront surface but not the full discovery-to-trial conversion path. |
| **Acceptance criteria** | (1) Public product catalog with sample output previews (extends F64 acceptance criteria). (2) Referral link generation from end-user portal: `generate_referral_link(user_id)` MCP tool. (3) Referral attribution tracking from signup to first paid conversion. (4) Reward mechanism with configurable rules (credit, trial extension, discount). (5) Trial signup flow from catalog → auth → trial subscription. (6) SEO-friendly marketing pages for inbound discovery. (7) REST API endpoints for catalog browse and referral link resolution. |
| **Dependencies** | F64 (Product Catalog/Storefront) — F65 extends F64 with referral and discovery. F59 (End-User Authentication) — trial signup requires auth. F38 (End User Lifecycle State Machine) — trial state. F36 (End User Profile) — profile creation at signup. |
| **Deferred scope** | Affiliate marketing program (third-party referrers), SEO content marketing automation, A/B testing of catalog landing pages, social sharing buttons, referral fraud detection, multi-tier referral chains. |

#### F66 — B1.3 End-User Onboarding ❌

*First-product experience after subscription. Initial delivery with explanation, preference verification, cross-product introduction, channel delivery confirmation, and config refinement loop.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.2 (B1.3 table row). F38 (End User Lifecycle State Machine) — the `trial→active` transition hook triggers onboarding. F36 (End User Profile) — profile and preferences verified during onboarding.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today, when a B1 subscribes (F38 `trial→active`), the system sends a welcome message via configured channels (F38 state transition hook). But there is no structured onboarding flow: no first-delivery design, no preference verification, no cross-product introduction, no config refinement loop. The B1's first experience is whatever the next scheduled delivery happens to be. |
| **First delivery design** | The first delivery to a new B1 is a specially designed "welcome digest" — not a standard scheduled product. It includes: (1) a welcome message explaining what AutoInfo does and what the B1 will receive, (2) a sample of the subscribed product with annotations explaining each section ("This is your TL;DR, this is your key points section, this is your source citation"), (3) a "what to expect next" preview of the next 3 scheduled deliveries, (4) a call-to-action to verify or adjust preferences. The welcome digest uses the product template but with onboarding-specific frontmatter. |
| **Preference verification step** | After the first delivery, the B1 is prompted to verify their preferences: "You signed up for the Medical Research Weekly Digest, delivered via Email + Telegram. Is this correct? Adjust here." This is a confirmation step, not a re-configuration step — it surfaces the NL→Config interpretation (F36/F67) for the B1 to confirm or refine. Verification via portal link (F40) or inline reply (channel-dependent). |
| **Cross-product up-sell timing** | After the B1 has received 2-3 successful deliveries of their subscribed product, the system introduces cross-products: "You're enjoying the Medical Research Weekly Digest. You might also like the Medical Research Alert Stream (real-time breakthroughs) or the Deep-Dive Report (monthly comprehensive review)." Up-sell timing is configurable (default: after 3rd delivery). Up-sell is non-intrusive — a footer note in the regular delivery, not a separate marketing message. |
| **Channel delivery confirmation** | For each configured delivery channel, the B1 receives a test delivery during onboarding: "This is a test delivery to confirm your Telegram channel is working. Reply to confirm." Each channel must be confirmed before it is marked active. Unconfirmed channels after 7 days → reminder, after 14 days → deactivated (email fallback remains). |
| **Config refinement loop** | If the initial NL→Config interpretation (at subscribe time, F36) was imprecise — e.g., the B1 said "I want IVF breakthroughs" but the config captured too broad or too narrow a scope — the onboarding period (first 14 days) includes a refinement loop: the B1 can re-express their intent in NL, the Agent re-parses to config, and the subscription config is updated (F67). This is the safety net for imprecise initial config. |
| **User flow** | B1 subscribes (F38) → `trial→active` hook triggers onboarding → welcome digest delivered to all configured channels → B1 verifies preferences → channel test deliveries sent → B1 confirms each channel → after 3 deliveries, cross-product up-sell begins → if config imprecise, B1 refines via NL during first 14 days. |
| **Rationale** | The first experience determines trial-to-paid conversion and long-term retention. A well-designed onboarding reduces churn by setting expectations, confirming the config is correct, and introducing the product ecosystem. Without onboarding, the B1's first delivery is a generic scheduled product with no context — leading to confusion and early cancellation. |
| **Acceptance criteria** | (1) Welcome digest template with annotated product sample and "what to expect next" preview. (2) Preference verification flow triggered after first delivery, via portal link and inline reply. (3) Channel test delivery with confirmation tracking per channel. (4) Cross-product up-sell mechanism with configurable timing (default after 3rd delivery). (5) Config refinement loop during first 14 days — B1 can re-express NL intent, Agent re-parses to config (F67). (6) Onboarding state tracking: `onboarding_status` field on subscription (welcomed, preferences_verified, channels_confirmed, onboarded). (7) MCP tools: `trigger_onboarding(subscription_id)`, `get_onboarding_status(subscription_id)`. |
| **Dependencies** | F38 (End User Lifecycle State Machine) — `trial→active` hook triggers onboarding. F36 (End User Profile) — preferences verified. F37 (Multi-Channel Delivery) — channel test deliveries. F40 (End User Self-Service Portal) — preference verification via portal. F67 (Subscription Config Modification) — config refinement loop. F27 (Product Delivery) — welcome digest delivery. |
| **Deferred scope** | Onboarding video tutorials, interactive product walkthrough, onboarding gamification (badges for completing setup steps), personalized onboarding based on B1's stated use case, onboarding A/B testing. |

#### F67 — B1.5 Subscription Config Modification (NL→Config) ❌

*B1 modifies subscription config via NL. Agent+LLM parses NL → structured config update. Billing vs non-billing change rules.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.4 (Config Change & Billing Interaction). F30 (Subscription & Billing) — subscription record contains config fields; F67 covers the modification interaction.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today, B1 can modify subscription config only via direct config manipulation (operator updates the subscription record fields directly via MCP tools `update_preferences`, `update_end_user`). There is no NL→Config path for modifications: the B1 cannot say "send me digests on Mondays instead of Fridays" or "add the AI Commercial domain to my subscription" and have the Agent parse that to a structured config update. The NL→Config pipeline exists at subscribe time (F36) but not for post-subscription modifications. |
| **NL input → Agent parses → structured update → confirmation to B1** | B1 expresses config change in NL (via portal, chat, or reply to a delivery): "Change my digest to weekly instead of daily" → Agent + LLM parses NL → structured config update diff (`{field: "cadence", old: "daily", new: "weekly"}`) → Agent applies update to subscription record → confirmation sent to B1: "Updated: your Medical Research digest is now weekly. Next delivery: [date]." Confirmation includes the parsed change for B1 to verify. |
| **Non-billing changes immediate** | Config changes that do not affect billing (e.g., cadence change within same tier, channel preference update, quiet hours adjustment, language/locale change, keyword refinement) take effect immediately. The next scheduled delivery uses the new config. |
| **Billing changes next cycle** | Config changes that affect billing (e.g., tier upgrade/downgrade, adding/removing a domain subscription, changing product type from RAW to PROCESSED) take effect at the next billing cycle. The B1 is notified: "Your tier upgrade from RAW Pro to PROCESSED Pro will take effect on [next billing date]. You will be billed $X/month instead of $Y/month." This prevents mid-cycle proration complexity and gives B1 a window to cancel the change. |
| **Config change audit trail** | Every config change (NL or direct) is logged in the audit log (F47) with: `subscription_id`, `change_type` (nl_parsed / direct_edit), `nl_input` (if applicable), `parsed_diff`, `applied_by` (b1 / agent / b3_direct), `applied_at`, `billing_impact` (none / next_cycle / immediate), `effective_at`. The B1 can view their config change history via the portal. |
| **User flow** | B1 sends NL config change request → Agent + LLM parses to structured diff → Agent classifies change as billing or non-billing → if non-billing: apply immediately, send confirmation → if billing: schedule for next cycle, send preview notification → config change logged in audit trail → B1 receives confirmation with parsed change. |
| **Rationale** | B1 should be able to refine their subscription config in the same way they initially expressed it — in natural language. Forcing B1 to use direct config manipulation (or to go through an operator) for every change is friction. The NL→Config pipeline at subscribe time (F36) proved the model; F67 extends it to the full subscription lifetime. |
| **Acceptance criteria** | (1) NL→Config parsing for config modifications using the same LLM pipeline as subscribe-time parsing (F36). (2) Change classification: billing vs non-billing (rules table mapping each config field to billing_impact). (3) Non-billing changes applied immediately, confirmed to B1. (4) Billing changes scheduled for next cycle, preview notification sent. (5) Config change audit trail with full NL input, parsed diff, and billing impact. (6) MCP tool: `modify_subscription_config(subscription_id, nl_input)` → returns parsed diff, classification, and confirmation. (7) Portal UI for NL config change input and history view. (8) Rate limiting on NL config changes (max 10/day per subscription) to prevent abuse. |
| **Dependencies** | F36 (End User Profile) — NL→Config pipeline reused. F30 (Subscription & Billing) — subscription record fields modified. F38 (End User Lifecycle State Machine) — billing change timing tied to billing cycle. F47 (Audit Log) — config change audit trail. F40 (End User Self-Service Portal) — NL input UI. |
| **Deferred scope** | NL config change undo/rollback within 24h, NL config change preview before applying, batch NL config changes (multiple changes in one NL message), NL config change templates ("apply the 'power user' preset"). |

#### F68 — B1.7 Subscription Reactivation ❌

*Churned B1 returns within retention window. Restore subscription + data from pre-churn config snapshot.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2.2 (B1.7 table row). F38 (End User Lifecycle State Machine) — mentions 90-day reactivation window but no implementation: `cancelled→active` transition is not coded, no config snapshot mechanism, no data restoration.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | F38 states "Cancelled users can re-activate within 90 days with full history preserved. After 90 days, profile is archived." But this is spec only — there is no implementation: no `cancelled→active` transition in the state machine, no config snapshot taken at cancellation time, no data restoration mechanism, no reactivation flow. A churned B1 who returns must be treated as a new signup with no history. |
| **Retention window duration (tier-dependent)** | The retention window — the period during which a churned B1 can reactivate with full data restoration — is tier-dependent: Free tier: 30 days, RAW Pro: 90 days, PROCESSED Pro: 180 days, Enterprise: 365 days (configurable per contract). After the window expires, the B1 profile is archived (data retained per GDPR/privacy policy F46-F48) but reactivation is no longer possible — the B1 must sign up as a new user. |
| **Config snapshot mechanism** | At the moment of `active→cancelled` (or `suspended→cancelled`) transition, the system takes a config snapshot: the complete subscription config (domains, products, channels, preferences, NL-originated config fields, tier, billing info) is serialized to a snapshot record (`ReactivationSnapshot` model). The snapshot is stored with `cancelled_at` timestamp and `retention_expires_at` = `cancelled_at` + retention window. Snapshot is immutable. |
| **Data continuity rules** | On reactivation within the retention window: (1) subscription config restored from snapshot, (2) delivery preferences restored, (3) product archive (past delivered products, F40) restored and accessible, (4) KB entries created by/for this B1 (if any custom KB scope) restored, (5) audit log history preserved and linked, (6) cost/billing history preserved. Data that was soft-deleted (F46) during the cancelled period is restored if within its own retention window. |
| **Reactivation notification** | When a churned B1 returns and signs in (via magic link, F59) within the retention window, the system detects the existing cancelled subscription and presents: "Welcome back! Your [Product Name] subscription was cancelled on [date]. You have [N] days left to reactivate with full history. Reactivate now?" If B1 confirms, the `cancelled→active` transition fires, config is restored from snapshot, and a reactivation welcome message is sent (extends F38 state transition hooks). |
| **User flow** | Churned B1 returns → signs in via magic link (F59) → system detects cancelled subscription within retention window → presents reactivation offer → B1 confirms → `cancelled→active` transition → config restored from snapshot → data continuity verified → reactivation welcome sent → next scheduled delivery resumes. If outside retention window → B1 treated as new signup (F65). |
| **Rationale** | Reactivation within the retention window preserves the B1's investment in configuring their subscription (NL→Config at subscribe time, F36; refinements via F67). Forcing a returning B1 to reconfigure from scratch is friction that reduces reactivation conversion. The 90-day window in F38 is a spec promise that is currently unfulfilled. |
| **Acceptance criteria** | (1) `ReactivationSnapshot` model with: `subscription_id`, `config_snapshot` (full config JSON), `cancelled_at`, `retention_expires_at`, `tier_at_cancellation`. (2) Config snapshot taken automatically at `active→cancelled` and `suspended→cancelled` transitions. (3) `cancelled→active` transition implemented in state machine (F38 extension). (4) Tier-dependent retention window configuration (F70 unified config). (5) Reactivation detection: returning B1 within window → reactivation offer presented. (6) Data restoration: config, preferences, product archive, audit history, cost history. (7) Reactivation welcome message (extends F38 hooks). (8) MCP tools: `reactivate_subscription(subscription_id)`, `check_reactivation_eligibility(user_id)`. (9) Automatic archival after retention window expires. |
| **Dependencies** | F38 (End User Lifecycle State Machine) — `cancelled→active` transition. F36 (End User Profile) — profile restoration. F40 (End User Self-Service Portal) — product archive restoration. F46-F48 (Data Privacy) — soft-deleted data restoration, GDPR compliance. F59 (End-User Authentication) — returning B1 identity. F30 (Subscription & Billing) — billing resume on reactivation. |
| **Deferred scope** | Partial reactivation (restore some products but not others), reactivation with tier downgrade, reactivation A/B testing (different offers for different churn reasons), win-back campaigns (proactive outreach to churned B1 before retention window expires), reactivation analytics (churn reason correlation with reactivation likelihood). |

### 3.15 Phase 15: B2 Lifecycle

> "Direct User (B2) lifecycle stages not covered by F01-F64. B2 is the AI agent that operates AutoInfo via MCP tools on behalf of the end user. This phase closes the B2 reporting gap identified in the user lifecycle definition."
>
> **Source:** [`docs/dev/specs/user-lifecycle-definition.md`](./user-lifecycle-definition.md) §3, B2 Direct User Lifecycle (B2.1-B2.6).

#### F69 — B2.6 Structured Execution Reporting ❌

*B2 generates periodic execution reports for B3: what was collected, what was delivered, errors, cost summary, anomaly flags.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §3.2 (B2.6 Report stage). F54-F57 (Operational Observability) — these observability tools are the data sources for B2's execution reports. F31 (Collection Overview) and F32 (Source Health) feed collection stats into the report.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today, B2 (the AI agent operating via MCP tools) has access to individual observability tools (F54-F57: `get_metrics`, `trace_item`, `diagnose_system`, `get_prometheus_metrics`) and collection tools (F31: `get_collection_stats`, F32: `get_source_health`). But there is no structured "execution report" that B2 generates for B3 — a periodic summary of what the system did, what it delivered, what errors occurred, what it cost, and what anomalies were flagged. B3 must actively query individual tools to piece together the system's execution state. |
| **Report format (structured JSON + human-readable summary)** | The execution report has two layers: (1) **Structured JSON** — machine-readable, for B3's dashboard ingestion (F71) and automated alert routing: `{report_id, period: {start, end}, collection: {items_collected, items_processed, items_failed, by_domain: [...]}, delivery: {products_delivered, deliveries_failed, sla_misses, by_channel: [...]}, errors: [{error_code, count, first_seen, last_seen, affected_domains}], cost: {total_tokens, total_cost_usd, by_domain: [...], by_model: [...]}, anomalies: [{type, severity, description, detected_at}]}`. (2) **Human-readable summary** — Markdown digest for B3 to read: "本周执行报告: 收集 145 条, 处理 142 条, 失败 3 条. 交付 28 个产品, SLA 全部达成. 总成本 $12.50. 异常: PubMed 源响应时间 P99 超阈值." |
| **Report frequency** | Configurable per B3 preference: daily (default for high-frequency domains), weekly (default), monthly. B2 generates the report at the end of each period and delivers it to B3 via B3's preferred channel (email, webhook, or dashboard update). Report generation is a scheduled job (extends cron system, F26). |
| **Anomaly detection criteria** | B2 flags anomalies in the report based on configurable criteria: (1) Source health degradation (3+ consecutive failures, F32), (2) SLA misses (P0 >5min, P1 >30min, P2 >2hr, F39), (3) Cost spike (>2x rolling 7-day average), (4) Collection volume anomaly (>50% deviation from rolling 30-day average), (5) Quality gate block rate spike (G0/G4 block rate >5%), (6) Delivery failure rate >10%. Anomaly flags include severity (Critical/Degraded/Recoverable — aligns with F72 severity classification). |
| **Delivery method to B3** | Report delivered to B3 via: (1) B3's dashboard (F71 — report appears in the "Execution Reports" view), (2) Email (if B3 prefers email summaries), (3) Webhook push (if B3 has configured a webhook for report ingestion), (4) MCP tool query (`get_execution_report(period="week")` — B3 or B3's agent can query on demand). Delivery method configurable per B3 preference. |
| **User flow** | B2 collects and processes throughout the period → at period end, B2 aggregates data from F54-F57, F31, F32, F39, cost metering → B2 generates structured JSON + human-readable summary → B2 runs anomaly detection → B2 delivers report to B3 via configured channel → B3 reviews (F71) or is alerted (F72) if anomalies are Critical. |
| **Rationale** | B3's oversight model is passive (F71) — B3 does not proactively query individual tools. B2 must proactively report execution state to B3. Without structured execution reports, B3 has no periodic visibility into what B2 is doing, what errors are occurring, and what the system is costing. The report is the primary B2→B3 communication channel. |
| **Acceptance criteria** | (1) `ExecutionReport` model with the structured JSON schema above. (2) `generate_execution_report(period="week", domain=None)` MCP tool — B2 generates the report. (3) Human-readable Markdown summary generated alongside JSON. (4) Anomaly detection with 6 configurable criteria (source health, SLA, cost, volume, gate block rate, delivery failure rate). (5) Anomaly severity classification aligned with F72 (Critical/Degraded/Recoverable). (6) Scheduled report generation via cron (extends F26). (7) Report delivery to B3 via dashboard (F71), email, webhook, or MCP query. (8) Report archive (past reports queryable for trend analysis). (9) Configurable report frequency per B3 preference. |
| **Dependencies** | F54-F57 (Operational Observability) — data sources. F31 (Collection Overview) — collection stats. F32 (Source Health Monitoring) — source health data. F39 (Delivery Reliability) — SLA and delivery failure data. F26 (Cron Scheduling) — scheduled report generation. F71 (Director Monitoring & Dashboard) — report display surface. F72 (Incident Intervention) — anomaly flags route to incident workflow. Cost metering (F41-F45) — cost summary data. |
| **Deferred scope** | Predictive anomaly detection (ML-based forecasting), report comparison/diff between periods, report export to external BI tools (Tableau, Looker), report sharing with stakeholders outside B3, natural language report queries ("show me last week's report for medical domain"). |

### 3.16 Phase 16: B3 Lifecycle

> "Director User (B3) lifecycle stages not covered by F01-F64. B3 is the human commander who deploys, configures, monitors, and intervenes. This phase closes the B3 configuration, monitoring, and intervention gaps identified in the user lifecycle definition."
>
> **Source:** [`docs/dev/specs/user-lifecycle-definition.md`](./user-lifecycle-definition.md) §4-§5, B3 Director User Lifecycle (B3.1-B3.3) and Error Escalation Path (§5.3).

#### F70 — B3.1 Unified Director Configuration 🟡

*B3 sets all configuration at deploy time: pricing tier definitions, domain quotas, quality thresholds, delivery SLA targets, data retention policies. Unified config scope.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §4.3 (B3 Configuration Scope). [`quality-gates.md`](./quality-gates.md) — quality thresholds. [`operations.md`](./operations.md) — cost/privacy/lifecycle/observability config. Partially implemented: config exists but is scattered across multiple config files and code-level defaults — there is no unified B3 config surface.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today, B3-relevant configuration is scattered across: `.autoinfo/config.yaml` (LLM config, domain config), per-domain config files (sources, topics, quality gate thresholds), code-level defaults (delivery SLA targets in `delivery.py`, retention policies in privacy modules, pricing tiers in `billing.py`). There is no unified "B3 config" surface where a director can set all deployment-wide policies in one place. B3 must edit multiple files and know which code-level defaults to override. |
| **Config scope table** | Unified B3 config covers five scopes: (1) **Pricing tier definitions** — tier names, prices, feature flags, quotas per tier (Free, RAW Pro, PROCESSED Pro, Enterprise). (2) **Domain quotas** — max domains per tenant, max sources per domain, max topics per domain, max items per collection run. (3) **Quality thresholds** — G1-G5 gate thresholds per domain, gate action defaults (archive/flag/pass), retry counts for hard gates. (4) **Delivery SLA targets** — P0/P1/P2 latency targets, retry chain config, fallback channel policy. (5) **Data retention policies** — per-domain TTL, soft-delete retention window, GDPR export format, auto-cleanup schedule. |
| **Config format (demo vs production)** | **Demo / single-tenant**: B3 config is a single YAML file (`.autoinfo/director-config.yaml`) edited at deploy time. Schema-validated, with defaults inherited from code-level values. **Production / multi-tenant**: B3 config is managed via an admin UI (web dashboard, extends F71) with form-based editing, validation, and version history. CLI equivalent: `autoinfo director config get|set|list|export|import`. MCP tools: `get_director_config()`, `set_director_config(scope, key, value)`. |
| **Config versioning** | Every B3 config change is versioned: `{version, changed_by, changed_at, scope, key, old_value, new_value, reason}`. Config version history is queryable via `get_config_history(scope, since_version)`. Rollback to a previous version: `rollback_config(to_version)`. Config changes are logged in the audit log (F47). This enables B3 to understand what changed when and roll back problematic changes. |
| **Config precedence** | B3 unified config is the deployment-wide default. Per-domain config can override B3 defaults (e.g., a specific domain with stricter quality thresholds). Per-tenant config (when F58 multi-tenancy is implemented) can override domain defaults. Per-subscription config (F30, F67) is the most specific. Precedence: subscription > tenant > domain > B3 unified > code-level default. |
| **User flow** | B3 deploys AutoInfo → edits `director-config.yaml` (demo) or uses admin UI (production) → sets pricing tiers, domain quotas, quality thresholds, SLA targets, retention policies → config validated against schema → config applied (some changes immediate, some require restart) → config version recorded → downstream configs inherit B3 defaults unless overridden. |
| **Rationale** | B3 is responsible for deployment-wide policy. Without a unified config surface, B3 must know the location and format of every scattered config file and code-level default — this is expert knowledge, not director-level operation. A unified config surface makes B3's deploy-time configuration explicit, validated, and version-controlled. |
| **Acceptance criteria** | (1) `DirectorConfig` schema covering all 5 scopes (pricing, domain quotas, quality thresholds, SLA, retention). (2) Single YAML file for demo/single-tenant: `.autoinfo/director-config.yaml`. (3) Schema validation with defaults inherited from code-level values. (4) Admin UI for production (extends F71 dashboard). (5) CLI: `autoinfo director config get|set|list|export|import`. (6) MCP tools: `get_director_config()`, `set_director_config(scope, key, value)`, `get_config_history()`, `rollback_config(to_version)`. (7) Config versioning with full audit trail. (8) Config precedence: subscription > tenant > domain > B3 > code default. (9) Validation: invalid config values rejected with explanation. (10) Hot-reload for non-restart-requiring changes. |
| **Dependencies** | F47 (Audit Log) — config change audit trail. F58 (Multi-Tenancy Isolation) — per-tenant config override. Quality gate config (existing `get_gate_config`/`set_gate_config`). Cost config (F41-F45). Data privacy config (F46-F48). Delivery SLA config (F39). Pricing/billing config (F30). |
| **Deferred scope** | Config templates per deployment type (single-tenant SaaS, enterprise on-prem, white-label), config diff between deployments, config import from external CMDB, config drift detection, config change approval workflow (B3 proposes, second B3 approves). |

#### F71 — B3.2 Director Monitoring & Dashboard 🟡

*B3 monitors B2 via dashboard and reports. Passive oversight — B3 does not proactively intervene unless alerted.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §4.2 (B3.2 Monitor). F54-F57 (Operational Observability) — observability data sources. F31/F32 (Collection Overview, Source Health) — existing monitor tools. F52 (Audit Log Query) — audit data for dashboard. Partially implemented: all data exists via CLI and MCP tools, but there is no unified B3 dashboard surface.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today, all the data B3 needs for monitoring exists and is accessible: `autoinfo status` (F31), `autoinfo sources health` (F32), `autoinfo cost dashboard` (F43), `autoinfo audit query` (F52), `autoinfo doctor --verbose` (F54), Prometheus metrics (F57), and B2's execution reports (F69). But there is no unified dashboard that aggregates these into a single B3-facing view. B3 must run multiple CLI commands or query multiple MCP tools to get a complete picture. The existing Web UI Dashboard (Bootstrap 5, collection stats + KB search + source health) is end-user-facing, not B3-director-facing. |
| **Dashboard views** | B3 dashboard aggregates 5 views: (1) **System health** — composite health score (F54), LLM key status, DB disk usage, source reachability summary, active collection/processing jobs. (2) **Collection stats** — items collected per domain per period, KB entries added, source health by domain (extends F31/F32). (3) **Delivery metrics** — products delivered, delivery success rate, SLA compliance per tier, bounce/failure rates per channel (extends F39). (4) **Cost trends** — daily LLM spend, top models by cost, top domains by cost, budget threshold status, cost projection (extends F43). (5) **Anomaly flags** — active anomalies from B2 execution reports (F69), severity classification, time since detection, resolution status. |
| **Report frequency** | Dashboard is real-time (data refreshes on page load, or via WebSocket push for active monitoring). B2's execution reports (F69) appear in the dashboard on their schedule (daily/weekly/monthly). B3 can configure dashboard alert thresholds: "notify me if health score < 80" or "notify me if cost > $50/day." Alerts route via B3's preferred channel (email, webhook). |
| **Alert routing** | Dashboard anomalies and threshold breaches route to B3 via: (1) Dashboard notification badge (real-time), (2) Email digest of alerts (configurable frequency), (3) Webhook push for integration with external monitoring (PagerDuty, Slack), (4) MCP tool query (`get_b3_alerts(severity="Critical")`). Critical anomalies (F72 severity) trigger immediate alert regardless of B3's quiet hours. |
| **Passive oversight model** | B3's monitoring is passive: B3 reviews the dashboard when they choose, and is alerted only when anomalies or threshold breaches occur. B3 does not need to actively poll the system. The dashboard + B2 execution reports (F69) + alert routing form the passive oversight loop. B3 proactively intervenes only when alerted (F72). |
| **User flow** | B3 opens dashboard (web UI or CLI `autoinfo director dashboard`) → sees 5 views with current data → reviews anomalies and cost trends → if Critical anomaly flagged → B3 initiates intervention (F72) → B3 reviews B2's latest execution report (F69) → B3 adjusts config if needed (F70). Between dashboard visits, B3 receives alerts only on anomalies/threshold breaches. |
| **Rationale** | B3's oversight is passive by design (user-lifecycle-definition §4.2). Without a unified dashboard, passive oversight requires B3 to actively run multiple commands — which is not passive. The dashboard aggregates the existing data into a single surface that supports true passive monitoring: B3 glances, is alerted on anomalies, and intervenes only when needed. |
| **Acceptance criteria** | (1) B3 dashboard web UI aggregating 5 views (system health, collection stats, delivery metrics, cost trends, anomaly flags). (2) Real-time data refresh (page load or WebSocket). (3) B2 execution reports (F69) displayed in dashboard. (4) Configurable alert thresholds (health score, cost, anomaly severity). (5) Alert routing via dashboard badge, email, webhook, MCP query. (6) Critical anomalies bypass quiet hours. (7) CLI equivalent: `autoinfo director dashboard` — text-based dashboard for terminal-only B3. (8) MCP tools: `get_b3_dashboard()`, `get_b3_alerts(severity)`. (9) Dashboard access control (B3 role only, extends F59 auth). (10) Dashboard extends existing Web UI (Bootstrap 5) with a B3-specific view. |
| **Dependencies** | F54-F57 (Operational Observability) — data sources. F31/F32 (Collection/Source Health) — collection stats. F39 (Delivery Reliability) — delivery metrics. F43 (Cost Dashboard) — cost data. F52 (Audit Log) — audit data. F69 (Execution Reports) — B2 reports displayed. F59 (End-User Authentication) — dashboard access control. Existing Web UI Dashboard (Bootstrap 5). |
| **Deferred scope** | Custom dashboard widgets, dashboard sharing with stakeholders, dashboard export to PDF/email, historical dashboard snapshots (point-in-time view), multi-deployment dashboard (monitor multiple AutoInfo instances), dashboard mobile app. |

#### F72 — B3.3 Incident Intervention Workflow 🟡

*Structured B3 intervention when B2 encounters critical errors. Severity classification, intervention steps, post-incident audit.*

> **Cross-ref:** [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §5.3 (Error Escalation Path). F20 (KB Storage) — note: promote Draft→Wiki is an **agent operation** since 2026-08-08 (KB is a database for raw/processed production), no longer a B3 intervention action. F47 (Audit Log) — intervention actions are audit-logged. Partially implemented: CLI operations exist (`autoinfo doctor`, `autoinfo trace`, `autoinfo kb promote`) but there is no structured incident workflow with severity classification and post-incident audit.

| UX Detail | Specification |
|-----------|---------------|
| **Context** | Today, B3 has individual tools for intervention: `autoinfo doctor --verbose` (diagnose system health, F54), `autoinfo trace <trace_id>` (trace an item's pipeline journey, F55), `autoinfo kb promote` (promote Draft→Wiki, F20), `autoinfo sources remove` (remove a failing source), `autoinfo clean` (clean artifacts), `diagnose_system()` MCP tool (F54). But there is no structured incident workflow: no severity classification, no defined intervention steps per severity, no incident record format, no post-mortem requirements. B3's intervention today is ad-hoc — B3 sees a problem, runs a command, hopes it's fixed. |
| **Severity classification (Critical/Degraded/Recoverable)** | Incidents are classified into 3 severity levels: **Critical** — system down, data loss risk, all deliveries failing, security breach. B3 must intervene immediately. Examples: LLM key invalid (all extraction blocked), DB corruption, all sources unreachable. **Degraded** — partial failure, some deliveries failing, some sources degraded, SLA misses accumulating. B3 should intervene within 1 hour. Examples: 2+ sources failing, SLA miss rate >20%, cost spike >2x average. **Recoverable** — minor issue, self-healing expected, no user impact. B3 is informed but intervention optional. Examples: single source timeout (auto-retry will handle), single delivery bounce (retry chain will handle). Severity is assigned by B2's anomaly detection (F69) or by B3 manually. |
| **Intervention steps table** | Defined intervention steps per severity: **Critical**: (1) B3 alerted immediately (bypasses quiet hours, F71), (2) B3 opens incident record, (3) B3 runs `diagnose_system()` + `trace_item()` on affected items, (4) B3 applies immediate fix (rollback config F70, remove failing source, promote/reject KB Draft F20, restart service), (5) B3 verifies system recovery, (6) B3 closes incident record with post-mortem. **Degraded**: (1) B3 alerted within 1 hour, (2) B3 reviews B2 execution report (F69) for context, (3) B3 applies targeted fix (adjust quality threshold F70, switch to fallback source, pause degraded source), (4) B3 monitors for recovery, (5) B3 closes incident record. **Recoverable**: (1) B3 informed via dashboard (F71) or next execution report (F69), (2) B3 reviews at next convenience, (3) no incident record required (logged as observed anomaly). |
| **Incident record format** | `Incident` model: `{incident_id, severity, status (open/investigating/resolved/closed), title, description, detected_at, detected_by (b2_anomaly / b3_manual / b2_report), affected_domains[], affected_sources[], intervention_steps[], applied_fixes[], resolution, post_mortem (required for Critical), post_mortem_url, closed_at, closed_by}`. Incident records are stored and queryable: `get_incidents(severity, status, since)`, `get_incident(incident_id)`. Critical incidents require a post-mortem document linked from the incident record. |
| **Post-mortem requirements** | Critical incidents require a post-mortem within 72 hours of resolution. Post-mortem document includes: (1) timeline of incident (detection → intervention → resolution), (2) root cause analysis, (3) impact assessment (users affected, data affected, cost impact), (4) what went well in the intervention, (5) what went poorly, (6) preventive actions (config changes F70, monitoring improvements F71, code fixes). Post-mortem is linked from the incident record and archived for future reference. Post-mortem template provided. |
| **User flow** | B2 detects anomaly (F69) or B3 notices issue on dashboard (F71) → severity classified (Critical/Degraded/Recoverable) → B3 alerted per severity rules → B3 opens incident record → B3 runs diagnostic tools → B3 applies intervention steps per severity → B3 verifies recovery → B3 closes incident record → if Critical: B3 writes post-mortem within 72h → incident + post-mortem archived in audit log (F47). |
| **Rationale** | B3's intervention today is ad-hoc. Without a structured workflow, intervention quality depends on B3's expertise and memory — not on a defined process. Severity classification ensures B3 prioritizes correctly. Defined intervention steps ensure B3 doesn't miss critical actions. Incident records ensure institutional knowledge is preserved. Post-mortems ensure learning from Critical incidents. |
| **Acceptance criteria** | (1) `Incident` model with the schema above. (2) Severity classification (Critical/Degraded/Recoverable) with defined criteria. (3) Intervention steps table per severity (3 levels). (4) Incident record CRUD: MCP tools `create_incident()`, `get_incident()`, `get_incidents()`, `update_incident()`, `close_incident()`. (5) CLI: `autoinfo incident list|show|open|close|postmortem`. (6) Alert routing per severity (Critical bypasses quiet hours, Degraded within 1h, Recoverable via dashboard). (7) Post-mortem requirement for Critical incidents (72h deadline, template provided, linked from incident). (8) Incident + post-mortem archived in audit log (F47). (9) Integration with F69 anomaly detection (auto-create incident on Critical anomaly) and F71 dashboard (incident status visible). (10) Integration with F20 (KB promote/reject as intervention action), F70 (config rollback as intervention action). |
| **Dependencies** | F69 (B2 Execution Reporting) — anomaly detection triggers incidents. F71 (Director Dashboard) — incident status displayed, alerts routed. F54-F57 (Observability) — diagnostic tools for intervention. F47 (Audit Log) — incident records and post-mortems archived. F20 (KB Storage) — promote/reject as intervention action. F70 (Unified Director Config) — config rollback as intervention action. F38 (Lifecycle State Machine) — subscription state changes as intervention (e.g., suspend delivery to affected B1). |
| **Deferred scope** | Automated incident response (auto-rollback on Critical), incident on-call rotation, incident severity auto-escalation (Recoverable → Degraded if not resolved in N hours), incident analytics (MTTR, incident frequency by domain), incident integration with external incident management (PagerDuty, Jira Service Desk), post-mortem review workflow (peer review before closing). |

### 3.17 Notes on Expectation Numbering

The catalog uses the following identifiers: F01-F06 (Phase 1: Setup), F07-F10b (Phase 2: Domain & Topic Config), F11-F15 (Phase 3: Information Gathering), F16-F19 (Phase 4: Curation & Interaction), F20-F23 (Phase 5: Knowledge Base Building), F24-F30 (Phase 6: Output & Asset Creation), F31-F32 (Phase 7: Monitor), F33-F34 (Phase 8: Iterate), F36-F40 (Phase 8.5: Product & Delivery — note: no F35 in source), F41-F45 (Phase 9: Cost Governance), F46-F48 (Phase 10: Data Privacy), F49-F53 (Phase 11: Knowledge Lifecycle), F54-F57 (Phase 12: Operational Observability), F58-F64 (Phase 13: Blank Spaces — added 2026-07-27 from cross-dimensional gap analysis), F65-F68 (Phase 14: B1 Lifecycle Gaps), F69 (Phase 15: B2 Lifecycle), F70-F72 (Phase 16: B3 Lifecycle). Note that F08 (Custom Sources) and F35 are not separately numbered in the source document — F08 appears as the F07b sub-section's continuation (the unheaded table after F07b's preamble concludes with the add-source UX), and F35 is omitted from the source ordering. F58-F64 were added on 2026-07-27 to document blank spaces (Type 1: Never Designed gaps) discovered during the cross-dimensional gap analysis — see [`cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) CD-001..CD-006, CD-010. F65-F68 (Phase 14: B1 Lifecycle Gaps), F69 (Phase 15: B2 Lifecycle), F70-F72 (Phase 16: B3 Lifecycle) — added 2026-07-27 to achieve 100% coverage of the user lifecycle definition ([`user-lifecycle-definition.md`](./user-lifecycle-definition.md) §2-§5).

---

Associated spec files:

- [`expectations.md`](./expectations.md) — F01-F72 founder expectation catalog (this file)
- [`pipeline.md`](./pipeline.md) — Collection pipeline, KB pipeline, processing & LLM extraction, import, CEFR, cross-collection dedup & merge
- [`quality-gates.md`](./quality-gates.md) — G0-G5 quality gates, D1-D3 delivery gates: catalog, philosophy, retry strategies, configuration
- [`delivery.md`](./delivery.md) — Output generation, delivery channels, error recovery & resilience, end user lifecycle
- [`operations.md`](./operations.md) — Cost governance, data privacy & compliance, knowledge lifecycle (TTL, versioning, decay), observability
- [`mcp-tools.md`](./mcp-tools.md) — Complete MCP tool inventory (146 tools across 35 categories)
- [`data-models.md`](./data-models.md) — Consolidated data model schemas (Item, ExtractionResult, UserProfile, Subscription, DeliveryLog, CostLog, AuditLog, SystemHealth)
- [`user-lifecycle-definition.md`](./user-lifecycle-definition.md) — B1/B2/B3 user types with complete lifecycles (root spec for F65-F72)
