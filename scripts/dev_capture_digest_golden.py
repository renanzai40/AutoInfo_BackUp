"""Scratch script — capture the CURRENT generate_digest render on a fixed
5-entry fixture KB (2 sources, all active) into tests/output/fixtures/digest_golden.md.

TDD RED artifact for todo 1 (cross-product-coherence-119-120): the render must be
deterministic — `_call_llm_for_digest` is patched to a canned synthesis (D1
sections) and `datetime.now(timezone.utc)` is frozen.  Run from repo root:

    python3 scripts/dev_capture_digest_golden.py > /tmp/opencode/golden.md

The captured bytes are then committed as the golden fixture.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from autoinfo.output import generate_digest

FROZEN_NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
FROZEN_TODAY = FROZEN_NOW.date()


_URLS = [
    "https://techcrunch.com/category/artificial-intelligence/1",
    "https://techcrunch.com/category/artificial-intelligence/2",
    "https://techcrunch.com/category/artificial-intelligence/3",
    "https://arstechnica.com/ai/2026/08/funding-round-4",
    "https://arstechnica.com/ai/2026/08/funding-round-5",
]

_SOURCES = ["techcrunch-ai", "techcrunch-ai", "techcrunch-ai", "ars-technica", "ars-technica"]


def _entry(i: int) -> dict[str, Any]:
    return {
        "entry_id": f"tech-e{i}",
        "title": f"AI funding round {i}: model inference costs fall",
        "summary": f"Startup {i} cut inference cost by 40% this week.",
        "domain": "tech-ai-developer",
        "tier": "01-Raw",
        "language": "en",
        "source_url": _URLS[i - 1],
        "source_type": "rss",
        "source_platform": _SOURCES[i - 1],
        "collected_at": f"2026-08-2{i}:10:00:00Z",
        "relevance_score": 90.0 - (i % 10),
        "tags": '["AI", "funding"]',
        "quality_tier": 1,
        "dedup_status": "unique",
        "file_path": "",
        "custom_fields": "{}",
    }


def _canned_llm(prompt: str, config: Any = None) -> dict[str, Any]:
    del prompt, config
    return {
        "executive_summary": (
            "This week's developments center on falling model inference costs "
            "driving new AI funding rounds."
        ),
        "key_findings": [
            {"topic": "Inference costs", "detail": "Startups report 40% cost cuts."},
        ],
        "trends": ["Cheaper inference"],
        "recommendations": ["Watch the inference pricing race."],
    }


def main() -> None:
    entries = [_entry(i) for i in range(1, 6)]
    store = type("Store", (), {})()
    store.list_entries = lambda **kwargs: list(entries)
    store.list_kb_tier = lambda **kwargs: []

    class _KB:
        def __init__(self) -> None:
            pass

        def list_entries(self, **kwargs: Any) -> list[dict[str, Any]]:
            return list(entries)

        def list_kb_tier(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def promote_kb_draft(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

        def flag_for_knowledge_base(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {}

    with (
        patch("autoinfo.output.KBStore", return_value=_KB()),
        patch("autoinfo.output._call_llm_for_digest", side_effect=_canned_llm),
        patch(
            "autoinfo.output.datetime",
            **{"now": lambda tz=None: FROZEN_NOW if tz == timezone.utc else FROZEN_NOW},
        ),
        patch(
            "autoinfo.output.date",
            **{"today": lambda: FROZEN_TODAY},
        ),
    ):
        result = generate_digest(domain="tech-ai-developer", period="weekly")
    sys_stdout = __import__("sys").stdout
    sys_stdout.write(result if isinstance(result, str) else result.output)


if __name__ == "__main__":
    main()
