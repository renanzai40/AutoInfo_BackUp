"""Collection-layer domain noise guard tests (#332-B).

Locks the real-SEC-title blind spot: SEC EDGAR items carry titles like
``8-K Apple Inc. (2025-01-15)`` (form + company + date), so the guard must
match the bare form numbers ("8-K", "10-K", "10-Q") — the "SEC 8-K" /
"8-K filing" phrasings never appear in real titles.
"""

from __future__ import annotations

from autoinfo.collect import _item_matches_domain_noise
from autoinfo.models import Item


def _item(iid: str, title: str, content: str) -> Item:
    return Item(
        id=iid,
        source_name="sec_edgar",
        source_type="sec_edgar",
        source_platform="sec_edgar",
        source_url=f"https://x.com/{iid}",
        title=title,
        content=content,
        collected_at="2026-01-01",
    )


def test_real_sec_title_caught_by_noise_guard() -> None:
    # Real SEC EDGAR title format: `8-K Apple Inc. (2025-01-15)` with the
    # form echoed in the content metadata JSON excerpt.
    assert _item_matches_domain_noise(
        _item("r1", "8-K Apple Inc. (2025-01-15)", '{"form": "8-K"}'),
        "financial-intelligence",
    )
    assert _item_matches_domain_noise(
        _item("r2", "10-K Microsoft Corp (2025-06-30)", '{"form": "10-K"}'),
        "financial-intelligence",
    )
    assert _item_matches_domain_noise(
        _item("r3", "10-Q Apple Inc. (2025-04-30)", '{"form": "10-Q"}'),
        "financial-intelligence",
    )


def test_real_sec_title_caught_for_ai_commercial() -> None:
    # ai-commercial carries the same bare-form keywords for parity.
    assert _item_matches_domain_noise(
        _item("r4", "8-K Apple Inc. (2025-01-15)", '{"form": "8-K"}'),
        "ai-commercial",
    )
    assert _item_matches_domain_noise(
        _item("r5", "10-K Microsoft Corp (2025-06-30)", '{"form": "10-K"}'),
        "ai-commercial",
    )


def test_clean_in_domain_item_not_flagged() -> None:
    # Control: in-domain content with no SEC form markers is NOT flagged.
    assert not _item_matches_domain_noise(
        _item("c1", "Apple announces new M5 chip", "Apple unveiled its next-gen silicon."),
        "financial-intelligence",
    )
    assert not _item_matches_domain_noise(
        _item("c2", "Apple announces new M5 chip", "Apple unveiled its next-gen silicon."),
        "ai-commercial",
    )
