"""Stripe integration for AutoInfo billing.

Uses stripe-mock (http://localhost:12111) during development.  Set
``STRIPE_API_KEY`` to use a live or test-mode Stripe endpoint instead.

Configuration (precedence: env var > stripe-mock default):

- ``STRIPE_API_KEY`` — Stripe secret key (e.g. ``sk_test_...``).
  When set, the module uses the real Stripe API.  When unset,
  it connects to stripe-mock on ``http://localhost:12111``.
- ``STRIPE_API_BASE`` — Override the API base URL.  Useful for
  pointing at a custom stripe-mock instance.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import stripe  # noqa: F401 — imported lazily in _ensure_stripe

from autoinfo.models import UserProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stripe configuration
# ---------------------------------------------------------------------------

_STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
_STRIPE_API_BASE = os.environ.get(
    "STRIPE_API_BASE",
    "http://localhost:12111",
)

# In-memory cache — backfilled from DB on startup via _backfill_stripe_map().
# All mutations go through get_user_stripe_id / set_user_stripe_id.
_user_stripe_map: dict[str, str] = {}

# Counter for stripe_customer_id persistence failures (exposed via metrics).
_stripe_sync_failures: int = 0


def resolve_user_id(user_id: str | None = None) -> str:
    """Resolve the effective end-user id.

    Precedence (highest to lowest):
    1. Explicit ``user_id`` argument
    2. Config ``multi_user.default_user_id``
    3. Hard-coded fallback ``"default"`` (single-user mode)
    """
    if user_id:
        return user_id
    try:
        from autoinfo.config import get_config_path, load_config

        path = get_config_path()
        if path:
            cfg = load_config(path)
            if getattr(cfg, "multi_user", None) and cfg.multi_user.default_user_id:
                return cfg.multi_user.default_user_id
    except Exception:
        pass
    return "default"


def _backfill_stripe_map() -> None:
    """Load all persisted stripe_customer_ids from DB into the in-memory cache."""
    try:
        from autoinfo.user_store import list_stripe_customer_ids

        db_map = list_stripe_customer_ids()
        _user_stripe_map.update(db_map)
        if db_map:
            logger.debug("Backfilled %d stripe customer IDs from DB", len(db_map))
    except Exception:
        logger.debug("Could not backfill stripe map (no DB or no profiles yet)")


def get_user_stripe_id(end_user_id: str) -> str | None:
    """Return the Stripe customer ID for *end_user_id*, or None.

    Checks the in-memory cache first; falls back to the DB on miss
    and caches the result.
    """
    cached = _user_stripe_map.get(end_user_id)
    if cached:
        return cached

    # Try DB on cache miss
    try:
        from autoinfo.user_store import get_stripe_customer_id

        db_id = get_stripe_customer_id(end_user_id)
        if db_id:
            _user_stripe_map[end_user_id] = db_id
            return db_id
    except Exception:
        pass

    return None


def set_user_stripe_id(end_user_id: str, customer_id: str) -> None:
    """Store the Stripe customer ID for *end_user_id* in cache and DB.

    Always updates the in-memory cache.  Persists to DB on a best-effort
    basis — a DB failure will log a warning but never raise.
    """
    global _stripe_sync_failures
    _user_stripe_map[end_user_id] = customer_id
    try:
        from autoinfo.user_store import set_stripe_customer_id

        set_stripe_customer_id(end_user_id, customer_id)
    except ValueError:
        logger.debug(
            "set_stripe_customer_id: user '%s' has no profile yet, cache-only",
            end_user_id,
        )
    except ConnectionError as exc:
        _stripe_sync_failures += 1
        logger.warning(
            "STORAGE_CONNECTION_ERROR set_user_stripe_id user=%s error=%s",
            end_user_id, exc,
        )
    except stripe.error.StripeError as exc:
        _stripe_sync_failures += 1
        logger.warning(
            "STRIPE_API_ERROR set_user_stripe_id user=%s stripe_error=%s",
            end_user_id, exc,
        )
    except Exception as exc:
        _stripe_sync_failures += 1
        logger.warning(
            "SET_USER_STRIPE_UNKNOWN set_user_stripe_id user=%s error=%s",
            end_user_id, exc,
        )


# Backfill the in-memory cache from DB on module load
_backfill_stripe_map()


def _configure_stripe() -> None:
    """Set up stripe library with the correct endpoint and key."""
    if _STRIPE_API_KEY:
        stripe.api_key = _STRIPE_API_KEY
        if "localhost" in _STRIPE_API_BASE or "127.0.0.1" in _STRIPE_API_BASE:
            logger.warning(
                "STRIPE_API_KEY is set but STRIPE_API_BASE points at "
                "stripe-mock (%s). Real keys would be sent to the mock "
                "endpoint — set STRIPE_API_BASE=https://api.stripe.com for "
                "real test-mode payments.",
                _STRIPE_API_BASE,
            )
    else:
        # stripe-mock mode — use a fake key (stripe-mock ignores it)
        stripe.api_key = "sk_test_mock"
    stripe.api_base = _STRIPE_API_BASE
    logger.debug(
        "Stripe configured: base=%s key_set=%s",
        _STRIPE_API_BASE,
        bool(_STRIPE_API_KEY),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_or_create_customer(end_user_id: str, email: str = "", name: str = "") -> str:
    """Return existing Stripe customer ID, or create one for *end_user_id*."""
    cached_id = get_user_stripe_id(end_user_id)
    if cached_id:
        return cached_id

    _configure_stripe()
    customer = stripe.Customer.create(
        email=email or f"{end_user_id}@example.com",
        name=name or end_user_id,
        metadata={"end_user_id": end_user_id},
    )
    set_user_stripe_id(end_user_id, customer["id"])  # type: ignore[index]
    logger.info(
        "Created Stripe customer %s for end_user %s",
        customer["id"],  # type: ignore[index]
        end_user_id,
    )
    return customer["id"]  # type: ignore[index]


def _sync_user_stripe_id(end_user_id: str, stripe_customer_id: str) -> bool:
    """Update the in-memory mapping and persist to UserProfile store.

    Returns ``True`` on success, ``False`` on persistence failure.
    Never raises — all exceptions are caught and logged.
    """
    global _stripe_sync_failures
    set_user_stripe_id(end_user_id, stripe_customer_id)
    # set_user_stripe_id always updates cache; verify DB persistence
    from autoinfo.user_store import get_stripe_customer_id as _db_get

    try:
        persisted = _db_get(end_user_id)
        if persisted != stripe_customer_id:
            logger.error(
                "SYNC_MISMATCH _sync_user_stripe_id user=%s "
                "operation=verify expected=%s got=%s",
                end_user_id, stripe_customer_id, persisted,
            )
            _stripe_sync_failures += 1
            return False
        return True
    except ConnectionError as exc:
        logger.error(
            "STORAGE_CONNECTION_ERROR _sync_user_stripe_id user=%s "
            "operation=verify error=%s",
            end_user_id, exc,
        )
        _stripe_sync_failures += 1
        return False
    except ValueError as exc:
        logger.error(
            "STORAGE_VALUE_ERROR _sync_user_stripe_id user=%s "
            "operation=verify error=%s",
            end_user_id, exc,
        )
        _stripe_sync_failures += 1
        return False
    except Exception as exc:
        logger.error(
            "SYNC_UNKNOWN_ERROR _sync_user_stripe_id user=%s "
            "operation=verify error=%s",
            end_user_id, exc,
        )
        _stripe_sync_failures += 1
        return False


def _load_user_profile(end_user_id: str) -> UserProfile | None:
    """Load a UserProfile from the user store, if available."""
    try:
        from autoinfo.user_store import get_profile

        return get_profile(end_user_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_checkout_session(
    product_id: str,
    end_user_id: str,
    *,
    mode: str = "subscription",
    success_url: str = "http://localhost:8741/success",
    cancel_url: str = "http://localhost:8741/cancel",
    email: str = "",
    name: str = "",
    article_id: str = "",
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for *product_id*.

    Parameters
    ----------
    product_id:
        Stripe Price ID (e.g. ``price_xxx``) for subscription mode.
        For payment mode this serves as the price name.
    end_user_id:
        AutoInfo end-user identifier.  A Stripe Customer is created or
        looked up automatically.
    mode:
        Checkout mode: ``"subscription"`` (default) or ``"payment"``
        (one-time purchase, e.g. single-article access).
    success_url:
        Redirect URL after successful payment.
    cancel_url:
        Redirect URL on cancellation.
    email:
        Customer email (optional — defaults to ``{end_user_id}@example.com``).
    name:
        Customer name (optional — defaults to *end_user_id*).
    article_id:
        Article identifier for single-purchase metadata (only meaningful
        when *mode* is ``"payment"`` — reserved for T11).

    Returns
    -------
    dict with keys: ``session_id``, ``url``, ``customer_id``,
    ``end_user_id``, ``mode``.
    """
    try:
        _configure_stripe()
        customer_id = _get_or_create_customer(
            end_user_id, email=email, name=name,
        )

        metadata: dict[str, str] = {"end_user_id": end_user_id}
        if article_id:
            metadata["article_id"] = article_id

        if mode == "payment":
            # One-time payment: use price_data with unit_amount
            line_items = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": product_id},
                    "unit_amount": 0,  # 0 = pay-what-you-want / T11 determines actual amount
                },
                "quantity": 1,
            }]
        else:
            # Subscription mode: use existing price ID
            line_items = [{"price": product_id, "quantity": 1}]

        session = stripe.checkout.Session.create(
            customer=customer_id,
            line_items=line_items,
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        logger.info(
            "Checkout session %s created for %s (mode=%s)",
            session["id"],  # type: ignore[index]
            end_user_id,
            mode,
        )
        return {
            "session_id": session["id"],  # type: ignore[index]
            "url": session.get("url", ""),
            "customer_id": customer_id,
            "end_user_id": end_user_id,
            "mode": mode,
        }
    except Exception as exc:
        logger.exception("create_checkout_session failed for %s", end_user_id)
        return {
            "error": str(exc),
            "end_user_id": end_user_id,
        }


def handle_webhook(event: dict[str, Any]) -> dict[str, Any]:
    """Process a Stripe webhook event.

    Handles these event types:

    - ``checkout.session.completed`` — marks subscription as active
      and stores ``stripe_subscription_id`` on the user profile.
    - ``customer.subscription.updated`` — updates subscription status.
    - ``customer.subscription.deleted`` — marks subscription cancelled.

    Parameters
    ----------
    event:
        Raw Stripe event dict (the full webhook payload).

    Returns
    -------
    dict with ``status`` (``"processed"`` | ``"ignored"`` | ``"error"``),
    ``event_type``, and ``action`` taken.
    """
    event_type = event.get("type", "")
    logger.info("Processing Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(event)
    elif event_type == "customer.subscription.updated":
        return _handle_subscription_updated(event)
    elif event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(event)
    else:
        return {
            "status": "ignored",
            "event_type": event_type,
            "action": "no_handler",
        }


def _handle_checkout_completed(event: dict[str, Any]) -> dict[str, Any]:
    """Handle ``checkout.session.completed`` webhook.

    Branches on ``session.mode``:

    - ``"subscription"`` (or missing): activates subscription profile
      (existing behaviour).
    - ``"payment"``: one-time purchase — does **not** write an empty
      subscription ID or set ``status="active"`` on the profile.
    """
    session = event.get("data", {}).get("object", {})
    session_mode = session.get("mode", "subscription")
    subscription_id = session.get("subscription", "")
    customer_id = session.get("customer", "")
    metadata = session.get("metadata", {})
    end_user_id = metadata.get("end_user_id", "")

    if not end_user_id:
        logger.warning("checkout.session.completed missing end_user_id metadata")
        return {
            "status": "error",
            "event_type": "checkout.session.completed",
            "action": "missing_end_user_id",
        }

    if not _sync_user_stripe_id(end_user_id, customer_id):
        logger.warning(
            "Stripe customer ID persistence failed for %s — "
            "subscription activation will proceed without stored customer ID",
            end_user_id,
        )

    # --- Payment mode: one-time purchase, no subscription state change ---
    if session_mode == "payment":
        article_id = metadata.get("article_id", "")
        payment_intent_id = session.get("payment_intent", "")
        entitlement: dict[str, Any] = {}

        # Grant single-article entitlement (E12)
        if article_id:
            from autoinfo.consumption import ConsumptionStore

            store = ConsumptionStore()
            entitlement = store.grant_article_access(
                user_id=end_user_id,
                article_id=article_id,
                payment_intent_id=payment_intent_id,
            )

            # Record purchase-consumption event
            store.record_event(
                user_id=end_user_id,
                product_type="article",
                product_id=article_id,
                event_type="purchased",
                metadata={
                    "payment_intent_id": payment_intent_id,
                    "customer_id": customer_id,
                    "entitlement_reason": entitlement["reason"],
                },
            )

        logger.info(
            "checkout.session.completed (payment) for %s article=%s "
            "entitlement=%s",
            end_user_id,
            article_id or "(none)",
            entitlement.get("reason") if article_id else "no_article",
        )
        return {
            "status": "processed",
            "event_type": "checkout.session.completed",
            "action": "payment_received",
            "mode": "payment",
            "end_user_id": end_user_id,
            "article_id": article_id,
            "entitlement_reason": entitlement.get("reason") if article_id else None,
        }

    # --- Subscription mode: activate profile ---
    try:
        from autoinfo.user_store import update_profile

        update_profile(
            user_id=end_user_id,
            stripe_subscription_id=subscription_id,
            status="active",
        )
    except Exception as exc:
        logger.exception("Failed to update user %s after checkout", end_user_id)
        return {
            "status": "error",
            "event_type": "checkout.session.completed",
            "action": "profile_update_failed",
            "error": str(exc),
        }

    return {
        "status": "processed",
        "event_type": "checkout.session.completed",
        "action": "activated_subscription",
        "end_user_id": end_user_id,
        "subscription_id": subscription_id,
    }


def _handle_subscription_updated(event: dict[str, Any]) -> dict[str, Any]:
    """Handle ``customer.subscription.updated`` webhook."""
    subscription = event.get("data", {}).get("object", {})
    subscription_id = subscription.get("id", "")
    status = subscription.get("status", "")
    customer_id = subscription.get("customer", "")

    # Map end_user_id from customer metadata (reverse lookup)
    end_user_id = ""
    for uid, cid in _user_stripe_map.items():
        if cid == customer_id:
            end_user_id = uid
            break

    if not end_user_id:
        return {
            "status": "ignored",
            "event_type": "customer.subscription.updated",
            "action": "no_end_user_match",
        }

    try:
        from autoinfo.user_store import update_profile

        mapped_status = _map_stripe_status(status)
        update_profile(
            user_id=end_user_id,
            stripe_subscription_id=subscription_id,
            status=mapped_status,
        )
    except Exception as exc:
        logger.exception("Failed to update status for %s", end_user_id)
        return {
            "status": "error",
            "event_type": "customer.subscription.updated",
            "action": "profile_update_failed",
            "error": str(exc),
        }

    return {
        "status": "processed",
        "event_type": "customer.subscription.updated",
        "action": "updated_status",
        "end_user_id": end_user_id,
        "new_status": mapped_status,
    }


def _handle_subscription_deleted(event: dict[str, Any]) -> dict[str, Any]:
    """Handle ``customer.subscription.deleted`` webhook."""
    subscription = event.get("data", {}).get("object", {})
    customer_id = subscription.get("customer", "")

    end_user_id = ""
    for uid, cid in _user_stripe_map.items():
        if cid == customer_id:
            end_user_id = uid
            break

    if not end_user_id:
        return {
            "status": "ignored",
            "event_type": "customer.subscription.deleted",
            "action": "no_end_user_match",
        }

    try:
        from autoinfo.user_store import update_profile

        update_profile(
            user_id=end_user_id,
            status="cancelled",
        )
    except Exception as exc:
        logger.exception("Failed to cancel subscription for %s", end_user_id)
        return {
            "status": "error",
            "event_type": "customer.subscription.deleted",
            "action": "profile_update_failed",
            "error": str(exc),
        }

    return {
        "status": "processed",
        "event_type": "customer.subscription.deleted",
        "action": "cancelled_subscription",
        "end_user_id": end_user_id,
    }


def get_subscription_status(end_user_id: str) -> dict[str, Any]:
    """Return the Stripe subscription status for *end_user_id*.

    Looks up the Stripe subscription via the stored ``stripe_subscription_id``
    on the user's profile.  Falls back to the profile's local status if no
    Stripe subscription is associated.

    Returns
    -------
    dict with keys: ``end_user_id``, ``profile_status``, ``stripe_status``,
    ``subscription_id``, ``customer_id``, ``plan``.
    """
    profile = _load_user_profile(end_user_id)
    local_status = profile.status if profile else "unknown"

    subscription_id = ""
    customer_id = ""
    stripe_status = "none"
    plan = "free"

    # Try to get subscription_id from the in-memory map or profile
    if profile is not None and hasattr(profile, "stripe_subscription_id"):
        subscription_id = getattr(profile, "stripe_subscription_id", "") or ""
    if profile is not None and hasattr(profile, "stripe_customer_id"):
        customer_id = getattr(profile, "stripe_customer_id", "") or ""

    if customer_id and customer_id not in _user_stripe_map.values():
        set_user_stripe_id(end_user_id, customer_id)

    if subscription_id:
        try:
            _configure_stripe()
            sub = stripe.Subscription.retrieve(subscription_id)
            stripe_status = sub.get("status", "unknown")  # type: ignore[union-attr]
            plan = (
                sub.get("items", {})  # type: ignore[union-attr]
                .get("data", [{}])[0]
                .get("price", {})
                .get("id", "free")
            )
        except Exception:
            logger.warning(
                "Failed to retrieve Stripe subscription %s for %s",
                subscription_id,
                end_user_id,
            )
            stripe_status = "error"

    return {
        "end_user_id": end_user_id,
        "profile_status": local_status,
        "stripe_status": stripe_status,
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "plan": plan,
    }


def _map_stripe_status(stripe_status: str) -> str:
    """Map Stripe subscription status → AutoInfo user status."""
    mapping: dict[str, str] = {
        "active": "active",
        "trialing": "trial",
        "past_due": "suspended",
        "unpaid": "suspended",
        "canceled": "cancelled",
        "incomplete": "trial",
        "incomplete_expired": "cancelled",
        "paused": "suspended",
    }
    return mapping.get(stripe_status, "trial")


# ---------------------------------------------------------------------------
# Freemium access gating (G15) + single-article entitlement (E12)
# ---------------------------------------------------------------------------


def _check_article_entitlement(user_id: str, article_id: str) -> bool:
    """Check whether *user_id* owns single-article access to *article_id*.

    Convenience wrapper around ``ConsumptionStore.check_article_access``
    that catches storage errors silently and returns ``False`` on failure.
    """
    try:
        from autoinfo.consumption import ConsumptionStore

        return ConsumptionStore().check_article_access(user_id, article_id)
    except Exception:
        logger.debug(
            "Article entitlement check failed for user=%s article=%s",
            user_id, article_id, exc_info=True,
        )
        return False


def check_access(
    end_user_id: str,
    access_level: str = "free",
    *,
    article_id: str = "",
) -> dict[str, Any]:
    """Check whether *end_user_id* has access to content at *access_level*.

    Implements the freemium gating logic (G15) plus single-article
    entitlement (E12):

    - ``"free"`` — always allowed.
    - ``"premium"`` — requires an active paid subscription (not trial,
      not cancelled, not suspended).  Falls back to article entitlement
      check when *article_id* is supplied.
    - ``"enterprise"`` — requires enterprise-tier access (plan/tier
      indicates enterprise billing tier).
    - ``article_id`` (keyword-only) — when supplied, precedes all other
      checks: single-article purchasers are always allowed regardless of
      tier, for the specified article only.

    Parameters
    ----------
    end_user_id:
        AutoInfo end-user identifier.
    access_level:
        Required access level: ``"free"``, ``"premium"``, or ``"enterprise"``.
    article_id:
        Optional article identifier for single-article entitlement check
        (E12).  When supplied and the user has purchased this article,
        access is granted immediately.

    Returns
    -------
    dict with keys:
        - ``allowed`` (bool) — whether access is granted.
        - ``reason`` (str) — human-readable explanation.
        - ``access_level`` (str) — requested access level.
        - ``end_user_id`` (str) — user ID checked.
        - ``upgrade_prompt`` (str | None) — upgrade prompt text when blocked
          (None when allowed).
        - ``profile_status`` (str) — user's current profile status.
        - ``plan`` (str) — user's current plan/tier.
        - ``article_id`` (str | None) — article ID when article path was used.
    """
    # --- Single-article entitlement fast path (E12) ---------------------
    if article_id and _check_article_entitlement(end_user_id, article_id):
        return {
            "allowed": True,
            "reason": (
                f"User has purchased single-article access to '{article_id}' "
                f"(article entitlement fast path)."
            ),
            "access_level": access_level,
            "end_user_id": end_user_id,
            "upgrade_prompt": None,
            "profile_status": "any",
            "plan": "article_purchase",
            "article_id": article_id,
        }
    # Free content is always allowed — no lookup needed
    if access_level == "free":
        return {
            "allowed": True,
            "reason": "Free content is available to all users.",
            "access_level": access_level,
            "end_user_id": end_user_id,
            "upgrade_prompt": None,
            "profile_status": "any",
            "plan": "any",
            "article_id": None,
        }

    # --- Fast path: check UserProfile.tier (no Stripe dependency) ----------
    TIER_MAP: dict[str, int] = {"free": 0, "premium": 1, "enterprise": 2}
    required_tier_num = TIER_MAP.get(access_level, 0)

    profile = _load_user_profile(end_user_id)
    if profile is not None:
        user_tier = getattr(profile, "tier", "free") or "free"
        user_tier_num = TIER_MAP.get(user_tier, 0)
        if user_tier_num >= required_tier_num:
            return {
                "allowed": True,
                "reason": (
                    f"User tier '{user_tier}' grants access to "
                    f"'{access_level}' content (tier fast path)."
                ),
                "access_level": access_level,
                "end_user_id": end_user_id,
                "upgrade_prompt": None,
                "profile_status": getattr(profile, "status", "active"),
                "plan": user_tier,
                "article_id": None,
            }

    # Fall through to Stripe-based subscription check
    sub = get_subscription_status(end_user_id)
    profile_status = sub.get("profile_status", "unknown")
    plan = sub.get("plan", "free")
    stripe_status = sub.get("stripe_status", "none")

    # --- Premium: requires active subscription (paid) ----------------------
    if access_level == "premium":
        # Active profile AND active/trial Stripe status = paying user
        is_active = profile_status in ("active",) and stripe_status in (
            "active", "trialing",
        )
        if is_active:
            return {
                "allowed": True,
                "reason": "User has an active premium subscription.",
                "access_level": access_level,
                "end_user_id": end_user_id,
                "upgrade_prompt": None,
                "profile_status": profile_status,
                "plan": plan,
                "article_id": None,
            }
        else:
            return {
                "allowed": False,
                "reason": (
                    f"User profile status is '{profile_status}' with Stripe "
                    f"status '{stripe_status}'. An active premium subscription "
                    f"is required to access premium content."
                ),
                "access_level": access_level,
                "end_user_id": end_user_id,
                "upgrade_prompt": (
                    "🔒 This is premium content. Upgrade to a paid subscription "
                    "to unlock premium digests, reports, and features. "
                    "Visit your account settings to upgrade."
                ),
                "profile_status": profile_status,
                "plan": plan,
                "article_id": None,
            }

    # --- Enterprise: requires enterprise-tier plan -------------------------
    if access_level == "enterprise":
        # Enterprise is determined by plan/tier containing "enterprise"
        # or by explicit enterprise status on the profile
        is_enterprise = (
            "enterprise" in plan.lower()
            or profile_status == "active"
            and stripe_status == "active"
            and plan not in ("free", "")
        )

        # Also check UserProfile.tier for enterprise flag
        profile = _load_user_profile(end_user_id)
        if profile is not None:
            tier = getattr(profile, "tier", "free") or "free"
            if "enterprise" in tier.lower():
                is_enterprise = True

        if is_enterprise:
            return {
                "allowed": True,
                "reason": "User has enterprise-tier access.",
                "access_level": access_level,
                "end_user_id": end_user_id,
                "upgrade_prompt": None,
                "profile_status": profile_status,
                "plan": plan,
                "article_id": None,
            }
        else:
            return {
                "allowed": False,
                "reason": (
                    f"User plan is '{plan}', profile status '{profile_status}'. "
                    f"An enterprise subscription is required for enterprise "
                    f"content."
                ),
                "access_level": access_level,
                "end_user_id": end_user_id,
                "upgrade_prompt": (
                    "🔒 This is enterprise content. Contact sales to upgrade "
                    "to an enterprise plan with custom data, white-labeling, "
                    "and priority support."
                ),
                "profile_status": profile_status,
                "plan": plan,
                "article_id": None,
            }

    # Unknown access_level — default to blocked
    return {
        "allowed": False,
        "reason": f"Unknown access level: {access_level!r}.",
        "access_level": access_level,
        "end_user_id": end_user_id,
        "upgrade_prompt": None,
        "profile_status": profile_status,
        "plan": plan,
        "article_id": None,
    }
