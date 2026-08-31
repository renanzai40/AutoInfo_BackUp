"""Tutorial completeness tests (backup issue #92).

An LLM that returns a "Weekly Digest" shell (digest-style title, title-copy
objectives, empty summary/content, TBD duration) must still render a
complete Tutorial: correct header, filled header fields, a real Summary,
learning-verb objectives (never title copies), and a language-teaching
structure (vocabulary/grammar) for language-learning domains.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

from autoinfo.output import PRODUCT_TEMPLATES, generate_digest, generate_tutorial


def _entry(eid: str, title: str, summary: str, url: str, lang: str = "fr") -> dict[str, object]:
    return {
        "entry_id": eid,
        "title": title,
        "domain": "french-learning",
        "tier": "01-Raw",
        "source_url": url,
        "source_type": "rss",
        "source_platform": "france24",
        "collected_at": "2026-08-25T00:00:00+00:00",
        "summary": summary,
        "quality_tier": 2,
        "relevance_score": 50.0,
        "dedup_status": "unique",
        "file_path": "",
        "tags": "[]",
        "custom_fields": "{}",
        "language": lang,
    }


_ENTRIES = [
    _entry(
        "1",
        "Le gouvernement annonce une réforme",
        "Le gouvernement a annoncé une réforme importante pour les étudiants.",
        "https://f24.fr/1",
    ),
    _entry(
        "2",
        "La chanteuse donne un concert",
        "La chanteuse a donné un concert à Paris hier soir.",
        "https://lefigaro.fr/2",
    ),
]

# The exact shell the issue observed: Weekly Digest title, title-copy
# objectives, TBD duration, empty summary/content, no teaching structure.
_SHELL = {
    "title": "Weekly Digest — french-learning",
    "target_audience": "student",
    "duration": "TBD",
    "prerequisites": "None",
    "objectives": ["Le gouvernement annonce une réforme", "La chanteuse donne un concert"],
    "content": [],
    "exercises": [],
    "summary": "",
    "further_reading": [],
    "vocabulary": [],
    "grammar": [],
}


def _render(shell: dict[str, object], domain: str = "french-learning") -> str:
    with (
        patch("autoinfo.output.KBStore") as mkb,
        patch("autoinfo.output._call_llm_for_tutorial") as mllm,
        patch("autoinfo.output._build_tutorial_markdown_prompt", return_value="p"),
    ):
        store = MagicMock()
        store.list_entries.return_value = _ENTRIES
        mkb.return_value = store
        mllm.return_value = shell
        out = generate_tutorial(domain=domain, target_audience="student", format="markdown")
        assert isinstance(out, str)
        return out


class TestTutorialCompleteness:
    def test_shell_header_is_tutorial_not_digest(self) -> None:
        out = _render(_SHELL)
        assert "# french-learning — Tutorial" in out
        assert "Weekly Digest" not in out

    def test_header_fields_filled(self) -> None:
        out = _render(_SHELL)
        assert "**Duration**: 2 minutes" in out
        assert "no prior experience required" in out
        assert "TBD" not in out

    def test_summary_present(self) -> None:
        out = _render(_SHELL)
        assert "## Summary" in out
        assert "walks through 2 knowledge base entries" in out

    def test_objectives_not_title_copies(self) -> None:
        out = _render(_SHELL)
        assert "Understand the key findings in" in out
        # No objective is a bare entry title.
        assert "- Le gouvernement annonce une réforme" not in out

    def test_lang_domain_has_vocabulary_and_grammar(self) -> None:
        out = _render(_SHELL)
        assert "## Vocabulary" in out
        assert "key vocabulary" in out
        assert "## Grammar" in out
        assert "Sentence structure" in out

    def test_non_lang_domain_no_fake_vocabulary(self) -> None:
        out = _render(_SHELL, domain="medical-research")
        # Non-lang domain: vocabulary/grammar stay empty (no fabricated list).
        assert "## Vocabulary" not in out or "no vocabulary list yet" in out


def _digest_render_tutorial(entries: list[dict[str, object]] | None = None) -> str:
    """Render the tutorial through the DIGEST path (issue #99).

    The production tutorial artifacts (``autoinfo output digest --product
    tutorial``) are generated via ``generate_digest`` with the tutorial
    registry template, NOT via ``generate_tutorial`` — so #92's header fills
    must also survive on this path.
    """
    with (
        patch("autoinfo.output.KBStore") as mkb,
        patch(
            "autoinfo.output._get_domain_source_configs",
            side_effect=lambda domain: [],  # fail-open: synthetic fixture hosts
        ),
        patch(
            "autoinfo.output._call_llm_for_digest",
            return_value={
                "executive_summary": "French-learning news roundup for this week.",
                "key_findings": [
                    {"topic": "Réforme", "detail": "Le gouvernement annonce une réforme."},
                ],
                "recommendations": ["Read the full article."],
            },
        ),
    ):
        store = MagicMock()
        store.list_entries.return_value = entries or _ENTRIES
        mkb.return_value = store
        tutorial_template = next(
            r["template"] for r in PRODUCT_TEMPLATES if r["name"] == "tutorial"
        )
        out = generate_digest(
            domain="french-learning",
            period="weekly",
            format="markdown",
            product_template=tutorial_template,
        )
        assert isinstance(out, str)
        return out


class TestDigestPathTutorialH1:
    """Issue #99 — ``--product tutorial`` renders a Tutorial H1, never Digest.

    Before the fix the digest-path H1 came from ``_PRODUCT_H1_WORDS`` which
    had no ``tutorial`` entry, so every tutorial artifact rendered
    ``# Weekly Digest — <domain>``.  After the fix it must render
    ``# Weekly Tutorial — <domain>`` AND keep the #92 header fills (Target
    Audience / Duration / Prerequisites / Summary) non-empty on the same
    path.
    """

    def test_h1_is_weekly_tutorial_not_digest(self) -> None:
        out = _digest_render_tutorial()
        assert "# Weekly Tutorial — french-learning" in out
        assert "Weekly Digest" not in out

    def test_header_fields_filled_on_digest_path(self) -> None:
        out = _digest_render_tutorial()
        assert "**Target Audience**: general audience" in out
        assert "**Duration**: 2 minutes" in out
        assert "no prior experience required" in out
        assert "## Summary" in out
        assert "walks through 2 knowledge base entries" in out


class TestTutorialEntryCap:
    """Backup issue #103 — ``generate_tutorial`` must cap KB entries fed to
    the LLM at 10 (#178 protocol).

    Before the fix ``entry_summaries`` iterated **all** filtered entries, so
    thick domains (medical-research: 602 KB files, gaming: 208, korean:
    162) blew the DeepSeek-V4-Flash reasoning-model prompt out of the safe
    window and timed out producing a 0B empty shell.  The cap keeps the
    prompt small while still grounding the tutorial in domain facts — and
    thin domains (well under 10) must be untouched.
    """

    @staticmethod
    def _prompt_entry_ids(n_entries: int) -> tuple[list[str], str]:
        """Run ``generate_tutorial`` over *n_entries* fake KB entries and
        return the ``[id]`` markers that reached the LLM prompt.
        """
        entries = [
            _entry(str(i), f"Titre {i}", f"Résumé {i}", f"https://f24.fr/{i}")
            for i in range(1, n_entries + 1)
        ]
        captured: dict[str, str] = {}

        def fake_prompt(
            audience: str,
            audience_desc: str,
            entry_summaries: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            captured["summaries"] = entry_summaries
            return "SENTINEL-PROMPT"

        with (
            patch("autoinfo.output.KBStore") as mkb,
            patch("autoinfo.output._call_llm_for_tutorial", return_value={}),
            patch(
                "autoinfo.output._build_tutorial_markdown_prompt",
                side_effect=fake_prompt,
            ),
        ):
            store = MagicMock()
            store.list_entries.return_value = entries
            mkb.return_value = store
            out = generate_tutorial(
                domain="french-learning", target_audience="student", format="markdown"
            )
            assert isinstance(out, str)
        markers = re.findall(r"\[(\d+)\]", captured.get("summaries", ""))
        return markers, captured.get("summaries", "")

    def test_thick_domain_prompt_capped_at_ten_entries(self) -> None:
        markers, summaries = self._prompt_entry_ids(15)
        assert len(markers) == 10, (len(markers), summaries)
        assert "[11]" not in summaries, "entry #11 leaked past the cap"
        assert "[15]" not in summaries, "tail entries leaked past the cap"

    def test_capped_entries_carry_real_source_urls(self) -> None:
        _, summaries = self._prompt_entry_ids(15)
        assert summaries.count("(Source: https://f24.fr/") == 10, summaries

    def test_thin_domain_under_cap_unchanged(self) -> None:
        markers, _ = self._prompt_entry_ids(3)
        assert markers == ["1", "2", "3"], markers
