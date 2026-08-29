"""Tutorial completeness tests (backup issue #92).

An LLM that returns a "Weekly Digest" shell (digest-style title, title-copy
objectives, empty summary/content, TBD duration) must still render a
complete Tutorial: correct header, filled header fields, a real Summary,
learning-verb objectives (never title copies), and a language-teaching
structure (vocabulary/grammar) for language-learning domains.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autoinfo.output import generate_tutorial


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
    _entry("1", "Le gouvernement annonce une réforme",
           "Le gouvernement a annoncé une réforme importante pour les étudiants.",
           "https://f24.fr/1"),
    _entry("2", "La chanteuse donne un concert",
           "La chanteuse a donné un concert à Paris hier soir.",
           "https://lefigaro.fr/2"),
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
        out = generate_tutorial(
            domain=domain, target_audience="student", format="markdown"
        )
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
