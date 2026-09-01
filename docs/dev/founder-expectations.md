# Founder's Expectations — Index

> Acceptance from the founder's perspective: does the project actually deliver on the original vision?
> Dimension 3 of the multi-dimension verification system.
>
> **This is an index document.** The full content of most sections has been extracted to standalone spec files
> under `docs/dev/specs/`. See each section for its cross-reference.
>
> **Keystone definition of "what" the system needs to be:** `docs/dev/cross-dimensional-catalog.md` (A1-A7 Pipeline × B1/B2/B3 Users — 42 capability cells cataloged). This document (founder-expectations) defines **why**; the catalog defines **what**; `docs/dev/specs/*.md` defines **how**.
>
> Backup before split: `docs/archive/founder-expectations-pre-split.md` (2108 lines, 2026-07-26).

---

## 1. Why Founder's Expectations?

AutoInfo is a new project — no tests, no quality gates, no users yet. The codebase is empty. But there's a harder question:

**Does this project actually solve the problem I created it to solve?**

This document answers that question. It defines what "done" looks like from the founder's perspective, before a single line of code is written. It's the blueprint for what AutoInfo must become.

### 1.1 The Project's Promise

> **AutoInfo 是一个通用信息追踪与知识库平台。你配置信源和关注领域，它自动完成采集、结构化提取、摘要、建立可查询的知识库。**
>
> AutoInfo 是你的"信息助理"——它不是帮你搜索，而是把从采集到知识沉淀的流程自动化、质量可控。你选择信源和方向，它完成剩下的所有体力活。领域不限，通用平台。

**Core insight**: AutoInfo's current demo domains (medical research, AI commercial intelligence, language learning) are **illustrative, not exhaustive**. The platform is **domain-agnostic and commercially grounded** — it is designed for any field where high-quality information exists and **customers are willing to pay** for curated knowledge products, thematic reports, or information feeds. Demo domains validate the concept; production domains are those with paying customers.

**Two product types** define AutoInfo's commercial model:

| Product Type | Description | Examples |
|-------------|-------------|----------|
| **RAW products** | The collected information itself — original papers, reports, articles delivered as-is | Raw data feeds, API endpoints, bulk exports (JSON/CSV/SQLite), real-time item streams |
| **PROCESSED products** | Value-added outputs — synthesized, curated, analyzed information products | Digest bundles, thematic research reports, structured data feeds, alert streams, tutorials, presentations |

Both product types are first-class entities in the architecture. The platform is the factory; RAW and PROCESSED products are what customers pay for.

| Demo Domain | Purpose | Key User During Validation |
|-------------|---------|---------------------------|
| **Medical Research** (辅助生殖/脑科学/神经科学) | Validates academic paper collection, structured metadata extraction, citation-aware KB | Founder (P0 validation) |
| **AI Commercial Intelligence** | Validates multi-source collection (API + web + feeds), structured ranking/case data, trend detection | Founder (P0 validation) |
| **Financial/Business Intelligence** | Validates financial data aggregation, multi-source pricing intelligence, regulatory filing monitoring, institutional-grade data feed production | Founder (P1 — high WTP domain) |
| **Tech/AI/Developer** | Validates open API-based collection (GitHub Trending, ProductHunt, Substack RSS), trend analysis, newsletter-style output for technical audiences | Founder (P1 — high API availability) |
| **Language Learning** (children's English reading) | Validates level classification, content simplification, vocabulary extraction, cross-lingual features | Founder (P2 — validate later) |

### 1.2 Design Principles

| Principle | Meaning |
|-----------|---------|
| **Value-first** | Criteria measure whether the project delivers value, not whether code is structured well |
| **Product-first** | The platform exists to produce sellable knowledge products. Two product lines: RAW (collected information) and PROCESSED (synthesized reports, digests, feeds, alerts). Every subsystem serves the product pipeline. A feature's value is measured by its contribution to product quality and delivery. |
| **Production-grade quality** | Quality is not advisory. Retry-first, block-last. Hard gates enforce correctness where block is the only right thing; soft gates operate with configurable thresholds. Paying customers demand genuine quality — human review loops, editorial SLAs, and production thresholds are built-in, not bolted-on. |
| **Founder's truth** | The founder's experience is the source of truth — if it doesn't work for the founder, it doesn't work |
| **Universal by default** | The platform is domain-agnostic. Demo domains are configurations, not hardcoded features |
| **Source-first** | Quality of output is bounded by quality of sources. Curated demo source libraries prove the concept |
| **Knowledge as asset** | The accumulated knowledge base is the primary long-term asset, not the real-time feed |
| **KB pipeline (4-tier)** | 4-tier pipeline (01-Raw → 02-Draft → 03-Wiki; 00-Inbox is scaffolded but deprecated — never written to). Sequential, no skipping. Draft→Wiki promotion is an **agent operation** (`promote_kb_draft`; the KB is a database for raw/processed production, director decision 2026-08-08). 01-Raw is the sole entry point. Aligned with KB pipeline design |
| **Agent-native** | All capabilities exposed as MCP tools first. CLI is fallback. Director-user communicates through agents |
| **BYOK** | Users bring their own LLM keys. No vendor lock-in. Local models supported where feasible |
| **Honest about gaps** | This document must candidly acknowledge what doesn't work yet |
| **Drives prioritization** | Failed expectations → highest-priority fixes |
| **Living document** | Expectations evolve as the project matures |

### 1.3 Three User Types (B1/B2/B3 Model)

> **Defined in:** `docs/dev/specs/user-lifecycle-definition.md` — this is the root specification. All user lifecycle modeling derives from it.

The system serves three distinct user roles. Unlike traditional multi-user systems, AutoInfo is designed for the agent-oriented paradigm: the **B2 Direct User** (the agent) executes, the **B3 Director User** (the human) directs, and the **B1 End User** (the paying customer) consumes.

| Role | Code | Description | Interface | Example | Lifecycle |
|------|------|-------------|-----------|---------|-----------|
| **End User** (最终用户 / 付费客户) | **B1** | **The paying customer.** Consumes curated knowledge products. Interacts in natural language; the B2 Agent (powered by LLM) translates NL into structured subscription config via the NL→Config pipeline. | Delivered products (email, Telegram, WeChat, API feeds); NL interaction with Agent for config changes; self-service portal | A pharmaceutical company subscribing to an "IVF Research Weekly" digest delivered via email + WeChat Work; a VC firm paying for "AI Competitive Intelligence" data feeds | B1.1 Discover → B1.2 Subscribe → B1.3 Onboard → B1.4 Consume → B1.5 Modify Config → B1.6 Churn → B1.7 Reactivate |
| **Direct User** (直接执行者 / Agent) | **B2** | **The operator.** Executes automation commands via structured tools. **Agent-first**: all capabilities are MCP tools for AI agents. The agent is the primary execution layer. | MCP tools (146 across 35 categories — primary), CLI (28 command groups — fallback) | An AI agent calling `collect_sources()` and `generate_digest()`; a human running `autoinfo collect` for ad-hoc operations | B2.1 Discover → B2.2 Connect → B2.3 Configure → B2.4 Operate → B2.5 Monitor → B2.6 Report |
| **Director User** (人类指挥者) | **B3** | **The commander.** Sets policy at deploy time, monitors passively, intervenes only on critical errors that B2 cannot self-heal. Never daily-operates the pipeline. | Dashboard + B2-generated reports; CLI for emergency intervention | "帮我追踪本周辅助生殖领域的重要论文，按创新程度排序，出一份简报" | B3.1 Configure → B3.2 Monitor → B3.3 Intervene |

**Design principle**: Agent-oriented by default, human-capable by design. All system capabilities are exposed as structured MCP tools first (for B2 agent), with CLI as an accessible alternative. B3 communicates intent through B2, not through AutoInfo directly. B1's requirements for quality, reliability, and delivery channel flexibility are embedded as hard constraints in every subsystem — see F36-F40 plus F65-F72 for the full lifecycle specification.

### 1.4 How This Dimension Is Different

| | D1 (Output) | D2 (Behavioral) | D3 (Founder) |
|---|---|---|---|
| **Asks** | Was this collection run's output acceptable? | Does the system behave correctly? | Does the project deliver value? |
| **Audience** | Pipeline operator (agent or human direct-user) | Developer | Founder / first user |
| **Scope** | Single collection run | All system surfaces | Entire project purpose |
| **Failure means** | Re-run the collection | Fix the code | Rethink the approach |
| **Frequency** | Every run | Before releases | Quarterly / milestone |
| **Tone** | Technical pass/fail | Technical pass/fail | Product-ish pass/fail |

---

## 2. Founder's User Journey

The founder's complete workflow — from configuring sources to extracting value from the knowledge base.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FOUNDER'S USER JOURNEY                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐   ┌──────────────┐   ┌───────────┐   ┌───────────────┐        │
│  │ 1. SETUP  │ → │ 2. CONFIGURE │ → │ 3. COLLECT│ → │ 4. CURATE     │        │
│  │          │   │              │   │           │   │               │        │
│  │ Install  │   │ Define domain│   │ On-demand │   │ Review summs  │        │
│  │ Config   │   │ Add sources  │   │ Scheduled  │   │ Interactive QA│        │
│  │ Keys     │   │ Set topics   │   │ Monitor    │   │ Link concepts │        │
│  └────┬─────┘   └──────┬───────┘   └─────┬─────┘   └───────┬───────┘        │
│       │                │                  │                │                │
│       ▼                ▼                  ▼                ▼                │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────┐   ┌────────────┐   ┌──────────────┐       │
│  │ 5. BUILD  │   │ 6. OUTPUT    │   │ 6.5 PRODUCT &    │   │ 7. MONITOR  │   │ 8. ITERATE   │       │
│  │ KNOWLEDGE │   │              │   │     DELIVERY      │   │             │   │              │       │
│  │          │   │              │   │                  │   │             │   │              │       │
│  │ Search KB │   │ Digest       │   │ Package RAW/     │   │ Source health│  │ Add sources  │       │
│  │ Graph viz │   │ Report       │   │ PROCESSED prods  │   │ Collection   │  │ Tune topics  │       │
│  │ Export    │   │ Tutorial     │   │ Manage subscribers│  │ stats        │  │ Improve QA   │       │
│  │           │   │ Presentation │   │ Deliver via chnl │   │             │  │ New domains  │       │
│  └──────────┘   └──────────────┘   └──────────────────┘   └────────────┘   └──────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

The journey has 8 phases. Each phase has specific expectations documented in the expectation catalog.

---

## 3. Expectation Catalog (F01-F72)

> **Content moved to:** `docs/dev/specs/expectations.md`
>
> 72 expectations across 16 phases (Setup → Configure → Collect → Curate → Build Knowledge → Output → Product & Delivery → Monitor → Iterate → Quality Gates → LLM Config → External Integration → Blank Spaces → B1 Lifecycle → B2 Lifecycle → B3 Lifecycle), each with UX Detail tables and current status markers (✅/🟡/❌). Current status: 55 ✅ fully implemented, 6 🟡 partially, 11 ❌ not implemented.
>
> F65-F72 were added 2026-07-27 to achieve 100% coverage of the user lifecycle definition (`docs/dev/specs/user-lifecycle-definition.md`).

---

## 4. Quality Gates (G0-G5, D1-D3)

> **Content moved to:** `docs/dev/specs/quality-gates.md`
>
> Gate catalog, hard/soft split, retry strategies, per-domain configuration, delivery gates (D1-D3).

---

## 5. Core Value Propositions

> **Content superseded by:** `docs/dev/cross-dimensional-catalog.md` (keystone product matrix)
>
> Assessment of 5 core value propositions: Universal Collector, LLM Extraction, KB as Asset, Agent Operations, Commercial-Grade Products.

---

## 6. Founder's Priority Matrix

> **Content moved to:** `docs/dev/specs/market-positioning.md` (§6)
>
> P0/P1/P2 priority mapping across all expectations, with effort vs. impact quadrants.

---

## 7. Market Positioning

> **Content moved to:** `docs/dev/specs/market-positioning.md` (§7)
>
> Competitive landscape, target user personas, WTP comparison, pricing benchmarks, content strategy, regional strategy, market trends.

---

## 8. Code & Test Status

> **Content moved to:** `docs/dev/specs/quality-gates.md` (§7 Testing Strategy). Code module status tables superseded by `docs/dev/cross-dimensional-catalog.md` (keystone product matrix).
>
> Verdict dataclasses, test types, and code module status tables have been moved to the respective spec files.

---

## 9. Current Reality Assessment

> **Content superseded by:** `docs/dev/cross-dimensional-catalog.md` (keystone product matrix)
>
> v1.6 reality status, What Works / What's Broken, gap table, metrics dashboard.

---

## 10. Evolution: From Vision to Reality

AutoInfo is starting from zero. This document is the blueprint.

### 10.1 The Build Process

```
For each expectation in the catalog:

  1. Define: What does "done" look like for this expectation?
     → "F11: `autoinfo collect --domain X --topic Y` stores structured items."

  2. Build: Implement the smallest version that delivers this.

  3. Test: Does it actually work? Run it.
     → Answer honestly: "yes", "mostly", "no".

  4. If no: What's the smallest change to flip it to "yes"?

  5. Lock: Write a test that asserts this behavior.
```

### 10.2 Milestone Definition

| Milestone | Definition | Expectations Met |
|-----------|-----------|-----------------|
| **v0.1 — Core Loop** | RSS collection → dedup → store → basic CLI. Medical demo domain with PubMed. | F01-F06, F07 (medical only), F11-F12, F13 (RSS), G1-G3, F31 |
| **v0.2 — Extraction & KB** | LLM summarization → KB storage → hybrid search → flag/review flow | F15, F16, F20, F21, G4 |
| **v0.3 — Multi-source** | API handler → web handler → AI commercial demo domain → cross-source dedup | F07 (AI commercial), F08, F13 (API+web), F18 |
| **v0.4 — Q&A & Graph** | Interactive Q&A → knowledge graph → cross-ref linking | F17, F19, F22 |
| **v0.5 — Output & Schedule** | Digest/report generation → scheduled collection → export formats | F14, F24, F26, F27 |
| **v0.6 — MCP Mature** | Full MCP tool suite → all domains → scheduled distribution → tutorial generation | F09, F10, F25, F32-F34 |
| **v1.0 — Product** | 35 expectations met. First paying users onboarded. Language learning demo (L1). | F07 (language-learning), F10 (learning-specific), all gates |
| **v1.1 — Gap-Fill** | G5 translation gate, KB promote/workflow, 3 new source handlers (webhook/email/PDF), KG export, 7 curated demo sources, 6 new MCP tools, interactive init, langdetect, collect --all | G5, F20 workflow, F13 (webhook/email/PDF), F22 (KG export), F07 (7 curated sources), F12 (progress MCP), F09 (keyword groups), F10 (langdetect) |
| **v1.2 — Enhancement** | Hybrid vector search (sqlite-vec), faceted search, REST API (FastAPI CRUD), Web UI dashboard, Obsidian [[wiki links]], CEFR classification, git versioning + SHA, PDF export, SMTP email, crontab installer, keywords management, schema versioning, multi-user foundation | F21 (hybrid+faceted), F23 (REST API+wiki links+versioning), F10 (CEFR), F26 (PDF export), F27 (SMTP+delivery), F14 (crontab), F20 (keywords), F34 (schema versioning) |
| **v1.3.1 — Expectations Update** | F10b (User-Defined Domains & Consulting Platforms) added, F10 localization QA enhanced (back-translation, multi-round refinement, terminology guard, composite score, agent skill). | F10b (new), F10/G5 (enhanced) |
| **v1.5 — Product & Production** | Commercial scope (any paying field), two product types (RAW + PROCESSED), production-grade quality gates (hard/soft split, retry-first/block-last), delivery infrastructure (SMTP, webhook, API), product delivery expectations F27-F30 | F27-F30 (product delivery ✅, RAW ✅, PROCESSED ✅, subscription 🟡 partially — Stripe webhook exists, full billing deferred), G0/G4 hard, D1-D3 |
| **v1.5+ → v1.6 — End User Lifecycle** | End User model (F36-F40) implemented: unified End User=Paying Customer role, profile/subscription CRUD, 6-channel delivery adapters (Telegram Bot, WeChat OA, WeChat Work, DingTalk, FeiShu, Discord + email fallback), lifecycle state machine (trial→active→suspended→cancelled), delivery logging & SLA tracking, CLI self-service portal. | F36-F40 |
| **v1.6 — Cost Governance** | Internal cost metering (LLM tokens + storage + API calls), per-domain/per-user cost allocation (pro-rata, usage-based, direct), cost dashboard with daily trends, budget alerts with auto-remediation. External billing (Stripe) partially implemented (Stripe integration coded, webhook endpoint and stripe-mock dev setup pending). | F41-F45 |
| **v1.6 — Data Privacy** | Source ToS compliance framework (access tier classification + disclaimer + processed-only output for sensitive sources), soft-delete with 30-day auto-cleanup + GDPR export, immutable audit logging for all operations. | F46-F48 |
| **v1.6 — Knowledge Lifecycle** | Per-domain TTL configuration with topic-level overrides, versioned re-collection (same source URL → version diff), stale content marking with search demotion & digest exclusion, domain decay metrics (staleness ratio + avg TTL + Green/Yellow/Red grade), cross-collection dedup and LLM-assisted merge. | F49-F53 |
| **v1.6 — Operational Observability** | Structured JSON pipeline logging with daily rotation, per-item trace_id propagation (collect→process→deliver→delivery), enhanced `doctor --verbose` with health score + error rates + latency p95/p99 + LLM spend, Prometheus `/metrics` endpoint export. | F54-F57 |

### 10.3 Explicit "No" List (v1.6 Scope)

| Feature | Status | Rationale |
|---------|--------|-----------|
| Web UI / dashboard | ✅ **v1.2 Added** | Bootstrap 5 dashboard at `/dashboard` |
| Mobile app | ❌ Out | Agent framework handles mobile access. |
| Email delivery (auto-scheduled) | ✅ **v1.4 Complete** | SMTP + cron digest delivery fully operational |
| Email collection (IMAP) | ✅ **v1.1 Added** | Source type added in v1.1 |
| Multi-user / collaboration | ❌ Out (v2) | user_id fields in place; full auth/teams are v2 |
| Social sharing | ❌ Out | No platform publishing. KB export is the output. |
| Custom scraping scripts (Python) | ❌ Out | YAML config + LLM extraction only. No code injection. |
| Image/video processing | ❌ Out | Text-only. KB is textual knowledge, not media. |
| Citation management (BibTeX) | ❌ Out for v1 | Post-v1 if medical community demands it. |
| Subscription management / billing | 🟡 Partial (v1.6) | Stripe integration coded (create_checkout_session, handle_webhook); webhook endpoint and stripe-mock dev setup pending |
| Feature gating / usage metering | 🟡 Partial (v1.6) | `check_access()` enforces free/premium/enterprise tiers in output.py; CostMeter tracks usage; MCP layer gating not enforced |

### 10.4 The True Test

The ultimate acceptance criterion for D3:

> **The founder can configure a new domain, collect content, and have a searchable, summarized knowledge base entry in one sitting, without reading documentation, without debugging errors, and with confidence that the information is high-quality.**

This is the standard. Everything else — tests, architecture, source curation — is in service of this.

#### Agent-Verifiable True Test Checklist

| # | Criterion | How Agent Verifies |
|---|-----------|-------------------|
| T1 | Fresh environment: `autoinfo init --demo medical-research` completes | Run in empty dir → exits 0, creates `.autoinfo/` with demo sources |
| T2 | Key configured: collection starts without auth errors | `collect_sources` → no LLM/source auth error |
| T3 | Topic → collected items: one command produces stored items | `autoinfo collect --domain medical-research --topic "IVF" --limit 5` → items stored in `knowledge/01-Raw/` |
| T4 | G1-G3 gates pass: items quality-filtered | Collection summary shows items with quality scores, dedup status, relevance ranks |
| T5 | Summaries generated: each item has LLM summary | `list_summaries` returns items with non-empty TL;DR + key points |
| T6 | KB entry created: flagged item → KB entry | `flag_for_knowledge_base(item_id)` → `search_knowledge_base` returns the entry |
| T7 | KB is searchable: hybrid search returns relevant results | `search_kb(query="embryo grading")` returns ranked results with relevance scores |
| T8 | Agent can operate via MCP: all core tools available | `health_check` → tool manifest includes `collect_sources`, `list_summaries`, `search_knowledge_base`, `create_kb_draft` |
| T9 | Custom domain works: user defines new domain | `add_source` + `collect_sources(domain="custom")` with new sources → items collected |
| T10 | Output generation works: digest from collected content | `generate_digest(domain="medical-research", period="today")` → structured digest with ≥1 entry |
| T11 | RAW product delivery: collected items accessible via API | `search_knowledge_base(domain="medical-research")` returns items with full provenance (`source_url`, `source_type`, `source_platform`) |
| T12 | PROCESSED product delivery: digest deliverable via channel | `generate_digest(domain="medical-research")` → output deliverable via SMTP email or webhook push |
| T13 | Hard gate enforcement: G4 blocks inconsistent items | Collection with intentionally contradictory content → G4 retries 3x, blocks item, writes to `_failed/` with diagnostics |

**Verdict**: PASS if ≥11/13 criteria pass (T3 is mandatory — if collection fails, True Test fails regardless).

---

## 11. Current Status (v1.8.1+ — 2026-08-04)

| Component | Status |
|-----------|--------|
| Framework design | ✅ Documented (this file) |
| Expectation catalog | ✅ 72 expectations across 16 phases — 55/72 implemented (✅), 6/72 partially implemented (🟡), 11/72 not implemented (❌). See `docs/dev/specs/user-lifecycle-definition.md` for the root lifecycle model. |
| Quality gates | ✅ G1-G5 hard/soft split (G0/G4 hard with retry→block, G1-G3/G5 soft with configurable thresholds); production delivery gates D1-D3; per-domain gate configuration |
| Demo domains | ✅ 13 defined with curated sources |
| Market positioning | ✅ Researched — whitespace confirmed |
| Target user persona | ✅ Defined — information-intensive professionals |
| Pricing reference | ✅ Drafted for v1 individual tier |
| Explicit "No" list | ✅ Updated for v1.6 — 5 deferred items tracked |
| Milestone mapping | ✅ v0.1→v1.6 all met, v2.0+ planned |
| True Test | ✅ 13-point agent-verifiable checklist — all pass |
| Code implementation | ✅ ~18K+ lines Python, 35+ modules |
| Demo source curation | ✅ 7 curated sources shipped with library metadata |
| Tests | ✅ ~4644 tests across 100+ test files (includes new collector tests) |
| MCP tools | ✅ 146 tools across 35 categories |
| Technical decisions | ✅ 34 categories documented, all implemented |
| CLI commands | ✅ 28 command groups |

---

## 12. Technical Decisions (Index)

Consolidated record of all technical decisions made during the design phase. Each sub-section below links to its full specification.

| # | Topic | Location |
|---|-------|----------|
| 12.1 | CLI Design | Stayed inline (§12.1 below) |
| 12.2 | Collection Pipeline (Two-Phase) | `docs/dev/specs/pipeline.md` (§1) |
| 12.3 | LLM Configuration (Per-Task Model Selection) | `docs/dev/specs/pipeline.md` (§3.3-3.4) |
| 12.4 | Source Handler Architecture | `docs/dev/specs/pipeline.md` (§1.4) |
| 12.5 | Dedup Strategy | `docs/dev/specs/pipeline.md` (§1.2, §7) |
| 12.6 | Incremental Collection Tracking | `docs/dev/specs/pipeline.md` (§1.5) |
| 12.7 | KB Processing Pipeline (Phase 2 Detail) | `docs/dev/specs/pipeline.md` (§2-3) |
| 12.8 | Search Architecture | `docs/dev/specs/pipeline.md` (§4.2) |
| 12.9 | Output Generation Architecture | `docs/dev/specs/delivery.md` (§1) |
| 12.10 | Product Architecture (v1.5) | `docs/dev/specs/delivery.md` (§1-2) |
| 12.11 | MCP Tool Inventory | `docs/dev/specs/mcp-tools.md` |
| 12.12 | Performance Targets | `docs/dev/specs/pipeline.md` (§8) |
| 12.13 | Testing Strategy | `docs/dev/specs/quality-gates.md` (§7) |
| 12.14 | Error Recovery Model | `docs/dev/specs/delivery.md` (§3) |
| 12.15 | End User Profile & Subscription Design | `docs/dev/specs/delivery.md` (§4), `data-models.md` |
| 12.16 | Cost Governance Design | `docs/dev/specs/operations.md` (§1), `data-models.md` |
| 12.17 | Data Privacy Design | `docs/dev/specs/operations.md` (§2), `data-models.md` |
| 12.18 | Knowledge Lifecycle Design | `docs/dev/specs/operations.md` (§3), `data-models.md` |
| 12.19 | Operational Observability Design | `docs/dev/specs/operations.md` (§4) |
| 12.20 | Consumer-Facing Output Design | `docs/dev/specs/delivery.md` (§1.5 Agent-Native JSON, §2.6 Agent-Mediated Delivery), `docs/dev/specs/expectations.md` (F24 audio/role-awareness, F27 RSS/agent-push, F28 agent-native format, F29 stored preferences) |

### 12.1 CLI Design

```
autoinfo <verb> [--domain <domain>] [--topic <topic>] [--source <source>] [flags]

Verbs:    init | doctor | collect | process | summaries | kb | output | cron | domain | source | topic | status | audit | trace | cost | enduser | portal | cefr | email | keywords | knowledge | clean

Domain management:   autoinfo domain add|list|remove|activate <name>
Source management:   autoinfo source add|list|remove|test <url> --domain <domain>
Topic management:    autoinfo topic add|list|remove --domain <domain>
Collection:          autoinfo collect [--domain <domain>] [--source <source>] [--topic <topic>] [--force-full]
Processing:          autoinfo process [--domain <domain>] [--batch] [--model <model>]
Summaries:           autoinfo summaries list|show|flag|rate [--domain <domain>]
KB:                  autoinfo kb search|create-draft|promote|reject|list [--domain <domain>] [--tier <tier>]
Output:              autoinfo output digest|report|tutorial|presentation|export [--domain <domain>] [--format <format>]
Cron:                autoinfo cron run|list-schedules|add-schedule|remove-schedule
Status:              autoinfo status [--domain <domain>]
Doctor:              autoinfo doctor
```

**Principles**: Flat verbs with `--domain` flag. Agent-friendly: CLI flags map 1:1 to MCP tool parameters. Domain is a parameter, not a subcommand namespace.

---

## 13. The Hard Truth

This document was designed to be **honest**. Not to make the project look good, but to make it **actually good**. The expectations in §3 are deliberately high — because the project's promise is ambitious.

The project started from zero (v0.1, July 18 2026) and reached v1.8 in 7 days of intensive development. Over 18K+ lines of Python, 35+ modules, ~2942 tests (includes new collector tests), and 141 MCP tools later — **a systematic gap analysis (2026-07-26) finds: 55/72 expectations fully implemented (✅), 6/72 partially implemented (🟡), 11/72 not implemented (❌). All 6 quality gates (G0-G5) and 3 delivery gates (D1-D3) are fully implemented. All 13 True Test criteria pass**. The product model (RAW + PROCESSED products), production-grade quality gates (hard/soft split), commercial scope, and delivery infrastructure are fully specified and operational. v1.6 closes all 13 residual v1.5+ gaps and delivers all 17 new development expectations across End User Lifecycle (F36-F40), Cost Governance (F41-F45), Data Privacy (F46-F48), Knowledge Lifecycle (F49-F53), and Operational Observability (F54-F57) — including multi-channel delivery, immutable audit logging, structured pipeline logging, per-item traceability, cost metering and allocation, budget alerts, source ToS compliance, soft-delete and GDPR retention, knowledge lifecycle (TTL, versioned re-collection, decay metrics, cross-collection dedup & merge), enhanced diagnostics, and Prometheus metrics.

v1.3.1 (hot on the heels of v1.3) hardened three resilience gaps: **LLM extraction crash on `None` content** (silent SQLite indexing failure — fixed with `TypeError` guards and `extraction_failed` detection), **KBEntry quality flags transparency** (quality gate results persisted in model, frontmatter, and search), and **filesystem fallback** when the SQLite index is empty (all KBStore query methods fall back to `knowledge/<domain>/**/*.md` scanning, providing identical dict shape to SQLite results).

Some expectations that seemed easy (F07: demo source curation) required deep research — understanding PubMed's API, navigating CrossRef REST endpoints, knowing which journals matter for 辅助生殖. Some that seemed hard (F20: file-based KB) were trivially simple — a directory of Markdown files. The v1.1 gap-fill closed the quality-of-life gaps; v1.2 added the major enhancement features: hybrid vector search, REST API, Web UI dashboard, CEFR classification, git versioning, PDF export, and email sending.

The explicit "No" list (§10.3) protected the project from scope creep. The deferred items (§14) are consciously tracked for v2.0+.

**The v1.5 pivot from "builder tool" to "commercial product"** was the hardest change. It meant rewriting the quality philosophy (from advisory to production-grade), defining product types and their economics, accepting that RAW products are a loss leader for PROCESSED margins, and consciously deferring billing to v2. The project is no longer "build a tool for yourself" — it's "build a product for paying customers."

**The v1.6 delivery of 5 domain pillars (End User Lifecycle, Cost Governance, Data Privacy, Knowledge Lifecycle, Operational Observability)** was the largest single release in the project's history. Every gap identified in the v1.5+ analysis was closed. 17 new expectations were implemented across 5 new code modules (`audit.py`, `cost.py`, `logging.py`, `delivery_log.py`, `user_store.py`) and enhanced by 6 delivery adapter modules. The project went from "commercial product scaffold" to "production-ready information delivery platform" in a single development cycle.

The project is not done when all tests pass.
The project is done when the founder can say: **"Yes, this does what I wanted."**

---

## 14. Remaining Gaps & Future Work (Post v1.6)

The following items represent the remaining delta between the founder's full vision and current implementation.

> **Completed in v1.4/v1.5/v1.5+ gap analysis:** hard gate retry→block logic (G0/G4), delivery gates D1-D3, per-domain gate configuration, RAW product feed API, alert stream configuration, KB import, webhook push, email digest delivery, translation QA pipeline, user-defined domains.

> **Completed in v1.6:** All 17 expectations across 5 pillars (F36-F40 End User, F41-F45 Cost, F46-F48 Data Privacy, F49-F53 Knowledge Lifecycle, F54-F57 Observability).

### ✅ 14.1 v1.6 Delivery Summary

| Pillar | Expectations | New Modules | Key Deliverables |
|--------|-------------|-------------|------------------|
| **End User Lifecycle** | F36-F40 | `user_store.py`, `delivery_log.py`, `delivery/adapters/*` | UserProfile/Subscription CRUD, 10 delivery channels, lifecycle state machine (trial→active→suspended→cancelled), DeliveryLog with SLA tracking, CLI self-service portal |
| **Cost Governance** | F41-F45 | `cost.py` | Cost metering (LLM tokens, storage, API calls), per-domain/per-user allocation, cost dashboard, budget alerts with auto-remediation |
| **Data Privacy** | F46-F48 | `audit.py` | Source ToS compliance tiers, soft-delete with 30-day auto-cleanup + GDPR export, immutable audit log |
| **Knowledge Lifecycle** | F49-F53 | KB pipeline enhancements | Per-domain TTL, versioned re-collection with structured diff, stale content handling, decay metrics, cross-collection dedup & merge |
| **Operational Observability** | F54-F57 | `logging.py` | JSON structured pipeline logging, UUID trace_id propagation, enhanced `doctor --verbose`, Prometheus `/metrics` |

### 🔴 v1.6+ Residual Gaps (Low Effort)

| Gap | Related Expectation | Effort |
|-----|--------------------|--------|
| LLM fallback chain never used | F04 — LLM Config | Low |
| CLI/MCP source type validation limited to rss/api/web | F08 — Custom Sources | Low |
| No `--force-full` flag | F11 — Collection | Low |
| No CLI `topics group` command | F09 — Topics | Low |
| No Dockerfile | F01 — Installation | Low |
| Version mismatch (1.3.0 vs 1.5.0) | F01 — Installation | Trivial |
| Relation types are free-form strings | F19 — Cross-ref | Low |
| CSV export missing from export_kb() | F26 — Export | Low |
| GraphML export only via CLI, not MCP | F26 — Export | Low |
| REST API and file/export not in DeliveryChannel registry | F27 — Delivery | Low |
| No BaseHandler ABC for source handlers | F13/F33 — Handlers | Medium |

> Full detail (file evidence, fix approach) in the backup at `docs/archive/founder-expectations-pre-split.md §14`.

### 🟢 Consumer-Facing Output Gaps (New — 2026-07-26)

Consumer requirements identified from global information payment research (5 reports: Reuters Institute DNR 2025/2026, Chinese knowledge payment market data, agent-mediated content trends). These are consumer-facing output/delivery gaps that the existing product pipeline does not yet address:

| Gap | Severity | Effort | Description |
|-----|----------|--------|-------------|
| **Audio output** (TTS podcast-style digest) | 🔴 Critical | Medium | 14% user preference for audio, 42% willingness to pay. TTS pipeline renders digest/report as MP3. New delivery channel: podcast RSS feed. |
| **Agent-native JSON format** | 🔴 Critical | Low-Med | Fastest-growing content channel (10% users, +3pp/y). Structured JSON-LD (`@type: "KnowledgeDigest"`) optimized for LLM re-consumption. MCP `format="agent"` parameter. |
| **RSS delivery channel** | 🟡 Medium | Low | 400M+ podcasts use RSS. `export_kb(format="rss")` exists but no scheduled RSS feed generation, no `RSSDeliveryChannel` class, no podcast RSS for audio. |
| **Agent push delivery** | 🟡 Medium | Medium | Agent subscriptions (Perplexity Comet, ChatGPT Tasks pattern). Webhook callback for product generation events. `set_agent_callback` MCP tool. |
| **Role-aware digest/report** | 🟡 Medium | Low | `target_audience` param already exists on tutorial/presentation but missing from digest/report. Consumer demand for persona-adapted content. |
| **Stored preference profiles** | 🟢 Small | Low | `UserProfile.delivery_preferences` not linked to output personalization. `generate_digest(user_id=usr_xxx)` should auto-apply user's format/timezone/channel preferences. |

> Full cross-reference: `docs/dev/cross-dimensional-catalog.md` CD-032..CD-036 — 10 gaps across 5 dimensions with priority matrix.

### 🔵 Longer-Term (v2.0+)

| Gap | Related Expectation | Effort |
|-----|--------------------|--------|
| Stripe / billing integration | F30 — Subscription & Billing | ✅ Fully implemented (Stripe webhook endpoint with signature verification, stripe-mock dev setup, freemium gating, usage-based billing) |
| Feature gating / usage metering | F30 — Subscription & Billing | 🟡 Partially implemented (check_access enforced in output.py; MCP layer gating pending) |
| Delivery analytics dashboard | F39 — Delivery Reliability | Medium |
| Collaboration / teams | §10.3 Explicit "No" | High |
| Mobile app | §10.3 Explicit "No" | High |
| Citation management (BibTeX) | §10.3 Explicit "No" | Medium |
| Image/video processing | §10.3 Explicit "No" | High |
| PROCESSED product template system | F29 | Low |

### v1.6 Gap Analysis Metrics

| Metric | Value |
|--------|-------|
| Expectations documented | 72 F-expectations across 16 phases (F01-F57 original + F58-F64 blank spaces + F65-F72 lifecycle coverage) + consumer-facing output requirements (see `docs/dev/cross-dimensional-catalog.md` CD-032..CD-036) |
| Value propositions fulfilled | 5/5 |
| True Test passing | 13/13 |
| MCP tools | 146 across 35 categories |
| Source handlers | 30 collector handlers (PubMed, arXiv, Semantic Scholar, CrossRef, DBLP, OpenAlex, USPTO, NYT, RSS, Web, Webhook, Email, PDF, Reddit, Spotify, YouTube, Bilibili, Apple Podcasts, HackerNews, AP API, Reuters MCP, SSRN, GDELT, HuggingFace/Kaggle, Unpaywall/CORE, Yahoo Finance, HTTP API, AKShare, SEC EDGAR, edX sitemap) + crontab installer |
| Quality gates | All 6 (G0-G5: G0/G4 hard, G1-G3/G5 soft) + 3 delivery gates (D1-D3) |
| Product delivery | ✅ RAW (API feeds, webhook streams, bulk export); ✅ PROCESSED (scheduled digests, thematic reports, alert streams) |
| Delivery channels | 13 channels ✅ (SMTP, Webhook, REST API, File Export, Discord, Telegram, WeChat Work, WeChat OA, DingTalk, FeiShu, RSS, Social Publish, Push). Email as mandatory fallback. |
| Subscription/billing | ✅ Fully implemented | Stripe webhook endpoint (signature verification), stripe-mock dev setup, freemium gating, usage-based billing. Full Stripe lifecycle from checkout to webhook event dispatch. |
| Tests | ~4644 (includes new collector tests) |
| Demo domains | 13 with curated sources |
| **🔴 v1.6+ residual gaps** | **11 low-effort fixes** |
| **🟢 Consumer-facing output gaps** | **6 items** (see §14 consumer gaps) |
| **🔵 v2.0+ deferred** | **8 items** |

---

## References

- This document — D3: Founder's expectations for AutoInfo v1 (index)
- `docs/dev/cross-dimensional-catalog.md` — **Keystone**: A1-A7 Pipeline × B1/B2/B3 Users — 42 capability cells. The "what" that derives from the "why" in this document.
- `docs/archive/founder-expectations-pre-split.md` — Exact backup before splitting (2108 lines)
- `docs/dev/specs/expectations.md` — Expectation Catalog F01-F72
- `docs/dev/specs/quality-gates.md` — G0-G5, D1-D3 gate catalog & configuration, testing strategy
- `docs/dev/specs/pipeline.md` — Collection pipeline, KB pipeline, extraction, search, performance targets
- `docs/dev/specs/delivery.md` — Output generation, delivery channels, error recovery, end user lifecycle
- `docs/dev/specs/operations.md` — Cost governance, data privacy, knowledge lifecycle, observability
- `docs/dev/specs/market-positioning.md` — Priority matrix, competitive landscape, pricing, personas
- `docs/dev/specs/mcp-tools.md` — Complete MCP tool inventory (146 tools, 35 categories)
- `docs/dev/specs/data-models.md` — Consolidated data model schemas
- `docs/dev/specs/user-lifecycle-definition.md` — **Root spec**: B1/B2/B3 user types and complete lifecycle definitions
- `docs/dev/specs/multi-tenancy-auth.md` — Multi-tenancy, authentication, rate limiting, admin dashboard (architectural design; deferred until SSE transport)
- `docs/dev/specs/ops-runbook.md` — Operations runbook: backup, disaster recovery, monitoring, scaling, agent quick reference with MCP tool mappings
- `docs/dev/director-user-guide.md` — Human-Agent interaction lifecycle, communication patterns, escalation protocol
