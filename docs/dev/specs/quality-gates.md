# Quality Gates Specification

> Extracted from `founder-expectations.md §4, §12.13`. See also: F18 (Quality Rating & Filtering), F24-F25 (Output Generation).
> **B3 lifecycle:** `docs/dev/specs/user-lifecycle-definition.md` §4.3 (B3 Configuration Scope). Quality gate thresholds are configured by B3 as part of the unified director configuration. See also `operations.md §7.1` (B3.1 Unified Director Configuration).
>
> **Keystone matrix:** [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) — this spec covers G0-G5 quality gates (A1-A7 Pipeline) and D1-D3 delivery gates (A4 Products). Cross-reference CD entries in the catalog for gap context.

Quality gates run automatically on each collection and (for delivery-quality gates) at product output time. They verify output quality and ensure paying customers receive genuinely high-quality products.

---

## 1. Gate Applicability

Each quality gate operates at a specific pipeline stage, evaluates a different subject, and has a distinct effect.

| Gate | Stage | Trigger | Subject | Effect on item/product |
|------|-------|---------|---------|----------------------|
| **G0** | **Collection** | `process_collection()` — runs first on every raw item before Item construction | Raw collected dict | Blocks malformed items (missing mandatory fields, invalid YAML) from entering the pipeline |
| **G1** | **Collection** | `run_quality_gates()` — runs immediately after G0 passes | `Item` object | Flags items from low-authority sources (Tier 3+); never blocks. `action=skip` signals caller to exclude. Computes deterministic `source_score` (0-100) from `quality_tier` via `SOURCE_TIER_SCORE_MAP` and persists it on the KBEntry (E9). |
| **G2** | **Collection** | `run_quality_gates()` — runs after G1 | `Item` + existing `KBEntry[]` | Detects duplicates (URL → PMID → DOI). Duplicates are skipped/logged; unique items proceed. |
| **G3** | **Collection** | `run_quality_gates()` — runs after G2 | `Item` + topic keywords | Scores relevance 0-100. Below-threshold items are archived (stored but hidden from default views). |
| **G4** | **Processing** | LLM extraction phase (opt-in: `--check-factual` flag) | `Item` content vs `ExtractionResult.tl_dr` | Verifies LLM summary does not contradict source. On persistent failure: blocks item, writes diagnostics to `_failed/`. |
| **G5** | **Processing** | LLM extraction phase (opt-in: `--check-translation` flag) | Source text vs `ExtractionResult.custom_fields["translation"]` | Verifies translation faithfulness. Advisory only — never blocks. |
| **CurationGate** | **Promotion (admission)** | `promote_kb_draft()`: evaluated before a 02-Draft entry is promoted to 03-Wiki (`check_promotion_admission` in `autoinfo/promotion.py`) | 02-Draft `KBEntry` | Admission gate for Draft→Wiki promotion: provenance completeness + G0 schema re-check + G1 `source_score` ≥ 30 + G3 `relevance_score` ≥ 30 + G4 factual re-check. Hard gate: reject blocks promotion and writes `_failed/`. See §3.1. |
| **D1** | **Delivery** | Product generation (`generate_digest` / `generate_report` / `generate_tutorial` / `generate_presentation`) — PROCESSED products only | Product output dict | Checks required sections (`key_findings`, `summary`, `recommendations`) are present and non-empty. Default action: block delivery. |
| **D2** | **Delivery** | Product generation — PROCESSED products only | Rendered output body | Validates HTML (tag balance), JSON (`json.loads`), Markdown (trivially passes). Default action: fallback to plain text. |
| **D3** | **Delivery** | Product generation — PROCESSED products only | Each entry's `collected_at` date | Flags entries older than recency window (default 30 days). Default action: flag (advisory). |

**Key rule**: G0-G3 are **mandatory** on every collected item. G4-G5 are **opt-in** (require explicit flags because they make LLM calls). **CurationGate** runs at Draft→Wiki promotion time (see §3.1). D1-D3 run **only for PROCESSED products**; RAW products skip all delivery gates.

**Concurrency note (gate semantics unchanged, 2026-08-13)**: post-extraction gates G3/G4/G5/CEFR run concurrently per item (bounded by `AUTOINFO_SUBTASK_CAP`, default 4; canonical gate order, G3 retry loop, G4 hard-gate 3× retry and the G0-G5 report order are preserved). All gate LLM calls route through `llm.call_with_fallback` and inherit the shared per-provider rate limiter (`AUTOINFO_LLM_MAX_CONCURRENCY`, default 4) + jittered 429/5xx backoff; G4/G5 judgment calls resolve config-first to `llm.judgment_model`/`llm.model` (issue #195 — see [`pipeline.md`](pipeline.md) §3.5); an LLM-failure surfaces as NOT_JUDGED (`QualityResult.judged=False`), never a silent pass.

Pipeline diagram:

```
Collection                           Processing                         Delivery
────────────────────────────────      ──────────────────────      ─────────────────────────
Raw Item ─→ [G0][G1][G2][G3] ─→ 01-Raw KB ─→ LLM Extract ─→ 02-Draft KB ─→ [D1][D2][D3] ─→ Product
                    ↑                        ↑       ↑            ↑
                Always runs                 G4 (opt-in) G5 (opt-in)  CurationGate on
                                                                promote Draft → Wiki
```

---

## 2. Gate Philosophy

| Principle | Meaning |
|-----------|---------|
| **Retry-first, block-last** | Every gate retries before blocking. Block only when retry is exhausted and continuing would produce an unacceptable product. |
| **Hard/soft split** | Hard gates (G0, G4) enforce correctness — they can block items after retries. Soft gates (G1, G2, G3, G5) flag and filter with configurable thresholds. |
| **Production-grade by default** | Gates are not advisory. Every gate has a configurable action: `retry`, `flag`, `block`, or `skip`. Per-domain configuration overrides the default. |
| **Never silently discard** | Even blocked items are logged with full diagnostics. Nothing disappears without trace. |

---

## 3. Gate Catalog

| Gate | Category | What it checks | Retry strategy | Action on persistent failure | Priority |
|------|----------|---------------|----------------|------------------------------|----------|
| **G0: Schema integrity** | 🔴 Hard | Entry structure, mandatory fields (`source_url`, `source_type`, `source_platform`), frontmatter validity | Retry once (re-parse) | Block item; log full parse diagnostics | 🔴 P0 |
| **G1: Source authority** | 🟡 Soft | Source quality tier check. Items from Tier 3+ flagged. User's minimum tier enforced. Computes a deterministic `source_score` (0-100) from `quality_tier` via `SOURCE_TIER_SCORE_MAP` (tier1=90, tier2=70, tier3=50, tier4=30) — see `src/autoinfo/quality.py`. The `quality_tier` is propagated from source config at collect time (`source_config.quality_tier` takes precedence over `item.quality_tier`). The score map is overridable via `QualityGateConfig.source_score_map`. The resulting `source_score` is persisted on the `KBEntry` and surfaced in search results (E9). | No retry (tier is static) | Hide from default view; store with warning flag | 🔴 P0 |
| **G1-ToS: Terms-of-Service Compliance (F46)** | 🟡 Soft | ToS compliance check against the source's quality tier → ToS map (`_TIER_TOS_MAP` in `src/autoinfo/quality.py`, gate `G1TosCompliance`, `gate_name` `G1-TosCompliance`): Open/Licensed/Restricted/Sensitive tiers map to their ToS obligations (attribution, output controls); violations are flagged, never block. | No retry (static tier→ToS map) | Flag item with ToS violation detail; store with warning flag | 🟡 P1 |
| **G2: Dedup** | 🟡 Soft | URL exact match + fuzzy title match (within configurable window, default 30 days). | No retry (deterministic) | Skip duplicate; log "already collected [date]" | 🔴 P0 |
| **G3: Relevance scoring** | 🟡 Soft | LLM-based relevance score against user's topics and keywords. Score 0-100. | Retry 2x with different model | Below threshold → archived (stored but not shown) | 🔴 P0 |
| **G4: Summary factual consistency** | 🔴 Hard | LLM verifies: does the generated summary contradict the source text? Judgment calls re-enable reasoning-model chain-of-thought (`disable_thinking=False`) with a raised budget (2000 tokens) — reasoning improves contradiction detection; CoT is disabled elsewhere to avoid token-budget truncation of JSON output. | Retry 3x with escalating context (different model each retry) | Block item; flag for human review with full diff | 🟡 P1 |
| **G5: Translation accuracy** | 🟡 Soft | Multi-round verification: (1) faithfulness to original, (2) back-translation consistency, (3) domain terminology compliance, (4) style/tone match. Composite quality score 0-100. | Retry 2x with escalating context | Flag translation issues at each round; store both versions with per-round diagnostics; below-threshold scores trigger human review prompt | 🟡 P1 |
| **CurationGate: Promotion admission** | 🔴 Hard | Admission for Draft→Wiki promotion (`check_promotion_admission` in `src/autoinfo/promotion.py`): (a) provenance completeness: `source_raw_ids` non-empty and every 01-Raw reference resolves with `source_url`/`source_type`/`source_platform`; (b) G0 schema re-check on the draft; (c) G1 `source_score` ≥ threshold (default 30); (d) G3 `relevance_score` ≥ threshold (default 30); (e) G4 factual re-check on the final body text (LLM, **on by default**: a fail is a hard reject). Deterministic checks (a)-(d) accumulate every rejection reason; G4 only runs when they are clean (fail-fast, no wasted LLM spend). | Hard: reject immediately (G4 3× retry with escalating context first); no retry for deterministic checks | Block promotion; typed `PromotionRejected` with per-component reason codes; entry stays 02-Draft; `_failed/` marker written | 🔴 P0 |

### 3.1 Curation Gate: Promotion Admission (Draft to Wiki)

The CurationGate is the **admission standard** for promoting a 02-Draft entry to
the append-only 03-Wiki tier. Promotion is an **agent operation** (`promote_kb_draft`,
`promotion_source: agent`, no human gate: the KB is a database for raw/processed
production, director decision 2026-08-08); the gate is the machine-enforced quality
bar that replaces the human approval step.

**Admission standard** (all must pass; a reject is a hard block):

| # | Check | Threshold / rule |
|---|-------|------------------|
| (a) | **Provenance completeness** | `source_raw_ids` non-empty; every referenced 01-Raw entry resolves with complete `source_url`/`source_type`/`source_platform` |
| (b) | **G0 schema re-check** | Draft passes `G0SchemaIntegrity` |
| (c) | **G1 source authority** | `source_score` ≥ 30 (configurable per domain) |
| (d) | **G3 relevance** | `relevance_score` ≥ 30 (configurable per domain) |
| (e) | **G4 factual re-check** | Final body text re-checked by `G4FactualConsistency` (LLM); **on by default**, fail = hard reject |

**Hard gate semantics**: a failed admission check **blocks promotion**: the entry
stays in 02-Draft, a typed `PromotionRejected` with per-component reason codes
(`missing-source-provenance`, `g0-schema-failed`, `source-score-below-threshold`,
`relevance-below-threshold`, `g4-factual-failed`) is raised, and a `_failed/`
marker is written. There is no silent pass and no human fallback loop; the agent
fixes the underlying cause (e.g. re-process the Raw with complete provenance) and
re-promotes. The director-only `force_promote` MCP tool (actor whitelist
`AUTOINFO_DIRECTOR_ACTORS`, default `director`) can bypass admission deliberately
and records `promotion_source: director` in the frontmatter.

**Configuration**: per-domain `quality_gates.CurationGate` entry:
`threshold` is the shared G1/G3 bar (default 30) and `enabled` toggles the G4
factual re-check (default `True`). When the entry is absent the defaults apply.
The dedicated `G1-SourceAuthority` / `G3-RelevanceScoring` keys take precedence
over the shared CurationGate threshold.

---

## 4. Production Delivery Gates

At product output time (for PROCESSED products), additional gates verify deliverable quality:

| Gate | What it checks | Failure mode |
|------|---------------|--------------|
| **D1: Product completeness** | Delivered product contains all required sections, sources cited, no empty fields | Block delivery; notify operator |
| **D2: Format integrity** | Rendered output parses correctly (valid HTML, valid PDF, valid JSON schema) | Block delivery; fall back to plain-text format |
| **D3: Freshness** | All cited items are within configured recency window (default 30 days) | Flag stale citations; optional block per domain config |

**Packaged gate reports**: validation-delivery packaging (`scripts/validation_delivery.py`) additionally persists a per-product `01-QA-GATES/gate-report-<product>.md` (human-readable) + `.json` (agent-consumable) recording that product's D1-D3 delivery-gate and authenticity verdicts, plus a `gate-reports-index.json` whose `rejected` list stays consistent with the package `manifest.json`'s `rejected` key. These packaged reports record delivery-gate outcomes only — G0-G5 run at the process layer and are not recomputed in packaging.

---

## 5. Configuration Model

Quality gate behavior is configurable per domain in `.autoinfo/config.yaml`:

```yaml
quality_gates:
  G4:  # hard gate — factual consistency
    category: hard
    retries: 3
    retry_models: [deepseek/deepseek-chat, anthropic/claude-sonnet-4]
    action: block  # retry → block
  G3:  # soft gate — relevance
    category: soft
    retries: 2
    retry_models: [deepseek/deepseek-chat]
    action: archive  # retry → archive (stored, hidden)
    threshold: 30    # relevance below 30 → archive
```

**Key design invariant**: AutoInfo never discards collected content without logging. Blocked items are written to `_failed/` with full diagnostics. The operator can always choose to override and force-publish.

---

## 6. Gate-Related MCP Tools

| Tool | Description |
|------|-------------|
| `get_gate_config(domain)` | Returns quality gate configuration for a domain. |
| `set_gate_config(domain, gate_config)` | Override quality gate thresholds, retries, or actions per domain. |

---

## 7. Testing Strategy

| Test Type | Scope | Method | CI |
|-----------|-------|--------|----|
| **Unit tests** | Source handlers, CLI parsing, config validation, dedup logic | Pure Python, no external calls | ✅ Every push |
| **Snapshot regression** | LLM extraction prompts | Collect known sample items → run extraction → assert output structure (fields present, types correct, no hallucination structure) | ✅ Every push (no LLM call in CI — uses cached snapshots) |
| **Integration tests** | Collection pipeline, KB pipeline | Test with a test LLM provider (cheap model) OR mock LLM responses | ✅ Nightly |
| **Collection E2E** | Real source fetch → store → process → KB entry | Test with public RSS feeds (no auth needed) | ⏸ Weekly (external dependency) |
| **True Test** | Full user journey (T1-T13) | Automated script running against a fresh environment | ⏸ Milestone gates only |

**Key principle**: LLM extraction tests use **snapshot regression** — store known input/output pairs. Assert structure, not semantic content. No LLM calls in CI. Full LLM tests run nightly or on demand.

---

## 8. ErrorCode & Error Response System

The MCP server uses a unified error response system (`src/autoinfo/mcp/errors.py`) that provides consistent error classification across all 146 MCP tools. The `ErrorCode` enum (30 values) covers all known failure modes and includes ten codes added since v1.8 (incl. `DIRECTOR_ONLY`):

| Code | Value | Purpose |
|------|-------|---------|
| `AUTH_REQUIRED` | `"AuthRequired"` | Future SSE authentication — returned when an SSE client attempts to connect without valid credentials |
| `RATE_LIMITED` | `"RateLimited"` | Future rate limiting — returned when a client exceeds configured rate limits for MCP tool calls |
| `SESSION_EXPIRED` | `"SessionExpired"` | Future session management — returned when an SSE session token has expired and requires re-authentication |
| `LLM_NOT_CONFIGURED` | `"LLMNotConfigured"` | LLM-required tool dispatched with no API key configured (v1.8.1) |
| `NO_CACHED_ITEMS` | `"NoCachedItems"` | No cached collection items to process (v1.8.1) |
| `EMPTY_RESULT` | `"EmptyResult"` | Operation produced an empty result (v1.8.1) |
| `CONFIG_NOT_FOUND` | `"ConfigNotFound"` | Project configuration not found (v1.8.1) |
| `DIRECTOR_ONLY` | `"DIRECTOR_ONLY"` | Director-only tool dispatched to a non-director actor — e.g. `force_promote` / `demote_kb_wiki` / `soft_delete_entry` purge (actor whitelist `AUTOINFO_DIRECTOR_ACTORS`, default `director`) |
| `READ_ONLY_SERVER` | `"READ_ONLY_SERVER"` | Mutating tool dispatched on a read-only server (`autoinfo serve --agent`, 4 read-only tools) — the server refuses state-changing calls |
| `FreeTierLimit` | `"FreeTierLimit"` | Free-tier end user hit a Subscription platform limit (concurrency/products/channels) — freemium gating (G15) |

These ten codes extend the existing 20 error codes (`NotFound`, `DomainNotFound`, `ValidationError`, `InvalidSourceId`, `SourceNotFound`, `Timeout`, `TopicNotFound`, `KeywordNotFound`, `EmailNotEnabled`, `EmailSendFailed`, `InvalidCronExpression`, `ScheduleAlreadyExists`, `ScheduleNotFound`, `NotPublished`, `CollectionFailed`, `ProcessingFailed`, `InvalidSection`, `UnknownTool`, `ConfirmationRequired`, `InternalError`). The three v1.8 codes (`AuthRequired`, `RateLimited`, `SessionExpired`) remain reserved for future use; the four v1.8.1 codes (`LLMNotConfigured`, `NoCachedItems`, `EmptyResult`, `ConfigNotFound`) are actively thrown — `LLM_NOT_CONFIGURED` is dispatched centrally by `call_tool` for all 16 LLM-required tools.

**Dual-format responses**: Error responses are backward-compatible via two formats:

1. **Flat format** (legacy, `error_dict()`): `{error_code: "<code>", message: "...", actionable: true/false}` — used throughout existing `server.py` tool handlers.

2. **Envelope format** (new, `error_response()`): `{success: false, error: {code: "<code>", message: "...", actionable: true/false}}` — recommended for new tool implementations, provides unambiguous `success` field for agent consumers.

The dual-format approach allows incremental migration: existing consumers continue using the flat format without breakage, while new consumers can adopt the envelope format. This aligns with the quality gate philosophy of *retry-first, block-last* by giving agents clear actionable flags (`actionable: true`) to decide whether to retry or escalate to B3.
