# Validation Scenario Authoring & Agent-Tester Execution

> **Canonical how-to for the Agent-native validation toolset** (`list_validation_scenarios` /
> `run_validation_scenario`, engine `src/autoinfo/mcp/validation.py`): **Part 1** is the
> exact contract for authoring validation scenario YAML files in
> `src/autoinfo/mcp/scenarios/`; **Part 2** is the result-oriented, full-coverage runbook
> that teaches the validating agent (B2 direct user) how to execute **every** AutoInfo
> feature with **real** MCP, CLI, REST, and LLM calls and surface all raw and processed
> data to the human director. Part 2 is **not** a subset, **not** a demo, **not** a
> starting point — it is the complete coverage runbook.
>
> **Audience:** scenario authors (Part 1) and the agent-tester / validator executing the
> guide end to end (Part 2). **Source of truth:** the actual `src/` code — every tool
> name, parameter, format enum, and count here was verified against source; where this
> guide differs from earlier drafts, the source value wins.
>
> **Relationship to the acceptance framework:** the grading authority is
> `docs/dev/acceptance-framework.md` (AC1-AC9) — it defines what "acceptable" means, the
> verdict semantics (PASS / FAIL / RISK / `unconfigured`), the evidence catalog (A1-A24),
> and AC7 process & governance (B2 executes and drafts verdicts; B3 adjudicates and signs
> off). `docs/archive/launch-validation-framework.md` (D1-D5) is superseded as charter and
> retained as archived evidence-production tooling. **This document is the authoring +
> execution how-to** that produces the evidence the acceptance framework grades.

---

## 0. Shared Rules (binding for both roles)

### 0.1 Definitions

| Term | Meaning |
|------|---------|
| **Validator** | The executing agent (B2 direct user). Runs every real call, collects every artifact, quotes real data. |
| **Director** | The human (B3 director user) who owns the API keys, reviews evidence, and decides. The validator reports to the director. |
| **Real call** | A genuine network request, LLM inference, subprocess, HTTP request, or database read/write against the live system. Never a mock, fixture, or stubbed response. |
| **Local sink** | A locally hosted capture endpoint (HTTP server, SMTP sink, stripe-mock) that records real network transactions. A local sink is a **real network transaction** with a labeled local destination; it is acceptable evidence, but it must be labeled as a sink in the evidence. |
| **RED** | The honest negative state recorded *before* a fix or configuration: the call fails, the scenario reports `unconfigured`, or the artifact is absent. Recorded first, never skipped. |
| **GREEN** | The verified positive state: the real call succeeds **and** the expected artifact exists on disk / in the DB / in a log / on the sink. GREEN is only GREEN when both conditions hold. |
| **Artifact-to-show** | The concrete file, table row, log line, or captured payload that proves the feature. |
| **unconfigured** | A scenario or tool that could not run because a required key is missing. `unconfigured` is a recorded known-limit. It is **never** a pass. |

### 0.2 Real-surface evidence, no mock (P3)

Validation must be **real**: scenarios and runbook rows execute through the MCP surface
(plus real CLI subprocesses and real HTTP requests), never mocked. Every step makes an
actual call and asserts on the standard `{success, data}` envelope; LLM-dependent steps
run a real model call via `llm_assert`. This mirrors principle **P3 (real-surface
evidence)** in `docs/dev/acceptance-framework.md` §0.6.

Evidence is only evidence if it came from a real surface:

| Surface | Acceptable evidence |
|---------|---------------------|
| MCP (stdio) | `{success, data}` envelope JSON from a live tool call |
| CLI | subprocess exit code + stdout/stderr from a real command |
| REST | real HTTP status + body from `uvicorn` on port 8741 |
| LLM | real LiteLLM completion output (extraction, judge, generation) |
| Network | real fetch from a real source; local sinks (HTTP/SMTP/stripe-mock) **labeled as sinks** |
| Storage | actual files under `collections/`, `knowledge/`, `outputs/`, `exports/`; real rows in `autoinfo.db`; real log lines in `logs/` |

Not evidence: unit-test output, mocked stores, seeded fixtures, sample data copied into
runtime paths, or claims without an artifact. **GREEN requires both halves:** (1) the
real call succeeded with the expected shape, **and** (2) the artifact exists **and** was
shown (pasted, quoted, or pointed to by absolute path) to the director. A call that
succeeds but whose artifact is never surfaced is NOT GREEN.

### 0.3 `unconfigured` is never a pass

When required environment variables (BYOK keys) are missing, the scenario reports
`unconfigured` — never silently skipped, never fake-passed. It is the honest state of a
known limit: recorded, then re-run after the key is configured. A validator must never
skip it, fake it, or grade it GREEN; authors gate key-dependent steps with `requires_env`
so the executor reports `unconfigured` instead of failing on a missing credential (§1.3).
Mirrors the `unconfigured` verdict semantics in `docs/dev/acceptance-framework.md` §7.3.

### 0.4 Baseline honesty

Before any key is configured, record the system's known no-keys profile (the RED
baseline): run `list_validation_scenarios()` (expect 68) then `run_validation_scenario`
for every scenario, and record the aggregate. The env-gated set is stable — **15
scenarios need keys**: 13 need `AUTOINFO_LLM_API_KEY` (cli-llm, data-lifecycle-e2e,
enduser-journey, kb-extraction, llm-gated, output-column, output-digest-report,
output-ebook, output-premium-products, output-simplify-recommend,
output-tutorial-presentation, output-video, processing), products-billing needs
`STRIPE_API_KEY`, and sources-a6-keyed needs `FRED_API_KEY` + `FINNHUB_API_KEY`.
After configuring keys, re-run those to GREEN (`passed`, never
`unconfigured`). Observed example (47-scenario suite, 2026-08-05): **37 passed / 0 failed
/ 10 unconfigured**; the suite has since grown to 68 (§1.8) — the baseline shape (all
env-gated `unconfigured`, nothing failed) is unchanged.

---

# Part 1 — Scenario Authoring Contract

## 1.1 Purpose and execution context

Scenarios must be real, loadable, and self-verifying: every implemented MCP tool is
exercised by a `kind: mcp` step in at least one scenario. The executor engine lives in
`src/autoinfo/mcp/validation.py` (scenario loading via `load_scenarios()`); the MCP
surface is `list_validation_scenarios` / `run_validation_scenario`. Every scenario runs
against the live system from the **project root** (`/mnt/d/贯维/AutoInfo`) where
`.autoinfo/config.yaml` exists and the `medical-research` domain is configured with 5
sources, 3 topics, and populated `knowledge/medical-research/01-Raw/` data. This is the
REAL operation context — do NOT write "empty state" assertions; tools return real data
here.

## 1.2 Scenario file schema

```yaml
name: kebab-case-unique-id          # required
description: "human readable"       # required
category: <one of: system|discovery|source|topic|collection|kb|output|delivery|
                    enduser|cost|privacy|lifecycle|observability|quality|cli|http|errors>
requires_env: []                    # optional list of env var names; if ANY missing
                                    # the WHOLE scenario reports status=unconfigured
                                    # (Director User BYOK obligation — never skipped)
requires_domain: []                 # optional list of domains a scenario requires
                                    # (e.g. ['medical-research']); if ANY required
                                    # domain is absent, the scenario reports
                                    # status=unconfigured (missing domain is not a
                                    # code defect)
requires_http: []                   # optional list of URLs (e.g. http://127.0.0.1:8741/health);
                                    # if ANY URL is unreachable the scenario reports
                                    # status=unconfigured with a reason instead of
                                    # failing (env preconditions are not code defects,
                                    # #157).  Used for REST-server-gated scenarios.
cleanup_steps:                      # optional list of steps (same schema as `steps`)
                                    # run AFTER the main steps on pass AND on fail
                                    # (best-effort); reported under `cleanup` and
                                    # never influence the scenario status.  Use for
                                    # removing state the scenario created.
min_passing: 5                      # optional int: minimum number of main steps that
                                    # must pass for the scenario to be `passed`; lets
                                    # a scenario degrade gracefully when a subset of
                                    # steps legitimately cannot all run (partial-pass).
pass_ratio: 0.8                     # optional float (0.0-1.0): alternative partial-pass
                                    # policy — fraction of main steps that must pass.
                                    # Only one of min_passing / pass_ratio should be
                                    # set; when neither is set, ALL steps must pass.
regression: true                    # optional bool: marks this scenario as a
                                    # regression scenario.  True for files placed in
                                    # the scenarios/regression/ subdirectory (auto-
                                    # loaded via recursive glob).  Regression
                                    # scenarios are reported with a "(regression)"
                                    # suffix in verdicts and a dedicated
                                    # `## Regression failures` report section.
regression_issue: "#NNN"            # optional (required when regression: true): the
                                    # issue/PR number this scenario guards against
                                    # regressing, e.g. "#119".
steps:
  - name: "human readable step name"   # required
    kind: mcp                         # optional: mcp (default) | cli | http
    timeout_seconds: 30               # optional int: per-step wall-clock budget; a
                                      # step exceeding it fails fast instead of
                                      # hanging the whole run (default: no timeout).
    recovery_steps:                   # optional list of steps (same schema as this
                                      # step); run AFTER this step's primary failure
                                      # in an attempt to recover, then re-evaluate.
    collect_artifacts:                # optional list of output artifacts to persist
                                      # for post-run inspection (e.g. file paths the
                                      # step wrote); used on output scenarios.
    # --- for kind=mcp ---
    tool: add_source                  # required: real MCP tool name
    arguments: {...}                  # required: real args the handler accepts
    # --- for kind=cli ---
    command: "autoinfo sources list"  # required: shell command, real subprocess
    # --- for kind=http ---
    method: GET                       # required
    url: "http://127.0.0.1:8741/health"   # required (REST server must be running)
    http_options: {}                  # optional: httpx kwargs (headers, json, params)
    # --- expect (all optional) ---
    expect:
      success: true                   # optional, default true
      # mcp envelope assertions:
      data_has: ["domains"]           # keys that must exist in envelope.data (dict)
      error_code: "UnknownTool"       # when success expected False: envelope.error.code
      error_actionable: false         # when success expected False: envelope.error.actionable
                                      # must equal this boolean (asserts the remediation hint)
      # cli assertions:
      exit_code: 0                    # expected subprocess returncode
      stdout_has: ["substring"]       # substrings that must appear in stdout
      stderr_has: ["substring"]       # substrings that must appear in stderr
      # http assertions:
      status_code: 200                # expected HTTP status
      json_has: ["status"]            # keys that must exist in response JSON body
      # LLM semantic assertion (REAL model call — never mocked):
      llm_assert: "NL assertion the LLM judges against the tool output"  # optional
```

## 1.3 Semantics

- **`success`**: envelope `{success: bool}`. For cli: exit_code==0 ⇒ success=True.
  For http: 2xx/3xx ⇒ success=True.
- **`requires_env`**: if any listed env var is unset, the scenario returns
  `status: unconfigured` with per-step unconfigured results (see §0.3 — the Director
  User's BYOK obligation; never silently skip).
- **`requires_http`**: if any listed URL is unreachable, the scenario returns
  `status: unconfigured` (not failed) with a reason per precondition. REST-server and
  network-gated scenarios use this so a missing local server (e.g. uvicorn on port
  8741) or an offline service does not pollute the failed count — env preconditions
  are not code defects (#157).
- **`cleanup_steps`**: top-level list using the same step schema as `steps`; run after
  the main steps **regardless of the main outcome** (pass or fail) so scenario-created
  state is removed even when a middle step failed. Each cleanup step is a real call,
  asserted the same way, but results are reported under `cleanup: {summary, steps}` and
  **never influence the scenario status**. When `requires_env` is missing, nothing ran,
  so cleanup is skipped. Scenarios that create persistent state MUST clean up after
  themselves (verify-before-delete provenance checks are strongly recommended so real
  user data is never touched).
- **`timeout_seconds`** (per step, optional): wall-clock budget in seconds. A step
  exceeding its budget is marked failed with a timeout reason and the executor moves
  on — a runaway step can no longer hang the whole run (default: no timeout).
- **`recovery_steps`** (per step, optional): steps using the same step schema, run
  **after the primary step fails** in an attempt to recover; each is a real call,
  asserted the same way. If they pass, the step is reported as recovered (the failure
  is still recorded in the per-step trace); if they fail, the step fails. Reported
  under the step's `recovery` key; never inflate the pass count on their own.
- **`min_passing` / `pass_ratio`** (top-level, optional): partial-pass policy.
  `min_passing` (int) = minimum main steps that must pass; `pass_ratio` (float
  0.0-1.0) = fraction that must pass. Set at most one; when neither is set, ALL main
  steps must pass. A scenario meeting the policy is `passed` even when some steps
  failed (they still surface in the report). Use where a subset of steps is
  legitimately environment-dependent.
- **`regression` / `regression_issue`**: `regression: true` requires
  `regression_issue: "#NNN"`. Files in `scenarios/regression/` are auto-loaded via
  recursive glob and conventionally set both fields. Reports show regression scenarios
  with a "(regression)" suffix in the verdicts table and a dedicated `## Regression
  failures` section (root cause + guarded issue).
- **`collect_artifacts`** (per step, optional): artifact references the step produced
  (e.g. written file paths); output scenarios use it so generated digests/reports/
  exports persist for post-run inspection in validation delivery.
- **`llm_assert`**: when present and structural assertions passed, the executor makes a
  REAL LiteLLM call (model from config) to judge the tool output against the NL
  assertion; no LLM key → step reports `unconfigured`. Add
  `requires_env: [AUTOINFO_LLM_API_KEY]` at scenario level for LLM-dependent scenarios.
- **`kind: cli`**: real subprocess via `subprocess.run(command, shell=True)`; must work
  from project root (`autoinfo ...` installed console script).
- **`kind: http`**: real HTTP request via httpx; the REST server must be running
  (`uvicorn autoinfo.api.server:app --port 8741`) for these to pass.

## 1.4 Status aggregation

- scenario status: `passed` (no failed), `unconfigured` (any step unconfigured, none
  failed), `failed` (any step failed). With a partial-pass policy (`min_passing` /
  `pass_ratio`), `passed` also applies when the passed-step count meets the policy
  despite some failed steps.
- summary: `{passed, failed, unconfigured, total}`.

## 1.5 Per-step trace and report sections

- Every executed step is recorded with `step_index`, `duration`, `arguments`,
  `trace_id`, and (for LLM steps) `llm_meta` (model, tokens, duration), so a failing
  run can be reconstructed exactly.
- The validation report (`scripts/validation_report.py`) emits:
  - **Verdicts** — per-scenario result table (regression scenarios carry a
    "(regression)" suffix).
  - **Executive summary** — aggregate pass/fail/unconfigured counts.
  - **`## Regression failures`** — every failed regression scenario with its guarded
    issue number.
  - **`## Blockers`** — root-cause analysis for each failed scenario, including the
    failing step's details from the per-step trace.
  - **`## Per-step trace`** — full step-by-step execution trace.
  - **Appendix pointer** — link to the raw results.

## 1.6 Authoring rules (MANDATORY)

1. **Verify every step before finalizing**: run the scenario via the MCP tool
   `run_validation_scenario(scenario="NAME")` (or call the executor directly with a
   real dispatch) from project root. Adjust assertions to match REAL responses.
2. **Real tool signatures**: read `src/autoinfo/mcp/server.py` `call_tool()` dispatch
   and the handler `def _handle_X(...)` signature for exact argument names. Some tools
   require `domain`, some don't take it (e.g. `get_source_health` takes `source_id`).
   VERIFY each.
3. **No mocks, no compromise**: every assertion must be checkable against real
   tool/LLM/HTTP responses (see §0.2/§0.3). If a tool needs an env var, gate the
   scenario with `requires_env` (unconfigured is honest; a fabricated pass is not).
4. **No destructive or state-corrupting side effects**: prefer idempotent reads
   (`list_*`, `get_*`, `search_*`). For mutating tools (`add_*`, `create_*`,
   `enduser_create`), use clearly-safe test data and clean up within the same scenario
   (e.g. `enduser_create` → `enduser_delete`, `add_source` → `remove_source`). For
   state that must survive to the last step (e.g. a KB entry created in step 1 and
   rejected in step 5), declare `cleanup_steps` so the state is removed even when a
   middle step fails. The `kb-draft` scenario is the reference pattern: fully
   self-contained steps operating only on the scenario's own deterministic entry ids,
   plus a `cleanup_steps` CLI step that verifies provenance markers before purging.
5. **Coverage**: every implemented MCP tool must appear as a `kind: mcp` step in at
   least one scenario. Track coverage with the audit script (see below).
6. **YAML validity**: scenarios must load via `load_scenarios()` with no errors.
7. Keep 2-6 steps per scenario. Split large tool lists into multiple scenario files.
8. Category should match the MCP category from the inventory where possible.

## 1.7 Coverage audit

Run after writing scenarios:
```bash
python3 scripts/coverage_audit.py   # reports covered/missing MCP tools
```
Every tool must disappear from the MISSING list. The audit counts `Tool(name=...)`
declarations in `src/autoinfo/mcp/server.py` (146 tools) against `kind: mcp` steps in
the scenario library. It also prints a `Regression scenarios: N (issues: ...)` metric —
every scenario in `scenarios/regression/` must carry `regression: true` and a
`regression_issue`, and the audit lists any that don't.

## 1.8 Scenario inventory (as of 2026-08-16)

70 scenario files in `src/autoinfo/mcp/scenarios/` (64 functional flat in `scenarios/`
+ 6 regression in `scenarios/regression/`):

- **System/Discovery**: system-health, discovery, meta-validation
- **Errors**: error-boundary
- **Domain/Source/Topic/Keyword**: domain-management, source-management,
  topic-management, keyword-management
- **Collection/Processing/Cron**: collection, collectors-e2e, processing,
  cron-schedules, collection-monitor, collect-failure-recovery, llm-failure-recovery
- **KB**: kb-access, kb-draft, kb-versioning, kb-graph, kb-import-export,
  kb-lifecycle, kb-extraction, kb-promote (E8: Draft→Wiki promotion end to end),
  kb-tier-matrix (AC4, 2026-08-16: 13 demo domains × 3 KB tiers matrix coverage)
- **Output**: output-digest-report, output-ebook, output-tutorial-presentation,
  output-simplify-recommend, output-discovery, output-column, output-agent-interaction,
  output-video (2026-08-13, LLM-gated: report video format rendered end to end)
  (output-quality-mega wave: differentiated product templates premium-briefing /
  enterprise-briefing / magazine-digest rendered end to end with per-product analysis
  persisted to KB and faceted `filter_custom_fields` retrieval; deterministic,
  `requires_env: []` — LLM seams patched)
- **M7 additions**: sources-gap-closure (3 new source-type registrations),
  output-column (report_type=column, LLM-gated), sources-a6-keyed
  (FRED/Finnhub, env-gated)
- **2026-08-07 additions (#156)**: output-premium-products (premium-briefing /
  magazine-digest / enterprise-briefing via `product_template`, LLM-gated),
  sources-coverage (academic + all 29 source platforms in the v3 spec; scenario
  library exercises 8/8 products, 8/8 formats, 28/29 sources —
  email_imap pending)
- **2026-08-08 additions (KB-curation wave)**: kb-promote-admission (admission
  gate + provenance guard end to end), promotion-provenance (source_platform
  admission requirement), promotion-triggers (auto-promote eligibility paths),
  curated-priority-consumption (curated content priority), search-tier-boost
  (03-Wiki search promotion), director-backdoor (reject/backdoor path)
- **Delivery/End-user/Cost**: delivery-channels, delivery-schedules,
  enduser-lifecycle, enduser-preferences, cost-budget, products-billing,
  enduser-journey (E8: full B1 lifecycle with UX metrics)
- **Privacy/Lifecycle/Observability**: data-privacy, data-lifecycle-e2e, observability,
  agent-callbacks, webhooks-alerts, quality-gate-config, projects-config
- **LLM-gated**: llm-gated (classify_cefr, suggest_keywords, cefr_batch)
- **CLI**: cli-core, cli-content, cli-ops, cli-extra, cli-llm
- **REST**: rest-api
- **Regression (scenarios/regression/)**: regression-collect-int-id (#104),
  regression-llm-key-resolution (#119), regression-period-enum (#126),
  regression-report-structure (#121), regression-source-301 (#135),
  regression-product-routing (#output-quality-mega; premium-briefing / magazine-digest
  product routing + product-render differentiation). Each carries
  `regression: true` + `regression_issue`, is auto-loaded via recursive glob, and
  appears with a "(regression)" suffix in verdicts plus a `## Regression failures`
  report section.

Coverage: 146/146 MCP tools (100%), all 28 CLI command groups, 8 REST API endpoints,
plus collector platform reachability probes (collectors-e2e) and G4/G5 gate flags
(processing, LLM-gated). Status profile depends on BYOK keys: LLM-gated and env-gated
scenarios (requires_env) report `unconfigured` without the keys (never silently
skipped); partial-pass scenarios (`min_passing`/`pass_ratio`) can pass with a degraded
step set. Run `run_validation_scenario` per scenario or `scripts/coverage_audit.py` for
the aggregate regression metric.

---

# Part 2 — Agent-Tester Execution Runbook

## 2.1 Purpose and scope

Prove, with real calls and real artifacts, that AutoInfo works across its full surface:
**146 MCP tools (35 categories), 28 CLI command groups, 8 REST endpoints, 13 delivery
channels, 30 collector handlers, and every output format**. Each proof must leave a
verifiable artifact on disk, in the SQLite store, in the audit log, or on a network
sink, and that artifact must be shown to the director.

Full coverage in nine phases — every row in §2.5 must be executed; there is no optional
row:

| Phase | Area | Rows |
|-------|------|------|
| A | System / config / discovery / error envelope | A1-A4 |
| B | Domain / source / topic / keyword / webhooks | B1-B7 |
| C | Collection pipeline, dedup, cache | C1-C3 |
| D | Processing, LLM extraction, quality gates | D1-D4 |
| E | KB pipeline, lifecycle, graph, search, Q&A | E1-E8 |
| F | Output generation, all formats, schema validation | F1-F9 |
| G | Delivery, scheduling, cron, agent callbacks | G1-G5 |
| H | End-user lifecycle, cost, billing, privacy | H1-H5 |
| I | Governance, observability, REST, validation meta | I1-I6 |

## 2.2 The Evidence Contract

Every feature row in §2.5 is executed against a fixed five-part contract:

```
(surface, real call, expect, actual, artifact-to-show)
```

| Part | Meaning | Rule |
|------|---------|------|
| **surface** | MCP tool, CLI command, or REST endpoint | The call is made through the real surface, never around it |
| **real call** | The exact command / tool invocation | Executed for real; no mocks (§0.2) |
| **expect** | What a correct system returns | Derived from source and documented behavior |
| **actual** | What the system actually returned | Recorded verbatim, even when it differs from expect |
| **artifact-to-show** | The file / DB row / log line / payload that proves it | Must exist on disk / DB / log / sink **and** be surfaced to the director (§2.8) |

GREEN semantics are defined in §0.1/§0.2 (a call that succeeds but whose artifact is
never surfaced is NOT GREEN).

## 2.3 Bootstrap for real calls — BYOK LLM setup

The only hard requirement for the LLM-dependent surface is one key. Full
catalog: `docs/dev/required-api-keys.md`.

```bash
# 1. Export the key in the shell that spawns the MCP server / CLI.
export AUTOINFO_LLM_API_KEY="sk-..."

# 2. Record it in config via the MCP tool (stores an env-var REFERENCE
#    ${AUTOINFO_LLM_API_KEY}, never the raw key).
#    MCP: configure_llm(provider="openai", model="<model>",
#                       api_key="${AUTOINFO_LLM_API_KEY}", base_url="<optional>")

# 3. Confirm the effective config:
#    MCP: get_effective_llm_config()
#    CLI: autoinfo doctor --verbose   (reports llm.provider / llm.model)
```

Precedence (highest to lowest): MCP tool parameter > `.autoinfo/config.yaml`
`llm.*` > `AUTOINFO_LLM_API_KEY` env var > defaults (openrouter /
deepseek/deepseek-chat). See `AGENTS.md` "LLM Configuration".

## 2.4 Collector bootstrap matrix

Two tiers. The authoritative map is `SOURCE_KEY_ENV_VARS` in
`src/autoinfo/config.py` (lines 70-82) plus `requires_key()` in the collector
handlers. **21 keyless collectors** (no credential required; optional keys only
raise rate limits), **9 key-gated groups** (real fetch is blocked without the
credential).

| Tier | Source types | Behavior |
|------|--------------|----------|
| **Keyless (21)** | rss, web, web_playwright (web), webhook, pdf, dblp, openalex, api/pubmed, api/s2, api/uspto, api/http_api, hackernews, gdelt, ssrn, sec_edgar, akshare, bilibili, apple_podcasts, yahoo_finance, edx_sitemap, huggingface (HF provider) | Real fetch with no credential; optional keys (pubmed/s2/uspto/http_api) only raise rate limits |
| **Key-gated (9 groups, 10 distinct types)** | nyt, ap_api, reuters_mcp, unpaywall, core, youtube, spotify (id+secret), quandl, kaggle (username+key), email/email_imap | Real fetch blocked without the credential; gating map = `SOURCE_KEY_ENV_VARS` |

Key env vars (full names in `docs/dev/required-api-keys.md`):
`AUTOINFO_NYT_API_KEY`, `AUTOINFO_AP_API_KEY`, `AUTOINFO_REUTERS_API_KEY`,
`AUTOINFO_YOUTUBE_API_KEY`, `AUTOINFO_UNPAYWALL_EMAIL`, `AUTOINFO_CORE_API_KEY`,
`AUTOINFO_SPOTIFY_CLIENT_ID` + `AUTOINFO_SPOTIFY_CLIENT_SECRET`,
`AUTOINFO_QUANDL_API_KEY`, `KAGGLE_USERNAME` + `KAGGLE_KEY`,
`AUTOINFO_EMAIL_PASSWORD`. Optional rate-limit keys: `AUTOINFO_PUBMED_API_KEY`,
`AUTOINFO_S2_API_KEY`, `AUTOINFO_USPTO_API_KEY`, `AUTOINFO_HTTP_API_KEY`.

**Corrections against earlier drafts (source of truth = `config.py`
`SOURCE_KEY_ENV_VARS`, `src/autoinfo/collectors/*.py`):**

- `email` is an **alias** for the `email_imap` handler; both share
  `AUTOINFO_EMAIL_PASSWORD` and both appear in `VALID_SOURCE_TYPES`.
- The "9 key-gated groups" merges `unpaywall` + `core` (one handler file) and `email` +
  `email_imap` (alias). The config map lists **10 distinct key-gated source types**:
  ap_api, nyt, quandl, reuters_mcp, unpaywall, core, youtube, spotify, kaggle,
  email_imap.
- `pubmed`, `semantic_scholar`, `uspto`, generic `http_api` keys are **optional /
  rate-limit only** — do not gate on them (PubMed 3 req/s vs 10 req/s with key).
- `requires_key()` returns True only for ap_api, reuters_mcp, unpaywall, youtube. The
  other gated types (nyt, spotify, quandl, kaggle, core, email_imap) enforce at collect
  time via their env-var guard. Use `SOURCE_KEY_ENV_VARS` as the single gating map.
- `webhook` needs no key (HMAC secret optional via settings); `email_imap` can also read
  `email.password` from config instead of `AUTOINFO_EMAIL_PASSWORD`.
- `reddit` is a valid source type and is keyless (the `reddit.py` handler reads no
  credential env vars).

## 2.5 Full-Coverage Validation Matrix

The keystone. Nine phases, one table per phase. Columns:

```
# | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s)
```

Legend for **LLM key**: `no` = callable without a key; `yes` = needs a real LLM call;
`LLM-not-configured` = the tool returns `LLM_NOT_CONFIGURED` until the key is set (this
is itself a proof, see A4). Legend for **Scenario(s)**: the `src/autoinfo/mcp/scenarios/`
file(s) exercising the same feature (see §1.8); `run_validation_scenario` executes them,
but the matrix row additionally requires the real call and the artifact.

### Phase A: System, Config, Discovery, Error Envelope

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| A1 | System health + phase | MCP `diagnose_system()` **and** CLI `autoinfo doctor --verbose` | The JSON with `health_score` (0-100) + `phase` (`uninitialized` / `llm_unconfigured` / `no_sources` / `ready_to_collect` / `operational`) | no | system-health |
| A2 | BYOK LLM config | MCP `configure_llm(provider, model, api_key, base_url)` then read `.autoinfo/config.yaml` `llm:` block | The config.yaml `llm:` block with the key **redacted as `${AUTOINFO_LLM_API_KEY}`** (never the raw key) | no | projects-config |
| A3 | Discovery inventory | MCP `list_domains()`, `get_domain_schema("<domain>")`, `list_available_models()`, `list_available_platforms()`, `get_tool_count()` (also `get_effective_llm_config()`, `list_output_templates()`) | The JSON responses, including `get_tool_count` returning the **live tool count (146)** | no | discovery, output-discovery, system-health, domain-management, error-boundary |
| A4 | Error envelope probe | MCP `run_validation_scenario("error-boundary")` plus a direct probe: call an unknown tool and a missing-domain tool | The `{success:false, error:{code, message, actionable}}` JSON, e.g. `UnknownTool` and `DOMAIN_NOT_FOUND`; also an LLM-required tool (`suggest_keywords`) returning `LLM_NOT_CONFIGURED` while the key is unset | no | error-boundary, llm-gated |

### Phase B: Domain, Source, Topic, Keyword, Webhooks

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| B1 | Domain/source/topic CRUD | MCP `add_domain(name, description)`, `add_source(name, url, type, domain, ...)`, `add_topic(domain, name, keywords)`; confirm with `list_sources(domain)` and `list_topics(domain)` | New `domain:` / `source:` / `topic:` blocks in `.autoinfo/config.yaml` plus the list responses | no | domain-management, source-management, topic-management |
| B2 | Keyless collector real fetch | MCP `collect_sources(domain="<d>", topic="<t>", dry_run=false)` against a keyless source (rss, pubmed, hackernews, openalex, dblp, ssrn, sec_edgar, gdelt, etc.) | `collections/<domain>/<source>/*.json` raw cache files with real `source_url`, `source_type`, `source_platform`, plus the collection log line | no | collection, collectors-e2e |
| B3 | Keyed collector with env set | Export the source key (e.g. `AUTOINFO_NYT_API_KEY`), MCP `collect_sources` on that source | `collections/<domain>/<source>/*.json` raw cache from the keyed source | no | sources-a6-keyed |
| B4 | Source reachability + health + rating | MCP `test_source(source_id)`, `get_source_health(source_id)`, `rate_item(item_id, rating)` | The reachability JSON (status/items/error) for each source; rating persisted (visible in later search/ranking output) | no | source-management, collectors-e2e |
| B5 | LLM keyword suggestions | MCP `suggest_keywords(domain, topic, ...)` (real LLM) then `approve_keyword(domain, keyword)` / `reject_keyword(...)`, confirm `list_keywords(domain)` | The suggested-keyword JSON (LLM output) and the updated keyword list showing approve/reject took effect | yes | llm-gated, keyword-management |
| B6 | Topic grouping | MCP `topic_group_add(domain, group_name, topics)` then `list_topics(domain)` | JSON showing the new group and its members | no | topic-management |
| B7 | Domain webhook push | MCP `set_domain_webhooks(domain, webhook_urls=["http://127.0.0.1:8787/hook"])`; run a **local HTTP sink** (e.g. `python -m http.server`-style capture or a small listener) and `collect_sources` | The sink-captured POST body: per-item JSON with source provenance, delivered to the local sink | no | webhooks-alerts |

### Phase C: Collection Pipeline, Dedup, Cache

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| C1 | Collection preview + progress + stats | MCP `collect_sources(domain, dry_run=true)` (preview, no writes) then a real run; poll `get_collection_progress(job_id)`; then `get_collection_stats(period)` and `get_collection_diff()` | The dry-run preview JSON, the real-run job JSON, progress updates, and the stats/diff JSON with item counts | no | collection, collection-monitor |
| C2 | Dedup | `collect_sources` the **same URL twice** (or a second source emitting the same URL) and inspect the collection log | The dedup log line (`duplicate` / `skipped`), proving the second fetch was not stored | no | collection, collectors-e2e |
| C3 | Cache cleanup | MCP `clean_cache()` (also `autoinfo clean` CLI) | The cleanup result JSON and a directory listing showing the temp/cache dir emptied | no | collection, projects-config |

### Phase D: Processing, LLM Extraction, Quality Gates

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| D1 | Process with extraction | MCP `process_collection(domain, check_factual=true, check_translation=true)` (real LLM), poll `get_processing_progress(job_id)` | `knowledge/<domain>/01-Raw/*.md` files whose frontmatter contains `tl_dr`, `key_points`, `entities`, `summary`, `relevance`, `source_url` | yes | processing, collection |
| D2 | Quality gates G0-G5 + config | MCP `get_gate_config(domain)`, `set_gate_config(domain, gate, action, threshold)` then re-read; inspect processing output for gate outcomes and any `_failed/` item | The gate config JSON before/after, gate outcome lines in the processing log, and any `knowledge/<domain>/_failed/` item (if a gate blocked) | no | quality-gate-config |
| D3 | Custom extraction | MCP `extract_fields(domain, text, fields=[...])` (real LLM) and `get_extraction(entry_id)` | The extracted JSON with the requested fields; the stored extraction for a real entry | yes | kb-extraction, kb-lifecycle |
| D4 | G4 factual + translation QA flags | MCP `process_collection(domain, check_factual=true, check_translation=true)` | Log lines / KB frontmatter showing G4 factual-consistency verification and translation-QA flags on the processed entries | yes | processing, llm-gated |

### Phase E: KB Pipeline, Lifecycle, Graph, Search, Q&A

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| E1 | 4-tier pipeline Raw→Draft→Wiki | MCP `list_kb_tier(domain, tier)`; MCP `create_kb_draft(raw_ids=[...], title=..., summary=..., tags=[...])` (Raw→Draft only); MCP `promote_kb_draft` (agent promotion Draft→Wiki, KB-tier guard, no human gate) | The `knowledge/` tree showing `01-Raw/`, `02-Draft/`, `03-Wiki/` with real entries at each reached tier | no | kb-access, kb-draft |
| E2 | KB import | MCP `import_kb(domain, format, data)` for markdown / pdf / html / json (CLI parity: `autoinfo import-kb --file <f>`) | The new entries landed in `knowledge/<domain>/01-Raw/*.md` with provenance | no | kb-import-export |
| E3 | Versioning | MCP `get_entry_history(entry_id)`, `compare_versions(entry_id, version_a, version_b)`, `restore_entry_version(entry_id, version)` | History/diff JSON showing version deltas, and a restore confirming the content reverted | no | kb-versioning |
| E4 | Knowledge graph | MCP `query_knowledge_graph(domain, entity=...)` and `knowledge_graph_export(domain, format=...)` | The graph query JSON and the exported GraphML file on disk | no | kb-graph |
| E5 | Item relations | MCP `link_items(source_id, target_id, relation)` and `get_item_relations(entry_id)` | The link response and relations JSON | no | kb-graph |
| E6 | Knowledge lifecycle | MCP `mark_stale(entry_id)`, `calculate_freshness_score(domain)`, `get_domain_decay(domain)`, `find_similar_items(entry_id)`, `merge_items(ids, strategy)`, `recommend_content(user_id, ...)`, `simplify_content(content, target_level)` | The staleness/decay JSON, similarity ranking, merge result, recommendation list, and the simplified text (original vs target CEFR) | recommend + simplify: yes; rest: no | kb-lifecycle, output-simplify-recommend |
| E7 | Hybrid/vector/faceted/cross-domain search | MCP `search_knowledge_base(domain, query, mode="hybrid"\|"vector"\|"faceted", filters={...})`; omit `domain` for cross-domain | The ranked JSON results with scores, plus faceted filter counts and cross-domain hits | no | kb-access |
| E8 | Q&A with citations | MCP `query_collected(query)` (real LLM) | The synthesized answer with source citations referencing real 01-Raw entries | yes | kb-extraction |

### Phase F: Output Generation, All Formats, Schema Validation

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| F1 | Digest, all 7 formats | MCP `generate_digest(domain, format="markdown"\|"html"\|"json"\|"agent"\|"audio"\|"epub"\|"audiobook")` (7 calls, real LLM) | `outputs/digests/*.md`, `*.html`, `*.json`, agent JSON-LD, MP3, EPUB, audiobook ZIP | yes | output-digest-report, output-ebook |
| F2 | Report, all report types + formats | MCP `generate_report(domain, report_type="industry"\|"competitive"\|"trend"\|"daily-briefing"\|"column"\|"standard", format="markdown"\|"json"\|"html"\|"audio"\|"agent"\|"epub"\|"audiobook")` (7 MCP-valid formats; see Appendix A for the `video` nuance) | `outputs/` report artifacts for each type/format combination exercised | yes | output-digest-report, output-column, output-ebook |
| F3 | Cross-domain report | MCP `generate_cross_domain_report(domains=[...])` | The cross-domain report artifact whose content aggregates multiple domains | yes | output-digest-report |
| F4 | Tutorial | MCP `generate_tutorial(domain, format="markdown"\|"agent")` | `outputs/` tutorial md + agent JSON-LD | yes | output-tutorial-presentation |
| F5 | Presentation | MCP `generate_presentation(domain, format="markdown"\|"html"\|"mkslides"\|"agent")` (4 calls) | `outputs/` presentation md, standalone HTML (Reveal.js CDN), mkslides build, agent JSON-LD | yes | output-tutorial-presentation |
| F6 | Localization | MCP `localize_content(domain, text, target_language)` (real LLM) | The translated text artifact | yes | output-tutorial-presentation |
| F7 | Export, all 12 formats | MCP `export_kb(domain, format="markdown"\|"json"\|"sqlite"\|"csv"\|"pdf"\|"graphml"\|"rss"\|"agent"\|"bundle"\|"sitemap"\|"epub"\|"mobi")` (12 calls; `sitemap` requires `base_url`) | `exports/autoinfo-export-<domain>-<ts>.*` artifacts for every format (bundle = ZIP with PDF+JSON+MD+YAML) | no | kb-import-export |
| F8 | Agent JSON-LD schema validation | Run `jsonschema` against the const-pinned schemas for all 4 agent artifacts: `python3 -m jsonschema -i <digest>.json docs/schemas/knowledge-digest-v1.json` (likewise tutorial / presentation / base-export) | The 4 validated JSON-LD artifacts, each passing its `docs/schemas/*-v1.json` (const-pinned `@context` / `@type`) | no | evidence-only (no dedicated scenario; graded via the acceptance framework's agent-format evidence A7) |
| F9 | Audio / audiobook | MCP `generate_digest(domain, format="audio")` and `format="audiobook"` (chaptered MP3 + ZIP with ID3v2.3 CHAP/CTOC) | The MP3 file (playable / size non-zero), the audiobook ZIP, and the chapter metadata | yes | output-ebook |

### Phase G: Delivery, Scheduling, Cron, Agent Callbacks

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| G1 | Channel health, 13 channels | MCP `get_channel_health()` | The health JSON covering smtp, webhook, rest_api, file_export, discord, telegram, wechat_work, wechat_oa, dingtalk, feishu, rss, social_publish, push with health + latency | no | delivery-channels |
| G2 | Email digest to local SMTP sink | MCP `email_config(...)` then `generate_digest(domain, format="html")` then `send_email_digest(domain, period)` pointed at a **local SMTP sink**; then MCP `query_delivery_log()` / `get_delivery_log()` | The sink-captured message (headers + html body) and the delivery-log rows for the send | no | delivery-channels |
| G3 | Delivery schedule CRUD | MCP `add_delivery_schedule(domain, cron_expression, output_type, channel, output_format, ...)`, `list_delivery_schedules()`, `remove_delivery_schedule(...)` | The schedule list JSON before/after add and after remove | no | delivery-schedules |
| G4 | Cron schedules + health | MCP `add_schedule(name, cron, command)`, `run_schedules()`, `get_schedule_status()`, `list_schedules()`, `remove_schedule()`; CLI `autoinfo cron install` and `autoinfo cron health` | The schedule status JSON, the heartbeat JSON from `cron health`, and the crontab line (if installed) | no | cron-schedules |
| G5 | Agent push callback | MCP `set_agent_callback(agent_url="http://127.0.0.1:8788/cb", events=[...])`; generate/deliver to trigger; read the callback with a **local HTTP sink** | The sink-captured payload `{event, payload, schema_version: 1, trace_id, product_id}` plus `agent_outbox` rows in `autoinfo.db` | no | agent-callbacks |

### Phase H: End-User Lifecycle, Cost, Billing, Privacy

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| H1 | End-user lifecycle | MCP `enduser_create(user_id, name, email, ...)` → `activate_trial(end_user_id, days)` → `get_subscription_status(end_user_id)` → `check_trial_expiry(end_user_id)` → `update_preferences(end_user_id, ...)` / `get_preferences(end_user_id)` → suspend → cancel; CLI `autoinfo enduser list` | The lifecycle JSON at each stage (trial → active → suspended → cancelled) and `get_enduser_history(end_user_id)` | no | enduser-lifecycle, enduser-preferences |
| H2 | End-user delivery | MCP `send_to_enduser(end_user_id, product_id, channel)` then `query_delivery_log(end_user_id)` / `get_delivery_log(end_user_id)` | The delivery-log rows for that end user | no | enduser-lifecycle, delivery-channels |
| H3 | Cost governance | MCP `cost_dashboard(period)`, `cost_allocation(domain)`, `get_billing_summary()`, `get_budget_thresholds()`, `set_budget_thresholds(...)`; then `sqlite3 autoinfo.db "SELECT * FROM cost_log ORDER BY created_at DESC LIMIT 5;"` | The dashboard/allocation JSON and the raw `cost_log` rows (LLM tokens, storage, API calls) | no | cost-budget, products-billing |
| H4 | Checkout (billing) | MCP `create_checkout_session(product_id, end_user_id, mode="subscription"\|"payment", article_id=...)` against **stripe-mock** (`STRIPE_API_BASE` defaults to `http://localhost:12111`, key `sk_test_mock`); label as mock in evidence | The checkout-session JSON returned by stripe-mock | no | products-billing |
| H5 | Data privacy / GDPR | MCP `soft_delete_entry(entry_id, purge=false)` then `restore_entry(entry_id)`; `export_user_data(user_id)` → GDPR export JSON; `delete_user_data(user_id)`; then `soft_delete_entry(entry_id, purge=true)` | The restore confirmation, the GDPR export JSON file, and the purge confirmation; deletion-log / audit rows | no | data-privacy |

### Phase I: Governance, Observability, REST, Validation Meta

| # | Feature | Real-call method | Artifact to show director | LLM key | Scenario(s) |
|---|---------|------------------|---------------------------|:---:|-------------|
| I1 | Audit log | MCP `query_audit_log(actor=..., action=...)` and CLI `autoinfo audit query` | The audit rows (actor / action / tool / resource / trace_id) pulled from `autoinfo.db`, proving dispatch-level audit | no | observability |
| I2 | Per-item trace | MCP `trace_item(trace_id)` and CLI `autoinfo trace <trace_id>` | The full journey for one trace_id: collection → gates → KB → delivery | no | observability |
| I3 | Metrics | MCP `get_metrics()` and `get_prometheus_metrics()`; REST `curl http://localhost:8741/metrics` | The metrics JSON and the Prometheus text exposition from the REST endpoint | no | observability |
| I4 | Alert rules | MCP `add_alert_rule(domain, topic_keywords, relevance_threshold, channel, kind)` → `get_alert_rules()` → trigger a rule → `remove_alert_rule(...)` | The rules YAML file (persisted), the alert list JSON, and the dispatch log line when the rule fired | no | webhooks-alerts |
| I5 | REST API | Start `uvicorn autoinfo.api.server:app --port 8741`; `curl` each endpoint: `GET /health`, `GET /api/v1/entries`, `POST /api/v1/entries`, `GET /api/v1/entries/{id}`, `DELETE /api/v1/entries/{id}`, `GET /api/v1/search`, `GET /dashboard`, `GET /metrics` | The envelope JSON for each endpoint (success + error envelopes) and the dashboard HTML | no | rest-api |
| I6 | Validation meta-coverage | MCP `list_validation_scenarios()`; `run_validation_scenario` for all 68; then `python3 scripts/coverage_audit.py` | The 68-scenario inventory JSON, per-scenario results, and the audit report showing **146/146** covered with zero MISSING | no | meta-validation |

## 2.6 Step-by-Step Walkthrough

Run from the project root (`/mnt/d/贯维/AutoInfo`). The venv interpreter is
`.venv/bin/python`; the `autoinfo` console script must be on PATH.

### 2.6.1 Pre-flight (RED baseline first)

1. **Git cleanliness.** `git status --porcelain` must show no modified source files and
   no runtime artifacts. Runtime dirs (`collections/`, `knowledge/`, `outputs/`,
   `exports/`, `autoinfo.db`, `.autoinfo/`, `logs/`, `.omo/`) are gitignored and must
   **never** be committed. If the tree is dirty, stop and report to the director.
2. **No-keys profile.** Record the RED baseline (§0.4): with no BYOK keys, run
   `list_validation_scenarios()` (expect 68) then `run_validation_scenario` for every
   scenario; record the aggregate. Honest, recorded, never graded as pass.
3. **Configure the key.** `export AUTOINFO_LLM_API_KEY="sk-..."` then MCP
   `configure_llm(...)`; confirm with `get_effective_llm_config()`.
4. **Re-run the 15 env-gated scenarios to GREEN** (list in §0.4); each must report
   `passed`, not `unconfigured`.
5. **Start the REST server** for http steps: `uvicorn autoinfo.api.server:app
   --port 8741` (needed by the `rest-api` scenario and Phase I).

### 2.6.2 Per-matrix-row loop

For **every** row in §2.5 (A1 → I6):

```
RED   → record the honest negative (unconfigured / absent artifact / failing call)
CALL  → make the real call exactly as the row prescribes
GREEN → assert the expected shape AND confirm the artifact exists
SHOW  → surface the artifact to the director (§2.8); GREEN is not final until shown
CLEAN → run the paired cleanup for every mutating call; verify with list_* + git status
```

Rules inside the loop:

- Execute rows in order A → I where a row depends on earlier state (e.g. D1 needs C1's
  collected items; E1 needs D1's processed raws).
- One mutating call, one cleanup. Every `add_*` / `create_*` / `set_*` /
  `soft_delete_entry` has a paired `remove_*` / `delete_*` / `restore_*` / `reject_*`,
  verified by the corresponding `list_*` and a clean `git status --porcelain`.
- Prefer idempotent reads for re-verification: `list_*`, `get_*`, `search_*`.
- If a row depends on a key you do not have, record `unconfigured` with the env var
  name, flag it to the director as a BYOK obligation, and move on. Never fake the row
  (§0.3).

### 2.6.3 Final sweep

1. Re-run all 70 scenarios with keys configured — all must report `passed` (expect 0
   failed, 0 unconfigured).
2. Run `python3 scripts/coverage_audit.py`; report **146/146 covered, zero MISSING**.
3. Cleanup sweep: re-run every scenario's `cleanup_steps` result (they run
   automatically), remove any leftover test domain/source/topic/end-user, and confirm
   `git status --porcelain` shows only the intended deliverable.
4. Produce the director summary table (§2.8.2) and hand the run report skeleton to the
   director per `docs/dev/acceptance-framework.md` §8 (per-dimension verdict table +
   executive summary + blocker list).

## 2.7 Evidence Rules

### 2.7.1 RED→GREEN discipline

- **Honest negative first.** For every row, the RED state is recorded before the GREEN
  state. A row that jumps straight to GREEN with no recorded negative (when a negative
  existed) is suspect.
- **Never fake-pass, never silently skip, unconfigured is not GREEN.** A call that fails
  is recorded as failed with the actual error; an `unconfigured` result is recorded as
  `unconfigured`. Neither is ever rewritten as a pass, and a row that ends at
  `unconfigured` is not complete (§0.3).
- The real-surface rule (which surfaces count as acceptable evidence) is §0.2.

### 2.7.2 Cleanup rule

- Every mutating call has a paired cleanup call (scenarios already encode this via
  `cleanup_steps`, see §1.3).
- After each phase, verify with the corresponding `list_*` and `git status --porcelain`
  that nothing leaked.
- Never commit runtime artifacts. The validator leaves the working tree as clean as it
  found it, plus the documentation deliverable.

## 2.8 Director Surfacing Protocol

> **UNMISSABLE INSTRUCTION: The validating agent MUST show the director all raw data
> and all processed data. Quote real content, not summaries.** After every phase, paste
> to the director: (1) the actual raw JSON from `collections/<domain>/<source>/*.json`,
> (2) the KB markdown file content at each tier reached under `knowledge/`, (3) the
> generated output artifacts under `outputs/` and `exports/`, (4) `sqlite3 autoinfo.db`
> query output for the audit, cost, delivery-log, and agent_outbox tables, and (5) the
> email/audio artifacts (sink-captured message body, MP3 file info). The director must
> see the project's real data flowing through the real pipeline. A summary of what you
> did is not evidence; the raw bytes are.

### 2.8.1 What to show, per artifact class

| Artifact class | Where it lives | Show |
|----------------|----------------|------|
| Raw collection cache | `collections/<domain>/<source>/*.json` | The full JSON of 1-3 items: `source_url`, `source_type`, `source_platform`, title, content excerpt |
| 4-tier KB | `knowledge/<domain>/01-Raw/`, `02-Draft/`, `03-Wiki/` | The frontmatter + body of a real entry per reached tier |
| Generated outputs | `outputs/` (digests, reports, tutorials, presentations), `exports/` (all 12 formats) | File paths, file sizes, first page / head of the artifact, JSON-LD `@type` |
| SQLite evidence | `autoinfo.db` | `sqlite3 autoinfo.db "..."` output for `audit_log`, `cost_log`, `delivery_log`, `agent_outbox`, `kb_entry` (or the real table names) |
| Email / audio artifacts | local SMTP sink capture, `outputs/**/*.mp3`, audiobook ZIP | The captured message headers + body; MP3 size/duration; ZIP contents |
| Network proof | local HTTP sink capture | The received POST/PUT payloads (webhook, agent callback) |

### 2.8.2 Final director summary table

Deliver this table to the director at the end of the walkthrough:

| Phase | Artifact path(s) | Verdict |
|-------|------------------|---------|
| A System/config/discovery | `...` | PASS / FAIL / unconfigured |
| B Domain/source/topic/keyword | `...` | |
| C Collection/dedup/cache | `...` | |
| D Processing/extraction/gates | `...` | |
| E KB pipeline/lifecycle/search | `...` | |
| F Output all formats | `...` | |
| G Delivery/scheduling/cron/callbacks | `...` | |
| H End-user/cost/billing/privacy | `...` | |
| I Governance/observability/REST/meta | `...` | |

Plus the two hard meta-results:

- Scenario suite: **68/68 passed** (0 failed, 0 unconfigured) with keys set.
- `scripts/coverage_audit.py`: **146/146 MCP tools covered, zero MISSING**.

## 2.9 QA Checklist (Pre-Handoff)

Before handing off to the director, verify all of the following:

- [ ] Every row in §2.5 (A1 through I6) was executed with a real call. No row skipped.
- [ ] RED was recorded before GREEN for every row.
- [ ] Every GREEN has a real artifact on disk / DB / log / sink, and that artifact was shown to the director (pasted or absolute path).
- [ ] No `unconfigured` row was graded as a pass; each missing key was surfaced as a BYOK obligation.
- [ ] All 70 scenarios re-run GREEN with keys configured (0 failed, 0 unconfigured); `python3 scripts/coverage_audit.py` reports 146/146 with zero MISSING.
- [ ] All 8 REST endpoints exercised via `curl` against `uvicorn autoinfo.api.server:app --port 8741`.
- [ ] All mutating calls have paired cleanup, verified by `list_*` and `git status --porcelain`.
- [ ] Runtime artifacts (`collections/`, `knowledge/`, `outputs/`, `exports/`, `autoinfo.db`, `.autoinfo/`, `logs/`, `.omo/`) are NOT committed and the working tree is clean.
- [ ] Local sinks (HTTP / SMTP / stripe-mock) are labeled as sinks in the evidence.
- [ ] Agent JSON-LD artifacts validate against `docs/schemas/*-v1.json` (4 artifacts).
- [ ] Director summary table (§2.8.2) filled with real paths and verdicts.
- [ ] English, tables, and relative `docs/dev/*.md` links follow repo conventions.

---

## Appendix A: Output Format Matrix

Source of truth: `src/autoinfo/output/__init__.py` (verified at the format validation
lines 329, 2515, 2980, 4474, 4769) and the MCP tool schemas in
`src/autoinfo/mcp/server.py`. Product templates: `PRODUCT_TEMPLATES`
(`src/autoinfo/output/__init__.py` line 2070): 8 templates: digest, report, tutorial,
presentation, premium-briefing, column, magazine-digest, enterprise-briefing.

| Generator | Formats (count) | Formats | Artifacts |
|-----------|:---:|---------|-----------|
| `generate_digest` | 7 | markdown, html, json, agent, audio, epub, audiobook | `.md`, `.html`, `.json`, JSON-LD (`@type: KnowledgeDigest`), MP3, EPUB, audiobook ZIP (chaptered MP3, ID3v2.3 CHAP/CTOC) |
| `generate_report` | 8 (function) / 7 (MCP schema enum) | markdown, json, html, audio, agent, video, epub, audiobook | report artifacts; `report_type`: standard, industry, competitive, trend, daily-briefing, column |
| `generate_tutorial` | 2 | markdown, agent | `.md`, JSON-LD (`@type: KnowledgeTutorial`) |
| `generate_presentation` | 4 | markdown, html, mkslides, agent | Reveal.js markdown, standalone HTML (CDN), mkslides build, JSON-LD (`@type: KnowledgePresentation`) |
| `export_kb` | 12 | markdown, json, sqlite, csv, pdf, graphml, rss, agent, bundle, sitemap, epub, mobi | `exports/autoinfo-export-<domain>-<ts>.*`; bundle = ZIP (PDF+JSON+MD+YAML); sitemap requires `base_url`; JSON-LD (`@type: KnowledgeBaseExport`) |

**Corrections against earlier drafts:**

- The report generator function accepts **8** formats including `video`
  (`src/autoinfo/output/__init__.py` line 2980), but the MCP schema enum for
  `generate_report` lists **7** (`src/autoinfo/mcp/server.py` lines 7906-7965, missing
  `video`). Both facts are recorded; the function is the source of truth for execution,
  the MCP enum is the source of truth for the tool surface. The same note is recorded
  in the acceptance framework's rendered-artifact evidence (A6/A7).
- `export_kb` validates 12 formats; the MCP schema enum confirms all 12 including
  `sitemap` and `mobi`.
- JSON-LD schemas live in `docs/schemas/`: `knowledge-digest-v1.json`,
  `knowledge-tutorial-v1.json`, `knowledge-presentation-v1.json`,
  `knowledge-base-export-v1.json` (const-pinned `@context` / `@type`).

## Citation Traps (verified against source 2026-08-14)

> Merged from the archived general guide `docs/archive/agent-tester-validation-guide.md` §8.3. Every item looks correct and is wrong; do not cite any of them.

1. `src/autoinfo/mcp/scenarios/regression/regression-collect-int-id.yaml` does not exist. The FILE is `collect-int-id.yaml` inside `regression/`; only the scenario's `name:` field is `regression-collect-int-id`. The same file-vs-name split holds for all 6 regression files.
2. `validation-runs/latest.json` does not exist. The actual pointer is `latest.txt` (refreshed at validation.py line 88).
3. There is no `REGRESSION:` keyword field. The YAML marker is the boolean `regression: true` plus `regression_issue: "#NN"` (see `collect-int-id.yaml` lines 17-18).
4. This document's path is `docs/dev/validation-scenario-contract.md`, not `docs/dev/specs/validation-scenario-contract.md`. The evidence contract is not under `specs/`.
5. `scripts/validation_diff.py` needs at least 2 persisted runs, and `validation-runs/` is runtime-gitignored. Cite it as a trend tool over an existing local history, not as always-runnable on a fresh clone.

## Related Documents

- `AGENTS.md` (root): operating model, 146-tool catalog, architecture rules
- `README.md` (root): feature inventory, status table, CLI/MCP tables
- `docs/dev/acceptance-framework.md`: **grading authority** (AC1-AC9), verdict
  semantics, evidence catalog A1-A24, AC7 process & governance
- `docs/archive/launch-validation-framework.md`: D1-D5, superseded as charter; archived
  evidence-production tooling (SUSPECT table, run-report skeleton)
- `docs/dev/required-api-keys.md`: every environment variable (31 `AUTOINFO_*` + provider keys)
- `docs/dev/mcp-usage-examples.md`: worked MCP workflows
- `docs/dev/cross-dimensional-catalog.md`: keystone product matrix (A1-A7 × B1/B2/B3)
- `docs/dev/enduser-coverage-matrix.md`: end-user feature coverage matrix
- `docs/dev/specs/mcp-tools.md`, `docs/dev/specs/pipeline.md`,
  `docs/dev/specs/delivery.md`, `docs/dev/specs/quality-gates.md`,
  `docs/dev/specs/operations.md`: extracted specs
- `docs/schemas/*-v1.json`: JSON-LD validation schemas
