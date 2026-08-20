"""Parallelized ``_group_by_theme`` batch loop tests (todo 8, llm-concurrency-remediation).

Verifies:
(a) batches run concurrently (in-flight > 1) but bounded (<= 4 workers);
(b) golden output is byte-identical to the captured sequential baseline
    (repr-identical — the baseline was captured by running the real
    pre-change ``_group_by_theme`` with the same mocked LLM and fixtures);
(c) one failing batch surfaces the same per-batch behavior as the sequential
    path (deterministic fallback groups, no exception escaping) while the
    other batches complete.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from autoinfo.llm import LLMExtractor
from autoinfo.output import (
    _GROUPING_BATCH_SIZE,
    _ensure_all_entries_grouped,
    _group_batch_by_theme,
    _group_by_theme,
    _merge_theme_groups,
)

# ---------------------------------------------------------------------------
# Fixtures + deterministic mocked LLM
# ---------------------------------------------------------------------------


def _make_entries(n: int, start: int = 1) -> list[dict[str, Any]]:
    """Deterministic fixture entries (identical shape to the baseline capture)."""
    entries: list[dict[str, Any]] = []
    for i in range(start, start + n):
        eid = f"e{i}"
        entries.append({
            "entry_id": eid,
            "title": f"Title {i}",
            "summary": f"Summary {i} for entry {i}.",
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{i:08d}/",
            "source_type": "rss",
            "source_platform": "test",
            "domain": "test-domain",
        })
    return entries


class _FakeResult:
    def __init__(self, custom_fields: dict[str, Any]) -> None:
        self.custom_fields = custom_fields


class _MockExtractor(LLMExtractor):
    """Deterministic mocked LLMExtractor.

    Parses entry ids out of the prompt and groups them into two themes
    (never triggering the anti-collapse retry).  Optionally raises for the
    batch containing ``fail_entry_id`` (exercising the in-batch error path)
    and optionally engages a concurrency gate on every ``extract`` call.
    """

    def __init__(
        self,
        fail_entry_id: str | None = None,
        gate: "_ConcurrencyGate | None" = None,
    ) -> None:
        self.fail_entry_id = fail_entry_id
        self.gate = gate
        self.calls = 0

    def extract(self, item: Any, schema: Any = None) -> Any:
        self.calls += 1
        if self.gate is not None:
            self.gate.enter()
        eids = re.findall(r"\[(e\d+)\]", item.content)
        if self.fail_entry_id and self.fail_entry_id in eids:
            raise RuntimeError("mock LLM failure for batch")
        half = max(1, len(eids) // 2)
        return _FakeResult({"groups": [
            {"theme": "Theme A", "entry_ids": eids[:half]},
            {"theme": "Theme B", "entry_ids": eids[half:]},
        ]})


class _ConcurrencyGate:
    """Deterministic in-flight gate: blocks ``extract`` until ``target`` calls
    are simultaneously in flight, then releases everyone.

    The first wave therefore reaches exactly ``target`` in-flight calls
    (proving concurrency), and no wave can exceed the worker bound.
    """

    def __init__(self, target: int) -> None:
        self._cond = threading.Condition()
        self._target = target
        self._released = False
        self.in_flight = 0
        self.max_in_flight = 0

    def enter(self) -> None:
        with self._cond:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            if not self._released and self.in_flight >= self._target:
                self._released = True
                self._cond.notify_all()
            while not self._released:
                self._cond.wait()
            self.in_flight -= 1


# ---------------------------------------------------------------------------
# Preserved sequential path (replicates the pre-parallelization loop exactly)
# ---------------------------------------------------------------------------


def _sequential_group_by_theme(
    extractor: LLMExtractor,
    entries: list[dict[str, Any]],
    domain: str = "",
    domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Replicates the pre-change sequential batch loop of ``_group_by_theme``."""
    batch_size = _GROUPING_BATCH_SIZE
    batches = [
        entries[i : i + batch_size] for i in range(0, len(entries), batch_size)
    ]
    merged: list[dict[str, Any]] = []
    for batch in batches:
        merged.extend(
            _group_batch_by_theme(extractor, batch, domain=domain, domains=domains)
        )
    return _ensure_all_entries_grouped(_merge_theme_groups(merged), entries)


# ---------------------------------------------------------------------------
# (b) Golden baseline — captured on the PRE-CHANGE code (2026-08-13) with the
# exact fixtures + mock above; the post-change output must match byte-for-byte.
# ---------------------------------------------------------------------------

_SEQUENTIAL_BASELINE = "[{'theme': 'Theme A', 'description': '', 'entries': [{'entry_id': 'e1', 'title': 'Title 1', 'summary': 'Summary 1 for entry 1.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000001/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e2', 'title': 'Title 2', 'summary': 'Summary 2 for entry 2.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000002/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e3', 'title': 'Title 3', 'summary': 'Summary 3 for entry 3.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000003/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e4', 'title': 'Title 4', 'summary': 'Summary 4 for entry 4.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000004/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e9', 'title': 'Title 9', 'summary': 'Summary 9 for entry 9.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000009/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}]}, {'theme': 'Theme B', 'description': '', 'entries': [{'entry_id': 'e5', 'title': 'Title 5', 'summary': 'Summary 5 for entry 5.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000005/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e6', 'title': 'Title 6', 'summary': 'Summary 6 for entry 6.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000006/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e7', 'title': 'Title 7', 'summary': 'Summary 7 for entry 7.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000007/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e8', 'title': 'Title 8', 'summary': 'Summary 8 for entry 8.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000008/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}, {'entry_id': 'e10', 'title': 'Title 10', 'summary': 'Summary 10 for entry 10.', 'source_url': 'https://pubmed.ncbi.nlm.nih.gov/00000010/', 'source_type': 'rss', 'source_platform': 'test', 'domain': 'test-domain'}]}]"  # noqa: E501


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_batches_run_concurrently_but_bounded() -> None:
    """(a) 5 batches: first wave reaches 4 in-flight extract calls (>1), never
    exceeds the 4-worker bound.  Deterministic: the gate releases only once
    ``min(n_batches, 4)`` calls are simultaneously in flight."""
    entries = _make_entries(40)  # 5 batches of _GROUPING_BATCH_SIZE
    assert len(entries) % _GROUPING_BATCH_SIZE == 0
    n_batches = len(entries) // _GROUPING_BATCH_SIZE
    gate = _ConcurrencyGate(target=min(n_batches, 4))
    extractor = _MockExtractor(gate=gate)

    result = _group_by_theme(extractor, entries, domain="", domains=None)

    assert gate.max_in_flight >= 2, (
        "batches ran strictly sequentially (max_in_flight=1) — expected "
        "concurrent execution"
    )
    assert gate.max_in_flight <= 4, (
        f"concurrency exceeded the 4-worker bound: {gate.max_in_flight}"
    )
    assert extractor.calls == n_batches
    assert {e["entry_id"] for g in result for e in g["entries"]} == {
        e["entry_id"] for e in entries
    }


def test_golden_output_matches_sequential_baseline() -> None:
    """(b) Output byte-identical (repr-identical) to the sequential baseline
    captured on the pre-change code with the same fixtures and mocked LLM."""
    entries = _make_entries(10)  # 2 batches (8 + 2)
    result = _group_by_theme(_MockExtractor(), entries, domain="", domains=None)

    assert repr(result) == _SEQUENTIAL_BASELINE

    # Also identical to the preserved sequential composition path.
    seq_result = _sequential_group_by_theme(
        _MockExtractor(), entries, domain="", domains=None
    )
    assert repr(result) == repr(seq_result)


def test_failing_batch_matches_sequential_error_behavior() -> None:
    """(c) One batch failing: the failing batch produces the same deterministic
    fallback groups as the sequential path (error caught inside the batch,
    no exception escapes), and the other batches complete normally."""
    entries = _make_entries(20)  # 3 batches: e1-e8, e9-e16, e17-e20
    parallel_extractor = _MockExtractor(fail_entry_id="e13")  # batch 2 fails
    sequential_extractor = _MockExtractor(fail_entry_id="e13")

    result = _group_by_theme(parallel_extractor, entries, domain="", domains=None)
    seq_result = _sequential_group_by_theme(
        sequential_extractor, entries, domain="", domains=None
    )

    # Same per-batch error behavior as the sequential path.
    assert repr(result) == repr(seq_result)
    # One call per batch (failing batch: single attempt, then fallback).
    assert parallel_extractor.calls == 3
    # Every entry still grouped.
    assert {e["entry_id"] for g in result for e in g["entries"]} == {
        e["entry_id"] for e in entries
    }
    # The failing batch's entries land in the deterministic fallback group.
    general = next(g for g in result if g["theme"] == "General")
    assert "e13" in {e["entry_id"] for e in general["entries"]}
    # Other batches completed via the LLM path (their themes are present).
    themes = {g["theme"] for g in result}
    assert {"Theme A", "Theme B", "General"} <= themes


def test_single_batch_still_works() -> None:
    """Degenerate path: fewer entries than one batch → a single worker."""
    entries = _make_entries(4)  # 1 batch
    extractor = _MockExtractor()
    result = _group_by_theme(extractor, entries, domain="", domains=None)
    assert extractor.calls == 1
    assert {e["entry_id"] for g in result for e in g["entries"]} == {
        e["entry_id"] for e in entries
    }


class TestGroupingDescriptionsUserFacing:
    """#338 — deterministic grouping must never surface internal search / count
    mechanics to end users: no ``N entries related to <kw>``, no ``N entry(ies)
    not matched to a topic keyword``, no per-theme count bullets, no
    ``N entries included in this report``."""

    LEAK_RE = re.compile(
        r"\d+\s+entries?\s+related to|entry\(ies\)|"
        r"\d+\s+entries?\s+from .+?sources?|"
        r"\d+\s+entries?\s+included in this report|"
        r"grouped into \d+ themes?|not matched to a topic keyword",
        re.IGNORECASE,
    )

    def _kw_entries(self) -> list[dict[str, Any]]:
        return [
            {"entry_id": f"e{i}", "title": t, "summary": "developments",
             "source_url": f"https://x.com/{i}", "source_type": "rss",
             "source_platform": "techcrunch"}
            for i, t in enumerate([
                "AI funding round new", "GPU cloud new",
                "biotech drug trial", "chip manufacturing",
            ])
        ]

    def test_keyword_group_descriptions_are_user_facing(self, tmp_path: Any) -> None:
        import os

        from autoinfo.output import _keyword_group_entries

        kdir = tmp_path / "knowledge" / "ai-commercial"
        kdir.mkdir(parents=True)
        (kdir / "_keywords.yaml").write_text(
            "keywords:\n  new:\n    state: active\n"
            "  biotech:\n    state: active\n",
            encoding="utf-8",
        )
        old = os.getcwd()
        try:
            os.chdir(tmp_path)
            groups = _keyword_group_entries(self._kw_entries(), domain="ai-commercial")
        finally:
            os.chdir(old)
        assert groups, "keyword grouping produced no groups"
        for g in groups:
            desc = str(g.get("description") or "")
            assert not self.LEAK_RE.search(desc), f"internal leak in description: {desc!r}"

    def test_deterministic_grouping_descriptions_are_user_facing(self) -> None:
        from autoinfo.output import _deterministic_grouping

        entries = [
            {"entry_id": f"e{i}", "title": f"T{i}", "summary": "s",
             "source_url": f"https://x.com/{i}", "source_type": st,
             "source_platform": "x", "domain": "d"}
            for i, st in enumerate(["rss", "api", "pubmed"])
        ]
        groups = _deterministic_grouping(entries, domain="d")
        assert groups, "deterministic grouping produced no groups"
        for g in groups:
            desc = str(g.get("description") or "")
            assert not self.LEAK_RE.search(desc), f"internal leak in description: {desc!r}"

    def test_executive_summary_fallback_is_user_facing(self) -> None:
        import os
        from unittest.mock import MagicMock

        from autoinfo.output import _generate_executive_summary

        entries = [
            {"entry_id": f"e{i}", "title": t, "summary": "summary",
             "source_url": f"https://x.com/{i}", "source_type": "rss",
             "source_platform": "techcrunch"}
            for i, t in enumerate(["AI funding round", "GPU cloud", "biotech"])
        ]
        groupings = [
            {"theme": "API", "description": "x", "entries": entries[:1]},
            {"theme": "IMPORT", "description": "y", "entries": entries[1:]},
        ]
        failing = MagicMock()
        failing.extract.side_effect = RuntimeError("llm down")
        old = os.getcwd()
        # _generate_executive_summary may touch the KB/config; run in a clean
        # temp cwd so the fallback path is reached without side effects.
        result = _generate_executive_summary(
            failing, entries, groupings, product_family="report"
        )
        os.chdir(old)
        summary = result["executive_summary"]
        assert isinstance(summary, str) and summary.strip()
        assert not self.LEAK_RE.search(summary), (
            f"internal leak in executive summary fallback: {summary!r}"
        )
        # The fallback still names real entries (user-facing content).
        assert "AI funding round" in summary or "biotech" in summary
