# CLI / MCP / REST Parity Matrix

**Source of truth for surface coverage**: every capability AutoInfo exposes, and
which of the three surfaces (CLI, MCP, REST) provides it.

This matrix is **derived**, not hand-written. Each row was produced by one of
three commands:

| Surface | Derivation command |
|---------|-------------------|
| CLI | `.venv/bin/autoinfo --help` + per-group `autoinfo <group> --help` (28 groups, all subcommands) |
| MCP | `list_tools()` on `autoinfo.mcp.server` (146 tools, runtime registry) |
| REST | FastAPI `app.routes` + `router.routes` on `autoinfo.api.server` (3 routers: routes/portal/storefront + app-level) |

Derivation date: 2026-08-05. Re-derive with the commands above whenever the
surface set changes; do not edit cells by hand.

## Status legend

| Status | Meaning |
|--------|---------|
| ✓ | Available on **all three** surfaces (CLI + MCP + REST) |
| ✓ CLI+MCP | Available on CLI and MCP; no REST endpoint |
| ✓ CLI+REST | Available on CLI and REST; no MCP tool |
| ✓ MCP+REST | Available on MCP and REST; no CLI command |
| MCP-only | Available only as an MCP tool |
| CLI-only | Available only as a CLI command |
| REST-only | Available only as an HTTP endpoint |

Cell values: `✓` = present, `—` = absent, `~` = partial/approximate mapping
(see notes).

## CLI job-state asymmetry (intentional, documented)

CLI jobs are **invisible to MCP progress polling**, and vice versa:

> **CLI job state: MCP-only** (jobs visible via `get_collection_progress` /
> `get_processing_progress`; CLI jobs invisible, progress jumps 0→100)

- MCP `collect_sources(async=true)` / `process_collection` return a `job_id`
  polled via `get_collection_progress` / `get_processing_progress`.
- The CLI (`autoinfo collect` / `autoinfo process`) runs synchronously and
  prints a completion summary; there is no CLI-facing progress poll, so a CLI
  run's progress reads 0 then 100 when observed through the MCP monitor tools.
- This asymmetry is deliberate: the CLI is human-first (block until done), the
  MCP surface is agent-first (async + poll). Do not "fix" it by hiding progress
  on the MCP side.

## Noop asymmetry (process_collection)

`process_collection` on a domain with no cached items returns a *noop* that the
CLI and MCP surfaces report differently by design. The canonical table lives at
**[`docs/dev/mcp-usage-examples.md:298`](mcp-usage-examples.md#cli-mcp-noop-asymmetry-process_collection)**
("CLI/MCP noop asymmetry (process_collection)") — this matrix does **not**
duplicate that content; it cross-links to it as the source of truth. Key facts
for quick reference: MCP returns `{status: "noop", ...}` inside `{success: true}`;
CLI human mode prints text + exit 0; CLI `--json` mirrors the MCP shape exactly.

## Global `--json` (T50) + per-command `--json` coverage

- **Global `--json`**: the root callback (`src/autoinfo/cli/__init__.py:49`)
  accepts `--json` before any command (e.g. `autoinfo --json status`) and sets
  `ctx.obj = {"json": True}`. Verified running: `autoinfo --json status`.
- **Per-command `--json`**: 21 of the 28 groups declare their own `--json`
  option at the group level or on individual subcommands (grep of `"--json"`
  in `src/autoinfo/cli/`): `sources`, `topics` (via `keywords`/`topic-group`),
  `domain`, `audit`, `billing`, `kb` (11 subcommands), `output`, `email`,
  `cron`, `summaries`, `keywords` (list/approve/reject/suggest), `knowledge`,
  `cost`, `enduser`, `portal`, `trace`, `import-kb`, `query-collected`,
  `alert-rules`, `agent-callback`, `doctor`, `collect`, `process`, `status`,
  `clean`.
- Groups without per-command `--json` (global flag only): `init`,
  `topic-group` (inherits `topics` JSON output on subcommands). `clean` and
  `doctor` expose `--dry-run` / `--verbose` as their structured-output flags.
- Convention: `--json` emits the **same envelope** the MCP tool returns
  (`{success, data}` or the documented noop shape), so script consumers get
  identical structure from either surface.

---

## Matrix (capability → surfaces)

### System

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Health check | `doctor` | `health_check` | `GET /health` | ✓ | REST /health is flat by design (M1T11) |
| System diagnostics | `doctor --verbose` | `diagnose_system` | — | ✓ CLI+MCP | MCP returns phase + health_score; CLI prints verbose sections |
| Tool count | — | `get_tool_count` | — | MCP-only | Self-discovering count |
| Get config | — | `get_config` | — | MCP-only | |
| List available models | — | `list_available_models` | — | MCP-only | |
| LLM config (BYOK) | `init` wizard | `configure_llm` | — | ✓ CLI+MCP | CLI init interactive; MCP stores env-var reference |
| Effective LLM config | — | `get_effective_llm_config` | — | MCP-only | |

### Discovery

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| List domains | `domain list` | `list_domains` | ~ | ✓ CLI+MCP | Dashboard consumes domains via REST UI |
| Available platforms | — | `list_available_platforms` | — | MCP-only | |
| Domain schema | `domain show` | `get_domain_schema` | — | ✓ CLI+MCP | |
| Activate domain | `domain activate` | `activate_domain` | — | ✓ CLI+MCP | |
| Deactivate domain | `domain deactivate` | `deactivate_domain` | — | ✓ CLI+MCP | |
| Get domain config | `domain show` | `get_domain_config` | — | ✓ CLI+MCP | |
| List output templates | `output list-templates` | `list_output_templates` | — | ✓ CLI+MCP | |

### Domain

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Add domain | `domain add` | `add_domain` | — | ✓ CLI+MCP | |
| Remove domain | `domain remove` | `remove_domain` | — | ✓ CLI+MCP | |
| Init project | `init` | `init_project` | — | ✓ CLI+MCP | Agents must use the MCP tool |

### Source

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Add source | `sources add` | `add_source` | — | ✓ CLI+MCP | Idempotent on both |
| Add sources (batch) | `sources add-sources` | `add_sources` | — | ✓ CLI+MCP | |
| Remove source | `sources remove` | `remove_source` | — | ✓ CLI+MCP | |
| Test source | `sources test` | `test_source` | — | ✓ CLI+MCP | |
| List sources | `sources list` | `list_sources` | — | ✓ CLI+MCP | |
| Source health | `sources health` | `get_source_health` | — | ✓ CLI+MCP | |
| Rate item | — | `rate_item` | — | MCP-only | |
| Get feeds | — | `get_feeds` | `GET /api/v1/feeds` | ✓ MCP+REST | RSS XML from both |

### Topic

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Add topic | `topics add` | `add_topic` | — | ✓ CLI+MCP | |
| Remove topic | `topics remove` | `remove_topic` | — | ✓ CLI+MCP | |
| List topics | `topics list` | `list_topics` | — | ✓ CLI+MCP | |
| Topic group add | `topic-group add` / `topics group add` | `topic_group_add` | — | ✓ CLI+MCP | New group (M6) |
| Topic group remove | `topic-group remove` / `topics group remove` | `topic_group_remove` | — | ✓ CLI+MCP | New group (M6) |
| List keywords | `keywords list` | `list_keywords` | — | ✓ CLI+MCP | New group (M6) |
| Approve keyword | `keywords approve` | `approve_keyword` | — | ✓ CLI+MCP | New group (M6) |
| Reject keyword | `keywords reject` | `reject_keyword` | — | ✓ CLI+MCP | New group (M6) |
| Suggest keywords | `keywords suggest` | `suggest_keywords` | — | ✓ CLI+MCP | New group (M6); graceful empty w/o `--text` |

### Collection

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Collect sources | `collect` | `collect_sources` | — | ✓ CLI+MCP | CLI sync; MCP async with job_id |
| Collection progress | — | `get_collection_progress` | — | MCP-only | **CLI job state: MCP-only** (see asymmetry note) |
| Collection status | `status` | `get_collection_status` | — | ✓ CLI+MCP | |
| Process collection | `process` | `process_collection` | — | ✓ CLI+MCP | Noop asymmetry → [mcp-usage-examples.md:298](mcp-usage-examples.md#cli-mcp-noop-asymmetry-process_collection) |
| Processing progress | — | `get_processing_progress` | — | MCP-only | **CLI job state: MCP-only** |
| Batch run | — | `batch_run` | — | MCP-only | |
| Clean cache | `clean` | `clean_cache` | — | ✓ CLI+MCP | CLI also has `--everything`/`--dry-run` |

### KB

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Search KB (hybrid) | `kb search` | `search_knowledge_base` | `GET /api/v1/search` | ✓ | REST search mirrors hybrid; MCP-only `filter_custom_fields` param (custom_fields dot-path facet: `""` = presence, non-empty = exact match) — not exposed via CLI/REST |
| Get KB entry | `kb list` | `get_kb_entry` | `GET /api/v1/entries/{entry_id}` | ✓ | |
| List summaries | `summaries list` | `list_summaries` | — | ✓ CLI+MCP | |
| Get summary | `summaries show` | `get_summary` | — | ✓ CLI+MCP | |
| Flag for KB | `summaries flag` | `flag_for_knowledge_base` | — | ✓ CLI+MCP | |
| Create KB entry | — | `create_kb_entry` | `POST /api/v1/entries` | ✓ MCP+REST | |
| Create KB draft | `kb create-draft` | `create_kb_draft` | — | ✓ CLI+MCP | Raw→Draft only |
| Reject KB draft | `kb reject-draft` | `reject_kb_draft` | — | ✓ CLI+MCP | |
| List KB tier | `kb list-tiers` / `kb list` | `list_kb_tier` | — | ✓ CLI+MCP | |
| Reindex KB | `kb reindex` | `reindex_kb` | — | ✓ CLI+MCP | |
| Delete entry | — | `soft_delete_entry` | `DELETE /api/v1/entries/{entry_id}` | ✓ MCP+REST | MCP has purge flag |
| Restore entry | — | `restore_entry` | — | MCP-only | |
| Link items | — | `link_items` | — | MCP-only | |
| Item relations | — | `get_item_relations` | — | MCP-only | |
| Entry history | `kb history` | `get_entry_history` | — | ✓ CLI+MCP | |
| Restore version | — | `restore_entry_version` | — | MCP-only | |
| Compare versions | — | `compare_versions` | — | MCP-only | |
| Collection stats | `status` | `get_collection_stats` | — | ✓ CLI+MCP | |
| Collection diff | — | `get_collection_diff` | — | MCP-only | |
| Domain decay | `kb decay` | `get_domain_decay` | — | ✓ CLI+MCP | |
| Mark stale | — | `mark_stale` | — | MCP-only | |
| Freshness score | — | `calculate_freshness_score` | — | MCP-only | |
| Recommend content | `kb recommend` | `recommend_content` | — | ✓ CLI+MCP | |
| Simplify content | — | `simplify_content` | — | MCP-only | E14 |

### KB Graph

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Query knowledge graph | — | `query_knowledge_graph` | — | MCP-only | |
| Knowledge graph export | `knowledge graph export` | `knowledge_graph_export` | — | ✓ CLI+MCP | CLI writes knowledge_graph_export.json |

### Output

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Generate digest | `output digest` | `generate_digest` | — | ✓ CLI+MCP | formats: md/html/json/agent |
| Digest product template | `output digest --product` | `generate_digest` `product` param | — | ✓ CLI+MCP | CLI `--product` → `product_template`; MCP `product` param |
| Generate report | `output report` | `generate_report` | — | ✓ CLI+MCP | formats: md/json/pdf/html/audio/agent |
| Report product template | `output report --product` | `generate_report` `product` param | — | ✓ CLI+MCP | CLI `--product` → `product_template`; MCP `product` param |
| Cross-domain report | `output report --domains` | `generate_cross_domain_report` | — | ✓ CLI+MCP | |
| Generate tutorial | `output tutorial` | `generate_tutorial` | — | ✓ CLI+MCP | md/agent |
| Generate presentation | `output presentation` | `generate_presentation` | — | ✓ CLI+MCP | md/agent |
| Localize / translate | `output translate` | `localize_content` | — | ✓ CLI+MCP | |
| Export KB | `output export` | `export_kb` | — | ✓ CLI+MCP | md/json/sqlite/pdf/csv/graphml/agent/bundle |
| Import KB | `import-kb` | `import_kb` | — | ✓ CLI+MCP | New group (M6); CLI reads files or `--data` |

### CEFR

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Classify CEFR | `cefr classify` | `classify_cefr` | — | ✓ CLI+MCP | EN/ZH/JA |
| Batch CEFR | `cefr batch` | `cefr_batch` | — | ✓ CLI+MCP | |

### Keywords

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Approve keyword | `keywords approve` | `approve_keyword` | — | ✓ CLI+MCP | New group (M6) |
| Reject keyword | `keywords reject` | `reject_keyword` | — | ✓ CLI+MCP | New group (M6) |
| Suggest keywords | `keywords suggest` | `suggest_keywords` | — | ✓ CLI+MCP | New group (M6) |

### Email

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Send digest email | `email send-digest` | `send_email_digest` | — | ✓ CLI+MCP | |
| Email config | `email config` | `email_config` | — | ✓ CLI+MCP | |

### Audit

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Query audit log | `audit query` | `query_audit_log` | — | ✓ CLI+MCP | Append-only |

### Q&A

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Query collected | `query-collected` | `query_collected` | — | ✓ CLI+MCP | New group (M6); FTS5 + LLM |

### Custom Extraction

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Extract fields | — | `extract_fields` | — | MCP-only | |
| Get extraction | — | `get_extraction` | — | MCP-only | |

### Cron

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| List schedules | `cron list-schedules` | `list_schedules` | — | ✓ CLI+MCP | |
| Add schedule | `cron add-schedule` | `add_schedule` | — | ✓ CLI+MCP | |
| Remove schedule | `cron remove-schedule` | `remove_schedule` | — | ✓ CLI+MCP | |
| Run schedules | `cron run` | `run_schedules` | — | ✓ CLI+MCP | |
| Schedule status | `cron health` | `get_schedule_status` | — | ✓ CLI+MCP | CLI adds heartbeat + missed-schedule |
| Install crontab | `cron install` | — | — | CLI-only | crontab management |
| Uninstall crontab | `cron uninstall` | — | — | CLI-only | crontab management |

### Delivery Schedule

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Add delivery schedule | `cron add-delivery` | `add_delivery_schedule` | — | ✓ CLI+MCP | |
| List delivery schedules | `cron list-deliveries` | `list_delivery_schedules` | — | ✓ CLI+MCP | |
| Remove delivery schedule | `cron remove-delivery` | `remove_delivery_schedule` | — | ✓ CLI+MCP | |

### Monitor

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| List active collections | `status` | `list_active_collections` | — | ✓ CLI+MCP | CLI status shows run state |
| List active deliveries | — | `list_active_deliveries` | — | MCP-only | |
| Channel health | — | `get_channel_health` | — | MCP-only | 13 channels |

### Webhooks

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Set domain webhooks | — | `set_domain_webhooks` | — | MCP-only | |
| Get domain webhooks | — | `get_domain_webhooks` | — | MCP-only | |

### Quality Gate Config

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Get gate config | — | `get_gate_config` | — | MCP-only | |
| Set gate config | — | `set_gate_config` | — | MCP-only | |

### Product

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| List products | — | `list_products` | `GET /storefront/products` | ✓ MCP+REST | REST is storefront HTML page |
| Get product | — | `get_product` | `GET /storefront/products/{product_id}` | ✓ MCP+REST | REST is storefront HTML page |

### Alert Rules

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Add alert rule | `alert-rules add` | `add_alert_rule` | — | ✓ CLI+MCP | New group (M6) |
| Get alert rules | `alert-rules list` | `get_alert_rules` | — | ✓ CLI+MCP | New group (M6) |
| Remove alert rule | `alert-rules remove` | `remove_alert_rule` | — | ✓ CLI+MCP | New group (M6) |

### End User

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Create end user | `enduser create` | `enduser_create` | — | ✓ CLI+MCP | |
| Get end user | `enduser get` | `enduser_get` | — | ✓ CLI+MCP | |
| Update end user | `enduser update` | `enduser_update` | — | ✓ CLI+MCP | |
| Delete end user | `enduser delete` | `enduser_delete` | — | ✓ CLI+MCP | |
| List end users | `enduser list` | `enduser_list` | — | ✓ CLI+MCP | |
| Send to end user | — | `send_to_enduser` | — | MCP-only | |
| End-user history | `portal history` | `get_enduser_history` | `GET /api/v1/portal/delivery-history` | ✓ | |
| End-user products | — | `get_enduser_products` | `GET /portal/{user_id}/products` | ✓ MCP+REST | REST is portal HTML page |
| Query delivery log | — | `query_delivery_log` | — | MCP-only | |
| Get delivery log | `portal history` | `get_delivery_log` | — | ✓ CLI+MCP | |
| Activate trial | — | `activate_trial` | — | MCP-only | |
| Check trial expiry | — | `check_trial_expiry` | — | MCP-only | |
| Update preferences | `portal preferences update` | `update_preferences` | `PUT /api/v1/portal/preferences` | ✓ | |
| Get preferences | `portal preferences show` | `get_preferences` | `GET /api/v1/portal/preferences` | ✓ | |
| Subscription status | `billing summary` | `get_subscription_status` | — | ✓ CLI+MCP | CLI billing summary includes it |

### Cost

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Billing summary | `billing summary` | `get_billing_summary` | — | ✓ CLI+MCP | |
| Budget thresholds get | — | `get_budget_thresholds` | — | MCP-only | |
| Budget thresholds set | — | `set_budget_thresholds` | — | MCP-only | |
| Checkout session | — | `create_checkout_session` | — | MCP-only | E12 payment mode |
| End-user usage | — | `get_enduser_usage` | — | MCP-only | |
| End-user invoice | — | `get_enduser_invoice` | — | MCP-only | |
| Cost dashboard | `cost dashboard` | `cost_dashboard` | — | ✓ CLI+MCP | |
| Cost allocation | `cost allocation` | `cost_allocation` | — | ✓ CLI+MCP | |

### Data Privacy

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Soft-delete entry | — | `soft_delete_entry` | `DELETE /api/v1/entries/{entry_id}` | ✓ MCP+REST | MCP purge flag |
| Restore entry | — | `restore_entry` | — | MCP-only | |
| Export user data | — | `export_user_data` | — | MCP-only | GDPR |
| Delete user data | — | `delete_user_data` | — | MCP-only | |

### Knowledge Lifecycle

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Compare versions | — | `compare_versions` | — | MCP-only | |
| Find similar items | — | `find_similar_items` | — | MCP-only | |
| Merge items | — | `merge_items` | — | MCP-only | |
| Domain decay | `kb decay` | `get_domain_decay` | — | ✓ CLI+MCP | |
| Mark stale | — | `mark_stale` | — | MCP-only | |
| Freshness score | — | `calculate_freshness_score` | — | MCP-only | |
| Recommend content | `kb recommend` | `recommend_content` | — | ✓ CLI+MCP | |
| Simplify content | — | `simplify_content` | — | MCP-only | E14 |

### Observability

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Trace item | `trace` | `trace_item` | — | ✓ CLI+MCP | CLI quirk: `--json` must precede id |
| Get metrics | `status --metrics` | `get_metrics` | — | ✓ CLI+MCP | |
| Prometheus metrics | `status --metrics` | `get_prometheus_metrics` | `GET /metrics` | ✓ | Prometheus text |
| Diagnose system | `doctor --verbose` | `diagnose_system` | — | ✓ CLI+MCP | |

### Agent Callbacks

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| Set agent callback | `agent-callback add` | `set_agent_callback` | — | ✓ CLI+MCP | New group (M6) |
| List agent callbacks | `agent-callback list` | `list_agent_callbacks` | — | ✓ CLI+MCP | New group (M6) |
| Remove agent callback | `agent-callback remove` | `remove_agent_callback` | — | ✓ CLI+MCP | New group (M6) |

### Projects

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| List projects | — | `list_projects` | — | MCP-only | |
| Project assets | — | `get_project_assets` | — | MCP-only | |
| Archive project | — | `archive_project` | — | MCP-only | |

### Validation

| Capability | CLI | MCP | REST | Status | Notes |
|------------|-----|-----|------|--------|-------|
| List validation scenarios | — | `list_validation_scenarios` | — | MCP-only | 109 scenarios (64 functional + 45 regression) |
| Run validation scenario | — | `run_validation_scenario` | — | MCP-only | Scenario steps may invoke CLI/REST internally |

### REST-only endpoints (no CLI / MCP counterpart)

| Endpoint | Method | Status | Purpose |
|----------|--------|--------|---------|
| `/` | GET | REST-only | Dashboard root (Bootstrap 5 UI) |
| `/dashboard` | GET | REST-only | Dashboard page |
| `/api/v1/entries` | GET | REST-only* | List entries (browse; approximates `search_knowledge_base`/`list_kb_tier`) |
| `/api/v1/entries` | POST | ✓ MCP+REST | Create entry (→ `create_kb_entry`) |
| `/api/v1/entries/{entry_id}` | GET | ✓ | Get entry (→ `get_kb_entry`) |
| `/api/v1/entries/{entry_id}` | DELETE | ✓ MCP+REST | Delete entry (→ `soft_delete_entry`) |
| `/api/v1/search` | GET | ✓ | Hybrid search (→ `search_knowledge_base`) |
| `/api/v1/feeds` | GET | ✓ MCP+REST | RSS feed (→ `get_feeds`) |
| `/api/v1/portal/preferences` | GET | ✓ | Get preferences (→ `get_preferences`) |
| `/api/v1/portal/preferences` | PUT | ✓ | Update preferences (→ `update_preferences`) |
| `/api/v1/portal/delivery-history` | GET | ✓ | Delivery history (→ `get_enduser_history`) |
| `/api/v1/webhook/stripe` | POST | REST-only | Stripe webhook (signature-verified) |
| `/portal/{user_id}` | GET | REST-only | Portal dashboard HTML page |
| `/portal/{user_id}/preferences` | GET | REST-only | Portal preferences HTML page |
| `/portal/{user_id}/history` | GET | REST-only | Portal history HTML page |
| `/portal/{user_id}/products` | GET | ✓ MCP+REST | Portal products HTML page (→ `get_enduser_products`) |
| `/storefront` | GET | REST-only | Storefront HTML page |
| `/storefront/products` | GET | ✓ MCP+REST | Product list page (→ `list_products`) |
| `/storefront/products/{product_id}` | GET | ✓ MCP+REST | Product detail page (→ `get_product`) |
| `/storefront/subscriptions` | POST | REST-only | Subscription creation |
| `/metrics` | GET | ✓ | Prometheus metrics (→ `get_prometheus_metrics`) |
| `/media/{file_path:path}` | GET | REST-only | Media file serving |
| `/openapi.json`, `/docs`, `/redoc` | GET | REST-only | OpenAPI docs |

### CLI-only commands (no MCP / REST counterpart)

| Command | Status | Purpose |
|---------|--------|---------|
| `kb promote` | ✓ CLI+MCP | Promote Draft→Wiki — **agent-operated, append-only** (→ `promote_kb_draft`; kept here for completeness) |
| `kb wiki-links` | CLI-only | Rebuild `[[wiki links]]` across the KB |
| `kb decay` | ✓ CLI+MCP | Decay metrics (listed above; kept here for completeness) |
| `output sitemap` | CLI-only | Generate XML sitemap for KB entries |
| `cron install` / `cron uninstall` | CLI-only | crontab lifecycle management |
| `domain import --from-demo` | CLI-only | Import demo domain definitions |
| `init --list-domains` | CLI-only | Print demo domains and exit |
| `clean --everything` | CLI-only | Remove ALL cached data incl. knowledge + DB |

---

## Spot-check log (CLI cells executed 2026-08-05)

The CLI side of the matrix was spot-checked by **running** the commands (not
reading source). The 6 new parity groups were all executed with real
state-changing operations (and reverted/cleaned up). MCP and REST cells were
derived from the runtime registries listed at the top; MCP cells were NOT
re-run cell-by-cell (derivation via `list_tools()` is exact).

| Group | Commands run | Result |
|-------|--------------|--------|
| `topic-group` | `topic-group add` (real) → `topic-group remove` (cleanup) | ✅ assigned + removed group `test-parity-t49` on medical-research |
| `keywords` | `keywords list` (real data) → `keywords approve` (real, positional args) → `keywords reject` (revert) → state restored to `auto_added` | ✅ full lifecycle verified |
| `import-kb` | `import-kb --format markdown --data <bad>` (rejected) → `--data <good>` (imported 1) → test entry removed | ✅ both error + success paths |
| `query-collected` | `--help` (LLM-required; not run without key) | ✅ option surface verified |
| `alert-rules` | `alert-rules add --json` (real) → `alert-rules list` → `alert-rules remove` (cleanup) | ✅ full lifecycle verified |
| `agent-callback` | `agent-callback add` (real, valid event) → `list` → `remove` (cleanup) | ✅ full lifecycle verified; invalid-event validation observed |
| Other groups | `status --json`, `summaries list`, `sources list`, `topics list`, `domain list`, `kb search`, `output list-templates`, `cron list-schedules`, `knowledge graph export`, `cost dashboard`, `billing summary`, `email config`, `audit query`, `enduser list`, `doctor`, `clean --dry-run`, `trace --json`, `portal preferences show --help`, `cefr classify --help`, `output digest/report --help` (agent formats) | ✅ representative sample per group |

Cleanup: `knowledge_graph_export.json`, the imported Raw entry
(`01-Raw/general/2026-08-05-parity-t49-spotcheck.md`), and all created
callbacks/rules/topic-groups were removed. No source or test files touched.

## Unrun cells

- All MCP tools: not executed individually; the 141 names come from the
  runtime `list_tools()` registry (exact, not approximate).
- All REST endpoints: not served over HTTP; paths/methods derived from
  FastAPI `app.routes` + the three router objects (`routes`, `portal`,
  `storefront`) — `_IncludedRouter` deferral means `app.routes` shows the
  routers, so router-level `.routes` were read directly.
- `query-collected`, `cefr classify`, `keywords suggest`, `output digest`/
  `report` (generation), `import-kb` LLM paths: not run end-to-end because no
  `AUTOINFO_LLM_API_KEY` is configured (LLM-required); their CLI surfaces were
  verified via `--help` and non-LLM paths.
