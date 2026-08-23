# Acceptance Run Report 2026-08-08 (First Run)

Run by: **B2 agent-as-tester** | Reviewed by: **B3 director (pending — adjudication required)**
Baseline (no keys): recorded per-scenario as `unconfigured` — never passed (see A24)
Keys configured: `AUTOINFO_LLM_API_KEY` in `.autoinfo/config.yaml` (provider=openai, model=deepseek-v4-flash, base_url=https://opencode.ai/zen/go/v1 — verified working with a real call); `STRIPE_API_KEY` / `FRED_API_KEY` / `FINNHUB_API_KEY` **not** configured
Evidence: `validation-runs/2026-08-08_acceptance/evidence/` (34 artifacts, A1-A24)
Framework: `docs/dev/acceptance-framework.md` (AC1-AC9, keystone)

## Verdicts

| Dimension | Verdict | Notes |
|-----------|:---:|-------|
| AC1 User model integrity | **FAIL** | Human-only ops not code-gated (B-01); CLI portal preferences crash (B-02); typed preference path works (positive) |
| AC2 Data-layer integrity | **FAIL** | Provenance missing on 8/27 raw entries incl. simulated URLs (B-03) |
| AC3 Dual orientation | **RISK** | Agent track 5/5 JSON-LD valid + 142/142 covered; human track: tutorial markdown empty-state (B-04); export agent CLI crash (B-05) |
| AC4 Coverage commitment | **PASS** | 99/99 items classified, 0 unclassified (OK 73 / PART 16 / BLK 2 / OOS 8) |
| AC5 Quality & deliverables | **RISK** | Gates run on code defaults, no config recorded (R-01); director sampling reads pending (B3) |
| AC6 Commercial viability | **RISK** | Lifecycle E2E passed (A16) + cost visibility OK; payment path unconfigured (Stripe) |
| AC7 Process & governance | **PASS** | First full run executed per framework; B3 adjudication pending is the expected state |
| AC8 Documentation health | **PASS** | `doc_inventory --check` exit 0 (5/5 facts, no test_bug, fresh); one-offs archived |
| AC9 Test & validation health | **FAIL** | Regression baseline 1/5 (B-06); 8 LLM-gated scenario failures incl. ebook CJK defect (B-07) |
| **Overall** | **FAIL (blocked)** | Any FAIL/RISK blocks sign-off; findings below are for B3 disposition |

## Executive summary

First full acceptance run against the new AC1-AC9 framework. The **framework itself executed correctly**: 34 real evidence artifacts, real MCP/CLI/REST/LLM calls, honest `unconfigured` recording, no fabricated passes. Two dimensions pass outright (AC4 coverage commitment: 99/99 classified; AC8 documentation health: automated checks green). The blocker cluster is real engineering debt, not framework noise: the regression flywheel no longer protects its own bugs (4/5 stale), the KB contains provenance-polluted entries left by earlier validation runs (simulated `example.com` URLs in the real 01-Raw tier), human-only KB operations are not machine-enforced, the ebook EPUB path rejects non-ASCII (CJK) content despite its documented CJK support, and three CLI surfaces crash (portal preferences ×2, export agent). None of these block the *product thesis*; all are actionable. B3 disposition required on 7 blockers + 1 risk + the AC5 sampling read.

## Blockers (findings only — B3 decides remediation)

- **[B-01] AC1 | Criterion 3** — Human-only operations are not code-gated.
  Finding: `promote_kb_draft` (Draft→Wiki) and `remove_domain` are exposed on the MCP surface with **no code-level human gate** (docstring/contract only). `soft_delete_entry` purge and `remove_source` are protected only by parameter flags (purge=True / confirm=True). An agent can call all four today.
  Source: `src/autoinfo/mcp/server.py` (promote ~7943/2504, remove_domain ~7043/1526, soft_delete ~9586/5149, remove_source); evidence `ac1_human_only_ops.txt`.
  Severity: **major** — contract-level enforcement contradicts AC1 criterion 3's "enforced at the code level". Adjudicable: the design intent (CD-029) is that agents *do* reach 03-Wiki via promote_kb_draft with a KB-tier guard; B3 decides whether to amend the criterion wording or add a code-level human gate.

- **[B-02] AC1 | Criterion 5 / B1 self-service** — CLI portal preferences crash.
  Finding: `autoinfo portal preferences show --json` and `update` crash with `AttributeError: 'UserProfile' object has no attribute 'delivery_prefs'` (cli/portal.py:49,58). Also, the CLI's `--delivery-prefs` writes the legacy `delivery_prefs` column, never the typed `preferences` store read by `get_preferences` — so the CLI cannot set `content_preference` at all. The typed path (MCP `update_preferences`/`get_preferences`) works correctly incl. validation + `actionable` errors.
  Source: `src/autoinfo/cli/portal.py:49,58`, `user_store.update_profile/get_preferences`; evidence `ac1_preferences.txt`.
  Severity: **major** — B1 self-service surface broken; agent path unaffected.

- **[B-03] AC2 | Criterion 3** — Raw-entry provenance incomplete; simulated URLs in the real KB.
  Finding: 8 of 27 `01-Raw` entries in medical-research fail mandatory provenance — 7 missing `source_platform`, 1 missing both `source_url` and `source_platform` (a `qa-article`); several carry `https://example.com` / `https://example.org` simulated URLs with `source_type: web|import` (left by earlier validation-scenario runs, SUSPECT S4 confirmed live). REST `/api/v1/entries` returns these entries with empty `source_platform`.
  Source: `knowledge/medical-research/01-Raw/` (8 failing files listed in `ac2_provenance.txt`); REST smoke `ac1_rest_smoke.txt`.
  Severity: **major** — violates AC2 provenance + P3 authenticity (simulated data in real store).

- **[B-04] AC3 | Criterion 3 (human track)** — Tutorial markdown generation fails (2/2).
  Finding: `autoinfo output tutorial --domain medical-research --audience student` renders an honest empty state (`_No objectives defined._`) with stderr `Failed to parse LLM digest response as JSON:` — on a populated KB. Counter-evidence: the same tutorial in `format="agent"` produced complete content (7560 B, validated against its schema) — the LLM call succeeds; only the markdown-path JSON parser rejects this model's response (systematic with deepseek-v4-flash via this endpoint).
  Source: `src/autoinfo/output/` tutorial markdown renderer; evidence `ac6_tutorial_student.md` (+retry), `ac7_tutorial_agent.json`.
  Severity: **major** — one PROCESSED product form (tutorial, markdown) cannot produce human-readable content with the configured model.

- **[B-05] AC3 | Criterion 1/evidence** — CLI `export --format agent` crashes.
  Finding: `autoinfo output export --domain medical-research --format agent` → exit 1, `KeyError: 'entries_count'` (cli/output.py:172) — `_export_agent_json()` returns the JSON-LD payload directly (never a file) while the CLI unconditionally reads `result['entries_count']`/`result['path']`. The payload itself is well-formed and validates.
  Source: `src/autoinfo/cli/output.py:172`, `src/autoinfo/output/__init__.py` `_export_agent_json`; evidence `ac7_agent_format.txt`.
  Severity: **minor-major** — agent-format export unreachable via CLI; MCP/function path works.

- **[B-06] AC9 | Criterion 4 (regression)** — Regression flywheel broken: 1/5 pass.
  Finding: 4 of 5 regression scenarios fail on stale assumptions:
  - `regression-llm-key-resolution` (#119): `ImportError: cannot import name 'LLMClient' from 'autoinfo.llm'` — guarded symbol removed.
  - `regression-period-enum` (#126) + `regression-report-structure` (#121): assert `env.data` dict but handlers return a flat envelope (`data is not a dict: got NoneType`) — envelope-contract drift.
  - `regression-collect-int-id` (#104): `chdir`/path assumption stale (`collections/regression-104/... not in subpath of tmp`).
  Only `regression-source-301` (#135) passes. The flywheel no longer protects the guarded bugs.
  Source: `src/autoinfo/mcp/scenarios/regression/`; evidence `ac24_scenario_run.txt`.
  Severity: **major** — AC9 criterion 4 violated; regression guards are dead weight until repaired.

- **[B-07] AC9 / AC3 / AC2 | output-ebook** — EPUB path rejects non-ASCII (CJK) content.
  Finding: `output-ebook` scenario fails 4/4: steps 1/3 `ValidationError: string argument should contain only ASCII characters` in the EPUB path — **the feature documented for CJK support (`set_language` + xhtml output) cannot process non-ASCII content**; steps 2/4 `OpenAI TTS network error: [Errno 101] Network is unreachable` (env limitation, not a defect).
  Source: `src/autoinfo/output/ebook.py`; evidence `ac24_scenario_run.txt` (output-ebook rows).
  Severity: **major** — contradicts B23's documented CJK support; content-language-specific defect.

- **[R-01] AC5 | Criterion 2** — No quality-gate configuration recorded.
  Finding: `.autoinfo/config.yaml` has no `quality_gates`/`delivery_gates` sections; all gates run on code defaults (soft: retries=0, action=flag; G3 archive; G0/G4 hard retry→block, default retries 1). Processing run showed soft-gate behavior (G2 dedup flag, G3 score 100, G4 enabled no block). No live hard-gate block demonstrated this run (`_failed/` exists from prior runs).
  Source: `.autoinfo/config.yaml`, `src/autoinfo/config.py` defaults; evidence `ac5_gates.txt`, `ac5_processing_gates.txt`.
  Severity: **minor** — gates work but "configuration recorded" criterion unmet; recommend persisting explicit gate config.

## Honest unconfigured (recorded, never passed)

| Item | Reason | Re-run trigger |
|------|--------|----------------|
| products-billing / E2 | `STRIPE_API_KEY` absent — billing fails closed | Stripe test key or stripe-mock |
| sources-a6-keyed / A6 | `FRED_API_KEY` + `FINNHUB_API_KEY` absent | Free keys (1h to obtain) |
| output-premium-products | requires `general-news` domain (not configured in this project) | Configure domain or accept scope |
| kb-extraction llm_assert | judge returned non-JSON + `query_collected` found no citations on populated KB — **recorded as FAIL not unconfigured** (LLM was available) | Investigation (B3) |

## AC5 — Director sampling read list (B3, human-as-end-user)

Read these real artifacts and record a verdict (PASS/RISK/FAIL) per the four concerns (accuracy / depth / freshness / presentation) from `market-positioning.md`:

| Form | Artifact | Concern focus |
|------|----------|---------------|
| Digest (weekly, md) | `evidence/ac6_digest_weekly.md` | synthesis accuracy; timeliness of 14-entry window |
| Report (md + html) | `evidence/ac6_report_standard.md` / `.html` | depth; theme grouping quality |
| Report (PDF) | `evidence/ac6_export_pdf.pdf` | presentation; readability |
| Presentation (md) | `evidence/ac6_presentation_crispr.md` | clarity; speaker-note quality |
| Tutorial (md) | `evidence/ac6_tutorial_student.md` | **expected FAIL-ish** (empty state — see B-04) |

## AC7 — Adjudication list for B3

1. B-01: amend AC1 criterion 3 wording (design intent: agent-escorted promote) **or** require code-level human gate?
2. B-02 / B-05: fix CLI defects (portal preferences, export agent) or declare CLI fallback-only and route B1 through MCP?
3. B-03: purge/reprovenance the 8 polluted entries (who owns the cleanup — agent may not delete Wiki, but 01-Raw entries are agent-editable)?
4. B-04: tutorial markdown parser fix vs model-config workaround (`reasoning_model: true`)?
5. B-06: repair or archive the 4 stale regression scenarios (regression flywheel integrity)?
6. B-07: EPUB non-ASCII defect — fix `ebook.py` or scope CJK out?
7. R-01: persist explicit gate config to `.autoinfo/config.yaml` (via `set_gate_config` MCP) or accept code defaults as recorded?

## 中文摘要（Director）

首次按 AC1-AC9 全维度审查完成：框架本身运转正确——34 份真实证据、真实 MCP/CLI/REST/LLM 调用、unconfigured 如实记录、零造假通过。**两项直接通过**：AC4 覆盖承诺（99/99 项全分类，未分类=0）、AC8 文档健康（doc_inventory --check 全绿）。**阻塞项是真实工程债，非框架噪音**：
- **回归飞轮失效（4/5 陈旧）**——#119 引用的符号已删除、#126/#121 信封契约漂移、#104 路径假设过时；
- **KB 溯源污染**——8/27 条 01-Raw 缺 source_platform，且含验证场景残留的 `example.com` 模拟 URL（真实 KB 中的模拟数据）；
- **人工专属操作无代码级门**——promote_kb_draft/remove_domain 可被 Agent 直接调用；
- **EPUB 拒绝非 ASCII 内容**——与 B23 文档宣称的 CJK 支持矛盾；
- **三处 CLI 崩溃**——portal preferences（show/update）、export --format agent；
- **tutorial markdown 空态**（2/2 失败，agent 格式却完整）——模型/解析器兼容问题。

整体判定 **FAIL（阻塞签收）**，符合预期：这正是框架的用途——把问题摆上桌，由你（B3）裁定处置。支付（Stripe）、FRED/Finnhub 如实记 unconfigured，待凭证后补跑。AC5 抽样阅读清单与 AC7 裁定清单见上表，等你逐项拍板。

- **[B-08] AC9 / AC7 | Scenario step timeout does not kill spawned subprocesses.**
  Finding: the `cli-llm` scenario's step1 (`autoinfo process --batch-size 0 --json`) exceeded its 180 s per-step budget; the scenario step timed out, but the spawned CLI subprocess survived as an orphan for 37+ minutes at ~98% CPU (`process --batch-size 0` = process all 34 cached items, unbounded). Killed by the tester after detection. Per-step timeouts must terminate child processes.
  Source: `src/autoinfo/mcp/validation.py` step timeout handling; observed process `205841`.
  Severity: **minor-major** — resource leak under scenario execution; batch-0 semantics unbounded.

---

## B3 Adjudication (2026-08-08, director corrections) — appended after first-run verdicts

The director issued two corrections to the acceptance framework that re-scope three first-run findings. Framework amended accordingly (see `acceptance-framework.md` §0.3 KB orientation, AC1 criterion 3, AC6 phase split, §0.7 provenance).

1. **KB promotion is an agent operation** (correction 1). AutoInfo's KB is a **database** for raw/processed data production, not a human-curated knowledge base; the three-tier model is borrowed from human KM practice, and in AutoInfo the tiers are production stages. Draft→Wiki promotion is executed by the agent (`promote_kb_draft`, KB-tier guard, **no human gate**) — maximum automation, agent as user. A director promote/approval step would cripple production throughput.
   - **B-01 re-scoped → resolved for `promote_kb_draft`.** Agent-callable promotion is now *correct design*, not a violation; AC1 criterion 3's human-exclusive class is narrowed to destructive ops (permanent purge, domain/source removal). **AC1 verdict: FAIL → RISK** — the surviving finding is that `remove_domain` has no confirm guard (purge/remove_source remain param-gated; recommendation: add `confirm` to `remove_domain` for parity).
   - **B-02 unchanged** (CLI portal preferences crash is a real defect independent of the KB rule).
2. **Payment chain is V2** (correction 2). V1 validation covers the **collection + production pipeline** only; the full payment chain (Stripe checkout, webhooks, entitlement, invoicing, lifecycle billing) is V2 scope. AC6 amended with a V1/V2 phase split.
   - **AC6 re-scored: RISK → PASS (V1 scope).** V1 criteria — products producible from real content (A11/A6 evidence: RAW+PROCESSED product types, real rendered artifacts), cost visibility (A18: $9.11/1880 logs) — hold. The unconfigured `products-billing` (Stripe) item is no longer a V1 risk; it becomes a V2 binding criterion to be evidenced at V2 launch. Lifecycle E2E (A16 passed 2/2) remains an informational positive in V1.
   - **AC6 overall: PASS (V1) with V2 payment deferred.**

### Re-scored verdict table

| Dimension | First-run verdict | Adjudicated verdict |
|-----------|:---:|:---:|
| AC1 User model integrity | FAIL | **RISK** (only `remove_domain` guard finding survives) |
| AC6 Commercial viability | RISK | **PASS (V1 scope); V2 payment deferred** |
| Overall | FAIL | **RISK** (remaining blockers: B-02 CLI portal, B-03 KB pollution, B-04 tutorial, B-05 export CLI, B-06 regression flywheel, B-07 epub CJK, B-08 orphan process; R-01 gate config) |

All other findings (B-02…B-08, R-01) stand as first-run findings awaiting B3 disposition.

## B-class Closure Status (KB-curation gap-closure wave, 2026-08-08)

The following first-run findings have been **fixed and verified closed** by the
KB-curation gap-closure implementation wave (T3/T9/T11/T12). Fixes are code +
scenario-level; this note records the closure against the original matrix.

| Finding | Fix (task) | Closure evidence | Status |
|---------|-----------|------------------|:---:|
| B-03: Raw-entry provenance incomplete (8/27 missing `source_platform`) | Admission gate requires `source_url`/`source_type`/`source_platform` on every Raw (`promotion.py:180-181` `_has_provenance`; `kb-promote-admission` + `promotion-provenance` scenarios) | T3 fix + scenario coverage | **CLOSED** |
| B-04: Tutorial markdown empty-state (agent-format JSON parse) | Agent-format empty guard in CLI/output (`cli/output.py` `.get` defaults, `output/__init__.py` `_render_agent_json`) | T11 fix | **CLOSED** |
| B-05: CLI `export --format agent` crashes (`KeyError: 'entries_count'`) | `cli/output.py:172-173` uses `result.get('entries_count', 0)` / `result.get('path', 'unknown')` | T11 fix (B-04 guard covers B-05) | **CLOSED** |
| B-06: Regression flywheel 1/5 (4 stale scenarios) | 4 regression scenarios repaired (collect-int-id #104, llm-key-resolution #119, period-enum #126, report-structure #121) | T9 fix; `coverage_audit.py` reports 5 regression, issues #104/#119/#126/#121/#135 | **CLOSED** |
| B-07: EPUB rejects non-ASCII/CJK (`set_language` hardcoded) | `ebook.py` `render_epub(..., lang)` parameterizes language, `book.set_language(lang)` + per-chapter `lang` | T11 fix (see B-07 evidence in T11 assert) | **CLOSED** |
| B-08: Scenario step timeout orphans subprocess | `validation.py` `_kill_process_group()` + `start_new_session=True` in `Popen` | T11 fix (see B-08 evidence in T11 assert) | **CLOSED** |
| query_collected CWD trap (`KBStore()` unstable base_path) | `kb.py:2188` `_default_kb_base_path()` — project-root-relative default, `KBStore()` resolves to `<root>/knowledge` regardless of cwd | T11 fix | **CLOSED** |
| FRED_API_KEY undocumented | `required-api-keys.md:53` — FRED_API_KEY row (free reg, `auth_mode: query`, gates `sources-a6-keyed`) | T12 doc fix | **CLOSED** |

**Still open (out of scope for this wave):** B-01 `remove_domain` confirm guard
(only surviving AC1 finding, adjudicated RISK), B-02 CLI portal preferences wire
rename (T11 wire-level fix verified; B3 disposition on the CLI surface remains),
R-01 explicit `quality_gates` config persistence in `.autoinfo/config.yaml`
(gates run on code defaults; set via `set_gate_config` if B3 opts to record).
