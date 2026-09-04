"""Tests for `autoinfo billing create-free` (todo 11).

The billing CLI was read-only; the roadmap acceptance requires a
``create-free`` subcommand that provisions a free subscription with
free-tier defaults (1 domain / 1 product / weekly / no custom).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autoinfo.cli import app as main_app
from autoinfo.user_store import list_subscriptions


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def user_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the user-store SQLite DB in a temp project dir."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("autoinfo.user_store._DB_PATH", None)
    monkeypatch.setattr(
        "autoinfo.user_store._get_db_path", lambda: tmp_path / ".autoinfo" / "users.db"
    )
    return tmp_path


class TestBillingCreateFree:
    def test_creates_free_subscription_with_defaults(self, runner, user_db) -> None:
        result = runner.invoke(
            main_app, ["billing", "create-free", "--user-id", "alice"]
        )

        assert result.exit_code == 0, f"STDERR: {result.output}"

        subs = list_subscriptions("alice")
        assert len(subs) == 1
        sub = subs[0]
        assert sub.plan == "free"
        assert sub.tier == "free"
        assert sub.status == "active"
        assert sub.domain_limit == 1
        assert sub.max_products == 1
        assert sub.max_frequency == "weekly"
        assert sub.allow_custom is False
        assert sub.price_monthly == 0.0

    def test_creates_missing_profile(self, runner, user_db) -> None:
        """subscriptions.user_id has a FK to user_profiles — the command
        must ensure the profile exists before inserting."""
        result = runner.invoke(
            main_app, ["billing", "create-free", "--user-id", "bob"]
        )
        assert result.exit_code == 0, f"STDERR: {result.output}"

        from autoinfo.user_store import get_profile

        assert get_profile("bob") is not None

    def test_repeat_is_idempotent_no_dup_rows(self, runner, user_db) -> None:
        for _ in range(2):
            result = runner.invoke(
                main_app, ["billing", "create-free", "--user-id", "carol"]
            )
            assert result.exit_code == 0, f"STDERR: {result.output}"

        subs = list_subscriptions("carol")
        assert len(subs) == 1
        assert "already" in result.output.lower()

    def test_json_output_reports_free_defaults(self, runner, user_db) -> None:
        result = runner.invoke(
            main_app, ["billing", "create-free", "--user-id", "dave", "--json"]
        )
        assert result.exit_code == 0, f"STDERR: {result.output}"

        payload = json.loads(result.output)
        assert payload["user_id"] == "dave"
        assert payload["plan"] == "free"
        assert payload["created"] is True or payload["created"] is False
        limits = payload["limits"]
        assert limits == {
            "max_domains": 1,
            "max_products": 1,
            "max_frequency": "weekly",
            "allow_custom": False,
        }

    def test_summary_shows_free_plan_with_limits(self, runner, user_db) -> None:
        """get_subscription_status reports plan=free for the provisioned user."""
        create = runner.invoke(
            main_app, ["billing", "create-free", "--user-id", "erin"]
        )
        assert create.exit_code == 0, f"STDERR: {create.output}"

        from autoinfo.billing import get_subscription_status

        status = get_subscription_status("erin")
        assert status["plan"] == "free"

        summary = runner.invoke(
            main_app, ["billing", "summary", "--user-id", "erin"]
        )
        assert summary.exit_code == 0, f"STDERR: {summary.output}"
        assert "free" in summary.output

    def test_rejects_empty_user_id(self, runner, user_db) -> None:
        result = runner.invoke(main_app, ["billing", "create-free", "--user-id", ""])
        assert result.exit_code != 0
        assert list_subscriptions() == []

    def test_existing_subscription_untouched(self, runner, user_db) -> None:
        """Idempotency must not overwrite a pre-existing subscription."""
        from autoinfo.user_store import create_profile, create_subscription

        create_profile(user_id="frank", name="Frank", status="active")
        create_subscription(
            user_id="frank",
            plan="premium",
            tier="premium",
            max_products=8,
            max_frequency="daily",
            allow_custom=True,
        )

        result = runner.invoke(
            main_app, ["billing", "create-free", "--user-id", "frank"]
        )
        assert result.exit_code == 0, f"STDERR: {result.output}"

        subs = list_subscriptions("frank")
        assert len(subs) == 1
        assert subs[0].plan == "premium"
