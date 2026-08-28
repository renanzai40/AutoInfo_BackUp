"""Near-duplicate product-layer convergence tests (backup issue #69).

The same event (e.g. Dolly Parton's death) ingested across languages and
domains is invisible to char-level G2 dedup — this locks the deterministic
product-layer convergence that collapses same-event entries to one
representative per cluster.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autoinfo.output import _converge_near_duplicates, _extract_proper_nouns


def _mk_entry(**overrides: object) -> dict[str, object]:
    """Build an entry dict with digest-test fixture defaults."""
    base: dict[str, object] = {
        "entry_id": "default-id",
        "title": "Default title",
        "domain": "french-learning",
        "source_url": "https://example.com/default",
        "source_type": "rss",
        "source_platform": "source",
        "collected_at": "2026-08-25T12:00:00",
        "summary": "",
        "quality_tier": 2,
        "relevance_score": 50.0,
        "dedup_status": "unique",
        "language": "fr",
        "tags": "[]",
        "custom_fields": "{}",
    }
    base.update(overrides)
    return base


class TestExtractProperNouns:
    def test_basic_person_name(self) -> None:
        assert _extract_proper_nouns("Dolly Parton has died at age 80") == [
            "Dolly Parton"
        ]

    def test_stoplist_phrase_removed(self) -> None:
        assert _extract_proper_nouns("New York Stock Exchange report") == []

    def test_people_names_both_kept(self) -> None:
        result = _extract_proper_nouns(
            "Dolly Parton and Donald Trump met in Nashville"
        )
        assert "Dolly Parton" in result
        assert "Donald Trump" in result

    def test_empty_title(self) -> None:
        assert _extract_proper_nouns("") == []

    def test_single_capitalized_word_not_extracted(self) -> None:
        # "Stock" alone is one word → no phrase; the second word "Exchange"
        # is also capitalized so "Stock Exchange" IS a 2-word phrase — this
        # asserts the single-word "Stock" does not produce a phrase.
        assert _extract_proper_nouns("Stock rises") == []


class TestConvergeNearDuplicates:
    def test_cross_language_same_event_converges(self) -> None:
        entries = [
            _mk_entry(
                entry_id="en-1",
                title="Dolly Parton has died",
                source_url="https://example.com/en",
                language="en",
                dedup_status="duplicate",
            ),
            _mk_entry(
                entry_id="fr-1",
                title="Mort de la star américaine Dolly Parton",
                source_url="https://example.com/fr",
                language="fr",
                dedup_status="duplicate",
            ),
            _mk_entry(
                entry_id="es-1",
                title="Muere Dolly Parton, la reina del country",
                source_url="https://example.com/es",
                language="es",
                dedup_status="duplicate",
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 1

    def test_french_duplicates_converge(self) -> None:
        entries = [
            _mk_entry(
                entry_id=f"fr-{i}",
                title=f"Mort de Dolly Parton — article {i}",
                source_url=f"https://example.com/fr/{i}",
                language="fr",
                dedup_status="duplicate",
                relevance_score=float(60 - i),
                collected_at=f"2026-08-2{3 + (i % 3)}T12:00:00",
            )
            for i in range(5)
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 1

    def test_trump_counterexample_not_merged(self) -> None:
        """Two stories both naming Trump but different events must not merge."""
        entries = [
            _mk_entry(
                entry_id="trump-1",
                title="Donald Trump visits Tokyo",
                source_url="https://example.com/tokyo",
                language="en",
                dedup_status="unique",
            ),
            _mk_entry(
                entry_id="trump-2",
                title="Donald Trump indicted by federal prosecutors",
                source_url="https://example.com/indictment",
                language="en",
                dedup_status="unique",
            ),
        ]
        # The shared proper noun "Donald Trump" alone must NOT merge two
        # different events — the titles are dissimilar enough that no
        # secondary signal fires.
        assert len(_extract_proper_nouns(entries[0]["title"])) == 1
        assert len(_extract_proper_nouns(entries[1]["title"])) == 1
        result = _converge_near_duplicates(entries)
        assert len(result) == 2

    def test_identical_source_url_never_merged(self) -> None:
        entries = [
            _mk_entry(
                entry_id="same-1",
                title="Dolly Parton has died",
                source_url="https://example.com/syndicated",
                dedup_status="duplicate",
            ),
            _mk_entry(
                entry_id="same-2",
                title="Dolly Parton est décédée",
                source_url="https://example.com/syndicated",
                dedup_status="duplicate",
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 2

    def test_representative_highest_relevance_then_earliest(self) -> None:
        entries = [
            _mk_entry(
                entry_id="low",
                title="Dolly Parton has died",
                source_url="https://example.com/low",
                relevance_score=40.0,
                collected_at="2026-08-24T12:00:00",
                dedup_status="duplicate",
            ),
            _mk_entry(
                entry_id="high",
                title="Dolly Parton est décédée à 80 ans",
                source_url="https://example.com/high",
                relevance_score=90.0,
                collected_at="2026-08-25T12:00:00",
                dedup_status="duplicate",
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 1
        assert result[0]["entry_id"] == "high"

    def test_earliest_tiebreak_when_scores_equal(self) -> None:
        entries = [
            _mk_entry(
                entry_id="early",
                title="Dolly Parton has died",
                source_url="https://example.com/early",
                relevance_score=50.0,
                collected_at="2026-08-24T12:00:00",
                dedup_status="duplicate",
            ),
            _mk_entry(
                entry_id="late",
                title="Dolly Parton est décédée",
                source_url="https://example.com/late",
                relevance_score=50.0,
                collected_at="2026-08-26T12:00:00",
                dedup_status="duplicate",
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 1
        assert result[0]["entry_id"] == "early"

    def test_out_of_window_not_merged(self) -> None:
        entries = [
            _mk_entry(
                entry_id="old",
                title="Dolly Parton has died",
                source_url="https://example.com/old",
                collected_at="2026-07-01T12:00:00",
                dedup_status="duplicate",
            ),
            _mk_entry(
                entry_id="new",
                title="Dolly Parton est décédée",
                source_url="https://example.com/new",
                collected_at="2026-08-25T12:00:00",
                dedup_status="duplicate",
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 2

    # ------------------------------------------------------------------
    # Backup issue #73 — EVENT-WORD signal for multi-angle same-event
    # obituaries.  The same death event is reported with heavily reworded
    # headlines ("Mort de Dolly Parton" vs "... est morte à l'âge de 80 ans"):
    # char-similarity drops out of the [0.5, 0.85) band, each carries only
    # ONE shared proper noun, and G2Dedup stores both as "unique" — none of
    # the pre-#73 secondary signals fire.  A canonical death-word co-occurring
    # with the shared proper noun in BOTH titles closes that gap.
    # ------------------------------------------------------------------

    @staticmethod
    def _char_ratio(a: str, b: str) -> float:
        from difflib import SequenceMatcher  # noqa: PLC0415

        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    _OBIT_TRUMP = (
        "Mort de Dolly Parton : Donald Trump fait mettre les drapeaux en berne, "
        "émotion unanime dans une Amérique divisée"
    )
    _OBIT_AGE = "Dolly Parton, reine de la musique country, est morte à l’âge de 80 ans"
    _TRIBUTE_FAUX = "Dolly Parton : celle qui portait du faux et du vrai"
    _TRIBUTE_SONGS = (
        "Jolene, I Will Always Love You, 9 to 5... Les dix titres iconiques de "
        "Dolly Parton, l’icône de la country morte à 80 ans"
    )

    def test_french_obituary_variants_merge_via_event_word(self) -> None:
        """(a) Two reworded reports of the SAME death event merge to one — all
        pre-#73 secondary signals absent (both unique, one shared noun, char
        similarity outside the [0.5, 0.85) band)."""
        entries = [
            _mk_entry(
                entry_id="obit-1",
                title=self._OBIT_TRUMP,
                source_url="https://www.lefigaro.fr/musique/obit-1",
                language="fr",
                dedup_status="unique",
                relevance_score=90.0,
                collected_at="2026-08-25T23:46:43+02:00",
            ),
            _mk_entry(
                entry_id="obit-2",
                title=self._OBIT_AGE,
                source_url="https://www.lefigaro.fr/musique/obit-2",
                language="fr",
                dedup_status="unique",
                relevance_score=70.0,
                collected_at="2026-08-25T22:26:38+02:00",
            ),
        ]
        assert len(_extract_proper_nouns(entries[0]["title"])) == 2
        assert len(_extract_proper_nouns(entries[1]["title"])) == 1
        assert not (
            0.5 <= self._char_ratio(entries[0]["title"], entries[1]["title"]) < 0.85
        )
        result = _converge_near_duplicates(entries)
        assert len(result) == 1
        assert result[0]["entry_id"] == "obit-1"

    def test_cross_language_obituaries_merge_via_event_word(self) -> None:
        """Same death event reported in two languages merges via the event
        word — both unique, one shared noun, ratio outside the char band."""
        entries = [
            _mk_entry(
                entry_id="de-obit",
                title="Dolly Parton ist gestorben im Alter von 80 Jahren",
                source_url="https://example.com/de",
                language="de",
                dedup_status="unique",
                relevance_score=70.0,
            ),
            _mk_entry(
                entry_id="es-obit",
                title="Muere Dolly Parton, la reina del country",
                source_url="https://example.com/es",
                language="es",
                dedup_status="unique",
                relevance_score=60.0,
            ),
        ]
        assert len(_extract_proper_nouns(entries[0]["title"])) == 1
        assert len(_extract_proper_nouns(entries[1]["title"])) == 1
        assert not (
            0.5 <= self._char_ratio(entries[0]["title"], entries[1]["title"]) < 0.85
        )
        result = _converge_near_duplicates(entries)
        assert len(result) == 1
        assert result[0]["entry_id"] == "de-obit"

    def test_obituary_not_merged_with_death_word_free_tribute(self) -> None:
        """(b) A death-variant + a feature/tribute title sharing the name do
        NOT merge when the tribute carries no event word."""
        entries = [
            _mk_entry(
                entry_id="obit",
                title=self._OBIT_TRUMP,
                source_url="https://www.lefigaro.fr/musique/obit",
                language="fr",
                dedup_status="unique",
                relevance_score=90.0,
            ),
            _mk_entry(
                entry_id="feature",
                title=self._TRIBUTE_FAUX,
                source_url="https://www.lefigaro.fr/industrie-mode/feature",
                language="fr",
                dedup_status="unique",
                relevance_score=50.0,
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 2

    def test_obituary_not_merged_with_songlist_tribute(self) -> None:
        """A song-list tribute whose title contains a bare appositional
        \"morte à 80 ans\" must NOT collapse into the obituary cluster — the
        event word \"morte\" there is not a canonical headline/predicate form
        (no \"mort de\"/\"est morte\"/\"à l'âge\")."""
        entries = [
            _mk_entry(
                entry_id="obit",
                title=self._OBIT_TRUMP,
                source_url="https://www.lefigaro.fr/musique/obit",
                language="fr",
                dedup_status="unique",
                relevance_score=95.0,
            ),
            _mk_entry(
                entry_id="songs",
                title=self._TRIBUTE_SONGS,
                source_url="https://www.lefigaro.fr/musique/songs",
                language="fr",
                dedup_status="unique",
                relevance_score=90.0,
            ),
        ]
        result = _converge_near_duplicates(entries)
        assert len(result) == 2


# 18 same-event Dolly Parton entries across 8 domains/languages — the exact
# shape of the backup #69 flood.  All share the "Dolly Parton" proper noun,
# all within the ±3-day window, all distinct source URLs.  Only the
# highest-relevance fr entry is "unique"; the rest are already flagged
# "duplicate" (G2 could catch same-language dups, just not cross-language).
_DOLLY_18: list[dict[str, object]] = [
    _mk_entry(
        entry_id="fr-rep",
        title="Dolly Parton est décédée à 80 ans",
        source_url="https://www.france24.com/fr/dolly-rep",
        language="fr",
        relevance_score=95.0,
        dedup_status="unique",
        summary="La chanteuse country s'est éteinte.",
        collected_at="2026-08-25T06:00:00",
    ),
    _mk_entry(
        entry_id="fr-2",
        title="Mort de la star américaine Dolly Parton",
        source_url="https://www.lefigaro.fr/dolly-2",
        language="fr",
        relevance_score=60.0,
        dedup_status="duplicate",
        summary="La musicienne nous a quittés.",
        collected_at="2026-08-25T08:00:00",
    ),
    _mk_entry(
        entry_id="fr-3",
        title="La chanteuse Dolly Parton nous a quittés",
        source_url="https://www.lefigaro.fr/dolly-3",
        language="fr",
        relevance_score=55.0,
        dedup_status="duplicate",
        summary="Hommage à la reine de la country.",
        collected_at="2026-08-25T09:00:00",
    ),
    _mk_entry(
        entry_id="fr-4",
        title="Adieu à Dolly Parton, icône de la country",
        source_url="https://www.lefigaro.fr/dolly-4",
        language="fr",
        relevance_score=50.0,
        dedup_status="duplicate",
        summary="La star s'est éteinte à 80 ans.",
        collected_at="2026-08-25T10:00:00",
    ),
    _mk_entry(
        entry_id="fr-5",
        title="Dolly Parton s'éteint à 80 ans",
        source_url="https://www.france24.com/fr/dolly-5",
        language="fr",
        relevance_score=45.0,
        dedup_status="duplicate",
        summary="La chanteuse est morte.",
        collected_at="2026-08-25T11:00:00",
    ),
    _mk_entry(
        entry_id="fr-6",
        title="Réactions après la mort de Dolly Parton",
        source_url="https://www.lefigaro.fr/dolly-6",
        language="fr",
        relevance_score=40.0,
        dedup_status="duplicate",
        summary="L'émotion est immense.",
        collected_at="2026-08-25T12:00:00",
    ),
    _mk_entry(
        entry_id="en-1",
        title="Dolly Parton has died at age 80",
        source_url="https://www.npr.org/dolly-en1",
        language="en",
        relevance_score=60.0,
        dedup_status="duplicate",
        summary="The country icon has passed away.",
        collected_at="2026-08-25T13:00:00",
    ),
    _mk_entry(
        entry_id="en-2",
        title="Country icon Dolly Parton dead",
        source_url="https://www.billboard.com/dolly-en2",
        language="en",
        relevance_score=55.0,
        dedup_status="duplicate",
        summary="The singer has died.",
        collected_at="2026-08-25T14:00:00",
    ),
    _mk_entry(
        entry_id="en-3",
        title="Dolly Parton passes away aged 80",
        source_url="https://pitchfork.com/dolly-en3",
        language="en",
        relevance_score=50.0,
        dedup_status="duplicate",
        summary="An era ends for country music.",
        collected_at="2026-08-25T15:00:00",
    ),
    _mk_entry(
        entry_id="es-1",
        title="Muere Dolly Parton, la reina del country",
        source_url="https://www.20minutos.es/dolly-es1",
        language="es",
        relevance_score=55.0,
        dedup_status="duplicate",
        summary="La cantante ha fallecido.",
        collected_at="2026-08-25T16:00:00",
    ),
    _mk_entry(
        entry_id="es-2",
        title="Dolly Parton fallece a los 80 años",
        source_url="https://www.20minutos.es/dolly-es2",
        language="es",
        relevance_score=50.0,
        dedup_status="duplicate",
        summary="Adiós a una leyenda.",
        collected_at="2026-08-25T17:00:00",
    ),
    _mk_entry(
        entry_id="pt-1",
        title="Morreu Dolly Parton, ícone da música",
        source_url="https://observador.pt/dolly-pt1",
        language="pt",
        relevance_score=55.0,
        dedup_status="duplicate",
        summary="A cantora tinha 80 anos.",
        collected_at="2026-08-25T18:00:00",
    ),
    _mk_entry(
        entry_id="pt-2",
        title="Dolly Parton morre aos 80 anos",
        source_url="https://observador.pt/dolly-pt2",
        language="pt",
        relevance_score=50.0,
        dedup_status="duplicate",
        summary="Morreu a lenda da country.",
        collected_at="2026-08-25T19:00:00",
    ),
    _mk_entry(
        entry_id="b2b-1",
        title="Dolly Parton brand licensing deals surge",
        source_url="https://news.ycombinator.com/dolly-b2b1",
        language="en",
        relevance_score=45.0,
        dedup_status="duplicate",
        summary="Licensing interest is rising.",
        collected_at="2026-08-25T20:00:00",
    ),
    _mk_entry(
        entry_id="b2b-2",
        title="Dolly Parton estate merchandise demand jumps",
        source_url="https://news.ycombinator.com/dolly-b2b2",
        language="en",
        relevance_score=40.0,
        dedup_status="duplicate",
        summary="Merchandise sales are climbing.",
        collected_at="2026-08-25T21:00:00",
    ),
    _mk_entry(
        entry_id="gaming-1",
        title="Dolly Parton tribute concert announced",
        source_url="https://www.ign.com/dolly-g1",
        language="en",
        relevance_score=45.0,
        dedup_status="duplicate",
        summary="Fans are paying tribute.",
        collected_at="2026-08-25T22:00:00",
    ),
    _mk_entry(
        entry_id="gaming-2",
        title="Dolly Parton tie-in game announced",
        source_url="https://www.ign.com/dolly-g2",
        language="en",
        relevance_score=40.0,
        dedup_status="duplicate",
        summary="A new game is in the works.",
        collected_at="2026-08-25T23:00:00",
    ),
    _mk_entry(
        entry_id="edu-1",
        title="Dolly Parton biography for learners",
        source_url="https://www.openculture.com/dolly-edu1",
        language="en",
        relevance_score=45.0,
        dedup_status="duplicate",
        summary="A profile of the singer.",
        collected_at="2026-08-26T00:00:00",
    ),
]


class TestDigestConvergence:
    @patch("autoinfo.output.KBStore")
    @patch("autoinfo.output._call_llm_for_digest")
    def test_generate_digest_converges_dolly_duplicates(
        self, mock_llm: MagicMock, mock_kb: MagicMock
    ) -> None:
        """A Dolly-Parton-flooded KB renders a digest with ≤2 references."""
        mock_llm.return_value = {
            "executive_summary": "Weekly summary of the news.",
            "key_findings": [{"topic": "Culture", "detail": "Readings"}],
            "trends": ["Mourning"],
            "recommendations": ["Continue reading."],
        }
        mock_store = MagicMock()
        mock_store.list_entries.return_value = list(_DOLLY_18)
        mock_kb.return_value = mock_store

        from autoinfo.output import generate_digest

        body = generate_digest(
            domain="french-learning", period="weekly", format="markdown"
        )
        assert isinstance(body, str)
        assert body.count("Dolly") <= 2
