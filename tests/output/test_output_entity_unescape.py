"""Output-layer HTML entity unescape tests (backup issue #78).

Collectors may leave raw HTML entities (``&#039;``, ``&amp;``, ``&#8217;``)
in entry text that reaches rendered products despite the storage-layer
decode (pre-#51 entries, bypassed paths).  ``_render_markdown`` and
``_render_digest_html`` run a final idempotent ``html.unescape`` pass so
products are R4-clean; JSON output is left untouched (structured data).
"""

from __future__ import annotations

from autoinfo.output import _render_digest_html, _render_markdown


def _md_context(**overrides: object) -> dict[str, object]:
    ctx: dict[str, object] = {
        "title": "Weekly Digest",
        "domain": "hindi-learning",
        "period_label": "Weekly",
        "date_from": "2026-08-21",
        "date_to": "2026-08-28",
        "generated_at": "2026-08-28T00:00:00+00:00",
        "entries": [
            {
                "title": "PM मोदी की &#039;प्रगति&#039; बैठक",
                "summary": "Cyber fraud &amp; infrastructure review",
                "source_url": "https://example.com/1",
                "source_label": "example",
                "collected_at": "2026-08-25T00:00:00+00:00",
                "relevance_score": 50.0,
            }
        ],
    }
    ctx.update(overrides)
    return ctx


class TestRenderMarkdownUnescape:
    def test_named_and_numeric_entities_decoded(self) -> None:
        out = _render_markdown(_md_context())
        assert "&#039;" not in out
        assert "&amp;" not in out
        assert "प्रगति" in out
        # The apostrophe entity becomes a real quote; the ampersand decodes.
        assert "&#039;प्रगति&#039;" not in out

    def test_idempotent_no_corruption(self) -> None:
        """Decoding twice must not change the result (html.unescape is
        idempotent for named/numeric entities)."""
        first = _render_markdown(_md_context())
        from autoinfo.kb import _decode_html_entities

        assert _decode_html_entities(first) == first

    def test_double_encoded_collapses(self) -> None:
        """&amp;lt; (double-encoded) collapses to '<' via the bounded loop."""
        out = _render_markdown(_md_context(entries=[
            {
                "title": "Tag &amp;lt;b&gt; test",
                "summary": "",
                "source_url": "https://example.com/2",
                "source_label": "example",
                "collected_at": "2026-08-25T00:00:00+00:00",
                "relevance_score": 40.0,
            }
        ]))
        assert "&amp;lt;" not in out


class TestRenderDigestHtmlUnescape:
    def test_html_surface_decodes_entities(self) -> None:
        ctx = _md_context()
        out = _render_digest_html(ctx)
        assert "&#039;" not in out
        assert "&amp;" not in out
