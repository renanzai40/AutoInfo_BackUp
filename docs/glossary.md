<!-- doc-type: glossary -->
# AutoInfo Project Glossary (Ubiquitous Language)

> This is the project's **shared language** — the terms that must mean the same
> thing to humans, agents, code, and docs (DDD *Ubiquitous Language*). If a
> term is redefined ad-hoc, variable names, searches, and agent prompts
> silently diverge. Keep this file authoritative; `AGENTS.md` and the
> doc-manager skill reference it instead of duplicating definitions.
>
> **Maintenance rule**: add a term when it is used across ≥2 docs and its
> meaning is non-obvious. Never delete a term — deprecate it with a note.

## Core domain

| Term | Definition | Used In |
|------|-----------|---------|
| KB pipeline (4-tier) | 01-Raw → 02-Draft → 03-Wiki (00-Inbox scaffolded but deprecated) | AGENTS.md, specs/pipeline.md |
| 01-Raw | Sole entry point for all collected content; carries full source provenance | All KB-related docs |
| 03-Wiki | Append-only tier; entries never demoted/deleted by agents | All KB-related docs |
| 00-Inbox | Deprecated scaffold tier; not the entry point | specs/pipeline.md |
| G0-G5 | Quality gates: G0 Schema (hard), G1 Source authority, G2 Dedup, G3 Relevance, G4 Factual (hard), G5 Translation | AGENTS.md, README.md, specs/quality-gates.md |
| D1-D3 | Delivery gates: D1 completeness, D2 format integrity, D3 freshness | specs/quality-gates.md, AGENTS.md |
| G15 | Access-control gate: free always allowed; premium/enterprise require active paid subscription | README.md, specs/delivery.md |
| B1 / B2 / B3 | End User (customer) / Direct User (agent) / Director User (human commander) | specs/user-lifecycle-definition.md, director-user-guide.md |
| Keystone document | Single source of truth for product definition; all other docs derive from it | cross-dimensional-catalog.md, enduser-coverage-matrix.md, acceptance-framework.md |
| ADR | Architecture Decision Record (`docs/adr/`) — the *why* behind architecture rules | docs/adr/README.md |
| Product template | One of 8 product families (premium-briefing, magazine-digest, enterprise-briefing, column, …) with dedicated Jinja2 templates + per-product LLM synthesis | README.md, specs/delivery.md, src/autoinfo/data/ |

## Agent & tooling

| Term | Definition | Used In |
|------|-----------|---------|
| Agent-native | All capabilities as MCP tools; agent operates, human directs | AGENTS.md |
| AX | Agent Experience — how an agent experiences the codebase (feedback loops, module shape, test strategy) | docs/adr/, methodology docs |
| MCP | Model Context Protocol (stdio transport) | All docs |
| BYOK | Bring Your Own Keys (LLM provider) | README.md, AGENTS.md |
| LiteLLM | LLM provider abstraction layer | AGENTS.md, llm.py |
| Fallback chain | Ordered `[primary] + llm.fallback` walk; first successful model wins (ADR-0003) | AGENTS.md, docs/adr/0003-llm-fallback-chain.md |
| Reasoning model | Model flagged `reasoning_model: True` — never sent `response_format`; thinking disabled by default (ADR-0004) | AGENTS.md, docs/adr/0004-reasoning-model-json-mode-thinking.md |
| P0/P1/P2 | Priority levels used in status tables | README.md, AGENTS.md |

## Storage & search

| Term | Definition | Used In |
|------|-----------|---------|
| FTS5 / sqlite-vec | SQLite full-text search / vector embedding extensions | README.md, AGENTS.md |
| KBEntry | A knowledge-base entry object (id, tier, source metadata, custom_fields) | specs/data-models.md, src/autoinfo/kb.py |
| custom_fields | Per-entry metadata dict; per-product analysis persists here as `product_analysis` | README.md, specs/data-models.md |
| trace_id | UUID propagated from collection through delivery for per-item traceability | AGENTS.md, README.md |

## Product & delivery

| Term | Definition | Used In |
|------|-----------|---------|
| Domain-agnostic | Demo domains are configurations, not hardcoded features | AGENTS.md, founder-expectations.md |
| Delivery channel | One of 13 channels (smtp, webhook, rest_api, file_export, discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss, social_publish, push) | README.md, specs/delivery.md |
| RAW / PROCESSED | Product types: RAW (api_feed/webhook/bulk_export) vs PROCESSED (digest/report/alert streams) | README.md, specs/delivery.md |
| JSON-LD (agent output) | `format="agent"` output pinned by `@type` (KnowledgeDigest/Tutorial/Presentation/Export) via docs/schemas/ | README.md, specs/delivery.md |

*First extracted from doc-manager-skill §6 (v2.0.1) on 2026-08-13; expanded
with terms used by specs, ADRs, and the Status table.*