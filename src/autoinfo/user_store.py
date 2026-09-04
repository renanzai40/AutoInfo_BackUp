"""SQLite-backed storage for UserProfile and Subscription.

Tables are created lazily on first access.  All public functions call
:func:`init_db` before any operation so the caller never needs to
worry about schema bootstrapping.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autoinfo.models import Subscription, UserProfile

logger = logging.getLogger(__name__)

# Allowed values for the end-user ``content_preference`` preference
# (B-001 launch blocker; spec: docs/dev/specs/user-lifecycle-definition.md §2.3).
CONTENT_PREFERENCE_VALUES: frozenset[str] = frozenset(
    {"raw_only", "processed_only", "both"}
)
CONTENT_PREFERENCE_DEFAULT: str = "both"

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.cwd() / ".autoinfo" / "users.db"
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create tables if they do not already exist.

    Idempotent — safe to call on every request.
    """
    with _connect() as conn:
        conn.executescript("""
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
                max_products    INTEGER DEFAULT 1,
                max_frequency   TEXT DEFAULT 'weekly',
                allow_custom    INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
            );
        """)
    _ensure_columns_exist()


def _ensure_columns_exist() -> None:
    """Add missing columns to existing tables.

    Handles both ``user_profiles`` and ``subscriptions`` tables by
    checking for missing columns via ``PRAGMA table_info`` and adding
    them with ``ALTER TABLE``.
    """
    user_cols: list[tuple[str, str]] = [
        ("trial_started_at", "TEXT DEFAULT ''"),
        ("trial_days", "INTEGER DEFAULT 14"),
        ("preferences", "TEXT DEFAULT '{}'"),
        ("stripe_customer_id", "TEXT DEFAULT ''"),
        ("stripe_subscription_id", "TEXT DEFAULT ''"),
    ]
    sub_cols: list[tuple[str, str]] = [
        ("tier", "TEXT DEFAULT 'free'"),
        ("channels", "TEXT DEFAULT '[]'"),
        ("domains", "TEXT DEFAULT '[]'"),
        ("products", "TEXT DEFAULT '[]'"),
        ("platform_limit", "INTEGER DEFAULT 1"),
        ("domain_limit", "INTEGER DEFAULT 1"),
        ("raw_access", "INTEGER DEFAULT 0"),
        ("processed_access", "INTEGER DEFAULT 1"),
        ("max_products", "INTEGER DEFAULT 1"),
        ("max_frequency", "TEXT DEFAULT 'weekly'"),
        ("allow_custom", "INTEGER DEFAULT 0"),
    ]

    with _connect() as conn:
        for table, col_list in [("user_profiles", user_cols), ("subscriptions", sub_cols)]:
            existing = {
                row[1]
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            for col_name, col_def in col_list:
                if col_name not in existing:
                    try:
                        conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                        )
                        logger.info(
                            "Added column '%s' to %s table", col_name, table
                        )
                    except sqlite3.OperationalError:
                        logger.warning(
                            "Could not add column '%s' to %s (may already exist)",
                            col_name,
                            table,
                        )


# ---------------------------------------------------------------------------
# Row → model helpers
# ---------------------------------------------------------------------------


def _row_to_profile(row: sqlite3.Row) -> UserProfile:
    data = dict(row)

    # Map delivery_prefs (DB) → delivery_preferences (model)
    raw_prefs = data.pop("delivery_prefs", "{}")
    try:
        data["delivery_preferences"] = (
            json.loads(raw_prefs) if isinstance(raw_prefs, str) else raw_prefs
        )
    except (json.JSONDecodeError, TypeError):
        data["delivery_preferences"] = {}

    # Map trial_start (legacy DB) → trial_started_at (model)
    if "trial_start" in data:
        if "trial_started_at" not in data or not data["trial_started_at"]:
            data["trial_started_at"] = data.pop("trial_start")
        else:
            data.pop("trial_start")

    # Map trial_end (legacy DB) → trial_ends_at (model)
    if "trial_end" in data:
        if "trial_ends_at" not in data or not data["trial_ends_at"]:
            data["trial_ends_at"] = data.pop("trial_end")
        else:
            data.pop("trial_end")

    # Parse preferences JSON
    raw_preferences = data.get("preferences", "{}")
    if isinstance(raw_preferences, str):
        try:
            data["preferences"] = json.loads(raw_preferences)
        except (json.JSONDecodeError, TypeError):
            data["preferences"] = {}
    elif raw_preferences is None:
        data["preferences"] = {}

    # Coerce trial_days to int
    trial_days = data.get("trial_days", 14)
    try:
        data["trial_days"] = int(trial_days) if trial_days is not None else 14
    except (ValueError, TypeError):
        data["trial_days"] = 14

    # Filter to known UserProfile fields only
    from autoinfo.models import UserProfile

    valid_fields = set(UserProfile.__dataclass_fields__.keys())
    data = {k: v for k, v in data.items() if k in valid_fields}

    return UserProfile(**data)


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    data = dict(row)

    # Map SQL column names → dataclass field names
    col_map = {
        "sub_id": "subscription_id",
        "product_id": "plan",
    }
    for db_col, model_field in col_map.items():
        if db_col in data:
            data[model_field] = data.pop(db_col)

    # Coerce bool fields
    data["auto_renew"] = bool(data.get("auto_renew", True))
    data["raw_access"] = bool(data.get("raw_access", False))
    data["processed_access"] = bool(data.get("processed_access", True))
    data["allow_custom"] = bool(data.get("allow_custom", False))

    # Coerce int fields
    for int_col in ("platform_limit", "domain_limit", "max_products"):
        val = data.get(int_col, 1)
        try:
            data[int_col] = int(val) if val is not None else 1
        except (ValueError, TypeError):
            data[int_col] = 1

    # Coerce max_frequency
    if not data.get("max_frequency"):
        data["max_frequency"] = "weekly"

    # Parse JSON list fields
    for json_col in ("channels", "domains", "products"):
        raw = data.get(json_col, "[]")
        if isinstance(raw, str):
            try:
                data[json_col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data[json_col] = []
        elif raw is None:
            data[json_col] = []

    # Parse features JSON
    raw_features = data.get("features", "{}")
    if isinstance(raw_features, str):
        try:
            data["features"] = json.loads(raw_features)
        except (json.JSONDecodeError, TypeError):
            data["features"] = {}
    elif raw_features is None:
        data["features"] = {}

    # Filter to known Subscription fields only
    valid_fields = set(Subscription.__dataclass_fields__.keys())
    data = {k: v for k, v in data.items() if k in valid_fields}

    return Subscription(**data)


# ---------------------------------------------------------------------------
# UserProfile CRUD
# ---------------------------------------------------------------------------


def create_profile(
    user_id: str,
    name: str,
    email: str = "",
    delivery_prefs: dict[str, Any] | None = None,
    status: str = "trial",
    tier: str = "free",
) -> UserProfile:
    """Insert a new user profile.

    When *status* is ``"trial"``, ``trial_start`` is set to now and
    ``trial_end`` is set to 14 days later.

    Raises :class:`sqlite3.IntegrityError` if *user_id* already exists.
    """
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    trial_start = now if status == "trial" else ""
    trial_end = (
        (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        if status == "trial"
        else ""
    )
    profile = UserProfile(
        user_id=user_id,
        name=name,
        email=email,
        delivery_preferences=delivery_prefs or {},
        status=status,
        tier=tier,
        created_at=now,
        updated_at=now,
        trial_started_at=trial_start,
        trial_ends_at=trial_end,
        trial_days=14,
        preferences={},
    )
    with _connect() as conn:
        conn.execute(
            """INSERT INTO user_profiles
               (user_id, name, email, delivery_prefs, status, tier,
                created_at, updated_at, trial_start, trial_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile.user_id,
                profile.name,
                profile.email,
                json.dumps(profile.delivery_preferences),
                profile.status,
                profile.tier,
                profile.created_at,
                profile.updated_at,
                profile.trial_started_at,
                profile.trial_ends_at,
            ),
        )
    return profile


def get_profile(user_id: str) -> UserProfile | None:
    """Return a user profile by *user_id*, or ``None``."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
    return _row_to_profile(row) if row is not None else None


def update_profile(
    user_id: str,
    name: str | None = None,
    email: str | None = None,
    delivery_prefs: dict[str, Any] | None = None,
    status: str | None = None,
    tier: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> UserProfile | None:
    """Update fields on an existing user profile.

    Only the provided fields are changed.  Returns the updated profile,
    or ``None`` if *user_id* does not exist.
    """
    init_db()
    existing = get_profile(user_id)
    if existing is None:
        return None

    now = datetime.now(timezone.utc).isoformat()
    new_name = name if name is not None else existing.name
    new_email = email if email is not None else existing.email
    new_prefs = delivery_prefs if delivery_prefs is not None else existing.delivery_preferences
    new_status = status if status is not None else existing.status
    new_tier = tier if tier is not None else existing.tier
    new_stripe_customer = (
        stripe_customer_id
        if stripe_customer_id is not None
        else existing.stripe_customer_id
    )
    new_stripe_subscription = (
        stripe_subscription_id
        if stripe_subscription_id is not None
        else existing.stripe_subscription_id
    )

    with _connect() as conn:
        conn.execute(
            """UPDATE user_profiles
               SET name=?, email=?, delivery_prefs=?, status=?, tier=?,
                   stripe_customer_id=?, stripe_subscription_id=?, updated_at=?
               WHERE user_id=?""",
            (
                new_name,
                new_email,
                json.dumps(new_prefs),
                new_status,
                new_tier,
                new_stripe_customer,
                new_stripe_subscription,
                now,
                user_id,
            ),
        )

    # Return fresh data
    return get_profile(user_id)


def delete_profile(user_id: str) -> bool:
    """Delete a user profile by *user_id*.

    Also deletes associated subscriptions (CASCADE emulated via explicit
    delete).  Returns ``True`` if a row was removed.
    """
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        cursor = conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0


def list_profiles() -> list[UserProfile]:
    """Return all user profiles ordered by creation date (newest first)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM user_profiles ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_profile(r) for r in rows]


# ---------------------------------------------------------------------------
# Stripe customer ID persistence (replaces volatile billing._user_stripe_map)
# ---------------------------------------------------------------------------


def set_stripe_customer_id(user_id: str, customer_id: str) -> None:
    """Persist *customer_id* to the user profile in the DB.

    Thin wrapper around :func:`update_profile` that only touches
    ``stripe_customer_id``.  Thread-safe via SQLite transaction.

    Raises :class:`ValueError` if *user_id* does not exist.
    """
    init_db()
    result = update_profile(user_id=user_id, stripe_customer_id=customer_id)
    if result is None:
        raise ValueError(
            f"Cannot set stripe_customer_id: user '{user_id}' not found"
        )


def get_stripe_customer_id(user_id: str) -> str | None:
    """Retrieve the persisted ``stripe_customer_id`` from the DB.

    Returns ``None`` if *user_id* does not exist or has no customer ID.
    """
    init_db()
    profile = get_profile(user_id)
    if profile is None:
        return None
    return profile.stripe_customer_id or None


def list_stripe_customer_ids() -> dict[str, str]:
    """Return all non-empty stripe_customer_id mappings from the DB.

    Useful for backfilling the in-memory cache on startup.
    """
    init_db()
    result: dict[str, str] = {}
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, stripe_customer_id FROM user_profiles "
            "WHERE stripe_customer_id IS NOT NULL AND stripe_customer_id != ''"
        ).fetchall()
    for row in rows:
        result[row["user_id"]] = row["stripe_customer_id"]
    return result


# ---------------------------------------------------------------------------
# Trial management — Task 14
# ---------------------------------------------------------------------------


def activate_trial(
    end_user_id: str,
    days: int = 14,
) -> dict[str, Any]:
    """Activate or reset the trial period for an end user.

    Sets ``trial_started_at`` to now and ``trial_days`` to the
    requested duration.  Also moves the user to ``status="trial"``
    when they are not currently ``active``.
    """
    init_db()
    profile = get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": "NotFound",
            "message": f"End-user '{end_user_id}' not found",
            "actionable": True,
        }

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    trial_ends = (now_dt + timedelta(days=days)).isoformat()

    new_status = profile.status
    if profile.status != "active":
        new_status = "trial"

    with _connect() as conn:
        conn.execute(
            """UPDATE user_profiles
               SET trial_started_at=?, trial_days=?, trial_end=?,
                   status=?, updated_at=?
               WHERE user_id=?""",
            (now, days, trial_ends, new_status, now, end_user_id),
        )

    try:
        from autoinfo.audit import append_audit_log

        append_audit_log(
            actor="system",
            action="activate_trial",
            resource_type="user_profile",
            resource_id=end_user_id,
            details={"trial_days": days, "trial_started_at": now},
        )
    except Exception:
        logger.warning(
            "Failed to write audit log for trial activation '%s'",
            end_user_id,
            exc_info=True,
        )

    return {
        "success": True,
        "trial_started_at": now,
        "trial_ends_at": trial_ends,
        "trial_days": days,
        "status": new_status,
    }


def check_trial_expiry(end_user_id: str) -> dict[str, Any]:
    """Check the trial status for an end user.

    Computes ``days_remaining`` from the user's ``trial_started_at``
    and ``trial_days``.  Status is ``"expired"``, ``"active"``, or
    ``"no_trial"``.
    """
    init_db()
    profile = get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": "NotFound",
            "message": f"End-user '{end_user_id}' not found",
            "actionable": True,
        }

    trial_started = profile.trial_started_at
    trial_days = profile.trial_days

    if not trial_started or trial_days <= 0:
        return {
            "days_remaining": 0,
            "status": "no_trial",
            "trial_started_at": trial_started,
            "trial_days": trial_days,
        }

    try:
        started_dt = datetime.fromisoformat(trial_started)
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return {
            "days_remaining": 0,
            "status": "no_trial",
            "trial_started_at": trial_started,
            "trial_days": trial_days,
        }

    elapsed = datetime.now(timezone.utc) - started_dt
    total_seconds = trial_days * 86400
    remaining_seconds = int(total_seconds - elapsed.total_seconds())
    days_remaining = max(0, remaining_seconds // 86400)

    status = "expired" if days_remaining <= 0 else "active"

    return {
        "days_remaining": days_remaining,
        "status": status,
        "trial_started_at": trial_started,
        "trial_days": trial_days,
    }


# ---------------------------------------------------------------------------
# Preferences management — Task 16
# ---------------------------------------------------------------------------


def resolve_content_preference(preferences: dict[str, Any] | None) -> str:
    """Return the effective ``content_preference`` from stored preferences.

    Defaults to ``"both"`` when the key is missing or holds an invalid
    value, so already-stored preference dicts that predate the field
    (and callers that never set it) keep the pre-B-001 behavior.
    """
    raw = (preferences or {}).get("content_preference")
    if raw in CONTENT_PREFERENCE_VALUES:
        return raw
    return CONTENT_PREFERENCE_DEFAULT


def update_preferences(
    end_user_id: str,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Merge *preferences* into the stored preferences for an end user.

    Deep-merges on top of existing preferences so callers only need
    to pass the keys they want to change (e.g. ``format``,
    ``delivery_channel``, ``timezone``, ``max_items``).

    Validates ``content_preference`` when present: only ``"raw_only"``,
    ``"processed_only"`` or ``"both"`` are accepted.  An invalid value
    rejects the whole update with the standard error envelope and
    nothing is persisted.
    """
    init_db()
    profile = get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": "NotFound",
            "message": f"End-user '{end_user_id}' not found",
            "actionable": True,
        }

    invalid_cp = (
        "content_preference" in preferences
        and preferences["content_preference"] not in CONTENT_PREFERENCE_VALUES
    )
    if invalid_cp:
        from autoinfo.mcp.errors import ErrorCode, error_response  # noqa: PLC0415

        return error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message=(
                f"Invalid content_preference "
                f"'{preferences['content_preference']}'. "
                f"Must be one of: {', '.join(sorted(CONTENT_PREFERENCE_VALUES))}"
            ),
            actionable=True,
        )

    existing = profile.preferences or {}
    merged = {**existing, **preferences}

    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE user_profiles SET preferences=?, updated_at=? WHERE user_id=?",
            (json.dumps(merged), now, end_user_id),
        )

    return {
        "success": True,
        "user_id": end_user_id,
        "preferences": merged,
    }


def get_preferences(end_user_id: str) -> dict[str, Any]:
    """Return stored preferences for an end user."""
    init_db()
    profile = get_profile(end_user_id)
    if profile is None:
        return {
            "error_code": "NotFound",
            "message": f"End-user '{end_user_id}' not found",
            "actionable": True,
        }

    return {
        "user_id": end_user_id,
        "preferences": profile.preferences or {},
    }


# ---------------------------------------------------------------------------
# Subscription CRUD (basic — expanded in later phases)
# ---------------------------------------------------------------------------


def create_subscription(
    user_id: str,
    plan: str = "free",
    status: str = "active",
    start_date: str = "",
    end_date: str = "",
    auto_renew: bool = True,
    tier: str = "free",
    channels: list[str] | None = None,
    domains: list[str] | None = None,
    products: list[str] | None = None,
    platform_limit: int = 1,
    domain_limit: int = 1,
    raw_access: bool = False,
    processed_access: bool = True,
    max_products: int = 1,
    max_frequency: str = "weekly",
    allow_custom: bool = False,
) -> Subscription:
    """Create a new subscription for a user."""
    init_db()
    import uuid

    sub = Subscription(
        subscription_id="sub_" + str(uuid.uuid4())[:12],
        user_id=user_id,
        plan=plan,
        status=status,
        start_date=start_date or datetime.now(timezone.utc).isoformat(),
        end_date=end_date,
        auto_renew=auto_renew,
        tier=tier,
        channels=channels or [],
        domains=domains or [],
        products=products or [],
        platform_limit=platform_limit,
        domain_limit=domain_limit,
        raw_access=raw_access,
        processed_access=processed_access,
        max_products=max_products,
        max_frequency=max_frequency,
        allow_custom=allow_custom,
    )
    with _connect() as conn:
        conn.execute(
            """INSERT INTO subscriptions
               (sub_id, user_id, product_id, status, start_date, end_date, auto_renew,
                tier, channels, domains, products,
                platform_limit, domain_limit, raw_access, processed_access,
                max_products, max_frequency, allow_custom)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sub.subscription_id,
                sub.user_id,
                sub.plan,
                sub.status,
                sub.start_date,
                sub.end_date,
                int(sub.auto_renew),
                sub.tier,
                json.dumps(sub.channels),
                json.dumps(sub.domains),
                json.dumps(sub.products),
                sub.platform_limit,
                sub.domain_limit,
                int(sub.raw_access),
                int(sub.processed_access),
                sub.max_products,
                sub.max_frequency,
                int(sub.allow_custom),
            ),
        )
    return sub


def list_subscriptions(user_id: str | None = None) -> list[Subscription]:
    """List subscriptions, optionally filtered by *user_id*."""
    init_db()
    with _connect() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY start_date DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM subscriptions ORDER BY start_date DESC"
            ).fetchall()
    return [_row_to_subscription(r) for r in rows]


# ---------------------------------------------------------------------------
# F38 — End User Lifecycle State Machine
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "trial": ["active", "cancelled"],
    "active": ["suspended", "cancelled"],
    "suspended": ["active", "cancelled"],
    "cancelled": [],
}
"""Valid status transitions for the end-user lifecycle.

Diagram::

    trial ──→ active ⇄ suspended
       │          │         │
       └─→ cancelled ←────┘
"""


def transition_end_user(
    user_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Transition an end-user's status with lifecycle validation.

    Valid transitions (per :data:`_VALID_TRANSITIONS`):

    - ``trial → active``, ``trial → cancelled``
    - ``active → suspended``, ``active → cancelled``
    - ``suspended → active``, ``suspended → cancelled``
    - ``cancelled →`` *(none — terminal state)*

    Each transition is logged to the immutable audit log via
    :func:`autoinfo.audit.append_audit_log`.

    Parameters
    ----------
    user_id:
        The end-user to transition.
    new_status:
        Target status.

    Returns
    -------
    dict
        ``{success, user_id, from_status, to_status, trial_start, trial_end}``
        on success, or an error dict with ``error_code`` and ``message``.
    """
    init_db()
    profile = get_profile(user_id)
    if profile is None:
        return {
            "error_code": "NotFound",
            "message": f"End-user '{user_id}' not found",
            "actionable": True,
        }

    old_status = profile.status

    if old_status == new_status:
        return {
            "error_code": "NoOp",
            "message": f"End-user '{user_id}' already has status '{new_status}'",
            "actionable": True,
        }

    allowed = _VALID_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        terminal = "(none — terminal state)" if not allowed else ", ".join(allowed)
        return {
            "error_code": "InvalidTransition",
            "message": (
                f"Cannot transition end-user '{user_id}' from "
                f"'{old_status}' to '{new_status}'. "
                f"Valid transitions from '{old_status}': {terminal}"
            ),
            "actionable": True,
        }

    now = datetime.now(timezone.utc).isoformat()
    trial_start = profile.trial_started_at or ""
    trial_end = profile.trial_ends_at or ""

    if old_status == "trial" and new_status == "active" and not trial_end:
        trial_end = now

    with _connect() as conn:
        conn.execute(
            "UPDATE user_profiles SET status=?, updated_at=?, trial_end=? WHERE user_id=?",
            (new_status, now, trial_end, user_id),
        )

    try:
        from autoinfo.audit import append_audit_log

        append_audit_log(
            actor="system",
            action="transition_end_user",
            resource_type="user_profile",
            resource_id=user_id,
            details={
                "from_status": old_status,
                "to_status": new_status,
                "tier": profile.tier,
            },
        )
    except Exception:
        logger.warning(
            "Failed to write audit log for user '%s' transition %s → %s",
            user_id,
            old_status,
            new_status,
            exc_info=True,
        )

    return {
        "success": True,
        "user_id": user_id,
        "from_status": old_status,
        "to_status": new_status,
        "trial_start": trial_start,
        "trial_end": trial_end,
    }
