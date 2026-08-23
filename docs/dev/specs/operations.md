# Operations: Cost, Data Privacy, Knowledge Lifecycle, Observability, Feature Flags, Business Metrics

> Extracted from `founder-expectations.md §§12.16-12.19`. References: F28-F29 (Cost), F30-F31 (Data), F36-F39 (Lifecycle), F40-F44 (Observability). Sections 1.5, 2.5, 2.6, 3.6, 5, 6 added per `cross-dimensional-catalog.md` gap coverage (CD-004, CD-006, CD-009, CD-012, CD-030, CD-037, CD-038, CD-041).
>
> **B3 lifecycle:** `docs/dev/specs/user-lifecycle-definition.md` §4 (B3 Director User Lifecycle). Operations functions map to B3.1 Configure (unified config), B3.2 Monitor (dashboard), and B3.3 Intervene (incident response). See §7 for the full B3 lifecycle mapping.

---

## 1. Cost Governance & Metering (§12.16)

### 1.1 Cost Categories

| Category | Tracked Values | Unit | Precision |
|----------|---------------|------|-----------|
| **LLM Tokens** | model, prompt_tokens, completion_tokens, cost | tokens → USD | per API call |
| **Storage** | KB entry count, total bytes, git objects | bytes → MB | daily snapshot |
| **API Calls** | MCP tool invocations, external API requests | count | per call |
| **Delivery** | Channel usage per delivery | count | per delivery |

### 1.2 Cost Log Schema

```python
@dataclass
class CostLog:
    id: str                          # "cost_{uuid8}"
    category: str                    # "llm" | "storage" | "api" | "delivery"
    domain: str
    user_id: str | None = None       # For per-user allocation
    trace_id: str = ""               # Link to pipeline trace
    amount: float
    currency: str = "USD"
    metadata: dict = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=datetime.now)
```

### 1.3 Cost Allocation Strategies

| Strategy | Description | v1 Implementation |
|----------|-------------|-------------------|
| **Pro-rata** | Split costs evenly across all active users | Default for shared LLM calls. `total_cost / active_users`. |
| **Usage-based** | Attribute costs to the user who triggered the action | Per-user extraction, per-user delivery. Direct attribution. |
| **Direct allocation** | Attribute costs to the domain + task that consumed them | LLM costs → `{domain}/{task_type}` tag; storage → `{domain}/{tier}` tag. Default for all pipeline costs. |

**Direct allocation detail**: Every LLM call records `domain` and `task_type` (e.g., `extraction`, `g4_factual_check`, `relevance_scoring`). Storage costs record `domain` and `tier`. This enables domain-level cost reporting without user attribution.

### 1.4 Cost Dashboard & Alerts

**MCP Tools**:

| Tool | Description |
|------|-------------|
| `cost_dashboard(domain, period)` | Aggregate costs by category and domain for period |
| `get_billing_summary(user_id, period)` | Per-user billing summary |
| `set_budget_thresholds(domain, threshold_amount, period)` | Trigger alert when cost exceeds threshold |
| `get_budget_thresholds(domain)` | List active budget thresholds for domain |
| `cost_allocation(domain, period, strategy)` | Show cost breakdown by allocation strategy |

**Budget alerts**: When a domain's cost exceeds configured threshold within a period, an alert is generated via the Alert Rules system. Auto-remediation actions can be configured (e.g., pause collection, switch to cheaper model).

### 1.5 Email Templates

> **Cross-ref:** CD-009 (Email Templates). Automated lifecycle notifications ship via `notifications.py` — trial-ending reminders (3-day window, `check_expiring_trials()`) and content-ready notifications (`notify_content_ready()`) — and `send_email_digest` works. A full Jinja2 template engine covering all four lifecycle email types below remains the spec gap.

AutoInfo sends four lifecycle email types beyond the existing digest delivery. Each template is a Jinja2 file with structured variables, rendered through a shared engine before SMTP dispatch.

#### Template Types

| Template | Trigger | Recipient | Priority |
|----------|---------|-----------|----------|
| **Welcome** | `activate_trial()` completes | New end user | P1 |
| **Trial-ending** | Trial period enters final 3 days | Trial user | P0 |
| **Digest-ready** | Scheduled digest generation completes | Subscribed user | P1 |
| **Cancellation confirmation** | Subscription state transitions to `cancelled` | Former subscriber | P0 |

#### Template Variables

Each template receives a shared context plus template-specific variables:

```python
@dataclass
class EmailTemplateContext:
    # Shared
    user_id: str
    user_name: str
    domain: str
    locale: str = "en"          # "en" | "zh" | "ja"
    unsubscribe_url: str
    dashboard_url: str

    # Template-specific (populated per type)
    trial_end_date: datetime | None = None       # welcome, trial-ending
    trial_days_remaining: int | None = None      # trial-ending
    digest_summary: str | None = None            # digest-ready
    digest_url: str | None = None                # digest-ready
    cancellation_reason: str | None = None      # cancellation
    data_export_url: str | None = None           # cancellation (GDPR)
```

#### Rendering Engine

Templates are Jinja2 files stored under `templates/email/{locale}/{template_name}.html`:

```
templates/email/
├── en/
│   ├── welcome.html
│   ├── trial-ending.html
│   ├── digest-ready.html
│   └── cancellation.html
├── zh/
│   └── ...
└── ja/
    └── ...
```

Rendering pipeline:

1. Load template file by `{locale}/{template_name}`
2. Populate `EmailTemplateContext`
3. Jinja2 render to HTML body
4. Generate plain-text fallback via HTML stripping
5. Dispatch via `email_sender.send_email(to, subject, html_body, text_body)`

**Locale fallback**: If a template is missing for the requested locale, fall back to `en`. Log a warning. Never fail delivery due to a missing locale template.

#### MCP Tools (Spec'd, Not Implemented)

| Tool | Description |
|------|-------------|
| `list_email_templates(locale)` | List available templates for locale |
| `render_email_template(template_name, context)` | Render template to HTML + text without sending |
| `send_template_email(user_id, template_name, variables)` | Render and dispatch lifecycle email |

**Status:** ✅ Implemented (CD-009). Automated notifications shipped — trial-ending reminders (3-day window) and content-ready notifications via `notifications.py`. The template-engine MCP tools above remain spec-only. See CD-009 in `cross-dimensional-catalog.md`.

---

## 2. Data Privacy & Compliance (§12.17)

### 2.1 Soft Delete & Restore

```python
@dataclass
class AuditLog:
    id: str                          # "audit_{uuid8}"
    action: str                      # "soft_delete" | "restore" | "promote" | "merge" | "collect" | ...
    entity_type: str                 # "kb_entry" | "user" | "subscription"
    entity_id: str
    operator: str                    # "agent" | "human:{name}"
    details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
```

- **Soft delete**: KB entries get `status: deleted` in frontmatter; git commit records the change. No data lost.
- **Restore**: Revert the status field; git `revert` on the commit.
- **Hard delete** (GDPR): After 30-day soft-delete window, entries can be permanently removed (git filter-branch or new clone without the history).
- **Audit log is append-only**: Immutable record of all data-modifying operations.

#### Audit Log — GDPR Exemption (M1T15, user-approved append-only policy)

Audit log rows are **exempt from GDPR purge**. This is a deliberate policy, not
an oversight:

- `delete_user_data(user_id, confirm)` MUST NOT delete or redact `audit_log` rows.
- `soft_delete_entry(..., purge=True)` never touches `audit_log`.
- `export_user_data(user_id)` MAY include audit rows (metadata only — actor,
  action, tool, resource, result_code, trace_id; never tool inputs or response
  payloads) so the user can see their footprint, but the export is read-only.
- **Rationale**: the append-only invariant above makes the audit log the
  immutable record of *who did what*. Purging it on request would destroy the
  compliance trail the log exists to provide. The dispatch-level hook (M1T15)
  writes only the six whitelisted fields, so audit rows contain no user content.
- **Contrast with retention (§2.5)**: the per-tier audit retention figures are
  *query-time filters only* — rows are never physically deleted. Every other
  data class remains purgeable under GDPR; only `audit_log` is exempt.

### 2.2 Data Export (GDPR)

`export_user_data(user_id)` gathers:
- User profile and delivery preferences
- Subscription history
- Delivery logs (metadata — not product content)
- No KB entries are included in user data export (KB is domain-owned, not user-owned)

### 2.3 Retention & TTL

| Data Type | Retention | Cleanup |
|-----------|-----------|---------|
| Soft-deleted entries | 30 days | Auto-permanent-delete after 30d |
| Delivery logs | 90 days | Auto-purge after 90d |
| Cost logs | 90 days | Auto-purge after 90d |
| Collection cache | 7 days | Auto-clean after 7d |
| KB entries (active) | Indefinite | User-configurable TTL per domain |

### 2.4 MCP Data Privacy Tools

| Tool | Description |
|------|-------------|
| `soft_delete_entry(entry_id, reason)` | Mark entry as deleted; log to audit |
| `restore_entry(entry_id)` | Restore soft-deleted entry |
| `export_user_data(user_id)` | Gather all user data for GDPR export |
| `delete_user_data(user_id, confirm)` | GDPR delete (requires confirmation) |
| `query_audit_log(entity_type, entity_id, limit)` | Browse immutable audit trail |

### 2.5 Retention by Tier

> **Cross-ref:** CD-012 (Retention & Churn Analysis). The lifecycle state machine exists (trial → active → suspended → cancelled) but retention varies by subscription tier. This section specs differential retention.

Retention windows differ by subscription tier. Free users get short retention to limit storage cost. Paid tiers get longer windows. Enterprise gets compliance-grade retention.

#### Retention Schedule

| Tier | KB Entry Retention | Delivery Log Retention | Cost Log Retention | Audit Log Retention |
|------|-------------------|----------------------|-------------------|-------------------|
| **Free** | 30 days | 30 days | 90 days | 90 days |
| **Premium** | 90 days | 90 days | 90 days | 90 days |
| **Enterprise** | 180 days | 180 days | 180 days | 180 days |

> **Note:** Per-tier retention enforcement is spec-only — no code enforces it today (kb.py default `ttl_days=90`). Retention windows (authoritative spec values from `delivery.md` §11.4): **Free 30 days / Premium 90 days / Enterprise 180 days**.
>
> **Note:** Audit Log rows are **exempt from GDPR purge** — see §2.1 (M1T15). The 90-day figures above for `Audit Log Retention` are query-time filters, not deletion deadlines; `audit_log` rows are never physically deleted.

**Rationale:** Matches `delivery.md` §11.4 (authoritative retention windows). Free tier aligns with the existing 30-day soft-delete window. Premium covers a 90-day window. Enterprise gets compliance-grade 180-day retention.

#### Enforcement Points

Retention is enforced at query and export time, not at write time. Entries are never deleted on a timer. Instead, entries older than the tier's retention window are filtered out:

```python
def enforce_retention(entries: list[KBEntry], user_tier: str) -> list[KBEntry]:
    """Filter entries based on user's subscription tier retention window."""
    retention_days = {
        "free": 30,
        "premium": 90,
        "enterprise": 180,
    }
    cutoff = datetime.now() - timedelta(days=retention_days[user_tier])
    return [e for e in entries if e.collected_at >= cutoff]
```

| Enforcement Point | Behavior |
|-------------------|----------|
| `search_knowledge_base` | Results filtered by querying user's tier retention |
| `export_kb` | Export respects tier retention window |
| `generate_digest` / `generate_report` | Source entries filtered by tier |
| `list_summaries` | Summaries filtered by tier |
| `get_enduser_products` | Product archive filtered by tier |

**Soft-delete interaction:** The existing 30-day soft-delete window (§2.1) applies to all tiers. Retention-by-tier is an additional filter on top of soft-delete. An entry can be soft-deleted (30-day restore window) AND past retention (filtered from queries). These are independent mechanisms.

#### MCP Tools (Spec'd, Not Implemented)

| Tool | Description |
|------|-------------|
| `get_retention_report(domain, period)` | Retention metrics: active users by tier, entries within/outside retention window |
| `get_user_retention(user_id)` | Show user's tier and effective retention window |

**Status:** ✅ Partially implemented (CD-012). Soft-delete, restore, GDPR export, and 30-day auto-cleanup are shipped (`soft_delete_entry`, `restore_entry`, `export_user_data`, `delete_user_data`). Per-tier retention **enforcement** is spec-only — no code enforces tier windows today (kb.py default `ttl_days=90`). The MCP tools above remain spec-only. See CD-012 in `cross-dimensional-catalog.md`.

### 2.6 Unified Notification Framework

> **Cross-ref:** CD-006 (Unified Notification Framework), CD-038 (No Unified Notification Architecture). Config-based alert rules ship in `alerts.py` (YAML persistence, DeliveryChannel dispatch) and lifecycle notifications ship in `notifications.py`, but there is no unified bus. System alerts don't exist. This section specs a unified notification bus.

AutoInfo currently handles notifications ad-hoc: budget alerts in `alerts.py`, delivery notifications in `delivery.py`, system notifications nowhere. The unified framework consolidates all notification types into a single bus with per-user preferences and per-type channel routing.

#### Notification Types

| Type | Source | Examples | Priority |
|------|--------|----------|----------|
| **User lifecycle** | End user state machine | Trial starting, trial ending, subscription activated, payment failed, cancellation confirmed | P0 |
| **System alerts** | Pipeline + infrastructure | Cron failure, disk usage high, LLM key invalid, source health degraded, DB connection lost | P0 |
| **Budget alerts** | Cost governance | Domain cost threshold exceeded, user budget reached, projected overrun | P1 |
| **Collection alerts** | Collection pipeline | Source returned zero items, source rate limited, collection completed, dedup ratio high | P1 |
| **Quality alerts** | Quality gates | G0 schema failure rate high, G4 factual consistency below threshold, gate config changed | P2 |

#### Notification Bus Architecture

```python
@dataclass
class Notification:
    id: str                          # "notif_{uuid8}"
    type: str                        # "user_lifecycle" | "system" | "budget" | "collection" | "quality"
    subtype: str                     # e.g., "trial_ending", "cron_failure", "cost_threshold"
    severity: str                    # "info" | "warning" | "critical"
    domain: str | None = None
    user_id: str | None = None       # Target user (None = broadcast to operators)
    title: str
    body: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    dispatched: bool = False
    dispatched_at: datetime | None = None
```

**Bus flow:**

```
Source subsystem ──→ NotificationBus.publish(notification)
                          │
                          ├──→ Store in notification log (append-only)
                          ├──→ Resolve recipient preferences
                          ├──→ Select delivery channel(s) per preference
                          └──→ Dispatch via DeliveryChannel adapters
```

The bus is a single publish point. All subsystems (`alerts.py`, `end_user.py`, `schedule.py`, `quality.py`) publish to the bus instead of dispatching directly. The bus handles routing, preference resolution, and delivery.

#### Per-User Notification Preferences

```python
@dataclass
class NotificationPreferences:
    user_id: str
    # Per-type enable/disable
    enabled_types: list[str] = field(default_factory=lambda: [
        "user_lifecycle", "system", "budget", "collection", "quality"
    ])
    # Per-type channel selection
    channel_routing: dict[str, list[str]] = field(default_factory=lambda: {
        "user_lifecycle": ["email"],
        "system": ["webhook"],
        "budget": ["email", "webhook"],
        "collection": ["webhook"],
        "quality": ["webhook"],
    })
    # Quiet hours (CD-019 spec, not yet implemented)
    quiet_hours: dict | None = None  # {"timezone": "...", "start": "22:00", "end": "08:00"}
    # Minimum severity to dispatch
    min_severity: str = "info"       # "info" | "warning" | "critical"
```

**Channel selection logic:**

1. Check if notification type is in `enabled_types`. If not, drop.
2. Check if notification severity meets `min_severity`. If not, drop.
3. Look up `channel_routing[notification.type]` for target channels.
4. If quiet hours are active and severity is not `critical`, defer until quiet hours end.
5. Dispatch to each channel via the existing `DeliveryChannel` adapter registry.

#### MCP Tools (Spec'd, Not Implemented)

| Tool | Description |
|------|-------------|
| `get_notifications(user_id, type, since, limit)` | Query notification log for user |
| `update_notification_preferences(user_id, preferences)` | Update per-user notification preferences |
| `get_notification_preferences(user_id)` | Retrieve current preferences |
| `publish_notification(type, subtype, severity, title, body, metadata)` | Internal: publish to bus (agent-callable for custom alerts) |

**Status:** ✅ Partially implemented (CD-006). Config-based alert rules shipped in `alerts.py` with YAML persistence and DeliveryChannel dispatch (`add_alert_rule` / `get_alert_rules` / `remove_alert_rule`), plus automated lifecycle notifications in `notifications.py`. The unified notification bus and per-user preferences remain spec-only. See CD-006 and CD-038 in `cross-dimensional-catalog.md`.

---

## 3. Knowledge Lifecycle (§12.18)

### 3.1 Per-Domain TTL

Each domain has a configurable TTL (time-to-live) for its entries:

```yaml
# domain config
lifecycle:
  default_ttl_days: 90              # Entries older than 90 days are "stale"
  stale_action: demote              # "demote" | "exclude" | "flag"
  auto_refresh: false               # If true, auto-re-collect stale topics
```

**Stale marking**: An entry is marked `stale: true` in frontmatter when its `collected_at` exceeds TTL. This is a flag, not a deletion — stale entries remain searchable but are:

- **Demoted** in search results (lower ranking)
- **Excluded** from digest generation (unless explicitly requested)
- **Never automatically deleted**

### 3.2 Domain Decay Metrics

```python
@dataclass
class DecayMetrics:
    domain: str
    staleness_ratio: float           # stale_entries / total_entries (0-1)
    avg_ttl_remaining_days: float    # Average days until entries go stale
    decay_grade: str                 # "Green" (< 0.2), "Yellow" (0.2-0.5), "Red" (> 0.5)
```

Calculated periodically (or on-demand via MCP tool). Used to suggest source additions or collection schedule changes.

### 3.3 Versioned Re-Collection

When re-collecting a source that was previously collected:

1. New collection creates a new set of Items (new `collected_at`, new `content_hash`)
2. Each KB entry has a `version` field in frontmatter (integer, starts at 1)
3. If content changed (different `content_sha`), a new version is created alongside the old (old preserved in git)
4. `get_entry_history(entry_id)` returns all versions
5. `compare_versions(entry_id, v1, v2)` returns structured diff (added/removed/modified sections)

### 3.4 Cross-Collection Dedup & Merge

| Level | Method | Scope | Cost |
|-------|--------|-------|------|
| 1 | URL exact match | All items in collection cache | O(1) |
| 2 | PMID/DOI/arXiv ID match | All KB tiers + cache | O(1) |
| 3 | Fuzzy title similarity (Levenshtein, threshold 0.85) | Items within configurable window | O(n) |
| 4 | Cross-source semantic similarity (LLM) | Level 3 flagged candidates | 1 LLM call per pair |

**Merge rule**: Level 4 LLM decides whether to merge (combine source URLs + metadata) or keep separate.

### 3.5 MCP Lifecycle Tools

| Tool | Description |
|------|-------------|
| `set_ttl(domain, ttl_days)` | Configure per-domain entry TTL |
| `compare_versions(entry_id, v1, v2)` | Structured diff between versions |
| `find_similar_items(entry_id, threshold)` | Semantic similarity search across KB |
| `merge_items(target_id, source_ids)` | LLM-assisted merge of duplicate entries |
| `refresh_staleness(domain)` | Re-scan and update stale flags for domain |
| `get_domain_decay(domain)` | Return decay metrics object |

### 3.6 Cron Reliability

> **Cross-ref:** CD-004 (Cron Reliability & Backup). Cron scheduling exists (`add_schedule`, `run_schedules`) and `autoinfo cron health` ships with heartbeat tracking and missed-schedule detection, but there is no execution history, no failure alerts, no backfill mechanism. This section specs reliability guarantees.

Cron-driven collection is the backbone of scheduled knowledge base updates. When cron misses a beat, the knowledge base goes stale silently. This section specs three reliability mechanisms: missed-schedule detection, failure alerts, and backfill.

#### Missed-Schedule Detection

Each schedule records its expected and actual run times. A schedule is "missed" if the expected run time passes without a corresponding execution record.

```python
@dataclass
class ScheduleExecution:
    schedule_id: str
    expected_at: datetime            # When the cron should have fired
    actual_at: datetime | None       # When it actually fired (None = missed)
    status: str                      # "completed" | "failed" | "missed" | "running"
    items_collected: int = 0
    error: str | None = None
    duration_ms: int = 0
```

**Detection loop** (runs every 5 minutes via a watchdog cron job):

1. List all active schedules
2. For each schedule, compute next expected run time from `cron` expression
3. If expected run time has passed and no `ScheduleExecution` record exists for it, mark as `missed`
4. If a `ScheduleExecution` exists with `status="running"` for more than 2x the schedule's average duration, mark as `stalled`
5. Publish a `system` notification (§2.6) for any missed or stalled schedule

#### Cron Failure Alerts

When a schedule execution fails (collection error, LLM error, timeout), the failure is published to the notification bus:

| Failure Type | Severity | Notification Channel |
|---------------|----------|---------------------|
| Schedule missed (no execution) | `critical` | Webhook + email |
| Schedule stalled (running too long) | `warning` | Webhook |
| Collection error (source returned error) | `warning` | Webhook |
| Collection zero items (source healthy but empty) | `info` | Webhook (optional) |
| LLM processing failure | `critical` | Webhook + email |
| Cron daemon not running | `critical` | Webhook + email |

**Cron daemon health check:** The watchdog job verifies `crond` (or equivalent) is running. If not, publishes a `critical` system notification.

#### Backfill Mechanism

When a missed schedule is detected, AutoInfo can backfill the missed collection:

```python
def backfill_missed_schedules(domain: str, since: datetime) -> BackfillReport:
    """Re-run collections missed since the given timestamp."""
    missed = get_missed_schedules(domain, since)
    for schedule in missed:
        # Run collection with the schedule's original parameters
        result = collect_sources(
            domain=domain,
            topic=schedule.topic,
            since=missed.expected_at,  # Collect items published since the missed run
        )
        # Process the backfilled collection
        process_collection(domain=domain)
    return BackfillReport(
        schedules_backfilled=len(missed),
        items_collected=sum(r.items_count for r in results),
        items_processed=...,
    )
```

**Backfill rules:**

- Backfill collects items published since the missed `expected_at`, not since "now"
- Multiple missed runs for the same schedule collapse into a single backfill covering the full gap
- Backfill respects dedup (§3.4) so already-collected items are skipped
- Backfill is manual by default (agent or director triggers it). Auto-backfill is a per-schedule config option:

```yaml
# schedule config
lifecycle:
  auto_backfill: false              # If true, watchdog auto-triggers backfill on miss
  max_backfill_gap_hours: 48        # Don't backfill gaps larger than 48 hours
```

#### MCP Tools (Spec'd, Not Implemented)

| Tool | Description |
|------|-------------|
| `get_schedule_executions(schedule_id, since, limit)` | Query execution history for a schedule |
| `get_missed_schedules(domain, since)` | List schedules that missed their expected run |
| `backfill_missed_schedules(domain, since)` | Re-run missed collections |
| `get_cron_health()` | Cron daemon status, last watchdog check, missed schedule count |

**Status:** ✅ Partially implemented (CD-004). `autoinfo cron health` CLI shipped with heartbeat tracking and missed-schedule detection (`get_schedule_status` MCP tool). Execution-history tracking, watchdog, and backfill mechanisms remain spec-only. See CD-004 in `cross-dimensional-catalog.md`.

---

## 4. Observability (§12.19) (supports B2.5 Monitor and B3.2 Monitor)

### 4.1 Structured Pipeline Logging

Every pipeline event (collection, processing, delivery, gate failure) logs a structured JSON line:

```json
{
  "timestamp": "2026-07-26T10:00:00.000Z",
  "level": "INFO",
  "event": "collection.completed",
  "trace_id": "trc_abc123",
  "domain": "medical-research",
  "source": "pubmed",
  "items_count": 15,
  "duration_ms": 3200
}
```

Logging destinations: stdout (default), file, or external log aggregator (configurable).

> **Known gap (CD-030):** Not all pipeline stages emit structured JSON logs. Some modules use `print()` or `logging.info()` with unstructured format. Log level configuration is inconsistent across modules. Full structured logging coverage is a work in progress. See CD-030 in `cross-dimensional-catalog.md`.

### 4.2 Traceability

Every item has a `trace_id` set at Item construction (line 1 of the pipeline). This UUID follows the item through:

```
Collection → Processing (KB write) → Product generation → Delivery (DeliveryLog)
     ↑           ↑                      ↑                     ↑
trace_id    trace_id in KB          trace_id in          trace_id in
assigned    entry frontmatter       product metadata     delivery log
```

MCP tool: `trace_item(trace_id)` returns full pipeline timeline for an item.

### 4.3 Prometheus Metrics

Available at `http://localhost:8741/metrics` (configurable port):

| Metric | Type | Description |
|--------|------|-------------|
| `items_collected_total` | Counter | Total items collected across all domains |
| `items_processed_total` | Counter | Total items successfully processed (LLM extraction) |
| `extraction_tokens_total` | Counter | Total LLM tokens consumed during extraction |
| `errors_total` | Counter | Total pipeline errors recorded |
| `active_users` | Gauge | Active (non-cancelled) end-user profiles |
| `storage_bytes` | Gauge | KB storage usage (bytes used by knowledge base Markdown files) |
| `billing_stripe_sync_failures_total` | Counter | stripe_customer_id persistence failures in billing sync |
| `delivery_failures_total` | Counter | Failed deliveries (agent callback outbox failures) |

> **Canonical metrics reference** — `ops-runbook.md` §3.1 points here.

### 4.4 Diagnostics

`diagnose_system()` MCP tool returns comprehensive health data:

```python
@dataclass
class SystemHealth:
    status: str                      # "healthy" | "degraded" | "unhealthy"
    llm_key_configured: bool
    llm_last_call_success: bool | None
    disk_usage_percent: float
    db_connected: bool
    db_size_mb: float
    active_collections: int
    active_cron_jobs: int
    slowest_source: str | None       # Source with highest avg collection time
    error_rate_last_24h: float
    overall_health_score: int        # 0-100
```

### 4.5 MCP Observability Tools

| Tool | Description |
|------|-------------|
| `trace_item(trace_id)` | Full pipeline timeline for a single item |
| `get_prometheus_metrics(metric_name, since)` | Raw Prometheus metrics dump |
| `get_metrics(metric_name, domain, since)` | Query Prometheus metrics |
| `diagnose_system()` | Comprehensive system health check |

### 4.6 Source Health Polling & Proactive Alerting

> Merged from `docs/dev/agent-alerting.md` (archived 2026-08-23). The polling
> pattern below is the *agent-driven* source health loop; config-based alert
> rules (`add_alert_rule` / `get_alert_rules` / `remove_alert_rule` MCP tools)
> remain the preferred mechanism for cost/budget/knowledge-lifecycle alerts
> (§1.4, §2.6). AutoInfo deliberately does **not** push source-health alerts —
> agents poll state on their own schedule: **agent polls, agent decides, agent
> reports**.

**Detection rule**: if `error_count >= 3` (3 consecutive failures, status
`error`), flag to the user with specifics (error count, last error, source
name), then propose investigate (`test_source`) or pause/remove.

**Workflow**:
1. `list_sources(domain)` to enumerate active sources for a domain
2. `get_source_health(source_id)` per source (`domain:name` identifier, e.g.
   `medical-research:pubmed`)
3. Inspect `error_count` and `status` in the response
4. If `error_count >= 3` or `status == "error"` → proactively notify the user
5. User investigates via `test_source` or pauses/removes the failing source

**`get_source_health` status meanings**:

| Status | Condition |
|--------|-----------|
| `healthy` | Last run succeeded, < 3 consecutive failures |
| `degraded` | Last run failed (< 3 consecutively) or slow response |
| `error` | 3+ consecutive failures — needs attention |
| `paused` | `_paused` marker file exists (user-disabled) |
| `unknown` | No runs recorded yet |

**Implementation notes for agents**:
1. Poll before collect — avoids wasting resources on broken sources.
2. Batch polling — `list_sources` once then iterate; no batch health endpoint.
3. Status transitions — a source can return to `healthy` after a successful
   run; re-check each cycle and unpause/announce recovery.
4. Graceful degradation — `degraded` (1-2 failures) may still collect, but
   note the degraded state in reporting.
5. Human notification — alert only on `error` (3+ failures); `degraded` and
   `paused` are informational for periodic status summaries.

---

## 5. Feature Flags

> **Cross-ref:** CD-037 (No Feature Flag System). Zero feature flag infrastructure exists. This section specs a runtime toggle system with gradual rollout and kill switch capability.

AutoInfo has no feature flag system. All features are either compiled in or absent. This section specs a runtime toggle system that allows gradual rollout, per-domain enablement, and emergency kill switches.

### 5.1 Flag Model

```python
@dataclass
class FeatureFlag:
    key: str                         # e.g., "audio_output", "agent_native_json", "multi_tenant"
    description: str
    enabled: bool = False            # Global on/off
    rollout_percent: int = 100       # 0-100, percentage of users/domains where flag is active
    enabled_domains: list[str] | None = None  # If set, only these domains
    disabled_domains: list[str] | None = None # If set, exclude these domains
    kill_switch: bool = False        # If true, force-disable everywhere, overrides all
    created_at: datetime
    updated_at: datetime
    updated_by: str                  # "agent" | "human:{name}"
```

### 5.2 Flag Evaluation

Flag checks happen at runtime. The evaluator resolves a flag for a given context (domain, user_id):

```python
def is_flag_enabled(key: str, domain: str | None = None, user_id: str | None = None) -> bool:
    flag = get_flag(key)
    if flag.kill_switch:
        return False
    if not flag.enabled:
        return False
    if flag.disabled_domains and domain in flag.disabled_domains:
        return False
    if flag.enabled_domains and domain not in flag.enabled_domains:
        return False
    if flag.rollout_percent < 100:
        # Hash user_id or domain to 0-99, check against rollout_percent
        bucket = hash(f"{key}:{user_id or domain}") % 100
        return bucket < flag.rollout_percent
    return True
```

### 5.3 Gradual Rollout

Rollout is controlled by `rollout_percent`. A flag can be enabled for 10% of users, then bumped to 50%, then 100%. The hash-based bucketing ensures stable assignment: the same user always lands in the same bucket.

| Rollout Stage | Percent | Use Case |
|---------------|---------|----------|
| Canary | 5% | Test on internal domains first |
| Early | 25% | Test on a quarter of users |
| Half | 50% | Test on half the user base |
| Full | 100% | General availability |

### 5.4 Kill Switch

The `kill_switch` field is a hard override. When set to `true`, the flag evaluates to `false` for all contexts regardless of `enabled`, `rollout_percent`, or domain lists. This is the emergency off switch for a problematic feature.

Kill switch activation:

1. Set `kill_switch = true` via MCP tool or config
2. All flag checks for that key immediately return `false`
3. A `system` notification (§2.6) is published: "Feature flag {key} kill switch activated"
4. Kill switch can only be cleared by explicit human action (not agent)

### 5.5 Flag Storage

Flags are stored in `.autoinfo/feature_flags.yaml`:

```yaml
feature_flags:
  audio_output:
    description: "TTS-rendered digest/report as MP3"
    enabled: true
    rollout_percent: 100
    kill_switch: false
  agent_native_json:
    description: "JSON-LD output format for agent re-consumption"
    enabled: true
    rollout_percent: 100
    kill_switch: false
  multi_tenant:
    description: "Multi-tenant KB isolation"
    enabled: false
    rollout_percent: 0
    kill_switch: false
```

### 5.6 MCP Tools (Spec'd, Not Implemented)

| Tool | Description |
|------|-------------|
| `list_feature_flags()` | List all flags and their current state |
| `get_feature_flag(key)` | Get a single flag's configuration |
| `set_feature_flag(key, enabled, rollout_percent, kill_switch)` | Update flag configuration |
| `check_feature_flag(key, domain, user_id)` | Evaluate a flag for a given context |

**Status:** 🟡 Spec'd, not implemented. Zero feature flag infrastructure in the codebase. See CD-037 in `cross-dimensional-catalog.md`.

---

## 6. Business Metrics

> **Cross-ref:** CD-041 (No Data-Driven Business Metrics). Cost metrics exist (LLM tokens, storage, API calls) but no business metrics: MRR, churn, LTV, CAC. This section specs business performance tracking.

AutoInfo tracks operational cost metrics but not business performance metrics. The director has no visibility into revenue, churn, or customer lifetime value. This section specs the business metrics layer that sits on top of the existing cost and user lifecycle data.

### 6.1 Metric Definitions

| Metric | Definition | Calculation | Data Source |
|--------|------------|-------------|-------------|
| **MRR** | Monthly Recurring Revenue | Sum of active subscription `price_monthly` values | `Subscription` where `status="active"` |
| **ARR** | Annual Recurring Revenue | MRR × 12 | Derived from MRR |
| **Churn rate** | Percentage of users who cancelled in period | `cancelled_this_period / active_at_period_start` | `Subscription` state transitions |
| **LTV** | Lifetime Value | `avg_monthly_revenue × avg_customer_lifetime_months` | `Subscription` + `CostLog` (net) |
| **CAC** | Customer Acquisition Cost | `total_acquisition_spend / new_customers_in_period` | `CostLog` (marketing-attributed) + `Subscription` |
| **ARPU** | Average Revenue Per User | `MRR / active_user_count` | Derived from MRR + user count |
| **Net revenue** | Revenue minus cost-to-serve | `total_revenue - total_cost` | `Subscription` + `CostLog` |

### 6.2 Revenue per Delivery Channel

Each delivery channel contributes to revenue differently. Tracking revenue by channel shows which channels drive retention and which are cost centers.

```python
@dataclass
class ChannelRevenue:
    channel: str                     # "email" | "telegram" | "wechat_oa" | "discord" | ...
    period: str                      # "2026-07" (month)
    active_subscriptions: int        # Subscriptions using this channel
    revenue: float                   # Sum of subscription revenue attributed to this channel
    delivery_cost: float            # Cost of deliveries via this channel
    net_revenue: float               # revenue - delivery_cost
    delivery_count: int              # Total deliveries sent
    cost_per_delivery: float         # delivery_cost / delivery_count
```

**Attribution rule:** A subscription's revenue is attributed to its primary delivery channel. If a subscription has multiple channels, revenue is split evenly across active channels.

### 6.3 Cost-to-Serve per User

Cost-to-serve is the total operational cost attributed to a single user. It combines LLM cost, storage cost, API cost, and delivery cost.

```python
@dataclass
class UserCostToServe:
    user_id: str
    period: str                      # "2026-07"
    llm_cost: float                  # LLM tokens attributed to this user
    storage_cost: float              # Storage bytes attributed to this user
    api_cost: float                  # API calls attributed to this user
    delivery_cost: float             # Delivery channel usage cost
    total_cost: float                # Sum of above
    revenue: float                   # Subscription revenue from this user
    margin: float                    # revenue - total_cost
    margin_percent: float            # margin / revenue * 100
```

**Cost allocation:** Uses the existing allocation strategies (§1.3). Usage-based allocation for per-user attribution. Direct allocation for shared costs that can't be attributed to a single user.

### 6.4 Business Dashboard

| MCP Tool | Description |
|-----------|-------------|
| `get_business_metrics(period)` | MRR, ARR, churn rate, ARPU, net revenue for period |
| `get_channel_revenue(period)` | Revenue and cost per delivery channel |
| `get_user_cost_to_serve(user_id, period)` | Cost-to-serve breakdown for a single user |
| `get_cohort_retention(period_start, period_end)` | Cohort retention table (users grouped by signup month) |
| `get_ltv_cac(period)` | LTV and CAC for period |
| `get_churn_report(period)` | Churned users, churn reasons, churn rate trend |

**Status:** 🟡 Spec'd, not implemented. Cost dashboard exists (`get_billing_summary`, `cost_dashboard`). No revenue, MRR, churn, or LTV tracking. See CD-041 in `cross-dimensional-catalog.md`.

---

## 7. B3 Lifecycle Integration

> **Root spec:** `docs/dev/specs/user-lifecycle-definition.md` §4 (B3 Director User Lifecycle)
> **F-expectations:** F70 (B3.1 Unified Director Configuration), F71 (B3.2 Director Monitoring & Dashboard), F72 (B3.3 Incident Intervention Workflow)
> **Pipeline spec:** `docs/dev/specs/pipeline.md` §9 (B2 Lifecycle) — B2 execution is what B3 monitors

This section maps each B3 lifecycle stage to operations functions. B3 is the human director — configures at deploy time, monitors passively, intervenes only on critical error.

### 7.1 B3.1 Unified Director Configuration

B3 configuration is currently scattered across multiple files and config points. This section defines the **unified B3 config scope** that bundles pricing, quality, SLA, and retention into a coherent specification.

| Config Domain | Current Location | Parameters | Implementation Status |
|---------------|-----------------|------------|----------------------|
| **Pricing tiers** | `docs/dev/specs/market-positioning.md` | Tier names (free/premium/enterprise), placeholder prices, feature-to-tier mapping | 🟡 Code-level PricingTier enum. Feature-to-tier mapping not enforced in MCP layer. |
| **Domain quotas** | Code constants | Max domains per tier, max sources per domain | 🟡 Code constants exist. Not configurable by B3 at runtime. |
| **Quality thresholds** | `docs/dev/specs/quality-gates.md` | Min source tier per domain, min relevance score, G0-G5 gate mode (hard vs soft) | ✅ Gate config system exists with per-domain configuration. |
| **Delivery SLA** | `docs/dev/specs/delivery.md` §4 | Max delivery latency per priority (P0 ≤5min, P1 ≤30min, P2 ≤2hr) | ✅ SLA constants exist in delivery system. Not configurable by B3. |
| **Data retention** | `operations.md` §2.5 | Soft-delete window per tier, auto-cleanup period | ✅ Existing retention constants. |
| **Source ToS compliance** | `docs/dev/specs/expectations.md` §F46 (source classification; enforced by `docs/dev/specs/quality-gates.md` §G1) | Source access tier classification, per-tier output controls | ✅ G1 gate enforces source tiers. |
| **Budget thresholds** | `operations.md` §1.4 | Absolute cost thresholds, rate-based thresholds, projected overrun | ✅ Budget alert system exists. |

**Unified config format** (target — not implemented):

```yaml
# B3 unified configuration (demo phase: config file; production: admin UI)
b3_config:
  version: 1
  pricing:
    tiers:
      free:
        domains_max: 1
        features: ["raw_only"]
        placeholder_price: 0
      premium:
        domains_max: 5
        features: ["raw", "processed", "multi_channel"]
        placeholder_price: 29
      enterprise:
        domains_max: 10
        features: ["raw", "processed", "multi_channel", "custom"]
        placeholder_price: 199
  quality:
    min_source_tier: "open"        # Per-domain override possible
    min_relevance_score: 60
    gate_g0: "hard"                # Hard = retry 3x → block
    gate_g4: "hard"
    gate_g1: "soft"                # Soft = archive/flag/pass
    gate_g2: "soft"
    gate_g3: "soft"
    gate_g5: "soft"
  sla:
    p0_max_minutes: 5
    p1_max_minutes: 30
    p2_max_minutes: 120
  retention:
    free_days: 30
    premium_days: 90
    enterprise_days: 180
    auto_cleanup_days: 30
```

> **F70 status**: 🟡 Partially implemented. All individual config points exist; no unified config file or admin UI. The unified config format above is a specification target.

### 7.2 B3.2 Director Monitoring & Dashboard

B3 monitors B2 via dashboard and periodic reports. B3 does NOT proactively intervene unless alerted.

**Dashboard views** (target — not implemented):

| Dashboard View | Data Source | Current Alternative |
|---------------|-------------|-------------------|
| **System Health** | `diagnose_system()` + Prometheus metrics | `autoinfo doctor --verbose` (CLI) |
| **Collection Status** | `get_collection_stats()`, `get_collection_progress()` | `autoinfo status` (CLI) |
| **Source Health** | `get_source_health()` per domain | `autoinfo sources list --health` (CLI) |
| **Delivery Metrics** | `query_delivery_log()`, SLA compliance | None (MCP tools only) |
| **Cost Trends** | `cost_dashboard()` + budget alerts | `autoinfo cost dashboard` (CLI) |
| **Active Users** | UserProfile + Subscription status | `autoinfo enduser list` (CLI) |
| **Anomaly Feed** | Alert rules + budget alerts + cron health | None |

**Monitoring principles** (from lifecycle-definition §4.2):
1. **Passive by default** — B3 reviews dashboards and reports; alerts are for exceptions, not routine updates
2. **Exception-driven intervention** — B3 only acts when alert fires (critical error, budget breach, cron failure)
3. **B2-generated reports** — B2 summarizes execution status periodically (see F69)
4. **No live log watching** — B3 does not tail logs or watch pipeline execution in real-time

**Alert routing**:

| Alert Type | Severity | Channel to B3 | B3 Action |
|-----------|----------|---------------|-----------|
| Cron failure (missed schedule) | 🔴 Critical | Dashboard alert + notification | Investigate, restart cron, backfill |
| Source unreachable (all retries exhausted) | 🟡 Warning | Dashboard alert | Review source config, switch source |
| Budget threshold breached | 🟡 Warning | Notification | Review cost allocation, adjust budget |
| KB integrity violation | 🔴 Critical | Immediate notification | Repair KB, restore from backup |
| Delivery SLA miss (repeated) | 🟡 Warning | Dashboard | Review delivery channel health |
| Disk usage >90% | 🔴 Critical | Immediate notification | Free space, investigate growth |
| LLM key expired | 🔴 Critical | Immediate notification | Update key, restart services |

> **F71 status**: 🟡 Partially implemented. All monitoring data exists via CLI and MCP tools. No unified web dashboard. The Web UI Dashboard (Bootstrap 5, `/dashboard`) shows collection stats and KB search but no admin/monitoring views.

### 7.3 B3.3 Incident Intervention Workflow

When B2 encounters a critical error it cannot self-heal, B3 intervenes. This section defines the incident response structure.

**Error escalation** (from lifecycle-definition §5.3):

```
B2 encounters error
  ├── Recoverable → B2 retries (3x with backoff) → succeeds → continue
  ├── Degraded → B2 continues with degraded state, logs anomaly
  │              B3 sees anomaly in next report → may investigate
  └── Critical → B2 halts affected pipeline, alerts B3 immediately
                  B3 intervenes manually → repair, rollback, config fix
```

**Incident severity classification**:

| Severity | Label | Response Time | Examples | B3 Action |
|----------|-------|--------------|----------|-----------|
| **S1 — Critical** | 🔴 | Immediate (<15min) | KB integrity violation, disk full, config corruption, LLM key expired | Investigate immediately. Repair or rollback. Post-mortem required. |
| **S2 — Degraded** | 🟡 | Next business day | Source unreachable (after retries), partial delivery failure, budget threshold warning | Review at next opportunity. Adjust config if needed. |
| **S3 — Informational** | 🔵 | Next report cycle | Source timeout (temporary), single B1 delivery failure, minor anomaly | Review in next B2 periodic report. No dedicated action required. |

**Intervention actions** (with B3 tools):

| Intervention | B3 MCP/CLI Capability | Status |
|-------------|----------------------|--------|
| **Promote Draft→Wiki** | `create_kb_draft()` → agent promotes via MCP `promote_kb_draft` (KB-tier guard; no human gate — KB is a database for raw/processed production, director decision 2026-08-08) | ✅ Implemented (agent operation) |
| **Restore deleted entry** | `restore_entry(entry_id)` | ✅ Implemented |
| **Soft-delete entry** | `soft_delete_entry(entry_id)` | ✅ Implemented |
| **Repair source config** | `remove_source()` + `add_source()` | ✅ Implemented |
| **Restart services** | System-level (not in MCP) | 🟡 Requires SSH or systemd |
| **Rollback KB version** | `restore_entry_version(entry_id, version)` | ✅ Implemented |
| **Config recovery** | Not yet spec'd — depends on F70 unified config | ❌ Not implemented |
| **Incident record** | Not yet spec'd — depends on F72 | ❌ Not implemented |

**Incident record format** (target):

```json
{
  "incident_id": "inc_{uuid8}",
  "severity": "S1",
  "trigger": "B2 alert: KB integrity violation (entry raw_abc123 has corrupt frontmatter)",
  "detected_at": "2026-07-27T14:30:00Z",
  "acknowledged_at": "2026-07-27T14:32:00Z",
  "intervention_steps": [
    {"step": 1, "action": "restore_entry_version(raw_abc123, version=3)", "result": "success"},
    {"step": 2, "action": "reindex_kb(domain=medical-research)", "result": "success"}
  ],
  "resolved_at": "2026-07-27T14:35:00Z",
  "root_cause": "Concurrent write: two B2 pipeline instances wrote to same entry",
  "action_items": ["Add write lock to KB pipeline", "Make B2 pipeline single-instance"],
  "post_mortem": "link_to_post_mortem_doc"
}
```

> **F72 status**: 🟡 Partially implemented. Individual intervention CLIs exist (restore, promote, etc.). No structured incident workflow, no severity classification, no incident records, no post-mortem tracking.
