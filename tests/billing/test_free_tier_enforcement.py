"""Free-tier limit enforcement at generation/schedule time (todo 12).

Covers:
- ``check_free_tier_generation`` — the single enforcement seam consulted by
  ``generate_digest`` / ``generate_report`` for named end-users
  (``user_id=""`` batch/unattended paths SKIP the check entirely)
- Over-limit named free user → :class:`FreeTierLimitError` carrying an
  error envelope (code ``FREE_TIER_LIMIT``, current/limit values,
  actionable upgrade hint)
- Cron ``add-delivery`` schedule-frequency check (daily schedule under a
  weekly free-tier limit → same error)
- Premium-tier users are NOT limited (regression)
- ``ErrorCode.FREE_TIER_LIMIT`` exists (28 → 29 enum values)

Count semantics (plan todo 12):
  (a) active domains bound to the user's subscription (subscription.domains)
  (b) the user's existing product-type count (ConsumptionStore history)
  (c) schedule frequency vs the subscription ``max_frequency``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autoinfo.config import Config, FreeTierConfig
from autoinfo.mcp.errors import ErrorCode
from autoinfo.models import Subscription
from autoinfo.output import (
    FreeTierLimitError,
    check_free_tier_generation,
)
from autoinfo.user_store import create_profile, create_subscription, init_db

# ---------------------------------------------------------------------------
# Fixtures — isolated user-store DB + consumption DB in a temp project dir
# ---------------------------------------------------------------------------


@pytest.fixture
def user_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the user-store SQLite DB and consumption DB in a temp dir."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("autoinfo.user_store._DB_PATH", None)
    monkeypatch.setattr(
        "autoinfo.user_store._get_db_path", lambda: tmp_path / ".autoinfo" / "users.db"
    )
    # Reset the consumption store's module-level path cache as well.
    import autoinfo.consumption as consumption_mod

    monkeypatch.setattr(consumption_mod, "_DB_PATH", None)
    return tmp_path


def _free_subscription(user_id: str, **overrides: Any) -> Subscription:
    """Create an active free-tier subscription (free-tier defaults)."""
    init_db()
    create_profile(user_id=user_id, name=f"User {user_id}", status="active")
    kwargs: dict[str, Any] = {
        "plan": "free",
        "tier": "free",
        "status": "active",
        "max_products": 1,
        "max_frequency": "weekly",
        "allow_custom": False,
    }
    kwargs.update(overrides)
    return create_subscription(user_id=user_id, **kwargs)


def _premium_subscription(user_id: str) -> Subscription:
    """Create an active premium subscription (no free-tier limits)."""
    return _free_subscription(
        user_id,
        plan="premium",
        tier="premium",
        max_products=8,
        max_frequency="daily",
        allow_custom=True,
    )


def _record_product(
    user_id: str, product_type: str, product_id: str, domain: str = ""
) -> None:
    """Record one delivered product for *user_id* in the consumption store.

    The ``domain`` metadata mirrors what generate_digest/generate_report
    record via CD-018 — the gate counts (product_type, domain) pairs.
    """
    from autoinfo.consumption import ConsumptionStore

    metadata = {"domain": domain} if domain else {}
    ConsumptionStore().record_event(
        user_id=user_id,
        product_type=product_type,
        product_id=product_id,
        event_type="delivered",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Error code enum
# ---------------------------------------------------------------------------


class TestErrorCode:
    def test_free_tier_limit_code_exists(self) -> None:
        assert ErrorCode.FREE_TIER_LIMIT.value == "FreeTierLimit"


# ---------------------------------------------------------------------------
# Gate: no subscription
# ---------------------------------------------------------------------------


class TestNoSubscription:
    def test_no_subscription_not_blocked(self, user_db: Path) -> None:
        """A named user without any subscription record is not limited
        (mirrors check_access behavior: absent profile → no free-tier gate)."""
        result = check_free_tier_generation(
            user_id="no-such-user",
            domain="medical-research",
            product_type="digest",
        )
        assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Gate: user_id="" (batch / unattended / CLI-no-user) skips enforcement
# ---------------------------------------------------------------------------


class TestUnnamedUserSkipsGate:
    def test_empty_user_id_skips_even_when_limits_exceeded(self, user_db: Path) -> None:
        """user_id="" is the batch/unattended path — the gate must NOT fire
        even when a free subscription with exhausted limits exists."""
        _free_subscription("u-limit")
        _record_product("u-limit", "digest", "medical-research-weekly")

        result = check_free_tier_generation(
            user_id="",
            domain="other-domain",
            product_type="digest",
        )
        assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Gate: product-type count (1-product free limit)
# ---------------------------------------------------------------------------


class TestProductCountLimit:
    def test_first_product_allowed(self, user_db: Path) -> None:
        _free_subscription("u-free")
        result = check_free_tier_generation(
            user_id="u-free",
            domain="medical-research",
            product_type="digest",
        )
        assert result["allowed"] is True

    def test_second_product_type_blocked_with_envelope(
        self, user_db: Path
    ) -> None:
        """Named free user (1-product limit) generating a 2nd product type →
        FREE_TIER_LIMIT error containing current/limit values."""
        _free_subscription("u-quota")
        _record_product("u-quota", "digest", "medical-research-weekly")

        result = check_free_tier_generation(
            user_id="u-quota",
            domain="medical-research",
            product_type="report",
        )
        assert result["allowed"] is False
        assert result["code"] == ErrorCode.FREE_TIER_LIMIT.value
        assert result["actionable"] is True
        assert "upgrade" in result["message"].lower()
        # Current/limit values present in the message
        assert "1/1" in result["message"]
        assert "report" in result["message"]

    def test_same_product_type_regeneration_allowed(self, user_db: Path) -> None:
        """Re-generating the same (family, domain) pair stays allowed —
        the gate blocks NEW products, not scheduled refreshes."""
        _free_subscription("u-regen")
        _record_product(
            "u-regen", "digest", "medical-research-weekly", domain="medical-research"
        )

        result = check_free_tier_generation(
            user_id="u-regen",
            domain="medical-research",
            product_type="digest",
        )
        assert result["allowed"] is True

    def test_other_domain_counts_toward_product_limit(self, user_db: Path) -> None:
        """A second domain's digest is still a (different) product for the
        same user — with 1 product limit and a digest already delivered,
        the cross-domain digest is blocked too (plan todo 12 QA: 第 2 域
        digest → FREE_TIER_LIMIT)."""
        _free_subscription("u-xdom")
        _record_product("u-xdom", "digest", "medical-research-weekly")

        result = check_free_tier_generation(
            user_id="u-xdom",
            domain="ai-commercial",
            product_type="digest",
        )
        assert result["allowed"] is False
        assert result["code"] == ErrorCode.FREE_TIER_LIMIT.value


# ---------------------------------------------------------------------------
# Gate: premium users NOT limited
# ---------------------------------------------------------------------------


class TestPremiumNotLimited:
    def test_premium_user_above_free_product_count_allowed(
        self, user_db: Path
    ) -> None:
        _premium_subscription("u-premium")
        for i in range(3):
            _record_product("u-premium", "digest", f"domain-{i}-weekly")

        result = check_free_tier_generation(
            user_id="u-premium",
            domain="new-domain",
            product_type="report",
        )
        assert result["allowed"] is True


# ---------------------------------------------------------------------------
# Gate: config free-tier limits respected
# ---------------------------------------------------------------------------


class TestConfigFreeTierLimits:
    def test_config_max_products_limits_gate(self, user_db: Path) -> None:
        """The gate reads free-tier limits from Config.free_tier (todo 11)."""
        cfg = Config()
        cfg.free_tier = FreeTierConfig(
            max_domains=2, max_products=3, frequency="weekly", allow_custom=False
        )
        _free_subscription("u-cfg")
        for i in range(3):
            _record_product("u-cfg", "digest", f"domain-{i}-weekly")

        result = check_free_tier_generation(
            user_id="u-cfg",
            domain="new-domain",
            product_type="digest",
            config=cfg,
        )
        assert result["allowed"] is True


# ---------------------------------------------------------------------------
# FreeTierLimitError exception shape
# ---------------------------------------------------------------------------


class TestFreeTierLimitError:
    def test_error_is_valueerror_with_envelope(self, user_db: Path) -> None:
        """generate_* handlers catch ValueError → VALIDATION_ERROR; the
        free-tier exception subclasses ValueError so both the MCP handlers
        and CLI catch it, while carrying the structured envelope."""
        _free_subscription("u-err")
        _record_product("u-err", "digest", "medical-research-weekly")

        with pytest.raises(FreeTierLimitError) as exc_info:
            check_free_tier_generation(
                user_id="u-err",
                domain="medical-research",
                product_type="report",
                raise_on_block=True,
            )
        err = exc_info.value
        assert isinstance(err, ValueError)
        envelope = err.to_envelope()
        assert envelope["success"] is False
        assert envelope["error"]["code"] == ErrorCode.FREE_TIER_LIMIT.value
        assert envelope["error"]["actionable"] is True
        assert "upgrade" in envelope["error"]["message"].lower()


# ---------------------------------------------------------------------------
# generate_digest / generate_report entry enforcement
# ---------------------------------------------------------------------------


class TestGenerationEntryEnforcement:
    """The single seam: generate_digest / generate_report consult the gate
    at ENTRY when user_id is non-empty."""

    def test_generate_digest_blocks_named_over_limit_user(
        self, user_db: Path
    ) -> None:
        from autoinfo.output import generate_digest

        _free_subscription("u-entry")
        _record_product("u-entry", "digest", "medical-research-weekly")

        with pytest.raises(FreeTierLimitError):
            generate_digest(
                domain="medical-research",
                period="weekly",
                user_id="u-entry",
            )

    def test_generate_digest_allows_unnamed_despite_exhausted_quota(
        self, user_db: Path
    ) -> None:
        """user_id="" generation must NOT be blocked (batch path)."""
        from autoinfo.output import generate_digest

        _free_subscription("u-batch")
        _record_product("u-batch", "digest", "medical-research-weekly")

        out = generate_digest(
            domain="medical-research",
            period="weekly",
            user_id="",
        )
        assert isinstance(out, str)
        assert out.strip()  # non-empty product

    def test_generate_report_blocks_named_over_limit_user(
        self, user_db: Path
    ) -> None:
        from autoinfo.output import generate_report

        _free_subscription("u-entry-r")
        _record_product("u-entry-r", "report", "medical-research-monthly")

        with pytest.raises(FreeTierLimitError):
            generate_report(
                domain="medical-research",
                period="monthly",
                user_id="u-entry-r",
            )

    def test_generate_report_allows_unnamed_despite_exhausted_quota(
        self, user_db: Path
    ) -> None:
        from autoinfo.output import generate_report

        _free_subscription("u-batch-r")
        _record_product("u-batch-r", "report", "medical-research-monthly")

        out = generate_report(
            domain="medical-research",
            period="monthly",
            user_id="",
        )
        assert isinstance(out, str)
        assert out.strip()


# ---------------------------------------------------------------------------
# Schedule-frequency gate (cron add-delivery seam)
# ---------------------------------------------------------------------------


class TestScheduleFrequency:
    def test_daily_schedule_under_weekly_limit_blocked(self, user_db: Path) -> None:
        """Over-frequency schedule (daily when the subscription allows
        weekly) → the same FREE_TIER_LIMIT error."""
        from autoinfo.delivery.frequency_gate import check_schedule_frequency

        _free_subscription("u-sched")

        result = check_schedule_frequency(
            user_id="u-sched",
            frequency="daily",
        )
        assert result["allowed"] is False
        assert result["code"] == ErrorCode.FREE_TIER_LIMIT.value
        assert result["actionable"] is True
        assert "upgrade" in result["message"].lower()
        assert "weekly" in result["message"].lower()
        assert "daily" in result["message"].lower()

        with pytest.raises(FreeTierLimitError):
            check_schedule_frequency(
                user_id="u-sched", frequency="daily", raise_on_block=True
            )

    def test_weekly_schedule_under_weekly_limit_allowed(self, user_db: Path) -> None:
        from autoinfo.delivery.frequency_gate import check_schedule_frequency

        _free_subscription("u-sched-ok")
        result = check_schedule_frequency(user_id="u-sched-ok", frequency="weekly")
        assert result["allowed"] is True

    def test_frequency_ranking(self) -> None:
        from autoinfo.delivery.frequency_gate import frequency_rank

        assert frequency_rank("daily") > frequency_rank("weekly")
        assert frequency_rank("weekly") > frequency_rank("monthly")
        assert frequency_rank("monthly") > frequency_rank("quarterly")
        # Unknown frequency → conservative (0, never more frequent than known)
        assert frequency_rank("weird") == 0

    def test_premium_daily_schedule_allowed(self, user_db: Path) -> None:
        from autoinfo.delivery.frequency_gate import check_schedule_frequency

        _premium_subscription("u-sched-prem")
        result = check_schedule_frequency(user_id="u-sched-prem", frequency="daily")
        assert result["allowed"] is True


# ---------------------------------------------------------------------------
# CLI cron add-delivery: schedule-frequency check for named users
# ---------------------------------------------------------------------------


class TestCronAddDelivery:
    def test_add_delivery_free_user_daily_blocked(self, user_db: Path) -> None:
        from typer.testing import CliRunner

        from autoinfo.cli import app as main_app

        _free_subscription("u-cron")

        runner = CliRunner()
        result = runner.invoke(
            main_app,
            [
                "cron", "add-delivery",
                "--domain", "medical-research",
                "--schedule", "0 8 * * *",  # daily
                "--output", "digest",
                "--period", "daily",
                "--user-id", "u-cron",
            ],
        )
        assert result.exit_code != 0
        assert "FreeTierLimit" in result.output or "FREE_TIER_LIMIT" in result.output

    def test_add_delivery_free_user_weekly_allowed(self, user_db: Path) -> None:
        from typer.testing import CliRunner

        from autoinfo.cli import app as main_app

        _free_subscription("u-cron-ok")

        runner = CliRunner()
        result = runner.invoke(
            main_app,
            [
                "cron", "add-delivery",
                "--domain", "medical-research",
                "--schedule", "0 8 * * 1",  # weekly (Monday)
                "--output", "digest",
                "--period", "weekly",
                "--user-id", "u-cron-ok",
            ],
        )
        assert result.exit_code == 0, f"STDERR: {result.output}"

    def test_add_delivery_unnamed_user_unblocked_daily(
        self, user_db: Path
    ) -> None:
        """No --user-id → schedule user_id="" → gate skipped (batch path)."""
        from typer.testing import CliRunner

        from autoinfo.cli import app as main_app

        runner = CliRunner()
        result = runner.invoke(
            main_app,
            [
                "cron", "add-delivery",
                "--domain", "medical-research",
                "--schedule", "0 8 * * *",  # daily — would violate weekly, but no user
                "--output", "digest",
            ],
        )
        assert result.exit_code == 0, f"STDERR: {result.output}"
