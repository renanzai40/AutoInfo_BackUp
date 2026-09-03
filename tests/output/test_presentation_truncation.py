"""Unit tests for word-safe presentation truncation (issue #201).

The KB-derived presentation fallback sliced titles/content with raw
``[:80]`` / ``[:600]``, cutting words mid-way (``"police offi"``,
``"product syste"``).  ``_truncate_ellipsis`` must only ever break on a
complete word boundary and must keep currency figures (``$8.5 billion``)
intact.
"""

from __future__ import annotations

from autoinfo.output import _truncate_ellipsis


class TestTruncateEllipsis:
    def test_keeps_complete_word_then_ellipsis(self) -> None:
        """A cut that would land mid-word keeps the full previous word + '…'.

        Naive ``text[:17]`` is ``"police officers a"`` (mid-``"arrest"``);
        word-safe output keeps ``"officers"`` whole and appends the
        ellipsis.  A tighter naive cut (``"police offi"``) is likewise
        completed to a whole-word prefix, never ``"police offi"``.
        """
        text = "police officers arrest the suspect"
        assert _truncate_ellipsis(text, 17) == "police officers…"
        truncated = _truncate_ellipsis(text, 11)
        assert "police offi" not in truncated
        assert truncated == "police…"

    def test_no_truncation_when_fits(self) -> None:
        text = "short title"
        assert _truncate_ellipsis(text, 80) == "short title"

    def test_preserves_currency_figure(self) -> None:
        """``$8.5 billion`` must never be split as ``$8.5 bil…``."""
        text = "The company raised $8.5 billion in its latest round of financing"
        out = _truncate_ellipsis(text, 40)
        # The intact figure must survive, and the ellipsis must only ever
        # follow a complete word (here: "...in its…"), never a mid-word cut.
        assert "$8.5 billion" in out
        assert out == "The company raised $8.5 billion in its…"
        assert out.endswith("…")

    def test_single_overlong_word_falls_back_to_hard_cut(self) -> None:
        """When no earlier break exists, truncate hard and append '…'."""
        # "supercal" is 8 chars (the limit); "supercali" would be 9.
        out = _truncate_ellipsis("supercalifragilistic", 8)
        assert out == "supercal…"