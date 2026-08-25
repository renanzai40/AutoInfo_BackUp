"""Unit tests for ``autoinfo.output._llm_json_extract`` retry-on-empty.

The extraction path returns an empty ``ExtractionResult`` (lenient contract)
when the LLM response cannot be parsed — a transient failure mode observed
with free-tier LLM providers under concurrent load (backup-repo #19-#38 run).
``_llm_json_extract`` must retry once before giving up, mirroring the
existing two-attempt pattern of ``_report_llm_call``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from autoinfo.output import _llm_json_extract


class _FakeResult:
    def __init__(self, custom_fields: dict) -> None:
        self.custom_fields = custom_fields


def _fake_extractor(responses: list[dict]) -> MagicMock:
    """Return an extractor whose ``extract`` returns responses in order."""
    extractor = MagicMock()
    extractor.extract.side_effect = [_FakeResult(r) for r in responses]
    return extractor


def test_returns_field_on_first_success() -> None:
    """Happy path: a parseable first response returns the field."""
    extractor = _fake_extractor([{"groups": [{"theme": "A", "entry_ids": ["e1"]}]}])
    value = _llm_json_extract(extractor, "prompt", "groups")
    assert value == [{"theme": "A", "entry_ids": ["e1"]}]
    assert extractor.extract.call_count == 1


def test_retries_once_on_empty_first_response() -> None:
    """A transient empty result triggers one retry and succeeds."""
    extractor = _fake_extractor(
        [
            {},  # first attempt: unparseable/empty response
            {"groups": [{"theme": "B", "entry_ids": ["e2"]}]},
        ]
    )
    value = _llm_json_extract(extractor, "prompt", "groups")
    assert value == [{"theme": "B", "entry_ids": ["e2"]}]
    assert extractor.extract.call_count == 2


def test_returns_none_when_both_attempts_empty() -> None:
    """Two consecutive empty responses yield None (caller falls back)."""
    extractor = _fake_extractor([{}, {}])
    value = _llm_json_extract(extractor, "prompt", "groups")
    assert value is None
    assert extractor.extract.call_count == 2


def test_missing_field_also_retries() -> None:
    """A parseable response lacking the requested field counts as failure."""
    extractor = _fake_extractor(
        [
            {"other": 1},
            {"groups": [{"theme": "C", "entry_ids": ["e3"]}]},
        ]
    )
    value = _llm_json_extract(extractor, "prompt", "groups")
    assert value == [{"theme": "C", "entry_ids": ["e3"]}]
    assert extractor.extract.call_count == 2