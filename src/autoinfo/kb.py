"""Knowledge base storage — Markdown files + SQLite index + FTS5 full-text search
+ entity extraction + knowledge graph relations.

Provides the ``KBStore`` (high-level file + index orchestration) and
``SQLiteIndex`` (lightweight metadata index) classes.

File layout::

    knowledge/<domain>/01-Raw/<topic>/<YYYY-MM-DD>-<slug>.md

Each file carries YAML frontmatter with all metadata fields needed for
fast filtering / browsing, and a plain-text body with the original
collected content plus any LLM-extracted summary / key points.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import subprocess
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from autoinfo.config import Config
from autoinfo.models import ExtractionResult, Item, KBEntry
from autoinfo.promotion import RejectionReason, check_promotion_admission
from autoinfo.quality import QualityResult
from autoinfo.schema import check_schema

logger = logging.getLogger(__name__)

from enum import Enum  # noqa: E402


class RelationType(str, Enum):
    """Types of relationships between KB entries."""
    RELATED = "related"
    RELATED_TO = "related_to"
    PARENT_OF = "parent_of"
    CHILD_OF = "child_of"
    REFERENCES = "references"
    REFERENCED_BY = "referenced_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    SIMILAR_TO = "similar_to"
    DUPLICATE_OF = "duplicate_of"
    VERSION_OF = "version_of"


RELATION_TYPES = {rt.value for rt in RelationType}

# ---------------------------------------------------------------------------
# Search tier soft-boost
# ---------------------------------------------------------------------------

# Soft post-multiplier applied to the combined score in
# ``KBStore.search_knowledge_base`` so curated 03-Wiki entries outrank
# equal-scoring Draft/Raw entries.  It is applied only after the base
# score (relevance * 0.8 + freshness * 0.2) is computed and never
# overrides stale-content demotion, which stays the primary sort key.
TIER_SCORE_BOOST: dict[str, float] = {
    "03-Wiki": 1.05,
    "02-Draft": 1.0,
    "01-Raw": 1.0,
}


class PromotionRejected(Exception):  # noqa: N818 — mandated name (plan T2/T5/T9 use PromotionRejected), not a generic Error
    """Raised when a 02-Draft entry fails the promotion admission gate.

    The draft is **not** moved and not deleted — it stays in 02-Draft and a
    ``_failed/<domain>/<entry_id>.md`` marker is written alongside it.
    ``reasons`` carries one typed :class:`RejectionReason` code per failed
    admission component so callers can route/handle rejections without
    parsing prose.
    """

    def __init__(self, reasons: list[RejectionReason]) -> None:
        self.reasons = reasons
        super().__init__(
            "Promotion rejected: " + ", ".join(str(r) for r in reasons)
        )


# ---------------------------------------------------------------------------
# Director whitelist — advisory actor gating for the curation backdoor
# ---------------------------------------------------------------------------

_DIRECTOR_ACTORS_ENV = "AUTOINFO_DIRECTOR_ACTORS"


def _director_actors() -> frozenset[str]:
    """Parse the ``AUTOINFO_DIRECTOR_ACTORS`` whitelist (default ``director``).

    The env var holds a comma-separated list of actor names; entries are
    stripped and empty entries are dropped.  Read on every call so tests and
    operators can change the whitelist without a reload.
    """
    raw = os.environ.get(_DIRECTOR_ACTORS_ENV, "director")
    return frozenset(a.strip() for a in raw.split(",") if a.strip())


def is_director(actor: str | None) -> bool:
    """Return whether *actor* is whitelisted in ``AUTOINFO_DIRECTOR_ACTORS``.

    ``None`` (or an empty string) — a caller that did not declare an actor —
    resolves to the default ``"director"`` actor, preserving pre-backdoor
    behavior for internal callers while every MCP surface passes its actor
    explicitly.  Advisory by design: real auth is future scope (v2).
    """
    return (actor or "director").strip() in _director_actors()


def _ensure_wiki_delete_allowed(
    tier: str,
    *,
    actor: str | None,
    entry_id: str,
) -> None:
    """Refuse deleting a 03-Wiki entry unless *actor* is a director.

    03-Wiki is append-only: only a whitelisted director may soft-delete or
    purge curated entries.  01-Raw / 02-Draft are unaffected.
    """
    if tier == "03-Wiki" and not is_director(actor):
        raise DirectorOnlyError(
            actor=actor or "director",
            entry_id=entry_id,
            operation="delete",
        )


class DirectorOnlyError(Exception):  # noqa: N818 — mandated name (plan T5), not a generic Error
    """Raised when a non-director actor attempts a director-only KB operation.

    Director-only operations — Wiki demotion (``demote_entry``), forced
    promotion (``force_promote_kb_draft``), and deletion of 03-Wiki entries —
    require an actor whitelisted in the ``AUTOINFO_DIRECTOR_ACTORS``
    environment variable (default ``director``).  The MCP layer maps this to
    the ``DIRECTOR_ONLY`` error envelope code.
    """

    def __init__(self, *, actor: str, entry_id: str, operation: str) -> None:
        self.actor = actor
        self.entry_id = entry_id
        self.operation = operation
        super().__init__(
            f"actor '{actor}' not whitelisted in AUTOINFO_DIRECTOR_ACTORS: "
            f"{operation} on '{entry_id}' requires a director"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str, max_len: int = 255) -> str:
    """Turn *text* into a lowercase, alphanumeric-plus-hyphens slug.

    Examples
    --------
    >>> _slugify("Improved IVF outcomes: a RCT")
    'improved-ivf-outcomes-a-rct'
    """
    slug = text.lower()
    # Replace any run of non-alphanumeric (except hyphens) with a single hyphen
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len].rstrip("-")


def _decode_html_entities(text: str) -> str:
    """Decode residual HTML entities in *text* (issue #55).

    Collectors leave raw entities in titles / summaries / content — ``&#039;``,
    ``&apos;``, ``&quot;``, ``&#8217;``, ``&amp;``, ``&lt;``, ``&gt;`` … (hindi
    140x ``&#039;``, online-video ``&#8217;``, tech-ai ``&amp;``).  Applied at
    the STORAGE layer (``store_entry``) so every downstream render surface
    (digest / report / column / agent / …) reads clean text instead of each
    renderer re-decoding independently (and inconsistently).

    ``html.unescape`` runs iteratively (bounded) so double-encoded entities
    (``&amp;lt;`` -> ``&lt;`` -> ``<``) collapse too; decoding ``&amp;`` falls
    out LAST by construction because each pass only widens a literal ``&``
    from an already-decoded ``&amp;``.  Idempotent — safe to run twice.
    """
    if not text:
        return text
    cleaned = text
    for _ in range(3):
        decoded = html.unescape(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded
    return cleaned


def calculate_freshness_score(entry: dict[str, Any], ttl_days: int = 90) -> float:
    """Calculate freshness score (0.0 to 1.0) based on age and TTL."""
    created_at = entry.get("collected_at") or entry.get("created_at") or ""
    if not created_at:
        return 1.0
    try:
        from datetime import datetime, timezone

        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 1.0
    age_days = (datetime.now(timezone.utc) - created).days
    if age_days >= ttl_days:
        return 0.0
    freshness = 1.0 - (age_days / ttl_days)
    return max(0.0, min(1.0, freshness))


def _parse_date(s: str) -> date:
    """Extract a ``date`` from an ISO-format datetime string or date string."""
    try:
        return datetime.fromisoformat(s).date()
    except (ValueError, TypeError):
        pass
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    return date.today()


# ---------------------------------------------------------------------------
# FTS5 query escaping
# ---------------------------------------------------------------------------

_FTS5_SPECIAL = re.compile(r'[\^"():+\-!~{}\[\]\\\\*?]')
_FTS5_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR"})


_CUSTOM_FIELD_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
)


def _validate_custom_field_path(path: str) -> None:
    """Validate a ``custom_fields`` dot-path used inside ``json_extract``.

    Only identifier characters and single dots are allowed, so a caller
    can never inject JSON-path syntax (``$``, brackets, quotes) into the
    ``$.<path>`` expression built by :meth:`SQLiteIndex.search_fts5`.
    """
    if not _CUSTOM_FIELD_PATH_RE.match(path):
        raise ValueError(
            f"filter_custom_fields path {path!r} is not a valid dot-path "
            "(letters, digits, underscores and single dots only)"
        )


def _escape_fts5_query(query: str) -> str:
    """Escape a user query string for safe use with FTS5 MATCH.

    Removes FTS5 special characters and lowercases FTS5 keyword tokens
    so they are treated as regular terms rather than operators.
    Returns ``''`` if the query becomes empty after cleaning.
    """
    if not query or not query.strip():
        return ""
    cleaned = query.replace('"', " ")
    cleaned = _FTS5_SPECIAL.sub(" ", cleaned)
    tokens = cleaned.split()
    safe: list[str] = []
    for tok in tokens:
        safe.append(tok.lower() if tok.upper() in _FTS5_KEYWORDS else tok)
    return " ".join(safe) if safe else ""


# Common English stopwords dropped when falling back to OR / LIKE search.
# Kept deliberately small — only words unlikely to carry search intent.
_FTS5_STOPWORDS = frozenset(
    {
        "a", "an", "the",
        "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
        "are", "is", "was", "were", "be", "been", "being", "am",
        "do", "does", "did", "done", "doing", "have", "has", "had",
        "can", "could", "would", "should", "will", "shall", "may", "might", "must",
        "and", "or", "not", "of", "to", "for", "in", "on", "at", "with", "by",
        "from", "as", "into", "over", "under", "about", "than", "then", "so",
        "if", "but", "up", "down", "out", "off", "it", "its", "this", "that",
        "these", "those", "there", "here", "we", "you", "they", "he", "she",
        "i", "me", "my", "our", "us", "their", "them", "your", "any", "all",
        "each", "every", "some", "such", "only", "same", "very", "just",
        "also", "other", "others", "more", "most", "no", "yes", "etc",
        # Frequent in natural-language questions about content
        "discuss", "discusses", "discussed", "discussing", "mention",
        "mentions", "mentioned", "technology", "technologies", "article",
        "articles", "information", "about", "main", "topic", "topics",
    }
)


def _split_search_terms(query: str) -> list[str]:
    """Split a query into individual search terms.

    Mirrors the tokenisation of :func:`_escape_fts5_query`: FTS5 special
    characters are replaced by whitespace and the remaining words are
    returned in order.
    """
    if not query or not query.strip():
        return []
    cleaned = query.replace('"', " ")
    cleaned = _FTS5_SPECIAL.sub(" ", cleaned)
    return cleaned.split()


def _meaningful_search_terms(query: str) -> list[str]:
    """Return the non-stopword terms of *query*, preserving order.

    Used to build OR-semantics and LIKE fallback queries for long
    natural-language questions that fail FTS5's default AND semantics.
    """
    return [
        term for term in _split_search_terms(query)
        if term.lower() not in _FTS5_STOPWORDS
    ]


# ---------------------------------------------------------------------------
# SQLite Index
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SQLite busy timeout (issue #295)
# ---------------------------------------------------------------------------

_DEFAULT_DB_BUSY_TIMEOUT_MS = 30000
_DB_BUSY_TIMEOUT_ENV = "AUTOINFO_DB_BUSY_TIMEOUT_MS"


def _db_busy_timeout_ms() -> int:
    """Return the SQLite ``busy_timeout`` (ms) for KB connections.

    Parallel ``autoinfo process`` workers write to the same SQLite DB; under
    external-writer contention a write can raise ``OperationalError: database
    is locked``.  A generous busy timeout makes a connection wait for the
    lock instead of failing immediately.  Configurable via
    ``AUTOINFO_DB_BUSY_TIMEOUT_MS`` (default 30000); unparsable values fall
    back to the default.
    """
    raw = os.environ.get(_DB_BUSY_TIMEOUT_ENV)
    if raw is None:
        return _DEFAULT_DB_BUSY_TIMEOUT_MS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_DB_BUSY_TIMEOUT_MS


class SQLiteIndex:
    """Lightweight SQLite metadata index for KB entries.

    Stores a subset of entry metadata to support fast listing, filtering,
    and ordering without reading Markdown files.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open a connection (with row factory for dict-like rows)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA busy_timeout={_db_busy_timeout_ms()}")
        return conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    entry_id        TEXT PRIMARY KEY,
                    title           TEXT,
                    domain          TEXT,
                    tier            TEXT DEFAULT '01-Raw',
                    source_url      TEXT,
                    source_type     TEXT,
                    source_platform TEXT,
                    collected_at    TEXT,
                    summary         TEXT,
                    quality_tier    INTEGER,
                    relevance_score REAL,
                    dedup_status    TEXT,
                    file_path       TEXT,
                    tags            TEXT,
                    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_domain
                    ON entries(domain);

                CREATE INDEX IF NOT EXISTS idx_tier
                    ON entries(tier);

                CREATE INDEX IF NOT EXISTS idx_collected_at
                    ON entries(collected_at);

                CREATE INDEX IF NOT EXISTS idx_domain_tier
                    ON entries(domain, tier);

                CREATE INDEX IF NOT EXISTS idx_domain_collected
                    ON entries(domain, collected_at DESC);

                -- Knowledge graph entity tables
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id   TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    type        TEXT NOT NULL,
                    domain      TEXT NOT NULL,
                    entry_id    TEXT NOT NULL,
                    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_entities_name
                    ON entities(name);
                CREATE INDEX IF NOT EXISTS idx_entities_type
                    ON entities(type);
                CREATE INDEX IF NOT EXISTS idx_entities_domain
                    ON entities(domain);
                CREATE INDEX IF NOT EXISTS idx_entities_entry
                    ON entities(entry_id);

                CREATE TABLE IF NOT EXISTS kg_relations (
                    relation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_a      TEXT NOT NULL,
                    entity_b      TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'related_to',
                    strength      REAL DEFAULT 1.0,
                    entries_shared TEXT,
                    domain        TEXT NOT NULL,
                    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entity_a, entity_b, relation_type)
                );
                CREATE INDEX IF NOT EXISTS idx_kg_relations_a
                    ON kg_relations(entity_a);
                CREATE INDEX IF NOT EXISTS idx_kg_relations_b
                    ON kg_relations(entity_b);
                CREATE INDEX IF NOT EXISTS idx_kg_relations_domain
                    ON kg_relations(domain);
            """)
            # Migration: add tier column if table existed before this change
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN tier TEXT DEFAULT '01-Raw'")
            except Exception:
                pass
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tier ON entries(tier)")
            except Exception:
                pass
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_domain_tier ON entries(domain, tier)")
            except Exception:
                pass
            # Migration: add importance column (v0.1.1+)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN importance INTEGER DEFAULT 3")
            except Exception:
                pass
            # Migration: add custom_fields JSON column (v1.1+)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN custom_fields TEXT DEFAULT '{}'")
            except Exception:
                pass
            # Migration: add language column (v1.1+)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN language TEXT DEFAULT ''")
            except Exception:
                pass
            # Migration: add content_type column (v1.1+)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN content_type TEXT DEFAULT ''")
            except Exception:
                pass
            # Migration: add user_id column (v1.2 — multi-user foundation)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN user_id TEXT DEFAULT ''")
            except Exception:
                pass
            # Migration: add cefr column (v1.2 — CEFR badge for dashboard)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN cefr TEXT DEFAULT ''")
            except Exception:
                pass
            # Migration: add deleted / deleted_at columns (v1.6 — soft-delete)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN deleted INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN deleted_at TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN version INTEGER DEFAULT 1")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN previous_version INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN supersedes TEXT DEFAULT ''")
            except Exception:
                pass
            # Migration: add source_score column (E9 — deterministic source credibility)
            try:
                conn.execute("ALTER TABLE entries ADD COLUMN source_score REAL DEFAULT 0.0")
            except Exception:
                pass

            conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts5
                   USING fts5(
                       title, summary, content, domain, tags,
                       tokenize='unicode61'
                   )"""
            )

            # --- relations table for item linking --------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relations (
                    relation_id   TEXT PRIMARY KEY,
                    item_a_id     TEXT NOT NULL,
                    item_b_id     TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'related',
                    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata      TEXT DEFAULT '{}',
                    FOREIGN KEY (item_a_id) REFERENCES entries(entry_id),
                    FOREIGN KEY (item_b_id) REFERENCES entries(entry_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relations_a
                    ON relations(item_a_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relations_b
                    ON relations(item_b_id)
            """)
            try:
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_pair
                        ON relations(item_a_id, item_b_id, relation_type)
                """)
            except Exception:
                pass

            # --- entry_versions table for versioning -----------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entry_versions (
                    version_id    TEXT PRIMARY KEY,
                    entry_id      TEXT NOT NULL,
                    version_num   INTEGER NOT NULL,
                    file_path     TEXT NOT NULL,
                    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                    comment       TEXT DEFAULT '',
                    git_sha       TEXT DEFAULT '',
                    FOREIGN KEY (entry_id) REFERENCES entries(entry_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entry_versions_entry
                    ON entry_versions(entry_id)
            """)
            # Migration: add git_sha column for existing databases
            try:
                conn.execute(
                    "ALTER TABLE entry_versions ADD COLUMN git_sha TEXT DEFAULT ''"
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def index_entry(self, entry: KBEntry) -> None:
        """Insert or replace *entry* in the SQLite index."""
        # Build custom_fields JSON from KBEntry expanded fields
        custom_fields: dict[str, Any] = {}
        custom_fields["author"] = entry.author
        custom_fields["source_ids"] = entry.source_ids
        custom_fields["status"] = entry.status
        custom_fields["related_concepts"] = entry.related_concepts
        custom_fields["linked_entries"] = entry.linked_entries
        # Merge any existing custom_fields from the entry
        if entry.custom_fields:
            custom_fields.update(entry.custom_fields)

        cefr_level = str(custom_fields.get("cefr", "")) if custom_fields else ""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO entries
                    (entry_id, title, domain, tier, source_url, source_type,
                     source_platform, collected_at, summary, quality_tier,
                     relevance_score, dedup_status, source_score, file_path, tags,
                     custom_fields, language, user_id, cefr,
                     version, previous_version, supersedes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.title,
                    entry.domain,
                    entry.tier,
                    entry.source_url,
                    entry.source_type,
                    entry.source_platform,
                    entry.collected_at,
                    entry.summary,
                    entry.quality_tier,
                    entry.relevance_score,
                    entry.dedup_status,
                    entry.source_score,
                    entry.file_path,
                    json.dumps(entry.tags, ensure_ascii=False),
                    json.dumps(custom_fields, ensure_ascii=False),
                    entry.language,
                    entry.user_id,
                    cefr_level,
                    entry.version,
                    entry.previous_version,
                    entry.supersedes,
                ),
            )

    def list_entries(
        self,
        domain: str,
        tier: str | None = None,
        date_from: str | None = None,
        limit: int = 20,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entries for *domain*, newest first, with optional tier and date filter.

        Parameters
        ----------
        domain:
            Domain to filter by.
        tier:
            Optional tier filter (e.g. "01-Raw", "02-Draft").
        date_from:
            Optional ISO date string — only entries collected on or after
            this date are returned.
        limit:
            Maximum number of rows (default 20).
        offset:
            Number of rows to skip (for pagination).
        user_id:
            Optional user_id filter. When provided, only entries with
            matching user_id are returned. ``None`` means no filter.

        Returns
        -------
        list[dict]
            Each dict contains the columns from the ``entries`` table.
        """
        with self._connect() as conn:
            conditions: list[str] = ["domain = ?"]
            params: list[Any] = [domain]
            if tier is not None:
                conditions.append("tier = ?")
                params.append(tier)
            if date_from is not None:
                # Issue #182 audit-feedback (stale-content regression): a
                # plain OR on created_at pulled OLD articles into weekly
                # digests just because they were re-ingested recently (e.g.
                # legal-compliance 2019 GDPR posts created_at=2026-08-10).
                # Weekly content should reflect the CONTENT date; created_at
                # only stands in when collected_at is missing entirely.
                conditions.append(
                    "COALESCE(NULLIF(collected_at, ''), NULLIF(created_at, '')) >= ?"
                )
                params.append(date_from)
            if user_id is not None:
                conditions.append("user_id = ?")
                params.append(user_id)
            where = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM entries WHERE {where} ORDER BY collected_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_entries_by_tier(
        self,
        domain: str,
        tier: str,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entries for a specific tier in *domain*.

        Parameters
        ----------
        domain:
            Domain to filter by.
        tier:
            Tier to filter by (e.g. "01-Raw", "02-Draft").
        limit:
            Maximum number of rows (default 50).
        offset:
            Number of rows to skip (for pagination).
        user_id:
            Optional user_id filter.

        Returns
        -------
        list[dict]
            Each dict contains the columns from the ``entries`` table.
        """
        return self.list_entries(domain=domain, tier=tier, limit=limit, offset=offset, user_id=user_id)  # noqa: E501

    def count_entries_by_tier(self, domain: str, tier: str) -> int:
        """Return the number of entries in *domain* for *tier*.

        Parameters
        ----------
        domain:
            Domain to filter by.
        tier:
            Tier to count (e.g. ``"01-Raw"``, ``"02-Draft"``).

        Returns
        -------
        int
            Number of matching entries.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE domain=? AND tier=?",
                (domain, tier),
            ).fetchone()
            return row[0] if row else 0

    def list_all_entries(
        self,
        domain: str | None = None,
        tier: str | None = None,
        date_from: str | None = None,
        limit: int = 20,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entries across all domains (or a specific *domain*).

        Supports the same filters as :meth:`list_entries`, but *domain*
        is optional.  When ``None``, entries from every domain are
        returned.  Results are ordered by ``collected_at DESC``.
        """
        with self._connect() as conn:
            conditions: list[str] = []
            params: list[Any] = []
            if domain is not None:
                conditions.append("domain = ?")
                params.append(domain)
            if tier is not None:
                conditions.append("tier = ?")
                params.append(tier)
            if date_from is not None:
                # Issue #182 audit-feedback (stale-content regression): a
                # plain OR on created_at pulled OLD articles into weekly
                # digests just because they were re-ingested recently (e.g.
                # legal-compliance 2019 GDPR posts created_at=2026-08-10).
                # Weekly content should reflect the CONTENT date; created_at
                # only stands in when collected_at is missing entirely.
                conditions.append(
                    "COALESCE(NULLIF(collected_at, ''), NULLIF(created_at, '')) >= ?"
                )
                params.append(date_from)
            if user_id is not None:
                conditions.append("user_id = ?")
                params.append(user_id)
            where = " AND ".join(conditions) if conditions else "1"
            rows = conn.execute(
                f"SELECT * FROM entries WHERE {where} ORDER BY collected_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Return a single entry dict by *entry_id*, or ``None``."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_entry_by_source_url(self, source_url: str) -> dict[str, Any] | None:
        """Return the most recent entry whose ``source_url`` exactly matches.

        Used by the output pipeline to link report-path agent entries
        (which hardcode ``entry_id: ""``) back to their KB entries.
        """
        if not source_url:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE source_url = ? "
                "ORDER BY collected_at DESC LIMIT 1",
                (source_url,),
            ).fetchone()
            return dict(row) if row else None

    def delete_entry(self, entry_id: str, *, actor: str | None = None) -> bool:
        """Delete an entry from the index, FTS5 table, and disk file.

        Returns ``True`` when the entry existed and was deleted,
        ``False`` when no entry with *entry_id* was found.

        Raises
        ------
        DirectorOnlyError
            If the entry lives in the 03-Wiki tier and *actor* is not
            whitelisted in ``AUTOINFO_DIRECTOR_ACTORS`` (03-Wiki is
            append-only; only a director may purge curated entries).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT file_path, rowid, tier FROM entries WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if row is None:
                return False

            _ensure_wiki_delete_allowed(row["tier"], actor=actor, entry_id=entry_id)

            file_path = row["file_path"]
            rowid = row["rowid"]

            conn.execute("DELETE FROM entries_fts5 WHERE rowid = ?", (rowid,))
            conn.execute("DELETE FROM entries WHERE entry_id = ?", (entry_id,))
            conn.execute("DELETE FROM entities WHERE entry_id = ?", (entry_id,))
            conn.execute(
                "DELETE FROM relations WHERE item_a_id = ? OR item_b_id = ?",
                (entry_id, entry_id),
            )
            conn.execute(
                "DELETE FROM kg_relations WHERE domain IN "
                "(SELECT domain FROM entries WHERE entry_id = ?)",
                (entry_id,),
            )
            conn.execute(
                "DELETE FROM entry_versions WHERE entry_id = ?",
                (entry_id,),
            )

        if file_path:
            fp = Path(file_path)
            if fp.is_file():
                fp.unlink(missing_ok=True)

        return True

    def search_by_field(
        self, field: str, value: str
    ) -> list[dict[str, Any]]:
        """Search entries where *field* LIKE ``%value%``.

        .. caution::
            This is a naive LIKE search. FTS5 full-text search will be
            added in v0.2.
        """
        allowed = {
            "title", "domain", "source_url", "source_type",
            "source_platform", "dedup_status",
        }
        if field not in allowed:
            raise ValueError(
                f"search_by_field: '{field}' is not allowed. "
                f"Allowed fields: {sorted(allowed)}"
            )

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM entries WHERE {field} LIKE ? ORDER BY collected_at DESC",
                (f"%{value}%",),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Relations (item linking)
    # ------------------------------------------------------------------

    def link_items(
        self,
        item_a_id: str,
        item_b_id: str,
        relation_type: str = "related",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a link between two KB entries.

        Idempotent: calling with the same (item_a, item_b, relation_type)
        returns the existing relation without creating a duplicate.
        """
        relation_id = f"{item_a_id}--{item_b_id}--{relation_type}"
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        # Validate that both entries exist
        entry_a = self.get_entry(item_a_id)
        if entry_a is None:
            return {
                "linked": False,
                "error": f"Entry '{item_a_id}' not found",
                "item_a_id": item_a_id,
                "item_b_id": item_b_id,
            }
        entry_b = self.get_entry(item_b_id)
        if entry_b is None:
            return {
                "linked": False,
                "error": f"Entry '{item_b_id}' not found",
                "item_a_id": item_a_id,
                "item_b_id": item_b_id,
            }

        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO relations
                   (relation_id, item_a_id, item_b_id, relation_type, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (relation_id, item_a_id, item_b_id, relation_type, meta_json),
            )
            row = conn.execute(
                "SELECT * FROM relations WHERE relation_id = ?",
                (relation_id,),
            ).fetchone()
            return dict(row) if row else {"linked": True, "relation_id": relation_id}

    def get_item_relations(
        self, item_id: str, relation_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Return all relations where *item_id* participates.

        Optionally filtered by *relation_type*.
        """
        with self._connect() as conn:
            if relation_type:
                rows = conn.execute(
                    """SELECT * FROM relations
                       WHERE (item_a_id = ? OR item_b_id = ?)
                       AND relation_type = ?
                       ORDER BY created_at DESC""",
                    (item_id, item_id, relation_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM relations
                       WHERE item_a_id = ? OR item_b_id = ?
                       ORDER BY created_at DESC""",
                    (item_id, item_id),
                ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Entry versioning
    # ------------------------------------------------------------------

    def _ensure_versioning_table(self) -> None:
        """Idempotent migration for entry_versions table."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entry_versions (
                    version_id   TEXT PRIMARY KEY,
                    entry_id     TEXT NOT NULL,
                    version_num  INTEGER NOT NULL,
                    file_path    TEXT NOT NULL,
                    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                    comment      TEXT DEFAULT '',
                    git_sha      TEXT DEFAULT '',
                    FOREIGN KEY (entry_id) REFERENCES entries(entry_id)
                )
            """)
            try:
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_entry_versions_entry
                        ON entry_versions(entry_id)
                """)
            except Exception:
                pass
            # Migration: add git_sha column for existing databases
            try:
                conn.execute(
                    "ALTER TABLE entry_versions ADD COLUMN git_sha TEXT DEFAULT ''"
                )
            except Exception:
                pass

    @staticmethod
    def _git_commit_and_get_sha(
        file_path: str,
        entry_id: str,
        version_num: int,
    ) -> str:
        """Run git add + commit for *file_path* and return the commit SHA.

        Returns empty string if git is unavailable, not in a repo, or
        if git user.name/email is not configured. Never raises.
        """
        try:
            # Check if git is available and we're in a repo
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                logger.warning("Git not available or not a git repo — skipping git commit")
                return ""

            repo_root = result.stdout.strip()

            # Check that git user is configured
            name_check = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True, text=True, timeout=5,
                cwd=repo_root,
            )
            email_check = subprocess.run(
                ["git", "config", "user.email"],
                capture_output=True, text=True, timeout=5,
                cwd=repo_root,
            )
            if not name_check.stdout.strip() or not email_check.stdout.strip():
                logger.warning(
                    "Git user.name or user.email not configured — skipping git commit"
                )
                return ""

            # git add
            add = subprocess.run(
                ["git", "add", file_path],
                capture_output=True, text=True, timeout=15,
                cwd=repo_root,
            )
            if add.returncode != 0:
                logger.warning("git add failed: %s", add.stderr.strip())
                return ""

            # git commit
            msg = f"autoinfo: version {version_num} of {entry_id}"
            commit = subprocess.run(
                ["git", "commit", "-m", msg],
                capture_output=True, text=True, timeout=15,
                cwd=repo_root,
            )
            if commit.returncode != 0:
                logger.warning("git commit failed: %s", commit.stderr.strip())
                return ""

            # Get SHA
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=repo_root,
            )
            if sha.returncode == 0:
                return sha.stdout.strip()
            return ""

        except FileNotFoundError:
            logger.warning("Git executable not found — skipping git commit")
            return ""
        except Exception as exc:
            logger.warning("Git commit skipped: %s", exc)
            return ""

    def save_entry_version(
        self,
        entry_id: str,
        file_path: str,
        comment: str = "",
    ) -> dict[str, Any]:
        """Save a version snapshot of an entry's file.

        Creates numbered .bak copies of the file at the same location.
        Prunes to max 5 versions. Returns version metadata including
        git_sha (empty string if git unavailable).
        """
        self._ensure_versioning_table()
        fp = Path(file_path)
        if not fp.is_file():
            return {"saved": False, "error": f"File not found: {file_path}"}

        # Determine the next version number
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(version_num) as m FROM entry_versions WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            next_ver = (row["m"] or 0) + 1 if row else 1

        # Create .bak file
        bak_path = fp.with_suffix(f".bak.{next_ver}")
        bak_path.write_bytes(fp.read_bytes())

        version_id = f"{entry_id}--v{next_ver}"
        git_sha = self._git_commit_and_get_sha(file_path, entry_id, next_ver)

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO entry_versions
                   (version_id, entry_id, version_num, file_path, comment, git_sha)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (version_id, entry_id, next_ver, str(bak_path), comment, git_sha),
            )

        # Prune to max 5 versions
        self._prune_versions(entry_id, max_versions=5)

        return {
            "saved": True,
            "version_id": version_id,
            "version_num": next_ver,
            "file_path": str(bak_path),
            "git_sha": git_sha,
        }

    def _prune_versions(self, entry_id: str, max_versions: int = 5) -> None:
        """Remove old versions beyond *max_versions*."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT version_id, version_num, file_path
                   FROM entry_versions WHERE entry_id = ?
                   ORDER BY version_num ASC""",
                (entry_id,),
            ).fetchall()
            if len(rows) <= max_versions:
                return
            to_remove = len(rows) - max_versions
            for row in rows[:to_remove]:
                fp = Path(row["file_path"])
                if fp.is_file():
                    fp.unlink(missing_ok=True)
                conn.execute(
                    "DELETE FROM entry_versions WHERE version_id = ?",
                    (row["version_id"],),
                )

    def get_entry_history(self, entry_id: str) -> list[dict[str, Any]]:
        """Return all saved versions for *entry_id*, newest first."""
        self._ensure_versioning_table()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM entry_versions
                   WHERE entry_id = ?
                   ORDER BY version_num DESC""",
                (entry_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def restore_entry_version(self, version_id: str) -> dict[str, Any]:
        """Restore an entry from a saved version backup.

        Copies the .bak file back over the original entry file.
        Returns the entry_id and file_path of the restored entry.
        """
        self._ensure_versioning_table()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM entry_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                return {
                    "restored": False,
                    "error": f"Version '{version_id}' not found",
                }
            version = dict(row)

        bak_path = Path(version["file_path"])
        if not bak_path.is_file():
            return {
                "restored": False,
                "error": f"Backup file not found: {version['file_path']}",
            }

        # Restore: find the original file path from the entries table
        with self._connect() as conn:
            entry_row = conn.execute(
                "SELECT file_path FROM entries WHERE entry_id = ?",
                (version["entry_id"],),
            ).fetchone()

        if entry_row is None:
            return {
                "restored": False,
                "error": f"Entry '{version['entry_id']}' not found in index",
            }

        orig_path = Path(entry_row["file_path"])
        orig_path.write_bytes(bak_path.read_bytes())

        return {
            "restored": True,
            "entry_id": version["entry_id"],
            "version_id": version_id,
            "version_num": version["version_num"],
            "file_path": str(orig_path),
            "comment": version.get("comment", ""),
        }

    def compare_versions(
        self, entry_id: str, version_a: str, version_b: str
    ) -> dict[str, Any]:
        """Compare two versions of a KB entry and return a structured diff.

        Reads the ``.bak`` files for two versions, parses their YAML
        frontmatter, and produces a field-by-field comparison.

        Parameters
        ----------
        entry_id:
            The KB entry ID whose versions to compare.
        version_a:
            Version identifier (version_id like ``entry_abc--v1`` or
            version number as a string like ``"1"``).
        version_b:
            Same format as *version_a*.

        Returns
        -------
        dict
            ``{entry_id, version_a, version_b, field_diffs, summary,
            changed_fields_count}``.  *field_diffs* is a list of
            ``{field, old_value, new_value}`` dicts.

            If a version cannot be found the result contains an ``error``
            key and empty diffs.
        """
        self._ensure_versioning_table()

        def _resolve_version_id(version_ref: str) -> str | None:
            """Resolve a version reference to a full version_id."""
            # Already a full version_id (e.g. "entry_abc--v2")
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM entry_versions WHERE version_id = ? AND entry_id = ?",
                    (version_ref, entry_id),
                ).fetchone()
                if row is not None:
                    return version_ref
                # Try as version_num
                try:
                    ver_num = int(version_ref)
                except ValueError:
                    return None
                row = conn.execute(
                    "SELECT * FROM entry_versions WHERE version_num = ? AND entry_id = ?",
                    (ver_num, entry_id),
                ).fetchone()
                if row is not None:
                    return dict(row)["version_id"]  # type: ignore[no-any-return]
                return None

        va_id = _resolve_version_id(version_a)
        vb_id = _resolve_version_id(version_b)

        if va_id is None:
            return {
                "entry_id": entry_id,
                "version_a": version_a,
                "version_b": version_b,
                "field_diffs": [],
                "summary": f"Version '{version_a}' not found for entry '{entry_id}'",
                "changed_fields_count": 0,
            }
        if vb_id is None:
            return {
                "entry_id": entry_id,
                "version_a": version_a,
                "version_b": version_b,
                "field_diffs": [],
                "summary": f"Version '{version_b}' not found for entry '{entry_id}'",
                "changed_fields_count": 0,
            }

        with self._connect() as conn:
            va_row = conn.execute(
                "SELECT * FROM entry_versions WHERE version_id = ?",
                (va_id,),
            ).fetchone()
            vb_row = conn.execute(
                "SELECT * FROM entry_versions WHERE version_id = ?",
                (vb_id,),
            ).fetchone()

        if va_row is None:
            return {
                "entry_id": entry_id,
                "version_a": version_a,
                "version_b": version_b,
                "field_diffs": [],
                "summary": f"Version '{version_a}' not found",
                "changed_fields_count": 0,
            }
        if vb_row is None:
            return {
                "entry_id": entry_id,
                "version_a": version_a,
                "version_b": version_b,
                "field_diffs": [],
                "summary": f"Version '{version_b}' not found",
                "changed_fields_count": 0,
            }

        va_path = Path(dict(va_row)["file_path"])
        vb_path = Path(dict(vb_row)["file_path"])

        if not va_path.is_file():
            return {
                "entry_id": entry_id,
                "version_a": version_a,
                "version_b": version_b,
                "field_diffs": [],
                "summary": f"Backup file not found for version '{version_a}': {va_path}",
                "changed_fields_count": 0,
            }
        if not vb_path.is_file():
            return {
                "entry_id": entry_id,
                "version_a": version_a,
                "version_b": version_b,
                "field_diffs": [],
                "summary": f"Backup file not found for version '{version_b}': {vb_path}",
                "changed_fields_count": 0,
            }

        text_a = va_path.read_text(encoding="utf-8")
        text_b = vb_path.read_text(encoding="utf-8")
        fm_a = _parse_frontmatter(text_a)
        fm_b = _parse_frontmatter(text_b)

        field_diffs: list[dict[str, Any]] = []
        all_keys: set[str] = set(fm_a.keys()) | set(fm_b.keys())

        def _serialize(val: Any) -> Any:
            """Make values JSON-safe for diff output."""
            if isinstance(val, (list, dict)):
                return val
            if isinstance(val, (str, int, float, bool, type(None))):
                return val
            return str(val)

        for key in sorted(all_keys):
            old_val = _serialize(fm_a.get(key))
            new_val = _serialize(fm_b.get(key))
            if old_val != new_val:
                field_diffs.append({
                    "field": key,
                    "old_value": old_val,
                    "new_value": new_val,
                })

        summary = (
            f"Compared {version_a} (v{dict(va_row)['version_num']}, "
            f"{dict(va_row)['created_at']}) with {version_b} "
            f"(v{dict(vb_row)['version_num']}, {dict(vb_row)['created_at']}): "
            f"{len(field_diffs)} field(s) changed"
        )

        return {
            "entry_id": entry_id,
            "version_a": version_a,
            "version_b": version_b,
            "field_diffs": field_diffs,
            "summary": summary,
            "changed_fields_count": len(field_diffs),
        }

    def count_entries_today(self, domain: str | None = None) -> int:
        """Return the number of entries collected today, optionally filtered by domain."""
        today = date.today().isoformat()  # "YYYY-MM-DD"
        with self._connect() as conn:
            if domain:
                (count,) = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE domain = ? AND collected_at >= ?",
                    (domain, today),
                ).fetchone()
            else:
                (count,) = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE collected_at >= ?",
                    (today,),
                ).fetchone()
            return count  # type: ignore[no-any-return]

    def count_entries(self, domain: str | None = None) -> int:
        """Return the total number of entries, optionally filtered by domain."""
        with self._connect() as conn:
            if domain:
                (count,) = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE domain = ?", (domain,)
                ).fetchone()
            else:
                (count,) = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
            return count  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Collection stats / diff
    # ------------------------------------------------------------------

    def get_collection_stats(self, period: str = "daily") -> dict[str, Any]:
        """Aggregated collection statistics for the given period.

        Parameters
        ----------
        period:
            ``"daily"`` — items collected today.
            ``"weekly"`` — items collected in the last 7 days.
            ``"monthly"`` — items collected in the last 30 days.

        Returns
        -------
        dict
            ``{period, date_from, date_to, total_items, new_items,
            duplicate_items, domains: {name: count}, sources: {name: count}}``
        """
        today = date.today()
        if period == "daily":
            date_from = today.isoformat()
        elif period == "weekly":
            from datetime import timedelta
            date_from = (today - timedelta(days=7)).isoformat()
        elif period == "monthly":
            from datetime import timedelta
            date_from = (today - timedelta(days=30)).isoformat()
        else:
            date_from = today.isoformat()

        date_to = today.isoformat()

        with self._connect() as conn:
            # Total items in period
            (total,) = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE collected_at >= ?",
                (date_from,),
            ).fetchone()

            # New (unique) vs duplicate
            (new_items,) = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE collected_at >= ? AND dedup_status = 'unique'",
                (date_from,),
            ).fetchone()
            (dup_items,) = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE collected_at >= ? AND dedup_status = 'duplicate'",  # noqa: E501
                (date_from,),
            ).fetchone()

            # Per-domain breakdown
            domain_rows = conn.execute(
                "SELECT domain, COUNT(*) as cnt FROM entries WHERE collected_at >= ? GROUP BY domain ORDER BY cnt DESC",  # noqa: E501
                (date_from,),
            ).fetchall()
            domains = {r["domain"]: r["cnt"] for r in domain_rows}

            # Per-source breakdown
            src_rows = conn.execute(
                "SELECT source_platform, COUNT(*) as cnt FROM entries WHERE collected_at >= ? GROUP BY source_platform ORDER BY cnt DESC",  # noqa: E501
                (date_from,),
            ).fetchall()
            sources = {r["source_platform"]: r["cnt"] for r in src_rows if r["source_platform"]}

        return {
            "period": period,
            "date_from": date_from,
            "date_to": date_to,
            "total_items": total,
            "new_items": new_items,
            "duplicate_items": dup_items,
            "domains": domains,
            "sources": sources,
        }

    def get_collection_diff(self, since_collection_id: str) -> dict[str, Any]:
        """Return entries collected since a previous collection ID.

        Parameters
        ----------
        since_collection_id:
            A collection ID (timestamp-based) to compare against.
            Only entries with ``collected_at > since_collection_id``
            are returned.

        Returns
        -------
        dict
            ``{since_id, new_entries: [...], count, domains: {name: count}}``
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM entries
                   WHERE collected_at > ?
                   ORDER BY collected_at DESC""",
                (since_collection_id,),
            ).fetchall()

        entries = [dict(r) for r in rows]
        domains: dict[str, int] = {}
        for e in entries:
            d = e.get("domain", "unknown")
            domains[d] = domains.get(d, 0) + 1

        return {
            "since_id": since_collection_id,
            "new_entries": entries,
            "count": len(entries),
            "domains": domains,
        }

    # ------------------------------------------------------------------
    # Flag / Tagging
    # ------------------------------------------------------------------

    def update_entry_tags(
        self, entry_id: str, tags: list[str], importance: int = 3
    ) -> None:
        """Update the ``tags`` and ``importance`` columns for an entry.

        Called by ``KBStore.flag_for_knowledge_base``.  Does not raise
        an error if the entry_id does not exist (SQL UPDATE on zero rows
        is a no-op).
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE entries SET tags = ?, importance = ? WHERE entry_id = ?",
                (
                    json.dumps(tags, ensure_ascii=False),
                    importance,
                    entry_id,
                ),
            )

    def update_entry_custom_fields(
        self, entry_id: str, fields: dict[str, Any]
    ) -> bool:
        """Merge *fields* into the entry's ``custom_fields`` JSON column.

        The ``custom_fields`` column is the KB metadata dict path: it is
        stored as JSON, returned by :meth:`get_entry` (and therefore by
        ``KBStore.get_entry`` / MCP ``get_kb_entry``), and written at
        index time from ``KBEntry.custom_fields``.  This method updates
        the column in place without touching the rest of the row, so
        unrelated columns (tags, source_url, ...) survive.

        Unlike ``INSERT OR REPLACE`` via :meth:`index_entry`, this is a
        targeted merge: keys in *fields* overwrite existing keys of the
        same name; everything else is preserved.

        Returns ``True`` when the entry exists and was updated, ``False``
        when no entry with *entry_id* was found.
        """
        existing = self.get_entry(entry_id)
        if existing is None:
            return False
        raw = existing.get("custom_fields") or "{}"
        try:
            current = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (json.JSONDecodeError, TypeError):
            current = {}
        current.update(fields)
        with self._connect() as conn:
            conn.execute(
                "UPDATE entries SET custom_fields = ? WHERE entry_id = ?",
                (json.dumps(current, ensure_ascii=False), entry_id),
            )
        return True

    # ------------------------------------------------------------------
    # FTS5 full-text search
    # ------------------------------------------------------------------

    def index_entry_fts5(self, entry: KBEntry, content: str = "") -> None:
        """Insert or update an entry in the FTS5 virtual table.

        The ``rowid`` in the FTS5 table matches the ``rowid`` in the
        ``entries`` table so that ``SEARCH ... JOIN entries`` works.

        *content* is the plain-text body of the entry (without frontmatter).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rowid FROM entries WHERE entry_id = ?",
                (entry.entry_id,),
            ).fetchone()
            if row is None:
                return
            rowid = row["rowid"]
            tags_json = json.dumps(entry.tags, ensure_ascii=False)
            conn.execute(
                "DELETE FROM entries_fts5 WHERE rowid = ?",
                (rowid,),
            )
            conn.execute(
                """INSERT INTO entries_fts5(rowid, title, summary, content, domain, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    rowid,
                    entry.title,
                    entry.summary,
                    content,
                    entry.domain,
                    tags_json,
                ),
            )

    def search_fts5(
        self,
        query: str,
        domain: str = "",
        limit: int = 20,
        offset: int = 0,
        mode: str = "fts5",
        filter_tags: list[str] | None = None,
        filter_date_from: str | None = None,
        filter_date_to: str | None = None,
        filter_quality_tier_min: int | None = None,
        filter_quality_tier_max: int | None = None,
        filter_content_type: str | None = None,
        filter_language: str | None = None,
        filter_user_id: str | None = None,
        filter_custom_fields: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Search the knowledge base using FTS5 full-text search.

        Returns a dict with keys: ``entries`` (list of matching entry
        dicts), ``total_count`` (int), ``query``, ``domain``, ``limit``,
        ``offset``, ``method``.  Falls back to a LIKE-based search if
        the FTS5 query syntax is invalid.

        To keep long natural-language questions from returning 0 hits
        (FTS5 MATCH uses AND semantics, so every token must match), the
        search walks a fallback chain when a query returns no results:
        (1) FTS5 MATCH with the escaped query (``method="fts5"``);
        (2) FTS5 MATCH with the meaningful non-stopword terms joined by
        ``OR`` (``method="or"``); (3) a LIKE search over title, summary
        and tags for those terms (``method="like"``).

        Parameters
        ----------
        query:
            Search query string.
        domain:
            Optional domain filter.
        limit:
            Max results (default 20).
        offset:
            Pagination offset.
        mode:
            Search mode: ``"fts5"`` (default, full-text only),
            ``"hybrid"`` (FTS5 + vector fusion), or ``"vector"``
            (vector-only).  Falls back to FTS5 when vector search is
            unavailable.
        filter_tags:
            Only include entries whose tags JSON array contains ANY of
            the given tag values.
        filter_date_from:
            Only include entries with ``collected_at >=`` this ISO date.
        filter_date_to:
            Only include entries with ``collected_at <=`` this ISO date.
        filter_quality_tier_min:
            Only include entries with ``quality_tier >=`` this value.
        filter_quality_tier_max:
            Only include entries with ``quality_tier <=`` this value.
        filter_content_type:
            Only include entries with this exact ``content_type``.
        filter_language:
            Only include entries with this exact ``language``.
        filter_user_id:
            Only include entries with this exact ``user_id``.
            When ``None``, no user_id filter is applied (returns all).
        filter_custom_fields:
            Faceted filter over the ``custom_fields`` JSON column (todo
            25, output-quality-mega — product-analysis metadata search).
            Each key is a dot-path into ``custom_fields`` (e.g.
            ``"product_analysis.action_required"``); an empty-string
            value matches entries where the field exists and is
            non-empty, any other value matches entries where the
            field's JSON value equals that text.  ``None`` applies no
            custom-fields filter (default behaviour unchanged).
        """
        safe_query = _escape_fts5_query(query)
        if not safe_query:
            return {
                "query": query,
                "domain": domain,
                "entries": [],
                "total_count": 0,
                "limit": limit,
                "offset": offset,
            }

        def _build_filter_params(
            prefix: str = "e",
        ) -> tuple[list[str], list[Any]]:
            """Build filter WHERE conditions and their parameter list.

            Returns (conditions_list, param_values) that can be merged
            into any SELECT on the ``entries`` table (aliased by
            *prefix*).  Always excludes entries whose ``custom_fields``
            status is ``archived`` or ``deprecated`` — they are stored
            but not discoverable via search.
            """
            conds: list[str] = []
            params: list[Any] = []

            if domain:
                conds.append(f"{prefix}.domain = ?")
                params.append(domain)

            if filter_tags:
                tag_conds = []
                for tag in filter_tags:
                    tag_conds.append(
                        f"EXISTS (SELECT 1 FROM json_each({prefix}.tags) WHERE value = ?)"
                    )
                    params.append(tag)
                conds.append(f"({' OR '.join(tag_conds)})")

            if filter_date_from:
                conds.append(f"{prefix}.collected_at >= ?")
                params.append(filter_date_from)

            if filter_date_to:
                conds.append(f"{prefix}.collected_at <= ?")
                params.append(filter_date_to)

            if filter_quality_tier_min is not None:
                conds.append(f"{prefix}.quality_tier >= ?")
                params.append(filter_quality_tier_min)

            if filter_quality_tier_max is not None:
                conds.append(f"{prefix}.quality_tier <= ?")
                params.append(filter_quality_tier_max)

            if filter_content_type:
                conds.append(f"{prefix}.content_type = ?")
                params.append(filter_content_type)

            if filter_language:
                conds.append(f"{prefix}.language = ?")
                params.append(filter_language)

            if filter_user_id is not None:
                conds.append(f"{prefix}.user_id = ?")
                params.append(filter_user_id)

            if filter_custom_fields:
                for path, expected in filter_custom_fields.items():
                    _validate_custom_field_path(path)
                    json_path = f"$.{path}"
                    if expected == "":
                        # Presence: the field must exist with a non-empty
                        # value.  json_type() is NULL when the path is
                        # missing; a JSON null / empty container / empty
                        # string is treated as absent.
                        conds.append(
                            f"(json_type({prefix}.custom_fields, ?) IS NOT NULL "
                            f"AND json_type({prefix}.custom_fields, ?) != 'null' "
                            f"AND json_extract({prefix}.custom_fields, ?) "
                            f"NOT IN ('[]', '{{}}', '\"\"'))"
                        )
                        params.extend([json_path, json_path, json_path])
                    else:
                        conds.append(
                            f"CAST(json_extract({prefix}.custom_fields, ?) "
                            f"AS TEXT) = ?"
                        )
                        params.extend([json_path, expected])

            conds.append(
                f"(json_type({prefix}.custom_fields, '$.status') IS NULL "
                f"OR CAST(json_extract({prefix}.custom_fields, '$.status') "
                f"AS TEXT) NOT IN ('archived', 'deprecated'))"
            )

            return conds, params

        with self._connect() as conn:
            def _fts5_rows(match_query: str) -> list[sqlite3.Row]:
                """Run an FTS5 MATCH with dynamic filters, returning rows."""
                fts_conds = ["entries_fts5 MATCH ?"]
                fts_params: list[Any] = [match_query]

                extra_conds, extra_params = _build_filter_params("e")
                fts_conds.extend(extra_conds)
                fts_params.extend(extra_params)

                where_clause = " AND ".join(fts_conds)

                return conn.execute(
                    f"""SELECT e.entry_id, e.title, e.summary, e.relevance_score,
                               e.source_score, e.file_path, e.domain, e.collected_at,
                               e.created_at, e.tier, f.rank
                        FROM entries_fts5 f
                        JOIN entries e ON e.rowid = f.rowid
                        WHERE {where_clause}
                        ORDER BY f.rank""",
                    fts_params,
                ).fetchall()

            method = "fts5"
            fts5_syntax_error = False
            try:
                rows = _fts5_rows(safe_query)
            except sqlite3.OperationalError:
                # FTS5 MATCH syntax error (e.g. query is a bare FTS5
                # keyword like "NOT") — the LIKE path is the only way to
                # search; fall through with an empty result set.
                rows = []
                fts5_syntax_error = True

            # A hyphenated pseudo-token like ``t9ztoken-no-such-term-zzz``
            # is split by _escape_fts5_query into 5 tokens, and FTS5 AND
            # semantics already decide "no match".  Multi-word
            # (natural-language) queries may still legitimately need the
            # OR/LIKE fallback chain (long questions match nothing under
            # pure AND).  Single-token queries must NOT fall back: OR/LIKE
            # lets a common fragment (e.g. ``term`` in long-term/short-term)
            # match unrelated entries, breaking the negative path (issue
            # #191).  Exception: a FTS5 syntax error leaves no other path,
            # so the LIKE fallback is kept for that case.
            is_multiword = " " in query.strip()
            meaningful: list[str] = []

            if not rows and is_multiword:
                # Step 2 — retry with OR semantics across the meaningful
                # (non-stopword) terms, since FTS5 MATCH defaults to AND
                # semantics and long questions can match nothing.
                meaningful = _meaningful_search_terms(query)
                or_terms = [
                    e for e in (_escape_fts5_query(t) for t in meaningful) if e
                ]
                if or_terms:
                    or_query = " OR ".join(or_terms)
                    method = "or"
                    try:
                        rows = _fts5_rows(or_query)
                    except sqlite3.OperationalError:
                        rows = []

            if not rows and (is_multiword or fts5_syntax_error):
                # Step 3 — LIKE fallback across title, summary, tags
                method = "like"
                like_terms = meaningful if is_multiword else _split_search_terms(query)
                like_parts: list[str] = []
                like_params: list[Any] = []
                for term in like_terms:
                    like_parts.append(
                        "(e.title LIKE ? OR e.summary LIKE ? OR e.tags LIKE ?)"
                    )
                    pattern = f"%{term}%"
                    like_params.extend([pattern, pattern, pattern])

                if not like_parts:
                    like_parts = ["(e.title LIKE ? OR e.summary LIKE ?)"]
                    like_params = [f"%{query}%", f"%{query}%"]

                like_conds = ["(" + " OR ".join(like_parts) + ")"]
                extra_conds_l, extra_params_l = _build_filter_params("e")
                like_conds.extend(extra_conds_l)
                like_params.extend(extra_params_l)

                like_where = " AND ".join(like_conds)

                rows = conn.execute(
                    f"""SELECT e.* FROM entries e
                        WHERE {like_where}
                        ORDER BY e.collected_at DESC""",
                    like_params,
                ).fetchall()
                # Convert to match FTS5 output shape
                entries = [dict(r) for r in rows]
                total = len(entries)
                paged = entries[offset : offset + limit]

                result: dict[str, Any] = {
                    "query": query,
                    "domain": domain,
                    "entries": paged,
                    "total_count": total,
                    "limit": limit,
                    "offset": offset,
                    "fts5_fallback": True,
                }

                if mode == "fts5":
                    result["method"] = method
                    return result

                # For hybrid/vector, try vector search on top
                return self._blend_with_vector(
                    result=result,
                    entries=entries,
                    query=query,
                    domain=domain,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                    mode=mode,
                )

        entries = [dict(r) for r in rows]
        total = len(entries)
        paged = entries[offset : offset + limit]

        result: dict[str, Any] = {  # type: ignore[no-redef]
            "query": query,
            "domain": domain,
            "entries": paged,
            "total_count": total,
            "limit": limit,
            "offset": offset,
        }

        if mode == "fts5":
            result["method"] = method
            return result

        # For hybrid/vector, open a new connection for vector search
        with self._connect() as conn:
            return self._blend_with_vector(
                result=result,
                entries=entries,
                query=query,
                domain=domain,
                limit=limit,
                offset=offset,
                conn=conn,
                mode=mode,
            )

    # ------------------------------------------------------------------
    # Vector / hybrid search helpers
    # ------------------------------------------------------------------

    def _blend_with_vector(
        self,
        result: dict[str, Any],
        entries: list[dict[str, Any]],
        query: str,
        domain: str,
        limit: int,
        offset: int,
        conn: sqlite3.Connection,
        mode: str,
    ) -> dict[str, Any]:
        """Blend FTS5 results with vector search for hybrid/vector modes.

        Called from :meth:`search_fts5` when *mode* is ``"hybrid"`` or
        ``"vector"``.  Falls back to FTS5 with a ``note`` when the
        sqlite-vec extension or embedding generation is unavailable.
        """
        from autoinfo.embeddings import (
            generate_embedding,
            load_vec_extension,
        )
        from autoinfo.embeddings import (
            is_available as vec_available,
        )

        # --- graceful degradation ------------------------------------------
        if not vec_available:
            result["method"] = "fts5"
            result["note"] = "vector unavailable"
            return result

        loaded = load_vec_extension(conn)
        if not loaded:
            result["method"] = "fts5"
            result["note"] = "vector unavailable"
            return result

        # --- config: model name + hybrid weights ---------------------------
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        model_name = "text-embedding-ada-002"
        w_fts5 = 0.7
        w_vec = 0.3
        if config_path:
            cfg = load_config(config_path)
            if cfg.vector_search.model:
                model_name = cfg.vector_search.model
            w_fts5 = cfg.vector_search.hybrid_weight_fts5
            w_vec = cfg.vector_search.hybrid_weight_vector

        # --- generate query embedding --------------------------------------
        query_embedding = generate_embedding(
            query,
            {"model": model_name},
        )

        # --- ensure embedding table exists ---------------------------------
        from autoinfo.embeddings import ensure_embedding_table

        ensure_embedding_table(conn)

        # --- vector KNN search ---------------------------------------------
        import sqlite_vec as _sv  # noqa: PLC0415 — deferred import

        try:
            blob = _sv.serialize_float32(query_embedding)
        except Exception:
            result["method"] = "fts5"
            result["note"] = "vector unavailable"
            return result

        try:
            if domain:
                vec_rows = conn.execute(
                    """SELECT emb.entry_id,
                              vec_distance_cosine(emb.embedding, ?) AS distance
                       FROM entry_embeddings emb
                       JOIN entries e ON e.entry_id = emb.entry_id
                       WHERE e.domain = ?
                         AND (json_type(e.custom_fields, '$.status') IS NULL
                              OR CAST(json_extract(e.custom_fields, '$.status')
                                      AS TEXT) NOT IN ('archived', 'deprecated'))
                       ORDER BY distance
                       LIMIT ?""",
                    (blob, domain, limit + offset),
                ).fetchall()
            else:
                vec_rows = conn.execute(
                    """SELECT emb.entry_id,
                              vec_distance_cosine(emb.embedding, ?) AS distance
                       FROM entry_embeddings emb
                       JOIN entries e ON e.entry_id = emb.entry_id
                       WHERE json_type(e.custom_fields, '$.status') IS NULL
                          OR CAST(json_extract(e.custom_fields, '$.status')
                                  AS TEXT) NOT IN ('archived', 'deprecated')
                       ORDER BY distance
                       LIMIT ?""",
                    (blob, limit + offset),
                ).fetchall()
        except Exception:
            logger.warning("Vector KNN query failed — falling back to FTS5")
            result["method"] = "fts5"
            result["note"] = "vector unavailable"
            return result

        # Build dict: entry_id -> vec_similarity (0-1 range)
        vec_scores: dict[str, float] = {}
        for row in vec_rows:
            eid = row["entry_id"] if isinstance(row, sqlite3.Row) else row[0]
            distance = row["distance"] if isinstance(row, sqlite3.Row) else row[1]
            if distance is not None:
                # vec_distance_cosine returns 0-2; convert to 0-1 similarity
                vec_scores[eid] = 1.0 - float(distance) / 2.0

        # -----------------------------------------------------------
        # mode == "vector" — return vector-only results
        # -----------------------------------------------------------
        if mode == "vector":
            vector_entries: list[dict[str, Any]] = []
            for eid, _score in sorted(
                vec_scores.items(), key=lambda x: x[1], reverse=True
            ):
                entry_dict = self.get_entry(eid)
                if entry_dict:
                    entry_dict["_vec_score"] = vec_scores[eid]
                    vector_entries.append(entry_dict)

            total = len(vector_entries)
            paged = vector_entries[offset : offset + limit]
            # Strip internal helper key
            for e in paged:
                e.pop("_vec_score", None)

            result["entries"] = paged
            result["total_count"] = total
            result["method"] = "vector"
            return result

        # -----------------------------------------------------------
        # mode == "hybrid" — fuse FTS5 + vector scores
        # -----------------------------------------------------------
        # Build entry_id -> fts5_score lookup
        fts5_scores: dict[str, float] = {}
        for entry_dict in entries:
            eid = entry_dict["entry_id"]
            rank = entry_dict.get("rank")
            if rank is not None:
                # FTS5 rank is negative BM25; normalize to 0-1
                fts5_scores[eid] = 1.0 / (1.0 + abs(rank))
            else:
                fts5_scores[eid] = 0.0

        # Merge all unique entry IDs
        all_ids = set(fts5_scores.keys()) | set(vec_scores.keys())

        scored: list[tuple[str, float, dict[str, Any]]] = []  # (entry_id, score, dict)
        for eid in all_ids:
            fts5 = fts5_scores.get(eid, 0.0)
            vec = vec_scores.get(eid, 0.0)
            hybrid = w_fts5 * fts5 + w_vec * vec

            if eid in fts5_scores:
                # Already have the entry dict from FTS5 results
                entry_dict = next(e for e in entries if e["entry_id"] == eid)
            else:
                # Vector-only hit — fetch from DB
                entry_dict = self.get_entry(eid)
                if entry_dict is None:
                    continue

            scored.append((eid, hybrid, entry_dict))

        # Sort descending by hybrid score
        scored.sort(key=lambda x: x[1], reverse=True)

        total = len(scored)
        paged_dicts = [sd[2] for sd in scored[offset : offset + limit]]

        result["entries"] = paged_dicts
        result["total_count"] = total
        result["method"] = "hybrid"
        return result

    def reindex_fts5(self) -> int:
        """Rebuild the entire FTS5 index from the ``entries`` table.

        Iterates all entries, reads their file content (if available on
        disk), and populates the FTS5 virtual table.  Returns the number
        of entries indexed.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, * FROM entries"
            ).fetchall()

        # Clear existing FTS5 content
        with self._connect() as conn:
            conn.execute("DELETE FROM entries_fts5")

        count = 0
        for row in rows:
            d = dict(row)
            rowid = d["rowid"]
            file_path = d.get("file_path") or ""
            content = ""
            if file_path and Path(file_path).is_file():
                raw = Path(file_path).read_text(encoding="utf-8")
                content = _strip_frontmatter(raw)

            title = d.get("title") or ""
            summary = d.get("summary") or ""
            domain = d.get("domain") or ""
            tags_json = d.get("tags") or ""

            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO entries_fts5(rowid, title, summary, content, domain, tags)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (rowid, title, summary, content, domain, tags_json),
                )
            count += 1

        return count

    # ------------------------------------------------------------------
    # Knowledge graph — entity indexing & relation discovery
    # ------------------------------------------------------------------

    def _entity_id(self, name: str, domain: str) -> str:
        """Deterministic entity ID from name + domain."""
        raw = f"{domain}:{name.lower().strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def index_entities(
        self,
        entry_id: str,
        domain: str,
        entities: list[dict[str, Any]],
    ) -> int:
        """Store entities extracted for a single entry.

        Each entity dict should have ``name`` and ``type`` keys (as
        returned by the LLM extractor).  Returns the number of entities
        indexed.
        """
        count = 0
        with self._connect() as conn:
            for ent in entities:
                name = ent.get("name", "").strip()
                etype = ent.get("type", "").strip()
                if not name or not etype:
                    continue
                eid = self._entity_id(name, domain)
                conn.execute(
                    """INSERT OR IGNORE INTO entities
                       (entity_id, name, type, domain, entry_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (eid, name, etype, domain, entry_id),
                )
                count += conn.total_changes  # not perfect but indicative
            # Deduplicate — keep only the first (earliest) row per name+type+domain
            conn.execute("""
                DELETE FROM entities
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM entities
                    WHERE domain = ?
                    GROUP BY name, type, domain
                )
                AND domain = ?
            """, (domain, domain))
        return count

    def discover_relations(
        self,
        entry_id: str,
        domain: str,
        entity_names: list[str],
    ) -> int:
        """Auto-discover ``related_to`` relations between entities sharing an entry.

        For every pair of distinct entity names in *entity_names* that
        exist in the ``entities`` table, create or update a ``related_to``
        relation in ``kg_relations`` with a strength proportional to the
        number of entries they co-occur in.

        Returns the number of relation rows upserted.
        """
        if len(entity_names) < 2:
            return 0

        count = 0
        with self._connect() as conn:
            for i in range(len(entity_names)):
                for j in range(i + 1, len(entity_names)):
                    a = entity_names[i].strip().lower()
                    b = entity_names[j].strip().lower()
                    if a == b or not a or not b:
                        continue
                    eid_a = self._entity_id(a, domain)
                    eid_b = self._entity_id(b, domain)

                    # Ensure a < b for canonical ordering
                    if eid_a > eid_b:
                        eid_a, eid_b = eid_b, eid_a

                    # Get current entries_shared set
                    row = conn.execute(
                        "SELECT entries_shared, strength FROM kg_relations "
                        "WHERE entity_a = ? AND entity_b = ? AND relation_type = 'related_to'",
                        (eid_a, eid_b),
                    ).fetchone()

                    if row is not None:
                        shared: set[str] = set(
                            json.loads(row["entries_shared"] or "[]")
                        )
                        shared.add(entry_id)
                        strength = len(shared)
                        conn.execute(
                            "UPDATE kg_relations SET strength = ?, entries_shared = ? "
                            "WHERE entity_a = ? AND entity_b = ? AND relation_type = 'related_to'",
                            (
                                strength,
                                json.dumps(sorted(shared)),
                                eid_a,
                                eid_b,
                            ),
                        )
                    else:
                        conn.execute(
                            """INSERT OR IGNORE INTO kg_relations
                               (entity_a, entity_b, relation_type, strength, entries_shared, domain)
                               VALUES (?, ?, 'related_to', ?, ?, ?)""",
                            (
                                eid_a,
                                eid_b,
                                1.0,
                                json.dumps([entry_id]),
                                domain,
                            ),
                        )
                    count += 1

        return count

    def query_knowledge_graph(
        self,
        entity: str,
        relation: str = "related_to",
        domain: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Query the knowledge graph for entities related to *entity*.

        Parameters
        ----------
        entity:
            Entity name to query (case-insensitive partial match).
        relation:
            Relation type filter (default ``"related_to"``).  Use ``""``
            to match all relation types.
        domain:
            Optional domain scope.
        limit:
            Maximum results (default 20).

        Returns
        -------
        dict
            ``{entity, relation, domain, results: [{entity_a, entity_b,
            relation_type, strength, entries_shared_count}], total_count}``
        """
        results: list[dict[str, Any]] = []
        with self._connect() as conn:
            # Find all entity_ids that match the name
            like_q = f"%{entity}%"
            if domain:
                matching = conn.execute(
                    "SELECT DISTINCT entity_id, name FROM entities "
                    "WHERE name LIKE ? AND domain = ?",
                    (like_q, domain),
                ).fetchall()
            else:
                matching = conn.execute(
                    "SELECT DISTINCT entity_id, name FROM entities WHERE name LIKE ?",
                    (like_q,),
                ).fetchall()

            if not matching:
                return {
                    "entity": entity,
                    "relation": relation,
                    "domain": domain,
                    "results": [],
                    "total_count": 0,
                }

            entity_ids = {r["entity_id"] for r in matching}
            entity_names = {r["entity_id"]: r["name"] for r in matching}

            for eid in entity_ids:
                if relation:
                    rows = conn.execute(
                        """SELECT r.entity_a, r.entity_b, r.relation_type,
                                  r.strength, r.entries_shared
                           FROM kg_relations r
                           WHERE (r.entity_a = ? OR r.entity_b = ?)
                             AND r.relation_type = ?
                           ORDER BY r.strength DESC
                           LIMIT ?""",
                        (eid, eid, relation, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT r.entity_a, r.entity_b, r.relation_type,
                                  r.strength, r.entries_shared
                           FROM kg_relations r
                           WHERE r.entity_a = ? OR r.entity_b = ?
                           ORDER BY r.strength DESC
                           LIMIT ?""",
                        (eid, eid, limit),
                    ).fetchall()

                for row in rows:
                    other_eid = (
                        row["entity_b"]
                        if row["entity_a"] == eid
                        else row["entity_a"]
                    )
                    # Skip self-relations
                    if other_eid == eid:
                        continue
                    shared_raw = row["entries_shared"] or "[]"
                    shared_count = len(json.loads(shared_raw))
                    results.append({
                        "entity": entity_names.get(eid, eid),
                        "related_entity": entity_names.get(other_eid, other_eid),
                        "relation_type": row["relation_type"],
                        "strength": row["strength"],
                        "entries_shared_count": shared_count,
                    })

        # Deduplicate by (entity, related_entity, relation_type)
        seen: set[tuple[str, str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for r in results:
            key = (r["entity"], r["related_entity"], r["relation_type"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        deduped = sorted(deduped, key=lambda x: x["strength"], reverse=True)[:limit]

        return {
            "entity": entity,
            "relation": relation,
            "domain": domain,
            "results": deduped,
            "total_count": len(deduped),
        }

    def list_entities(self, domain: str = "") -> list[dict[str, Any]]:
        """Return all entities, optionally filtered by *domain*.

        Each entity dict contains: ``entity_id``, ``name``, ``type``,
        ``domain``, ``entry_id``, ``created_at``.
        """
        with self._connect() as conn:
            if domain:
                rows = conn.execute(
                    "SELECT entity_id, name, type, domain, entry_id, created_at "
                    "FROM entities WHERE domain = ? ORDER BY name",
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT entity_id, name, type, domain, entry_id, created_at "
                    "FROM entities ORDER BY name"
                ).fetchall()
            return [dict(r) for r in rows]

    def list_relations(self, domain: str = "") -> list[dict[str, Any]]:
        """Return all relations, optionally filtered by *domain*.

        Each relation dict contains: ``relation_id``, ``entity_a``,
        ``entity_a_name``, ``entity_b``, ``entity_b_name``,
        ``relation_type``, ``strength``, ``entries_shared``, ``domain``,
        ``created_at``.
        """
        base_query = (
            "SELECT r.relation_id, r.entity_a, a.name AS entity_a_name, "
            "r.entity_b, b.name AS entity_b_name, r.relation_type, "
            "r.strength, r.entries_shared, r.domain, r.created_at "
            "FROM kg_relations r "
            "JOIN entities a ON r.entity_a = a.entity_id "
            "JOIN entities b ON r.entity_b = b.entity_id "
        )
        with self._connect() as conn:
            if domain:
                rows = conn.execute(
                    base_query + "WHERE r.domain = ? ORDER BY r.strength DESC",
                    (domain,),
                ).fetchall()
            else:
                rows = conn.execute(
                    base_query + "ORDER BY r.strength DESC"
                ).fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# KBStore
# ---------------------------------------------------------------------------


def _default_kb_base_path() -> Path:
    """Resolve the default KB base path anchored at the project root.

    The project root is the first ancestor of the current working directory
    (walking up, stopping before the home directory) that contains
    ``.autoinfo/config.yaml`` — the same marker :func:`autoinfo.config.
    get_config_path` uses, but anchored by ancestor walk instead of cwd-only.
    This makes ``KBStore()`` resolve to the same ``<root>/knowledge`` no
    matter which subdirectory of the project the process runs from.

    When no project config is found, falls back to ``Path("knowledge")``
    relative to the current working directory (historical behavior, which
    keeps cwd-based callers — including tests that chdir to a temp project —
    unchanged).
    """
    for ancestor in (Path.cwd(), *Path.cwd().parents):
        if ancestor == Path.home():
            break
        if (ancestor / ".autoinfo" / "config.yaml").is_file():
            return ancestor / "knowledge"
    return Path("knowledge")


# Minimum meaningful content length for a KB entry.  The process pipeline
# (process.py) and importers (importer.py) already enforce 50 characters;
# centralizing the constant here lets every write boundary — MCP
# create_kb_entry / create_kb_draft and the REST API — share the same floor
# (issue #279: entries with empty/short content must never enter the KB).
MIN_KB_CONTENT_CHARS = 50


class KBStore:
    """High-level knowledge base store that combines Markdown files + SQLite.

    File path convention::

        knowledge/<domain>/01-Raw/<topic>/<YYYY-MM-DD>-<slug>.md

    Usage
    -----
    >>> store = KBStore(base_path=Path("knowledge"))
    >>> entry = store.store_entry(item, extraction, quality_results)
    >>> entries = store.list_entries("medical-research")
    >>> full = store.get_entry(entry.entry_id)
    """

    def __init__(self, base_path: Path | None = None, min_content_chars: int = 0) -> None:
        # min_content_chars defaults to 0 so unit tests with intentionally
        # short fixtures keep working; production entry points (process.py,
        # importer.py, api routes) pass 50 explicitly (#182).
        if base_path is None:
            base_path = _default_kb_base_path()
        self.base_path = base_path.resolve()
        self.min_content_chars = min_content_chars
        # Place the SQLite db alongside the knowledge directory
        db_path = self.base_path.parent / "autoinfo.db"
        self.index = SQLiteIndex(db_path)
        self.index.init_db()
        # Ensure schema version is compatible (auto-migrates if needed)
        with self.index._connect() as conn:
            check_schema(conn)

    # ------------------------------------------------------------------
    # Filesystem fallback when SQLite index is empty
    # ------------------------------------------------------------------

    def _scan_kb_filesystem(
        self,
        domain: str,
        tier: str | None = None,
        entry_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback: walk ``knowledge/<domain>/`` and parse frontmatter from ``.md`` files.

        Returns the same dict shape as :meth:`SQLiteIndex.list_entries` so
        callers can use it as a transparent fallback when the SQLite index
        is empty or the requested entry is not found.

        Parameters
        ----------
        domain:
            Domain to scan.
        tier:
            Optional tier filter (e.g. ``"01-Raw"``, ``"02-Draft"``).
        entry_id:
            Optional entry ID — when set, only the matching file is returned.

        Returns
        -------
        list[dict]
            Each dict mirrors the columns returned by ``SQLiteIndex.list_entries``.
        """
        search_root = self.base_path / domain
        if not search_root.is_dir():
            return []

        results: list[dict[str, Any]] = []
        for md_file in sorted(search_root.rglob("*.md"), reverse=True):
            try:
                if tier and f"/{tier}/" not in str(md_file):
                    continue

                raw = md_file.read_text(encoding="utf-8")
                if not raw.startswith("---"):
                    continue
                end = raw.find("---", 3)
                if end == -1:
                    continue
                fm = yaml.safe_load(raw[3:end]) or {}
                if not isinstance(fm, dict) or "entry_id" not in fm:
                    continue

                if entry_id and fm["entry_id"] != entry_id:
                    continue

                tags = fm.get("tags", [])
                results.append({
                    "entry_id": fm.get("entry_id", ""),
                    "title": fm.get("title", ""),
                    "domain": fm.get("domain", domain),
                    "tier": fm.get("tier", tier or "01-Raw"),
                    "source_url": fm.get("source_url", ""),
                    "source_type": fm.get("source_type", ""),
                    "source_platform": fm.get("source_platform", ""),
                    "collected_at": fm.get("collected_at", ""),
                    "summary": fm.get("summary", ""),
                    "quality_tier": fm.get("quality_tier", 1),
                    "relevance_score": fm.get("relevance_score", 0.0),
                    "dedup_status": fm.get("dedup_status", "unique"),
                    "file_path": str(md_file),
                    "tags": json.dumps(tags) if isinstance(tags, list) else str(tags),
                    "content_type": fm.get("content_type", ""),
                    "language": fm.get("language", ""),
                    "user_id": fm.get("user_id", ""),
                    "cefr": fm.get("cefr", ""),
                })
            except Exception:
                continue

        results.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
        return results

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_not_wiki(file_path: str | Path) -> None:
        """Raise ``PermissionError`` if *file_path* targets the 03-Wiki tier.

        03-Wiki is append-only.  Only ``promote_kb_draft()`` may write
        entries into this tier — agent-facing write methods must reject
        any attempt to create or modify files under ``03-Wiki/``.
        """
        path_str = str(file_path)
        if "/03-Wiki/" in path_str or path_str.endswith("/03-Wiki"):
            raise PermissionError(
                "03-Wiki is append-only. "
                "Only promote_kb_draft() can write here."
            )

    def store_entry(
        self,
        item: Item,
        extraction: ExtractionResult | None = None,
        quality_results: dict[str, QualityResult] | None = None,
        tier: str = "01-Raw",
        user_id: str | None = None,
        topic_keywords: list[str] | None = None,
    ) -> KBEntry | None:
        """Create a Markdown KB entry for *item* and index it in SQLite.

        Parameters
        ----------
        item:
            The collected item to persist.
        extraction:
            Optional LLM extraction output (adds TL;DR + key points to body).
        quality_results:
            Quality gate results keyed by gate name.  Used to populate
            ``relevance_score`` (from G3) and ``dedup_status`` (from G2).
            A soft gate with ``details["archive"] = True`` (G3 relevance
            below threshold with action "archive") marks the entry
            ``status="archived"`` — stored, but excluded from search
            results and digest generation.
        tier:
            KB pipeline tier (default "01-Raw").  Set to "02-Draft" for
            agent-created Draft entries.
        topic_keywords:
            Optional keyword list for tag derivation (issue #68).  When the
            collector set no ``item.topic_tags``, tags are derived from the
            topic keywords that appear (case-insensitively) in the CLEANED
            TITLE, capped at 5.  ``None`` (the api/routes.py create_entry
            path) keeps the legacy empty-tags behavior.  Derivation is pure
            and O(keywords × title length) — it runs under ``_STORAGE_LOCK``
            in parallel workers, so it never touches the DB or the filesystem.

        Returns
        -------
        KBEntry
            The newly created entry (also persisted to disk + index).

        Raises
        ------
        PermissionError
            If *tier* is "03-Wiki" (append-only — use ``promote_kb_draft()``).
        """
        # --- derive metadata ---------------------------------------------------
        domain = item.domain or "default"
        topic = item.topic_tags[0] if item.topic_tags else "general"
        slug = _slugify(item.title)
        collected_date = _parse_date(item.collected_at)

        topic_slug = _slugify(topic)
        entry_id = f"{domain}-{topic_slug}-{slug}"

        # File path: knowledge/<domain>/<tier>/<topic>/<YYYY-MM-DD>-<slug>.md
        date_str = collected_date.isoformat()
        file_dir = self.base_path / domain / tier / topic
        file_name = f"{date_str}-{slug}.md"
        file_path = file_dir / file_name

        # 03-Wiki is append-only — reject agent-facing writes here
        self._ensure_not_wiki(file_path)

        # --- parse quality gate results ----------------------------------------
        relevance_score: float = 0.0
        dedup_status: str = "unique"
        quality_tier: int = item.quality_tier
        source_score: float = 0.0

        if quality_results:
            g3 = quality_results.get("G3-RelevanceScoring")
            if g3 is not None:
                relevance_score = g3.score

            g2 = quality_results.get("G2-Dedup")
            if g2 is not None:
                # Prefer explicit dedup_status if set, else derive from is_duplicate
                raw = g2.details.get("dedup_status")
                if raw:
                    dedup_status = str(raw)
                elif g2.details.get("is_duplicate"):
                    dedup_status = "duplicate"

            g1 = quality_results.get("G1-SourceAuthority")
            if g1 is not None:
                raw_score = g1.details.get("source_score")
                if raw_score is not None:
                    source_score = float(raw_score)  # type: ignore[arg-type]

        entry_status: str = "active"
        if quality_results:
            for _gr in quality_results.values():
                if _gr.details.get("archive") is True:
                    entry_status = "archived"
                    break

        # --- preserve lifecycle status on re-ingest (backup issue #79) ---------
        # Re-processing re-runs the quality gates over cached items.  A gate
        # deciding "archive" on a re-run must NOT downgrade an already-delivered
        # entry (active -> archived) — that removes valid content from digests
        # (empty-shell regression).  entry_id is content-derived, so a re-ingest
        # of the same item resolves to the same id: preserve the existing
        # status when the entry already exists; gates only apply to NEW entries.
        existing_entry = self.index.get_entry(entry_id)
        if existing_entry is not None:
            try:
                existing_cf = json.loads(existing_entry.get("custom_fields") or "{}")
            except (json.JSONDecodeError, TypeError):
                existing_cf = {}
            existing_status = existing_cf.get("status") or existing_entry.get("status")
            if existing_status in ("active", "archived", "deprecated"):
                entry_status = existing_status

        # --- resolve user_id ---------------------------------------------------
        resolved_user_id: str = ""
        if user_id is not None:
            resolved_user_id = user_id
        else:
            # Try from config multi_user settings
            try:
                from autoinfo.config import get_config_path, load_config

                cfg_path = get_config_path()
                if cfg_path:
                    cfg = load_config(cfg_path)
                    if cfg.multi_user.enabled:
                        # Prefer item.raw_data["user_id"], fall back to default
                        resolved_user_id = str(
                            item.raw_data.get("user_id", cfg.multi_user.default_user_id)
                        )
            except Exception:
                pass  # No config available — stay with empty user_id

        # --- build KBEntry -----------------------------------------------------
        # Issue #55: decode residual HTML entities at the storage layer so
        # every downstream surface (title / summary / tags / body) is clean.
        cleaned_title = _decode_html_entities(str(item.title or ""))
        summary = extraction.tl_dr if extraction and extraction.tl_dr else ""
        summary = _decode_html_entities(str(summary))
        tags = [_decode_html_entities(str(tag)) for tag in item.topic_tags]
        # Issue #68: collectors often set no topic_tags, leaving the digest
        # "Tags" column empty.  Derive tags from the title-matching topic
        # keywords (title-hit only — body-only matches are noise), capped at
        # 5, coerced via str().  Pure O(keywords × title-length) — no DB/IO —
        # and item.topic_tags is never mutated.
        if not tags and topic_keywords:
            title_low = cleaned_title.lower()
            derived: list[str] = []
            for kw in topic_keywords:
                if not kw:
                    continue
                if str(kw).lower() in title_low:
                    derived.append(str(kw))
                    if len(derived) == 5:
                        break
            tags = derived

        # Issue #182 audit-feedback:
        # 1) collected_at must never be empty at rest — fall back to the
        #    content/creation time so provenance is always present.
        # 2) items whose content is essentially absent (title only, <50
        #    chars) are not yet usable as paid content — skip them instead
        #    of polluting KB with empty shells.
        collected_at = item.collected_at or ""
        if not collected_at.strip():
            created_at_ts = datetime.now(timezone.utc).isoformat()
            collected_at = created_at_ts
        content_len = len((item.content or "").strip())
        if content_len < self.min_content_chars:
            logger.warning(
                "Skipping KB store for %s: content too short (%d chars) — "
                "title-only item would ship an empty shell (#182)",
                item.id,
                content_len,
            )
            return None

        entry = KBEntry(
            entry_id=entry_id,
            title=cleaned_title,
            domain=domain,
            tier=tier,
            source_url=item.source_url,
            source_type=item.source_type,
            source_platform=item.source_platform,
            collected_at=collected_at,
            summary=summary,
            tags=tags,
            quality_tier=quality_tier,
            relevance_score=relevance_score,
            dedup_status=dedup_status,
            source_score=source_score,
            file_path=str(file_path),
            language=item.language,
            user_id=resolved_user_id,
            version=getattr(item, "version", 1),
            previous_version=getattr(item, "previous_version", 0),
            supersedes=getattr(item, "supersedes", ""),
            trace_id=getattr(item, "trace_id", ""),
            status=entry_status,
        )

        # --- write Markdown file ----------------------------------------------
        file_dir.mkdir(parents=True, exist_ok=True)

        frontmatter = _build_frontmatter(entry, quality_results, extraction)
        body = _build_body(item, extraction)

        full_content = f"---\n{frontmatter}---\n\n{body}"
        file_path.write_text(full_content, encoding="utf-8")

        # --- index in SQLite + FTS5 -------------------------------------------
        # Versioning: save a .bak copy if this entry_id already exists
        existing = self.index.get_entry(entry_id)
        if existing is not None:
            self.index.save_entry_version(
                entry_id=entry_id,
                file_path=str(file_path),
                comment=f"Auto-backup before update of {entry_id}",
            )

        self.index.index_entry(entry)
        self.index.index_entry_fts5(entry, content=body)

        # --- vector embedding (if enabled) ------------------------------------
        self._maybe_store_embedding(entry, body)

        # --- Auto-linking: keyword overlap with existing entries ---------------
        self._auto_link_entry(entry, item)

        return entry

    # ------------------------------------------------------------------
    # Vector embedding helper
    # ------------------------------------------------------------------

    def _maybe_store_embedding(self, entry: KBEntry, body: str) -> None:
        """Generate and store a vector embedding for *entry* if vector search is enabled.

        Called from :meth:`store_entry` after the FTS5 index is updated.
        Failures are logged but do not propagate — a failed embedding must
        never block the entry creation flow.
        """
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        if not config_path:
            return
        config = load_config(config_path)
        if not config.vector_search.enabled:
            return

        model_name = config.vector_search.model or "text-embedding-ada-002"

        # Construct meaningful text for embedding — title + body content
        entry_text = f"{entry.title}\n\n{body}"

        try:
            from autoinfo.embeddings import (
                generate_embedding,
                load_vec_extension,
                store_embedding,
            )

            embedding = generate_embedding(
                entry_text,
                {"model": model_name},
            )

            with self.index._connect() as conn:
                load_vec_extension(conn)
                from autoinfo.embeddings import ensure_embedding_table

                ensure_embedding_table(conn)
                store_embedding(conn, entry.entry_id, embedding, model_name)
                conn.commit()
        except Exception:
            logger.exception(
                "Failed to store embedding for entry %s — skipping",
                entry.entry_id,
            )

    # ------------------------------------------------------------------
    # Auto-linking helper
    # ------------------------------------------------------------------

    def _auto_link_entry(self, entry: KBEntry, item: Item) -> None:
        """Link *entry* to existing entries that share topic tags.

        Scans the SQLite index for entries in the same domain that have
        overlapping topic tags, then creates ``related`` relations.
        """
        if not entry.tags and not item.topic_tags:
            return

        # Combine sources of tags
        tags = set(entry.tags or []) | set(item.topic_tags or [])
        if not tags:
            return

        with self.index._connect() as conn:
            rows = conn.execute(
                "SELECT entry_id, tags FROM entries WHERE domain = ? AND entry_id != ?",
                (entry.domain, entry.entry_id),
            ).fetchall()

        for row in rows:
            existing_id = row["entry_id"]
            existing_tags_raw = row["tags"] or "[]"
            try:
                existing_tags = set(json.loads(existing_tags_raw))
            except (json.JSONDecodeError, TypeError):
                continue
            # Link if they share at least one tag
            if tags & existing_tags:
                self.index.link_items(
                    item_a_id=entry.entry_id,
                    item_b_id=existing_id,
                    relation_type="related",
                    metadata={"matched_tags": list(tags & existing_tags)},
                )

    # ------------------------------------------------------------------
    # Relations (item linking)
    # ------------------------------------------------------------------

    def link_items(
        self,
        item_a_id: str,
        item_b_id: str,
        relation_type: str = "related",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a link between two KB entries.

        See :meth:`SQLiteIndex.link_items` for details.
        """
        return self.index.link_items(
            item_a_id=item_a_id,
            item_b_id=item_b_id,
            relation_type=relation_type,
            metadata=metadata,
        )

    def get_item_relations(
        self, item_id: str, relation_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Return all relations where *item_id* participates."""
        return self.index.get_item_relations(
            item_id=item_id, relation_type=relation_type
        )

    # ------------------------------------------------------------------
    # Entry versioning
    # ------------------------------------------------------------------

    def get_entry_history(self, entry_id: str) -> list[dict[str, Any]]:
        """Return all saved backup versions for *entry_id*, newest first."""
        return self.index.get_entry_history(entry_id=entry_id)

    def restore_entry_version(self, version_id: str) -> dict[str, Any]:
        """Restore an entry from a saved version backup."""
        return self.index.restore_entry_version(version_id=version_id)

    def compare_versions(
        self, entry_id: str, version_a: str, version_b: str
    ) -> dict[str, Any]:
        """Compare two versions of a KB entry and return a structured diff.

        See :meth:`SQLiteIndex.compare_versions` for details.
        """
        return self.index.compare_versions(
            entry_id=entry_id, version_a=version_a, version_b=version_b
        )

    # ------------------------------------------------------------------
    # Collection stats / diff
    # ------------------------------------------------------------------

    def get_collection_stats(self, period: str = "daily") -> dict[str, Any]:
        """Aggregated collection statistics for the given period.

        Parameters
        ----------
        period:
            ``"daily"`` (default), ``"weekly"``, or ``"monthly"``.

        Returns
        -------
        dict
            ``{period, date_from, date_to, total_items, new_items,
            duplicate_items, domains, sources}``
        """
        return self.index.get_collection_stats(period=period)

    def get_collection_diff(
        self, since_collection_id: str
    ) -> dict[str, Any]:
        """Return entries collected since a previous collection ID.

        Parameters
        ----------
        since_collection_id:
            A collection ID to compare against (entries with
            ``collected_at > since_collection_id`` are returned).

        Returns
        -------
        dict
            ``{since_id, new_entries, count, domains}``
        """
        return self.index.get_collection_diff(
            since_collection_id=since_collection_id
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_entries(
        self,
        domain: str,
        tier: str | None = None,
        date_from: str | None = None,
        limit: int = 20,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fast listing from the SQLite index (with filesystem fallback).

        Falls back to scanning ``knowledge/<domain>/`` when the SQLite index
        is empty.  Returns entries sorted by ``collected_at DESC``.
        """
        entries = self.index.list_entries(
            domain, tier, date_from, limit, offset, user_id=user_id,
        )
        if entries:
            return entries
        # Fallback: scan filesystem
        fs_entries = self._scan_kb_filesystem(domain, tier=tier)
        if date_from:
            def _content_date(e: dict[str, Any]) -> str:
                return e.get("collected_at") or e.get("created_at") or ""
            fs_entries = [
                e for e in fs_entries
                if _content_date(e) >= date_from
            ]
        return fs_entries[offset: offset + limit]

    def list_all_entries(
        self,
        domain: str | None = None,
        tier: str | None = None,
        date_from: str | None = None,
        limit: int = 20,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entries across all domains (or a specific *domain*).

        When *domain* is ``None``, entries from every domain are
        returned.  Falls back to filesystem scan when SQLite index is empty.
        Otherwise behaves like :meth:`list_entries`.
        """
        entries = self.index.list_all_entries(
            domain=domain, tier=tier, date_from=date_from,
            limit=limit, offset=offset, user_id=user_id,
        )
        if entries:
            return entries
        # Fallback: scan filesystem
        kb_base = self.base_path
        if not kb_base.is_dir():
            return []
        if domain:
            fs_entries = self._scan_kb_filesystem(domain, tier=tier)
        else:
            fs_entries = []
            for child in sorted(kb_base.iterdir()):
                if not child.is_dir() or child.name.startswith("_"):
                    continue
                fs_entries.extend(self._scan_kb_filesystem(child.name, tier=tier))
            fs_entries.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
        if date_from:
            fs_entries = [
                e for e in fs_entries
                if e.get("collected_at", "") >= date_from
            ]
        return fs_entries[offset: offset + limit]

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Return full entry content from the Markdown file + SQLite metadata.

        The returned dict contains all SQLite columns plus the parsed
        ``content`` (body text from the Markdown file).
        Falls back to filesystem scan when the SQLite index has no match.
        Returns ``None`` if the entry is not found.
        """
        meta = self.index.get_entry(entry_id)
        if meta is None:
            # Fallback: scan filesystem for the entry
            kb_base = self.base_path
            if not kb_base.is_dir():
                return None
            fs_results = self._scan_kb_filesystem(
                domain="*", entry_id=entry_id,
            )
            if not fs_results:
                # Try each real domain directory
                for child in sorted(kb_base.iterdir()):
                    if not child.is_dir() or child.name.startswith("_"):
                        continue
                    fs_results = self._scan_kb_filesystem(
                        domain=child.name, entry_id=entry_id,
                    )
                    if fs_results:
                        break
            if not fs_results:
                return None
            meta = fs_results[0]

        file_path = Path(meta["file_path"]) if meta["file_path"] else None
        if file_path and file_path.is_file():
            raw = file_path.read_text(encoding="utf-8")
            content = _strip_frontmatter(raw)
            meta["content"] = content
            fm = _parse_frontmatter(raw)
            if fm:
                if not meta.get("cefr") and fm.get("cefr"):
                    meta["cefr"] = fm["cefr"]
                if fm.get("quality_flags"):
                    meta["quality_flags"] = fm["quality_flags"]
                cf = meta.get("custom_fields") or "{}"
                try:
                    cf_dict = json.loads(cf) if isinstance(cf, str) else dict(cf)
                except (json.JSONDecodeError, TypeError):
                    cf_dict = {}
                for k in ("author", "source_ids", "status", "related_concepts", "linked_entries"):
                    if k in fm and k not in cf_dict:
                        cf_dict[k] = fm[k]
                meta["custom_fields"] = json.dumps(cf_dict, ensure_ascii=False)
        else:
            meta["content"] = ""

        return meta

    def count_entries(self, domain: str | None = None) -> int:
        """Return the total number of entries, optionally filtered by domain."""
        return self.index.count_entries(domain)

    def get_entry_by_path(self, file_path: str) -> dict[str, Any] | None:
        """Look up an entry by its file path and return full content."""
        meta = self.index.search_by_field("file_path", file_path)
        if not meta:
            return None
        return self.get_entry(meta[0]["entry_id"])

    def get_entry_by_source_url(self, source_url: str) -> dict[str, Any] | None:
        """Return the full entry dict whose ``source_url`` exactly matches.

        Used by the output pipeline to link report-path agent entries
        (which hardcode ``entry_id: ""``) back to their KB entries by
        source URL (todo 24, output-quality-mega).
        """
        return self.index.get_entry_by_source_url(source_url)

    def delete_entry(
        self,
        entry_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Delete an entry by *entry_id* from the index, FTS5, and disk.

        Returns ``{"deleted": True, "entry_id": ..., "title": ...}`` on
        success, or ``{"deleted": False, "entry_id": ..., "error": ...}``
        when the entry does not exist.

        Raises
        ------
        DirectorOnlyError
            If the entry lives in the 03-Wiki tier and *actor* is not
            whitelisted in ``AUTOINFO_DIRECTOR_ACTORS``.
        """
        meta = self.index.get_entry(entry_id)
        if meta is None:
            return {
                "deleted": False,
                "entry_id": entry_id,
                "error": "Entry not found",
            }

        ok = self.index.delete_entry(entry_id, actor=actor)
        return {
            "deleted": ok,
            "entry_id": entry_id,
            "title": meta.get("title", ""),
        }

    # ------------------------------------------------------------------
    # Draft tier — agent-created entries from Raw
    # ------------------------------------------------------------------

    def create_kb_draft(
        self,
        raw_ids: list[str],
        title: str,
        summary: str = "",
        tags: list[str] | None = None,
    ) -> KBEntry:
        """Create a Draft entry from one or more Raw entries.

        Validates that all *raw_ids* exist in the 01-Raw tier, merges
        content from the source entries, and creates a file in
        ``02-Draft/<topic>/`` with ``tier: 02-Draft``.

        Parameters
        ----------
        raw_ids:
            One or more entry IDs that exist in the 01-Raw tier.
        title:
            Title for the new Draft entry.
        summary:
            Optional summary text.
        tags:
            Optional tags for the Draft entry.

        Returns
        -------
        KBEntry
            The newly created Draft entry.

        Raises
        ------
        ValueError
            If *raw_ids* is empty or any ID does not exist in 01-Raw.
        """
        if not raw_ids:
            raise ValueError("raw_ids must not be empty")

        tags = tags or []

        raw_entries: list[dict[str, Any]] = []
        domains: set[str] = set()
        topics: set[str] = set()

        for rid in raw_ids:
            entry = self.index.get_entry(rid)
            if entry is None:
                raise ValueError(
                    f"Raw entry '{rid}' not found in knowledge base"
                )
            if entry.get("tier", "01-Raw") != "01-Raw":
                raise ValueError(
                    f"Entry '{rid}' is not in 01-Raw tier "
                    f"(found: {entry.get('tier', 'unknown')})"
                )
            raw_entries.append(entry)

            fp = Path(entry["file_path"])
            # file_path: knowledge/<domain>/01-Raw/<topic>/<file>
            if len(fp.parts) >= 4:
                domains.add(fp.parts[-4])
                topics.add(fp.parts[-2])

        domain = domains.pop() if len(domains) == 1 else "default"
        topic = topics.pop() if len(topics) == 1 else "general"
        slug = _slugify(title)
        today_str = date.today().isoformat()

        entry_id = f"{domain}-draft-{slug}"

        # File path: knowledge/<domain>/02-Draft/<topic>/<YYYY-MM-DD>-<slug>.md
        file_dir = self.base_path / domain / "02-Draft" / topic
        file_name = f"{today_str}-{slug}.md"
        file_path = file_dir / file_name

        merged_body_parts: list[str] = []
        source_bodies: list[str] = []
        for i, re in enumerate(raw_entries):  # noqa: F402
            merged_body_parts.append(
                f"## Source {i + 1}: {re['title']}\n\n"
            )
            raw_fp = Path(re["file_path"])
            if raw_fp.is_file():
                raw_text = raw_fp.read_text(encoding="utf-8")
                body = _strip_frontmatter(raw_text)
                source_bodies.append(body)
                merged_body_parts.append(body)
            merged_body_parts.append("\n\n")

        merged_body = "".join(merged_body_parts)

        # Same 50-char floor the process/import write paths enforce: a Draft
        # built from a Raw entry whose content is below MIN_KB_CONTENT_CHARS
        # is an empty shell and must not be written (issue #279).
        if any(
            len(body.strip()) < self.min_content_chars for body in source_bodies
        ):
            raise ValueError(
                "draft content too short: a source Raw entry provides "
                f"fewer than {self.min_content_chars} characters"
            )

        # Build KBEntry
        source_raw_ids = ",".join(raw_ids)
        entry = KBEntry(  # type: ignore[assignment]
            entry_id=entry_id,
            title=title,
            domain=domain,
            tier="02-Draft",
            source_url=raw_entries[0].get("source_url", ""),
            source_type=raw_entries[0].get("source_type", ""),
            source_platform=raw_entries[0].get("source_platform", ""),
            collected_at=today_str,
            summary=summary,
            tags=tags,
            # Carry forward real gate scores from the first source Raw entry
            # (G1/G3-derived) instead of zeroing them (G-02 score-cleanup gap).
            quality_tier=int(raw_entries[0].get("quality_tier") or 1),
            relevance_score=float(raw_entries[0].get("relevance_score") or 0.0),
            source_score=float(raw_entries[0].get("source_score") or 0.0),
            dedup_status="unique",
            file_path=str(file_path),
            custom_fields={"source_raw_ids": source_raw_ids},
            # Expanded frontmatter fields
            source_ids=raw_ids,
            status="active",
            # Carry forward language from first raw entry
            language=raw_entries[0].get("language", ""),
        )

        # Write Markdown file
        file_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = _build_frontmatter(entry)  # type: ignore[arg-type]
        parts = [f"---\n{frontmatter}---\n\n"]
        parts.append(f"_Compiled from: {source_raw_ids}_\n\n")
        parts.append(merged_body)
        file_path.write_text("".join(parts), encoding="utf-8")

        # Index in SQLite
        self.index.index_entry(entry)  # type: ignore[arg-type]

        return entry  # type: ignore[return-value]

    def reject_kb_draft(
        self,
        draft_id: str,
        reason: str = "",
        action: str = "back_to_raw",
    ) -> dict[str, Any]:
        """Reject a Draft, moving it back to 01-Raw or archiving.

        Reads the file from 02-Draft/, adds ``rejection_reason`` to the
        frontmatter, and moves the file to 01-Raw/ (or archives it).

        Parameters
        ----------
        draft_id:
            Entry ID of the Draft to reject.
        reason:
            Optional human-readable reason for rejection.
        action:
            What to do with the file.  ``"back_to_raw"`` (default) moves
            it to the 01-Raw tier.  ``"archive"`` moves to
            ``_archive/<domain>/``.

        Returns
        -------
        dict
            Summary of the operation including old/new paths.
        """
        meta = self.index.get_entry(draft_id)
        if meta is None:
            raise ValueError(f"Draft entry '{draft_id}' not found")

        if meta.get("tier") != "02-Draft":
            raise ValueError(
                f"Entry '{draft_id}' is not a Draft (tier: {meta.get('tier', 'unknown')})"
            )

        file_path = Path(meta["file_path"])
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Draft file not found on disk: {file_path}"
            )

        raw_content = file_path.read_text(encoding="utf-8")

        if raw_content.startswith("---"):
            end = raw_content.find("---", 3)
            if end != -1:
                fm_text = raw_content[3:end]
                fm_data = yaml.safe_load(fm_text) or {}
                fm_data["rejection_reason"] = reason
                fm_data["rejected_at"] = datetime.now(timezone.utc).isoformat()
                new_fm = yaml.dump(
                    fm_data,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )
                body = raw_content[end + 3 :].lstrip("\n")
                raw_content = f"---\n{new_fm}---\n\n{body}"
            else:
                raw_content = (
                    f"---\nrejection_reason: {reason}\n---\n\n{raw_content}"
                )
        else:
            raw_content = (
                f"---\nrejection_reason: {reason}\n---\n\n{raw_content}"
            )

        if action == "back_to_raw":
            parts = list(file_path.parts)
            tier_idx = None
            for i, p in enumerate(parts):
                if p == "02-Draft":
                    tier_idx = i
                    break
            if tier_idx is not None:
                parts[tier_idx] = "01-Raw"
            new_path = Path(*parts)

            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(raw_content, encoding="utf-8")
            file_path.unlink()

            custom_fields_raw = meta.get("custom_fields") or "{}"
            draft_custom_fields: dict[str, Any] = json.loads(custom_fields_raw)

            entry = KBEntry(
                entry_id=draft_id,
                title=meta["title"],
                domain=meta["domain"],
                tier="01-Raw",
                source_url=meta.get("source_url", ""),
                source_type=meta.get("source_type", ""),
                source_platform=meta.get("source_platform", ""),
                collected_at=meta.get("collected_at", ""),
                summary=meta.get("summary", ""),
                tags=json.loads(meta.get("tags", "[]")),
                quality_tier=meta.get("quality_tier", 1),
                relevance_score=meta.get("relevance_score", 0.0),
                dedup_status=meta.get("dedup_status", "unique"),
                file_path=str(new_path),
                custom_fields=draft_custom_fields,
                author=draft_custom_fields.get("author", ""),
                source_ids=draft_custom_fields.get("source_ids", []),
                status=draft_custom_fields.get("status", "active"),
                related_concepts=draft_custom_fields.get("related_concepts", []),
                linked_entries=draft_custom_fields.get("linked_entries", []),
                language=meta.get("language", ""),
            )
            self.index.index_entry(entry)

            return {
                "status": "rejected",
                "action": action,
                "draft_id": draft_id,
                "old_path": str(file_path),
                "new_path": str(new_path),
                "reason": reason,
            }

        elif action == "archive":
            archive_dir = self.base_path / "_archive" / meta["domain"]
            archive_path = archive_dir / file_path.name
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path.write_text(raw_content, encoding="utf-8")
            file_path.unlink()

            with self.index._connect() as conn:
                conn.execute(
                    "DELETE FROM entries WHERE entry_id = ?", (draft_id,)
                )

            return {
                "status": "archived",
                "action": action,
                "draft_id": draft_id,
                "old_path": str(file_path),
                "new_path": str(archive_path),
                "reason": reason,
            }

        else:
            raise ValueError(
                f"Unknown action '{action}'. Use 'back_to_raw' or 'archive'."
            )

    @staticmethod
    def _entry_from_meta(meta: dict[str, Any]) -> KBEntry:
        """Rebuild a :class:`KBEntry` from an index meta dict.

        Used by the admission gate and the promotion path so the gate, the
        promoted record, and the raw-entry resolver all see identical data
        (scores, provenance, ``source_ids``).
        """
        custom_fields_raw = meta.get("custom_fields") or "{}"
        custom_fields: dict[str, Any] = json.loads(custom_fields_raw)
        return KBEntry(
            entry_id=meta["entry_id"],
            title=meta.get("title", ""),
            domain=meta.get("domain", ""),
            tier=meta.get("tier", "01-Raw"),
            source_url=meta.get("source_url", ""),
            source_type=meta.get("source_type", ""),
            source_platform=meta.get("source_platform", ""),
            collected_at=meta.get("collected_at", ""),
            summary=meta.get("summary", ""),
            tags=json.loads(meta.get("tags", "[]")),
            quality_tier=int(meta.get("quality_tier") or 1),
            relevance_score=float(meta.get("relevance_score") or 0.0),
            source_score=float(meta.get("source_score") or 0.0),
            dedup_status=meta.get("dedup_status", "unique"),
            file_path=meta.get("file_path", ""),
            custom_fields=custom_fields,
            author=custom_fields.get("author", ""),
            source_ids=custom_fields.get("source_ids", []),
            status=custom_fields.get("status", "active"),
            related_concepts=custom_fields.get("related_concepts", []),
            linked_entries=custom_fields.get("linked_entries", []),
            language=meta.get("language", ""),
        )

    def _resolve_raw_entry(self, raw_id: str) -> KBEntry | None:
        """Resolve a 01-Raw entry by id for the admission gate's provenance check.

        Returns ``None`` when the id does not exist or does not live in the
        01-Raw tier — the gate then reports the source as unresolvable.
        """
        meta = self.index.get_entry(raw_id)
        if meta is None or meta.get("tier") != "01-Raw":
            return None
        return self._entry_from_meta(meta)

    def _write_promotion_failed_marker(
        self, entry: KBEntry, reasons: list[RejectionReason]
    ) -> Path:
        """Write ``knowledge/_failed/<domain>/<entry_id>.md`` for a rejected promotion.

        Mirrors the collection/processing ``_failed/`` convention
        (``_failed/`` under a domain-scoped directory, diagnostics payload)
        while keeping the draft itself untouched in 02-Draft.
        """
        domain = entry.domain or "unknown"
        failed_dir = self.base_path / "_failed" / domain
        failed_dir.mkdir(parents=True, exist_ok=True)
        marker = failed_dir / f"{entry.entry_id}.md"
        reason_codes = [str(r) for r in reasons]
        frontmatter = yaml.dump(
            {
                "entry_id": entry.entry_id,
                "domain": domain,
                "tier": "02-Draft",
                "gate": "PromotionAdmission",
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "reasons": reason_codes,
                "item_snapshot": {
                    "id": entry.entry_id,
                    "title": entry.title,
                    "source_url": entry.source_url,
                    "source_type": entry.source_type,
                    "source_platform": entry.source_platform,
                    "draft_path": entry.file_path,
                },
            },
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
        body = (
            f"# Promotion rejected: {entry.entry_id}\n\n"
            "The admission gate rejected this 02-Draft entry; it was **not** "
            "moved to 03-Wiki and remains in 02-Draft.\n"
        )
        marker.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
        logger.warning(
            "Promotion rejected for %s (%s) — marker written to %s",
            entry.entry_id,
            ", ".join(reason_codes),
            marker,
        )
        return marker

    def promote_kb_draft(
        self,
        draft_id: str,
        *,
        config: Config | None = None,
        caller: str = "agent",
    ) -> dict[str, Any]:
        """Promote a Draft entry to the 03-Wiki tier (admission-gated agent promotion).

        Evaluates the promotion admission gate (:mod:`autoinfo.promotion` —
        provenance completeness, G0 schema re-check, G1/G3 thresholds, and
        the CurationGate G4 factual re-check) **before** touching the file.
        A rejected draft stays in ``02-Draft/`` and a
        ``_failed/<domain>/<entry_id>.md`` marker is written; the file is
        never moved or deleted.  On acceptance the frontmatter records
        ``promotion_source: agent`` / ``promoted_by`` / ``promoted_at`` and
        the file moves to ``03-Wiki/`` under the same domain and topic, with
        the SQLite index tier updated to ``03-Wiki``.

        Parameters
        ----------
        draft_id:
            Entry ID of the Draft to promote.
        config:
            Project configuration for gate thresholds; ``None`` uses the
            gate defaults (30/30, G4 enabled).
        caller:
            Actor performing the promotion, recorded in ``promoted_by``
            (default ``"agent"``).

        Returns
        -------
        dict
            Summary of the operation including old/new paths.

        Raises
        ------
        ValueError
            If *draft_id* is not found or not in the 02-Draft tier.
        FileNotFoundError
            If the Draft file is missing from disk.
        PromotionRejected
            If the admission gate rejects the draft; ``reasons`` carries
            the typed rejection codes and a ``_failed/`` marker is written.
        """
        meta = self.index.get_entry(draft_id)
        if meta is None:
            raise ValueError(f"Draft entry '{draft_id}' not found")

        if meta.get("tier") != "02-Draft":
            raise ValueError(
                f"Entry '{draft_id}' is not a Draft "
                f"(tier: {meta.get('tier', 'unknown')})"
            )

        file_path = Path(meta["file_path"])
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Draft file not found on disk: {file_path}"
            )

        # --- Admission gate (T2/T3): evaluate before any file movement ----
        entry = self._entry_from_meta(meta)
        admission = check_promotion_admission(
            entry,
            meta.get("domain", ""),
            config,
            resolve_raw=self._resolve_raw_entry,
        )
        if not admission.allowed:
            self._write_promotion_failed_marker(entry, admission.reasons)
            raise PromotionRejected(admission.reasons)

        return self._move_draft_to_wiki(meta, promotion_source="agent", caller=caller)

    def _move_draft_to_wiki(
        self,
        meta: dict[str, Any],
        *,
        promotion_source: str,
        caller: str,
    ) -> dict[str, Any]:
        """Rewrite the frontmatter with promotion provenance, move the
        02-Draft file to 03-Wiki under the same domain/topic, and re-index.

        Shared by :meth:`promote_kb_draft` (admission-gated agent promotion)
        and :meth:`force_promote_kb_draft` (director bypass).  No gate logic
        lives here — callers decide whether admission is required.
        """
        file_path = Path(meta["file_path"])
        raw_content = file_path.read_text(encoding="utf-8")

        now_iso = datetime.now(timezone.utc).isoformat()
        fm_data: dict[str, Any] = {}
        body = raw_content
        if raw_content.startswith("---"):
            end = raw_content.find("---", 3)
            if end != -1:
                fm_data = yaml.safe_load(raw_content[3:end]) or {}
                body = raw_content[end + 3 :].lstrip("\n")
        fm_data["promotion_source"] = promotion_source
        fm_data["promoted_by"] = caller
        fm_data["promoted_at"] = now_iso
        new_fm = yaml.dump(
            fm_data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
        raw_content = f"---\n{new_fm}---\n\n{body}"

        parts = list(file_path.parts)
        tier_idx = None
        for i, p in enumerate(parts):
            if p == "02-Draft":
                tier_idx = i
                break
        if tier_idx is not None:
            parts[tier_idx] = "03-Wiki"
        new_path = Path(*parts)

        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(raw_content, encoding="utf-8")
        file_path.unlink()

        promoted_entry = replace(
            self._entry_from_meta(meta),
            tier="03-Wiki",
            file_path=str(new_path),
            promotion_source=promotion_source,
            promoted_by=caller,
        )
        self.index.index_entry(promoted_entry)

        return {
            "status": "promoted",
            "draft_id": meta["entry_id"],
            "old_path": str(file_path),
            "new_path": str(new_path),
            "promoted_at": now_iso,
        }

    def promote_pending_drafts(
        self,
        domain: str,
        *,
        config: Config | None = None,
        caller: str = "sweep",
    ) -> dict[str, Any]:
        """Promote all eligible 02-Draft entries for *domain* (T6 sweep trigger).

        Batch promotion: lists every 02-Draft entry in the domain, skips
        entries that already carry a ``_failed/<domain>/<entry_id>.md``
        marker (previously rejected — **never retried**), and attempts the
        admission-gated promotion per entry via :meth:`promote_kb_draft`.
        Every per-entry attempt is isolated — a rejection or an unexpected
        failure never aborts the sweep.  Idempotent: already-promoted
        entries no longer live in 02-Draft, so a second sweep promotes
        nothing.

        Parameters
        ----------
        domain:
            Domain whose eligible 02-Draft entries are promoted.
        config:
            Project configuration for gate thresholds; ``None`` uses the
            gate defaults (30/30, G4 enabled).
        caller:
            Actor performing the promotions, recorded in ``promoted_by``
            (default ``"sweep"``).

        Returns
        -------
        dict
            Summary: ``{domain, total, promoted: [{entry_id, new_path}],
            rejected: [{entry_id, reasons}], failed: [{entry_id, error}],
            skipped_failed_markers: [entry_id]}``.
        """
        summary: dict[str, Any] = {
            "domain": domain,
            "total": 0,
            "promoted": [],
            "rejected": [],
            "failed": [],
            "skipped_failed_markers": [],
        }
        drafts = self.list_kb_tier(domain=domain, tier="02-Draft", limit=10000)
        summary["total"] = len(drafts)
        for draft in drafts:
            draft_id = draft.get("entry_id", "")
            if not draft_id:
                continue
            marker = self.base_path / "_failed" / domain / f"{draft_id}.md"
            if marker.is_file():
                summary["skipped_failed_markers"].append(draft_id)
                logger.info(
                    "Promotion sweep skip %s — previous admission failure "
                    "marker exists, not retried",
                    draft_id,
                )
                continue
            try:
                result = self.promote_kb_draft(
                    draft_id=draft_id, config=config, caller=caller
                )
                summary["promoted"].append(
                    {"entry_id": draft_id, "new_path": result.get("new_path", "")}
                )
            except PromotionRejected as exc:
                summary["rejected"].append(
                    {
                        "entry_id": draft_id,
                        "reasons": [str(r) for r in exc.reasons],
                    }
                )
            except (ValueError, FileNotFoundError) as exc:
                summary["failed"].append({"entry_id": draft_id, "error": str(exc)})
            except Exception as exc:  # never let one draft abort the sweep
                logger.exception("promotion sweep failed for %s", draft_id)
                summary["failed"].append({"entry_id": draft_id, "error": str(exc)})
        return summary

    # ------------------------------------------------------------------
    # Director backdoor — demotion & forced promotion (T5)
    # ------------------------------------------------------------------

    def force_promote_kb_draft(
        self,
        draft_id: str,
        *,
        caller: str = "director",
    ) -> dict[str, Any]:
        """Force-promote a 02-Draft entry to 03-Wiki, skipping the admission
        gate (director-only backdoor).

        The director bypasses :func:`autoinfo.promotion.check_promotion_admission`
        entirely — provenance, G0/G1/G3, and the CurationGate G4 re-check are
        not evaluated.  The frontmatter records ``promotion_source: director``
        / ``promoted_by`` / ``promoted_at`` and the file moves to ``03-Wiki/``
        under the same domain and topic, with the SQLite index tier updated.

        Parameters
        ----------
        draft_id:
            Entry ID of the Draft to force-promote.
        caller:
            Actor performing the promotion, recorded in ``promoted_by``
            (default ``"director"``).  Must be whitelisted in
            ``AUTOINFO_DIRECTOR_ACTORS``.

        Returns
        -------
        dict
            Summary of the operation including old/new paths.

        Raises
        ------
        DirectorOnlyError
            If *caller* is not whitelisted in ``AUTOINFO_DIRECTOR_ACTORS``.
        ValueError
            If *draft_id* is not found or not in the 02-Draft tier.
        FileNotFoundError
            If the Draft file is missing from disk.
        """
        if not is_director(caller):
            raise DirectorOnlyError(
                actor=caller, entry_id=draft_id, operation="force-promote"
            )

        meta = self.index.get_entry(draft_id)
        if meta is None:
            raise ValueError(f"Draft entry '{draft_id}' not found")

        if meta.get("tier") != "02-Draft":
            raise ValueError(
                f"Entry '{draft_id}' is not a Draft "
                f"(tier: {meta.get('tier', 'unknown')})"
            )

        file_path = Path(meta["file_path"])
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Draft file not found on disk: {file_path}"
            )

        return self._move_draft_to_wiki(meta, promotion_source="director", caller=caller)

    def demote_entry(
        self,
        entry_id: str,
        *,
        caller: str = "director",
    ) -> dict[str, Any]:
        """Demote a 03-Wiki entry back to 02-Draft (director-only backdoor).

        Content is fully preserved: the file moves from ``03-Wiki/`` to
        ``02-Draft/`` under the same domain and topic, frontmatter ``tier``
        is rewritten to ``02-Draft`` and a ``demoted_at`` timestamp (plus
        ``demoted_by``) is appended.  The original ``promotion_source`` /
        ``promoted_by`` provenance is kept so the promotion remains
        auditable, and the SQLite index tier is updated to ``02-Draft``.

        Parameters
        ----------
        entry_id:
            Entry ID of the 03-Wiki entry to demote.
        caller:
            Actor performing the demotion (default ``"director"``).  Must be
            whitelisted in ``AUTOINFO_DIRECTOR_ACTORS``.

        Returns
        -------
        dict
            Summary of the operation including old/new paths.

        Raises
        ------
        DirectorOnlyError
            If *caller* is not whitelisted in ``AUTOINFO_DIRECTOR_ACTORS``.
        ValueError
            If *entry_id* is not found or not in the 03-Wiki tier.
        FileNotFoundError
            If the Wiki file is missing from disk.
        """
        if not is_director(caller):
            raise DirectorOnlyError(
                actor=caller, entry_id=entry_id, operation="demote"
            )

        meta = self.index.get_entry(entry_id)
        if meta is None:
            raise ValueError(f"Entry '{entry_id}' not found")

        if meta.get("tier") != "03-Wiki":
            raise ValueError(
                f"Entry '{entry_id}' is not in 03-Wiki "
                f"(tier: {meta.get('tier', 'unknown')})"
            )

        file_path = Path(meta["file_path"])
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Wiki file not found on disk: {file_path}"
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        raw_content = file_path.read_text(encoding="utf-8")
        if raw_content.startswith("---"):
            end = raw_content.find("---", 3)
            if end != -1:
                fm_data = yaml.safe_load(raw_content[3:end]) or {}
                fm_data["tier"] = "02-Draft"
                fm_data["demoted_at"] = now_iso
                fm_data["demoted_by"] = caller
                new_fm = yaml.dump(
                    fm_data,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )
                body = raw_content[end + 3 :].lstrip("\n")
                raw_content = f"---\n{new_fm}---\n\n{body}"
            else:
                raw_content = (
                    f"---\ntier: 02-Draft\ndemoted_at: {now_iso}\n"
                    f"demoted_by: {caller}\n---\n\n{raw_content}"
                )
        else:
            raw_content = (
                f"---\ntier: 02-Draft\ndemoted_at: {now_iso}\n"
                f"demoted_by: {caller}\n---\n\n{raw_content}"
            )

        parts = list(file_path.parts)
        tier_idx = None
        for i, p in enumerate(parts):
            if p == "03-Wiki":
                tier_idx = i
                break
        if tier_idx is not None:
            parts[tier_idx] = "02-Draft"
        new_path = Path(*parts)

        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(raw_content, encoding="utf-8")
        file_path.unlink()

        demoted_entry = replace(
            self._entry_from_meta(meta),
            tier="02-Draft",
            file_path=str(new_path),
        )
        self.index.index_entry(demoted_entry)

        return {
            "status": "demoted",
            "entry_id": entry_id,
            "old_path": str(file_path),
            "new_path": str(new_path),
            "demoted_at": now_iso,
            "demoted_by": caller,
        }

    def list_kb_tier(
        self,
        domain: str,
        tier: str,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entries in a specific tier for a domain.

        Parameters
        ----------
        domain:
            Domain to filter by.
        tier:
            Tier to list (e.g. "01-Raw", "02-Draft").
        limit:
            Max entries (default 50).
        offset:
            Pagination offset.
        user_id:
            Optional user_id filter.

        Returns
        -------
        list[dict]
            Entries in the specified tier.
        """
        return self.index.list_entries_by_tier(domain, tier, limit, offset, user_id=user_id)

    def count_entries_by_tier(self, domain: str, tier: str) -> int:
        """Return entry count for *domain* and *tier*.

        Delegates to the underlying index — uses ``SELECT COUNT(*)``
        instead of fetching rows.
        """
        return self.index.count_entries_by_tier(domain, tier)

    # ------------------------------------------------------------------
    # Flag for KB inclusion
    # ------------------------------------------------------------------

    def flag_for_knowledge_base(
        self,
        summary_id: str,
        tags: list[str] | None = None,
        importance: int = 3,
    ) -> dict[str, Any]:
        """Flag an entry for KB inclusion.

        - Tags the entry in SQLite index (tags, importance)
        - Does **not** create a Draft -- agent must call
          ``create_kb_draft`` separately
        - Idempotent: calling again with same tags merges (no duplicates)

        Returns
        -------
        dict
            ``{flagged: true, entry_id, tags, importance}`` on success.
            ``{flagged: false, entry_id, error}`` when not found.
        """
        existing = self.index.get_entry(summary_id)
        if existing is None:
            return {
                "flagged": False,
                "entry_id": summary_id,
                "error": "Entry not found",
            }

        current_tags: list[str] = (
            json.loads(existing["tags"]) if existing.get("tags") else []
        )
        if tags:
            merged = list(dict.fromkeys(current_tags + tags))
        else:
            merged = current_tags

        self.index.update_entry_tags(summary_id, merged, importance)

        return {
            "flagged": True,
            "entry_id": summary_id,
            "tags": merged,
            "importance": importance,
        }

    def update_entry_metadata(self, entry_id: str, metadata: dict[str, Any]) -> bool:
        """Merge *metadata* into the entry's ``custom_fields`` JSON column.

        This is the KB metadata dict path: ``KBEntry.custom_fields`` ↔
        ``entries.custom_fields`` (SQLite JSON column), surfaced by
        :meth:`get_entry` / MCP ``get_kb_entry``.  The output pipeline
        uses it to persist product-derived analysis fields
        (``{"product_analysis": {...}}``) onto the KB entries a product
        output was generated from (todo 24, output-quality-mega).

        The merge is key-wise: keys in *metadata* overwrite existing keys
        of the same name; all other custom_fields keys are preserved.

        Returns ``True`` when the entry exists and was updated, ``False``
        when no entry with *entry_id* was found.
        """
        return self.index.update_entry_custom_fields(entry_id, metadata)

    # ------------------------------------------------------------------
    # Knowledge graph — entity & relation storage
    # ------------------------------------------------------------------

    def store_entities(
        self,
        entry_id: str,
        domain: str,
        entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Store extracted entities for an entry and discover relations.

        Calls through to :meth:`SQLiteIndex.index_entities` and
        :meth:`SQLiteIndex.discover_relations`.

        Parameters
        ----------
        entry_id:
            The KB entry these entities were extracted from.
        domain:
            Domain scope.
        entities:
            List of entity dicts with ``name`` and ``type`` keys.

        Returns
        -------
        dict
            ``{entities_indexed, relations_discovered, entry_id}``.
        """
        entity_names = [e.get("name", "").strip() for e in entities if e.get("name")]
        indexed = self.index.index_entities(entry_id, domain, entities)
        discovered = self.index.discover_relations(entry_id, domain, entity_names)
        return {
            "entities_indexed": indexed,
            "relations_discovered": discovered,
            "entry_id": entry_id,
        }

    def query_knowledge_graph(
        self,
        entity: str,
        relation: str = "related_to",
        domain: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Query the knowledge graph for entities related to *entity*.

        Dispatches to :meth:`SQLiteIndex.query_knowledge_graph`.

        Parameters
        ----------
        entity:
            Entity name to query (case-insensitive partial match).
        relation:
            Relation type filter (default ``"related_to"``).  Use ``""``
            for all relation types.
        domain:
            Optional domain scope filter.
        limit:
            Max results (default 20).

        Returns
        -------
        dict
            ``{entity, relation, domain, results, total_count}``.
        """
        return self.index.query_knowledge_graph(
            entity=entity,
            relation=relation,
            domain=domain,
            limit=limit,
        )

    def export_knowledge_graph(self, domain: str = "") -> dict[str, Any]:
        """Export the entire knowledge graph for the given *domain*.

        Parameters
        ----------
        domain:
            Domain filter.  When empty, exports all domains.

        Returns
        -------
        dict
            ``{domain, exported_at, entities: [...], relations: [...]}``.
        """
        entities = self.index.list_entities(domain=domain)
        relations = self.index.list_relations(domain=domain)
        return {
            "domain": domain or "*",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "relations": relations,
        }

    def get_summary(self, summary_id: str) -> dict[str, Any]:
        """Return full summary detail for an entry.

        Reads from the SQLite index **and** the Markdown file to
        assemble a comprehensive result including key points parsed
        from the body and quality flags from the YAML frontmatter.

        Returns
        -------
        dict
            Keys: ``entry_id``, ``title``, ``tl_dr``, ``key_points``,
            ``relevance_score``, ``quality_scores``,
            ``source_provenance``, ``tags``, ``importance``,
            ``file_path``.
            Returns ``{error, entry_id}`` when not found.
        """
        meta = self.get_entry(summary_id)
        if meta is None:
            return {"error": "Entry not found", "entry_id": summary_id}

        file_path = Path(meta["file_path"]) if meta["file_path"] else None
        content = ""
        quality_scores: dict[str, Any] = {}

        if file_path and file_path.is_file():
            raw = file_path.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end = raw.find("---", 3)
                if end != -1:
                    fm = yaml.safe_load(raw[3:end]) or {}
                    quality_scores = fm.get("quality_flags", {})
                    content = raw[end + 3 :].lstrip("\n")
                else:
                    content = raw
            else:
                content = raw
        else:
            content = meta.get("content", "")

        key_points = _extract_key_points(content)
        tags: list[str] = (
            json.loads(meta["tags"]) if meta.get("tags") else []
        )

        return {
            "entry_id": meta["entry_id"],
            "title": meta.get("title", ""),
            "tl_dr": meta.get("summary", ""),
            "key_points": key_points,
            "relevance_score": meta.get("relevance_score", 0),
            "quality_scores": quality_scores,
            "source_provenance": {
                "source_url": meta.get("source_url", ""),
                "source_type": meta.get("source_type", ""),
                "source_platform": meta.get("source_platform", ""),
                "collected_at": meta.get("collected_at", ""),
            },
            "tags": tags,
            "importance": meta.get("importance", 3),
            "file_path": meta.get("file_path", ""),
        }

    # ------------------------------------------------------------------
    # FTS5 search
    # ------------------------------------------------------------------

    def search_knowledge_base(
        self,
        query: str,
        domain: str = "",
        limit: int = 20,
        offset: int = 0,
        mode: str = "fts5",
        filter_tags: list[str] | None = None,
        filter_date_from: str | None = None,
        filter_date_to: str | None = None,
        filter_quality_tier_min: int | None = None,
        filter_quality_tier_max: int | None = None,
        filter_content_type: str | None = None,
        filter_language: str | None = None,
        filter_user_id: str | None = None,
        include_stale: bool = False,
        filter_custom_fields: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Search the knowledge base.

        Parameters
        ----------
        query:
            Search query string.
        domain:
            Optional domain filter.
        limit:
            Max results (default 20).
        offset:
            Pagination offset.
        mode:
            Search mode: ``"fts5"`` (default), ``"hybrid"`` (FTS5 + vector),
            or ``"vector"``.  Falls back to FTS5 when vector search is
            unavailable.
        filter_tags:
            Only include entries whose tags contain ANY of the given values.
        filter_date_from:
            Only entries with ``collected_at >=`` this ISO date.
        filter_date_to:
            Only entries with ``collected_at <=`` this ISO date.
        filter_quality_tier_min:
            Only entries with ``quality_tier >=`` this value.
        filter_quality_tier_max:
            Only entries with ``quality_tier <=`` this value.
        filter_content_type:
            Only entries with this exact ``content_type``.
        filter_language:
            Only entries with this exact ``language``.
        filter_user_id:
            Only entries with this exact ``user_id``.
            ``None`` means no filter (returns all).
        include_stale:
            If ``False`` (default), stale entries are demoted to the
            bottom of search results.  If ``True``, stale entries are
            mixed normally with fresh entries.
        filter_custom_fields:
            Faceted filter over the ``custom_fields`` JSON column (todo
            25, output-quality-mega — product-analysis metadata search).
            Each key is a dot-path into ``custom_fields`` (e.g.
            ``"product_analysis.action_required"``); an empty-string
            value matches entries where the field exists and is
            non-empty, any other value matches entries where the
            field's JSON value equals that text.  ``None`` applies no
            custom-fields filter (default behaviour unchanged).

        Returns
        -------
        dict
            ``{query, domain, entries, total_count, limit, offset, method}``.
            Each entry includes ``tier`` ("01-Raw"/"02-Draft"/"03-Wiki"),
            ``freshness_score`` and ``is_stale`` fields.
            Falls back to LIKE search if FTS5 syntax is invalid.
        """
        results = self.index.search_fts5(
            query=query,
            domain=domain,
            limit=limit,
            offset=offset,
            mode=mode,
            filter_tags=filter_tags,
            filter_date_from=filter_date_from,
            filter_date_to=filter_date_to,
            filter_quality_tier_min=filter_quality_tier_min,
            filter_quality_tier_max=filter_quality_tier_max,
            filter_content_type=filter_content_type,
            filter_language=filter_language,
            filter_user_id=filter_user_id,
            filter_custom_fields=filter_custom_fields,
        )

        # Resolve domain-specific TTL and freshness threshold from config.
        ttl_days = 90
        freshness_threshold = 0.5
        if domain:
            try:
                from autoinfo.config import get_config_path, load_config
                config_path = get_config_path()
                if config_path:
                    cfg = load_config(config_path)
                    for dc in cfg.domains:
                        if dc.name == domain:
                            ttl_days = dc.ttl_days
                            freshness_threshold = dc.freshness_threshold
                            break
            except Exception:
                pass

        entries = results.get("entries", [])
        scored_entries: list[dict[str, Any]] = []
        for entry in entries:
            freshness_score = calculate_freshness_score(entry, ttl_days)
            is_stale = freshness_score < freshness_threshold
            relevance_score = entry.get("relevance_score", 0.5) or 0.5
            combined_score = relevance_score * 0.8 + freshness_score * 0.2
            tier = entry.get("tier", "01-Raw")
            combined_score *= TIER_SCORE_BOOST.get(tier, 1.0)
            entry["tier"] = tier
            entry["freshness_score"] = round(freshness_score, 4)
            entry["is_stale"] = is_stale
            entry["combined_score"] = round(combined_score, 4)
            scored_entries.append(entry)

        # Demote stale entries when include_stale is False (default).
        # entry_id is the final tie-break so equal scores sort deterministically.
        if include_stale:
            scored_entries.sort(key=lambda e: (-e["combined_score"], e["entry_id"]))
        else:
            scored_entries.sort(
                key=lambda e: (e["is_stale"], -e["combined_score"], e["entry_id"])
            )

        for e in scored_entries:
            e.pop("combined_score", None)

        results["entries"] = scored_entries
        return results

    # ------------------------------------------------------------------
    # Wiki links (Obsidian-style [[links]])
    # ------------------------------------------------------------------

    def rebuild_wiki_links(self) -> dict[str, Any]:
        """Scan all KB entries for ``[[wiki link]]`` syntax and
        update the ``## Linked References`` sections.

        Two-pass: (1) build title→entry map + collect all ``[[Title]]`` references;
        (2) write/replace sections per entry (skipping 03-Wiki — append-only).
        Each section shows outgoing links and backlinks.
        Idempotent and no-op on entries without references.

        Returns ``{files_scanned, files_updated, wiki_links_found, backlinks_found}``.
        """
        from collections import defaultdict

        WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")  # noqa: N806
        SECTION_PATTERN = re.compile(  # noqa: N806
            r"\n## Linked References\n.*?(?=\n## |\Z)", re.DOTALL
        )

        stats: dict[str, Any] = {
            "files_scanned": 0,
            "files_updated": 0,
            "wiki_links_found": 0,
            "backlinks_found": 0,
        }

        all_entries: dict[str, dict[str, Any]] = {}
        title_map: dict[str, list[dict[str, str]]] = defaultdict(list)

        for md_file in sorted(self.base_path.rglob("*.md")):
            try:
                raw = md_file.read_text(encoding="utf-8")
                if not raw.startswith("---"):
                    continue
                end = raw.find("---", 3)
                if end == -1:
                    continue
                fm = yaml.safe_load(raw[3:end]) or {}
                entry_id = fm.get("entry_id", "")
                title = fm.get("title", "")
                if not entry_id or not title:
                    continue

                all_entries[entry_id] = {
                    "title": title,
                    "file_path": str(md_file),
                    "tier": fm.get("tier", "01-Raw"),
                    "fm_text": raw[3:end],
                    "body": raw[end + 3 :].lstrip("\n"),
                }

                key = title.lower().strip()
                title_map[key].append({
                    "entry_id": entry_id,
                    "title": title,
                    "tier": fm.get("tier", "01-Raw"),
                })
            except Exception as exc:
                logger.debug("Skipping %s: %s", md_file, exc)

        stats["files_scanned"] = len(all_entries)

        forward_map: dict[str, list[dict[str, str]]] = defaultdict(list)
        backlink_map: dict[str, list[dict[str, str]]] = defaultdict(list)

        for entry_id, info in all_entries.items():
            links = WIKI_LINK_RE.findall(info["body"])
            if not links:
                continue
            stats["wiki_links_found"] += len(links)

            for link_title in links:
                key = link_title.lower().strip()
                matches = title_map.get(key, [])
                for tm in matches:
                    if tm["entry_id"] == entry_id:
                        continue
                    forward_map[entry_id].append({
                        "wikilink": link_title,
                        "target_entry_id": tm["entry_id"],
                        "target_title": tm["title"],
                    })
                    backlink_map[tm["entry_id"]].append({
                        "source_entry_id": entry_id,
                        "source_title": info["title"],
                        "wikilink": link_title,
                    })

        stats["backlinks_found"] = sum(len(v) for v in backlink_map.values())

        for entry_id, info in all_entries.items():
            if info["tier"] == "03-Wiki":
                continue

            forwards = forward_map.get(entry_id, [])
            backwards = backlink_map.get(entry_id, [])

            if not forwards and not backwards:
                continue

            section_parts: list[str] = ["\n\n## Linked References\n"]
            if forwards:
                for f in forwards:
                    section_parts.append(
                        f"- [[{f['wikilink']}]] — linked to {f['target_entry_id']}\n"
                    )
            if backwards:
                if forwards:
                    section_parts.append("\n### Backlinks\n")
                for b in backwards:
                    section_parts.append(
                        f"- Referenced by [[{b['source_title']}]] ({b['source_entry_id']})\n"
                    )

            new_section = "".join(section_parts)
            body = info["body"]

            if SECTION_PATTERN.search(body):
                body = SECTION_PATTERN.sub(new_section, body)
            else:
                body = body.rstrip() + new_section

            new_content = f"---\n{info['fm_text']}---\n\n{body}"
            Path(info["file_path"]).write_text(new_content, encoding="utf-8")
            stats["files_updated"] += 1

        return stats

    def reindex_knowledge_base(self, domain: str | None = None) -> dict[str, Any]:
        """Walk knowledge/ and rebuild the FTS5 search index.

        Finds all ``.md`` files under ``knowledge/``, ensures each has
        a corresponding entry in the SQLite index, then rebuilds the
        FTS5 virtual table from the ``entries`` table.

        Parameters
        ----------
        domain:
            Optional domain to scope the reindex to.

        Returns
        -------
        dict
            ``{files_found, fts5_indexed, errors}``.
        """
        files_found = 0
        sync_errors: list[dict[str, Any]] = []

        search_root = self.base_path
        if domain:
            search_root = self.base_path / domain

        if not search_root.is_dir():
            return {
                "files_found": 0,
                "fts5_indexed": 0,
                "errors": [{"message": f"Directory not found: {search_root}"}],
            }

        for md_file in search_root.rglob("*.md"):
            try:
                raw = md_file.read_text(encoding="utf-8")
                if not raw.startswith("---"):
                    continue
                end = raw.find("---", 3)
                if end == -1:
                    continue
                fm = yaml.safe_load(raw[3:end])
                if not fm or "entry_id" not in fm:
                    continue

                entry_id = fm["entry_id"]
                existing = self.index.get_entry(entry_id)
                if existing is None:
                    entry = KBEntry(
                        entry_id=entry_id,
                        title=fm.get("title", ""),
                        domain=fm.get("domain", ""),
                        tier=fm.get("tier", "01-Raw"),
                        source_url=fm.get("source_url", ""),
                        source_type=fm.get("source_type", ""),
                        source_platform=fm.get("source_platform", ""),
                        collected_at=fm.get("collected_at", ""),
                        summary=fm.get("summary", ""),
                        tags=fm.get("tags", []),
                        quality_tier=fm.get("quality_tier", 1),
                        relevance_score=fm.get("relevance_score", 0.0),
                        dedup_status=fm.get("dedup_status", "unique"),
                        file_path=str(md_file),
                        # Expanded frontmatter fields (safe defaults if absent)
                        author=fm.get("author", ""),
                        source_ids=fm.get("source_ids", []),
                        status=fm.get("status", "active"),
                        related_concepts=fm.get("related_concepts", []),
                        linked_entries=fm.get("linked_entries", []),
                        quality_flags=fm.get("quality_flags", {}),
                        language=fm.get("language", ""),
                    )
                    self.index.index_entry(entry)
                files_found += 1
            except Exception as exc:
                sync_errors.append({
                    "file": str(md_file),
                    "error": str(exc),
                })

        fts5_count = self.index.reindex_fts5()

        return {
            "files_found": files_found,
            "fts5_indexed": fts5_count,
            "errors": sync_errors,
        }

    # ------------------------------------------------------------------
    # Soft-delete, restore, and GDPR user data management
    # ------------------------------------------------------------------

    def soft_delete_entry(
        self,
        entry_id: str,
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Mark an entry as deleted without removing it from disk.

        Sets ``deleted=1`` and ``deleted_at`` to the current UTC timestamp
        in both the SQLite index and the YAML frontmatter of the Markdown
        file.  The entry can be restored later with :meth:`restore_entry`.

        Returns ``{"deleted": True, "entry_id": ...}`` on success, or an
        error dict when the entry is not found.

        Raises
        ------
        DirectorOnlyError
            If the entry lives in the 03-Wiki tier and *actor* is not
            whitelisted in ``AUTOINFO_DIRECTOR_ACTORS`` (03-Wiki is
            append-only; only a director may soft-delete curated entries).
        """
        meta = self.index.get_entry(entry_id)
        if meta is None:
            return {
                "deleted": False,
                "entry_id": entry_id,
                "error": "Entry not found",
            }

        _ensure_wiki_delete_allowed(
            meta.get("tier", "01-Raw"), actor=actor, entry_id=entry_id
        )

        now = datetime.now(timezone.utc).isoformat()

        with self.index._connect() as conn:
            conn.execute(
                "UPDATE entries SET deleted = 1, deleted_at = ? WHERE entry_id = ?",
                (now, entry_id),
            )

        file_path = Path(meta["file_path"]) if meta.get("file_path") else None
        if file_path and file_path.is_file():
            raw = file_path.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end = raw.find("---", 3)
                if end != -1:
                    fm_data = yaml.safe_load(raw[3:end]) or {}
                    fm_data["deleted"] = True
                    fm_data["deleted_at"] = now
                    new_fm = yaml.dump(
                        fm_data,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                        width=120,
                    )
                    body = raw[end + 3:].lstrip("\n")
                    file_path.write_text(
                        f"---\n{new_fm}---\n\n{body}", encoding="utf-8"
                    )

        return {
            "deleted": True,
            "entry_id": entry_id,
            "title": meta.get("title", ""),
            "deleted_at": now,
        }

    def restore_entry(self, entry_id: str) -> dict[str, Any]:
        """Restore a soft-deleted entry.

        Removes the ``deleted`` and ``deleted_at`` flags from both the
        SQLite index and the YAML frontmatter.

        Returns ``{"restored": True, "entry_id": ...}`` on success, or an
        error dict when the entry is not deleted or not found.
        """
        meta = self.index.get_entry(entry_id)
        if meta is None:
            return {
                "restored": False,
                "entry_id": entry_id,
                "error": "Entry not found",
            }

        if not meta.get("deleted"):
            return {
                "restored": False,
                "entry_id": entry_id,
                "error": "Entry is not deleted",
            }

        with self.index._connect() as conn:
            conn.execute(
                "UPDATE entries SET deleted = 0, deleted_at = '' WHERE entry_id = ?",
                (entry_id,),
            )

        file_path = Path(meta["file_path"]) if meta.get("file_path") else None
        if file_path and file_path.is_file():
            raw = file_path.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end = raw.find("---", 3)
                if end != -1:
                    fm_data = yaml.safe_load(raw[3:end]) or {}
                    fm_data.pop("deleted", None)
                    fm_data.pop("deleted_at", None)
                    new_fm = yaml.dump(
                        fm_data,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                        width=120,
                    )
                    body = raw[end + 3:].lstrip("\n")
                    file_path.write_text(
                        f"---\n{new_fm}---\n\n{body}", encoding="utf-8"
                    )

        return {
            "restored": True,
            "entry_id": entry_id,
            "title": meta.get("title", ""),
        }

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        """Soft-delete all entries belonging to *user_id*.

        Iterates over every entry in the index with a matching ``user_id``
        and calls :meth:`soft_delete_entry` on each one.  This implements
        the "right to be forgotten" soft-deletion path — entries remain
        recoverable until the retention window expires.

        Returns a summary dict with the count of deleted entries.
        """
        with self.index._connect() as conn:
            rows = conn.execute(
                "SELECT entry_id FROM entries WHERE user_id = ?",
                (user_id,),
            ).fetchall()

        deleted_ids: list[str] = []
        errors: list[dict[str, Any]] = []

        for row in rows:
            result = self.soft_delete_entry(row["entry_id"])
            if result.get("deleted"):
                deleted_ids.append(row["entry_id"])
            else:
                errors.append(result)

        return {
            "deleted_count": len(deleted_ids),
            "deleted_entry_ids": deleted_ids,
            "errors": errors,
            "user_id": user_id,
        }

    def get_domain_decay(self, domain: str, ttl_days: int = 90) -> dict[str, Any]:
        """Compute decay / staleness metrics for a domain.

        Analyses all entries for *domain* and returns:
        - staleness_ratio (fraction of entries past TTL)
        - avg_ttl_remaining_days (TTL * (1 - staleness_ratio))
        - collection_freshness_days (days since most recent collection)
        - decay_grade (GREEN / YELLOW / RED based on ratio thresholds)
        - total_entries, stale_count, fresh_entries
        - suggestions based on decay grade
        """
        all_entries = self.index.list_entries(domain, limit=10000)
        if not all_entries:
            return {
                "staleness_ratio": 0.0,
                "avg_ttl_remaining_days": float(ttl_days),
                "collection_freshness_days": 0,
                "decay_grade": "GREEN",
                "total_entries": 0,
                "stale_count": 0,
                "fresh_entries": 0,
                "suggestions": ["No entries found for domain"],
            }

        total_entries = len(all_entries)
        stale_count = 0
        latest_collected: str | None = None

        now = datetime.now(timezone.utc)
        for entry in all_entries:
            if entry.get("deleted"):
                continue
            created_at = entry.get("collected_at") or entry.get("created_at") or ""
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at)
                    # Make naive datetimes UTC-aware (fixes naive-vs-aware
                    # subtraction crash for date-only collected_at values
                    # such as OpenAlex '2020-06-08').
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    age_days = (now - created_dt).days
                    is_stale = age_days >= ttl_days
                except (ValueError, TypeError):
                    is_stale = False
            else:
                is_stale = False
            if is_stale:
                stale_count += 1

            if created_at and (latest_collected is None or created_at > latest_collected):
                latest_collected = created_at

        fresh_entries = total_entries - stale_count
        staleness_ratio = stale_count / total_entries if total_entries > 0 else 0.0

        if latest_collected:
            try:
                latest_dt = datetime.fromisoformat(latest_collected)
                collection_freshness_days = (datetime.now(timezone.utc) - latest_dt).days
            except (ValueError, TypeError):
                collection_freshness_days = 0
        else:
            collection_freshness_days = 0

        if staleness_ratio > 0.5:
            decay_grade = "RED"
        elif staleness_ratio > 0.2:
            decay_grade = "YELLOW"
        else:
            decay_grade = "GREEN"

        avg_ttl_remaining_days = round(ttl_days * (1.0 - staleness_ratio), 1)

        suggestions: list[str] = []
        if decay_grade == "RED":
            suggestions.append("Consider reducing TTL or re-collecting domain")
        elif decay_grade == "YELLOW":
            suggestions.append("Monitor domain freshness")
        else:
            suggestions.append("Domain is healthy")

        return {
            "staleness_ratio": staleness_ratio,
            "avg_ttl_remaining_days": avg_ttl_remaining_days,
            "collection_freshness_days": collection_freshness_days,
            "decay_grade": decay_grade,
            "total_entries": total_entries,
            "stale_count": stale_count,
            "fresh_entries": fresh_entries,
            "suggestions": suggestions,
        }


# ---------------------------------------------------------------------------
# Internal helpers — frontmatter / body building
# ---------------------------------------------------------------------------


def _build_frontmatter(
    entry: KBEntry,
    quality_results: dict[str, QualityResult] | None = None,
    extraction: ExtractionResult | None = None,
) -> str:
    """Render YAML frontmatter for *entry*."""
    data: dict[str, Any] = {
        "title": entry.title,
        "domain": entry.domain,
        "tier": entry.tier,
        "entry_id": entry.entry_id,
        "source_url": entry.source_url,
        "source_type": entry.source_type,
        "source_platform": entry.source_platform,
        "collected_at": entry.collected_at,
        "summary": entry.summary,
        "tags": entry.tags,
        "quality_tier": entry.quality_tier,
        "relevance_score": entry.relevance_score,
        "dedup_status": entry.dedup_status,
        "source_score": entry.source_score,
        "language": entry.language,
        "user_id": entry.user_id,
        "version": entry.version,
        "previous_version": entry.previous_version,
        "supersedes": entry.supersedes,
        "trace_id": entry.trace_id,
    }

    # Expanded frontmatter fields (Draft+ tiers only — 01-Raw stays lean)
    if entry.tier != "01-Raw":
        data["author"] = entry.author
        data["source_ids"] = entry.source_ids
        data["status"] = entry.status
        data["related_concepts"] = entry.related_concepts
        data["linked_entries"] = entry.linked_entries
        # Promotion provenance is nullable — emit only when set
        if entry.promotion_source is not None:
            data["promotion_source"] = entry.promotion_source
        if entry.promoted_by is not None:
            data["promoted_by"] = entry.promoted_by

    # Include quality gate flags in frontmatter for transparency
    flags: dict[str, bool] = dict(entry.quality_flags)
    tos_compliant: bool | None = None
    tos_classification: str | None = None
    if quality_results:
        # quality_results overrides entry.quality_flags when provided
        for gname, gresult in quality_results.items():
            flags[gname] = gresult.flagged
        # Extract ToS compliance metadata from G1-TosCompliance gate
        g1tos = quality_results.get("G1-TosCompliance")
        if g1tos is not None:
            tos_compliant = bool(g1tos.details.get("tos_compliant"))
            tos_classification = str(g1tos.details.get("source_tos", "")) or None
    if flags:
        data["quality_flags"] = flags
    if tos_compliant is not None:
        data["tos_compliant"] = tos_compliant
    if tos_classification is not None:
        data["tos_classification"] = tos_classification

    # Include custom extracted fields in frontmatter
    if extraction and extraction.custom_fields:
        data["extracted_fields"] = extraction.custom_fields

    result: str = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    return result


def _build_body(
    item: Item,
    extraction: ExtractionResult | None = None,
) -> str:
    """Render the body of a KB entry Markdown file.

    Structure::

        ## Original Content
        <item.content>

        ## Summary
        <extraction.tl_dr>

        ## Key Points
        - <key_point_1>
        - <key_point_2>

    Issue #55: every text field is run through :func:`_decode_html_entities`
    so collector-residual entities never reach the stored/rendered surface.
    """
    parts: list[str] = []

    parts.append("## Original Content\n")
    parts.append(_decode_html_entities(str(item.content or "")))

    if extraction:
        if extraction.tl_dr:
            parts.append("\n\n## Summary\n")
            parts.append(_decode_html_entities(str(extraction.tl_dr)))

        if extraction.key_points:
            parts.append("\n\n## Key Points\n")
            for kp in extraction.key_points:
                parts.append(f"- {_decode_html_entities(str(kp))}\n")

        if extraction.entities:
            parts.append("\n\n## Entities\n")
            for ent in extraction.entities:
                name = _decode_html_entities(str(ent.get("name", "")))
                etype = ent.get("type", "")
                rel = ent.get("relevance", "")
                parts.append(f"- **{name}** ({etype}, relevance={rel})\n")

    return "".join("" if part is None else str(part) for part in parts)


def _strip_frontmatter(text: str) -> str:
    """Return the body text after the YAML frontmatter block (if any)."""
    # python-frontmatter is available in deps, but for a lightweight
    # approach we just strip the --- delimited block here.
    if text.startswith("---"):
        # Find the closing ---
        idx = text.find("---", 3)
        if idx != -1:
            return text[idx + 3 :].lstrip("\n")
    return text


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the YAML frontmatter of a Markdown file into a dict.

    Returns an empty dict when the file has no frontmatter or the YAML
    is malformed.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_key_points(content: str) -> list[str]:
    """Extract bullet-point key points from a KB entry body.

    Looks for a ``## Key Points`` section and parses lines starting
    with ``- `` as individual points.
    """
    match = re.search(r"## Key Points\n(.+?)(?:\n## |\Z)", content, re.DOTALL)
    if not match:
        return []
    points: list[str] = []
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        if line.startswith("- "):
            points.append(line[2:])
    return points


def update_frontmatter_field(file_path: str, key: str, value: Any) -> bool:
    """Add or update a single field in the YAML frontmatter of a Markdown file.

    Reads the file, parses the YAML frontmatter (between ``---`` markers),
    sets *key* to *value*, and writes the file back.

    Parameters
    ----------
    file_path:
        Path to the Markdown file.
    key:
        Frontmatter field name (e.g. ``"cefr"``).
    value:
        Value to set for the field.

    Returns
    -------
    bool
        ``True`` if the file was successfully modified.
    """
    fp = Path(file_path)
    if not fp.is_file():
        logger.warning("update_frontmatter_field: file not found — %s", file_path)
        return False

    raw = fp.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        logger.warning("update_frontmatter_field: no frontmatter in %s", file_path)
        return False

    end = raw.find("---", 3)
    if end == -1:
        logger.warning("update_frontmatter_field: malformed frontmatter in %s", file_path)
        return False

    fm_text = raw[3:end]
    try:
        fm_data: dict[str, Any] = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        logger.warning("update_frontmatter_field: invalid YAML in %s", file_path)
        return False

    fm_data[key] = value

    new_fm = yaml.dump(
        fm_data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    body = raw[end + 3 :].lstrip("\n")
    fp.write_text(f"---\n{new_fm}---\n\n{body}", encoding="utf-8")
    return True


def mark_stale(entry_id: str) -> dict[str, Any]:
    """Mark a KB entry as stale in its YAML frontmatter.

    Sets ``status: stale`` in the frontmatter.  Stale entries are
    demoted in search results and excluded from digest generation
    but are never deleted.

    Returns ``{"success": True, "entry_id": ...}`` on success, or an
    error dict when the entry is not found.
    """
    store = KBStore()
    meta = store.index.get_entry(entry_id)
    if meta is None:
        return {
            "success": False,
            "entry_id": entry_id,
            "error": "Entry not found",
        }

    file_path = meta.get("file_path", "")
    if file_path:
        ok = update_frontmatter_field(file_path, "status", "stale")
        return {"success": ok, "entry_id": entry_id}

    return {
        "success": False,
        "entry_id": entry_id,
        "error": "No file path for entry",
    }


def get_active_entries(domain: str) -> list[dict[str, Any]]:
    """Return entries for *domain* that are neither deleted nor stale.

    Filters out entries where:
    * The database ``deleted`` flag is set, or
    * The YAML frontmatter contains ``status: stale``.

    Returns a list of entry metadata dicts (same shape as
    :meth:`SQLiteIndex.list_entries`).
    """
    store = KBStore()
    all_entries = store.index.list_entries(domain, limit=10000)
    active: list[dict[str, Any]] = []

    for entry in all_entries:
        if entry.get("deleted"):
            continue
        file_path = entry.get("file_path", "")
        if file_path:
            fp = Path(file_path)
            if fp.is_file():
                raw = fp.read_text(encoding="utf-8")
                if raw.startswith("---"):
                    end = raw.find("---", 3)
                    if end != -1:
                        try:
                            fm = yaml.safe_load(raw[3:end]) or {}
                            if fm.get("status") == "stale":
                                continue
                        except yaml.YAMLError:
                            pass
        active.append(entry)

    return active
