"""Deduplication checker for the collection pipeline.

Provides the :class:`DedupChecker` which detects duplicate items by URL
exact match, PMID/DOI identifiers, and fuzzy title matching.
"""

from __future__ import annotations

import difflib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from autoinfo.models import Item, KBEntry
from autoinfo.textutil import (
    _NEAR_DUP_WINDOW_DAYS,
    _extract_proper_nouns,
    _has_death_event_word,
)

logger = logging.getLogger(__name__)


class DedupChecker:
    """Detect duplicate items using URL + PMID/DOI + fuzzy-title + event match.

    Priority:
        1. URL exact match (comparing ``item.source_url``)
        2. PMID/DOI match (if the item has raw_data with these identifiers)
        3. Fuzzy title match (SequenceMatcher, threshold 0.85)
        4. Cross-domain event match (shared proper noun + death-word signal)

    Usage::

        checker = DedupChecker(knowledge_dir="knowledge")
        existing = checker.load_all_domains_entries()
        verdict = checker.check(my_item, existing)
    """

    def __init__(self, knowledge_dir: str | Path = "knowledge") -> None:
        """Initialise checker.

        Args:
            knowledge_dir: Root path of the knowledge base directory
                (contains ``<domain>/01-Raw/`` sub-trees).
        """
        self.knowledge_dir = Path(knowledge_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_existing(self, domain: str) -> list[KBEntry]:
        """Scan ``knowledge/<domain>/01-Raw/`` for existing KB entries.

        Reads Markdown files with YAML frontmatter and returns them as
        :class:`KBEntry` instances.  Returns an empty list when the
        directory does not exist or contains no entries.

        Args:
            domain: Domain name (e.g. ``"medical-research"``).

        Returns:
            List of existing KB entries found on disk.
        """
        raw_dir = self.knowledge_dir / domain / "01-Raw"
        if not raw_dir.is_dir():
            return []

        entries: list[KBEntry] = []
        for md_file in raw_dir.rglob("*.md"):
            try:
                entry = self._parse_kb_file(md_file)
                if entry is not None:
                    entries.append(entry)
            except Exception as exc:
                logger.warning("Skipping unparseable KB file %s: %s", md_file, exc)
                continue

        return entries

    def load_all_domains_entries(self) -> list[KBEntry]:
        """Scan ``knowledge/<every-domain>/01-Raw/`` for existing KB entries.

        Unlike :meth:`load_existing` — which only inspects one domain — this
        walks every domain sub-directory under ``knowledge/`` and returns all
        01-Raw entries as a single list.  The collection layer uses it so the
        SAME event collected into a SECOND domain is skipped: dedup means
        "don't store the same event in a second domain" (backup issue #109).
        """
        if not self.knowledge_dir.is_dir():
            return []

        entries: list[KBEntry] = []
        for domain_dir in self.knowledge_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            entries.extend(self.load_existing(domain_dir.name))
        return entries

    def check(
        self,
        item: Item,
        existing_entries: list[KBEntry],
    ) -> dict[str, Any]:
        """Check *item* against a list of existing KB entries for duplicates.

        Matches are attempted in order:
            1. Exact URL match
            2. PMID match (from ``item.raw_data``)
            3. DOI match (from ``item.raw_data``)
            4. Fuzzy title match (SequenceMatcher, threshold 0.85)
            5. Cross-domain event match (shared proper noun + death-word
               co-occurrence within the window)

        Args:
            item: The freshly collected item to check.
            existing_entries: Previously stored KB entries to compare against.
                Pass :meth:`load_all_domains_entries` output so the SECOND
                domain's copy of a shared event is also skipped.

        Returns:
            A dict with the verdict::

                {
                    "is_duplicate": bool,
                    "matched_by": str,  # url|pmid|doi|fuzzy_title|cross_domain_event|""
                    "existing_id": str,     # matched entry ID, or ""
                }
        """
        # -- 1. URL exact match -----------------------------------------
        if item.source_url:
            for entry in existing_entries:
                if entry.source_url and entry.source_url == item.source_url:
                    return {
                        "is_duplicate": True,
                        "matched_by": "url",
                        "existing_id": entry.entry_id,
                    }

        # -- 2. PMID / DOI match ----------------------------------------
        item_pmid = item.raw_data.get("pmid", "")
        item_doi = item.raw_data.get("doi", "")

        for entry in existing_entries:
            entry_pmid = entry.custom_fields.get("pmid", "")
            entry_doi = entry.custom_fields.get("doi", "")

            if item_pmid and entry_pmid and item_pmid == entry_pmid:
                return {
                    "is_duplicate": True,
                    "matched_by": "pmid",
                    "existing_id": entry.entry_id,
                }

            if item_doi and entry_doi and item_doi == entry_doi:
                return {
                    "is_duplicate": True,
                    "matched_by": "doi",
                    "existing_id": entry.entry_id,
                }

        # -- 3. Fuzzy title match ----------------------------------------
        item_title = (item.title or "").strip().lower()
        if item_title:
            for entry in existing_entries:
                entry_title = (entry.title or "").strip().lower()
                if entry_title:
                    similarity = difflib.SequenceMatcher(
                        None, item_title, entry_title
                    ).ratio()
                    if similarity >= 0.85:
                        logger.info(
                            "DedupChecker: duplicate detected (fuzzy title: %.2f) - "
                            "new='%s' matched existing='%s' (%s)",
                            similarity,
                            item_title,
                            entry_title,
                            entry.entry_id,
                        )
                        return {
                            "is_duplicate": True,
                            "matched_by": "fuzzy_title",
                            "existing_id": entry.entry_id,
                        }

        # -- 4. Cross-domain event match ------------------------------------
        # Same news EVENT collected across domains: different URLs + different
        # languages rewrite the headline ("Mort de Dolly Parton" vs "Muere
        # Dolly Parton"), so char-level fuzzy-title and URL means never match.
        # A shared proper-noun signature + a death/obituary event word in both
        # titles within a short window identifies the same event (backup #109).
        item_title_raw = (item.title or "").strip()
        if item_title_raw:
            item_nouns = set(_extract_proper_nouns(item_title_raw))
            if item_nouns:
                for entry in existing_entries:
                    if self._cross_domain_event_match(
                        item_title_raw,
                        item_nouns,
                        item.collected_at,
                        item.language,
                        entry,
                    ):
                        return {
                            "is_duplicate": True,
                            "matched_by": "cross_domain_event",
                            "existing_id": entry.entry_id,
                        }

        return {
            "is_duplicate": False,
            "matched_by": "",
            "existing_id": "",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cross_domain_event_match(
        item_title: str,
        item_nouns: set[str],
        item_collected_at: str,
        item_language: str | None,
        entry: KBEntry,
    ) -> bool:
        """Return True when *item* is the same death/obituary *entry* across
        domains/languages.

        Criteria (all required):
            1. The item and entry share a proper-noun signature (≥2-word
               capitalized phrase, incl. phrase-subsumption so "Muere Dolly
               Parton" and "Dolly Parton" match).
            2. Their ``collected_at`` timestamps are within
               :data:`_NEAR_DUP_WINDOW_DAYS` days (unparseable dates skip the
               window clause — conservative; the nouns+event-word signals
               alone are allowed to merge).
            3. BOTH titles carry a canonical death/obituary event word in
               their own language (``_DEATH_EVENT_WORDS`` from
               :mod:`autoinfo.textutil`), each co-occurring with the shared
               noun in its own title.
        """
        entry_title = (entry.title or "").strip()
        if not entry_title:
            return False

        entry_nouns = set(_extract_proper_nouns(entry_title))
        shared = {n for n in item_nouns if n in entry_nouns}
        # Phrase subsumption: "Muere Dolly Parton" contains "Dolly Parton"
        # as a whole-word substring of a longer signature — keep the shorter
        # (contained) phrase, which is what both titles then co-occur with.
        for a in item_nouns:
            for b in entry_nouns:
                if a in b:
                    shared.add(a)
                if b in a:
                    shared.add(b)
        if not shared:
            return False

        # Event + noun co-occur in each title's own language.
        if not any(noun in item_title for noun in shared):
            return False
        if not any(noun in entry_title for noun in shared):
            return False
        if not _has_death_event_word(item_title, item_language):
            return False
        if not _has_death_event_word(entry_title, entry.language):
            return False

        return DedupChecker._within_window(item_collected_at, entry.collected_at)

    @staticmethod
    def _within_window(a_collected_at: str, b_collected_at: str) -> bool:
        """True when two collection timestamps are within the near-dup window.

        Unparseable/missing timestamps skip the window clause (conservative —
        allow a merge on the noun+event-word signals alone).
        """
        a_dt = DedupChecker._parse_dt(a_collected_at)
        b_dt = DedupChecker._parse_dt(b_collected_at)
        if a_dt is None or b_dt is None:
            return True
        return abs((a_dt - b_dt).days) <= _NEAR_DUP_WINDOW_DAYS

    @staticmethod
    def _parse_dt(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_kb_file(path: Path) -> KBEntry | None:
        """Parse a Markdown KB file with YAML frontmatter into a KBEntry.

        The file is expected to have the format::

            ---
            title: "..."
            entry_id: "..."
            ...
            ---
            <body>

        Returns ``None`` if the file lacks valid frontmatter.
        """
        content = path.read_text(encoding="utf-8")

        # -- Extract YAML frontmatter between --- markers ----------------
        if not content.startswith("---"):
            return None

        # Find the closing ---
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return None

        yaml_block = content[3:end_idx].strip()
        if not yaml_block:
            return None

        try:
            data: dict[str, Any] = yaml.safe_load(yaml_block) or {}
        except yaml.YAMLError:
            logger.warning("Invalid YAML frontmatter in %s", path)
            return None

        entry = KBEntry.from_dict(data)
        entry.file_path = str(path)
        return entry
