"""Schedule-frequency gate for named end-users (todo 12 — P1-2 enforcement).

Single enforcement seam for the cron ``add-delivery`` path (CLI
``autoinfo cron add-delivery`` and MCP ``add_delivery_schedule``): when
the schedule carries a named *user_id*, the requested schedule frequency
is compared against the subscription's ``max_frequency``.

``user_id=""`` schedules (unattended/batch) skip the gate — quotas apply
only to named end-users.

Frequency ranking (most→least frequent): ``minutely`` / ``hourly`` /
``daily`` / ``weekly`` / ``monthly`` / ``quarterly``.  A schedule at or
below the subscription ceiling is allowed; anything more frequent is
rejected with the canonical ``FREE_TIER_LIMIT`` error envelope.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from autoinfo.mcp.errors import ErrorCode, error_response
from autoinfo.output.free_tier import (
    FreeTierLimitError,
    _is_limited_subscription,
    _subscription_for_user,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

logger = logging.getLogger(__name__)

_FREQUENCY_RANK: dict[str, int] = {
    "quarterly": 1,
    "monthly": 2,
    "weekly": 3,
    "daily": 4,
    "hourly": 5,
    "minutely": 6,
}


def frequency_rank(frequency: str) -> int:
    """Rank *frequency* by how often it fires (higher = more frequent).

    Unknown frequencies rank ``0`` — never treated as more frequent than
    a known ceiling (conservative for the *subscription* side, strict
    enough for the *requested* side since unknown requested frequencies
    cannot exceed rank 0 subscriptions).
    """
    return _FREQUENCY_RANK.get(str(frequency or "").strip().lower(), 0)


def _frequency_error_envelope(
    requested: str, allowed: str
) -> dict[str, Any]:
    message = (
        f"Free-tier limit reached: schedule frequency '{requested}' exceeds "
        f"the '{allowed}' allowance of the free plan. Upgrade to a premium "
        "subscription to schedule more frequent deliveries."
    )
    return error_response(
        ErrorCode.FREE_TIER_LIMIT,
        message=message,
        actionable=True,
    )


def check_schedule_frequency(
    user_id: str,
    frequency: str,
    *,
    raise_on_block: bool = False,
) -> dict[str, Any]:
    """Gate a delivery-schedule frequency against the user's subscription.

    Parameters
    ----------
    user_id:
        Named end-user bound to the schedule. ``""`` immediately allows
        (batch/unattended schedules carry no user quota).
    frequency:
        Requested schedule frequency (``daily`` / ``weekly`` / ``monthly``).
    raise_on_block:
        When ``True``, raise :class:`FreeTierLimitError` on breach.

    Returns
    -------
    dict
        ``{allowed: bool, reason: str}`` plus ``code`` / ``message`` /
        ``actionable`` when blocked (the error-envelope fields).
    """
    # --- Named-user only: unattended schedules skip the gate -------------
    if not user_id:
        return {"allowed": True, "reason": "No user context (batch path)"}

    subscription = _subscription_for_user(user_id)
    if not _is_limited_subscription(subscription):
        return {
            "allowed": True,
            "reason": "User is not on a limited plan",
        }

    max_frequency = str(
        getattr(subscription, "max_frequency", "") or "weekly"
    ).strip().lower()
    requested = str(frequency or "").strip().lower()

    if frequency_rank(requested) > frequency_rank(max_frequency):
        envelope = _frequency_error_envelope(requested, max_frequency)
        if raise_on_block:
            raise FreeTierLimitError(envelope)
        return {
            "allowed": False,
            "reason": "Schedule frequency exceeds plan allowance",
            **envelope["error"],
        }

    return {
        "allowed": True,
        "reason": "Schedule frequency within plan allowance",
    }
