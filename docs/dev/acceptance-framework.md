# AutoInfo Acceptance Framework (AC1-AC9)

> **Keystone acceptance document.** The single entry point for judging whether a version, feature wave, or the project itself is **acceptable** for AutoInfo. It defines what "acceptable" means across nine dimensions — user model integrity, data-layer integrity, dual orientation, coverage commitment, quality, commercial viability, process governance, documentation health, and test/validation suite health — with binary acceptance criteria, verdict semantics, and an evidence catalog.
>
> **Status:** Ratified 2026-08-08 (director decision). Binding for all subsequent validation, launch, and feature-wave sign-off work.
>
> **Supersedes:** `docs/archive/launch-validation-framework.md` (D1-D5, originally `docs/dev/launch-validation-framework.md`) as the top-level validation charter, archived 2026-08-08. The D1-D5 machinery (evidence catalog, SUSPECT table, grading legend, run-report skeleton) is **retained as evidence-production tooling**, superseded in numbering by this framework's Appendix A. The D1-D5 template is no longer the acceptance authority on its own.
>
> **Change process:** Any change to a dimension definition, an acceptance criterion, a grading rule, or the dimension set requires director-user (B3) approval — the same discipline the D1-D5 template enforced. Per-version evidence lives in per-run reports, never in this template.
>
> **Relationship to other docs:**
> - `docs/dev/specs/user-lifecycle-definition.md` — the ratified B1/B2/B3 user model this framework grades against (AC1).
> - `docs/dev/enduser-coverage-matrix.md` — the A-E 99-item end-user service coverage matrix this framework's coverage commitment grades against (AC4). Its basis: `docs/dev/research/综合报告-资讯付费与AI触达研究.md` (multi-agent research synthesis on what end users pay for).
> - `docs/dev/cross-dimensional-catalog.md` — the A1-A7 × B1/B2/B3 keystone product matrix; AC1/AC4/AC5 draw their user and pipeline context from it.
> - `docs/dev/specs/quality-gates.md` — G0-G5 (extraction quality) and D1-D3 (delivery quality) gates that AC5 consumes.
> - `docs/dev/validation-scenario-contract.md` — how scenarios are authored **and executed** by the agent-tester (real process execution, never mocked); the evidence production layer. The former standalone runbook (`docs/archive/agent-tester-validation.md`) was merged into it and archived (2026-08-08).
> - `docs/archive/launch-validation-framework.md` — D1-D5, archived (2026-08-08); its evidence catalog and SUSPECT-table machinery are superseded by this framework's Appendix A.
> - `docs/dev/specs/market-positioning.md` — quality concerns per product line (RAW vs PROCESSED) that AC5's director-review criteria operationalize.

---

## Table of Contents

1. [§0 Purpose, Principles, and Operating Model](#0-purpose-principles-and-operating-model)
2. [§1 AC1 User Model Integrity](#1-ac1-user-model-integrity)
3. [§2 AC2 Data-Layer Integrity](#2-ac2-data-layer-integrity)
4. [§3 AC3 Dual Orientation (Agent-Operated Tool, Human-First Results)](#3-ac3-dual-orientation-agent-operated-tool-human-first-results)
5. [§4 AC4 Coverage Commitment](#4-ac4-coverage-commitment)
6. [§5 AC5 Quality and Deliverable Acceptance](#5-ac5-quality-and-deliverable-acceptance)
7. [§6 AC6 Commercial Viability](#6-ac6-commercial-viability)
8. [§7 AC7 Process and Governance](#7-ac7-process-and-governance)
9. [§8 AC8 Documentation Health](#8-ac8-documentation-health)
10. [§9 AC9 Test and Validation Suite Health](#9-ac9-test-and-validation-suite-health)
11. [§10 Grading and Report Template](#10-grading-and-report-template)
12. [Appendix A: Evidence Catalog](#appendix-a-evidence-catalog)
13. [Appendix B: Glossary](#appendix-b-glossary)

---

## §0 Purpose, Principles, and Operating Model

### 0.1 Purpose

AutoInfo is a universal information tracking and knowledge base platform: configure sources and topics, and the platform handles collection, LLM-based structured extraction, summarization, and a queryable knowledge base. Because the product spans collection → processing → knowledge → product → delivery → payment, "it works" is not a single question. This framework answers it as nine independent dimensions, each with binary acceptance criteria, so that a version is either acceptable or not — with the reasons recorded.

### 0.2 The Three Users (from the ratified spec)

The user model is **not** invented by this framework; it is the ratified foundation in `docs/dev/specs/user-lifecycle-definition.md`:

| User | Definition | Interface | Role in acceptance |
|------|-----------|-----------|--------------------|
| **B1 End User** | The paying customer. Buys Raw and Processed data. Treated uniformly (individual, creator, publisher, enterprise, licensor, agent delegate). | Receives delivered products; intent expressed via subscription config, never ad-hoc commands | The ultimate judge of value; the lens through which every deliverable is assessed (as a human) |
| **B2 Direct User** | The AI agent that operates the platform. Agent as user **and** agent as tester. | MCP tools (145 tools, 35 categories); CLI is fallback | Executes acceptance evidence; drafts verdicts |
| **B3 Director User** | The human owner of the agent. Configures at deploy time, monitors at runtime, intervenes on exceptions. | Natural language with the agent | Adjudicates verdicts; performs human reading of deliverables; signs off |

**Critical nuance (director decision, 2026-08-08):** the acceptance lens for deliverables is **always human-first**. Even when an agent performs a test or validation, the standard of judgment is "a human, as the end user, would find this acceptable." An agent-delegate end user (B1 subtype) does not weaken this: human judgment remains the primary view.

### 0.3 The Two Data Layers

| Layer | Definition | Internal form | Shipped product form |
|-------|-----------|---------------|----------------------|
| **Raw data** | The original collected material — reports, news, papers, information — exactly as fetched. | KB tier 01-Raw (sole entry point; complete source provenance required) | **RAW product**: `variants: ["api_feed", "webhook", "bulk_export"]` |
| **Processed data** | Raw data that has been processed: commercial-safety filtering (raw that is not commercially usable gets processed away), synthesis, structuring. | KB tiers 02-Draft → 03-Wiki | **PROCESSED product**: digest, report, tutorial, presentation, briefing, column, magazine digest, audio/video/ebook derivatives |

Two meanings of "raw" must never be conflated: the **internal data layer** (01-Raw, pipeline provenance) and the **shipped RAW product** (a sellable data feed). AC2 grades both.

**KB orientation (director correction, 2026-08-08):** AutoInfo's knowledge base is a **database** for raw/processed data production — not a human-curated knowledge base. The three-tier model (01-Raw → 02-Draft → 03-Wiki) is borrowed from human knowledge-management practice, but in AutoInfo the tiers are **production stages**: **Draft→Wiki promotion is an agent operation** (via `promote_kb_draft`), executed as part of the production pipeline with **no human gate** — maximum automation, agent as user. A director-driven promote/approval step would cripple production throughput. 03-Wiki remains append-only (no agent demote/delete); deprecation (`status: deprecated`) happens only upon explicit human command.

### 0.4 The Two Orientations (the founding principle)

1. **Tool design is Agent-oriented.** Every capability is an MCP tool; the agent operates the full lifecycle; the human is a secondary consideration of the tool itself. Validation and testing are performed by the agent, for the agent, through the agent.
2. **Project results are End-User-oriented.** The only test of Raw/Processed data quality is the end user. Processed data is written for people. Even when an agent validates deliverables, the evaluation is done **with a human as the end user as the primary view**.

The hierarchy matters: the agent track proves the tool is operable; the human track proves the result is acceptable. Agent evidence without human evidence is, at best, RISK. This corrects the parallel "dual-track" framing in the superseded D1-D5 D3 dimension, which treated human and agent tracks as equal end users.

### 0.5 Scope Basis (why the coverage matrix is authoritative)

The service-coverage scope of this project is grounded in an end-user willingness-to-pay research synthesis, `docs/dev/research/综合报告-资讯付费与AI触达研究.md` (aggregating four agent research reports, 80+ P0/P1 sources, covering 2024-2026 data). From it, `docs/dev/enduser-coverage-matrix.md` maps **99 items across five dimensions** (A sources 29, B output products 25, C channels 14, D domains 16, E agent/commercial capabilities 15) to code and validation coverage. The coverage matrix is the operationalization of "what end users want to pay for"; AC4 grades commitment against it.

### 0.6 Five Principles

| # | Principle | Meaning |
|---|-----------|---------|
| P1 | **Agent-first tooling** | All capabilities are agent-reachable (MCP); the tool is testable and operable by an agent with no human help. |
| P2 | **Human-first results** | Deliverables are judged through a human-as-end-user lens; agent validation is a means, never the end. |
| P3 | **Real-surface evidence** | Evidence comes from real MCP/CLI/REST/LLM/network calls. No mocks, no seeded stores, no simulated layers in runtime paths. |
| P4 | **Committed coverage** | Every scope item is implemented-and-validated **or** explicitly classified (documented limit / out-of-scope / blocked-with-record). No dangling, unclassified gaps. |
| P5 | **The agent grades; the human disposes** | B2 executes and drafts verdicts; B3 adjudicates and signs off. Blockers are findings only — remediation is a B3 decision. |

### 0.7 Dimension Provenance (how this framework was formed)

The dimension set was proposed by the director (2026-08-08), evaluated against the codebase and existing docs, and ratified with the following adjustments:

| Director-proposed dimension | Verdict | Adjustment |
|----------------------------|---------|-----------|
| Three user types | ✅ Kept | Formalized as **AC1**, aligned to the ratified B1/B2/B3 spec; added the human-lens nuance. |
| Raw/Processed data | ✅ Kept | Formalized as **AC2**; split the "raw" ambiguity into internal layer vs shipped product. |
| Dual orientation | ✅ Kept, strengthened | Formalized as **AC3** with an explicit human-first hierarchy (supersedes D3's parallel dual-track). |
| Coverage scope | ✅ Kept | Formalized as **AC4**; added the committed-coverage acceptance criterion (unclassified gaps = 0). |
| *(supplement)* Quality & deliverables | ➕ Added | **AC5**: automated gates (G0-G5/D1-D3) + director sampling review — operationalizes "the end user tests quality." |
| *(supplement)* Commercial viability | ➕ Added | **AC6**: the money path (subscription lifecycle, payment, gating, metering) must be real, since B1 is a *paying* customer. |
| *(supplement)* Process & governance | ➕ Added | **AC7**: who accepts, when, verdict semantics, run reports, change control. |
| *(supplement, 2026-08-08 round 2)* Documentation health | ➕ Added | **AC8**: the docs system must stay lean, current, and single-sourced for an agent-facing tool — grounded in industry best practice (AGENTS.md as index, generated inventory, one-off docs archived, single source of truth). |
| *(supplement, 2026-08-08 round 2)* Test & validation suite health | ➕ Added | **AC9**: the pytest suite (organized by subject, mirroring `src/`) and the agent-facing validation layer (68 real-surface scenarios, agent as tester) must both stay healthy and feed acceptance evidence. |
| *(2026-08-08 director correction)* KB orientation | ➕ Amended | **AC1 criterion 3**: Draft→Wiki promotion is an **agent operation** — AutoInfo's KB is a database for raw/processed production (max automation, agent as user); a human promote gate would cripple production. Human-exclusive class narrowed to destructive ops (permanent purge, domain/source removal). |
| *(2026-08-08 director correction)* Commercial scope | ➕ Amended | **AC6 phase split**: the **payment chain is V2**. V1 validation covers the collection + production pipeline only; V2 criteria (lifecycle billing, checkout, webhooks, entitlement, invoicing) become binding at V2 launch. |

---

## §1 AC1 User Model Integrity

### Definition

The system must honor the three-user model everywhere: B1 pays and consumes, B2 operates via the agent surface, B3 directs and adjudicates. The agent is the operator and the tester; the human is the director; the end user is the payer and the judge.

### Binary acceptance criteria

1. **B2 can operate the full lifecycle with no human help.** An agent, given only the MCP surface, can: enumerate capabilities (`get_tool_count`, `list_validation_scenarios`, `tools/list`), diagnose (`diagnose_system`), configure, collect, process, generate, and deliver. False = FAIL.
2. **B2 can self-verify.** The agent can run validation scenarios against real surfaces and get machine-parseable verdicts (passed / failed / unconfigured) without a human interpreting logs. False = FAIL.
3. **Destructive, B3-decided operations are not reachable by the agent as routine actions.** Operations the director owns — permanent purge (`soft_delete_entry purge`), domain/source removal — are either absent from the agent surface or explicitly gated/escorted (e.g. `confirm` flag), and the constraint is enforced at the code level, not just in documentation. A demonstrable bypass = FAIL. **KB Draft→Wiki promotion is NOT in this class**: it is an agent operation by design (see §0.3 KB orientation).
4. **B1 intent is expressed through subscription configuration, not ad-hoc commands** (per `user-lifecycle-definition.md` §6.1). B1's `content_preference` (`raw_only`/`processed_only`/`both`), tier, channels, and frequency are honored in delivery. A delivered product set that ignores the preference contract = FAIL.
5. **Error envelopes are agent-parseable and human-comprehensible.** All tool responses follow the `{success, error: {code, message, actionable}}` envelope; failures are actionable (`LLM_NOT_CONFIGURED` style), never raw auth errors or silent drops.

### Evidence requirements

- Scenario-library execution demonstrating the B2 lifecycle with no human step (evidence catalog A2/A3).
- A walk of the MCP tool list against the destructive B3-decided operation list (evidence catalog A9).
- Preference test: B1 profiles with each of the three `content_preference` values, delivered product set attached (evidence catalog A8).
- Error-boundary scenario output asserting `actionable` on representative failures.

---

## §2 AC2 Data-Layer Integrity

### Definition

Raw data and processed data are distinct layers with a one-to-one mapping to shipped products. Provenance is mandatory: every process artifact traces to at least one raw entry, and every raw entry has complete source metadata.

**KB tiering semantics (curation model, director decision 2026-08-08):** the three internal tiers are **production stages**, not human knowledge-management stages:

| Tier | Role | Semantics |
|------|------|-----------|
| **01-Raw** | Sole entry point | All collected content lands here with mandatory provenance; immutable source record |
| **02-Draft** | Workspace | Agent-processed summaries; agent creates/edits Drafts from Raw; replaceable via re-processing |
| **03-Wiki** | Curated, trusted | The curated production tier; **append-only**. Reached only through the promotion admission standard |

**Admission standard:** a Draft may be promoted to Wiki only when it passes the CurationGate (provenance complete + G0 schema + G1 `source_score` ≥ 30 + G3 `relevance_score` ≥ 30 + G4 factual re-check — `autoinfo/promotion.py`). A failed check blocks promotion (typed `PromotionRejected`, `_failed/` marker).

**Agent promotes with no human gate:** Draft→Wiki promotion is an **agent operation** (`promote_kb_draft`, `promotion_source: agent`). The agent is the operator and the curator; a human promote/approve gate would cripple production throughput. The director keeps a backdoor (`force_promote` / `demote_kb_wiki`, `AUTOINFO_DIRECTOR_ACTORS` whitelist, default `director`) for deliberate override, and 03-Wiki stays append-only for agents (no agent demote/delete; `WIKI_PROTECTED` blocks non-director deletes on 03-Wiki).

### Binary acceptance criteria

1. **Every shipped product maps to exactly one data layer.** A product is RAW or PROCESSED, never both and never neither. Verify per product via `list_products` / `get_product`; assert each carries a single `product_type` consistent with its content. False = FAIL.
2. **Every process artifact traces to ≥ 1 raw entry.** A digest, report, tutorial, presentation, column, or magazine must cite at least one underlying 01-Raw entry through the provenance path 01-Raw → 02-Draft → 03-Wiki. An artifact with untraceable content = FAIL.
3. **Raw entries carry mandatory provenance.** Every 01-Raw entry has `source_url`, `source_type`, `source_platform`. Missing provenance on any inspected raw entry = FAIL.
4. **RAW products deliver raw data, PROCESSED products deliver processed data.** A RAW feed (api_feed/webhook/bulk_export) must not silently substitute synthesized content; a PROCESSED product must not be presented as raw source material. Violation = FAIL.
5. **The 01-Raw sole-entry rule holds.** No collected content enters the KB pipeline outside 01-Raw (imports land in 01-Raw; drafts are created from raw only). Violation = FAIL.
6. **Promotion is agent-driven with a machine-enforced admission standard.** A Draft reaches 03-Wiki via `promote_kb_draft` with `promotion_source: agent`, passing the CurationGate (provenance + G0 + G1 ≥ 30 + G3 ≥ 30 + G4); a failed admission check blocks promotion. 03-Wiki remains append-only (no agent demote/delete; director-only `force_promote`/`demote_kb_wiki` backdoor records `promotion_source: director`). A promotion path that bypasses the admission standard without director authorization, or an agent demote/delete of a Wiki entry, = FAIL.

### Evidence requirements

- `list_products` / `get_product` reads with data-layer classification (evidence catalog A11).
- Provenance walk for at least one process artifact per PROCESSED product form shipped this version: artifact → KB tier → collected raw item (evidence catalog A10).
- Raw-entry provenance sampling from the real KB (evidence catalog A5/A10).
- Promotion admission evidence: `kb-promote-admission` / `promotion-provenance` scenario runs showing the pass and reject paths (evidence catalog A2).

---

## §3 AC3 Dual Orientation (Agent-Operated Tool, Human-First Results)

### Definition

Two orientations, one hierarchy. The **agent track** proves the tool is operable by an agent (P1). The **human track** proves the results are acceptable to a human end user (P2). Human evidence is the higher bar: an agent-verified feature that no human has read is not accepted.

### 3.1 Agent track (tool operability)

### Binary acceptance criteria

1. **Full-surface agent operability.** An agent can exercise the entire feature surface — MCP tools (145/145), CLI groups (28/28), REST endpoints (8/8), delivery channels (13/13), collector reachability (30/30) — via real calls and record per-feature verdicts. Any surface row with neither a scenario nor a real artifact = FAIL.
2. **Self-discovering coverage.** An agent can enumerate coverage and features using only MCP tools and in-repo audit scripts, with no human help. False = FAIL.

### 3.2 Human track (deliverable acceptability) — the higher bar

### Binary acceptance criteria

3. **Every PROCESSED product form shipped this version has a real, human-readable rendered artifact on record.** Markdown/HTML/PDF (digest, report, tutorial, presentation), audio/video derivatives, EPUB/MOBI/audiobook — each form produced by a real generation path, not a mock. A form with only machine-readable output = RISK at best; a form with no artifact at all = FAIL.
4. **Empty-KB states are honest, never fabricated.** Generating a product on an empty KB yields an honest "no content" state, not a fabricated page. Fabrication = FAIL.
5. **The director reads.** For each PROCESSED product form, at least one real sample is read by the director (human-as-end-user) with a recorded verdict (see AC5). A form with no director verdict = RISK at best.

### 3.3 Hierarchy rule

Agent evidence alone is never sufficient for a deliverable-type acceptance. Where the agent track passes but the human track has no evidence, the verdict is RISK — and RISK blocks sign-off until a human verdict is recorded.

### Evidence requirements

- Scenario-library coverage audit output (evidence catalog A1/A2).
- Rendered artifacts per product form, generated from real content (evidence catalog A6).
- Empty-KB vs populated variance check (evidence catalog A12).
- Director verdict table (evidence catalog A13).

---

## §4 AC4 Coverage Commitment

### Definition

The service-coverage scope is fixed by the end-user willingness-to-pay research synthesis, operationalized by `docs/dev/enduser-coverage-matrix.md` (A-E, 99 items). Acceptance is based on **committed coverage**, not raw percentages: every scope item must be in exactly one committed state, and the set of unclassified items must be empty.

### Item state machine (committed states)

| State | Meaning | Example |
|-------|---------|---------|
| ✅ **Implemented & validated** | Code exists, validation evidence exists, both on the real surface | A1 arXiv, B1 digest, E1 MCP tools |
| ⚠️ **Partial (documented limit)** | Delivered to a defined ceiling; the limit and its rationale are documented; alternative path recorded | A25 OA subset, A7 EOD-level via akshare |
| 🔒 **Blocked (recorded)** | Cannot complete without external action (credential, key, access); recorded as `unconfigured`, never silently skipped | A6 env-gated awaiting keys |
| ⛔ **Out-of-scope (rationale)** | Deliberately not built; the reason is documented (product range, licensing, N/A) | B21 live-streaming, C9 TV, E13 RaaS |
| ❌ **Unclassified** | No state, no decision, no rationale | **This is the only failing state** |

### Binary acceptance criteria

1. **Zero unclassified items.** Every item in the coverage matrix is in one of the four committed states, with the state and its rationale recorded in the matrix or its companion `coverage-gaps.json`. Any item with no status and no decision = FAIL.
2. **No silent passes.** An item whose validation reports `unconfigured` is recorded as Blocked, never counted as passed. A matrix that reports `unconfigured` as coverage = FAIL.
3. **Coverage rates are informational; commitment is binding.** The matrix's Code/Validation/two-way percentages are reported per version for trend visibility, but acceptance hinges on criterion 1, not on a percentage threshold.
4. **The matrix is regenerated per version** from `docs/dev/specs/end-user-matrix.yaml` via `scripts/coverage_matrix.py`, and item states are reconciled with the actual code and scenario library. A stale or hand-edited matrix with no regeneration record = RISK.

### Evidence requirements

- Regenerated coverage matrix (04-MATRIX output) and `coverage-gaps.json` (evidence catalog A14).
- The unclassified-items query: items lacking any committed state, with disposition.

---

## §5 AC5 Quality and Deliverable Acceptance

### Definition

"Only the end user can test the quality of raw and processed data" is operationalized as two complementary evidence streams: automated gates (machine-verifiable, run every time) and director sampling review (human-as-end-user, run per version).

### 5.1 Automated gates

### Binary acceptance criteria

1. **Hard gates cannot be bypassed.** G0 (schema integrity) and G4 (factual consistency) are hard: 3× retry then block, with blocked items written to `_failed/`. A path that silently passes a hard-gate failure = FAIL.
2. **Soft gates act per configuration.** G1 (source authority), G2 (dedup), G3 (relevance), G5 (translation) apply their configured action (archive/flag/pass) with the configuration recorded. A gate running with no recorded configuration = RISK.
3. **Delivery gates are enforced at output time.** D1 (product completeness), D2 (format integrity), D3 (freshness) run per delivery, with the configured thresholds recorded. A delivered product that skipped its gates = FAIL.
4. **Raw-quality signals are present.** Freshness (per-domain TTL), dedup, and source traceability are enforced on the raw layer; stale content is demoted/excluded per lifecycle rules, never silently served. Violation = RISK.
5. **The curation/admission gate is enforced and configured.** The CurationGate (Draft→Wiki promotion admission: provenance + G0 + G1 `source_score` ≥ 30 + G3 `relevance_score` ≥ 30 + G4 factual re-check, per `quality-gates.md` §3.1) is a hard gate: a failed admission check blocks promotion with a typed `PromotionRejected` and a `_failed/` marker, never a silent pass. Its thresholds (`quality_gates.CurationGate`: shared `threshold` default 30, G4 `enabled` default True) are recorded per domain and queryable via `get_gate_config`/`set_gate_config`. A promotion that bypasses the admission standard without director authorization (director-only `force_promote` backdoor) = FAIL.

### 5.2 Director sampling review (human-as-end-user)

For every PROCESSED product form shipped this version, the director reads at least one real sample and records a verdict against the four quality concerns from `market-positioning.md`:

| Quality concern | RAW product lens | PROCESSED product lens |
|-----------------|------------------|------------------------|
| **Completeness / accuracy** | Coverage of the domain's sources; no key items missing | Factual accuracy: no errors, hallucination, or misattribution |
| **Depth / freshness** | Data is current per domain TTL | Analysis depth; timeliness of the briefing |
| **Traceability / presentation** | Source provenance visible | Presentation quality: renders cleanly, reads well for a human |

### Binary acceptance criteria

5. **Every PROCESSED product form has a director verdict on record for the version** (PASS / RISK / FAIL per the four concerns). Missing verdict for any shipped form = RISK at best.
6. **A FAIL verdict on any sample blocks the version** until the director's remediation decision is recorded and re-verified.

### Evidence requirements

- Gate configuration dump and processing logs showing retry-then-block behavior (evidence catalog A15).
- Rendered artifacts with director verdict table (evidence catalog A13).

---

## §6 AC6 Commercial Viability

### Definition

B1 is a paying customer; the money path must be real — **but the payment chain is a V2 requirement** (director decision, 2026-08-08). V1 validation covers the **collection and production pipeline** only: products are producible, costs are visible, and the gating/payment infrastructure is present as V2 preparation. Prices are placeholders (per `user-lifecycle-definition.md` §6.4); viability means the *in-scope* mechanism works, not that the numbers are final.

### Phase split

| Phase | Scope | Binding at |
|-------|-------|-----------|
| **V1** | Collection + production pipeline: RAW/PROCESSED products producible from real content; cost metering visible; tier-gating infrastructure present (V2 prep) | Now |
| **V2** | Full payment chain: end-user lifecycle billing, Stripe checkout (subscription + single-article), signature-verified webhooks, entitlement enforcement, invoicing | V2 launch (deferred) |

### Binary acceptance criteria — V1 (binding now)

1. **RAW and PROCESSED products are producible from real content.** `list_products`/`get_product` return both product types; PROCESSED templates generate real artifacts from real KB content; RAW variants (`api_feed`/`webhook`/`bulk_export`) are defined. A product type that cannot be produced = FAIL.
2. **Cost visibility exists for the director.** Cost metering (LLM tokens, storage, API calls) and cost summaries are queryable (E3). A version that ships new LLM/API-consuming features without cost visibility = RISK.
3. **Tier-gating infrastructure is present** (V2 preparation): `check_access`/G15 gating code and tiered product templates exist; gating is not required to have live payment evidence in V1. Absent infrastructure = RISK (blocks V2 readiness).

### Binary acceptance criteria — V2 (binding at V2 launch)

4. **The end-user lifecycle state machine works.** trial → active → suspended → cancelled transitions are executable and recorded; `activate_trial`, `check_trial_expiry`, `get_subscription_status` behave per spec. Broken transitions = FAIL.
5. **At least one payment path is real and honest.** Stripe checkout (subscription mode and single-article `mode="payment"`) with signature-verified webhooks; the SUSPECT S1 discipline applies — with no `STRIPE_API_KEY`, billing must fail closed with an explicit configuration error, never present fake charges as real. Fake-as-real = FAIL.
6. **RAW products are commercially deliverable per entitlement.** RAW product variants deliver real raw data per subscription entitlement (E11). Missing variant with a paying RAW tier = RISK.

### Evidence requirements

- V1: `list_products` / `get_product` reads; rendered PROCESSED artifacts (A6/A11); cost dashboard output (A18).
- V2 (deferred): lifecycle scenario execution (enduser-journey, A16); checkout + webhook flow with stripe-mock or test keys + S1 disposition (A17); billing summary (A18).

---

## §7 AC7 Process and Governance

### 7.1 Roles

| Role | Responsibility |
|------|----------------|
| **B2 agent-as-tester** | Executes the evidence catalog, collects real artifacts, fills evidence tables, drafts verdicts. |
| **B3 director** | Reviews the run report, adjudicates RISK verdicts, performs the AC5 sampling reads, signs off. Intervenes only on critical errors or blocked evidence (e.g., expired source key). |
| **B1 lens** | Applied by the director on every dimension: "does this serve a paying human end user?" — AC3/AC5 make it explicit; AC1/AC4/AC6 make it structural. |

### 7.2 Triggers

| Trigger | Scope |
|---------|-------|
| **Major release** (pre-launch, shipping to end users) | Full run: all seven dimensions, full evidence catalog. |
| **Minor / patch release** | Delta run: changed modules keep their dimension evidence, SUSPECT table re-scanned, AC4 matrix re-audited, AC5 verdicts refreshed for changed product forms. |
| **Feature wave** (M-wave style: a batch of features + scenarios lands) | Affected-dimension regression on merge: AC2/AC3/AC4/AC5 for the touched surface; AC6 if billing/delivery touched; AC1 if the tool surface changed. |

### 7.3 Verdict semantics (adopted from D1-D5)

| Verdict | Meaning |
|---------|---------|
| **PASS** | All binary acceptance criteria in the dimension hold, with real evidence on record. |
| **FAIL** | At least one binary acceptance criterion is false. |
| **RISK** | Criteria hold but evidence is partial, indirect, or time-limited; or an open SUSPECT item affects the dimension. |
| **`unconfigured`** | A check could not run because a required key is missing. Recorded as a known limit, **never** a pass; re-run once configured. |

An overall FAIL or RISK in any dimension blocks sign-off.

### 7.4 Blocker discipline

Blockers are findings only — no auto-fix, no remediation code, no suggested patch. A blocker entry records what was observed, where, and which criterion it violates. The director decides remediation; the agent grades, the human disposes.

### 7.5 Deliverable

Each run produces one report at `docs/dev/validation-reports/acceptance-<version>.md` following the §10 skeleton: per-dimension verdicts, blocker list, executive summary, evidence pointers. The report body is English (repo convention, source of truth); a Chinese-language summary of verdicts, blockers, and executive summary is included for the director.

### 7.6 Change control

Template-level changes (dimension definitions, criteria, grading rules, the dimension set itself) require B3 approval and a note in §0.7's provenance. Adding evidence rows or updating counts is routine per-version work.

---

## §8 AC8 Documentation Health

### Definition

AutoInfo is an agent-facing tool: the primary consumer of its documentation is an AI agent that must orient quickly and trust what it reads. The documentation system must therefore be **lean** (an agent can find current state fast), **current** (maintained paths describe only the current surface), and **single-sourced** (repeated facts live once, not four times). Grounded in industry best practice: agent-context docs as a short index with progressive disclosure; inventory derived by script, not hand-maintained; one-off docs archived with explicit status; duplicate content loses authority.

**Knowledge-reachability note (director decision, 2026-08-08):** critical knowledge must be *reachable by default* — in AGENTS.md or enforced by an acceptance dimension — not dependent on an agent's reliable invocation of an optional skill. Skills are a progressive-disclosure aid, never the sole carrier of mandatory knowledge.

### Binary acceptance criteria

1. **No unclassified one-off docs in maintained paths.** Migration guides, per-version run reports, and one-off epic conclusions live in `docs/archive/` or their designated run-report location (`docs/dev/validation-reports/`), with an explicit archive/status label. A one-off document in a maintained path (`docs/dev/`, `docs/dev/specs/`) with no archive intent = FAIL. Verified by `scripts/doc_inventory.py` (category + status columns).
2. **Repeated facts are single-sourced.** Status tables (MCP tool count, CLI groups, delivery channels, validation scenarios, demo domains) are verified consistent between `README.md` and `AGENTS.md` by `scripts/doc_inventory.py --check`; any mismatch = FAIL.
3. **The inventory is generated, not hand-maintained.** `docs/dev/doc-inventory.md` is AUTO-GENERATED by `scripts/doc_inventory.py` (header marks it); the doc-management skill must not hand-maintain a full inventory. A stale inventory (missing AUTO-GENERATED header) or a hand-maintained list that drifts = RISK.
4. **AGENTS.md functions as an index, not a dump.** It provides an orientation table into `docs/dev/specs/` and the keystone docs, and its size is reported per version (baseline 452 lines, 2026-08-08) with a downward/stable trend. No orientation structure = RISK; growth without documented need = RISK.
5. **Superseded content is archived, not mixed into active prose.** A superseded or one-off document found in a live path without an archive label (per criterion 1) = FAIL. Maintained docs describe only the current surface.

### Evidence requirements

- `python3 scripts/doc_inventory.py --check` output: inventory + README/AGENTS fact match report (evidence catalog A21).
- Archive listing with status labels (evidence catalog A21).
- Per-version AGENTS.md line count and orientation-structure check.

---

## §9 AC9 Test and Validation Suite Health

### Definition

Two layers, judged separately:

- **(a) Test layer** — the pytest suite (~3728 tests) that verifies the code itself. Industry best practice: organized by subject, mirroring the `src/` package structure; named by subject, not issue number; pyramid-shaped (many fast unit tests, few integration, very few end-to-end).
- **(b) Validation layer** — the agent-facing scenario suite (68 scenarios, 62 functional + 6 regression) executed through the MCP surface by an agent (agent as tester / validator). This layer is the executable specification at the top of the pyramid: real-surface calls, `unconfigured` never passes, per-step trace + root-cause report, regression flywheel. **Judged compliant with best practice as of 2026-08-08**; it is retained as positive acceptance evidence.

### Binary acceptance criteria

1. **Test suite mirrors source structure.** `tests/` is organized into subpackages mirroring `src/` (collectors/, cli/, mcp/, kb/, llm/, output/, delivery/, api/), with a bounded set of ungrouped files at the root (integration/validation/config/historical). More than ~40 ungrouped root files = RISK.
2. **No bug-numbered test filenames.** Regression tests are named by subject (e.g., `test_cli_summaries_tags.py`) with the bug reference kept in the module docstring, not the filename. Any `test_bug_*` file = FAIL. Verified by `scripts/doc_inventory.py --check`.
3. **The test pyramid holds.** Unit tests dominate; integration/end-to-end tests are a minority; slow or external tests are gated (`requires_optional_dep`, env-gated keys). A layer inversion (more e2e than unit) = RISK.
4. **The validation layer is real-surface and self-disclosing.** Scenarios execute real MCP/CLI/REST calls; `unconfigured` results are recorded, never passed; every step carries a trace (step_index/duration/arguments/trace_id); `scripts/coverage_audit.py` reports **zero MISSING tools**; regression scenarios exist with a ~100% pass expectation. A silent env-gated pass or a coverage gap = FAIL.
5. **Validation evidence feeds the acceptance run report.** The per-version report (AC7 §10) records: scenario inventory, coverage_audit result, and per-scenario verdicts. A version whose validation evidence is absent from the report = RISK.

### Known improvement backlog (not yet criteria)

Recorded from external best-practice research (2026-08-08), for future hardening of the validation layer: (1) run each behavioral scenario N times and gate on pass rate (5/5 hard, 4/5 soft) rather than a single run; (2) add a cheap deterministic conformance layer (no LLM) that runs on every push, keeping LLM-gated scenarios on schedule; (3) gate on score delta vs the last green run, not absolute thresholds; (4) add negative cases (assert a tool is *not* called) to catch over-triggering. **Verifiable sources for the best-practice claims:** `docs/dev/best-practice-review.md` §9 (evidence & source index, compiled 2026-08-14) — the independent best-practice review dimension with per-claim evidence strength (🔬 empirical / 📐 convention / ⚖️ contested).

### Evidence requirements

- Test-suite structure audit: per-package file counts + bug-numbered test count (evidence catalog A22).
- Test/validation layer ratio: pytest collect counts by package vs scenario inventory (evidence catalog A23).
- Scenario pass-rate baseline from the run (evidence catalog A24).

---

## §10 Grading and Report Template

### Per-dimension verdict table skeleton

| Dimension | Verdict | Blockers | Evidence artifacts | Notes |
|-----------|:---:|----------|--------------------|-------|
| AC1 User model integrity | | | | |
| AC2 Data-layer integrity | | | | |
| AC3 Dual orientation (agent) | | | | |
| AC3 Dual orientation (human) | | | | |
| AC4 Coverage commitment | | | | (unclassified: N) |
| AC5 Quality (automated gates) | | | | |
| AC5 Quality (director review) | | | | (forms read: N/M) |
| AC6 Commercial viability | | | | |
| AC7 Process & governance | | | | |
| AC8 Documentation health | | | | (one-offs: N; fact mismatches: N) |
| AC9 Test & validation health | | | | (root files: N; bug-named: N; MISSING: N) |
| **Overall verdict** | | | | |

### Executive summary skeleton

```
# Acceptance Run Report <version> (<date>)

Run by: <B2 agent-as-tester> | Reviewed by: <B3 director>
Baseline (no keys): <X passed / Y failed / Z unconfigured at N scenarios>
Keys configured: <yes/no, which>

## Verdicts
- AC1: <verdict>   AC2: <verdict>   AC3: <agent>/<human>   AC4: <verdict> (unclassified: N)
- AC5: <gates>/<director>   AC6: <verdict>   AC7: <verdict>   AC8: <verdict>   AC9: <verdict>

## Executive summary
<3-6 sentences: what was accepted, what passed, what blocks sign-off>

## Blockers
<blocker list: [B-NNN] Dimension | Criterion | Finding | Source | Severity>

## 中文摘要（Director）
<Chinese-language summary of verdicts, blockers, and executive summary>
```

---

## Appendix A: Evidence Catalog

Re-runnable per version, run from the project root. This catalog **replaces** the D1-D5 evidence catalog numbering (A1-A12); where a row overlaps a D1-D5 command, the same command is reused under the acceptance ID. Each row produces the artifact named; attach it to the run report.

| # | Check | Command / surface | Produces | Dimension |
|---|-------|-------------------|----------|-----------|
| A1 | Scenario coverage audit | `python3 scripts/coverage_audit.py` | covered/missing tool list, 145/145 target | AC3-agent, AC1 |
| A2 | Scenario inventory + run | MCP `list_validation_scenarios` / `run_validation_scenario` | per-scenario status (passed/failed/unconfigured), per-step trace, root-cause report | AC1, AC3, AC7 |
| A3 | System phase + health | MCP `diagnose_system`, `get_tool_count` | health_score + phase; live tool count | AC1 |
| A4 | No-simulated-layer scan | grep over `src/` (excl. `tests/`) for `mock`/`fixture`/`placeholder`/`example.com`/`sk_test` | SUSPECT-table hits with dispositions | AC5, AC7 |
| A5 | Real-fetch proof | `collect_sources(domain=…, dry_run=false)` on a real configured source | raw JSON cache + collection log with real `source_url`/`source_type`/`source_platform` | AC2, AC5 |
| A6 | Rendered artifacts | generate digest/report (md/html/pdf), tutorial, presentation, audio/video/ebook as shipped | rendered output artifacts per product form | AC3-human, AC5 |
| A7 | Agent-format validation | `format="agent"` + `jsonschema` against `docs/schemas/*-v1.json` | validated JSON-LD, const-pinned `@context`/`@type` | AC3-agent |
| A8 | B1 preference test | `update_preferences` / `get_preferences` for the three values | preference honored in delivered product set | AC1, AC2 |
| A9 | Destructive-op walk | MCP tool inventory vs destructive B3-decided operation list (purge, domain/source removal); code-level guard check | disposition per operation (absent / gated / bypassed) | AC1 |
| A10 | Provenance walk | `get_kb_entry`, `list_kb_tier`, `trace_item` on one process artifact | artifact → 01-Raw → source chain | AC2 |
| A11 | Product data-layer read | `list_products` / `get_product` | per-product `product_type` classification | AC2 |
| A12 | Empty-KB variance | generate same artifact on empty and populated KB | honest "no content" vs real content | AC3-human |
| A13 | Director reading | director reviews ≥1 real sample per PROCESSED form | director verdict table (PASS/RISK/FAIL × 4 concerns) | AC3-human, AC5 |
| A14 | Coverage matrix regen | `scripts/coverage_matrix.py` (+ `end-user-matrix.yaml`) | 04-MATRIX + `coverage-gaps.json`; unclassified-items query | AC4 |
| A15 | Gate config + logs | `get_gate_config`; processing logs | gate configuration; retry-then-block evidence | AC5 |
| A16 | Lifecycle E2E | `enduser-journey` scenario; `activate_trial` → … → cancel | lifecycle transitions with UX metrics | AC6 |
| A17 | Payment path | Stripe checkout (subscription + single-article) + webhook, stripe-mock or test keys | session creation, webhook verification, S1 disposition | AC6 |
| A18 | Billing/cost visibility | `get_billing_summary`, `cost_dashboard` | billing summary + cost output | AC6 |
| A19 | REST smoke | `curl http://localhost:8741/health`, `/api/v1/entries?limit=5` | envelope JSON | AC1, AC3 |
| A20 | Git cleanliness | `git status --porcelain` | untracked/modified list; no runtime artifacts swept into the run | AC7 |
| A21 | Doc inventory + consistency | `python3 scripts/doc_inventory.py --check` | `docs/dev/doc-inventory.md` + README/AGENTS fact-match report (exit non-zero on mismatch / `test_bug_*` / stale inventory) | AC8 |
| A22 | Test-suite structure audit | `find tests -name "*.py"` grouped by package; grep for `test_bug_*` | per-package file counts; bug-numbered test count | AC9 |
| A23 | Test/validation layer ratio | pytest collect counts by package vs scenario inventory | unit vs integration vs validation-layer composition | AC9 |
| A24 | Scenario pass-rate baseline | `run_validation_scenario` results from the run (regression scenarios included) | per-scenario status; regression ~100% pass expectation | AC9 |

Run order: A20 (cleanliness) → A1/A2/A3 (baseline) → A4 (suspect scan) → A5/A10/A11 (data-layer evidence) → A8/A9 (user-model evidence) → A6/A7/A12 (orientation evidence) → A13 (director reads) → A14 (coverage) → A15 (gates) → A16/A17/A18 (viability) → A19 (surface smoke) → A21/A22/A23/A24 (doc + test/validation health). Record the no-keys baseline first, then set keys and re-run env-gated checks; `unconfigured` results are recorded, never passed.

---

## Appendix B: Glossary

| Term | Meaning |
|------|---------|
| **B1 / B2 / B3** | End User (paying customer) / Direct User (agent operator) / Director User (human owner) — per the ratified user-lifecycle spec. |
| **Raw data** | Original collected material, exactly as fetched (internal layer: 01-Raw; shipped product: RAW product with api_feed/webhook/bulk_export variants). |
| **Processed data** | Raw data after processing: commercial-safety filtering, synthesis, structuring (internal layers 02-Draft/03-Wiki; shipped PROCESSED products). |
| **Dual orientation** | Tool design is agent-oriented; project results are end-user-oriented (human-first hierarchy). |
| **Committed coverage** | Every scope item is implemented-and-validated or explicitly classified; the only failing state is unclassified. |
| **Human-first** | The standard of judgment for deliverables is a human as end user, even when an agent performs the test. |
| **Unclassified gap** | A scope item with no state, no decision, and no rationale — the acceptance failure condition of AC4. |
| **Bug-numbered test** | A test file named after an issue (e.g., `test_bug_39.py`) rather than its subject — the AC9 anti-pattern; regression tests are named by subject with the bug reference in the docstring. |
| **Single source of truth** | A fact (e.g., tool counts, status) is recorded in exactly one canonical place and referenced elsewhere; duplicated facts lose authority and drift (AC8 criterion 2). |
| **Generated inventory** | The documentation inventory is produced by `scripts/doc_inventory.py`, not hand-maintained in a skill — derived metadata, docs-as-code (AC8 criterion 3). |
| **SUSPECT** | A code-level artifact that may violate real-surface authenticity; recorded, investigated, and disposed per AC7/§0.6 P3. |
| **unconfigured** | A check that could not run for lack of a required key; recorded as a known limit, never a pass. |
| **Feature wave** | A batch of features plus scenarios landing together (M-wave style); triggers affected-dimension regression runs. |
