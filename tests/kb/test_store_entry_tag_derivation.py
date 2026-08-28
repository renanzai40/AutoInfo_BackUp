"""KB entry tag derivation tests (issue #68, PART B).

When collectors set no ``topic_tags`` on an item, ``store_entry`` derives
tags from the ``topic_keywords`` that appear (case-insensitively) in the
CLEANED TITLE — capped at 5.  Body-only keyword hits are noise and never
produce tags.  ``topic_keywords=None`` (the api/routes.py create_entry
path) keeps the legacy empty-tags behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from autoinfo.kb import KBStore
from autoinfo.models import Item


def _store(
    tmp_path: Path,
    title: str,
    topic_tags: list[str],
    topic_keywords: list[str] | None,
) -> dict[str, Any]:
    """Run ``store_entry`` against a tmp KB and return the parsed frontmatter."""
    store = KBStore(base_path=tmp_path / "knowledge", min_content_chars=0)
    item = Item(
        id="tag-item-1",
        source_name="rss",
        source_type="rss",
        source_platform="rss",
        source_url="https://example.com/tag/1",
        title=title,
        content=(
            "Body text that also mentions IVF and embryo imaging but never "
            "appears in the title."
        ),
        content_type="text",
        collected_at="2026-07-15T10:00:00Z",
        language="en",
        domain="medical-research",
        topic_tags=topic_tags,
        quality_tier=1,
    )
    entry = store.store_entry(item, topic_keywords=topic_keywords)
    assert entry is not None
    raw = Path(entry.file_path).read_text(encoding="utf-8")
    assert raw.startswith("---")
    end = raw.find("---", 3)
    fm = yaml.safe_load(raw[3:end])
    assert isinstance(fm, dict)
    return fm


class TestStoreEntryTagDerivation:
    def test_empty_topic_tags_derives_from_matched_keywords(
        self, tmp_path: Path
    ) -> None:
        """Empty ``topic_tags`` + a keyword in the title → derived tag."""
        stored = _store(
            tmp_path,
            title="IVF outcomes improve",
            topic_tags=[],
            topic_keywords=["IVF", "embryo imaging"],
        )
        assert stored.get("tags") == ["IVF"], stored.get("tags")

    def test_derived_tags_capped_at_five(self, tmp_path: Path) -> None:
        """More than 5 title-matching keywords → at most 5 tags."""
        stored = _store(
            tmp_path,
            title="alpha beta gamma delta epsilon zeta eta theta",
            topic_tags=[],
            topic_keywords=[
                "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
            ],
        )
        tags = stored.get("tags") or []
        assert len(tags) <= 5, f"derived tags exceeded the 5 cap: {tags}"

    def test_case_insensitive_title_hit(self, tmp_path: Path) -> None:
        """Keyword ``ivf`` matches the uppercase title ``IVF Breakthrough``."""
        stored = _store(
            tmp_path,
            title="IVF Breakthrough",
            topic_tags=[],
            topic_keywords=["ivf"],
        )
        assert stored.get("tags") == ["ivf"], stored.get("tags")

    def test_no_derivation_when_topic_keywords_none(self, tmp_path: Path) -> None:
        """``topic_keywords=None`` (api/routes.py create_entry parity) →
        tags stay empty — no derivation."""
        stored = _store(
            tmp_path,
            title="IVF outcomes improve",
            topic_tags=[],
            topic_keywords=None,
        )
        assert stored.get("tags") == [], stored.get("tags")
