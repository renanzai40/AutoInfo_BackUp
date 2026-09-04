"""Free-tier limits made configurable — schema, migration, config (todo 11).

Covers:
- Subscription model gains ``max_products`` / ``max_frequency`` / ``allow_custom``
- New DB → DDL columns present; old DB → ALTER TABLE migration adds the 3
  columns via ``_ensure_columns_exist`` WITHOUT losing existing rows
- Config dataclass gains a ``free_tier`` limits section with free-tier
  defaults (1 domain / 1 product / weekly / no custom), YAML round-trip
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from autoinfo.models import Subscription
from autoinfo.user_store import (
    create_subscription,
    init_db,
    list_subscriptions,
)

FREE_TIER_COLUMNS = {"max_products", "max_frequency", "allow_custom"}


@pytest.fixture
def user_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the user-store SQLite DB in a temp dir."""
    monkeypatch.setattr("autoinfo.user_store._DB_PATH", None)
    monkeypatch.setattr(
        "autoinfo.user_store._get_db_path", lambda: tmp_path / "users.db"
    )
    return tmp_path


def _subscription_columns(db_path: Path) -> set[str]:
    """Open the SQLite file directly and return the subscriptions column names."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA table_info(subscriptions)").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema: new DB → DDL
# ---------------------------------------------------------------------------


class TestNewDbSchema:
    def test_new_db_ddl_contains_free_tier_columns(self, user_db: Path) -> None:
        init_db()
        cols = _subscription_columns(user_db / "users.db")
        assert FREE_TIER_COLUMNS <= cols, (
            f"Expected free-tier columns in new-DB DDL, missing: "
            f"{FREE_TIER_COLUMNS - cols}"
        )


# ---------------------------------------------------------------------------
# Migration: old DB → ALTER TABLE
# ---------------------------------------------------------------------------

# Pre-change schema (exactly the subscriptions/user_profiles DDL before the
# free-tier columns were introduced).  Used to simulate an old database.
_LEGACY_DDL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    email          TEXT DEFAULT '',
    delivery_prefs TEXT DEFAULT '{}',
    status         TEXT DEFAULT 'trial',
    tier           TEXT DEFAULT 'free',
    created_at     TEXT DEFAULT '',
    updated_at     TEXT DEFAULT '',
    trial_start    TEXT DEFAULT '',
    trial_end      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS subscriptions (
    sub_id     TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    product_id TEXT DEFAULT '',
    status     TEXT DEFAULT 'active',
    start_date TEXT DEFAULT '',
    end_date   TEXT DEFAULT '',
    auto_renew INTEGER DEFAULT 1,
    tier       TEXT DEFAULT 'free',
    channels   TEXT DEFAULT '[]',
    domains    TEXT DEFAULT '[]',
    products   TEXT DEFAULT '[]',
    platform_limit  INTEGER DEFAULT 1,
    domain_limit    INTEGER DEFAULT 1,
    raw_access      INTEGER DEFAULT 0,
    processed_access INTEGER DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
);
"""


@pytest.fixture
def legacy_db(user_db: Path) -> Path:
    """Create an old-schema DB with one existing profile + subscription row."""
    db_path = user_db / "users.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_LEGACY_DDL)
        conn.execute(
            "INSERT INTO user_profiles (user_id, name, status, tier) "
            "VALUES ('legacy-user', 'Legacy User', 'active', 'free')"
        )
        conn.execute(
            "INSERT INTO subscriptions (sub_id, user_id, product_id, status, "
            "tier, domain_limit) "
            "VALUES ('sub_legacy01', 'legacy-user', 'free', 'active', 'free', 1)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


class TestOldDbMigration:
    def test_alter_adds_free_tier_columns(self, legacy_db: Path) -> None:
        assert not (FREE_TIER_COLUMNS & _subscription_columns(legacy_db))
        init_db()
        cols = _subscription_columns(legacy_db)
        assert FREE_TIER_COLUMNS <= cols, (
            f"ALTER migration must add {FREE_TIER_COLUMNS - cols}"
        )

    def test_alter_migration_preserves_existing_rows(self, legacy_db: Path) -> None:
        init_db()
        conn = sqlite3.connect(str(legacy_db))
        try:
            rows = conn.execute(
                "SELECT sub_id, user_id, product_id FROM subscriptions"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [("sub_legacy01", "legacy-user", "free")]

    def test_migration_idempotent_no_duplicate_columns(self, legacy_db: Path) -> None:
        init_db()
        cols_once = _subscription_columns(legacy_db)
        init_db()
        assert _subscription_columns(legacy_db) == cols_once

    def test_legacy_row_reads_back_with_free_tier_defaults(
        self, legacy_db: Path
    ) -> None:
        """Legacy row pre-dating the new columns reads back with free-tier defaults."""
        init_db()
        subs = list_subscriptions("legacy-user")
        assert len(subs) == 1
        sub = subs[0]
        assert sub.max_products == 1
        assert sub.max_frequency == "weekly"
        assert sub.allow_custom is False


# ---------------------------------------------------------------------------
# Model + create_subscription round-trip
# ---------------------------------------------------------------------------


class TestSubscriptionFreeTierFields:
    def test_model_defaults(self) -> None:
        sub = Subscription(subscription_id="sub_x", user_id="u1")
        assert sub.max_products == 1
        assert sub.max_frequency == "weekly"
        assert sub.allow_custom is False
        # Free-tier alignment: 1 domain / 1 product / weekly / no custom
        assert sub.domain_limit == 1

    def test_create_subscription_persists_free_tier_fields(self, user_db: Path) -> None:
        from autoinfo.user_store import create_profile

        create_profile(user_id="u-free", name="Free User", status="active")
        sub = create_subscription(
            user_id="u-free",
            plan="free",
            tier="free",
            max_products=1,
            max_frequency="weekly",
            allow_custom=False,
        )
        assert sub.max_products == 1
        assert sub.max_frequency == "weekly"
        assert sub.allow_custom is False

        stored = list_subscriptions("u-free")
        assert len(stored) == 1
        assert stored[0].max_products == 1
        assert stored[0].max_frequency == "weekly"
        assert stored[0].allow_custom is False

    def test_create_subscription_explicit_values_round_trip(self, user_db: Path) -> None:
        from autoinfo.user_store import create_profile

        create_profile(user_id="u-paid", name="Paid User", status="active")
        create_subscription(
            user_id="u-paid",
            plan="premium",
            tier="premium",
            max_products=8,
            max_frequency="daily",
            allow_custom=True,
        )
        stored = list_subscriptions("u-paid")[0]
        assert stored.max_products == 8
        assert stored.max_frequency == "daily"
        assert stored.allow_custom is True


# ---------------------------------------------------------------------------
# Config: free_tier section
# ---------------------------------------------------------------------------


class TestConfigFreeTierSection:
    def test_free_tier_defaults(self) -> None:
        from autoinfo.config import Config

        ft = Config().free_tier
        assert ft.max_domains == 1
        assert ft.max_products == 1
        assert ft.frequency == "weekly"
        assert ft.allow_custom is False

    def test_free_tier_yaml_round_trip(self, tmp_path: Path) -> None:
        from autoinfo.config import config_to_dict, load_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "project:\n  name: t\n"
            "free_tier:\n  max_domains: 2\n  max_products: 3\n"
            "  frequency: daily\n  allow_custom: true\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert cfg.free_tier.max_domains == 2
        assert cfg.free_tier.max_products == 3
        assert cfg.free_tier.frequency == "daily"
        assert cfg.free_tier.allow_custom is True

        dumped = config_to_dict(cfg)
        assert dumped["free_tier"] == {
            "max_domains": 2,
            "max_products": 3,
            "frequency": "daily",
            "allow_custom": True,
        }

    def test_free_tier_defaults_when_section_missing(self, tmp_path: Path) -> None:
        from autoinfo.config import load_config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("project:\n  name: t\n", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.free_tier.max_domains == 1
        assert cfg.free_tier.max_products == 1
        assert cfg.free_tier.frequency == "weekly"
        assert cfg.free_tier.allow_custom is False
