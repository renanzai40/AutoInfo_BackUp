"""Language-learning tutorial generation tests (backup issues #59, #61, #62).

- #59: language-learning domains must get a language-teaching tutorial
  structure (Vocabulary / Grammar / target-language exercises), NOT a news
  title list with English retelling exercises.
- #61: tutorial body/exercises must be constrained to the domain's
  ``default_language`` (no random English), and collected entries from
  non-target-language sources must not feed the tutorial.
- #62: the tutorial prompt must forbid fabricating causal attributions the
  source entries do not claim (e.g. ``due to COVID-19``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.output import (
    _build_tutorial_json_prompt,
    _build_tutorial_markdown_prompt,
    _entry_derived_sections,
    _filter_foreign_language_teaching_entries,
    _parse_tutorial_markdown,
    _render_tutorial_template,
    generate_tutorial,
)


def _plain_prompt(lang_learning: bool = False, target_language: str = "") -> str:
    return _build_tutorial_markdown_prompt(
        "student",
        "foundational concepts, simplified explanations, step-by-step learning",
        "- [1] Sample article: A short summary (Source: https://example.com/1)",
        "",
        lang_learning=lang_learning,
        target_language=target_language,
    )


def _json_prompt(lang_learning: bool = False, target_language: str = "") -> str:
    return _build_tutorial_json_prompt(
        "student",
        "foundational concepts, simplified explanations, step-by-step learning",
        "- [1] Sample article: A short summary (Source: https://example.com/1)",
        "",
        lang_learning=lang_learning,
        target_language=target_language,
    )


# ---------------------------------------------------------------------------
# #59: language-teaching structure for language-learning domains
# ---------------------------------------------------------------------------


class TestLangLearningPrompt:
    def test_markdown_prompt_requires_vocabulary_section(self) -> None:
        prompt = _plain_prompt(lang_learning=True, target_language="ru")
        assert "## Vocabulary" in prompt
        assert "part of speech" in prompt.lower() or "example sentence" in prompt.lower()

    def test_markdown_prompt_requires_grammar_section(self) -> None:
        prompt = _plain_prompt(lang_learning=True, target_language="ru")
        assert "## Grammar" in prompt

    def test_markdown_prompt_requires_target_language_body(self) -> None:
        prompt = _plain_prompt(lang_learning=True, target_language="ru")
        assert "Russian" in prompt
        assert "in the target language" in prompt.lower()

    def test_markdown_prompt_objectives_are_language_goals(self) -> None:
        prompt = _plain_prompt(lang_learning=True, target_language="fr")
        assert "language" in prompt.lower()
        assert "Learning Objectives" in prompt

    def test_non_lang_domain_unchanged(self) -> None:
        prompt = _plain_prompt(lang_learning=False)
        assert "## Vocabulary" not in prompt
        assert "## Grammar" not in prompt
        # The non-language skeleton still has the standard sections.
        assert "## Learning Objectives" in prompt
        assert "## Content" in prompt
        assert "## Exercises" in prompt

    def test_json_prompt_requires_vocabulary_field(self) -> None:
        prompt = _json_prompt(lang_learning=True, target_language="es")
        assert '"vocabulary"' in prompt

    def test_json_prompt_requires_grammar_field(self) -> None:
        prompt = _json_prompt(lang_learning=True, target_language="es")
        assert '"grammar"' in prompt

    def test_json_non_lang_unchanged(self) -> None:
        prompt = _json_prompt(lang_learning=False)
        assert '"vocabulary"' not in prompt
        assert '"grammar"' not in prompt


# ---------------------------------------------------------------------------
# #62: no fabricated causal attribution in the prompt
# ---------------------------------------------------------------------------


class TestNoFabricatedAttribution:
    def test_markdown_prompt_forbids_fabricated_causal_attribution(self) -> None:
        prompt = _plain_prompt(lang_learning=True, target_language="ru")
        assert "causal" in prompt.lower() or "attribution" in prompt.lower()
        assert "not" in prompt.lower()

    def test_non_lang_prompt_also_forbids_fabrication(self) -> None:
        prompt = _plain_prompt(lang_learning=False)
        assert "causal" in prompt.lower() or "attribution" in prompt.lower()


# ---------------------------------------------------------------------------
# #59: markdown parser extracts Vocabulary / Grammar sections
# ---------------------------------------------------------------------------


class TestParseVocabularyGrammar:
    def _markdown(self) -> str:
        return (
            "# Russian Current Events Tutorial\n"
            "Duration: 30 minutes\n"
            "Prerequisites: A1\n\n"
            "## Learning Objectives\n"
            "- Understand a news headline in Russian\n\n"
            "## Vocabulary\n"
            "- банк — bank (noun) — example: ...\n"
            "- экономика — economy (noun) — example: ...\n\n"
            "## Grammar\n"
            "- Genitive case for negation\n"
            "- Verb aspect: perfective vs imperfective\n\n"
            "## Content\n"
            "### Российские новости\n"
            "Текст на русском.\n\n"
            "## Exercises\n"
            "- Write a summary in Russian\n\n"
            "## Summary\n"
            "Краткое содержание.\n"
        )

    def test_parses_vocabulary_section(self) -> None:
        result = _parse_tutorial_markdown(self._markdown())
        assert result["vocabulary"]
        assert any("банк" in v for v in result["vocabulary"])

    def test_parses_grammar_section(self) -> None:
        result = _parse_tutorial_markdown(self._markdown())
        assert result["grammar"]
        assert any("Genitive case" in g for g in result["grammar"])

    def test_non_lang_markdown_has_empty_lists(self) -> None:
        result = _parse_tutorial_markdown(
            "# Tutorial\n## Learning Objectives\n- A\n## Content\n### C\nBody.\n"
        )
        assert result["vocabulary"] == []
        assert result["grammar"] == []


# ---------------------------------------------------------------------------
# #59: template renders Vocabulary / Grammar only when present
# ---------------------------------------------------------------------------


class TestTemplateVocabularyGrammar:
    def test_renders_vocabulary_section_when_present(self) -> None:
        context: dict[str, Any] = {
            "title": "T",
            "domain": "russian-learning",
            "target_audience": "student",
            "duration": "30 minutes",
            "prerequisites": "None",
            "objectives": ["obj"],
            "content": [{"heading": "h", "body": "b"}],
            "exercises": [],
            "summary": "s",
            "further_reading": [],
            "generated_at": "2026-08-28",
            "vocabulary": ["банк — bank (noun)", "экономика — economy"],
            "grammar": ["Genitive case for negation"],
            "collection_id": "",
        }
        rendered = _render_tutorial_template(context)
        assert "## Vocabulary" in rendered
        assert "банк" in rendered
        assert "## Grammar" in rendered
        assert "Genitive case" in rendered

    def test_non_lang_context_omits_sections(self) -> None:
        context: dict[str, Any] = {
            "title": "T",
            "domain": "medical-research",
            "target_audience": "student",
            "duration": "30 minutes",
            "prerequisites": "None",
            "objectives": ["obj"],
            "content": [{"heading": "h", "body": "b"}],
            "exercises": [],
            "summary": "s",
            "further_reading": [],
            "generated_at": "2026-08-28",
            "vocabulary": [],
            "grammar": [],
            "collection_id": "",
        }
        rendered = _render_tutorial_template(context)
        assert "## Vocabulary" not in rendered
        assert "## Grammar" not in rendered


# ---------------------------------------------------------------------------
# #59: KB-derived fallback uses target-language exercises, not English
# ---------------------------------------------------------------------------


class TestEntryDerivedSectionsLang:
    _ENTRIES = [
        {
            "entry_id": "e1",
            "title": "Российские новости",
            "summary": "Текст на русском.",
            "source_url": "https://example.com/1",
        }
    ]

    def test_lang_learning_fallback_exercises_are_target_language(self) -> None:
        objectives, content, exercises, further = _entry_derived_sections(
            self._ENTRIES,
            lang_learning=True,
            target_language="ru",
        )
        assert objectives
        ex = exercises[0]
        joined = f"{ex['title']} {ex['description']}".lower()
        assert "summary in" in joined or "in russian" in joined
        assert "what is the key finding" not in joined

    def test_non_lang_fallback_unchanged(self) -> None:
        objectives, content, exercises, further = _entry_derived_sections(self._ENTRIES)
        ex = exercises[0]
        assert "What is the key finding" in ex["title"]


# ---------------------------------------------------------------------------
# #61: tutorial excludes entries about OTHER languages (topic-level guard)
# ---------------------------------------------------------------------------


class TestFilterForeignLanguageTeaching:
    def test_drops_spanish_teaching_post_from_english_domain(self) -> None:
        entries = [
            {
                "entry_id": "en-1",
                "title": '"Y" vs. "e": What does "y" mean in Spanish?',
                "summary": "This article explains the Spanish conjunction 'y'.",
                "source_url": "https://blog.duolingo.com/y-vs-e",
            },
            {
                "entry_id": "en-2",
                "title": "Hospital nursery fire kills 14 newborns",
                "summary": "Tragedy in a hospital nursery.",
                "source_url": "https://www.example.com/en/2",
            },
        ]
        kept = _filter_foreign_language_teaching_entries(entries, "en")
        assert [e["entry_id"] for e in kept] == ["en-2"]

    def test_keeps_target_language_entries(self) -> None:
        entries = [
            {
                "entry_id": "es-1",
                "title": "El Banco Central sube los tipos",
                "summary": "Noticia en español.",
                "source_url": "https://www.example.com/es/1",
            }
        ]
        kept = _filter_foreign_language_teaching_entries(entries, "es")
        assert [e["entry_id"] for e in kept] == ["es-1"]

    def test_non_lang_domain_unchanged(self) -> None:
        entries = [
            {
                "entry_id": "m1",
                "title": "New cancer therapy trial shows promise",
                "summary": "Medical research news.",
                "source_url": "https://www.example.com/m/1",
            }
        ]
        kept = _filter_foreign_language_teaching_entries(entries, "")
        assert [e["entry_id"] for e in kept] == ["m1"]


# ---------------------------------------------------------------------------
# #61/#63: end-to-end — english-learning tutorial drops the Spanish post
# ---------------------------------------------------------------------------


class TestTutorialExcludesForeignLanguage:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_tutorial")
    def test_english_tutorial_drops_spanish_teaching_post(
        self, mock_llm: MagicMock, mock_kb_store: MagicMock
    ) -> None:
        store = MagicMock()
        store.list_entries.return_value = [
            {
                "entry_id": "en-1",
                "title": '"Y" vs. "e": What does "y" mean in Spanish?',
                "domain": "english-learning",
                "tier": "01-Raw",
                "source_url": "https://blog.duolingo.com/y-vs-e",
                "source_type": "rss",
                "source_platform": "rss",
                "language": "en",
                "collected_at": "2026-08-25T00:00:00+00:00",
                "summary": "The Spanish conjunction 'y'.",
                "tags": "[]",
                "quality_tier": 1,
                "relevance_score": 80.0,
            },
            {
                "entry_id": "en-2",
                "title": "Hospital nursery fire kills 14 newborns",
                "domain": "english-learning",
                "tier": "01-Raw",
                "source_url": "https://www.example.com/en/2",
                "source_type": "rss",
                "source_platform": "rss",
                "language": "en",
                "collected_at": "2026-08-25T00:00:00+00:00",
                "summary": "Tragedy in a hospital nursery.",
                "tags": "[]",
                "quality_tier": 1,
                "relevance_score": 80.0,
            },
        ]
        mock_kb_store.return_value = store
        mock_llm.return_value = {
            "title": "English Tutorial",
            "objectives": ["Understand a news headline in English"],
            "content": [{"heading": "News", "body": "Body in English."}],
            "exercises": [],
        }
        body = generate_tutorial(domain="english-learning", format="markdown")
        assert '"Y" vs. "e"' not in body
        assert "Hospital nursery fire" in body