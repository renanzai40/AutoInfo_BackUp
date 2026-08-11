<!-- agent: delivery-reference -->
# Delivery, Products & End User Lifecycle

> Extracted from `founder-expectations.md §§12.9-12.10, 12.14-12.15`. References: F20 (Output Generation), F21-F24 (Delivery), F32 (End User Lifecycle), F55 (Error Recovery), F56 (User Portal).
> **Cross-spec:** `docs/dev/specs/user-lifecycle-definition.md` (B1 End User Lifecycle root spec) — see §11 B1 Lifecycle Integration for stage-to-delivery mapping.

---

## 1. Output Generation (§12.9)

### 1.1 Product Types

| Product | MCP Tool | Description | Template Engine | Output Formats | Delivery Gates |
|---------|----------|-------------|----------------|----------------|---------------|
| **Digest** | `generate_digest()` | Curated summary of recent items per topic | Jinja2 | Markdown, HTML, Plain Text, **Audio (TTS MP3)** | D1, D3 |
| **Report** | `generate_report()` | Structured deep-dive on a topic with analysis | Jinja2 + LLM | Markdown, JSON, PDF, HTML, **Audio (TTS MP3)** | D1, D2, D3 |
| **Premium Briefing** | `generate_report(product="premium-briefing")` | Premium differentiated report product: per-item **implications / risks / action_required** analysis layered on the base synthesis (G15-gated tiered product) | Jinja2 + LLM | Markdown, HTML, JSON, PDF, Audio, Agent | D1, D2, D3 |
| **Enterprise Briefing** | `generate_report(product="enterprise-briefing")` | Enterprise differentiated report product: adds per-item **key_metrics** (metric/value/source) on top of the premium analysis fields | Jinja2 + LLM | Markdown, HTML, JSON, PDF, Audio, Agent | D1, D2, D3 |
| **Magazine Digest** | `generate_digest(product="magazine-digest")` | Per-title clustered digest (D11) — routed through the **digest** generation path (`generate_digest`), not the report path | Jinja2 + LLM | Markdown, HTML, JSON, Agent | D1, D2, D3 |
| **Tutorial** | `generate_tutorial()` | Step-by-step learning content built from KB | Jinja2 + LLM | Markdown, HTML | D1, D2 |
| **Presentation** | `generate_presentation()` | Slide deck generated from KB entries | Jinja2 + Reveal.js CDN | HTML | D1, D2 |
| **Agent-Native JSON** | `generate_digest(format="agent")` | Structured JSON-LD optimized for LLM re-consumption | LLM renderer | JSON-LD (`@type: "KnowledgeDigest"`) | D1, D2 |
| **KB Export** | `export_kb()` | Bulk export of KB entries | Export renderer | Markdown, JSON, SQLite, PDF, CSV, GraphML, **Bundle (ZIP)** | D1, D2 |
| **RAW Feed** | `list_products()` / `get_product()` (type=`raw`) | Raw KB items delivered as API feed, webhook stream, or bulk export. `Product.variants` distinguishes the three modes: `["api_feed", "webhook", "bulk_export"]` (E11). | N/A (direct KB read) | API JSON, webhook payload, export bundle | D1, D3 |

**Differentiated product templates** (8 templates in `PRODUCT_TEMPLATES`, `src/autoinfo/output/__init__.py`): `digest`, `report`, `tutorial`, `presentation`, `premium-briefing`, `column`, `magazine-digest`, `enterprise-briefing`. The `premium-briefing` and `enterprise-briefing` templates are resolved guard-first via `_resolve_report_product_type` (mirrors the digest resolver `_resolve_digest_product_type`) and render only when the request names the product — a `generate_report(product="premium-briefing")` call resolves to the differentiated template before any fallback to the standard report template. `magazine-digest` is a digest-path product: `generate_digest(product="magazine-digest")` routes through the digest renderer (D11 fix: previously mis-routed via the report path).

### 1.2 Generation Pipeline

> **Agent reference**: All `generate_*` functions are available as MCP tools. See `mcp-tools.md` for full signatures.

```
1. Agent calls the generate_digest() MCP tool (or generate_report, generate_tutorial, etc.)
2. Fetch relevant 02-Draft entries (by topic + date range)
3. Load Jinja2 template (built-in or custom; `product` param resolves a differentiated product template guard-first — `premium-briefing`/`enterprise-briefing` via `_resolve_report_product_type`, `magazine-digest` via `_resolve_digest_product_type`)
4. Build template context:
   - entries: list of draft entries
   - domain_config: current domain settings
   - frontmatter_context: resolved from template frontmatter
   - generated_at: current timestamp
   - custom_globals: user-defined variables
   - llm_synthesis: per-product LLM synthesis (see below)
5. Render template → Markdown
6. Run delivery gates (D1-D3):
   - D1: completeness check
   - D2: format conversion + integrity check
   - D3: freshness check
7. Return rendered product or raise gate failure
```

**Dual-context render contract** — differentiated product templates are rendered with a **normalized flat context**, not the raw nested digest context: `_normalize_digest_product_context` flattens the `llm_synthesis` structure into top-level keys so product templates can reference `{{ implications }}` / `{{ risks }}` / `{{ action_required }}` / `{{ key_metrics }}` directly (the standard digest/report templates keep the nested context unchanged). Product templates that request per-item analysis receive **per-product LLM synthesis fields**: `implications` and `risks` (all products), `action_required` (premium/enterprise), `key_metrics` (enterprise only) — each a `list[str]` (or `list[dict[str, str]]` for metrics: `metric` / `value` / `source`) **index-aligned 1:1 with `key_findings`** so every finding carries its so-what analysis. The product analysis is persisted to the KB entries' `custom_fields["product_analysis"]` via `KBStore.update_entry_metadata` (see pipeline.md §2.6).

**Report-synthesis robustness** — `_generate_executive_summary` retries the §2.4 product sections with a bounded retry loop (up to 4 attempts with backoff) and a dedicated small prompt when the base synthesis omits the product sections, so a partial LLM omission degrades to a retry, not a section gap.

### 1.3 Template Frontmatter Context Variables

Templates support frontmatter blocks for configuration:

```yaml
---
# Built-in variables (resolved at generation time):
title: "Weekly Digest: {{domain}}"
date: {{generated_at}}
period: {{period}}  # "day", "week", "month"
max_entries: 10      # Custom parameter

# Custom globals (from config or tool params):
company_name: "Acme Research"
logo_url: "https://example.com/logo.png"
---
```

**Resolution order** (later overrides earlier):
1. Template default frontmatter
2. Domain-level custom template globals (`config.yaml → output.templates.{name}.globals`)
3. Tool call parameter (`generate_digest(..., template_vars={"max_entries": 20})`)

### 1.4 Context Variable Resolution

When a template references `{{company_name}}`, the resolver checks:
1. `template_vars` dict (from tool call)
2. `domain_config.output.templates.{name}.globals`
3. Template frontmatter defaults
4. Empty string (fallback — never fails with undefined error)

### 1.5 Agent-Native JSON Output Format

The Agent-Native JSON format is a structured JSON-LD schema designed for LLM re-consumption — agents parse, re-synthesize, store in their own KB, or combine with other data sources.

```json
{
  "@context": "https://autoinfo.ai/schemas/knowledge-digest-v1",
  "@type": "KnowledgeDigest",
  "uuid": "digest_uuid8",
  "generated_at": "2026-07-26T10:00:00Z",
  "domain": "medical-research",
  "period": "week",
  "target_audience": "clinician",
  "entries": [
    {
      "uuid": "entry_uuid8",
      "title": "Endometrial Receptivity Markers in IVF",
      "tl_dr": "Study identifies three novel biomarkers for endometrial receptivity...",
      "source_url": "https://pubmed.ncbi.nlm.nih.gov/12345",
      "source_platform": "pubmed",
      "collected_at": "2026-07-25T08:00:00Z",
      "relevance_score": 92,
      "confidence_score": 0.87,
      "entities": [
        {"name": "Endometrial Receptivity", "type": "concept", "relation": "subject"},
        {"name": "IVF", "type": "technology", "relation": "context"}
      ],
      "key_points": ["Novel biomarker A shows 89% specificity", "Clinical trial with n=450"],
      "full_text_summary": "Full LLM-generated summary of the entry...",
      "citations": [{"source": "PubMed", "url": "https://pubmed.ncbi.nlm.nih.gov/12345", "accessed_at": "2026-07-25T08:00:00Z"}]
    }
  ],
  "trends": [
    {"topic": "Biomarker discovery", "direction": "accelerating", "evidence": "3 new studies this week"}
  ],
  "product_analysis": {
    "implications": ["Biomarker A panel could enter clinical validation within 12 months"],
    "risks": ["Small cohort (n=450) limits statistical power"],
    "action_required": ["Track follow-up validation trial", "Monitor competitor assay filings"],
    "key_metrics": [{"metric": "Sensitivity", "value": "89%", "source": "Study table 3"}]
  },
  "metadata": {
    "entry_count": 15,
    "total_tokens": 4500,
    "generation_model": "claude-sonnet-4",
    "quality_gates": [
      {"name": "D1", "passed": true},
      {"name": "D3", "passed": true}
    ]
  }
}
```

**Key design principles**:
- Every entity has an `entity_id` (UUID) for cross-referencing across digests
- `confidence_score` (0.0-1.0) per entry enables agent to weigh reliability
- `quality_gates` array tells agent what checks were passed
- `@context` enables JSON-LD consumption by semantic web tools
- Format is generated by the LLM renderer (not Jinja2) — the LLM receives the digest context and outputs structured JSON-LD
- `product_analysis` (optional) carries the per-product synthesis fields — `implications`, `risks`, `action_required`, `key_metrics` — index-aligned with `key_findings` when generated for a differentiated product template (premium-briefing / enterprise-briefing / magazine-digest); absent for standard digest/report renders. The JSON-LD schema in `docs/schemas/knowledge-digest-v1.json` was extended with these optional fields.

**Usage**: `generate_digest(domain, period, format="agent")` returns the agent-native JSON. The MCP tool serializes the LLM output into the structured schema. Agent uses this for: re-synthesis into own knowledge base, cross-domain analysis, caching for offline access, or direct presentation to end user.

### 1.6 MCP Output Tools

| Tool | Parameters | Returns |
|------|-----------|---------|
| `list_output_templates(domain)` | domain | List of available template names with description |
| `generate_digest(domain, period, topic, template, format, template_vars, product)` | Required: domain. Optional: all others. `product` selects a differentiated digest-path product template (e.g. `magazine-digest`). | Rendered product in requested format |
| `generate_report(domain, topic, template, format, template_vars, product)` | Same pattern. `product="premium-briefing"` / `"enterprise-briefing"` select the differentiated briefing templates (guard-first resolution). | Rendered report |
| `generate_tutorial(domain, topic, template, format, template_vars)` | Same pattern | Rendered tutorial |
| `generate_presentation(domain, topic, template, template_vars)` | Same pattern | HTML presentation |
| `localize_content(content, source_language, target_language)` | content + language params | Translated content |

---

## 2. Delivery Channels (§12.10)

### 2.1 Architecture

Delivery runs as a synchronous export step: product is generated, gates run, then passed to the delivery channel.

```
Product → D1 → D2 → D3 → Delivery Channel → DeliveryLog → (optional) Delivery receipt
```

### 2.2 Channel Registry

Delivery is channel-agnostic via `DeliveryChannel` ABC:

```python
class DeliveryChannel(ABC):
    channel_type: str  # Unique identifier

    @abstractmethod
    def deliver(self, product, config) -> DeliveryResult:
        """Send product through channel. Returns success/failure + metadata."""
        ...

    @abstractmethod
    def validate_config(self, config) -> bool:
        """Check required credentials/endpoints are configured."""
        ...
```

### 2.3 Supported Channels

| Channel | Channel Type | Config Requirements | SLA Target |
|---------|-------------|---------------------|------------|
| **SMTP Email** | `smtp` | SMTP host, port, username, password, from_addr | < 30s |
| **Telegram** | `telegram` | Bot token, chat_id | < 5s |
| **WeChat OA** | `wechat_oa` | AppID, AppSecret, template_id | < 5s |
| **WeChat Work** | `wechat_work` | CorpID, AgentID, Secret | < 5s |
| **DingTalk** | `dingtalk` | Webhook URL + secret | < 3s |
| **FeiShu/Lark** | `feishu` | Webhook URL + secret | < 3s |
| **Discord** | `discord` | Webhook URL | < 3s |
| **Webhook** | `webhook` | URL, HMAC secret (opt), retry config | < 10s |
| **REST API** | `rest_api` | Base URL, API key | < 5s |
| **Local File Export** | `file_export` | Output directory | < 1s |
| **RSS Feed** ✅ | `rss` | Output directory, feed config (title, description, ttl). RSS 2.0 channel with `<enclosure>` + `itunes:*` namespace for podcast feed generation (C11). | < 30s |
| **Social Publish** ✅ | `social_publish` | Platform credentials, post template | < 10s |
| **Push** ✅ | `push` | Generic HTTP POST endpoint (`push_endpoint` or `${PUSH_ENDPOINT}` env var), optional Bearer token (`push_token` or `${PUSH_TOKEN}`) | < 10s |

### 2.4 Retry & SLA

```python
# Per-channel retry config
CHANNEL_RETRY_CONFIG: dict[str, RetryConfig] = {
    "smtp":          RetryConfig(max_retries=3, backoff_base=5.0, backoff_max=300.0),
    "telegram":      RetryConfig(max_retries=2, backoff_base=2.0, backoff_max=30.0),
    "wechat_oa":     RetryConfig(max_retries=2, backoff_base=2.0, backoff_max=30.0),
    "wechat_work":   RetryConfig(max_retries=2, backoff_base=2.0, backoff_max=30.0),
    "dingtalk":      RetryConfig(max_retries=2, backoff_base=1.0, backoff_max=10.0),
    "feishu":        RetryConfig(max_retries=2, backoff_base=1.0, backoff_max=10.0),
    "discord":       RetryConfig(max_retries=2, backoff_base=1.0, backoff_max=10.0),
    "webhook":       RetryConfig(max_retries=3, backoff_base=2.0, backoff_max=60.0),
    "rest_api":      RetryConfig(max_retries=3, backoff_base=2.0, backoff_max=60.0),
    "file_export":   RetryConfig(max_retries=1, backoff_base=1.0, backoff_max=5.0),
    "rss":           RetryConfig(max_retries=2, backoff_base=2.0, backoff_max=30.0),
    "social_publish": RetryConfig(max_retries=2, backoff_base=2.0, backoff_max=30.0),
}

@dataclass
class RetryConfig:
    max_retries: int = 3
    backoff_base: float = 5.0       # seconds — exponential backoff multiplier
    backoff_max: float = 300.0      # seconds — cap per retry interval
    retryable_statuses: list[int] = field(default_factory=lambda: [408, 429, 500, 502, 503, 504])
```

### 2.5 Delivery Result

```python
@dataclass
class DeliveryResult:
    success: bool
    channel: str
    recipient: str
    delivered_at: datetime
    attempt_count: int = 1
    error: str | None = None
    receipt_id: str | None = None  # External channel message ID
```

---

### 2.6 Agent-Mediated Delivery

Agent-mediated delivery extends the channel model beyond direct push-to-human channels. Instead of delivering products to email or chat, products are pushed to an **agent endpoint** (webhook callback) for agent consumption and re-distribution.

**Push model**:
```
Product → D1 → D2 → D3 → Agent Push (HTTP POST to agent callback URL)
                           → Agent receives structured JSON
                           → Agent decides: present to user, re-synthesize, or cache
```

| Pattern | Description |
|---------|-------------|
| **Agent subscription** | Agent registers callback URL via `set_agent_callback(url, events=["new_digest"])`. AutoInfo pushes to callback when matching product is generated. Enables "subscription" without human polling. |
| **Pull model (existing)** | Agent calls `generate_digest()`, `search_knowledge_base()`, etc. synchronously. No callback needed. |
| **Hybrid** | Agent polls for availability, AutoInfo provides callback as optimization. Both coexist. |

**Callback payload**: Canonical push envelope `{event, payload, schema_version, trace_id, product_id}`. `event` is one of `new_digest`, `new_report`, `new_tutorial`; `payload` is the generated output (JSON-LD for `format="agent"`, markdown/HTML otherwise); `schema_version` is `1`; `trace_id` and `product_id` carry delivery context. Delivery is fire-and-forget through the durable SQLite outbox (`agent_outbox`): the row is persisted before any attempt, a background worker drains it (`pending` → `delivered` | `failed`), and `failed` rows are requeued on process start. No retry or backoff; failures surface via the `delivery_failures_total` metric.

**Use cases**:
- AI agent (e.g., Perplexity Comet, ChatGPT Tasks) subscribes to "weekly medical research digest" — AutoInfo pushes when ready
- Enterprise integration: agent receives structured data, enriches with internal data, delivers to end users via custom channel
- Agent-to-agent handoff: AutoInfo pushes to orchestrator agent, orchestrator fans out to specialist agents

---

## 3. Error Recovery & Resilience (§12.14)

### 3.1 Channel-Level

| Failure | Recovery |
|---------|----------|
| Transient HTTP error (408, 429, 5xx) | Retry with exponential backoff per `RetryConfig` |
| Network timeout | Retry up to `max_retries`; after exhaustion → log failure |
| Authentication failure | No retry (credential issue) → log with diagnostic |
| Rate limiting (429 with Retry-After) | Respect Retry-After header, then retry |
| Channel misconfiguration (invalid webhook URL, deleted bot) | No retry → log with config diagnostic |

### 3.2 Product-Level

| Failure | Recovery |
|---------|----------|
| D1 completeness failure | Block delivery; return error with missing sections |
| D2 format failure | Fallback from HTML to plain text; return with warning |
| D3 staleness | Flag in output but deliver (configurable per domain — block or proceed) |
| Empty entry list (no items for topic/period) | Return error "No items available" — do NOT send empty digest |

### 3.3 Delivery Log

Every delivery attempt (success or failure) is recorded in `DeliveryLog`:

```python
@dataclass
class DeliveryLog:
    id: str                          # "dlog_{uuid8}"
    subscription_id: str             # FK to Subscription
    product_id: str | None           # FK to Product (if applicable)
    channel: str
    recipient: str
    success: bool
    attempt_count: int
    delivered_at: datetime
    error: str | None = None
    trace_id: str = ""               # Links to collection trace
```

---

## 4. End User Lifecycle (§12.15)

> **Root spec**: `docs/dev/specs/user-lifecycle-definition.md` §2 (B1 End User Lifecycle) — that is the canonical home for B1 lifecycle stages, state machine, and identity model. This section covers **delivery-specific aspects only**: data models for delivery, channel configuration, and MCP end-user tools. Do not duplicate lifecycle-stage tables here; refer to the root spec.

### 4.1 Data Model

```python
@dataclass
class UserProfile:
    id: str                          # "usr_{uuid8}"
    name: str
    email: str
    delivery_preferences: DeliveryPreferences
    status: UserStatus               # trial | active | suspended | cancelled
    created_at: datetime
    updated_at: datetime
    identity_anchor: str             # "native" | "oauth_provider:{provider}:{sub}"

@dataclass
class DeliveryPreferences:
    channels: dict[str, list[ChannelConfig]]  # channel_type → [config per subscription? maybe per user?]
    quiet_hours: QuietHours | None = None
    max_daily_digests: int = 1
    preferred_format: str = "markdown"  # "markdown" | "html" | "text"

@dataclass
class ChannelConfig:
    channel_type: str
    recipient: str                   # email address, chat_id, webhook URL
    enabled: bool = True

@dataclass
class QuietHours:
    start: str                       # "22:00"
    end: str                         # "07:00"
    timezone: str = "UTC"
    only_urgent: bool = False        # If True, only urgent alerts during quiet hours

@dataclass
class Subscription:
    id: str                          # "sub_{uuid8}"
    user_id: str                     # FK to UserProfile
    domain: str
    topics: list[str]
    products: list[str]              # ["digest", "report", "tutorial", "presentation"]
    channels: list[str]              # Channel types for delivery ("smtp", "telegram", ...) — one of the 13 canonical channels
    schedule: str                    # Cron expression ("0 8 * * 1" = weekly Monday 8AM)
    status: SubscriptionStatus       # active | paused | cancelled
    created_at: datetime
    updated_at: datetime
    last_delivered_at: datetime | None = None

class UserStatus(Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"

class SubscriptionStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
```

> **UserProfile ↔ B1 identity**: `UserProfile` maps to B1 identity. The NL→Config pipeline (B1 NL utterance → Agent parses intent → structured config mutation) creates and updates this profile. See `docs/dev/specs/user-lifecycle-definition.md` §2.1 and §11.3 of this file for the NL→Config pipeline.

#### 4.1.1 Code Reality vs Spec Discrepancies

> **Updated 2026-07-27**: The spec dataclasses above describe the *intended* data model. The actual implementation in `src/autoinfo/models.py` differs in the following ways. These discrepancies should be resolved by implementing the spec model (not by downgrading the spec).

| Spec Construct | Code Reality | Gap ID | Resolution |
|---------------|-------------|--------|------------|
| `DeliveryPreferences` dataclass with typed `channels: dict[str, list[ChannelConfig]]`, `quiet_hours`, `max_daily_digests`, `preferred_format` | `delivery_preferences: dict[str, Any]` — freeform dict with no type enforcement | [CD-019](cross-dimensional-catalog.md#cd-019-quiet-hours-configuration) | Implement typed `DeliveryPreferences`; currently operator must know the expected dict shape |
| `ChannelConfig` typed class with `channel_type`, `recipient`, `enabled` | **No `ChannelConfig` class exists** — channel config is embedded in the freeform dict or handled ad-hoc | [CD-020](cross-dimensional-catalog.md#cd-020-subscription--channel-linking) | Implement `ChannelConfig`; link to `DeliveryChannel` registry for validation |
| `QuietHours` dataclass with `start`, `end`, `timezone`, `only_urgent` | **Not implemented** — zero code for quiet hours enforcement | [CD-019](cross-dimensional-catalog.md#cd-019-quiet-hours-configuration) | Implement `QuietHours` and enforcement in `deliver_with_retry()` |
| `Subscription` with `domain`, `topics`, `products`, `channels`, `schedule` — single unified model tied to a domain | `Subscription` has `plan`, `status`, `price_monthly`, `auto_renew`, `features` — billing-only model, no domain/product/channel linking | [CD-024](cross-dimensional-catalog.md#cd-024-subscription-model-disconnected-layers) | Unify `Subscription` with domain-scoped fields; implement tier→product→channel linking |
| `UserProfile.identity_anchor` for cross-platform identity resolution | `UserProfile` has `stripe_customer_id`, `stripe_subscription_id`, `tier` — identity is implicit via `user_id` UUID | [CD-021](cross-dimensional-catalog.md#cd-021-identity-anchor) | Add `identity_anchor` field to `UserProfile` |
| `UserProfile.tier` controls data retention | `Subscription.plan` controls billing tier | `UserProfile.tier` + `Subscription.plan` are **3 disconnected layers** — no code links tier ↔ plan ↔ product access | [CD-024](cross-dimensional-catalog.md#cd-024-subscription-model-disconnected-layers) | Unify as single source of truth: `Subscription.plan` determines `UserProfile.tier` and unlocked `ProductTemplate.access_level` |

**Implication**: The MCP tool `update_preferences` currently writes into a `dict[str, Any]` with no schema validation. Any key can be set; invalid keys are silently stored. Channel configurations are not validated against the `DeliveryChannel` registry. Operators and agents must manually ensure the dict structure matches expected shape.

### 4.2 User Status State Machine

```
         trial ──→ active ──→ suspended ──→ cancelled
           │         │            │
           └──→ cancelled    (can re-activate)
           (trial expired)
```

**v1 Constraints**:
- No user registration flow (users created via MCP tool only)
- No authentication/authorization (all users are operator-managed)
- No self-service portal (portal is CLI-based, operator-facing)
- All delivery config is operator-set

### 4.3 Identity Anchors

`UserProfile.identity_anchor` determines how a user is identified:

| Anchor | Format | Use Case |
|--------|--------|----------|
| `native` | `native` | Operator-created users (v1 default) |
| OAuth | `oauth_provider:{provider}:{sub}` | Future OAuth integration |
| Email | `email:{email}` | Future email-based auth |

**Design choice**: identity anchor is stored once and never changed. It is the source of truth for user uniqueness. No merging of identities in v1.

### 4.4 MCP End User Tools

| Tool | Description |
|------|-------------|
| `create_end_user(name, email, channels, products, trial_days=14)` | Create user with default trial subscription |
| `get_end_user(user_id)` | Get user profile + subscription summary |
| `update_end_user(user_id, **fields)` | Update delivery preferences, status, etc. |
| `list_end_users(domain, status, page, limit)` | Paginated user list with filters |
| `get_subscription(subscription_id)` | Get subscription details |
| `update_subscription(subscription_id, **fields)` | Pause, resume, change topics/products/channels |
| `deactivate_end_user(user_id, reason)` | Suspend or cancel user; trigger notification |
| `get_delivery_log(user_id, limit)` | Recent delivery history for a user |
| `send_test_delivery(user_id, channel)` | Send test product through a specific channel |

### 4.5 Implementation Notes (v1)

| Concern | Decision |
|---------|----------|
| **Persistence** | SQLite via `sqlite3` module. User table, Subscription table, DeliveryLog table. Linked to KB via trace_id / user_id. |
| **Trial management** | Operator-managed. MCP tool `create_end_user` sets `trial_end = created_at + trial_days`. No automatic expiry in v1 (operator checks manually or via `list_end_users(status="trial")`). |
| **Quiet hours enforcement** | `deliver_with_retry()` checks `DeliveryPreferences.quiet_hours` before sending. If inside quiet window and `only_urgent=False`, queue for next window. |
| **Channel config per user** | Each channel type can appear once per user with different recipient (e.g., two email addresses = two email ChannelConfig entries). |
| **Subscription→Channel linking** | `Subscription.channels` lists channel types. The actual recipient config comes from `UserProfile.delivery_preferences.channels[channel_type]`. This allows operator to change user's email address without updating every subscription. |

---

## 5. End-User Product Lifecycle

> **Gap-filled 2026-07-26**: This section addresses the product lifecycle from the end user's perspective — how products get created, consumed, age, and get regenerated across different domain types.
> **Updated 2026-07-27**: Added `ProductState` management lifecycle enum (CD-017) — distinct from the product journey states in §5.1 below. The ProductState enum controls product *availability* (draft → active → archived), while §5.1 states track product *generation progress* (Created → Generated → Delivered).

### 5.0 ProductState Enum — Management Lifecycle (CD-017)

> **Specification for implementation** — defines the availability/management lifecycle of a product instance. This is distinct from the generation pipeline states in §5.1: a product can be in `active` management state while going through `Created → Generated → Delivered` pipeline states.

```python
class ProductState(Enum):
    """Management lifecycle of a product instance."""
    DRAFT = "draft"           # Being authored — not visible to end users
    PENDING = "pending"       # Awaiting review/approval before activation
    ACTIVE = "active"         # Available for delivery — normal operating state
    PAUSED = "paused"         # Temporarily suspended — no new deliveries
    ARCHIVED = "archived"     # Moved to long-term storage — still accessible
    DEPRECATED = "deprecated" # No longer supported — may be removed in future
```

| State | Description | Allowed Transitions | Visible to End User? | Deliverable? |
|-------|-------------|---------------------|---------------------|-------------|
| **Draft** | Product being authored/configured. Template and source configs being set up. | → Pending, → Active (skip review) | ❌ No | ❌ No |
| **Pending** | Submitted for review. Director/agent verifies quality before activation. | → Active (approved), → Draft (rejected back to authoring) | ❌ No | ❌ No |
| **Active** | Product is live. Scheduled deliveries execute. End users with matching subscriptions receive this product. | → Paused, → Archived, → Deprecated | ✅ Yes | ✅ Yes |
| **Paused** | Temporarily suspended (e.g., during maintenance, source outage, or seasonal break). No new deliveries but existing archive remains accessible. | → Active (resume), → Archived | 🟡 Existing archive visible; no new deliveries | ❌ No |
| **Archived** | Product no longer in active rotation. Content preserved in archive for historical access. | → Active (reactivate, rare) | 🟡 Archive view only | ❌ No |
| **Deprecated** | Product is obsolete. Not recommended for new subscriptions. May be removed in future cleanup. | Terminal — no recovery (archive → deprecated is possible) | 🟡 Archive view with deprecation warning | ❌ No |

**State machine diagram**:
```
        ┌─────────┐     approve     ┌─────────┐
        │  DRAFT  │ ──────────────→ │ PENDING │
        └────┬─────┘                 └────┬─────┘
             │                            │
             │ skip review                │ approved
             │                            │
             ▼                            ▼
        ┌─────────────────────────────────────────┐
        │                ACTIVE                    │
        │  (normal operation — deliveries active)  │
        └─────┬──────────────┬───────────────┬────┘
              │              │               │
              │ pause        │ archive       │ deprecate
              ▼              ▼               ▼
        ┌─────────┐   ┌──────────┐   ┌─────────────┐
        │ PAUSED  │   │ ARCHIVED │   │ DEPRECATED  │
        └────┬────┘   └──────────┘   └─────────────┘
             │                              ▲
             │ resume                       │
             └──────────────────────────────┘
             (or: paused → archive)
```

**MCP tools for lifecycle management** (CD-017):

| Tool | Description | State Transition |
|------|-------------|-----------------|
| `get_product_lifecycle(product_id)` | Return current ProductState + transition history timestamps | Read-only |
| `list_user_products(user_id, state, limit)` | List products accessible to a user, filtered by state | Read-only |
| `activate_product(product_id)` | Move from Draft/Pending → Active (approval step) | Draft/Pending → Active |
| `publish_product(product_id)` | Make draft product visible; optional skip-review → Active directly | Draft → Active |
| `pause_product(product_id)` | Temporarily suspend deliveries for a product | Active → Paused |
| `resume_product(product_id)` | Resume deliveries for a paused product | Paused → Active |
| `archive_product(product_id)` | Move product to long-term storage | Active/Paused → Archived |
| `deprecate_product(product_id)` | Mark product as deprecated — terminal action (CD-028) | Active/Archived → Deprecated |
| `regenerate_product(product_id, template_vars)` | Force regeneration of an existing product with current KB state, respecting active state | Read-only (generates a new delivery) |
| `get_engagement_metrics(user_id, period)` | Aggregate delivery + consumption signals for a user (see §6) | Read-only |

> **Implementation status (2026-07-27)**: `ProductState` enum and all lifecycle MCP tools are **spec'd but not implemented** ([CD-017](cross-dimensional-catalog.md#cd-017-product-lifecycle-mcp-tools)). The existing `Product` model in `src/autoinfo/models.py` has `ProductType` (RAW/PROCESSED) and `ProductTemplate` but no `ProductInstance`, no `ProductState`, and no lifecycle management code. Only `list_products` and `get_product` MCP tools exist in the Product category.

### 5.1 Product Lifecycle States

Each product tracks its lifecycle through these states:

```
Created (by schedule/trigger) → Generated → Delivered → Consumed → Aged → Archived
                                                                  │
                                                                  └→ Regenerated (by new schedule run)
```

| State | Description | Metadata |
|-------|-------------|----------|
| **Created** | Product instance is initiated by a schedule trigger, user request, or alert rule | `product_state: created`, `created_at` |
| **Generated** | Template rendering + gate checks complete. Product content exists. | `product_state: generated`, `generated_at`, `entry_count`, `size_bytes` |
| **Delivered** | Product pushed through at least one delivery channel. DeliveryLog recorded. | `product_state: delivered`, `delivered_at`, `channel_count`, `recipient_count` |
| **Consumed** | End user has accessed/read the product (tracked via delivery channel read receipts or implicit signals) | `product_state: consumed`, `first_opened_at`, `read_duration_seconds` (optional) |
| **Aged** | Product content exceeds domain TTL or freshness threshold. Still accessible but flagged. | `product_state: aged`, `aged_at`, `freshness_score` |
| **Archived** | Product moved to long-term storage. Not in active rotation but user-accessible via portal. | `product_state: archived`, `archived_at`, `archive_path` |

**v1 Constraints**: `consumed` tracking is optional (channel-dependent — email read receipts are unreliable, webhook has no read signal). In v1, products transition directly `Delivered → Aged → Archived` unless the channel provides explicit consumption signals.

### 5.2 Product Consumption Patterns by Domain

Different domains produce products with fundamentally different consumption lifecycles:

#### 5.2.1 Medical Research

| Aspect | Pattern |
|--------|---------|
| **Product types** | Weekly digest, thematic report, alert (new paper matching saved query) |
| **Consumption cadence** | Weekly batch (Mondays), with alerts interspersed. Clinicians read during dedicated research time. |
| **Freshness window** | 7–30 days. Newer papers supersede older findings. Relevance decays as consensus shifts. |
| **Archive value** | High. Users search historical digests for literature reviews. Archive search is a primary feature. |
| **Regeneration trigger** | New papers published (source-driven). `collect` runs daily; digest regenerated weekly on schedule. |
| **Bundling** | Alert + Weekly Digest is natural bundle. Users subscribe to specific topics. |

#### 5.2.2 AI Commercial Intelligence

| Aspect | Pattern |
|--------|---------|
| **Product types** | Daily brief, competitive analysis report, alert (funding round, product launch) |
| **Consumption cadence** | Daily (morning brief). Executives scan headlines; deep-dive on weekends. |
| **Freshness window** | 1–3 days. Market news is extremely time-sensitive. 7-day-old funding news is stale. |
| **Archive value** | Moderate — for trend analysis but not for operational decisions. |
| **Regeneration trigger** | Time-driven (daily) + event-driven (alert rules on competitor names). |
| **Bundling** | Daily Brief + Custom Alert stream. Report produced weekly on specific competitor. |

#### 5.2.3 Financial Intelligence

| Aspect | Pattern |
|--------|---------|
| **Product types** | Daily market brief, SEC filing alert, earnings report digest |
| **Consumption cadence** | Pre-market open (daily), intra-day for alerts. Analysts need data before trading hours. |
| **Freshness window** | Hours to 1 day. SEC filing timestamps matter. Earnings data loses value after next earnings cycle. |
| **Archive value** | Moderate (for back-testing, historical comparison, compliance). Regulated users need 5+ year retention. |
| **Regeneration trigger** | Strictly time-driven (pre-market) + SEC filing event-driven. |
| **Compliance** | FINRA/SEC record-keeping requirements may mandate delivery log retention for 5+ years. |

#### 5.2.4 Tech/AI Developer

| Aspect | Pattern |
|--------|---------|
| **Product types** | Weekly newsletter, GitHub trend report, release alert |
| **Consumption cadence** | Irregular — batch reading during dedicated time. Weekend peak consumption. |
| **Freshness window** | 7–14 days. Framework releases and GitHub trends have ~2-week relevance. |
| **Archive value** | High for reference (release notes history, trend comparisons). |
| **Regeneration trigger** | Weekly + event-driven (new GitHub star threshold, new Stack Exchange hot question). |

#### 5.2.5 Language Learning

| Aspect | Pattern |
|--------|---------|
| **Product types** | CEFR-graded reading list, vocabulary tutorial, comprehension quiz |
| **Consumption cadence** | Self-paced — daily or every-other-day practice. Users control their schedule. |
| **Freshness window** | Months to years. Learning content is evergreen. Freshness is about CEFR calibration accuracy, not topicality. |
| **Archive value** | Very high. Learners revisit past materials for review. Archive is core to the learning process. |
| **Regeneration trigger** | Manual (user requests new material at their level) or periodic (new content sourced weekly). |

### 5.3 Product ↔ Content Lifecycle Integration

Products do not exist independently — they are derived from KB entries, which have their own lifecycle (TTL, versioning, stale handling, §3 of `operations.md`). The integration rules:

| Rule | Behavior |
|------|----------|
| **Product reflects KB at generation time** | Generated product captures a snapshot of current KB entries. Subsequent KB updates (version bumps, stale marking) do NOT retroactively update already-generated products. |
| **Stale KB entries → excluded from new products** | When generating a new product, entries flagged `stale: true` are excluded by default (override via `include_stale=True` parameter). |
| **Re-collected entries → product regenerated** | When a source is re-collected and entries are version-bumped, the next scheduled product generation includes the updated content. Old product versions remain in archive. |
| **TTL extends to products** | Products aged beyond the domain's `default_ttl_days` are flagged `aged` and demoted in archive search. They are never automatically deleted (respecting data privacy retention policy, §2 of `operations.md`). |

### 5.4 Product Archive & User Access

Users access their historical products through the **End User Portal** (§4.4 MCP tools, `autoinfo portal` CLI command):

| Access Type | Scope | Implementation |
|-------------|-------|----------------|
| **Recent products** | Last 30 days / last 50 products | In-memory cache or SQLite query on DeliveryLog |
| **Archive search** | All products + aged flag | SQLite FTS5 on product metadata (domain, topic, generated_at range) |
| **Product download** | Single product content | Fetch original rendered output from `outputs/` directory |
| **Bulk export** | All products for a user (GDPR) | ZIP with all product content + metadata; `export_kb(user_id=…)` |

**Storage model**: Each generated product creates a file at `outputs/<domain>/<product_type>/<user_id>/<generated_at>.<format>`. The file path is stored in DeliveryLog for retrieval.

### 5.5 Engagement & Churn Signals

While v1 does not implement explicit consumption tracking for all channels, the following signals are available:

| Signal | Source | Reliability |
|--------|--------|-------------|
| **Delivery success** | DeliveryLog (all channels) | ✅ High |
| **Email open rate** | SMTP tracking pixel (if configured) | ⚠️ Medium (privacy, ad-block) |
| **Portal login frequency** | `autoinfo portal` CLI usage logs | ⚠️ Medium (CLI-only) |
| **Subscription pause/cancel** | Subscription state machine | ✅ High (explicit user action) |
| **Missing quiet hours override** | `only_urgent=False` + no manual check | 🔮 Low (inferred disengagement) |

**v1 Retention Strategy**: When `list_end_users(status="trial")` returns users approaching trial end, operator manually assesses engagement using available signals above. No automated churn prediction (deferred to v2+ LTV modelling).

### 5.6 Product Lifecycle MCP Tools

| Tool | Description |
|------|-------------|
| `get_product_lifecycle(product_id)` | Return current state + state transition timestamps for a product |
| `list_user_products(user_id, status, limit)` | Products by lifecycle state for a user |
| `regenerate_product(product_id)` | Force regeneration of an existing product (respects current KB state) |
| `archive_product(product_id)` | Manually move product to archived state |
| `get_engagement_metrics(user_id, period)` | Aggregate delivery + consumption signals for a user over period |

### 5.7 v1 Implementation Constraints

| Concern | Decision |
|---------|----------|
| **Product state machine** | File-based tracking via frontmatter-style metadata in product output files. No separate product_instances table in v1. |
| **Consumption tracking** | Only channels that provide explicit read receipts (Telegram — message read count; Webhook — HTTP 200 with acknowledgement). Email and most other channels skip consumption tracking. |
| **Archive retention** | Products never deleted in v1. `aged` flag set based on domain TTL. Operator can manually archive. |
| **Bulk export** | `export_kb(format="zip", user_id=…)` exports all user products + metadata file. |
| **Product ↔ KB entry linking** | Product metadata includes `kb_entry_ids: [list of entry UUIDs]` for traceability. |

---

## 6. Consumption Tracking (CD-011, CD-018)

> **Gap-filled 2026-07-27**: Consumption tracking is documented as a gap ([CD-011](cross-dimensional-catalog.md#cd-011-consumption-tracking-read-receipts--engagement) — never designed; [CD-018](cross-dimensional-catalog.md#cd-018-consumption-tracking-mcp-tools) — spec'd not implemented). This section defines the consumption tracking model, event types, and MCP tools needed to close the consumption gap.
>
> ✅ **Implemented 2026-08-04**: `ConsumptionEvent` (view/open/click) auto-recorded on delivery. SQLite store at `src/autoinfo/consumption.py`. The entire A6 Consumption stage is 🔴 blank in the cross-dimensional matrix.

### 6.1 ConsumptionEvent Model

```python
@dataclass
class ConsumptionEvent:
    """A single consumption signal from an end user interacting with a delivered product."""
    event_id: str                        # "cevt_{uuid8}"
    product_id: str                      # FK to Product (generated instance)
    user_id: str                         # FK to UserProfile
    subscription_id: str                 # FK to Subscription
    delivery_log_id: str                 # FK to DeliveryLog (the delivery this consumption relates to)
    event_type: ConsumptionEventType
    timestamp: str                       # ISO 8601
    channel: str                         # Channel through which consumption occurred
    metadata: dict[str, Any] = field(default_factory=dict)  # channel-specific data
    trace_id: str = ""                   # Links to collection trace

class ConsumptionEventType(Enum):
    """Types of consumption events."""
    DELIVERED = "delivered"              # Product successfully delivered (already in DeliveryLog)
    OPENED = "opened"                    # User opened/accessed the product (read receipt)
    READ_COMPLETE = "read_complete"      # User scrolled to end / spent sufficient time
    CLICKED = "clicked"                  # User clicked a link within the product
    SHARED = "shared"                    # User shared the product with others
    SAVED = "saved"                      # User bookmarked/saved the product
    FEEDBACK = "feedback"                # User provided explicit feedback (rating, reaction)
    DISMISSED = "dismissed"              # User dismissed/ignored the product (negative signal)
    EXPIRED = "expired"                  # Product aged beyond consumption window
```

### 6.2 Consumption Signals by Channel

| Channel | OPENED Signal | READ_COMPLETE Signal | CLICKED Signal | Reliability |
|---------|--------------|---------------------|---------------|-------------|
| **Email (SMTP)** | Tracking pixel (if configured) | N/A (no scroll depth) | Link click tracking via redirect proxy | ⚠️ Medium (ad-block blocks pixels) |
| **Telegram** | Message read status via Bot API | N/A (no read duration) | Inline button callback | ✅ High |
| **WeChat OA** | Template message send confirmation | N/A | Menu click event | ✅ High |
| **WeChat Work** | Message read receipts (enterprise) | N/A | N/A | 🟡 Medium (enterprise-only) |
| **DingTalk** | Message read status | N/A | N/A | 🟡 Medium |
| **FeiShu/Lark** | Message read receipts | N/A | N/A | ✅ High |
| **Discord** | N/A (no read receipts) | N/A | Reaction emoji | 🔴 Low |
| **Webhook** | HTTP 200 acknowledgement | N/A | N/A (depends on consumer) | 🟡 Medium |
| **REST API** | Explicit `mark_as_read` call | Explicit `mark_as_read` | N/A | ✅ High (if consumer implements) |
| **Portal** | Page view event | Scroll depth event | Click event | ✅ High |

### 6.3 Consumption Storage Model

```
delivery_logs  ←── 1:1 ──→  consumption_events (one per DELIVERED event)
     │                                    │
     │ 1:N                                │ 1:N (OPENED, CLICKED, FEEDBACK, etc.)
     ▼                                    ▼
subscriptions                      product_instances
     │                                    │
     │ 1:N                                │ 1:1
     ▼                                    ▼
 user_profiles                       product_templates
```

### 6.4 MCP Consumption Tools (CD-018)

| Tool | Description | Parameters |
|------|-------------|------------|
| `record_consumption_event(product_id, user_id, event_type, metadata)` | Record a consumption signal | Required: product_id, user_id, event_type. Optional: metadata |
| `get_consumption_history(user_id, period, event_type)` | Query consumption events for a user | Required: user_id. Optional: period, event_type filter |
| `get_product_consumption_stats(product_id)` | Aggregate consumption stats for a product | Required: product_id |
| `get_engagement_summary(user_id, period)` | Aggregated engagement metrics (open rate, click rate, read rate) | Required: user_id. Optional: period |
| `get_channel_consumption_stats(channel, period)` | Per-channel consumption KPIs | Required: channel. Optional: period |

### 6.5 Engagement Metrics

| Metric | Formula | P0/P1 |
|--------|---------|-------|
| **Delivery Rate** | `delivered / attempted` | 🔴 P0 |
| **Open Rate** | `opened / delivered` | 🔴 P0 |
| **Click Rate** | `clicked / opened` | 🟡 P1 |
| **Read Completion Rate** | `read_complete / opened` | 🟡 P1 |
| **Feedback Rate** | `feedback / delivered` | 🟡 P1 |
| **Dismissal Rate** | `dismissed / delivered` | 🟡 P1 |
| **Engagement Score** | Weighted composite (configurable weights) | 🟡 P1 |

> **Implementation status (2026-07-27)**: Zero consumption tracking code exists. No `ConsumptionEvent` model, no consumption event storage, no MCP tools for engagement. The entire A6 Consumption stage is 🔴 blank. This section serves as the implementation specification.
>
> ✅ **Implemented 2026-08-04**: `ConsumptionEvent` is now auto-recorded on digest/report delivery (view/open/click events). SQLite-backed store exists at `src/autoinfo/consumption.py`. See `get_enduser_usage` MCP tool for consumption queries.

---

## 7. Delivery Channel Health Monitoring (CD-007)

> **Gap-filled 2026-07-27**: Channel health monitoring is a never-designed gap ([CD-007](cross-dimensional-catalog.md#cd-007-delivery-channel-health-monitoring)). Currently, if a delivery channel (Telegram Bot, WeChat OA, DingTalk, etc.) fails or degrades, delivery silently retries without alerting. This section defines the health monitoring model.
>
> ✅ **Implemented 2026-08-04**: `get_channel_health` MCP tool now reports health + latency for all 13 delivery channels (smtp, webhook, rest_api, file_export, discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss, social_publish, push).

### 7.1 Channel Health Model

```python
@dataclass
class ChannelHealth:
    """Health status for a single delivery channel."""
    channel_type: str                    # "smtp", "telegram", "wechat_oa", etc. — one of 13 canonical channels
    status: ChannelHealthStatus
    health_score: float                  # 0.0–100.0 (composite score)
    
    # Recent performance
    delivery_count_24h: int = 0
    success_count_24h: int = 0
    failure_count_24h: int = 0
    success_rate_24h: float = 0.0        # success_count / delivery_count
    
    # Latency (milliseconds)
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Error breakdown
    last_error: str = ""
    last_error_at: str = ""
    consecutive_failures: int = 0
    
    # Config
    failure_threshold: int = 5           # Consecutive failures before auto-suspend
    latency_threshold_ms: float = 30000.0  # P95 latency above which channel is degraded
    suspended: bool = False
    suspended_at: str = ""
    suspended_reason: str = ""

class ChannelHealthStatus(Enum):
    HEALTHY = "healthy"                  # Green — all KPIs normal
    DEGRADED = "degraded"               # Yellow — elevated latency or intermittent failures
    FAILING = "failing"                  # Orange — approaching failure threshold
    SUSPENDED = "suspended"             # Red — auto-suspended due to threshold breach
    DISABLED = "disabled"               # Gray — manually disabled by operator
    UNKNOWN = "unknown"                  # No recent delivery data
```

### 7.2 Auto-Suspend Mechanism

When a channel exceeds its `failure_threshold` of consecutive failures or `latency_threshold_ms` is breached for > 5 minutes:

1. **Detection**: `DeliveryLog` records each failure. `ChannelHealth` is updated on each delivery attempt.
2. **Threshold breach**: After `consecutive_failures >= failure_threshold`, channel status transitions to `SUSPENDED`.
3. **Notification**: System alert dispatched (via [CD-006](cross-dimensional-catalog.md#cd-006-unified-notification-framework)) — "Channel `{channel_type}` auto-suspended after {N} consecutive failures."
4. **Fallback**: Active subscriptions using the suspended channel are **auto-routed to fallback channel** (email is the mandatory universal fallback — see §2.3).
5. **Operator action**: Operator can manually override suspension: `resume_channel(channel_type)` or `force_deliver(subscription_id, channel_type)`.
6. **Auto-recovery**: Channel is periodically probed (every 5 minutes). If probe succeeds, health score recovers; after 3 consecutive successful probes, channel auto-unsuspends and resumes deliveries.

### 7.3 MCP Health Monitoring Tools

| Tool | Description |
|------|-------------|
| `get_channel_health(channel_type)` | Health status and metrics for a specific channel |
| `list_channel_health()` | Health summary for all channels |
| `get_channel_health_history(channel_type, period)` | Historical health data (score, latency, failures over time) |
| `suspend_channel(channel_type, reason)` | Manually suspend a delivery channel |
| `resume_channel(channel_type)` | Manually resume a suspended channel |
| `get_delivery_sla_report(period)` | SLA compliance per channel (P0 ≤5min, P1 ≤30min, P2 ≤2hr) |

### 7.4 Health Score Calculation

```
HealthScore = (SuccessRateWeight × SuccessRate) 
            + (LatencyWeight × LatencyScore) 
            + (ConsecutiveFailurePenalty × -ConsecutiveFailures)

Where:
- SuccessRate = success_count_24h / delivery_count_24h (clamped to [0, 1])
- LatencyScore = max(0, 1 - p95_latency_ms / latency_threshold_ms) (clamped to [0, 1])
- ConsecutiveFailurePenalty = 10 points per failure

Default weights: SuccessRateWeight=60, LatencyWeight=30, ConsecutiveFailurePenalty=10
Health score clamped to [0, 100].
```

> **SLA Targets** (from §2.3): SMTP < 30s, Telegram/DingTalk/FeiShu < 5s, Discord/Webhook < 10s, REST API < 5s, File Export < 1s, RSS < 30s, Social Publish < 10s.

> **Implementation status (2026-07-27)**: No channel health monitoring exists. DeliveryLog records per-item delivery results but there is no aggregate channel health view, no auto-suspend mechanism, and no health monitoring MCP tools. See [CD-007](cross-dimensional-catalog.md#cd-007-delivery-channel-health-monitoring).
>
> ✅ **Implemented 2026-08-04**: `get_channel_health` now reports `{healthy, latency_ms, error}` per channel. The auto-suspend mechanism and historical health tracking remain spec-only; the core monitoring surface is shipped.

---

## 8. Product Preview Workflow (CD-008)

> **Gap-filled 2026-07-27**: Product preview is documented as a gap ([CD-008](cross-dimensional-catalog.md#cd-008-pre-delivery-product-preview)) — there is no way to preview a product before delivery. End users receive products without preview. Agents/directors cannot QA before send.

### 8.1 Preview Generation Pipeline

```
1. Agent/director calls preview_product(product_id, template_vars, format)
2. Fetch relevant 02-Draft entries (same as final generation)
3. Render template → target format (Markdown/HTML/JSON)
4. Apply delivery gates D1-D3 (completeness, format, freshness) — soft mode (warn but don't block)
5. Return preview with metadata:
   - entry_count, estimated_read_time, quality_gate_results
   - "This is a preview. Not yet delivered."
6. Preview is NOT stored in DeliveryLog — it's transient
```

### 8.2 MCP Preview Tools

| Tool | Description |
|------|-------------|
| `preview_product(product_id, template_vars, format)` | Generate preview of a product before delivery. Returns rendered content + metadata. |
| `preview_delivery(product_id, channel_type, recipient)` | Preview how a product will render in a specific channel (e.g., preview Telegram MarkdownV2 formatting, preview email HTML) |
| `list_previewable_products(user_id)` | List products that this user is subscribed to and can preview |
| `approve_delivery(product_id)` | After preview, approve product for delivery (transitions product state if applicable — see §5.0) |
| `reject_delivery(product_id, reason)` | After preview, reject product with reason (back to draft/needs-revision) |

### 8.3 Preview → Approve → Deliver Workflow

```
┌─────────────┐     preview_product()     ┌──────────────┐
│   Product   │ ────────────────────────→ │   PREVIEW    │
│  (DRAFT or  │                           │  (transient) │
│   ACTIVE)   │                           └──────┬───────┘
└─────────────┘                                  │
      ▲                                          │
      │                           ┌───────────────┴───────────────┐
      │                           │                               │
      │                    approve_delivery()           reject_delivery(reason)
      │                           │                               │
      │                           ▼                               ▼
      │                    ┌──────────────┐              ┌──────────────┐
      │                    │  APPROVED    │              │   REJECTED   │
      │                    │  → DELIVER   │              │ → back to    │
      │                    └──────────────┘              │    DRAFT     │
      │                                                  └──────────────┘
      │                                                         │
      └─────────────────────────────────────────────────────────┘
                    (fix issues, re-preview)
```

### 8.4 Preview Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **Agent preview** | Agent receives rendered product via MCP `preview_product()`. Inspects content, checks gate results, approves or rejects. | B2 Direct User — QA before scheduled delivery |
| **Director preview** | Human director uses CLI `autoinfo output preview --product-id X` to see rendered content in terminal. | B3 Director User — manual QA |
| **End-user preview** | End user receives "preview of upcoming digest" via portal/email. "This is a preview of your Monday digest. [View Full Digest]" | B1 End User — discover what they'll receive (trial conversion tool) |
| **Channel preview** | Preview product exactly as it would render in Telegram, DingTalk, email HTML, etc. Detects formatting issues before delivery. | B2/B3 — channel-specific QA |

> **Implementation status (2026-07-27)**: No preview workflow exists. `generate_digest()` and other output tools produce final products directly with no preview step. The existing output generation pipeline (see §1.2) must be refactored to support a "preview mode" that renders without recording a DeliveryLog entry. See [CD-008](cross-dimensional-catalog.md#cd-008-pre-delivery-product-preview).

---

## 9. Delivery Schema Enforcement (CD-039)

> **Gap-filled 2026-07-27**: Delivery schema enforcement is an architecture gap ([CD-039](cross-dimensional-catalog.md#cd-039-no-delivery-schema-enforcement)). Currently, delivery channels receive products with no schema validation — a product expected to have certain fields can be sent without them. Each channel adapter handles formatting independently with no shared contract.

### 9.1 Per-Channel Format Contracts

Each delivery channel requires a specific format schema. The enforcement layer validates that a product meets the channel's schema *before* dispatch.

```python
@dataclass
class ChannelFormatContract:
    """Schema contract that a product must satisfy for a given channel."""
    channel_type: str
    required_fields: list[str]           # Fields that MUST be present in the product
    optional_fields: list[str]           # Fields that MAY be present
    field_types: dict[str, type]         # Expected Python types for each field
    max_content_length: int | None       # None = no limit
    supported_formats: list[str]         # "markdown", "html", "plain_text", "json"
    format_transforms: dict[str, str]    # field → transform function name
```

### 9.2 Channel Format Contracts Table

| Channel | Required Fields | Max Length | Supported Formats | Special Constraints |
|---------|----------------|------------|-------------------|---------------------|
| **Email (SMTP)** | `subject`, `body_html`, `body_text` | 100KB (body) | HTML + Plain Text | Must have text fallback for HTML. Subject ≤ 78 chars. |
| **Telegram** | `text` | 4096 chars | MarkdownV2 / HTML | No nested formatting in MarkdownV2. Entities must be valid. |
| **WeChat OA** | `template_id`, `data` (dict) | Template-dependent | JSON (template data) | Template ID must match WeChat OA template. Field names must match template params. |
| **WeChat Work** | `content` (Markdown), optional `msg_type` | 2048 chars | Markdown | @mentions must use valid userid format. |
| **DingTalk** | `title`, `text` | 20000 chars (Markdown) | Markdown | Title ≤ 256 chars. @mentions use mobile numbers. |
| **FeiShu/Lark** | `title`, `content` | 30000 chars | Markdown (FeiShu) / Rich Text (Lark) | Title optional in some contexts. |
| **Discord** | `content` or `embeds` | 2000 chars (content) / 6000 chars (embed) | Markdown (limited subset) | Embeds have strict field limits. Color must be decimal. |
| **Webhook** | `payload` (any JSON-serializable) | Configurable | JSON | HMAC signature if configured. Consumer defines schema. |
| **REST API** | Endpoint-specific | Endpoint-specific | JSON | API key in header. Consumer defines schema. |
| **Export** | File content + filename | Disk limit | Any (as-is) | Must be valid file format for extension. |

### 9.3 Validation Pipeline

```
Product → SchemaValidator.validate(product, channel_contract)
           │
           ├── 1. Required field check: all required_fields present?
           │        → Missing fields → ValidationError(reason="missing_fields", fields=[...])
           │
           ├── 2. Type check: each field matches expected type?
           │        → Type mismatch → ValidationError(reason="type_mismatch", field=..., expected=..., actual=...)
           │
           ├── 3. Content length check: within max_content_length?
           │        → Exceeded → ValidationError(reason="content_too_long", current=..., max=...)
           │
           ├── 4. Format transform: apply format_transforms (e.g., Markdown → MarkdownV2 for Telegram)
           │
           └── 5. Channel-specific validation: per-channel rules
                    → Violation → ValidationError(reason="channel_rule", rule=...)
           │
           ▼
      ✅ Validated product → dispatch
      ❌ ValidationError → return to caller with reason (do NOT retry — schema errors don't self-heal)
```

### 9.4 Schema Enforcement MCP Tools

| Tool | Description |
|------|-------------|
| `get_channel_format_contract(channel_type)` | Return the format contract (required fields, types, limits) for a channel |
| `validate_product_for_channel(product_id, channel_type)` | Validate a product against a channel's format contract — returns pass/fail + details |
| `list_channel_format_contracts()` | List all channel format contracts |
| `test_channel_format(channel_type, sample_payload)` | Validate a sample payload against a channel contract |

> **Implementation status (2026-07-27)**: No schema enforcement layer exists. Channel adapters handle formatting independently in their `deliver()` methods with no shared validation contract. `ProductTemplate` has fields but no channel-aware validation. See [CD-039](cross-dimensional-catalog.md#cd-039-no-delivery-schema-enforcement).

---

## 10. Consumption Feedback Loop (CD-040)

> **Gap-filled 2026-07-27**: The consumption feedback loop is an architecture gap ([CD-040](cross-dimensional-catalog.md#cd-040-no-end-user-consumption-loop)). The entire pipeline ends at delivery — there is no feedback from end-user consumption back into product generation. The system delivers but does not learn.

### 10.1 Feedback Loop Architecture

```
                    ┌─────────────────────────────────────────┐
                    │           CONSUMPTION SIGNALS            │
                    │  (open rate, click rate, read time,     │
                    │   feedback, shares, dismissals)          │
                    └──────────────┬──────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    FEEDBACK ENGINE                           │
│                                                              │
│  1. Collect consumption signals → ConsumptionEvent store     │
│  2. Aggregate per: user, product, topic, channel, domain     │
│  3. Compute engagement scores (see §6.5)                     │
│  4. Generate adaptation signals                              │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│                   ADAPTATION RULES                           │
│                                                              │
│  Rule 1: Topic re-weighting                                 │
│    High engagement on topic X → boost X in next digest       │
│    Low engagement on topic Y → deprioritize Y                │
│                                                              │
│  Rule 2: Content length adaptation                          │
│    Low read completion rate → shorter digests                │
│    High read completion → maintain or increase length        │
│                                                              │
│  Rule 3: Format preference learning                         │
│    User consistently opens HTML but ignores Markdown         │
│    → auto-switch preferred format for that user              │
│                                                              │
│  Rule 4: Timing optimization                                │
│    Cluster open timestamps → find optimal delivery window    │
│    → adjust Subscription.schedule per user                   │
│                                                              │
│  Rule 5: Channel preference                                 │
│    User engages on Telegram but ignores email                │
│    → recommend/prefer Telegram channel                       │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│              PRODUCT GENERATION (A4)                         │
│                                                              │
│  - Template selection influenced by engagement history       │
│  - Entry selection re-weighted by topic affinity             │
│  - Format auto-selected per user preference                  │
│  - Delivery timing optimized per user's active window        │
│  - Channel auto-selected per user's engagement profile       │
└──────────────────────────────────────────────────────────────┘
```

### 10.2 Feedback-Driven Product Adaptation

| Adaptation | Trigger Signal | Action | Scope |
|-----------|---------------|--------|-------|
| **Topic boost** | Topic X has >70% open rate for user | Increase weight of Topic X entries in next digest by 1.5× | Per-user |
| **Topic suppression** | Topic Y has <20% open rate for 3 consecutive deliveries | Move Topic Y to "low priority" in digest; user can opt back in | Per-user |
| **Content length** | <30% read completion rate for digests >5 entries | Reduce `max_entries` to 3; gradually increase back if completion improves | Per-user |
| **Format switch** | HTML open rate > 2× Markdown open rate for 5+ consecutive deliveries | Switch preferred format to HTML; notify user of change | Per-user |
| **Timing shift** | Open timestamps cluster at 07:30-08:00 but digest sent at 12:00 | Shift schedule to 07:00 delivery window | Per-user |
| **Channel switch** | Telegram engagement > 3× Email engagement for 1 month | Recommend Telegram as primary; keep email as fallback | Per-user |

### 10.3 Feedback Data Flow

```
Subscriptions ──→ Schedule Trigger ──→ Product Generation
                                          │
                                          ▼
                                     Product Instance
                                          │
                                    ┌─────┴─────┐
                                    ▼           ▼
                              DeliveryLog   ConsumptionEvent
                                    │           │
                                    └─────┬─────┘
                                          │
                                          ▼
                                    EngagementStore
                                    (aggregated metrics)
                                          │
                                          ▼
                                    FeedbackEngine
                                    (adaptation rules)
                                          │
                                          ▼
                              ┌───────────────────┐
                              │  Updated:          │
                              │  - Topic weights   │
                              │  - Schedule times  │
                              │  - Format prefs    │
                              │  - Channel prefs   │
                              │  - Content length  │
                              └───────────────────┘
                                          │
                                          ▼
                              Next Product Generation
                              (uses adapted parameters)
```

### 10.4 MCP Feedback Tools

| Tool | Description |
|------|-------------|
| `get_adaptation_signals(user_id)` | Current adaptation signals active for a user (topic weights, format pref, timing, channel pref) |
| `apply_adaptation(user_id, rule_name, params)` | Manually apply an adaptation rule — operator/director override |
| `reset_adaptations(user_id)` | Reset all learned adaptations for a user — back to defaults |
| `get_adaptation_history(user_id, period)` | History of adaptations applied and their effect on engagement |
| `suggest_topic_weights(user_id)` | LLM-assisted suggestion for topic weighting based on engagement patterns |

### 10.5 Feedback Loop Constraints

| Constraint | Rule |
|-----------|------|
| **Never remove topics silently** | Low engagement → deprioritize, never delete. User must have explicit control to unsubscribe from topics. |
| **Opt-out for all adaptations** | Every adaptation must have an opt-out flag. User can say "don't adjust my schedule" or "don't change topics." |
| **Cold start** | New users start with default weights. No adaptation data = no modification. First 5 deliveries are "learning period" — collect data, apply adaptations starting at delivery #6. |
| **Transparency** | User preferences page shows current adaptations with explanation: "We noticed you read IVF topics most. We're showing more IVF content." |
| **Director override** | Director can lock certain parameters (e.g., "don't change schedule for enterprise users"). |

> **Implementation status (2026-07-27)**: Zero feedback loop code. The pipeline is entirely unidirectional (collect → extract → generate → deliver). No consumption data feeds back into product generation. This is a foundational architecture gap that requires all of §6 (Consumption Tracking) to be implemented first. See [CD-040](cross-dimensional-catalog.md#cd-040-no-end-user-consumption-loop).

---

## 11. B1 Lifecycle Integration

> **Root spec:** `docs/dev/specs/user-lifecycle-definition.md` §2 (B1 End User Lifecycle) — that is the canonical home for B1 stage definitions, lifecycle state machine, and subscription config model. **This section covers delivery-specific aspects only**: referral flow delivery mechanics, onboarding delivery actions, NL→Config pipeline delivery integration, and reactivation retention windows. §11.4 retention windows (Free 30d / Premium 90d / Enterprise 180d) remain authoritative for the delivery spec.
> **F-expectations:** F65 (B1.1 Discovery), F66 (B1.3 Onboarding), F67 (B1.5 Config Modification), F68 (B1.7 Reactivation)
> **Associated data models:** `docs/dev/specs/data-models.md` §4.9-4.13

This section maps B1 lifecycle stages (from the root spec) to delivery mechanisms — delivery channels, DeliveryLog, retry chain, SLA — only. The root spec owns lifecycle stage definitions and the B1 state machine.

### 11.1 B1.1 Discovery & Referral

The B1 lifecycle begins when a potential customer discovers AutoInfo. This is primarily a product catalog / storefront function (see F64), but the delivery system plays a supporting role:

| Component | Delivery Role | Status |
|-----------|--------------|--------|
| **Product catalog** | Lists available products (digest, report, tutorial, presentation) with sample outputs, pricing tiers, and subscribe CTA | ❌ Not implemented (F64) |
| **Referral mechanism** | Existing B1 generates referral link; referred B1 receives a welcome product (sample digest) as part of discovery | ❌ Not implemented (F65) |
| **Trial activation** | Upon signup (free tier), delivery system queues the onboarding sequence (§11.2) | ❌ Requires subscription CRUD (F36) + onboarding (F66) |

**Delivery requirement**: When a product catalog/storefront is built, product listing MUST include:
- Product name, description, domain, format, cadence
- Sample output (Markdown/HTML preview)
- Pricing tier (free/premium/enterprise)
- Subscribe/Try button that creates a Subscription record with `tier=free` (trial)

**Referral flow**:
```
Existing B1 → generates referral link
  → shares with potential B1
  → potential B1 clicks link → sees product catalog with referral code attached
  → subscribes → new B1's Subscription.referred_by = existing B1's id
  → delivery system records referral for reward processing
```

### 11.2 B1.3 Onboarding

This is the critical "aha moment" — the first product delivery that determines whether B1 stays or churns.

| Stage | Trigger | Delivery Action | Config |
|-------|---------|----------------|--------|
| **Onboarding trigger** | Subscription created with `tier=free` or `tier=premium` | Immediately queue first delivery regardless of frequency schedule | System-wide default: immediate |
| **First delivery** | OTrigger → Agent generates first product (digest or welcome briefing) | Generate using B1's subscription config (domains, topics, channels). If no collected items yet, generate a **sample digest** from demo domain data. | `onboarding.first_delivery.content: "live" | "sample"` |
| **Preference verification** | After first delivery, Agent prompts B1: "Are these the right topics? Too many/few items? Right channels?" | B1 responds in NL → Agent parses → updates subscription config. This is the **config refinement loop**. | Loop continues until B1 confirms satisfaction or max 3 rounds. |
| **Cross-product introduction** | After preference confirmed | Agent generates a second product (different type — e.g., if first was digest, second is report) to demonstrate breadth. Deliver 24h after confirmation. | `onboarding.cross_product.introduce: ["digest", "report"]` |
| **Channel delivery confirmation** | Agent sends test message to each configured channel | "This is a test delivery from AutoInfo. You're receiving this via [channel]." B1 confirms receipt. | Verify all channels work before marking onboarding complete. |
| **Onboarding complete** | All above steps done | B1 transitions to normal Consume phase. Regular schedule takes effect. | `onboarding.status: "complete"` |

**Config refinement loop** (critical for NL→Config quality):
```
B1: "这个 Digest 太长了，我只要每个 topic 3 篇文章"
  → Agent: "Updated: max_items_per_topic=3. I'll reduce the next digest to 3 articles per topic. Anything else?"
  → B1: "可以，再把频率改成每周一次"
  → Agent: "Updated: frequency=weekly. Your next digest will arrive every Monday."
  → B1 confirms → onboarding proceeds
```

**Metrics**: 
- First delivery → preference verification completion rate
- Config refinement rounds (target: ≤2 rounds)
- Cross-product introduction → upgrade conversion rate
- Onboarding → 30-day retention correlation

### 11.3 B1.5 Config Modification (NL→Config Pipeline)

When B1 modifies their subscription config after onboarding, the NL→Config pipeline handles it:

**Pipeline flow**:
```
B1: "帮我把金融资讯加到订阅里"
  → Agent receives NL utterance
  → LLM parses intent: {action: "add", target: "domains", value: ["financial-intelligence"]}
  → Agent validates against B1's tier (does the tier support this domain?)
  → Classification: billing-affecting? No (domain change is non-billing per lifecycle-definition §2.4)
  → Apply immediately: subscription.domains += ["financial-intelligence"]
  → Next pipeline run uses updated config
  → Agent confirms to B1: "已添加金融资讯到你的订阅，下次收集周期生效。"
```

**Billing vs non-billing rules** (authoritative source: `docs/dev/specs/user-lifecycle-definition.md` §2.4 — this is a delivery-specific summary only):

| Change Type | Examples | Effective | Action |
|-------------|----------|-----------|--------|
| **Non-billing** | Add/remove domains, change channels, adjust frequency, toggle content preference | Immediate (next pipeline run) | Update subscription config, no billing interaction |
| **Billing-affecting** | Tier upgrade/downgrade | Price → next billing cycle; Features → immediate | Update subscription.access_level immediately; price change queued to next billing cycle |

**Config change audit trail**:
```
{
  "nl_intent": "帮我把金融资讯加到订阅里",
  "parsed_config": {"domains": {"action": "add", "value": ["financial-intelligence"]}},
  "change_type": "non-billing",
  "applied_immediately": true,
  "previous_config": {...},
  "updated_config": {...},
  "confirmed_by": "B1_NL",
  "timestamp": "..."
}
```

### 11.4 B1.7 Reactivation

When a churned B1 returns within the retention window:

**Reactivation flow**:
```
Churned B1 returns (via product catalog / referral / direct link)
  → Agent checks: is B1's data within retention window?
  → If yes: restore subscription from pre-churn config snapshot
  → If config snapshot unavailable: Agent asks B1 to reconfigure (quick mode: "之前的配置找不到了，重新说一下你的需求？")
  → Data continuity: B1's KB entries (raw/draft/wiki) are restored from soft-delete
  → Delivery resumes from next schedule tick
  → Agent sends welcome-back message: "欢迎回来！你的订阅已恢复。"
```

**Retention windows** (per tier, from operations.md §2.5):

| Tier | Retention Window | Config Snapshot | Data Continuity |
|------|-----------------|-----------------|-----------------|
| Free | 30 days | Full config preserved | KB entries archived |
| Premium | 90 days | Full config + delivery history | Full data restore |
| Enterprise | 180 days | Full config + history + delivery logs | Full + SLA continuity |

**Reactivation vs new subscription**:
- Reactivation: preserves history, preferences, config (within retention window). Lower CAC but higher churn risk (churned once, may churn again).
- New subscription: no history, fresh config. Higher CAC, unknown churn risk.

**Reactivation delivery action**: Upon reactivation, Agent generates a "since you were away" digest — summary of what was collected during the gap period. This is delivered immediately (not on schedule) as a recovery product.
