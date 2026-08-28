# AutoInfo — Agent Guide

## What Is AutoInfo

AutoInfo is a **universal information tracking and knowledge base platform**. You configure sources and topics; AutoInfo handles collection, LLM-based structured extraction, summarization, and builds a queryable knowledge base.

**Key principle**: Domain-agnostic. The 21 demo domains (medical-research, ai-commercial, financial-intelligence, tech-ai-developer, language-learning, online-video, financial-news, online-education, legal-compliance, general-news, gaming, b2b, retail, english-learning, french-learning, hindi-learning, italian-learning, korean-learning, portuguese-learning, russian-learning, spanish-learning) are configurations, not hardcoded features. Users define their own domains.

## Agent Operating Model

AutoInfo is designed **agent-first**:

```
Director-user (human) ──NL──> Agent ──MCP tools──> AutoInfo MCP Server
                                ↑                           │
                                └──── structured JSON-RPC ───┘
```

1. **You (the agent)** connect to AutoInfo's MCP server over stdio (SSE transport is future work)
2. **All capabilities** are exposed as MCP tools (146 tools across 35 categories)
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
│   │   │   ├── mcp-tools.md        # 146 MCP tools across 35 categories
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
│       ├── mcp/                     # MCP server (146 tools)
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

**146 MCP tools across 35 categories** — full catalog in `README.md` (MCP Tools table)
and discoverable at runtime via `health_check()` → `tools/list` → `get_tool_count()`.
Category → key-tool mapping is maintained in the README, not duplicated here.

**Discovery flow**: `health_check()` → `tools/list` (MCP auto-discovery) → `list_domains()` → `get_domain_schema(domain)` → `list_available_models()` → `list_output_templates(domain)`.

**Validation**: `list_validation_scenarios` / `run_validation_scenario` — 124 scenarios
(65 functional + 59 regression in `src/autoinfo/mcp/scenarios/regression/`); per-scenario timeout,
recovery_steps + partial-pass, per-step trace + root-cause report, regression flywheel;
env-gated steps report `unconfigured` (never silently pass); `llm_assert` runs a real
model call. Scenario authoring contract: `docs/dev/validation-scenario-contract.md`.

**Response format**: All tools return `{success: true, data: ...}` on success and `{success: false, error: {code, message, actionable}}` on failure. `actionable` is a boolean flag; the remediation guidance itself lives in `message`. Error codes: `src/autoinfo/mcp/errors.py` (`ErrorCode` enum, 28 values). LLM-required tools return `LLM_NOT_CONFIGURED` when no key is configured. REST API uses the same envelope.

## Common Patterns

Full step-by-step worked examples live in **`docs/dev/mcp-usage-examples.md`** —
the authoritative index of every pattern with real call traces. The highest-value
patterns, inlined:

**Track a new topic**: `add_topic(domain, name, keywords)` → `collect_sources(domain, topic, dry_run=true)` → `collect_sources(...)` → `process_collection(domain)` → `list_summaries(domain, topic)` → `flag_for_knowledge_base(summary_id, tags)`.

**Check system health**: `diagnose_system()` → returns `health_score` (0-100) + `phase` (`uninitialized` / `llm_unconfigured` / `no_sources` / `ready_to_collect` / `operational`). On degraded status, inspect `phase`.

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
| fallback | [] | Ordered `llm.fallback` list — each entry: `model` (required), optional `provider`/`base_url`/`api_key`. An empty `provider` inherits the primary provider; an empty `api_key` inherits the primary key (or a `${ENV}` reference). Every LLM call path (extraction, validation judge, quality gates, translation QA, output generation, keyword suggest, Q&A, CEFR) walks `[primary] + fallback` via `llm.call_with_fallback`; the first successful model wins. Every chain entry runs under the same per-provider limiter and 429/5xx backoff (below). |
| max_concurrency | 4 | Per-provider shared rate limiting: `AUTOINFO_LLM_MAX_CONCURRENCY` env override (clamped ≥1, unparsable → default) bounds in-flight requests per `(provider, base_url)` via a shared `threading.Semaphore` in `call_with_fallback` (llm.py `_PROVIDER_SEMAPHORES`). Enforced across **every** fan-out path — process workers, post-extraction gates, cefr_batch, output grouping, MCP `to_thread` handlers, fallback chain. No single global process-wide lock. |
| 429/5xx backoff | 3 attempts (2 retries) | Jittered exponential backoff on HTTP 429 and 5xx inside `call_with_fallback`: base 1.0s, factor 2, cap 8s, jitter ±25% (llm.py `MAX_LLM_ATTEMPTS`/`BACKOFF_*`). Non-retryable 4xx (400/403/404) surface immediately — never retried. After the final attempt the last error surfaces. |

**Precedence** (highest to lowest):
1. MCP tool parameter (e.g. `init_project(llm_provider="openai")`)
2. Config file `.autoinfo/config.yaml` → `llm.provider`, `llm.model`
3. Environment variable `AUTOINFO_LLM_API_KEY`
4. Default values (openrouter/deepseek/deepseek-chat)

**Custom endpoint** (e.g. OpenCode Go, Ollama, Azure): set `provider="openai"`, `base_url` to your endpoint, `api_key` via env var, `model` to your model name.

**Fallback example** (`.autoinfo/config.yaml`) — this is now the **actual configured fallback** (2026-08-13): `mimo-v2.5` on the same gateway (`https://opencode.ai/zen/go/v1`). The entry carries full fields with empty `provider`/`api_key` — an empty `provider` inherits the primary provider (`openai`), and an empty `api_key` inherits the primary key (or a `${ENV}` reference):
```yaml
llm:
  provider: openai
  model: deepseek-v4-flash
  base_url: https://opencode.ai/zen/go/v1
  fallback:
    - provider: ''
      model: mimo-v2.5
      base_url: https://opencode.ai/zen/go/v1
      api_key: ''
```

**Per-task model routing** (2026-08-13): `_resolve_task_llm_config` (config.py) resolves the model per task and feeds `call_with_fallback(task=)` → `_build_config_with_model` (process.py). Extraction/classification tasks use the task-config model (else the base model). Judgment calls (G4 factual, G5 translation, llm_judge) resolve to the release-pinned `JUDGMENT_MODEL = "deepseek-v4-flash"` constant (config.py, beside `LLMConfig`) — a release-level decision, never runtime task-config drift.

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

Component-by-component status lives in **`README.md` → Status table** (the single
authoritative component matrix; AGENTS.md and README are cross-checked by
`scripts/doc_inventory.py --check` on the drift-prone facts below).

Key counts the agent must know without opening README:

| Fact | Value |
|------|-------|
| MCP tools | **146 tools across 35 categories** |
| CLI command groups | **28 command groups** |
| Delivery channels | **13 channels** |
| Validation scenarios | **124 scenarios** (65 functional + 59 regression) |
| Demo domains | **21 demo domains** |
| LLM-required tools | **16 LLM-required tools** |
| Test suite | **~4345 tests** |

Operational invariants (full rules in Architecture Rules above and
`docs/dev/acceptance-framework.md`):
- KB pipeline: 01-Raw sole entry → 02-Draft → 03-Wiki append-only.
- Quality gates: G0/G4 hard (retry-then-block), G1-G3/G5 soft, D1-D3 delivery.
- Promotion Draft→Wiki is an **agent operation** (`promote_kb_draft`, no human gate).
- Everything else is deferred/planned in `docs/dev/founder-expectations.md` §14.

## References

- `docs/dev/workflow-charter.md` — Development workflow charter (7-stage process + 3 support methods, English index; canonical methodology: `docs/dev/七阶段AI开发流程-用CodingAgent交付成品的方法论.md`; adoption decision: `docs/adr/0006-dev-process-workflow-charter.md`)
- `docs/dev/mcp-usage-examples.md` — Full worked MCP tool workflow examples (moved from Common Patterns)
- `docs/dev/required-api-keys.md` — Full catalog of API keys and environment variables
- `docs/dev/founder-expectations.md` — D3 index (simplified after split; see `docs/archive/founder-expectations-pre-split.md` for full original)
- `docs/dev/specs/` — Extracted spec files (11 files: expectations.md, quality-gates.md, pipeline.md, delivery.md, operations.md, market-positioning.md, mcp-tools.md, data-models.md, user-lifecycle-definition.md, multi-tenancy-auth.md, ops-runbook.md)
- `docs/archive/kb-pipeline-reference.md` — Reference KB pipeline model (archived)
- `docs/dev/cross-dimensional-catalog.md` — **Keystone**: A1-A7 Pipeline × B1/B2/B3 Users (42 cells, 5 gap types). Supersedes archived gap-audit docs.
- `docs/dev/enduser-coverage-matrix.md` — End-user feature coverage matrix (keystone reference)
- `docs/dev/acceptance-framework.md` — **Acceptance mechanism (keystone, AC1-AC9)**: user model integrity, data-layer integrity, dual orientation (agent-operated tool / human-first results), coverage commitment, quality, commercial viability, process governance, documentation health (AC8), test & validation suite health (AC9). Supersedes `launch-validation-framework.md` as the top-level validation charter (D1-D5 now archived at `docs/archive/launch-validation-framework.md`; evidence machinery retained as tooling).
- `docs/dev/validation-scenario-contract.md` — Scenario authoring **and agent-tester execution** how-to (real MCP/CLI/REST calls, real artifacts); authoring + execution merged into one doc 2026-08-08 (former runbook archived at `docs/archive/agent-tester-validation.md`); graded against `acceptance-framework.md` (AC1-AC9)
- `docs/adr/` — Architecture Decision Records: the *why* behind architecture rules (01-Raw sole entry, agent promotion without human gate, LLM fallback chain, reasoning-model JSON control, unified envelope, release-please version truth). Template: `docs/adr/TEMPLATE.md`.
- `docs/glossary.md` — Project glossary (Ubiquitous Language): the authoritative definitions of KB pipeline, gates, user types, and agent/tooling terms.
- `docs/dev/agent-era-doc-architecture.md` — Portable playbook: agent-era documentation architecture (generic, applies to any project).
- `docs/dev/agent-era-doc-architecture-autoinfo.md` — AutoInfo-specific map of the doc architecture (what to keep/update, the maintenance loop, cleaned-items record).

## Community

- `CONTRIBUTING.md` — Human-facing contribution guide (Conventional Commits, AI contribution policy, mandatory 回归场景).
- `GOVERNANCE.md` — Roles, label taxonomy, review policy, branch protection + DCO, release management (release-please).
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1.
- `SECURITY.md` — Vulnerability reporting (48-72h acknowledgment) + security-relevant areas (BYOK keys, webhooks, REST port 8741).
- `.github/` — PR/issue templates (mandatory 回归场景), CODEOWNERS, workflow gates (pr-title-check, baseline-aware coverage, release-please), dependabot, `.pre-commit-config.yaml` (gitleaks + credential-url guard).
