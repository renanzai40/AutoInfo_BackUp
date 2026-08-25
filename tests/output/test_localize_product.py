"""Product-level localization tests (issue #38).

Covers the ``autoinfo.output.localize`` pipeline: generating a product,
segmenting markdown into translatable vs protected content (URLs, code
fences, frontmatter, placeholders), batch translation via
``localize_content``, translation-QA gating with refinement, and the
``<product>-<lang>.md`` + manifest output contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from autoinfo.output.localize import (
    PROTECTED_KINDS,
    _reassemble_markdown,
    _segment_markdown,
    localize_product,
)

SAMPLE_MD = """---
title: Weekly Digest
period: 2026-W34
---

# IVF Breakthroughs

Recent studies improved [embryo selection](https://pubmed.ncbi.nlm.nih.gov/42582453/).

```python
scores = [88, 92]
```

- Oocyte vitrification outcomes
- Recombinant LH priming helps

| Metric | Value |
|--------|-------|
| Live birth | 38% |

{{custom_placeholder}}

## Neuroplasticity Update

See https://example.com for details.
"""


class TestSegmentMarkdown:
    """Translatable vs protected segmentation."""

    def test_protected_kinds_not_translated(self) -> None:
        """Code fences, frontmatter, table rows and placeholders are protected."""
        segments = _segment_markdown(SAMPLE_MD)
        translatable = "".join(s["text"] for s in segments if s["kind"] not in PROTECTED_KINDS)
        for protected in (
            "period: 2026-W34",
            "scores = [88, 92]",
            "{{custom_placeholder}}",
            "|--------|-------|",
        ):
            assert protected not in translatable, f"{protected} leaked into translatable content"

    def test_inline_urls_placeholders_sentinelized(self) -> None:
        """URLs inside text lines are stripped by the token protector."""
        from autoinfo.output.localize import _protect_tokens

        protected, tokens = _protect_tokens(
            "See https://example.com/feed and [link](https://x.io/a) and `code` and {{ph}}"
        )
        assert "https://" not in protected
        assert "{{ph}}" not in protected
        assert "`code`" not in protected
        assert tokens == [
            "[link](https://x.io/a)",
            "{{ph}}",
            "`code`",
            "https://example.com/feed",
        ]

    def test_headings_lists_tables_carry_markers(self) -> None:
        """Markers (heading #, bullets -, table pipes) survive translation."""
        segments = _segment_markdown(SAMPLE_MD)
        kinds = {s["kind"] for s in segments}
        assert "heading" in kinds
        assert "list_item" in kinds
        assert "table_row" in kinds
        for seg in segments:
            if seg["kind"] == "heading":
                assert seg["text"].startswith("#")
            if seg["kind"] == "list_item":
                assert seg["text"].startswith("- ")
            if seg["kind"] == "table_row":
                assert seg["text"].startswith("|")


class TestReassemble:
    """Rebuilding markdown preserves structure and order."""

    def test_reassemble_roundtrip_preserves_markdown(self) -> None:
        """After translation, URLs/fences/structure are byte-identical."""
        original = _segment_markdown(SAMPLE_MD)
        translated: list[dict] = []
        for seg in original:
            if seg["kind"] in PROTECTED_KINDS:
                translated.append(seg)
            else:
                translated.append({**seg, "text": f"TR:{seg['text']}", "translated": True})
        out = _reassemble_markdown(translated)
        for protected in (
            "https://pubmed.ncbi.nlm.nih.gov/42582453/",
            "```python",
            "scores = [88, 92]",
            "|--------|-------|",
            "{{custom_placeholder}}",
            "---\ntitle: Weekly Digest",
        ):
            assert protected in out
        assert "TR:# IVF Breakthroughs" in out
        assert "TR:- Oocyte vitrification outcomes" in out


class TestLocalizeProduct:
    """End-to-end pipeline with mocked LLM surfaces."""

    def test_writes_lang_file_and_manifest(self, tmp_path: Path) -> None:
        """``<product>-<lang>.md`` plus a manifest recording the language."""
        with (
            patch("autoinfo.output.localize.generate_digest", return_value=SAMPLE_MD),
            patch(
                "autoinfo.output.localize.localize_content",
                side_effect=lambda content, source_lang, target_lang, domain=None: {
                    "translated_body": f"TR:{content}",
                    "success": True,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                },
            ),
            patch("autoinfo.output.localize.run_back_translation_pipeline",
                  return_value={"quality_score": 92.0, "success": True}),
        ):
            result = localize_product(
                domain="medical-research",
                product="digest",
                period="weekly",
                target_lang="zh",
                out_dir=str(tmp_path),
                source_lang="en",
            )

        lang_dir = tmp_path / "zh"
        out_file = lang_dir / "digest-zh.md"
        assert out_file.is_file(), "localized product file missing"
        assert "TR:# IVF Breakthroughs" in out_file.read_text(encoding="utf-8")
        assert "https://pubmed.ncbi.nlm.nih.gov/42582453/" in out_file.read_text(encoding="utf-8")
        manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert isinstance(manifest, list) and manifest
        assert manifest[0]["language"] == "zh"
        assert manifest[0]["domain"] == "medical-research"
        assert manifest[0]["product"] == "digest"
        assert manifest[0]["qa"]["gate"] == "passed"
        assert result["file_path"] == str(out_file)

    def test_qa_gate_refines_low_score(self, tmp_path: Path) -> None:
        """A low back-translation score triggers one refinement pass."""
        calls: dict[str, int] = {"n": 0}

        def _flaky_score(*_args: Any, **_kwargs: Any) -> dict:
            calls["n"] += 1
            return {"quality_score": 41.0 if calls["n"] == 1 else 95.0, "success": True}

        with (
            patch("autoinfo.output.localize.generate_digest", return_value=SAMPLE_MD),
            patch(
                "autoinfo.output.localize.localize_content",
                side_effect=lambda content, source_lang, target_lang, domain=None: {
                    "translated_body": f"TR:{content}",
                    "success": True,
                },
            ),
            patch("autoinfo.output.localize.run_back_translation_pipeline",
                  side_effect=_flaky_score),
            patch("autoinfo.output.localize.refine_translation",
                  return_value={"refined_text": "REFINED", "success": True}) as refine,
        ):
            result = localize_product(
                domain="medical-research",
                product="digest",
                period="weekly",
                target_lang="ja",
                out_dir=str(tmp_path),
                source_lang="en",
            )
        assert refine.called
        assert result["qa"]["gate"] == "passed"
        assert result["qa"]["refined_count"] == 1

    def test_unknown_product_rejected(self, tmp_path: Path) -> None:
        """Unsupported product names surface a clear error."""
        with pytest.raises(ValueError, match="Unsupported product"):
            localize_product(
                domain="medical-research",
                product="presentation",
                period="weekly",
                target_lang="zh",
                out_dir=str(tmp_path),
            )

    def test_non_str_translated_body_keeps_original(self, tmp_path: Path) -> None:
        """A list-shaped translated_body (LLM array) must not crash the pipeline."""
        from autoinfo.output.localize import _translate_segment_text

        with patch(
            "autoinfo.output.localize.localize_content",
            return_value={"translated_body": ["one", "two"], "success": True},
        ):
            out = _translate_segment_text("Keep this sentence", "en", "zh", "medical-research")
        assert out == "Keep this sentence"
