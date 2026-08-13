# User Types & Lifecycle Definition

> **Date:** 2026-07-27
> **Purpose:** Foundational specification — defines the three AutoInfo user types and their complete lifecycles. All other specs (delivery, pipeline, operations, expectations) derive from this framework.
> **Status:** ✅ Ratified — binding for all subsequent spec work and implementation decisions.
> **Change process:** Any modification to user type definitions or lifecycle stages requires director-user approval.
> **Keystone matrix:** [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) — the B1/B2/B3 user rows in the CD catalog derive directly from the lifecycle definitions in this spec. The CD catalog maps these user types against the A1-A7 pipeline stages to identify gaps.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [B1 End User (Paying Customer)](#2-b1-end-user-paying-customer)
3. [B2 Direct User (AI Agent Operator)](#3-b2-direct-user-ai-agent-operator)
4. [B3 Director User (Human Manager)](#4-b3-director-user-human-manager)
5. [Cross-User Interaction Model](#5-cross-user-interaction-model)
6. [Key Architectural Principles](#6-key-architectural-principles)

---

## 1. Architecture Overview

### 1.1 The Three User Tiers

```
┌──────────────────────────────────────────────────────────────────┐
│  B3 Director (Human Manager)                                    │
│                                                                  │
│  Role:  Backup overseer. Delegates daily ops to B2.             │
│         Defines pricing tier config and quality thresholds       │
│         at deploy time. Only intervenes when B2 hits a           │
│         critical error or blocking issue.                        │
│                                                                  │
│  Interacts via: Dashboard, B2-generated periodic reports         │
│                                                                  │
│  Does NOT: Change B2 runtime logic at runtime.                   │
│            (Demo phase: pricing/config changes = code change.     │
│             Production phase: via admin interface.)               │
└────────────────────┬─────────────────────────────────────────────┘
                     │ Deploy-time configuration
                     │ (pricing tiers, quotas, thresholds)
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│  B2 Direct User (AI Agent)                                      │
│                                                                  │
│  Role:  Primary platform operator. Reads B1 subscription          │
│         configs, executes the full pipeline on behalf of B1:     │
│         collect → extract → KB → generate → deliver.            │
│                                                                  │
│  Interacts via: MCP tools (145 tools across 35 categories)      │
│                                                                  │
│  Does NOT: Handle money or pricing decisions.                    │
│            Accept ad-hoc instructions from B1.                   │
│            (B1's intent is expressed ONLY through subscription   │
│             configuration, not natural-language commands.)       │
└──────────┬───────────────────────────────────────────────────────┘
           │ Pipeline execution (collect → extract → deliver)
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  B1 End User (Paying Customer)                                  │
│                                                                  │
│  Role:  Subscriber and consumer. Expresses information needs     │
│         via structured subscription config, receives products    │
│         via configured delivery channels.                        │
│                                                                  │
│  End user types (all treated uniformly):                         │
│  - Individual consumer                                           │
│  - Creator / publisher                                           │
│  - Enterprise / institutional buyer                              │
│  - Platform operator                                             │
│  - Content licensor                                              │
│  - Agent delegate (an AI operating on behalf of the above)      │
│                                                                  │
│  Interacts via: Subscription configuration + delivered products  │
│                                                                  │
│  Does NOT: Directly instruct B2 Agent.                           │
│            Send natural-language commands to the platform.       │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 Interaction Principles

| Interaction | Direction | Format | Description |
|-------------|-----------|--------|-------------|
| **B1 → AutoInfo** | NL-in, structured-out | Natural language → (Agent + LLM) → structured subscription config | B1 communicates in natural language. The B2 Agent, powered by LLM, decomposes B1's NL intent into structured subscription configuration (tier, domains, channels, frequency, preference). Subscription config is the storage/execution layer, not the interaction layer. |
| **AutoInfo → B1** | One-way delivery | Products (digest, report, tutorial, presentation, alert) via channels | Products are pushed to B1 based on subscription config. B1 does not "request" individual products. |
| **B2 → AutoInfo** | Full control | MCP tools | B2 is the primary operator. It configures sources, triggers collection, manages KB, generates and delivers products — all through MCP. |
| **B1 ↔ B3** | Billing only | Payment / subscription management | Money flows between B1 and B3 (or B3's billing system). B2 is never involved in financial transactions. |
| **B3 → B2** | Policy only | Deploy-time configuration | B3 sets pricing tiers, domain quotas, quality thresholds at deploy time. At runtime, B3 monitors B2 via dashboards and reports but does not change B2's operational logic. |

---

## 2. B1 End User (Paying Customer)

### 2.1 Definition

The **B1 End User** is the paying customer — an individual or organization that subscribes to AutoInfo's information products. All B1 user types (individual consumer, creator, publisher, enterprise buyer, institutional buyer, platform operator, content licensor, agent delegate) are **treated uniformly**: no demographic, role-based, or accessibility-based segmentation is applied.

B1 interacts in **natural language**. The B2 Agent (powered by LLM) parses B1's NL intent and translates it into **structured subscription configuration** for platform execution:

```
B1: "帮我关注台积电财报和AI芯片新闻，每天推送到微信"
  → Agent + LLM parses NL intent
  → Structured config:
      domains:    ["financial-intelligence", "tech-ai-developer"]
      topics:     ["TSMC earnings", "AI chips"]
      frequency:  daily
      channels:   [WeChat]
```

The subscription config fields (storage/execution layer):

1. **Subscription tier** — free / premium / enterprise (prices are placeholders)
2. **Domain selection** — which domains to track (one or multiple)
3. **Content preference** — raw data only, processed products only, or both
4. **Delivery channel preference** — email, chat (Telegram/WeChat/Discord/etc.), RSS, REST API, file export, webhook
5. **Receiving frequency** — real-time, daily, weekly, monthly, custom cron

B1 **cannot** (these remain platform-level constraints, not interaction constraints):
- Directly instruct the B2 Agent outside the NL→config pipeline
- Trigger one-off collection or processing runs bypassing subscription config
- Modify pipeline logic or quality gates

### 2.2 Lifecycle Stages

```
                   ┌──────────┐
             ┌────►│ Discover │  ← B1 becomes aware of AutoInfo
             │     └────┬─────┘     Referral path: existing B1 refers new B1
             │          │
             │     ┌────▼─────┐
             │     │ Subscribe│  ← Choose tier + configure domains/
             │     │          │     channels/frequency/content pref
             │     └────┬─────┘     → Create subscription record
             │          │
             │     ┌────▼─────┐
             │     │ Onboard  │  ← First-product experience: initial delivery,
             │     │          │     preference verification, cross-product
             │     │          │     up-sell, "aha moment" design
             │     └────┬─────┘
             │          │
             │     ┌────▼─────┐
             │     │ Consume  │  ← AutoInfo pushes products via
             │     │          │     configured channels on schedule
             │     └────┬─────┘
             │          │
             │    ┌─────┼──────────┐
             │    │     │          │
             │ ┌──▼──┐ ┌▼─────┐ ┌─▼──────┐
             │ │Modif│ │Upgrad│ │ Churn  │
             │ │y    │ │e/    │ │        │
             │ │Confi│ │Downgr│ └───┬────┘
             │ │g    │ │ade   │     │
             │ └─────┘ └──────┘     │
             │                      │
             │                 ┌────▼──────┐
             │                 │Reactivation│  ← Churned B1 may return:
             │                 │           │     within retention window,
             │                 │           │     restore subscription + data
             │                 └────┬──────┘
             │                      │
             └──────────────────────┘
```

| Stage | Trigger | Description | Notes |
|-------|---------|-------------|-------|
| **B1.1 Discover** | External (marketing, referral, search) | B1 learns about AutoInfo: product capabilities, pricing tiers, sample outputs, supported domains, delivery channels. **Referral sub-path**: existing B1 can refer new B1 via referral link/reward mechanism. | Requires a **product catalog / storefront** (CD-010). Until built, discovery is manual (operator-led). Referral requires a reward tracking system. |
| **B1.2 Subscribe** | B1 decision to start | B1 interacts in natural language (via Agent NL→Config pipeline) or directly selects: tier, domains, channels, frequency, content preference. A **Subscription** record is created with structured config. | **Trial** is not a separate stage — it's a **subscription with tier=free** that may have time-limited premium features. The subscribe action is the same regardless of trial status. |
| **B1.3 Onboard** | First subscription activated | B1 receives their **first product delivery** — this is the critical "aha moment". Agent performs: initial delivery with explanation, preference verification (are the right topics being tracked?), cross-product introduction (digest, report, alerts), channel delivery confirmation. | 🆕 This stage is critical for retention. First delivery quality determines whether B1 continues to Consume or churns early. Onboarding may trigger a config refinement loop if initial NL→Config translation was imprecise. |
| **B1.4 Consume** | Scheduled or event-triggered | AutoInfo (via B2) executes the pipeline per B1's subscription config: collect → extract → KB → generate products → deliver via configured channels. B1 receives products passively (push model, not pull). | B1 does not "request" individual products. Delivery is driven by subscription configuration. |
| **B1.5 Modify Config** | B1 initiates change | B1 changes any config parameter (via NL or direct edit): tier upgrade/downgrade, add/remove domains, change channels, adjust frequency, toggle content preference. **If change affects billing, the price change takes effect from the next billing cycle.** The config change itself takes effect immediately for non-billing parameters. | Config modification is the primary B1 maintenance action. Renewal is a billing event, not a product experience event. Tier upgrade = immediate feature access, next-cycle pricing. |
| **B1.6 Churn** | B1 cancels | Subscription is cancelled. Delivery stops. Data retention policy applies (soft-delete, grace period for reactivation, eventual cleanup). B1 may export their data. | The subscription lifecycle (trial → active → suspended → cancelled) is a **billing state machine** orthogonal to the product lifecycle. A cancelled user's KB entries persist (soft-deleted, tier-dependent retention). |
| **B1.7 Reactivate** | Churned B1 returns | Within data retention window, B1 can restore their subscription and data. Config is restored from before churn (if available) or created fresh. Reactivation is not the same as new subscription — history, preferences, and content continuity may be preserved. | 🆕 Reactivation requires: retention window not expired, ability to restore soft-deleted subscription record, config snapshot from pre-churn state. Reactivation economics differ from acquisition (lower CAC but higher churn risk). |

### 2.3 B1 Subscription Config Model (Required Fields)

For the demo ("五脏俱全"), the subscription config must include at minimum:

| Field | Type | Values | Behavior on Change |
|-------|------|--------|-------------------|
| `tier` | enum | `free` / `premium` / `enterprise` | Billing impact → next cycle. Product access changes immediately. |
| `domains` | list of domain names | e.g., `["medical-research", "tech-ai"]` | Takes effect on next pipeline run. |
| `content_preference` | enum | `raw_only` / `processed_only` / `both` | Affects which product types are generated/delivered. |
| `channels` | list of `{channel_type, config}` | See delivery channel list | Takes effect on next delivery. |
| `frequency` | cron expression or preset | `realtime` / `daily` / `weekly` / `monthly` / custom | Determines pipeline execution schedule. |
| `active` | bool | `true` / `false` | If `false`, pipeline runs but no products are delivered (pause). |

### 2.4 Config Change & Billing Interaction

```
B1 modifies config
       │
       ├── Non-billing change (channels, domains, content_pref, frequency)
       │     └── Takes effect immediately on next pipeline run
       │
       └── Billing-affecting change (tier upgrade/downgrade)
             └── Price change → next billing cycle
                 Product access change → immediate
```

**Key rules:**
- **Tier upgrade**: Premium features become available immediately. Extra charge prorated, appears on next invoice.
- **Tier downgrade**: Premium features are lost at end of current billing cycle. New (lower) price applies next cycle.
- **Non-billing config changes**: Always take effect immediately (domains, channels, frequency, content preference).
- **Pause/Resume**: Setting `active=false` stops delivery but retains config. Setting `active=true` resumes with existing config.
- **Price implementation**: All prices are **placeholders** in the demo phase. The pricing logic (which tier costs what) is configurable by B3 but the actual numeric values are determined by business case analysis, not engineering.

---

## 3. B2 Direct User (AI Agent Operator)

### 3.1 Definition

The **B2 Direct User** is an AI agent that serves as the **primary operator** of the AutoInfo platform. B2:

- Connects to AutoInfo via the MCP protocol (stdio; SSE is future work)
- Uses 145 MCP tools to configure sources, run collection, manage the KB, generate products, and orchestrate delivery
- Reads B1 subscription configs to determine what to collect, process, and deliver for each B1 user
- Operates autonomously on a schedule — executing the full pipeline for all active subscriptions
- Reports execution status and anomalies to B3 (Director) for oversight

B2 **does not**:
- Handle money, pricing, or billing decisions
- Accept ad-hoc instructions from B1 end users
- Modify its own runtime logic or core pipeline configuration

### 3.2 Lifecycle Stages

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Discover │──→│ Connect  │──→│ Configure│──→│ Operate  │──→│ Monitor  │──→│ Report   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

| Stage | Trigger | Description | MCP/CLI Coverage |
|-------|---------|-------------|-----------------|
| **B2.1 Discover** | B2 connects to AutoInfo | B2 discovers available capabilities: MCP tool list, registered domains, available sources, output templates, LLM models. | ✅ `health_check`, `list_domains`, `list_available_platforms`, `list_available_models`, `list_output_templates` |
| **B2.2 Connect** | Session establishment | B2 establishes MCP connection (stdio; SSE is future work), authenticates (if applicable), verifies system health. | ✅ `diagnose_system`, MCP protocol auto-discovery |
| **B2.3 Configure** | Initial setup or domain change | B2 configures sources, topics, extraction schemas, and schedules for each active domain. This is done once (or when domains change), not per-cycle. | ✅ (`add_source`, `add_topic`, `add_schedule`, `get_schedule_status`) but 🟡 `add_sources` batch lacks dry-run |
| **B2.4 Operate** | Scheduled pipeline execution | B2 reads all active B1 subscription configs, deduplicates domain/source requirements, runs collection → processing → KB → generation → delivery. This is the **core loop** — repeated on each schedule tick. | ✅ Core pipeline tools all exist. ✅ All 7 previously-gapped tools now registered (see §3.3). |
| **B2.5 Monitor** | Ongoing oversight | B2 monitors: pipeline execution success/failure, source health, delivery SLA compliance, cost trends, anomaly detection. | 🟡 Some monitoring tools exist (`get_collection_progress`, `trace_item`). No unified monitoring dashboard. |
| **B2.6 Report** | Periodic or on exception | B2 generates execution reports for B3 (Director): what was collected, what was delivered, errors encountered, cost summary, anomaly flags. B3 reviews these reports but does not change B2's runtime logic. | ❌ No structured reporting mechanism exists. This is a gap. |

### 3.3 B2 MCP Tool Gaps

> ✅ **Resolved 2026-08-04** — all tools previously listed as "backend exists, MCP not registered" in this gap table are now registered (145/145 tools). This includes `compare_versions` (Knowledge Lifecycle), `get_schedule_status` (Cron), and the End User tools `get_delivery_log`, `send_to_enduser`, `activate_trial`, `check_trial_expiry`, `update_preferences`. No MCP surface gaps remain.

---

## 4. B3 Director User (Human Manager)

### 4.1 Definition

The **B3 Director User** is a human who owns and operates the AutoInfo platform. B3 is a **backup overseer**, not a daily operator:

- **Deploy-time**: Sets pricing tiers, domain quotas, quality thresholds, and system configuration. In the demo phase, this is done via code/config changes. In the production phase, this is done via admin interface.
- **Runtime**: Does NOT change B2's operational logic. Monitors B2 via dashboard and B2-generated periodic reports.
- **Intervention**: Only steps in when B2 encounters a **critical error** or **blocking issue** that B2 cannot resolve autonomously (e.g., source API key expired, disk full, KB integrity violation).

B3 **does not**:
- Operate the pipeline directly (no daily collect/process/deliver)
- Change B2's runtime logic dynamically (B2's behavior is encoded)
- Handle individual B1 subscription management (that's automated)

### 4.2 Lifecycle Stages

```
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Configure│──→│ Monitor  │──→│Intervene │
└──────────┘   └──────────┘   └──────────┘
     │              │              │
     │ (done once   │ (ongoing,    │ (rare — only on
     │  at deploy)  │  passive)    │  critical error)
     ▼              ▼              ▼
```

| Stage | Trigger | Description | Current Status |
|-------|---------|-------------|----------------|
| **B3.1 Configure** | Deploy / upgrade | B3 sets: pricing tier definitions (placeholder values), domain-to-tier mapping, per-domain quality thresholds (source tier minimums, relevance score minimums), delivery SLA targets, data retention policies. In demo phase, these are code-level constants or config file values. | 🟡 Partially done. Some thresholds exist as constants in code. No unified "B3 config" that bundles pricing + quality + SLA + retention. |
| **B3.2 Monitor** | Ongoing | B3 reviews: B2 periodic execution reports, dashboard (system health, collection stats, delivery success rates, cost burn, anomaly flags), alert notifications (cron failure, budget threshold breached, source unreachable). B3 does NOT proactively intervene unless alerted. | 🟡 Dashboard exists (Web UI Bootstrap 5) but limited to collection stats + KB search. No execution reports. No anomaly alerting beyond budget alerts. |
| **B3.3 Intervene** | Critical error or blocking issue | B3 takes manual action: repair broken source config, restore deleted entries, clear disk space, restart failed services. (Note: promote Draft→Wiki is **no longer** a B3 action — 2026-08-08 director decision: promotion is an agent operation, the KB being a database for raw/processed production.) | 🟡 Manual CLI operations exist (`soft_delete_entry`, `restore_entry`). No structured incident response workflow. No "intervention mode" in the UI. |

### 4.3 B3 Configuration Scope (Demo Phase)

For the demo ("五脏俱全"), B3 must be able to configure (via code/config):

| Config Domain | Parameters | Implementation |
|---------------|------------|----------------|
| **Pricing tiers** | Tier names (`free`/`premium`/`enterprise`), placeholder prices, feature-to-tier mapping | Code-level `PricingTier` enum with placeholder price values |
| **Domain quotas** | Max domains per tier, max sources per domain | Code constants |
| **Quality thresholds** | Min source tier per domain, min relevance score, G0-G5 gate behavior (hard vs soft) | Existing gate config system |
| **Delivery SLA** | Max delivery latency per priority (P0/P1/P2) | Existing SLA constants |
| **Data retention** | Soft-delete window per tier, auto-cleanup period | Existing constants |

---

## 5. Cross-User Interaction Model

### 5.1 Request Flow

```
B1 End User                                         B1 End User
    │                                                    ▲
    │ ① Subscribe / Modify Config                        │ ④ Receive products
    │    (structured: tier, domains,                      │    (digest, report, tutorial,
    │     channels, frequency,                             │     presentation, alert)
    │     content preference)                              │
    ▼                                                    │
┌───────────────────────────────────────────────────────────┐
│  AutoInfo Platform                                        │
│                                                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │  B2 Agent (internal operator)                     │   │
│  │                                                    │   │
│  │  ② Read all active B1 subscription configs         │   │
│  │  ③ Deduplicate → collect → extract → KB → gen     │   │
│  │  ④ Route products to B1's configured channels      │   │
│  │                                                    │   │
│  │  ⑤ Periodically report to B3                       │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                │
└─────────────────────────┼────────────────────────────────┘
                          │
                          ▼
                    B3 Director
                    (monitors via dashboard + reports,
                     intervenes only on critical error)
```

### 5.2 Configuration Change Flow

```
B1 changes their subscription config
       │
       ▼
B2 detects config change on next pipeline cycle
       │
       ├── Non-billing fields changed (domains, channels, frequency, content_pref)
       │     └── Apply immediately → next pipeline run uses new config
       │
       └── Billing-affecting field changed (tier)
             └── Update product access → immediate
                 Update price → next billing cycle
                 │
                 ▼
           B3 billing system (or placeholder) handles the financial delta
```

### 5.3 Error Escalation Path

```
B2 encounters an error during operation
       │
       ├── Recoverable (source timeout, rate limit, temp API failure)
       │     └── B2 retries with backoff → succeeds → continue
       │
       ├── Degraded (source unreachable after retries, partial delivery failure)
       │     └── B2 continues with degraded state, logs anomaly
       │         B3 sees anomaly in next report → may investigate
       │
       └── Critical (KB integrity violation, disk full, config corruption)
             └── B2 halts affected pipeline, alerts B3 immediately
                 B3 intervenes manually (repair, rollback, config fix)
```

---

## 6. Key Architectural Principles

### 6.1 NL-In, Structured-Out: B1 Intent Pipeline

B1 communicates in **natural language**. The B2 Agent (powered by LLM) translates NL intent into structured subscription configuration:

```
B1: "我想跟踪AI芯片行业动态"
  → Agent parses → structured config stored → pipeline executes on schedule
```

This is not a constraint — it's a pipeline. The key architectural principles:

1. **Interaction layer is NL** — B1 speaks naturally, as they would to a human analyst.
2. **Translation layer is Agent + LLM** — B2 decomposes NL into structured fields (domain, topic, frequency, channel).
3. **Execution layer is structured config** — The pipeline runs deterministically against config, not against raw NL.
4. **B1 cannot bypass the translation layer** — Once config is set, B1's intent is expressed through the subscription lifecycle, not through one-off NL commands to the pipeline.

This design combines the flexibility of NL interaction with the determinism of structured execution. AutoInfo is an **autonomous information service** — it listens in NL, reasons in structured config, and executes deterministically.

### 6.2 B2 Is the Sole Operator

B2 is the only entity that directly operates AutoInfo's pipeline. B3 configures at deploy time and monitors at runtime, but does not operate. B1 configures their subscription but does not operate. This single-operator model ensures:
- Clear audit trail (all actions are through B2)
- Predictable pipeline execution (B2's behavior is deterministic, not ad-hoc)
- Simplified error handling (one operator to monitor and debug)

### 6.3 B3 Is Backup, Not Daily Operator (Agent-First Principle)

This is the core philosophy of AutoInfo: **the Agent operates, humans direct.**

B3's role is deliberately limited:
- **Configure at deploy time** — not at runtime
- **Monitor passively** — via dashboards and B2 reports, not by watching live logs
- **Intervene only on exception** — critical errors that B2 cannot self-heal

**Why this is non-negotiable**: In the LLM era, having a human as the daily operator is a structural disadvantage. An agent-operated platform runs 24/7, scales to hundreds of B1s without linear human cost, and improves autonomously. B3's job is to set policy and handle edge cases, not to manually operate pipelines.

**Demo imperative**: The demo must demonstrate this agent-first state as faithfully as possible. If the demo shows B3 micro-managing B2, it fails to prove the thesis. B3 intervention is an **exception path**, not a design intent.

### 6.4 Pricing Is a Placeholder (Demo Phase)

During the demo phase:
- All price values are **placeholders** (e.g., `free=$0`, `premium=$29`, `enterprise=$199`)
- The **pricing logic** (which features map to which tier) is real and functional
- The **specific numeric values** are determined by business case analysis, not engineering
- B3 can change pricing config at code/config level

### 6.5 Billing-Affecting Config Changes Defer to Next Cycle

When B1 changes their subscription config:
- **Non-billing changes** (domains, channels, frequency, content preference) → take effect immediately
- **Tier changes** → product access changes immediately, but the **price change** takes effect from the next billing cycle

This prevents billing surprises and simplifies the subscription state machine.

---

## Appendix: Document Dependencies

This document is the **root specification** for the AutoInfo user model. All other spec documents derive from it:

| Document | Derives From | Covers Lifecycle Stages | Relationship |
|----------|-------------|------------------------|-------------|
| `expectations.md` | This doc (entire) | All B1/B2/B3 stages (mapped to F01-F72) | Founder expectations indexed to lifecycle stages. §3 preamble defines B1/B2/B3 terminology. F65-F68 cover B1 lifecycle gaps, F69 covers B2 Report, F70-F72 cover B3 lifecycle. |
| `delivery.md` | This doc §2.2 (B1 Lifecycle), §2.3 (B1 Config), §2.4 (Config Change) | B1.2 Subscribe, B1.3 Onboard, B1.4 Consume, B1.5 Modify Config, B1.7 Reactivate | Delivery channel behavior per B1 subscription config. §4 (End User Lifecycle), §11 (B1 Lifecycle Integration: Onboarding, NL→Config, Reactivation). |
| `pipeline.md` | This doc §3 (B2 Operate lifecycle) | B2.1-B2.6 (all B2 stages) | Pipeline execution model for B2. §2 (KB Pipeline) executes in B2.4 Operate. §9 (B2 Lifecycle Integration) maps all 6 B2 stages. |
| `operations.md` | This doc §4 (B3 lifecycle) | B3.1 Configure, B3.2 Monitor, B3.3 Intervene | B3 monitoring, intervention, and configuration. §7 (B3 Lifecycle Integration) creates unified config scope, dashboard spec, and incident response workflow. |
| `data-models.md` | This doc §2.3 (Subscription Config Model), §2.1 (NL→Config pipeline) | B1.2 Subscribe, B1.3 Onboard, B1.5 Modify Config | Data model schemas: `SubscriptionConfig` (§4.9), `ReferralRecord`/`OnboardingRecord`/`ReactivationRecord`/`NLConfigAuditEntry` (§4.10-4.13). |
| `quality-gates.md` | This doc §4.3 (Quality thresholds) | B3.1 Configure | Gate configuration by B3. Per-domain quality thresholds are part of B3 unified configuration. |
| `docs/dev/cross-dimensional-catalog.md` | This doc (entire) | All B1/B2/B3 stages | Keystone product matrix — B1/B2/B3 user rows mapped against A1-A7 pipeline stages (supersedes the archived comprehensive gap audit). Covers all lifecycle stages. |
| `market-positioning.md` | This doc §2.1 (End user types) | B1 lifecycle (commercial context) | Market analysis — informational, not prescriptive. Provides WTP data and personas. |
