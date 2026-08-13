<!-- agent: data-models-reference -->
<!-- owner: docs/dev/specs -->
<!-- source-truth: src/autoinfo/ -->
<!-- schema-count: 35+ -->
<!-- mcp-mapping: see Agent Quick Reference below -->
<!-- keystone: docs/dev/cross-dimensional-catalog.md -->

# Data Models Reference

> Consolidated data model schemas referenced across all spec files. Source truth for these schemas lives in `src/autoinfo/`.
> **Keystone matrix:** [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) — the CD catalog defines what each pipeline stage (A1-A7) needs to produce for each user type (B1/B2/B3). This spec provides the data model definitions that implement those needs.
>
> **Canonical home for data-model schemas.** This file is the single source of truth for schema definitions. `delivery.md`, `pipeline.md`, and `operations.md` reference schemas defined here rather than re-declaring them. When adding or modifying a shared data model, update this file first, then cross-reference from other specs.

---

## Agent Quick Reference

Entity-to-MCP-tool mapping. Use this table to find which tool produces or
consumes each entity. "spec only" marks models not yet implemented in code.

| Entity | MCP Tool | Key Fields |
|--------|----------|------------|
| `Item` | `collect_sources`, `process_collection`, `get_collection_status` | `source_url`, `source_type`, `topic_tags`, `raw_data`, `trace_id` |
| `ExtractionResult` | `extract_fields`, `get_extraction`, `process_collection` | `tl_dr`, `key_points`, `entities` (list[dict]), `custom_fields`, `relevance_score` |
| KB Entry (YAML frontmatter) | `search_knowledge_base`, `get_kb_entry`, `create_kb_draft`, `flag_for_knowledge_base`, `list_kb_tier` | `entry_id`, `source_url`, `tier`, `status`, `tags`, `trace_id`, `version` |
| `DeliveryResult` | `send_to_enduser`, `send_email_digest` | `product_id`, `channel`, `status`, `timestamp`, `recipient_count`, `error` |
| `DeliveryLog` | `query_delivery_log`, `get_delivery_log`, `get_enduser_history` | `log_id`, `subscription_id`, `channel`, `message_type`, `status`, `sla_tier` |
| Delivery retry policy | `send_to_enduser`, `deliver_with_retry` | SLA-tier retries (`_SLA_RETRIES`: critical=5, standard=3, bulk=1); backoff `_RETRY_BACKOFF` = `[1.0, 5.0, 30.0]` (last value repeats) |
| `UserProfile` | `send_to_enduser`, `get_enduser_history`, `update_preferences`, `get_preferences` | `user_id`, `name`, `email`, `status`, `tier`, `preferences` |
| `DeliveryPreferences` | `update_preferences`, `get_preferences` | `channels`, `quiet_hours`, `max_daily_digests`, `preferred_format` |
| `Subscription` | `get_subscription_status`, `activate_trial`, `check_trial_expiry` | `subscription_id`, `user_id`, `plan`, `tier`, `channels`, `domains`, `products` |
| `ProductState` / `ProductInstance` | `list_products`, `get_product` | `id`, `template_id`, `state`, `version` |
| `ConsumptionEvent` | `get_enduser_usage` | `id`, `product_id`, `event_type`, `channel` |
| `EngagementMetrics` | `get_enduser_usage` (spec only) | `product_id`, `open_count`, `read_count`, `completion_rate` |
| `ReadReceipt` | `query_delivery_log` (spec only) | `id`, `product_id`, `channel`, `delivered_at`, `opened_at` |
| `NotificationTemplate` | (notification framework, spec only) | `id`, `type`, `channel`, `locale` |
| `UserNotification` | (notification framework, spec only) | `id`, `user_id`, `type`, `status` |
| `NotificationPreferences` | `update_preferences` (spec only) | `per_type_channel_preference`, `digest_frequency` |
| `CostLog` | `get_billing_summary`, `get_enduser_invoice`, `get_budget_thresholds` | `id`, `category`, `domain`, `amount`, `trace_id` |
| `AuditLog` | `audit query` (CLI + MCP) | `id`, `action`, `entity_type`, `operator`, `timestamp` |
| `SysConfig` | `get_config`, `get_gate_config`, `set_gate_config` | `llm`, `storage`, `logging`, `metrics` |
| `DecayMetrics` | `get_domain_decay`, `calculate_freshness_score`, `mark_stale` | `domain`, `staleness_ratio`, `decay_grade` |
| `SystemHealth` | `diagnose_system`, `health_check`, `get_metrics` | `status`, `llm_key_configured`, `overall_health_score` |
| `Tenant` | (multi-tenancy, spec only) | `id`, `name`, `slug`, `settings` |
| `ApiKey` | (auth, spec only) | `id`, `tenant_id`, `key_hash`, `permissions` |
| `UserSession` | (auth, spec only) | `id`, `user_id`, `tenant_id`, `token_hash` |
| `RateLimit` | (abuse prevention, spec only) | `tenant_id`, `endpoint`, `limit`, `window_seconds` |
| `SubscriptionConfig` | `update_preferences`, `get_preferences` (spec only) | `tier`, `domains`, `channels`, `frequency` |
| `ChannelBinding` | `update_preferences` (spec only) | `channel_type`, `config`, `enabled` |
| `ConfigChange` | (NL→Config pipeline, spec only) | `field`, `old_value`, `new_value`, `change_type` |
| `ReferralRecord` | (B1 referral, spec only) | `id`, `referring_user_id`, `referral_code`, `status` |
| `ProductCatalogEntry` | `list_output_templates` (spec only) | `id`, `name`, `domain`, `product_type`, `cadence` |
| `OnboardingRecord` | (B1.3 onboarding, spec only) | `id`, `subscription_id`, `current_step`, `status` |
| `ConfigSnapshot` | (B1.7 reactivation, spec only) | `id`, `subscription_id`, `config`, `captured_at` |
| `ReactivationRecord` | (B1.7 reactivation, spec only) | `id`, `original_subscription_id`, `data_restored` |
| `NLConfigAuditEntry` | (NL→Config audit, spec only) | `id`, `nl_intent`, `parsed_config`, `confidence_score` |

> Schema anchors of the form `<!-- schema: EntityName -->` precede each schema
> block below. Use them to jump to a definition or to cross-reference from
> other docs.

---

## 1. Collection & Pipeline Models

<!-- schema: Item -->
```python
@dataclass
class Item:
    """A single collected item from any source."""
    id: str
    source_name: str
    source_type: str                  # one of VALID_SOURCE_TYPES (29 types, single source of truth in src/autoinfo/config.py)
    source_url: str
    title: str
    content: str                      # main body text
    content_type: str = "text"
    source_platform: str = ""         # e.g. "pubmed", "arxiv", "hn"
    collected_at: str = ""            # ISO-8601 timestamp (string, not datetime)
    language: str = ""
    domain: str = ""
    topic_tags: list[str] = field(default_factory=list)   # matched topic names
    quality_tier: int = 1             # 1-4, propagated from source config at collect time (G1 input)
    raw_data: dict[str, Any] = field(default_factory=dict)  # source-specific (DOI, PMID, URL)
    version: int = 1
    previous_version: int = 0
    supersedes: str = ""
    trace_id: str = ""                # UUID assigned at collection, carried through delivery
```

<!-- schema: ExtractionResult -->
```python
@dataclass
class ExtractionResult:
    """Structured extraction output from LLM processing."""
    item_id: str
    title: str = ""
    tl_dr: str = ""                    # One-sentence summary
    key_points: list[str] = field(default_factory=list)  # 3-5 bullet points
    entities: list[dict[str, Any]] = field(default_factory=list)  # Extracted entities — list of dicts (not dict-of-lists)
    relevance_score: float = 0.0       # populated by G3
    custom_fields: dict[str, Any] = field(default_factory=dict)   # Domain-specific fields
    usage: dict[str, Any] = field(default_factory=dict)  # LLM token usage metadata
```

---

## 2. KB Entry Schema

<!-- schema: KBEntry -->
Stored as Markdown with YAML frontmatter:

```yaml
---
entry_id: "raw_abc123"
source_url: "https://..."
source_type: "pubmed"
source_platform: "pubmed"
collected_at: "2026-07-26T10:00:00"
tags: ["IVF breakthroughs"]
trace_id: "trc_abc123"
version: 1
relevance_score: 85
quality_tier: 1          # 1-4, propagated from source config (G1 input)
source_score: 90.0       # 0-100 deterministic credibility score from quality_tier via SOURCE_TIER_SCORE_MAP (E9)
status: "active"       # "active" | "deprecated" | "archived"  ("deleted" is a DB column, not a status; `stale` is set via mark_stale flag)
tier: "01-Raw"         # "01-Raw" | "02-Draft" | "03-Wiki"
custom_fields:        # optional — domain extraction fields plus reserved product analysis key
  key_findings: ["..."]
  product_analysis:   # written during differentiated product generation (premium-briefing / enterprise-briefing / magazine-digest)
    product: "premium-briefing"
    implications: ["so-what per key_findings entry"]   # list[str], index-aligned 1:1 with key_findings
    risks: ["..."]                                     # list[str], index-aligned
    action_required: ["..."]                           # list[str], index-aligned (premium/enterprise)
    key_metrics: [{"metric": "...", "value": "...", "source": "..."}]  # list[dict], enterprise only
---
```

`custom_fields["product_analysis"]` is persisted via `KBStore.update_entry_metadata` at product-generation time (no new store/tool) and is filterable through `search_knowledge_base(filter_custom_fields={...})` — dot-path into `custom_fields`, `""` = presence, non-empty = exact match, path-injection validated (see mcp-tools.md).

---

## 3. Delivery Models

<!-- schema: DeliveryResult -->
<!-- schema: DeliveryLog -->
```python
@dataclass
class DeliveryResult:
    """Result of delivering a product through a specific channel."""
    product_id: str
    channel: str
    status: Literal["success", "failed", "partial"]
    timestamp: str = ""                # ISO-8601 timestamp (string)
    recipient_count: int = 0
    error: str | None = None

@dataclass
class DeliveryLog:
    """A single delivery attempt record (append-only log)."""
    log_id: str                        # "dlog_{uuid8}"
    subscription_id: str               # FK to Subscription
    channel: str
    message_type: str                  # e.g. "digest" | "report" | "alert"
    status: str                        # "success" | "failed" | "retrying" | "pending" ...
    attempt_count: int = 0
    last_attempt: str = ""             # ISO-8601 timestamp (string)
    error_message: str = ""
    sla_tier: str = "standard"         # "critical" | "standard" | "bulk"
```

> **Retry policy**: retries are **SLA-tier-based**, not per-channel — there is no per-channel retry-config dataclass.
> `src/autoinfo/delivery/__init__.py` defines `_SLA_RETRIES = {"critical": 5, "standard": 3, "bulk": 1}`
> (retries beyond the initial attempt) and `_RETRY_BACKOFF = [1.0, 5.0, 30.0]` (seconds between retries;
> the last value repeats for attempts beyond the list). Unknown tiers fall back to `standard`.

---

## 4. End User Models

> **Root spec:** `docs/dev/specs/user-lifecycle-definition.md` §2.3 (B1 Subscription Config Model), §2.4 (Config Change & Billing Interaction)
> The B1 lifecycle data models in §4.9-4.13 supplement the core delivery models above.

<!-- schema: UserStatus -->
<!-- schema: SubscriptionStatus -->
<!-- schema: UserProfile -->
<!-- schema: DeliveryPreferences -->
<!-- schema: ChannelConfig -->
<!-- schema: QuietHours -->
<!-- schema: Subscription -->
```python
class UserStatus(Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
# Note: spec-only enum — models.py stores UserProfile.status as a plain str
# ("trial" | "active" | "suspended" | "cancelled"); no enum exists in code.

class SubscriptionStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
# Note: spec-only enum — models.py stores Subscription.status as a plain str.

@dataclass
class UserProfile:
    """End-user profile with lifecycle status (trial→active→suspended→cancelled)."""
    user_id: str                       # "usr_{uuid8}" — identity is implicit via user_id (no identity_anchor field in code)
    name: str
    email: str = ""
    status: str = "trial"              # "trial" | "active" | "suspended" | "cancelled"
    tier: str = "free"                 # "free" | "premium" | "enterprise"
    delivery_preferences: dict[str, Any] = field(default_factory=dict)  # freeform dict — no typed DeliveryPreferences class
    created_at: str = ""               # ISO-8601 (string)
    updated_at: str = ""
    trial_ends_at: str = ""
    trial_started_at: str = ""
    trial_days: int = 14
    grace_period_days: int = 7
    last_login_at: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Stripe billing fields
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""

# ── Spec-only target models (no dataclass in src/autoinfo/models.py) ──
@dataclass
class DeliveryPreferences:
    channels: dict[str, list[ChannelConfig]]
    quiet_hours: QuietHours | None = None
    max_daily_digests: int = 1
    preferred_format: str = "markdown"

@dataclass
class ChannelConfig:
    channel_type: str
    recipient: str
    enabled: bool = True

@dataclass
class QuietHours:
    start: str                       # "22:00"
    end: str                         # "07:00"
    timezone: str = "UTC"
    only_urgent: bool = False

@dataclass
class Subscription:
    """Subscription tied to a user profile with plan, status, and billing info.
    CD-024 fields: tier, channels, domains, products, platform_limit, domain_limit,
    raw_access, processed_access.
    """
    subscription_id: str             # "sub_{uuid8}"
    user_id: str                     # FK to UserProfile
    plan: str = "free"               # "free" | "premium" | "enterprise"
    status: str = "active"           # "active" | "paused" | "cancelled"
    start_date: str = ""             # ISO-8601 (string)
    end_date: str = ""
    auto_renew: bool = True
    price_monthly: float = 0.0
    currency: str = "USD"
    features: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""             # ISO-8601 (string)
    updated_at: str = ""
    tier: str = "free"               # CD-024: product-gating tier
    channels: list[str] = field(default_factory=list)   # CD-024: 13 canonical channel types
    domains: list[str] = field(default_factory=list)    # CD-024: subscribed domains
    products: list[str] = field(default_factory=list)   # CD-024: subscribed products
    platform_limit: int = 1          # CD-024: max platforms
    domain_limit: int = 1            # CD-024: max domains
    raw_access: bool = False         # CD-024: RAW product access
    processed_access: bool = True    # CD-024: PROCESSED product access
```

---

### 4.6 Product Data Models

> Cross-ref: CD-017 (Product Lifecycle MCP Tools) — spec'd in delivery.md, 0% implemented.
> No `ProductState` enum, no `ProductInstance`, no lifecycle state machine in current code.

<!-- schema: ProductState -->
<!-- schema: ProductInstance -->
<!-- schema: ProductLifecycle -->
```python
class ProductState(Enum):
    """Lifecycle states for a product instance. State machine: 
    draft → pending → active ↔ paused → archived → deprecated."""
    DRAFT = "draft"           # Being configured/edited
    PENDING = "pending"       # Scheduled for generation, awaiting trigger
    ACTIVE = "active"         # Being generated and delivered
    PAUSED = "paused"         # Temporarily suspended (manual or auto)
    ARCHIVED = "archived"     # No longer generated; content retained
    DEPRECATED = "deprecated" # Superseded; scheduled for removal


@dataclass
class ProductInstance:
    """A concrete instance of a product template, tracked through its lifecycle.
    Not to be confused with Product/ProductTemplate (the template definition)."""
    id: str                          # "prod_{uuid8}"
    template_id: str                 # FK to ProductTemplate
    user_id: str                     # FK to UserProfile (owner/subscriber)
    domain: str                      # Domain context
    state: ProductState              # Current lifecycle state
    created_at: datetime
    updated_at: datetime
    generated_at: datetime | None = None  # When product content was rendered
    delivered_at: datetime | None = None  # When product was sent to channels
    metadata: dict = field(default_factory=dict)  # generation params, content hash, etc.
    version: int = 1                 # Incremented on regeneration


class ProductLifecycle:
    """State machine definition for ProductInstance transitions.

    Valid transitions:
      draft     → pending, archived
      pending   → active, archived
      active    → paused, archived
      paused    → active, archived
      archived  → (terminal)

    DEPRECATED is a human-applied label on ARCHIVED instances.
    """

    TRANSITIONS: dict[ProductState, set[ProductState]] = {
        ProductState.DRAFT:       {ProductState.PENDING, ProductState.ARCHIVED},
        ProductState.PENDING:     {ProductState.ACTIVE, ProductState.ARCHIVED},
        ProductState.ACTIVE:      {ProductState.PAUSED, ProductState.ARCHIVED},
        ProductState.PAUSED:      {ProductState.ACTIVE, ProductState.ARCHIVED},
        ProductState.ARCHIVED:    set(),
        ProductState.DEPRECATED:  set(),
    }

    @classmethod
    def can_transition(cls, from_state: ProductState, to_state: ProductState) -> bool:
        return to_state in cls.TRANSITIONS.get(from_state, set())
```

### 4.7 Consumption Models

> Cross-ref: CD-011 (Consumption Tracking), CD-018 (Consumption MCP Tools).
> ✅ **Implemented 2026-08-04**: `ConsumptionEvent` is auto-recorded on digest/report delivery (view/open/click). SQLite-backed store at `src/autoinfo/consumption.py`. The model below is aligned with the implementation. Read receipt infrastructure (per-channel open/read timestamps) is spec-only.

<!-- schema: ConsumptionEvent -->
<!-- schema: EngagementMetrics -->
<!-- schema: ReadReceipt -->
```python
@dataclass
class ConsumptionEvent:
    """A single consumption action by an end user on a delivered product."""
    id: str                          # "cns_{uuid8}"
    product_id: str                  # FK to ProductInstance
    user_id: str                     # FK to UserProfile
    event_type: str                  # "delivered" | "opened" | "clicked" | "purchased" (aligned with src/autoinfo/consumption.py)
    channel: str                     # Channel through which consumed (e.g., "smtp", "telegram") — one of 13 canonical channels
    timestamp: datetime
    metadata: dict = field(default_factory=dict)  # user-agent, IP-geo, referrer, etc.


@dataclass
class EngagementMetrics:
    """Aggregated engagement metrics for a product-user pair."""
    product_id: str                  # FK to ProductInstance
    user_id: str                     # FK to UserProfile
    open_count: int = 0              # Number of times product was opened
    read_count: int = 0              # Number of times product was read (scrolled through)
    click_count: int = 0             # Number of in-content link clicks
    share_count: int = 0             # Number of shares
    time_spent_seconds: float = 0.0  # Estimated reading time
    completion_rate: float = 0.0     # 0.0 - 1.0 estimated content completion
    first_interaction: datetime | None = None
    last_interaction: datetime | None = None


@dataclass  
class ReadReceipt:
    """Per-channel delivery receipt with open/read timestamps."""
    id: str                          # "rcpt_{uuid8}"
    product_id: str                  # FK to ProductInstance
    user_id: str                     # FK to UserProfile
    channel: str                     # Delivery channel (email, telegram, wechat, etc.)
    delivered_at: datetime           # Confirmed delivery timestamp
    opened_at: datetime | None = None  # First open (tracking pixel / API callback)
    read_at: datetime | None = None  # Sufficient scroll/time to count as "read"
    metadata: dict = field(default_factory=dict)  # channel-specific delivery metadata
```

### 4.8 Notification Models

> Cross-ref: CD-006 (Unified Notification Framework), CD-038 (No Unified Notification Architecture).
> Current code has budget alerts (`alerts.py`) and delivery notifications (`delivery.py`)
> as separate subsystems with no shared notification bus, templates, or preferences.
> These models define the target unified architecture.

<!-- schema: NotificationTemplate -->
<!-- schema: UserNotification -->
<!-- schema: NotificationPreferences -->
```python
@dataclass
class NotificationTemplate:
    """A reusable notification template with locale support."""
    id: str                          # "ntpl_{uuid8}"
    type: str                        # "welcome" | "trial_ending" | "digest_ready" | "cancellation" | "system_alert" | "budget_alert"
    subject_template: str            # Jinja2 template for subject line
    body_template: str               # Jinja2 template for body
    channel: str                     # "smtp" | "telegram" | "wechat_oa" | "wechat_work" | "webhook" — one of 13 canonical channels
    locale: str = "en"               # ISO language code
    variables_schema: dict = field(default_factory=dict)  # JSON Schema for template variables


@dataclass
class UserNotification:
    """A rendered notification instance sent to a specific user."""
    id: str                          # "notif_{uuid8}"
    user_id: str                     # FK to UserProfile
    type: str                        # Notification type (matches template type)
    channel: str                     # Delivery channel used
    template_id: str                 # FK to NotificationTemplate
    status: str                      # "pending" | "sent" | "failed" | "read"
    rendered_subject: str = ""       # Rendered subject (filled at send time)
    rendered_body: str = ""          # Rendered body (filled at send time)
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: datetime | None = None
    read_at: datetime | None = None
    error: str | None = None         # Failure reason if status == "failed"


@dataclass
class NotificationPreferences:
    """Per-user notification channel and timing preferences."""
    user_id: str                     # FK to UserProfile
    per_type_channel_preference: dict[str, list[str]] = field(default_factory=dict)
    # Example: {"digest_ready": ["smtp"], "budget_alert": ["telegram", "smtp"]}
    quiet_hours: QuietHours | None = None  # Reuses existing QuietHours model
    digest_frequency: str = "daily"  # "realtime" | "daily" | "weekly" | "never"
    max_notifications_per_day: int = 10


# ── Notification State Machine ──
# pending  → sent  (delivered to channel)
# pending  → failed (channel error)
# sent     → read  (user acknowledged)
# failed   → pending (retry)
```

---

## 5. Operations Models

<!-- schema: CostLog -->
<!-- schema: AuditLog -->
<!-- schema: SysConfig -->
<!-- schema: DecayMetrics -->
<!-- schema: SystemHealth -->
```python
@dataclass
class CostLog:
    id: str                          # "cost_{uuid8}"
    category: str                    # "llm" | "storage" | "api" | "delivery"
    domain: str
    user_id: str | None = None
    trace_id: str = ""
    amount: float
    currency: str = "USD"
    metadata: dict = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=datetime.now)

@dataclass
class AuditLog:
    id: str                          # "audit_{uuid8}"
    action: str                      # "soft_delete" | "restore" | "promote" | "merge"
    entity_type: str                 # "kb_entry" | "user" | "subscription"
    entity_id: str
    operator: str                    # "agent" | "human:{name}"
    details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class SysConfig:
    """Global system configuration (not domain-specific)."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)

@dataclass
class DecayMetrics:
    domain: str
    staleness_ratio: float
    avg_ttl_remaining_days: float
    decay_grade: str                 # "Green" | "Yellow" | "Red"

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
    slowest_source: str | None
    error_rate_last_24h: float
    overall_health_score: int        # 0-100
```

---

## 6. Auth & Multi-Tenancy Models

> Cross-ref: CD-001 (Multi-Tenancy Isolation), CD-002 (End-User Authentication),
> CD-003 (Rate Limiting / Abuse Prevention).
> Entirely spec only — no auth layer, no tenant model, no rate limiting in current code.
> `user_id` fields exist on entries but there is no authentication, session management,
> or tenant isolation anywhere in the system.

<!-- schema: Tenant -->
<!-- schema: ApiKey -->
<!-- schema: UserSession -->
<!-- schema: RateLimit -->
```python
@dataclass
class Tenant:
    """A multi-tenancy context. All data, users, and configurations are scoped
    to a tenant. In single-tenant mode, there is one unnamed default tenant."""
    id: str                          # "tnt_{uuid8}"
    name: str                        # Display name
    slug: str                        # URL-safe unique identifier
    settings: dict = field(default_factory=dict)  # Tenant-wide config overrides
    created_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True


@dataclass
class ApiKey:
    """API key for programmatic access (MCP/CLI agents, webhook senders)."""
    id: str                          # "apk_{uuid8}"
    tenant_id: str                   # FK to Tenant
    name: str = ""                   # Human-readable label (e.g., "Production CLI")
    key_hash: str                    # SHA256 hash of the actual key (key never stored)
    prefix: str = ""                 # First 8 chars for display/identification
    permissions: list[str] = field(default_factory=list)
    # Example: ["kb:read", "kb:write", "collection:run", "delivery:send"]
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_revoked: bool = False


@dataclass
class UserSession:
    """Authenticated user session. Created on login, invalidated on logout/expiry."""
    id: str                          # "sess_{uuid8}"
    user_id: str                     # FK to UserProfile
    tenant_id: str                   # FK to Tenant (session is tenant-scoped)
    token_hash: str                  # SHA256 hash of the session token
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime
    ip_address: str = ""
    user_agent: str = ""
    is_active: bool = True


@dataclass
class RateLimit:
    """Per-tenant, per-endpoint rate limit tracking.
    Uses a sliding-window counter pattern."""
    tenant_id: str                   # FK to Tenant (or "*" for global)
    endpoint: str                    # e.g., "mcp:collect_sources", "api:/v1/search"
    limit: int                       # Max requests in the window
    window_seconds: int              # Window size in seconds
    current_count: int = 0           # Requests in current window
    window_start: datetime | None = None
    blocked_until: datetime | None = None  # If limit exceeded, cooldown expiry


# ── Auth Architecture Notes ──
# 
# 1. Session tokens: JWT or opaque token stored as HTTP-only cookie / Bearer header.
#    Sessions are tenant-scoped — a user must select or be assigned a tenant.
#
# 2. API keys: Generated via MCP/CLI, transmitted as `Authorization: Bearer <key>`
#    or `X-API-Key: <key>`. Hashed with SHA256 before storage; raw key shown once.
#
# 3. Rate limiting: Per-tenant, per-endpoint sliding window. On exceed:
#    - 429 response with Retry-After header
#    - Cooldown = window_seconds before re-enabling
#    - Configurable per tenant via Tenant.settings
#
# 4. Tenant isolation: All queries include `WHERE tenant_id = ?` or are scoped
#    to the tenant's database partition. In single-tenant SQLite mode, tenant
#    isolation is at the application layer (query filtering).
#
# 5. Future considerations:
#    - OAuth 2.0 / OIDC integration (Google, GitHub, enterprise SSO)
#    - RBAC with predefined roles (admin, editor, viewer, enduser)
#    - Per-tenant DB partitioning (separate SQLite files or PostgreSQL schemas)
```

---

### 4.9 B1 Subscription Config Model

> **Root spec:** `docs/dev/specs/user-lifecycle-definition.md` §2.3 (Subscription Config Model)
>
> This is the structured config that results from the NL→Config pipeline (B1 NL → Agent + LLM → structured config).
> The config is stored as part of the Subscription record and drives pipeline execution.

<!-- schema: SubscriptionConfig -->
<!-- schema: ChannelBinding -->
<!-- schema: ConfigChange -->
```python
@dataclass
class SubscriptionConfig:
    """Structured subscription configuration — the output of the NL→Config pipeline.

    Created at B1.2 Subscribe (via NL→Config pipeline) and modified at B1.5 Modify Config.
    Drives pipeline execution: what domains to collect, how often, where to deliver.
    """
    tier: str                          # "free" | "premium" | "enterprise" — pricing tier
    domains: list[str]                 # Domain names to track (e.g., ["medical-research", "tech-ai"])
    content_preference: str            # "raw_only" | "processed_only" | "both"
    channels: list[ChannelBinding]     # Delivery channels with per-channel config
    frequency: str                     # Cron expression or preset: "realtime" | "daily" | "weekly" | "monthly"
    active: bool = True                # If False, pipeline runs but no products delivered (pause)
    max_items_per_delivery: int = 10   # Max items per product delivery
    language: str = "zh"               # Preferred content language

@dataclass
class ChannelBinding:
    channel_type: str                  # "smtp" | "telegram" | "wechat_oa" | "wechat_work" | "dingtalk" | "feishu" | "discord" | "webhook" | "rest_api" | "file_export" | "rss" | "social_publish" | "push" — 13 canonical channels
    config: dict                       # Channel-specific config (e.g., {"chat_id": "..."} for Telegram)
    enabled: bool = True

@dataclass
class ConfigChange:
    """Records a single config change (from NL→Config pipeline or direct edit)."""
    field: str                         # Which field changed
    old_value: Any                     # Previous value
    new_value: Any                     # New value
    change_type: str                   # "non-billing" | "billing_affecting"
    change_source: str                 # "nl_config_pipeline" | "direct_edit" | "admin_override"
    applied_at: datetime
    effective_immediately: bool
```

### 4.10 Discovery & Referral Models

<!-- schema: ReferralRecord -->
<!-- schema: ProductCatalogEntry -->
```python
@dataclass
class ReferralRecord:
    """Tracks a B1-to-B1 referral. Created when referred B1 subscribes."""
    id: str                            # "ref_{uuid8}"
    referring_user_id: str             # B1 who shared the referral link
    referred_user_id: str             # B1 who subscribed via the referral link
    referral_code: str                 # Unique code embedded in the referral link
    status: str                        # "pending" | "rewarded" | "expired"
    reward_type: str | None           # e.g., "free_month", "discount_50"
    reward_status: str | None          # "granted" | "pending" | "failed"
    created_at: datetime
    reward_granted_at: datetime | None = None

@dataclass
class ProductCatalogEntry:
    """A product listing in the catalog/storefront (F64)."""
    id: str                            # "pce_{uuid8}"
    name: str                          # Product display name
    description: str                   # Short description for listing
    domain: str                        # Associated domain
    product_type: str                  # "digest" | "report" | "tutorial" | "presentation"
    output_format: list[str]           # Available formats (["markdown", "html", "json"])
    cadence: str                       # "realtime" | "daily" | "weekly" | "monthly" | "on_demand"
    pricing_tiers: list[str]           # Tiers this product is available on
    sample_output: str | None         # Path or URL to sample output
    subscribe_action: str              # MCP tool call to execute on subscribe
```

### 4.11 Onboarding Model

<!-- schema: OnboardingStep -->
<!-- schema: OnboardingRecord -->
```python
class OnboardingStep(str, Enum):
    FIRST_DELIVERY = "first_delivery"
    PREFERENCE_VERIFICATION = "preference_verification"
    CROSS_PRODUCT_INTRO = "cross_product_intro"
    CHANNEL_CONFIRMATION = "channel_confirmation"
    COMPLETE = "complete"

@dataclass
class OnboardingRecord:
    """Tracks B1.3 Onboarding progress."""
    id: str                            # "ob_{uuid8}"
    subscription_id: str               # FK to Subscription
    status: str                        # "in_progress" | "complete" | "failed"
    current_step: OnboardingStep       # Current onboarding step
    first_delivery_at: datetime | None = None
    preference_verified_at: datetime | None = None
    config_refinement_rounds: int = 0  # Number of NL→Config refinement loops
    cross_product_delivered_at: datetime | None = None
    channels_confirmed: list[str] = field(default_factory=list)
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
```

### 4.12 Reactivation Model

<!-- schema: ConfigSnapshot -->
<!-- schema: ReactivationRecord -->
```python
@dataclass
class ConfigSnapshot:
    """Pre-churn config snapshot for reactivation."""
    id: str                            # "cs_{uuid8}"
    subscription_id: str              # FK to original Subscription
    config: SubscriptionConfig         # Frozen config at time of churn
    delivery_history_ref: str | None  # Reference to archived delivery log
    captured_at: datetime

@dataclass
class ReactivationRecord:
    """Tracks B1.7 Reactivation."""
    id: str                            # "rea_{uuid8}"
    original_subscription_id: str      # FK to pre-churn Subscription
    new_subscription_id: str           # FK to new/reactivated Subscription
    config_snapshot_id: str | None     # FK to ConfigSnapshot (may be None if snapshot unavailable)
    retention_window_expired: bool     # Whether retention window has passed
    data_restored: list[str]           # List of restored data types: ["config", "kb_entries", "delivery_history"]
    reactivated_at: datetime
    welcome_back_digest_id: str | None = None  # "Since you were away" digest product
```

### 4.13 NL→Config Audit Model

<!-- schema: NLConfigAuditEntry -->
```python
@dataclass
class NLConfigAuditEntry:
    """Records a single NL→Config pipeline execution for audit trail.

    Created every time B1's NL utterance is parsed into structured config changes.
    Provides traceability for: what B1 said, what the agent understood, what changed.
    """
    id: str                            # "nlcfg_{uuid8}"
    subscription_id: str               # FK to Subscription being modified
    nl_intent: str                     # B1's original NL utterance
    parsed_config: dict                # LLM-parsed structured intent
    confidence_score: float            # LLM confidence in parsing (0-1)
    change_type: str                   # "non-billing" | "billing_affecting" | "ambiguous"
    changes_applied: list[ConfigChange]  # List of actual config changes
    human_confirmed: bool              # Whether B1 confirmed the parsed changes
    ambiguous: bool                    # Whether LLM needed clarification
    clarification_prompt: str | None  # If ambiguous, what agent asked B1
    created_at: datetime
```

> **Note on implementation**: These models are specification-only until the corresponding F-expectations (F65-F68) are implemented. The existing `Subscription` model in code (`src/autoinfo/models.py`) will need to be extended with a `config: SubscriptionConfig` field when F67 (NL→Config pipeline) is built.
