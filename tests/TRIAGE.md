# Failure Triage — 2026-08-05 (Task M0T1)

Gate artifact for `agent-orientation-plus-coverage` plan. Classifies **every**
currently-failing test (83 failures + 1 error) so later waves can fix them in
order. This table **supersedes** the stale CI note in
`.github/workflows/ci.yml` ("27 pre-existing baseline failures triaged in #117").

## Baseline (verified 2026-08-05, full run)

```
83 failed / 2707 passed / 11 skipped / 3 deselected / 1 error in 427.30s (0:07:07)
```

- Command: `.venv/bin/python -m pytest -q --ignore tests/cost/test_stripe.py -m "not real_api" --durations=20`
- Full output: `/tmp/opencode/triage-full.txt`
- Collection: **2804 collected, 0 collection errors** under the same flags
  (baseline `pytest --collect-only -q` without exclusions = **2855**; the 51
  delta = `tests/cost/test_stripe.py` (51 tests) excluded here — see Count reconciliation below).
- Failure count is **identical** to the plan baseline (83F + 1E) — no new failures, no stale-failure drift.

## Count reconciliation (2855 vs 2804)

| Fact | Value |
|---|---|
| Plan baseline `--collect-only -q` (no exclusions) | 2855 collected, 0 errors |
| This run: `--collect-only -q --ignore tests/cost/test_stripe.py -m "not real_api"` | 2801/2804 collected, 3 deselected |
| Delta | 51 = `tests/cost/test_stripe.py` (51 tests; stripe is a core dep so the module imports fine — excluded per run convention) |
| `real_api` deselected | 3 (`tests/test_real_api.py`, marked `real_api` + `requires_llm_key`) |
| Full suite (this run) | 83 failed / 2707 passed / 11 skipped / 3 deselected / 1 error |

Note: the plan baseline "83 failed / 2752 passed / 20 skipped / 1 error in 432s"
was captured with **no** `--ignore`/`-m` exclusions. The failure set is
byte-identical to this run's; only passed/skipped/deselected composition
differs (stripe tests + real_api deselection).

## Skip-count ceiling (baseline)

- **20 skipped** is the asserted ceiling (plan-verified baseline).
- This run (with exclusions) reports **11 skipped** — composition:
  `tests/output/test_video_integration.py` module-level `pytest.importorskip("PIL")` (1),
  `tests/test_digest.py` typer-on-Py3.14 skips (4),
  `tests/test_report.py` typer-on-Py3.14 skips (5),
  `tests/test_pubmed_handler.py` missing-VCR-cassettes skip (1).
- **Rule: no new skip may be added without a triage tag and without raising the
  ceiling.** All future skip gates (M0T3) must be tagged and counted against 20.

### Ceiling update — M0T3 (2026-08-05): 20 → 25 (per-test justification)

M0T3 applied 14 new tagged skips (all converting **current failures** to skips, none
touching a passing test). New totals: 11 baseline + 14 = **25 skipped** in the
excluded run (34 in an unfiltered run). Justification per test (root causes from this
table; env lacks PyMuPDF — `pip install -e ".[pdf]"` runs them):

| Test | Row(s) | Why skipped (not failed / not installed) |
|---|---|---|
| `tests/test_pdf_handler.py` — `test_extract_returns_items`, `test_small_pdf_single_item`, `test_large_pdf_multiple_chunks`, `test_content_from_all_pages`, `test_source_name_propagates`, `test_file_not_found` | #2-7 | PyMuPDF absent → `fitz = None` at `src/autoinfo/collectors/pdf.py:34` → `_check_deps()` raises (`pdf.py:269-274`). All 6 were FAILING; gated on `requires_optional_dep("fitz")` + `@pytest.mark.optional`. |
| `tests/test_pdf_handler.py` — `test_title_from_metadata`, `test_title_fallback_to_filename`, `test_author_and_subject_in_raw_data`, `test_raw_data_has_page_info` | #8-11 | Same root cause (`pdf.py:34`). 4 were FAILING → skipped with tag. |
| `tests/test_pdf_handler.py` — `test_url_download_and_extract`, `test_fetch_method`, `test_download_size_limit` | #12-14 | Same root cause (`pdf.py:34`). 3 were FAILING → skipped with tag. |
| `tests/test_v1_5_quality_gates.py::TestD2FormatIntegrity::test_valid_pdf_passes` | #15 | `import fitz` fails at `src/autoinfo/quality.py:2106-2119` → `passed=False, score=0.0` vs asserts. 1 was FAILING → skipped with tag. |

Non-skip resolutions in the same pass (rows #1, #16, #17-24, #31, #44 — not counted
against the ceiling): pytest-mock declared+installed (ERROR→PASS), `get_config_path`
stubbed in test (env interference removed), litellm 1.93.0 broken install replaced
with 1.83.7 (8+1 tests PASS), `pip install -e .` refreshed version metadata (PASS).


## Classification legend

| Class | Meaning | Fixed by |
|---|---|---|
| `env-dep` | Environment/dependency missing or env state interferes (optional deps not installed, broken venv package, gitignored runtime config present). No code defect in tests or source. | M0T3 (env-dep skip gates) |
| `mock-seam` | Test cannot reach its mock: source refactor removed the patched symbol, added a pre-check that short-circuits, or added a precondition the fixture does not satisfy. Test needs a new seam/stub. | M0T5 (mock seam) |
| `stale` | Test expectation no longer matches current *intended* behavior (counts, fixtures, intentional fallback change, test-helper bug, brittle path). Source is correct. | M0T6 (stale tests) |
| `regression` | Source change postdated the test and broke a previously-passing assertion (envelope drift, KB-status short-circuit, cost-meter binding, init layout/dispatch). | M0T4 (init_project) / M1T11-12 (error-envelope drift) / M0T6 as noted |

## Triage table (84 rows = 83 failed + 1 error)

| # | Test id | Class | Root cause (file that must change : line) |
|---|---|---|---|
| 1 | `tests/test_knowledge_graph.py::TestProcessIntegration::test_process_calls_store_entities` (**ERROR**) | env-dep | `tests/test_knowledge_graph.py:404` requests `mocker` fixture; pytest-mock NOT installed and never declared — `pyproject.toml:75-79` dev extra lacks `pytest-mock` (commit 49b3fa6 only rewrote the test, never added the dep; later commits reintroduced `mocker`). Fixture error → ERROR not FAIL. |
| 2 | `tests/test_pdf_handler.py::TestExtractFromFile::test_extract_returns_items` | env-dep | PyMuPDF missing → `src/autoinfo/collectors/pdf.py:34` (`fitz = None`) → `_check_deps()` raises at `pdf.py:269-274`. Fix: add PyMuPDF to dev/`[pdf]` extra or tag skip (`pyproject.toml:75-79`). |
| 3 | `tests/test_pdf_handler.py::TestExtractFromFile::test_small_pdf_single_item` | env-dep | same as #2 (`src/autoinfo/collectors/pdf.py:34`) |
| 4 | `tests/test_pdf_handler.py::TestExtractFromFile::test_large_pdf_multiple_chunks` | env-dep | same as #2 |
| 5 | `tests/test_pdf_handler.py::TestExtractFromFile::test_content_from_all_pages` | env-dep | same as #2 |
| 6 | `tests/test_pdf_handler.py::TestExtractFromFile::test_source_name_propagates` | env-dep | same as #2 |
| 7 | `tests/test_pdf_handler.py::TestExtractFromFile::test_file_not_found` | env-dep | same as #2 (test patches `fitz.open`; `fitz` is `None` → "None does not have the attribute 'open'") |
| 8 | `tests/test_pdf_handler.py::TestMetadataParsing::test_title_from_metadata` | env-dep | same as #2 |
| 9 | `tests/test_pdf_handler.py::TestMetadataParsing::test_title_fallback_to_filename` | env-dep | same as #2 |
| 10 | `tests/test_pdf_handler.py::TestMetadataParsing::test_author_and_subject_in_raw_data` | env-dep | same as #2 |
| 11 | `tests/test_pdf_handler.py::TestMetadataParsing::test_raw_data_has_page_info` | env-dep | same as #2 |
| 12 | `tests/test_pdf_handler.py::TestUrlDownloadAndParse::test_url_download_and_extract` | env-dep | same as #2 |
| 13 | `tests/test_pdf_handler.py::TestUrlDownloadAndParse::test_fetch_method` | env-dep | same as #2 |
| 14 | `tests/test_pdf_handler.py::TestUrlDownloadAndParse::test_download_size_limit` | env-dep | same as #2 |
| 15 | `tests/test_v1_5_quality_gates.py::TestD2FormatIntegrity::test_valid_pdf_passes` | env-dep | PyMuPDF missing → `src/autoinfo/quality.py:2106-2119` (`import fitz` fails → `passed=False`, `valid=False`, `score=0.0` vs test asserts `passed is True`, `score == 1.0`, `valid is True` at `tests/test_v1_5_quality_gates.py:553`). |
| 16 | `tests/test_llm.py::TestConfigHandling::test_default_config_no_file` | env-dep | Repo-root gitignored runtime `.autoinfo/config.yaml` (created 2026-08-03) is picked up by `get_config_path()` → `LLMExtractor()._model` != documented default. Test asserts defaults at `tests/test_llm.py:434`; env state interferes (`src/autoinfo/llm.py:88-102`). Fix: isolate cwd in test or stub `get_config_path`. |
| 17 | `tests/test_simplify.py::test_simplify_success` | env-dep | **Broken litellm install**: `litellm` 1.93.0 in `.venv` is a namespace package (missing `litellm/__init__.py`; lazy-import design at `litellm/_lazy_imports.py` needs `__getattr__` in `__init__.py`) → `litellm.completion` does not exist → `patch("litellm.completion", ...)` at `tests/test_simplify.py:77` raises AttributeError. Fix: reinstall/pin litellm or re-seam mocks at `src/autoinfo/llm.py:279` (`_get_litellm`). |
| 18 | `tests/test_simplify.py::test_simplify_verified_when_same_level` | env-dep | same as #17 (`tests/test_simplify.py:100`) |
| 19 | `tests/test_simplify.py::test_simplify_not_verified_when_higher` | env-dep | same as #17 (`tests/test_simplify.py:120`) |
| 20 | `tests/test_simplify.py::test_simplify_valid_levels` | env-dep | same as #17 (`tests/test_simplify.py:179`) |
| 21 | `tests/test_simplify.py::test_simplify_llm_exception` | env-dep | same as #17 (`tests/test_simplify.py:197`) |
| 22 | `tests/test_simplify.py::test_simplify_llm_empty_response` | env-dep | same as #17 (`tests/test_simplify.py:210`) |
| 23 | `tests/test_simplify.py::test_simplify_language_zh` | env-dep | same as #17 |
| 24 | `tests/test_simplify.py::test_simplify_language_ja` | env-dep | same as #17 |
| 25 | `tests/test_v1_2_integration.py::TestCEFRClassification::test_classify_text_returns_known_level` | env-dep | same broken litellm: `patch("litellm.completion")` at `tests/test_v1_2_integration.py:370` raises AttributeError. |
| 26 | `tests/test_v1_2_integration.py::TestCEFRClassification::test_classify_text_unknown_on_empty` | env-dep | same as #25 (`tests/test_v1_2_integration.py:378`) |
| 27 | `tests/test_v1_2_integration.py::TestCEFRClassification::test_classify_text_unknown_on_llm_failure` | env-dep | same as #25 (`tests/test_v1_2_integration.py:387`) |
| 28 | `tests/test_v1_2_integration.py::TestCEFRClassification::test_classify_text_zh_lang` | env-dep | same as #25 (`tests/test_v1_2_integration.py:397`) |
| 29 | `tests/test_v1_2_integration.py::TestCEFRClassification::test_cli_classify_command` | env-dep | same as #25 (`tests/test_v1_2_integration.py:433`) |
| 30 | `tests/test_v1_2_integration.py::TestCEFRClassification::test_mcp_classify_cefr` | env-dep | same as #25 (`tests/test_v1_2_integration.py:445`) |
| 31 | `tests/test_v1_2_integration.py::TestVectorSearch::test_generate_embedding_fallback_on_exception` | env-dep | same broken litellm: `patch("litellm.embedding")` at `tests/test_v1_2_integration.py:188` raises AttributeError. |
| 32 | `tests/test_digest.py::TestGenerateDigest::test_markdown_output_includes_entries_and_synthesis` | mock-seam | `@patch("autoinfo.kb.KBStore")` is dead since f83bd8d hoisted `from autoinfo.kb import KBStore` to module level — `src/autoinfo/output/__init__.py:49`. `generate_digest` uses `autoinfo.output.KBStore`, patch never intercepts → real store → "No entries found", "Executive Summary" missing. Assert at `tests/test_digest.py:189`. Fix: patch `autoinfo.output.KBStore`. |
| 33 | `tests/test_digest.py::TestGenerateDigest::test_json_output_valid_structure` | mock-seam | same as #32 (assert `entry_count == 2` at `tests/test_digest.py:212`, got 0) |
| 34 | `tests/test_digest.py::TestGenerateDigest::test_llm_failure_still_renders_entries` | mock-seam | same as #32 (`tests/test_digest.py:283`) |
| 35 | `tests/test_v1_5_delivery.py::TestProductTemplate::test_backward_compatible_digest` | mock-seam | same as #32: `monkeypatch.setattr("autoinfo.kb.KBStore", ...)` at `tests/test_v1_5_delivery.py:355` never intercepts `autoinfo.output.KBStore` (`output/__init__.py:49`); digest renders "No entries found" → assert at `tests/test_v1_5_delivery.py:370`. |
| 36 | `tests/test_mcp_full.py::TestJobId::test_collect_sources_returns_job_id` | mock-seam | `_handle_collect_sources` now validates the domain against config first — `src/autoinfo/mcp/server.py:512-518` returns DOMAIN_NOT_FOUND for unconfigured `test-domain` before the mocked `run_collection` runs. Test calls `domain="test-domain"` at `tests/test_mcp_full.py:516`; needs a tmp config with the domain (or assert the error). |
| 37 | `tests/test_mcp_full.py::TestJobId::test_get_collection_progress_by_job_id` | mock-seam | same as #36 (`tests/test_mcp_full.py:536`, domain `"test-progress"`) |
| 38 | `tests/test_digest.py::TestMcpHandler::test_handler_returns_success_with_content` | mock-seam | `_handle_generate_digest` no-entry pre-check (added e497e11) short-circuits before the mocked `generate_digest` — `src/autoinfo/mcp/server.py:2380-2385` returns `success_response({"status": "noop", ...})` → `result["format"]` KeyError at `tests/test_digest.py:338`. Fix: stub KBStore entries or assert the noop envelope. |
| 39 | `tests/test_digest.py::TestMcpHandler::test_handler_json_format_parses_content` | mock-seam | same as #38 (`tests/test_digest.py:360`) |
| 40 | `tests/test_digest.py::TestMcpHandler::test_handler_propagates_validation_error` | mock-seam | same as #38 — noop envelope returned instead of error dict → `"error_code"` missing at `tests/test_digest.py:377` |
| 41 | `tests/test_digest.py::TestMcpHandler::test_handler_returns_error_for_exception` | mock-seam | same as #38 (`tests/test_digest.py:393`) |
| 42 | `tests/test_task12_features.py::TestListDemoDomains::test_returns_all_five_domains` | stale | Repo has **9** demo domains (`src/autoinfo/cli/init.py:37-45`, `src/autoinfo/data/domains/`), test asserts 5 at `tests/test_task12_features.py:101`. Fix: 5→9 (M0T6; 9→13 later in M3T32). |
| 43 | `tests/test_task12_features.py::TestMcpEnumFix::test_init_project_enum_has_all_five` | stale | Same count drift: asserts `len(enum_vals) == 5` at `tests/test_task12_features.py:607`; `_list_demo_domains()` returns 9. |
| 44 | `tests/test_version.py::test_version_matches_installed_metadata` | stale | `src/autoinfo/_version.py` says 1.8.1 but installed dist metadata says 1.3.0 (stale `.venv` install; pyproject `dynamic = ["version"]` + `attr = "autoinfo._version.__version__"` at `pyproject.toml:7,114`). Assert at `tests/test_version.py:6-7`. Fix: reinstall editable pkg (M0T6 verifies) or relax assert. |
| 45 | `tests/test_demo_sources.py::TestDemoSources::test_old_sources_preserved[language-learning-old2-new2]` | stale | `EXPECTED` snapshot at `tests/test_demo_sources.py:16-37` stale: `voa-learning-english` removed from `src/autoinfo/data/domains/language-learning/sources.yaml`; assert at `:55-59`. |
| 46 | `tests/test_demo_sources.py::TestDemoSources::test_total_count[medical-research-old0-new0]` | stale | Same: EXPECTED says 3 sources, file has 7 (`src/autoinfo/data/domains/medical-research/sources.yaml`); assert at `tests/test_demo_sources.py:76-79`. |
| 47 | `tests/test_demo_sources.py::TestDemoSources::test_total_count[language-learning-old2-new2]` | stale | Same: EXPECTED 4, actual 3. |
| 48 | `tests/test_demo_sources.py::TestDemoSources::test_total_count[financial-intelligence-old3-new3]` | stale | Same: EXPECTED 5, actual 6. |
| 49 | `tests/test_demo_sources.py::TestDemoSources::test_total_count[tech-ai-developer-old4-new4]` | stale | Same: EXPECTED 5, actual 8. |
| 50 | `tests/test_report.py::TestGenerateReport::test_llm_grouping_failure_falls_back_to_single_group` | stale | Intentional fallback change (f83bd8d): grouping fallback now splits by domain/source_type instead of single "General" — `src/autoinfo/output/__init__.py:3275-3317`. Test asserts old `"### General"` at `tests/test_report.py:247`. Fix: update expectation. |
| 51 | `tests/test_report.py::TestGenerateReport::test_llm_grouping_exception_falls_back` | stale | same as #50 (`tests/test_report.py:276`) |
| 52 | `tests/test_report.py::TestGenerateReport::test_ungrouped_entries_go_to_additional_topics` | stale | same as #50 (`tests/test_report.py:332`) |
| 53 | `tests/test_source_health.py::TestGetSourceHealth::test_error_after_three_consecutive_failures[10]` | stale | Test-helper date bug: `_ts()` at `tests/test_source_health.py:68-73` computes `dt.replace(day=dt.day - days_ago)` — on 2026-08-05, `days_ago=9` → day=-4 → `ValueError: day -4 out of range`. Only passes when day-of-month ≥ max days_ago. Fix: use `timedelta`. |
| 54 | `tests/test_source_health.py::TestGetSourceHealth::test_resets_after_success_following_errors` | stale | same as #53 (`tests/test_source_health.py:290` calls `_ts(days_ago=5)` → day=0). |
| 55 | `tests/test_bug_40.py::test_create_draft_source_has_subscript_annotations` | stale | Opens cwd-relative `"src/autoinfo/cli/kb.py"` at `tests/test_bug_40.py:71`; fails only when an earlier test leaks `os.chdir` (e.g. `tests/test_backward_compat.py:414-503` chdir without restore). Passes standalone. Fix: `Path(__file__)`-relative path + restore cwd in leaker. |
| 56 | `tests/test_mcp_server.py::TestToolRegistration::test_required_params_are_marked` | stale | `collect_sources` domain is *intentionally* optional (domain-less collection) — schema `required: []` at `src/autoinfo/mcp/server.py` tool decl; test asserts `"domain" in required` at `tests/test_mcp_server.py:295`. Fix: update expectation (drop collect_sources from required list). |
| 57 | `tests/test_v1_2_integration.py::TestRestAPI::test_list_entries_empty_domain_returns_empty` | stale | Domain-precondition middleware (de88d30) makes unknown-domain `GET /api/v1/entries` return 404 — `src/autoinfo/api/routes.py:257`; test expects 200-empty at `tests/test_v1_2_integration.py:353`. Fix: update expectation (use configured domain). |
| 58 | `tests/test_v1_5_feed_api.py::TestFeedAPI::test_feed_domain_isolation` | stale | Same de88d30 domain precondition: `_create_entry(domain="ai-commercial")` → 404 DomainNotFound (`src/autoinfo/api/routes.py:257`); fixture config at `tests/test_v1_5_feed_api.py:34-42` declares no domains. Fix: configure domains in fixture at `tests/test_v1_5_feed_api.py:34`. |
| 59 | `tests/test_backward_compat.py::TestAllV01TestsPass::test_all_v01_tests_pass` | regression | Meta-test reruns 10 v0.1 test files as subprocess (`tests/test_backward_compat.py:251-280`); 8 nested failures (integration TestTrueTest×5 + llm config-env + mcp_server×2) → exit 1. Aggregate of rows #60-63, #67-72, #74, #78. Fix with its constituents. |
| 60 | `tests/test_backward_compat.py::TestInitIntegration::test_init_exit_code_zero` | regression | #106 dir-layout change (79b188a) moved runtime dirs from `.autoinfo/knowledge/...` to project root — `src/autoinfo/cli/init.py:135-140`; test still asserts `.autoinfo/knowledge/01-Raw` at `tests/test_backward_compat.py:421-423`. |
| 61 | `tests/test_backward_compat.py::TestInitIntegration::test_init_config_validates` | regression | `--list-domains` option (a4549e1) at `src/autoinfo/cli/init.py:194-198`: direct call `init(demo=...)` hits truthy `list_domains` OptionInfo object → prints usage, creates nothing → `load_config` FileNotFoundError at `tests/test_backward_compat.py:463`. Fix: call via CliRunner or pass flags explicitly. |
| 62 | `tests/test_backward_compat.py::TestCollectProcessPipeline::test_process_smoke` | regression | Cost-meter binding regression (Wave 3 4a6786b): `src/autoinfo/process.py:685-695` passes mocked LLM's MagicMock token counters into `CostMeter().log_llm_tokens` → `cost.py:159` `_insert_log` binds MagicMock → `InterfaceError: Error binding parameter 5` → 0 KB entries → assert at `tests/test_backward_compat.py:562`. Fix: coerce `int()` at `process.py:690`/`cost.py:159`. |
| 63 | `tests/test_custom_extraction.py::TestProcessingWithExtractFields::test_processing_with_custom_fields` | regression | same cost-meter MagicMock binding (#62) — assert `kb_entries_created == 1` at `tests/test_custom_extraction.py:358`. |
| 64 | `tests/test_integration.py::TestTrueTest::test_t1_init_creates_config` | regression | same #106 dir-layout change — test asserts `.autoinfo/knowledge/01-Raw` at `tests/test_integration.py:270`; init creates `knowledge/01-Raw` at root (`src/autoinfo/cli/init.py:135`). |
| 65 | `tests/test_integration.py::TestTrueTest::test_t3_collection_stores_items` | regression | cost-meter MagicMock binding (#62) — assert `kb_entries_created == 2` at `tests/test_integration.py:354`. |
| 66 | `tests/test_integration.py::TestTrueTest::test_t4_quality_scores_present` | regression | cost-meter MagicMock binding (#62) — per-item log `status: error` → `g3_score` missing, assert at `tests/test_integration.py:425`. |
| 67 | `tests/test_integration.py::TestTrueTest::test_t5_summaries_list_has_tldr` | regression | cost-meter MagicMock binding (#62) — `list_entries returned no results`, assert at `tests/test_integration.py:476`. |
| 68 | `tests/test_integration.py::TestTrueTest::test_end_to_end` | regression | cost-meter MagicMock binding (#62) — assert `len(entries) == 2` at `tests/test_integration.py:560` (plus #106 dir assertion at `:270`). |
| 69 | `tests/test_mcp_dispatch.py::TestGetDomainWebhooksDispatch::test_get_domain_webhooks_not_polluted_by_init_project` | regression | **init_project dispatch bug (M0T4)**: `_handle_init_project` passes string `domain` where a list is expected — `src/autoinfo/mcp/server.py:3398` `_run_init(domain, ...)` iterates the string char-by-char ("medical-research" → 16 char "domains") → real domain never created → `get_domain_webhooks` returns error envelope → `body["success"] is False` at `tests/test_mcp_dispatch.py:76`. Fix: `_run_init([domain], ...)`. |
| 70 | `tests/test_mcp_server.py::TestListSummaries::test_dispatches_to_kb_store` | regression | `_detect_kb_status()` short-circuit (f7a5873) at `src/autoinfo/mcp/server.py:720-732` returns uninitialized/empty before `store.list_entries` → mock called 0 times → assert at `tests/test_mcp_server.py:508`. Fix: stub `_detect_kb_status` or KB dirs. |
| 71 | `tests/test_mcp_v2.py::TestSearchKnowledgeBaseStub::test_returns_result_not_stub` | regression | `_handle_search_knowledge_base` returns `count` key (f7a5873, `src/autoinfo/mcp/server.py:2074-2078`) but test asserts legacy `total_count` at `tests/test_mcp_v2.py:501`. Shape drift. |
| 72 | `tests/test_mcp_v2.py::TestNewToolDispatch::test_implemented_tool_returns_result` | regression | same as #71 (`tests/test_mcp_v2.py:659`). |
| 73 | `tests/test_mcp_v2.py::TestErrorResponseV2::test_error_includes_required_fields` | regression | Exception→ErrorCode mapping (51dbc69) at `src/autoinfo/mcp/server.py:6173-6174`: `ValueError` now maps to `VALIDATION_ERROR`; test asserts legacy `"InternalError"` at `tests/test_mcp_v2.py:679`. Error-envelope drift — feeds M1T11-12. |
| 74 | `tests/test_task12_features.py::TestConfigureLlm::test_update_provider` | regression | Envelope wrap (b39829a) at `src/autoinfo/mcp/server.py:3529`: `_handle_configure_llm` now returns `success_response({...})` = `{success, data:{...}}`; tests assert flat `result["status"]` at `tests/test_task12_features.py:417-419`. Error-envelope drift — feeds M1T11-12. |
| 75 | `tests/test_task12_features.py::TestConfigureLlm::test_update_model` | regression | same as #74 (`tests/test_task12_features.py:433-439`) |
| 76 | `tests/test_task12_features.py::TestConfigureLlm::test_update_base_url` | regression | same as #74 (`tests/test_task12_features.py:448-453`) |
| 77 | `tests/test_task12_features.py::TestConfigureLlm::test_api_key_stored_as_env_ref` | regression | same as #74 (`tests/test_task12_features.py:466-473`) |
| 78 | `tests/test_task12_features.py::TestConfigureLlm::test_api_key_without_config_returns_error` | regression | same family: error path wrapped in `error_response` envelope at `src/autoinfo/mcp/server.py:3486` → `result.get("error_code")` is None vs `"CONFIG_NOT_FOUND"` at `tests/test_task12_features.py:483-484`. |
| 79 | `tests/test_task12_features.py::TestConfigureLlm::test_field_by_field_update` | regression | same as #74 (`tests/test_task12_features.py:498-515`) |
| 80 | `tests/test_task12_features.py::TestConfigureLlm::test_all_fields_at_once` | regression | same as #74 (`tests/test_task12_features.py:530-540`) |
| 81 | `tests/test_task12_features.py::TestConfigureLlm::test_config_not_found` | regression | same as #78 (`tests/test_task12_features.py:554-556`) |
| 82 | `tests/test_task12_features.py::TestConfigureLlm::test_empty_provider_unchanged` | regression | same as #74 (`tests/test_task12_features.py:565-572`) |
| 83 | `tests/test_task12_features.py::TestConfigureLlm::test_success_includes_config_path` | regression | same as #74 — `result["config_path"]` KeyError at `tests/test_task12_features.py:582-583`. |
| 84 | `tests/test_v1_2_integration.py::TestRestAPI::test_get_entry_not_found_returns_404` | regression | REST error envelope: 404 body no longer carries FastAPI `detail` — `src/autoinfo/api/server.py:208` (HTTPException handler); test asserts `response.json()["detail"]` at `tests/test_v1_2_integration.py:301`. REST-envelope drift — feeds M1T11-12. |

## Cluster summaries

| Cluster | Count | Class | Root cause |
|---|---|---|---|
| `TestConfigureLlm` (10) | 10 | regression | Envelope wrap at `server.py:3529/3486` (b39829a, 2026-07-31) — tests assert flat shape. **NOT env-gated** (AUTOINFO_LLM_API_KEY unset; handler never reads it; `configure_llm` excluded from `_LLM_REQUIRED_TOOLS` at `server.py:9684-9699`). Feeds M1T11-12. |
| `TestErrorResponseV2::test_error_includes_required_fields` | 1 | regression | ValueError→VALIDATION_ERROR mapping (51dbc69, `server.py:6173-6174`) vs test's legacy "InternalError" expectation. Error-envelope drift confirmed — feeds M1T11-12. |
| `TestProcessIntegration::test_process_calls_store_entities` (ERROR) | 1 | env-dep | `mocker` fixture missing — pytest-mock not installed/declared (`pyproject.toml:75-79`). |
| PDF handler (13) + valid_pdf_passes (1) | 14 | env-dep | PyMuPDF (`fitz`) not installed — `pdf.py:34`, `quality.py:2106`. |
| litellm patch failures (simplify 8 + CEFR 6 + embedding 1) | 15 | env-dep | Broken litellm 1.93.0 install (namespace package, no `__init__.py`) — `litellm.completion`/`embedding` absent. |
| Cost-meter MagicMock binding (integration 4 + custom_extraction 1 + process_smoke 1) | 6 | regression | Wave 3 cost metering `process.py:690` → `cost.py:159` binds uncoerced MagicMock token counters. |
| Digest rendering (3) + backward_compatible_digest (1) | 4 | mock-seam | KBStore patch dead — module-level import at `output/__init__.py:49` (f83bd8d). |
| Digest McpHandler (4) | 4 | mock-seam | No-entry pre-check `server.py:2380-2385` (e497e11) bypasses mocked `generate_digest`. |
| KB-status shape (mcp_server 1 + mcp_v2 2) | 3 | regression | `_detect_kb_status` short-circuit (f7a5873): `list_entries` not called / `count` vs `total_count`. |
| Envelope drift (ConfigureLlm 10 + digest McpHandler error path + mcp_v2 error 1 + REST 404 1) | — | regression | Dual-format envelope standardization (db98d1a/b39829a/51dbc69/de88d30). |

## Task mapping

| Class | Fix task |
|---|---|
| `env-dep` | **M0T3** — optional-dep skip gates (`requires_optional_dep` already in conftest via M0T2) + reinstall litellm/PyMuPDF/pytest-mock as declared deps |
| `mock-seam` | **M0T5** — restore mock seams (patch `autoinfo.output.KBStore`, stub `_detect_kb_status`, configure domains in fixtures, stub KBStore in digest handler tests) |
| `stale` | **M0T6** — required-params/collect_sources schema, digest expectations, feed-isolation fixtures, task12 counts 5→9, demo-source EXPECTED, report fallback expectations, `_ts` helper, version assert, bug_40 path |
| `regression` (init_project char-split) | **M0T4** — `server.py:3398` `_run_init([domain], ...)` |
| `regression` (envelope/error-code drift) | **M1T11-12** — envelope shape tests + REST error body (`server.py:3529/3486/6173`, `api/server.py:208`) |
| `regression` (cost-meter MagicMock) | M0T6/M0T5 — coerce `int()` at `process.py:690` or numeric mock usage |
| `regression` (#106 dir layout) | M0T6 — update init-dir assertions to project-root layout |

## Verification

- `grep -c "env-dep\|mock-seam\|stale\|regression" tests/TRIAGE.md` → 84
- Full suite output: `/tmp/opencode/triage-full.txt`
- Evidence: `.omo/evidence/merged-task-1-triage.md`, `.omo/evidence/merged-task-1-clean.txt`

## Post-baseline fixes (2026-08-07 — #117)

The following 8 tests were config-dependent (implicitly relying on a gitignored
`.autoinfo/config.yaml` in the repo root). In a fresh checkout/CI the file is
absent, so each test now patches a usage-site seam instead of the loader:
`PYTHONPATH=src pytest tests/test_cli_commands.py tests/test_mcp_server.py` is
green with `.autoinfo/` missing.

| Test | Seam now patched |
|---|---|
| `test_cli_commands.py::TestSummariesCommand::test_summaries_human` | `autoinfo.cli.summaries.get_config_path` (usage-site binding — `summaries.py` imports it at module top, so patching `autoinfo.config.get_config_path` was a no-op) |
| `test_cli_commands.py::TestSummariesCommand::test_summaries_json` | same |
| `test_cli_commands.py::TestSummariesCommand::test_summaries_empty` | same |
| `test_cli_commands.py::TestSummariesCommand::test_summaries_with_limit_offset` | same |
| `test_mcp_server.py::TestCollectSources::test_dispatches_to_run_collection` | `autoinfo.mcp.server._load_config` → `Config(domains=[DomainConfig(name="medical-research")])` |
| `test_mcp_server.py::TestCollectSources::test_dry_run_passed_through` | same |
| `test_mcp_server.py::TestCollectSources::test_nonexistent_domain_returns_not_found` | `autoinfo.mcp.server._load_config` → `Config()` (empty domains → `_find_domain` returns None → `DOMAIN_NOT_FOUND`) |
| `test_mcp_server.py::TestListSummaries::test_empty_result` | `autoinfo.mcp.server._detect_kb_status` → `"operational"` (prevents short-circuit on `uninitialized`) |
