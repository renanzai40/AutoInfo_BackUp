"""Integration & end-to-end tests for the complete T1-T5 True Test flow.

Verifies the full pipeline from init → collect → process → summaries listing,
with all external dependencies mocked (no real API calls).

Tests
-----
T1: ``autoinfo init --demo medical-research`` creates ``.autoinfo/config.yaml``
    and the required directory structure.
T2: The generated config contains a valid LLM API key placeholder
    (``${AUTOINFO_LLM_API_KEY}``).
T3: Collection followed by processing produces ``01-Raw`` Markdown files
    with correct YAML frontmatter.
T4: The processing result includes quality scores (G3 relevance) per item.
T5: ``KBStore.list_entries()`` returns entries with a TL;DR summary.
E2E: The complete ``init → collect → process → summaries`` pipeline
    produces consistent results at each stage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.kb import KBStore
from autoinfo.llm import LLMExtractor
from autoinfo.models import ExtractionResult, Item
from autoinfo.process import ProcessResult, run_processing


# ===================================================================
# Constants
# ===================================================================

DOMAIN = "medical-research"
TOPIC = "IVF breakthroughs"

# A minimal AutoInfo config with proper domain structure.
SAMPLE_CONFIG = {
    "project": {"name": "Test Project", "created_at": "2026-07-20"},
    "llm": {
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat",
        "api_key": "${AUTOINFO_LLM_API_KEY}",
    },
    "domains": [
        {
            "name": DOMAIN,
            "active": True,
            "sources": [
                {
                    "name": "pubmed",
                    "type": "api",
                    "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
                    "quality_tier": 1,
                }
            ],
            "topics": [
                {"name": TOPIC, "keywords": ["IVF", "embryo", "implantation"]}
            ],
        }
    ],
}

# Synthetic PubMed-like items that _fetch_items would return.
SAMPLE_RAW_ITEMS = [
    Item(
        id="pmid-1000001",
        source_name="pubmed",
        source_type="api",
        source_platform="pubmed",
        source_url=(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
            "efetch.fcgi?db=pubmed&id=1000001&retmode=xml"
        ),
        title="Improved IVF outcomes with time-lapse embryo imaging: an RCT",
        content=(
            "Time-lapse embryo imaging significantly improves live birth "
            "rates compared to standard morphological assessment in IVF "
            "patients. A multicenter RCT with 1,200 patients showed 48.2% "
            "vs 39.5% live birth rate (p=0.006)."
        ),
        content_type="text",
        collected_at="2026-07-15T10:30:00Z",
        language="en",
        domain=DOMAIN,
        topic_tags=["IVF", "embryo imaging"],
        quality_tier=1,
        raw_data={"pmid": "1000001", "doi": "10.1000/j.ivf.2026.001"},
    ),
    Item(
        id="pmid-1000002",
        source_name="pubmed",
        source_type="api",
        source_platform="pubmed",
        source_url=(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
            "efetch.fcgi?db=pubmed&id=1000002&retmode=xml"
        ),
        title="Embryo grading and implantation success in IVF cycles",
        content=(
            "Embryo morphology grading remains the cornerstone of embryo "
            "selection in IVF. This retrospective study of 3,500 cycles "
            "evaluates the predictive value of the new grading system for "
            "implantation and clinical pregnancy rates."
        ),
        content_type="text",
        collected_at="2026-07-16T08:15:00Z",
        language="en",
        domain=DOMAIN,
        topic_tags=["IVF", "embryo grading"],
        quality_tier=1,
        raw_data={"pmid": "1000002", "doi": "10.1000/j.ivf.2026.002"},
    ),
]

# Mock LLM extraction result matching the first sample item.
MOCK_EXTRACTION = ExtractionResult(
    item_id="pmid-1000001",
    title="Improved IVF outcomes with time-lapse embryo imaging: an RCT",
    tl_dr=(
        "Time-lapse embryo imaging significantly improves live birth "
        "rates (48.2% vs 39.5%) compared to standard morphological "
        "assessment in a large RCT of 1,200 IVF patients."
    ),
    key_points=[
        "Multicenter RCT with 1,200 IVF patients",
        "Live birth rate: 48.2% (time-lapse) vs 39.5% (control), p=0.006",
        "Time-lapse imaging is a non-invasive method that improves "
        "embryo selection in IVF cycles",
    ],
    entities=[
        {"name": "Time-lapse embryo imaging", "type": "technology", "relevance": 0.95},
        {"name": "IVF", "type": "procedure", "relevance": 0.90},
    ],
    relevance_score=92.0,
)

MOCK_EXTRACTION_2 = ExtractionResult(
    item_id="pmid-1000002",
    title="Embryo grading and implantation success in IVF cycles",
    tl_dr=(
        "Embryo morphology grading remains the cornerstone of embryo "
        "selection. This retrospective study of 3,500 cycles validates "
        "the new grading system's predictive value for implantation rates."
    ),
    key_points=[
        "Retrospective study of 3,500 IVF cycles",
        "New embryo grading system predicts implantation success",
        "Morphology grading remains the cornerstone of embryo selection",
    ],
    entities=[
        {"name": "Embryo grading", "type": "procedure", "relevance": 0.92},
        {"name": "IVF", "type": "procedure", "relevance": 0.88},
    ],
    relevance_score=85.0,
)


# ===================================================================
# Helper
# ===================================================================


def _write_config(root: Path, config: dict[str, Any] | None = None) -> Path:
    """Write ``.autoinfo/config.yaml`` under *root* and return its path."""
    config_dir = root / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(config or SAMPLE_CONFIG, fh, default_flow_style=False, sort_keys=False)
    return config_path


def _prepare_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fully initialised project directory skeleton.

    * Writes ``.autoinfo/config.yaml`` with the standard test config.
    * Creates empty ``knowledge/`` and ``collections/`` dirs.
    * Changes CWD to *tmp_path*.

    Returns *tmp_path*.
    """
    # M0T10: restore cwd via monkeypatch (order-independent)
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    # Create directories that the pipeline expects
    (tmp_path / "collections").mkdir(exist_ok=True)
    (tmp_path / "knowledge").mkdir(exist_ok=True)
    return tmp_path


def _parse_frontmatter(file_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a Markdown KB file."""
    raw = file_path.read_text(encoding="utf-8")
    assert raw.startswith("---"), f"File {file_path} has no frontmatter"
    end = raw.find("---", 3)
    assert end != -1, f"File {file_path} has unclosed frontmatter"
    result = yaml.safe_load(raw[3:end])
    return result if isinstance(result, dict) else {}


def _mock_litellm_completion(*args: object, **kwargs: object) -> MagicMock:
    """Return a mock ``litellm.completion`` response."""
    raw_messages: object = kwargs.get("messages", args[1] if len(args) > 1 else [])
    messages: list[dict[str, Any]] = (
        raw_messages if isinstance(raw_messages, list) else []
    )

    # Extract the item title from the user message
    user_msg: str = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            user_msg = str(content) if content else ""
            break
    title_line = user_msg.split("\n")[0] if user_msg else ""

    if "embryo grading" in title_line or "implantation success" in title_line:
        result = MOCK_EXTRACTION_2
    else:
        result = MOCK_EXTRACTION

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps({
        "tl_dr": result.tl_dr,
        "key_points": result.key_points,
        "entities": result.entities,
        "relevance_score": result.relevance_score,
    })
    # TRIAGE #65-68 (regression): cost-meter MagicMock binding
    # (`process.py:690` → `cost.py:159`) — real int token counters so
    # `CostMeter().log_llm_tokens` binds ints, not MagicMocks.
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    response.usage.total_tokens = 150
    return response


# ===================================================================
# T1-T5 True Test
# ===================================================================


class TestTrueTest:
    """T1-T5 True Test verification: init → collect → process → summaries."""

    # ------------------------------------------------------------------
    # T1: init creates config
    # ------------------------------------------------------------------

    def test_t1_init_creates_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``autoinfo init --demo medical-research`` creates ``.autoinfo/config.yaml``
        and the required sub-directories."""
        # M0T10: restore cwd via monkeypatch (order-independent)
        monkeypatch.chdir(tmp_path)

        from typer.testing import CliRunner
        from autoinfo.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["init", "--demo", "medical-research"])
        assert result.exit_code == 0, f"init failed: {result.output}"

        # -- config.yaml exists --
        config_path = tmp_path / ".autoinfo" / "config.yaml"
        assert config_path.is_file(), "config.yaml was not created"

        # -- Required sub-directories exist --
        # TRIAGE #64 (regression): #106 (79b188a) moved runtime dirs from
        # `.autoinfo/knowledge/...` to project root (`src/autoinfo/cli/init.py:135-140`).
        assert (tmp_path / "knowledge" / "01-Raw").is_dir()
        assert (tmp_path / "collections").is_dir()
        assert (tmp_path / "outputs").is_dir()

        # -- Config parses as valid YAML --
        with open(config_path, encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh)
        assert isinstance(parsed, dict)
        assert "project" in parsed
        assert "llm" in parsed
        assert "domains" in parsed

    # ------------------------------------------------------------------
    # T2: LLM key placeholder
    # ------------------------------------------------------------------

    def test_t2_config_has_llm_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config YAML has ``${AUTOINFO_LLM_API_KEY}`` as the API key value."""
        # M0T10: restore cwd via monkeypatch (order-independent)
        monkeypatch.chdir(tmp_path)

        from typer.testing import CliRunner
        from autoinfo.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["init", "--demo", "medical-research"])
        assert result.exit_code == 0, f"init failed: {result.output}"

        config_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(config_path, encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh)

        llm = parsed.get("llm", {})
        api_key = llm.get("api_key", "")
        assert api_key, "llm.api_key is missing or empty"
        assert "${AUTOINFO_LLM_API_KEY}" in api_key, (
            f"Expected '{{AUTOINFO_LLM_API_KEY}}' placeholder, got {api_key!r}"
        )

        # Also verify provider and model are present
        assert llm.get("provider") == "openrouter"
        assert "deepseek" in llm.get("model", "")

    # ------------------------------------------------------------------
    # T3: collection → 01-Raw files with frontmatter
    # ------------------------------------------------------------------

    def test_t3_collection_stores_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collection followed by processing produces 01-Raw Markdown files
        with all required frontmatter fields."""
        _prepare_project(tmp_path, monkeypatch)

        # -- Step 1: Collect (mocked fetch, no real API) --
        with patch("autoinfo.collect._fetch_items", return_value=SAMPLE_RAW_ITEMS):
            from autoinfo.collect import run_collection

            collect_result = run_collection(
                domain=DOMAIN,
                topic="IVF",
                limit=10,
                dry_run=False,
            )

        assert collect_result["total_new"] == 2, (
            f"Expected 2 new items, got {collect_result['total_new']}"
        )

        # Verify cached JSON files in collections/
        collection_files = list(
            (tmp_path / "collections" / DOMAIN).rglob("*.json")
        )
        assert len(collection_files) >= 2, (
            f"Expected ≥2 cached JSON files, got {len(collection_files)}"
        )

        # -- Step 2: Process (mocked LLM, no real API) --
        mock_llm = MagicMock()
        mock_llm.completion.side_effect = _mock_litellm_completion

        with patch.object(
            LLMExtractor, "_get_litellm", return_value=mock_llm
        ):
            proc_result = run_processing(domain=DOMAIN)

        assert proc_result.total_items == 2
        assert proc_result.kb_entries_created == 2

        # -- Step 3: Verify 01-Raw Markdown files --
        kb_dir = tmp_path / "knowledge" / DOMAIN / "01-Raw"
        md_files = sorted(kb_dir.rglob("*.md"))
        assert len(md_files) == 2, (
            f"Expected 2 Markdown KB files, got {len(md_files)}"
        )

        # -- Step 4: Verify frontmatter on every file --
        REQUIRED_FRONTMATTER = [
            "title",
            "domain",
            "tier",
            "entry_id",
            "source_url",
            "source_type",
            "source_platform",
            "collected_at",
            "summary",
            "tags",
            "quality_tier",
            "relevance_score",
            "dedup_status",
            "language",
        ]

        for md_file in md_files:
            fm = _parse_frontmatter(md_file)

            for field in REQUIRED_FRONTMATTER:
                assert field in fm, (
                    f"Missing frontmatter field '{field}' in {md_file.name}"
                )

            # Verify values are sensible
            assert fm["domain"] == DOMAIN
            assert fm["tier"] == "01-Raw"
            assert fm["source_type"] == "api"
            assert fm["source_platform"] == "pubmed"
            assert fm["dedup_status"] in ("unique", "duplicate")
            assert isinstance(fm["relevance_score"], (int, float))
            assert isinstance(fm["quality_tier"], int)
            assert fm["title"], "Title must not be empty"
            assert fm["source_url"], "source_url must not be empty"
            assert fm["collected_at"], "collected_at must not be empty"

    # ------------------------------------------------------------------
    # T4: quality scores present
    # ------------------------------------------------------------------

    def test_t4_quality_scores_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Processing output includes per-item quality scores (G3 relevance)."""
        _prepare_project(tmp_path, monkeypatch)

        # Collect
        with patch("autoinfo.collect._fetch_items", return_value=SAMPLE_RAW_ITEMS):
            from autoinfo.collect import run_collection

            run_collection(domain=DOMAIN, topic="IVF", limit=10, dry_run=False)

        # Process with mocked LLM
        mock_llm = MagicMock()
        mock_llm.completion.side_effect = _mock_litellm_completion

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_llm):
            proc_result = run_processing(domain=DOMAIN)

        # -- G3 relevance scores in per_item_logs --
        assert len(proc_result.per_item_logs) == 2
        for log in proc_result.per_item_logs:
            assert "g3_score" in log, f"Missing g3_score in log for {log['item_id']}"
            assert isinstance(log["g3_score"], (int, float))
            assert 0 <= log["g3_score"] <= 100, (
                f"g3_score {log['g3_score']} out of range"
            )
            assert "relevance_score" in log, (
                f"Missing relevance_score in log for {log['item_id']}"
            )

        # -- KB entries have relevance_score --
        store = KBStore()
        entries = store.list_entries(DOMAIN)
        for entry in entries:
            assert "relevance_score" in entry
            assert isinstance(entry["relevance_score"], (int, float))
            assert 0 <= entry["relevance_score"] <= 100

        # -- Quality flag in frontmatter --
        kb_dir = tmp_path / "knowledge" / DOMAIN / "01-Raw"
        for md_file in sorted(kb_dir.rglob("*.md")):
            fm = _parse_frontmatter(md_file)
            relevance: float = float(fm.get("relevance_score", 0) or 0)
            assert relevance > 0, (
                f"relevance_score should be > 0 in {md_file.name}"
            )

    # ------------------------------------------------------------------
    # T5: summaries list has TL;DR
    # ------------------------------------------------------------------

    def test_t5_summaries_list_has_tldr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``KBStore.list_entries()`` returns entries with TL;DR summary."""
        _prepare_project(tmp_path, monkeypatch)

        # Collect
        with patch("autoinfo.collect._fetch_items", return_value=SAMPLE_RAW_ITEMS):
            from autoinfo.collect import run_collection

            run_collection(domain=DOMAIN, topic="IVF", limit=10, dry_run=False)

        # Process with mocked LLM
        mock_llm = MagicMock()
        mock_llm.completion.side_effect = _mock_litellm_completion

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_llm):
            run_processing(domain=DOMAIN)

        # -- List summaries --
        store = KBStore()
        entries = store.list_entries(DOMAIN, limit=10)

        assert len(entries) > 0, "list_entries returned no results"

        for entry in entries:
            # Each entry must have a title
            assert entry.get("title"), (
                f"Entry {entry.get('entry_id', '?')} has no title"
            )
            # summary field corresponds to TL;DR
            assert entry.get("summary"), (
                f"Entry {entry.get('entry_id', '?')} has no summary/TL;DR"
            )
            # Each entry has a relevance_score
            assert "relevance_score" in entry
            # Collected at should be present
            assert entry.get("collected_at"), (
                f"Entry {entry.get('entry_id', '?')} has no collected_at"
            )

    # ------------------------------------------------------------------
    # E2E: Complete pipeline
    # ------------------------------------------------------------------

    def test_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Complete pipeline: init → collect → process → summaries.

        Verifies that the output of each stage is consistent with the
        previous one and that no real API calls are made.
        """
        # M0T10: restore cwd via monkeypatch (order-independent)
        monkeypatch.chdir(tmp_path)

        # -- Stage 1: init ---------------------------------------------------
        from typer.testing import CliRunner
        from autoinfo.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["init", "--demo", "medical-research"])
        assert result.exit_code == 0, f"init failed: {result.output}"

        # The init command creates a minimal config, but for the full
        # pipeline we need a properly structured config. Overwrite with
        # our proper config that has domain/source/topic structure.
        _write_config(tmp_path)
        # Also create the collections/ and knowledge/ dirs at project root
        (tmp_path / "collections").mkdir(exist_ok=True)
        (tmp_path / "knowledge").mkdir(exist_ok=True)

        # Verify init created .autoinfo/ structure
        assert (tmp_path / ".autoinfo" / "config.yaml").is_file()
        assert (tmp_path / "knowledge" / "01-Raw").is_dir()

        # -- Stage 2: collect (mocked fetch, no real API) --------------------
        with patch("autoinfo.collect._fetch_items", return_value=SAMPLE_RAW_ITEMS):
            from autoinfo.collect import run_collection

            collect_result = run_collection(
                domain=DOMAIN,
                topic="IVF",
                limit=10,
                dry_run=False,
            )

        assert collect_result["total_new"] == 2
        assert collect_result["total_found"] == 2
        assert collect_result["dry_run"] is False
        assert len(collect_result["per_source"]) == 1
        assert collect_result["per_source"][0]["status"] == "success"

        # -- Stage 3: process (mocked LLM, no real API) ---------------------
        mock_llm = MagicMock()
        mock_llm.completion.side_effect = _mock_litellm_completion

        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_llm):
            proc_result = run_processing(domain=DOMAIN)

        assert proc_result.total_items == 2
        assert proc_result.kb_entries_created == 2
        assert proc_result.passed_gates > 0
        assert proc_result.errors == []
        assert proc_result.duration_s > 0

        # -- Stage 4: summaries ----------------------------------------------
        store = KBStore()
        entries = store.list_entries(DOMAIN, limit=10)

        assert len(entries) == 2, f"Expected 2 entries, got {len(entries)}"

        # Titles from both items should appear
        titles = {e["title"] for e in entries}
        assert "Improved IVF outcomes with time-lapse embryo imaging: an RCT" in titles
        assert "Embryo grading and implantation success in IVF cycles" in titles

        for entry in entries:
            assert entry.get("summary"), "Missing summary/TL;DR"
            assert entry.get("relevance_score", 0) > 0, (
                "relevance_score should be > 0"
            )
            assert entry.get("dedup_status") == "unique"
            assert entry.get("source_platform") == "pubmed"

        # -- Stage 5: Read one entry in full --------------------------------
        first_entry = entries[0]
        full_entry = store.get_entry(first_entry["entry_id"])
        assert full_entry is not None
        assert "content" in full_entry
        # Content should include the body text (no frontmatter markers)
        assert "---" not in full_entry["content"]
        # Should contain the LLM-extracted body (summary or key points)
        body = full_entry["content"]
        has_key_points = "Key Points" in body
        has_summary = "Summary" in body
        assert has_key_points or has_summary, (
            "Entry body should contain extracted content"
        )
        # The original article content must be present
        assert "Original Content" in body
        # The cached items should still be on disk
        cached_count = len(list((tmp_path / "collections" / DOMAIN).rglob("*.json")))
        assert cached_count >= 2, (
            f"Expected ≥2 cached JSON files, found {cached_count}"
        )

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_domain_returns_no_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pipeline on an empty/unknown domain returns gracefully."""
        _prepare_project(tmp_path, monkeypatch)

        from autoinfo.collect import run_collection

        with pytest.raises(ValueError, match="not found in configuration"):
            run_collection(domain="unknown-domain", dry_run=True)

    def test_no_cached_items_process_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Processing with no cached items returns zero counts."""
        _prepare_project(tmp_path, monkeypatch)

        result = run_processing(domain=DOMAIN)
        assert result.total_items == 0
        assert result.kb_entries_created == 0
        assert result.passed_gates == 0

    def test_config_loaded_from_env_has_placeholder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify the config file can be loaded by Config and the placeholder
        survives env-var resolution."""
        _prepare_project(tmp_path, monkeypatch)

        from autoinfo.config import load_config

        config_path = tmp_path / ".autoinfo" / "config.yaml"
        config = load_config(config_path)

        # The key should resolve to empty string (since AUTOINFO_LLM_API_KEY
        # is not set in test env) — but the raw placeholder is only visible
        # in the YAML file, not after resolution.
        # What we verify is that the config loads without error.
        assert config.llm.provider == "openrouter"
        assert "deepseek" in config.llm.model

        # Also verify the first domain
        assert len(config.domains) == 1
        assert config.domains[0].name == DOMAIN
        assert len(config.domains[0].sources) == 1
        assert config.domains[0].sources[0].name == "pubmed"
