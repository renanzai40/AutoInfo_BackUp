# MCP Usage Examples

Worked examples for common AutoInfo MCP tool workflows. Referenced from
`AGENTS.md` Common Patterns. Each example shows the exact tool calls and
expected return shape.

For the compact pattern index, see `AGENTS.md` → Common Patterns. For the
full tool catalog, see `docs/dev/specs/mcp-tools.md` (145 tools, 35 categories).

---

## Track a new topic in medical research

```
1. add_topic(domain="medical-research", name="IVF breakthroughs", keywords=["IVF", "embryo"])
2. collect_sources(domain="medical-research", topic="IVF breakthroughs", dry_run=true) → preview
3. collect_sources(domain="medical-research", topic="IVF breakthroughs") → actual collection
4. process_collection(domain="medical-research") → LLM extraction
5. list_summaries(domain="medical-research", topic="IVF") → review results
6. flag_for_knowledge_base(summary_id, tags=["ivf", "breakthrough"]) → promote to KB
```

## What changed since last week

```
1. get_collection_stats(period="week") → overview
2. get_collection_diff(domain="medical-research", since_collection_id="...") → new items
```

## Check system health

```
1. diagnose_system() → comprehensive health (LLM key, sources, disk, DB) + health_score (0-100) + phase (uninitialized / llm_unconfigured / no_sources / ready_to_collect / operational)
```

Returns structured health with composite score. On degraded status, inspect
`phase` to identify the failing stage.

## Configure the LLM (BYOK)

```
1. configure_llm(api_key="sk-...", provider="openai", model="gpt-4") → stores env var reference (requires AutoInfo ≥ v1.8.1)
2. If LLM is missing, LLM-required tools return LLM_NOT_CONFIGURED (not a raw auth error) — see docs/dev/required-api-keys.md
```

Any of the 16 LLM-required tools (e.g. `process_collection`, `generate_digest`,
`suggest_keywords`) return `ErrorCode.LLM_NOT_CONFIGURED` at dispatch when no
key is configured.

## Create a custom domain

```
1. add_domain(name="my-custom-domain", description="My custom domain") → domain created
2. list_available_platforms() → discover supported source types
3. add_source(domain="my-custom-domain", name="my-rss", type="rss", url="https://example.com/feed") → source added
4. add_topic(domain="my-custom-domain", name="My Topic", keywords=["keyword1", "keyword2"]) → topic configured
5. collect_sources(domain="my-custom-domain") → collect from all sources
```

Custom domain with sources and topics fully configured.

## Initialise a project

```
1. health_check() → verify server availability
2. init_project(name="my-project", demo="medical-research") → scaffold project structure (requires AutoInfo ≥ v1.3), returns next_steps guidance array
3. list_domains() → confirm demo domain is active
```

Project initialised with demo domain, sources, and topics configured. Follow
the `next_steps` items (e.g. `configure_llm`, add sources) to finish setup.

## Save an article to the knowledge base

```
1. flag_for_knowledge_base(summary_id="sum_123", tags=["important", "review"]) → promote summary
2. create_kb_draft(summary_id="sum_123") → agent creates Draft from Raw
3. promote_kb_draft(draft_id="draft_123") → agent promotes Draft → Wiki (no human gate)
```

Summary flagged, Draft created, promoted to Wiki by the agent. Promotion is an agent production operation (2026-08-08 director decision); the CLI `autoinfo kb promote` is the human-facing equivalent.

## Set up and run a cron schedule

```
1. add_schedule(domain="medical-research", cron="0 8 * * 1", topic="IVF breakthroughs") → schedule created (requires AutoInfo ≥ v1.2)
2. cron_install() → install crontab entries (requires AutoInfo ≥ v1.2)
3. list_schedules() → verify active schedules
4. run_schedules() → manual trigger for immediate collection
```

Scheduled collection runs every Monday at 8 AM.

## Generate and send a digest email

```
1. generate_digest(domain="medical-research", period="week") → digest Markdown
2. send_email(to="user@example.com", subject="Weekly Digest", body=digest) → email sent via SMTP (requires AutoInfo ≥ v1.2)
```

Weekly digest generated and delivered to inbox.

## Classify content by CEFR level

```
1. classify_cefr(text="The mitochondria is the powerhouse of the cell.", language="en") → returns CEFR level (requires AutoInfo ≥ v1.2)
```

Returns `{"level": "B2", "confidence": 0.87, "features": ["academic vocabulary", "complex structure"]}`.

## Search with hybrid or vector mode

```
1. search_knowledge_base(domain="medical-research", query="embryo development", mode="hybrid") → FTS5 + vector
2. search_knowledge_base(domain="medical-research", query="embryo development", mode="vector") → semantic only (requires AutoInfo ≥ v1.2)
3. search_knowledge_base(domain="medical-research", mode="faceted", filters={"source_type": "pubmed", "relevance_min": 70}) → filtered (requires AutoInfo ≥ v1.2)
```

Ranked results from KB with source citations.

## Export knowledge base to PDF

```
1. export_kb(domain="medical-research", format="pdf", topic="IVF breakthroughs") → generates PDF report
```

PDF file written to `exports/medical-research/IVF-breakthroughs-report.pdf`.

## Manage keywords for a domain

```
1. list_keywords(domain="medical-research") → view current keywords and pending candidates
2. suggest_keywords(domain="medical-research", topic="IVF breakthroughs") → LLM suggests new keyword candidates
3. approve_keyword(keyword_id="kw_123") → accept a suggested keyword into the active set
4. reject_keyword(keyword_id="kw_456") → reject a suggested or obsolete keyword
```

Keywords curated for source filtering and topic matching. Use the CLI
(`autoinfo keywords add|remove|list`) for direct add/remove outside the
suggest-then-approve workflow.

## Generate agent-native JSON output

```
1. generate_digest(domain="medical-research", period="week", format="agent") → returns structured JSON-LD optimized for LLM re-consumption
```

Returns `{"@type": "KnowledgeDigest", "entries": [{uuid, title, tl_dr, source_url, confidence_score, entities, key_points}], "trends": [...], "metadata": {entry_count, quality_gates}}`.
Agent can re-synthesize, cache, or combine with other data.

## Subscribe to agent push delivery

```
1. set_agent_callback(url="https://my-agent.example.com/callback", events=["new_digest", "new_report"]) → register callback
2. AutoInfo pushes structured JSON when a matching product is generated
3. Agent receives {event, payload, schema_version: 1, trace_id, product_id} via HTTP POST
```

Payload contract: every push is an HTTP POST with the canonical shape
`{event, payload, schema_version: 1, trace_id, product_id}`. `event` is one of
`new_digest`, `new_report`, `new_tutorial`. `payload` is the generated output
(JSON-LD for `format="agent"`, markdown/HTML for other formats). `schema_version`
is `1`. `trace_id` ties the push to the item trace, and `product_id` names the
generated product when one exists.

Delivery is fire-and-forget: no retry or backoff, and the push never blocks or
fails the caller. Durability comes from the SQLite outbox (`agent_outbox`): the
event row is persisted before any delivery attempt, then a background worker
drains it (`pending` → `delivered` | `failed`). Rows survive process restarts;
on startup, `failed` rows are requeued to `pending` and re-attempted. A failed
delivery is counted in the `delivery_failures_total` metric.

Agent subscription pattern: register once, receive pushes without polling.
(requires AutoInfo ≥ v1.7)

## Generate and deliver a digest email

```
1. generate_digest(domain="medical-research", period="week", format="html") → digest HTML
2. send_email_digest(domain="medical-research", period="week", recipients=["user@example.com"]) → sends via SMTP
```

Digest generated as HTML and emailed to subscribers.

## Use the REST API

```
1. Start the FastAPI server: uvicorn autoinfo.api.server:app --port 8741
2. curl http://localhost:8741/health → {"status": "ok"}
3. curl http://localhost:8741/api/v1/entries?domain=medical-research → paginated entries
4. curl -X POST http://localhost:8741/api/v1/search -H "Content-Type: application/json" -d '{"query": "embryo"}'
```

Full KB CRUD over HTTP, no auth required (localhost security). Errors use the
same `{success, error: {code, message, actionable}}` envelope as MCP —
nonexistent domains return `DomainNotFound` with remediation hint.

## Configure the LLM (detailed)

```
1. configure_llm(api_key="sk-...", provider="openai", model="gpt-4") → stores env var reference in config (requires AutoInfo ≥ v1.8.1)
2. api_key is stored as ${AUTOINFO_LLM_API_KEY} env var reference — never the raw key
3. Set the actual key as an environment variable: export AUTOINFO_LLM_API_KEY="sk-..."
```

LLM configured for extraction and processing. If the key is missing,
`configure_llm` returns `CONFIG_NOT_FOUND` and LLM-required tools return
`LLM_NOT_CONFIGURED`. Full variable catalog: `docs/dev/required-api-keys.md`.

## Handle MCP error responses

All MCP tools return the canonical envelope
`{success, error: {code, message, actionable}}`. When a tool fails:

1. Read `error.code` to classify the failure (`DOMAIN_NOT_FOUND`,
   `LLM_NOT_CONFIGURED`, `VALIDATION_ERROR`, ...)
2. If `actionable` is true, follow the remediation hint in `error.message` —
   e.g. `DOMAIN_NOT_FOUND` errors include "Use `add_domain()` to create it."
3. For `LLM_NOT_CONFIGURED`, run `configure_llm()` first (or check
   `docs/dev/required-api-keys.md`)
4. `process_collection` with no cached items returns
   `{status: "noop", total_items: 0}` — not an error, proceed with collection
   first

Every configuration gap produces a structured, actionable error; no raw
tracebacks or silent fallbacks.

## Generate cross-domain report

```
1. generate_report(domain="medical-research", domains=["medical-research", "ai-commercial"], format="markdown", report_type="industry") → combined analysis
2. Or via CLI: autoinfo output report --domains medical --domains ai-commercial --type trend
```

Cross-domain analysis combining insights from multiple domains.

## Set up a delivery schedule

```
1. add_delivery_schedule(domain="medical-research", cron_expression="0 8 * * 1", output_type="digest", channel="email") → schedule created
2. list_delivery_schedules() → view all schedules
3. Schedules execute automatically via autoinfo cron run
```

Automated scheduled delivery of digests and reports.

## Export knowledge base as bundle

```
1. export_kb(domain="medical-research", format="bundle") → creates ZIP with JSON+MD+YAML+PDF
```

Comprehensive export bundle with all formats in a single ZIP archive.

## Generate a specialized report

```
1. generate_report(domain="medical-research", format="markdown", report_type="competitive", target_audience="researcher") → competitive analysis report
```

Specialized report types (competitive, trend, industry, summary) with audience
targeting.

## Run MCP-native validation

```
1. list_validation_scenarios() → returns available scenario names (68 built-in across all MCP categories, CLI, and REST API surfaces)
2. run_validation_scenario(scenario="system-health") → executes steps in-process (real tool calls, real subprocesses for CLI steps, real HTTP requests for REST steps), returns {success, data: {scenario, status: passed|failed|unconfigured, summary, steps}}
3. Scenarios with requires_env (e.g. llm-gated needs AUTOINFO_LLM_API_KEY) return status "unconfigured" when env vars are missing — never silently skipped, never fake-passed. Director User must provide BYOK keys during onboarding.
4. Steps may use llm_assert — a real LLM call judges the tool output against a natural-language assertion (semantic validation, not just structure checks)
```

Agent-native validation: scenarios execute MCP tools through the MCP surface
(plus CLI subprocess + REST HTTP steps) and assert on the standard
`{success, data}` envelope. Real calls only — no mocks, no compromise.

## Monitor long-running collection or processing

Collection and processing return a `job_id` for progress polling:

1. Start collection: `collect_sources(domain="medical", topic="IVF", async=true)` → returns `{..., "job_id": "uuid-xxx"}`
2. Poll every 5 seconds:
   ```
   while True:
       status = get_collection_progress(job_id="uuid-xxx")
       if status["is_complete"]:
           break
       sleep(5)
   ```
3. Start processing: `process_collection(domain="medical")` → returns `{..., "job_id": "uuid-yyy"}`
4. Poll: `get_processing_progress(job_id="uuid-yyy")` → check `status["is_complete"]`
5. When done: `list_summaries(domain="medical")` to review results

**Legacy**: `get_collection_progress(domain="medical")` and
`get_processing_progress(domain="medical")` still work for simple single-domain
usage without job_id.

## CLI/MCP noop asymmetry (process_collection)

Processing a domain with no cached collected items returns a *noop* — nothing
was processed, this is not an error. The MCP and CLI surfaces report it
differently, and this asymmetry is **intentional** (CLI is human-first; the
exit code is unchanged):

| Surface | Noop shape | Location |
|---------|-----------|----------|
| MCP `process_collection` | `{status: "noop", total_items: 0, message: "No cached items found for domain '<domain>'. Run collect_sources() first.", domain}` | `src/autoinfo/mcp/server.py:673-678` |
| CLI `autoinfo process` (human) | `No cached items found for domain '<domain>'.` + **exit 0** | `src/autoinfo/cli/process.py:98` |
| CLI `autoinfo process --json` | `{status: "noop", total_items: 0, message, domain}` — mirrors the MCP shape exactly | `src/autoinfo/cli/process.py:64-81` |

Design notes:

- **MCP is agent-facing**: agents branch on the structured `status` field.
  A noop is a normal `{success: true}` response, never an error envelope.
- **CLI is human-first**: plain text + exit 0 is the established behavior and
  is **not a change** — noop is not a failure, so no non-zero exit.
- **CLI `--json` noop parity**: `autoinfo process --json` on a noop run prints
  the same `{status: "noop", ...}` object as the MCP tool, so script consumers
  get identical structure from both surfaces.

> **Parity matrix note (for task 49)**: the canonical parity matrix
> `docs/dev/cli-mcp-rest-parity.md` must reference this asymmetry table
> (cross-link here) when it is created. Do not move this content — it is the
> source of truth; the matrix should point at it.
