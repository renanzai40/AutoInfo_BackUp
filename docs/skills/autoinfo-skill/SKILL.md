# AutoInfo MCP Operation Skill

Use this skill when the task involves operating, configuring, or querying
the AutoInfo information tracking platform via its MCP tools.

## Prerequisites

- AutoInfo MCP server must be running (`python -m autoinfo.mcp.server`)
- MCP tools auto-discovered via protocol — no manual config needed
- Director-user communicates intent in natural language

## Operating Model

```
Human (director) ──NL──> You ──MCP tools──> AutoInfo Server
                             │
                             ▼
                      End User (paying customer)
                         receives products via
                      delivery channels (SMTP, webhook,
                      Telegram, WeChat, DingTalk, FeiShu, Discord)
```

You are the interface. The human tells you what they want tracked, and
you translate that into AutoInfo tool calls. AutoInfo delivers finished
products (digests, reports, alerts, feeds) to End Users.

## Tool Discovery

Not sure what tools exist? Use MCP protocol discovery.
Full MCP tool catalog: see **AGENTS.md → Tool Discovery Guidance** (146 tools, 35 categories).

## Common Workflows

> Common workflows (track-topic flow, search, system health, LLM configuration, error handling, collection diff): see **AGENTS.md → Common Patterns**. The workflows below cover operations specific to the operator skill.

### Set up tracking for a new domain
```
list_domains() → see available domains
get_domain_schema("medical-research") → see extraction fields
activate_domain("medical-research") → load demo config
```

### Add a custom domain from scratch
```
add_domain(name="my-custom-domain", description="...")
list_available_platforms() → discover supported source types
add_source(domain="my-custom-domain", name="my-rss", type="rss", url="...")
add_topic(domain="my-custom-domain", name="My Topic", keywords=["kw1", "kw2"])
collect_sources(domain="my-custom-domain")
```

### Preview before collecting
```
collect_sources(domain="medical-research", dry_run=true)
→ Returns estimated item count without consuming API quota
```

### Generate and deliver output
```
generate_digest(domain="medical-research", period="week")
generate_digest(domain="medical-research", period="week", product="magazine-digest")
  → per-title clustered digest product (digest-path routing)
generate_report(domain="medical-research", format="pdf", topic="IVF breakthroughs")
generate_report(domain="medical-research", topic="IVF breakthroughs", product="premium-briefing")
generate_report(domain="medical-research", topic="Q3 M&A review", product="enterprise-briefing")
generate_presentation(domain="medical-research", topic="Latest Findings")
send_email_digest(to="user@example.com", subject="Weekly Digest", body=digest)
```
`product=` selects a differentiated product template (8 total: digest, report,
tutorial, presentation, premium-briefing, column, magazine-digest,
enterprise-briefing). `premium-briefing` / `enterprise-briefing` are report-path
products with per-item `implications` / `risks` / `action_required` /
`key_metrics` analysis; `magazine-digest` is a digest-path product. The analysis
persists to the KB entries' `custom_fields["product_analysis"]` and is retrievable
via search faceting (below).

### Compare changes over time
```
get_collection_stats(period="week")
get_collection_diff(domain="medical-research", since_collection_id="...")
```

### Configure quality gates
```
get_gate_config(domain="medical-research") → current gate settings
set_gate_config(domain="medical-research",
  gates={"G3": {"action": "pass", "threshold": 50}}) → customize
```

### Manage alert rules
```
add_alert_rule(domain="medical-research", name="source-down",
  condition="source_health == error", action="email")
get_alert_rules(domain="medical-research") → current rules
remove_alert_rule(domain="medical-research", rule_id="...")
```

### End User lifecycle management

**Create a new End User (starts in trial):**
```
send_to_enduser(name="Acme Corp", email="admin@acme.com",
  tier="pro", delivery_preferences={"channels": ["email", "webhook"]})
```

**Manage delivery preferences:**
```
update_preferences(user_id="usr_xxx",
  delivery_preferences={"channels": ["telegram", "email"],
    "quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "Asia/Shanghai"}})
```

**Check subscription status:**
```
get_subscription_status(end_user_id="usr_xxx")
```

**View cost vs. budget:**
```
get_billing_summary(user_id="usr_xxx", period="month")
cost_dashboard(period="month")
cost_allocation(domain="medical-research", strategy="usage-based")
```

**Trace a delivery issue:**
```
trace_item(trace_id="uuid-xxx") → full pipeline history
```

**GDPR data actions:**
```
export_user_data(user_id="usr_xxx") → full data export
soft_delete_entry(entry_id="kb_xxx") → mark entry deleted
restore_entry(entry_id="kb_xxx") → restore soft-deleted entry
```

### Manage products & delivery
```
list_products(domain="medical-research", type="processed")
get_product(domain="medical-research", product_id="prod_xxx")
```

### Set up webhook notification
```
set_domain_webhooks(domain="medical-research",
  webhooks=[{"url": "https://example.com/hook", "events": ["item.collected"]}])
get_domain_webhooks(domain="medical-research")
```

### Schedule recurring collection
```
add_schedule(domain="medical-research", cron="0 8 * * 1", topic="IVF breakthroughs")
list_schedules()
run_schedules() → manual trigger
```

### Classify content by CEFR level
```
classify_cefr(text="The mitochondria is the powerhouse of the cell.", language="en")
→ returns {"level": "B2", "confidence": 0.87}
```

### Custom field extraction
```
extract_fields(domain="medical-research", text="...",
  schema={"fields": [{"name": "dosage", "type": "string"}]})
get_extraction(extraction_id="ext_xxx")
```

### KB versioning & history
```
get_entry_history(entry_id="kb_xxx") → full version history
restore_entry_version(entry_id="kb_xxx", version=2) → rollback
```

### KB import
```
import_kb(domain="medical-research", file_path="/path/to/doc.pdf", format="pdf")
```

### View billing summary
```
get_billing_summary(user_id="usr_xxx", period="month")
→ returns total spend, per-model costs, budget status
```

### Monitor active deliveries
```
list_active_deliveries()
→ returns in-flight deliveries with status and retry info
get_delivery_log(subscription_id="sub_xxx", period="week")
→ returns delivery history with SLA compliance metrics
```

### Manage knowledge lifecycle
```
# Merge duplicate entries
find_similar_items(domain="medical-research", query="embryo", threshold=0.85)
merge_items(primary_id="kb_001", secondary_ids=["kb_002"], mode="llm")

# Check domain freshness & decay
get_domain_decay(domain="medical-research")
calculate_freshness_score(entry_id="kb_001")
mark_stale(entry_id="kb_001")

# Compare versions
compare_versions(entry_id="kb_001", v1="1", v2="2")
```

### Use Agent Callbacks (push delivery)
```
set_agent_callback(url="https://my-agent.example.com/callback",
  events=["new_digest", "new_report"])
list_agent_callbacks()
remove_agent_callback(callback_id="cb_xxx")
```
Pushes deliver a canonical envelope `{event, payload, schema_version: 1, trace_id,
product_id}` via a durable SQLite outbox — callbacks registered this way survive
server restarts, and failed pushes are requeued at process start.

### Run Agent-native validation
```
list_validation_scenarios() → 116 built-in scenarios (65 functional + 51 regression)
run_validation_scenario(scenario="sources-gap-closure") → {status, summary, steps}
```
Each scenario executes real MCP calls (plus real CLI subprocesses and REST HTTP
requests) and asserts on the `{success, data}` envelope. Env-gated steps report
`unconfigured` when BYOK keys are missing — never silently skipped, never
fake-passed. `llm_assert` steps run a real model call for semantic checks.
`requires_env` at scenario level (e.g. `AUTOINFO_LLM_API_KEY`, `FRED_API_KEY`,
`FINNHUB_API_KEY`) gates LLM/keyed scenarios.

### Generate differentiated product briefings
```
list_output_templates() → 8 product templates (digest, report, tutorial,
  presentation, premium-briefing, column, magazine-digest, enterprise-briefing)
generate_report(domain="medical-research", report_type="column",
  target_audience="clinician") → premium paid deep-dive column (G15-gated)
generate_report(domain="medical-research", product="premium-briefing") → tiered
  briefing with per-item implications/risks/action_required analysis
generate_report(domain="medical-research", product="enterprise-briefing") → adds
  per-item key_metrics (metric/value/source)
generate_digest(domain="medical-research", product="magazine-digest") → per-title
  clustered digest via the digest generation path
```
`report_type="column"` (B24) renders via the premium `column` ProductTemplate.
The premium-briefing / enterprise-briefing templates resolve guard-first via the
report product resolver (`_resolve_report_product_type`, mirrors the digest
resolver); magazine-digest routes through `generate_digest`'s product resolver
(D11 — digest path, not report path). All differentiated products carry per-product
LLM synthesis fields (`implications`, `risks`, `action_required`, `key_metrics`)
index-aligned with `key_findings`, persisted to the KB entries' metadata
(`custom_fields["product_analysis"]`, see `PRODUCT_TEMPLATES` in
`src/autoinfo/output/__init__.py`).

### Search KB with custom-field facets
```
search_knowledge_base(domain="medical-research", query="embryo",
  filter_custom_fields={"product_analysis.action_required": ""})
  → entries with a non-empty product_analysis.action_required (presence match)
search_knowledge_base(domain="medical-research", query="embryo",
  filter_custom_fields={"product_analysis.product": "premium-briefing"})
  → entries analyzed for a specific product (exact match)
```
`filter_custom_fields` facets on the entry `custom_fields` JSON via dot-path
(`""` = presence, non-empty = exact match; path-injection validated).

## Important Constraints

Agent constraints: see **AGENTS.md → Agent Constraints (MUST NOT)**.

## Authorization Boundaries

```
┌─────────────────────────────────────────────────────┐
│                    DIRECTOR USER (Human)              │
│  Can: promote Draft→Wiki, delete domains/sources,    │
│        purge End User data, manage API keys,         │
│        override any agent action, approve/reject     │
├─────────────────────────────────────────────────────┤
│                    DIRECT USER (You / Agent)          │
│  Can: all COLLECT/PROCESS/SEARCH/DELIVER operations, │
│        create Draft from Raw, manage End Users       │
│        (create/update/suspend/cancel, NOT purge),    │
│        soft-delete/restore KB entries, manage alerts,│
│        configure quality gates, import/export KB     │
├─────────────────────────────────────────────────────┤
│                    END USER (Paying Customer)         │
│  Can: receive products via configured channels,      │
│        manage own preferences (via portal CLI),      │
│        access own product archive, view own cost     │
│        CANNOT: operate AutoInfo directly             │
└─────────────────────────────────────────────────────┘
```
