"""Tests for custom extraction fields — user-defined extraction schema per domain.

Covers:

1. ``extract(item, schema=["methodology"])`` returns a ``methodology`` field
   in ``ExtractionResult.custom_fields``.
2. Prompt dynamically includes custom field descriptions (``Extract additionally``).
3. KB frontmatter has custom fields under ``extracted_fields``.
4. Config with ``extract_fields: [methodology, findings]`` works end-to-end
   via ``run_processing``.
5. Schema without custom fields uses defaults (backward compat).
6. On-demand re-extraction via ``extract_fields`` MCP tool.
7. ``get_extraction`` MCP tool returns correct data.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from autoinfo.kb import KBStore
from autoinfo.llm import DEFAULT_FIELDS, LLMExtractor
from autoinfo.models import ExtractionResult, Item
from autoinfo.process import run_processing

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def mock_litellm_with_custom() -> MagicMock:
    """Mock litellm that includes custom fields in the response."""
    m = MagicMock()
    response = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "tl_dr": (
                "Time-lapse embryo imaging improves live birth rates "
                "(48.2% vs 39.5%) in IVF patients."
            ),
            "key_points": [
                "Multicenter RCT with 1,200 IVF patients",
                "Live birth rate: 48.2% vs 39.5%, p=0.006",
            ],
            "entities": [
                {"name": "Time-lapse embryo imaging", "type": "technology"},
            ],
            "relevance_score": 92,
            "methodology": "Randomized controlled trial",
            "findings": "Significant improvement in live birth rate",
        })))]
    )
    # TRIAGE #63 (regression): cost-meter MagicMock binding
    # (`process.py:690` → `cost.py:159`) — real int token counters.
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    response.usage.total_tokens = 150
    m.completion.return_value = response
    return m


@pytest.fixture
def mock_litellm_default_only() -> MagicMock:
    """Mock litellm that returns ONLY default fields (no custom)."""
    m = MagicMock()
    response = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "tl_dr": "Default extraction only.",
            "key_points": ["Point one", "Point two"],
            "entities": [],
            "relevance_score": 50,
        })))]
    )
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    response.usage.total_tokens = 150
    m.completion.return_value = response
    return m


@pytest.fixture
def extractor() -> LLMExtractor:
    """Return a default :class:`LLMExtractor`."""
    return LLMExtractor()


# ===================================================================
# 1. extract() with custom schema returns custom_fields
# ===================================================================


class TestExtractWithCustomSchema:
    """``LLMExtractor.extract()`` with custom schema."""

    def test_custom_field_in_result(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """extract(item, schema=["methodology"]) returns methodology field."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom):
            result = extractor.extract(sample_item, schema=["methodology"])

        assert isinstance(result, ExtractionResult)
        assert "methodology" in result.custom_fields
        assert result.custom_fields["methodology"] == "Randomized controlled trial"

    def test_multiple_custom_fields(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """Multiple custom fields are returned in custom_fields."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom):
            result = extractor.extract(
                sample_item, schema=["methodology", "findings"]
            )

        assert "methodology" in result.custom_fields
        assert "findings" in result.custom_fields
        assert result.custom_fields["methodology"] == "Randomized controlled trial"
        assert "Significant improvement" in result.custom_fields["findings"]

    def test_default_fields_always_present(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """Default fields (tl_dr, key_points, ...) are present alongside custom."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom):
            result = extractor.extract(sample_item, schema=["methodology"])

        assert result.tl_dr != ""
        assert len(result.key_points) > 0
        assert result.relevance_score > 0

    def test_custom_field_missing_from_response(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm_default_only: MagicMock,
    ) -> None:
        """When LLM does not return a custom field, it is absent from custom_fields."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_default_only):
            result = extractor.extract(
                sample_item, schema=["methodology", "nonexistent_field"]
            )

        # Default fields still work
        assert result.tl_dr != ""
        # Custom field not in response -> not included
        assert "methodology" not in result.custom_fields
        assert "nonexistent_field" not in result.custom_fields
        assert result.custom_fields == {}


# ===================================================================
# 2. Prompt dynamically includes custom field descriptions
# ===================================================================


class TestPromptCustomSchema:
    """``LLMExtractor.dry_run()`` with custom schema."""

    def test_custom_field_in_prompt(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Custom field name appears in the prompt."""
        prompt = extractor.dry_run(sample_item, schema=["methodology"])
        assert "methodology" in prompt

    def test_extract_additionally_section(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Custom fields appear under 'Extract additionally' section."""
        prompt = extractor.dry_run(sample_item, schema=["methodology", "sample_size"])
        assert "Extract additionally" in prompt
        assert "methodology" in prompt
        assert "sample_size" in prompt

    def test_default_fields_always_in_prompt(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Default fields are always in the prompt even with custom schema."""
        prompt = extractor.dry_run(sample_item, schema=["custom_field"])
        for field in DEFAULT_FIELDS:
            assert field in prompt, f"Default field '{field}' should be in prompt"

    def test_no_custom_schema_uses_defaults(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """When no schema is given, only default fields are in the prompt."""
        prompt = extractor.dry_run(sample_item)
        for field in DEFAULT_FIELDS:
            assert field in prompt
        # No "Extract additionally" section
        assert "Extract additionally" not in prompt

    def test_custom_field_description_generated(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """Auto-generated description appears for custom fields."""
        prompt = extractor.dry_run(sample_item, schema=["sample_size"])
        # "sample_size" -> "Sample Size" (title cased)
        assert "Sample Size" in prompt or "sample_size" in prompt


# ===================================================================
# 3. KB frontmatter has custom fields under extracted_fields
# ===================================================================


class TestKBFrontmatterCustomFields:
    """KB frontmatter includes ``extracted_fields``."""

    def test_custom_fields_in_frontmatter(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """KB entry frontmatter includes extracted_fields when custom schema used."""
        # Override base path to use temp dir
        kb_base = tmp_path / "knowledge"

        # Create a minimal config for the domain's extract_fields
        from autoinfo.config import Config, DomainConfig, LLMConfig

        config = Config(
            llm=LLMConfig(provider="openrouter", model="deepseek/deepseek-chat"),
            domains=[DomainConfig(
                name="medical-research",
                extract_fields=["methodology"],
            )],
        )

        extractor = LLMExtractor(config=config)
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom):
            extraction = extractor.extract(sample_item, schema=["methodology"])

        store = KBStore(base_path=kb_base)
        entry = store.store_entry(sample_item, extraction)

        # Read the markdown file and parse frontmatter
        file_path = Path(entry.file_path)
        assert file_path.is_file()
        raw = file_path.read_text(encoding="utf-8")

        # Extract YAML frontmatter
        assert raw.startswith("---")
        end_idx = raw.find("---", 3)
        assert end_idx != -1
        fm = yaml.safe_load(raw[3:end_idx])

        assert "extracted_fields" in fm
        assert fm["extracted_fields"] == {"methodology": "Randomized controlled trial"}

    def test_no_custom_fields_no_extracted_fields_key(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_default_only: MagicMock,
    ) -> None:
        """Frontmatter omits extracted_fields when extraction has no custom fields."""
        kb_base = tmp_path / "knowledge"
        extractor = LLMExtractor()
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_default_only):
            extraction = extractor.extract(sample_item)  # no custom schema

        store = KBStore(base_path=kb_base)
        entry = store.store_entry(sample_item, extraction)

        file_path = Path(entry.file_path)
        raw = file_path.read_text(encoding="utf-8")
        end_idx = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end_idx])

        assert "extracted_fields" not in fm

    def test_empty_custom_fields_no_extracted_fields_key(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_default_only: MagicMock,
    ) -> None:
        """When custom_fields dict is empty, extracted_fields key is omitted."""
        kb_base = tmp_path / "knowledge"
        extractor = LLMExtractor()
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_default_only):
            extraction = extractor.extract(
                sample_item, schema=["methodology"]
            )

        store = KBStore(base_path=kb_base)
        entry = store.store_entry(sample_item, extraction)

        file_path = Path(entry.file_path)
        raw = file_path.read_text(encoding="utf-8")
        end_idx = raw.find("---", 3)
        fm = yaml.safe_load(raw[3:end_idx])

        assert "extracted_fields" not in fm


# ===================================================================
# 4. Config with extract_fields works end-to-end via run_processing
# ===================================================================


class TestProcessingWithExtractFields:
    """``run_processing`` passes custom schema from config."""

    def test_processing_with_custom_fields(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """Processing pipeline with extract_fields config works end-to-end."""
        # Create a project with config that has extract_fields
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_data = {
            "project": {"name": "Test", "created_at": "2026-07-20"},
            "llm": {"provider": "openrouter", "model": "deepseek/deepseek-chat"},
            "domains": [{
                "name": "medical-research",
                "active": True,
                "sources": [{"name": "pubmed", "type": "api", "url": "https://example.com"}],
                "topics": [],
                "extract_fields": ["methodology", "findings"],
            }],
        }
        config_path = config_dir / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as fh:
            yaml.dump(config_data, fh, default_flow_style=False)

        # Mock load_cached_items to return the sample item, and use
        # a mock KBStore so we can inspect what was stored
        from autoinfo.kb import KBEntry

        mock_store = MagicMock(spec=KBStore)
        mock_store.list_entries.return_value = []
        mock_entry = KBEntry(
            entry_id="test-entry-001",
            title=sample_item.title,
            domain="medical-research",
        )
        mock_store.store_entry.return_value = mock_entry

        with (
            patch("autoinfo.process.get_config_path", return_value=config_path),
            patch("autoinfo.process.load_cached_items", return_value=[sample_item]),
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom),
            patch("autoinfo.process.KBStore", return_value=mock_store),
        ):
            result = run_processing(domain="medical-research")

        assert result.kb_entries_created == 1
        assert result.processed_count == 1

        # Verify the extractor was called with the custom schema
        extract_call_args = mock_litellm_with_custom.completion.call_args
        assert extract_call_args is not None
        messages = extract_call_args[1]["messages"]
        system_msg = messages[0]["content"]
        assert "methodology" in system_msg
        assert "findings" in system_msg


# ===================================================================
# 5. Schema without custom fields uses defaults (backward compat)
# ===================================================================


class TestBackwardCompat:
    """Backward compatibility — no custom schema == default behavior."""

    def test_no_schema_uses_defaults(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm_default_only: MagicMock,
    ) -> None:
        """extract() without schema returns only default fields."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_default_only):
            result = extractor.extract(sample_item)

        assert isinstance(result, ExtractionResult)
        assert result.tl_dr != ""
        assert result.custom_fields == {}

    def test_default_schema_empty(
        self,
        sample_item: Item,
        extractor: LLMExtractor,
        mock_litellm_default_only: MagicMock,
    ) -> None:
        """Empty schema list extracts defaults only."""
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_default_only):
            result = extractor.extract(sample_item, schema=[])

        assert result.tl_dr != ""
        assert result.custom_fields == {}

    def test_dry_run_no_schema(
        self, sample_item: Item, extractor: LLMExtractor
    ) -> None:
        """dry_run() without schema produces prompt with only default fields."""
        prompt = extractor.dry_run(sample_item)
        assert "AutoInfo" in prompt
        for field in DEFAULT_FIELDS:
            assert field in prompt
        assert "Extract additionally" not in prompt


# ===================================================================
# 6. On-demand re-extraction via MCP
# ===================================================================


class TestMcpExtractFields:
    """``extract_fields`` MCP tool — on-demand re-extraction."""

    def test_extract_fields_mcp(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """extract_fields MCP tool returns custom fields for a stored entry."""
        from autoinfo.mcp.server import _handle_extract_fields

        # Create a mock entry for the KB lookup
        mock_entry = {
            "entry_id": "test-entry-001",
            "title": sample_item.title,
            "source_platform": "pubmed",
            "source_type": "api",
            "source_url": "https://example.com",
            "content": sample_item.content,
            "collected_at": sample_item.collected_at,
            "domain": "medical-research",
            "file_path": "",
        }

        mock_kb = MagicMock(spec=KBStore)
        mock_kb.get_entry.return_value = mock_entry

        with (
            patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom),
            patch("autoinfo.kb.KBStore", return_value=mock_kb),
        ):
            result = _handle_extract_fields(
                content_id="test-entry-001",
                schema=["methodology", "findings"],
            )

        assert result["content_id"] == "test-entry-001"
        assert "custom_fields" in result
        assert result["custom_fields"].get("methodology") == "Randomized controlled trial"
        assert "findings" in result["custom_fields"]

    def test_extract_fields_nonexistent_entry(self) -> None:
        """extract_fields MCP returns NotFound for unknown entry."""
        from autoinfo.kb import KBStore
        from autoinfo.mcp.server import _handle_extract_fields

        mock_kb = MagicMock(spec=KBStore)
        mock_kb.get_entry.return_value = None

        with patch("autoinfo.kb.KBStore", return_value=mock_kb):
            result = _handle_extract_fields(
                content_id="nonexistent-id",
                schema=["methodology"],
            )
        assert result["error"]["code"] == "NotFound"


# ===================================================================
# 7. get_extraction MCP tool returns correct data
# ===================================================================


class TestMcpGetExtraction:
    """``get_extraction`` MCP tool — retrieve stored extraction data."""

    def test_get_extraction_returns_custom_fields(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_with_custom: MagicMock,
    ) -> None:
        """get_extraction returns extracted_fields from frontmatter."""
        from autoinfo.mcp.server import _handle_get_extraction

        # Create a real KB entry file so get_extraction can read its frontmatter
        kb_base = tmp_path / "knowledge"
        store = KBStore(base_path=kb_base)
        extractor = LLMExtractor()
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_with_custom):
            extraction = extractor.extract(sample_item, schema=["methodology"])
        entry = store.store_entry(sample_item, extraction)

        # Mock the KBStore lookup to return metadata pointing to the real file
        meta = store.index.get_entry(entry.entry_id)
        assert meta is not None

        mock_kb = MagicMock(spec=KBStore)
        mock_kb.get_entry.return_value = {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "summary": extraction.tl_dr,
            "relevance_score": 92.0,
            "dedup_status": "unique",
            "quality_tier": 1,
            "file_path": entry.file_path,
        }

        with patch("autoinfo.kb.KBStore", return_value=mock_kb):
            result = _handle_get_extraction(content_id=entry.entry_id)

        assert result["content_id"] == entry.entry_id
        assert "extracted_fields" in result
        assert result["extracted_fields"].get("methodology") == "Randomized controlled trial"
        assert result["summary"] != ""

    def test_get_extraction_no_custom_fields(
        self,
        tmp_path: Path,
        sample_item: Item,
        mock_litellm_default_only: MagicMock,
    ) -> None:
        """get_extraction returns empty extracted_fields when none stored."""
        from autoinfo.mcp.server import _handle_get_extraction

        kb_base = tmp_path / "knowledge"
        store = KBStore(base_path=kb_base)
        extractor = LLMExtractor()
        with patch.object(LLMExtractor, "_get_litellm", return_value=mock_litellm_default_only):
            extraction = extractor.extract(sample_item)
        entry = store.store_entry(sample_item, extraction)

        meta = store.index.get_entry(entry.entry_id)
        mock_kb = MagicMock(spec=KBStore)
        mock_kb.get_entry.return_value = {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "summary": extraction.tl_dr,
            "relevance_score": 0.0,
            "dedup_status": "unique",
            "quality_tier": 1,
            "file_path": entry.file_path,
        } if meta else None

        with patch("autoinfo.kb.KBStore", return_value=mock_kb):
            result = _handle_get_extraction(content_id=entry.entry_id)
        assert result["extracted_fields"] == {}

    def test_get_extraction_nonexistent_entry(self) -> None:
        """get_extraction MCP returns NotFound for unknown entry."""
        from autoinfo.kb import KBStore
        from autoinfo.mcp.server import _handle_get_extraction

        mock_kb = MagicMock(spec=KBStore)
        mock_kb.get_entry.return_value = None

        with patch("autoinfo.kb.KBStore", return_value=mock_kb):
            result = _handle_get_extraction(content_id="nonexistent-id")
        assert result.get("error_code") == "NotFound"
