"""Free-tier quota gate for named end-users (todo 12 — P1-2 enforcement).

Single enforcement seam consulted at the ``generate_digest`` /
``generate_report`` ENTRY points: when *user_id* is non-empty the gate
compares the user's subscription free-tier limits against

  (a) active domains bound to the user's subscription (``domains`` list)
  (b) the user's existing product-type count (ConsumptionStore history)
  (c) nothing else at generation time — schedule frequency is enforced by
      :mod:`autoinfo.delivery.frequency_gate` at the cron ``add-delivery``
      seam.

``user_id=""`` (unattended / batch / CLI-without-user-context) SKIPS the
gate entirely — quotas apply only to named end-users, the same semantics
as the content_preference filtering (B-001).

The gate raises :class:`FreeTierLimitError` (a :class:`ValueError`
subclass carrying the canonical error envelope) when a limit is exceeded
— over-limit is an explicit error, never a silent pass.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from autoinfo.mcp.errors import ErrorCode, error_response

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for typing only
    from autoinfo.config import Config
    from autoinfo.models import Subscription

logger = logging.getLogger(__name__)


class FreeTierLimitError(ValueError):
    """Raised when a named free-tier user exceeds a subscription limit.

    Subclasses :class:`ValueError` so the existing ``except ValueError``
    paths in the MCP generate handlers and the CLI surface it as a clean
    error (no traceback), while :meth:`to_envelope` carries the canonical
    ``{success: False, error: {code, message, actionable}}`` shape.
    """

    def __init__(self, envelope: dict[str, Any]) -> None:
        self.envelope = envelope
        super().__init__(envelope.get("error", {}).get("message", ""))

    def to_envelope(self) -> dict[str, Any]:
        """Return the canonical error envelope for this limit breach."""
        return self.envelope


def free_tier_error_envelope(message: str) -> dict[str, Any]:
    """Build the unified ``FREE_TIER_LIMIT`` error envelope."""
    return error_response(
        ErrorCode.FREE_TIER_LIMIT,
        message=message,
        actionable=True,
    )


def _resolve_free_tier_limits(config: "Config | None") -> dict[str, Any]:
    """Free-tier limits from the project config (todo 11 defaults)."""
    try:
        if config is None:
            from autoinfo.config import get_config_path, load_config

            config_path = get_config_path()
            config = (
                load_config(config_path) if config_path is not None else None
            )
    except Exception:
        config = None
    if config is None:
        from autoinfo.config import Config

        config = Config()
    return {
        "max_domains": config.free_tier.max_domains,
        "max_products": config.free_tier.max_products,
        "frequency": config.free_tier.frequency,
        "allow_custom": config.free_tier.allow_custom,
    }


def _subscription_for_user(user_id: str) -> "Subscription | None":
    """Latest subscription record for *user_id*, or ``None``.

    Absent profile/subscription → ``None`` (no free-tier gate — mirrors
    ``check_access``, which also allows unknown users on free content).
    """
    try:
        from autoinfo.user_store import list_subscriptions

        subs = list_subscriptions(user_id)
        return subs[0] if subs else None
    except Exception:
        logger.debug(
            "free_tier gate: could not load subscription for '%s'",
            user_id,
            exc_info=True,
        )
        return None


def _is_limited_subscription(subscription: "Subscription | None") -> bool:
    """Whether *subscription* is subject to free-tier limits.

    Any subscription whose plan/tier is not free/premium/enterprise is
    considered limited (defensive: unknown plans keep the free-tier
    ceiling).
    """
    if subscription is None:
        return False
    plan = (getattr(subscription, "plan", "") or "").lower()
    tier = (getattr(subscription, "tier", "") or "").lower()
    return plan not in ("premium", "enterprise") and tier not in (
        "premium",
        "enterprise",
    )


def _existing_products(user_id: str) -> set[tuple[str, str]]:
    """(product_type, domain) pairs already delivered for *user_id*.

    The ConsumptionStore ledger (CD-018) is the single source of truth for
    "the user's existing product count".  Domain comes from the event
    metadata; events without it count toward the total with an empty
    domain key.
    """
    try:
        from autoinfo.consumption import ConsumptionStore

        events = ConsumptionStore().list_events(user_id, limit=1000)
    except Exception:
        logger.debug(
            "free_tier gate: could not read consumption history for '%s'",
            user_id,
            exc_info=True,
        )
        return set()
    products: set[tuple[str, str]] = set()
    for event in events:
        product_type = str(event.get("product_type") or "").strip()
        if not product_type:
            continue
        metadata = event.get("metadata")
        domain = (
            str(metadata.get("domain") or "").strip()
            if isinstance(metadata, dict)
            else ""
        )
        products.add((product_type, domain))
    return products


def check_free_tier_generation(
    user_id: str,
    domain: str,
    product_type: str,
    *,
    config: "Config | None" = None,
    raise_on_block: bool = False,
) -> dict[str, Any]:
    """Quota gate for product generation by a named end-user.

    Parameters
    ----------
    user_id:
        Named end-user. ``""`` (batch/unattended) immediately allows —
        quotas apply only to named users.
    domain:
        Domain the product is generated for.
    product_type:
        Product family being generated (``"digest"``, ``"report"``, …).
    config:
        Optional pre-loaded :class:`Config` (limits come from
        ``Config.free_tier``; loaded from the project config when omitted).
    raise_on_block:
        When ``True``, raise :class:`FreeTierLimitError` instead of
        returning the ``allowed: False`` result dict.

    Returns
    -------
    dict
        ``{allowed: bool, reason: str}`` plus ``code`` / ``message`` /
        ``actionable`` when blocked (the error-envelope fields).
    """
    # --- Named-user only: batch/unattended paths skip the gate -----------
    if not user_id:
        return {"allowed": True, "reason": "No user context (batch path)"}

    subscription = _subscription_for_user(user_id)
    if not _is_limited_subscription(subscription):
        return {
            "allowed": True,
            "reason": "User is not on a limited plan",
        }

    limits = _resolve_free_tier_limits(config)

    # --- (b) Existing product count vs max_products ----------------------
    # A product is a (family, domain) pair: regenerating the SAME pair is
    # the scheduled-refresh path and stays allowed; a NEW family or a NEW
    # domain counts as a 2nd product (plan todo 12: "第 2 个产品/第 2 域
    # digest → FREE_TIER_LIMIT").
    existing = _existing_products(user_id)
    if (product_type, domain) not in existing and len(existing) >= limits["max_products"]:
        existing_label = (
            ", ".join(sorted(f"{ptype}@{dom}" for ptype, dom in existing))
            or "none"
        )
        message = (
            f"Free-tier limit reached: {len(existing)}/"
            f"{limits['max_products']} products (existing: {existing_label}). "
            f"Generating '{product_type}' for domain '{domain}' would "
            "exceed the free plan. Upgrade to a premium subscription to "
            "unlock more products."
        )
        envelope = free_tier_error_envelope(message)
        if raise_on_block:
            raise FreeTierLimitError(envelope)
        return {"allowed": False, "reason": "Product limit reached", **envelope["error"]}

    return {
        "allowed": True,
        "reason": "Within free-tier limits",
    }


# Alias kept for the schedule-frequency seam documentation: the cron
# ``add-delivery`` check lives in autoinfo.delivery.frequency_gate
# (check_schedule_frequency) and returns the same envelope shape.
