"""Tests for the read-only end-user portal (``/portal/{user_id}``).

All tests mock ``autoinfo.user_store`` and ``autoinfo.delivery_log`` so no
real SQLite database is required.  The FastAPI ``TestClient`` is used to
exercise the Jinja2-rendered HTML routes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from autoinfo.models import DeliveryLog, Subscription, UserProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_profile() -> UserProfile:
    """Return a synthetic UserProfile with realistic trial info."""
    return UserProfile(
        user_id="user-001",
        name="Alice Test",
        email="alice@example.com",
        status="trial",
        tier="free",
        delivery_preferences={
            "format": "html",
            "delivery_channel": "smtp",
            "timezone": "UTC",
            "max_items": 10,
            "enabled": True,
            "topics": ["IVF", "embryo"],
        },
        created_at="2026-07-01T00:00:00Z",
        updated_at="2026-07-20T00:00:00Z",
        trial_started_at="2026-07-20T00:00:00Z",
        trial_ends_at="2026-08-03T00:00:00Z",
        trial_days=14,
    )


@pytest.fixture
def sample_subscriptions() -> list[Subscription]:
    """Return two synthetic subscriptions (one active, one cancelled)."""
    return [
        Subscription(
            subscription_id=str(uuid4()),
            user_id="user-001",
            plan="medical-research-processed",
            status="active",
            start_date="2026-07-01T00:00:00Z",
            end_date="2027-07-01T00:00:00Z",
            auto_renew=True,
        ),
        Subscription(
            subscription_id=str(uuid4()),
            user_id="user-001",
            plan="ai-commercial-raw",
            status="cancelled",
            start_date="2026-06-01T00:00:00Z",
            end_date="2026-07-01T00:00:00Z",
            auto_renew=False,
        ),
    ]


@pytest.fixture
def sample_delivery_logs(sample_subscriptions: list[Subscription]) -> list[DeliveryLog]:
    """Return three synthetic delivery log entries."""
    sub_id = sample_subscriptions[0].subscription_id
    return [
        DeliveryLog(
            log_id=str(uuid4()),
            subscription_id=sub_id,
            channel="smtp",
            message_type="digest",
            status="success",
            attempt_count=1,
            last_attempt="2026-07-25T08:00:00Z",
            error_message="",
            sla_tier="standard",
        ),
        DeliveryLog(
            log_id=str(uuid4()),
            subscription_id=sub_id,
            channel="webhook",
            message_type="report",
            status="failed",
            attempt_count=3,
            last_attempt="2026-07-24T12:00:00Z",
            error_message="connection refused",
            sla_tier="critical",
        ),
        DeliveryLog(
            log_id=str(uuid4()),
            subscription_id=sub_id,
            channel="telegram",
            message_type="alert",
            status="retrying",
            attempt_count=2,
            last_attempt="2026-07-23T18:00:00Z",
            error_message="rate limited",
            sla_tier="standard",
        ),
    ]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Return a TestClient with isolated config + KB store.

    Patches the config path so the portal's product listing (which reads
    ``.autoinfo/config.yaml``) does not pick up a real project config.
    """
    from autoinfo.api.server import app
    import autoinfo.api.routes as routes

    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        "rest_api:\n  port: 8741\n  host: 127.0.0.1\n"
        "llm:\n  provider: openai\n  model: gpt-4\n"
    )

    with patch("autoinfo.config.get_config_path", return_value=config_path):
        yield TestClient(app)

    routes._store = None


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_get_profile(profile: UserProfile | None):
    """Return a patcher for ``autoinfo.user_store.get_profile``."""
    return patch("autoinfo.user_store.get_profile", return_value=profile)


def _mock_list_subscriptions(subscriptions: list[Subscription]):
    """Return a patcher for ``autoinfo.user_store.list_subscriptions``."""
    return patch("autoinfo.user_store.list_subscriptions", return_value=subscriptions)


def _mock_check_trial_expiry(result: dict[str, Any]):
    """Return a patcher for ``autoinfo.user_store.check_trial_expiry``."""
    return patch("autoinfo.user_store.check_trial_expiry", return_value=result)


def _mock_query_delivery_log(logs: list[DeliveryLog]):
    """Return a patcher for ``autoinfo.delivery_log.query_delivery_log``."""

    def _query(subscription_id=None, **kwargs):
        # Return logs matching the requested subscription_id, or all
        if subscription_id is None:
            return logs
        return [log for log in logs if log.subscription_id == subscription_id]

    return patch("autoinfo.delivery_log.query_delivery_log", side_effect=_query)


def _mock_list_all_products(products: list[dict[str, Any]]):
    """Return a patcher for ``autoinfo.api.portal._list_all_products``."""
    return patch("autoinfo.api.portal._list_all_products", return_value=products)


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------


class TestPortalDashboard:
    """``GET /portal/{user_id}`` — landing dashboard."""

    def test_dashboard_renders_for_valid_user(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_check_trial_expiry(
                {
                    "days_remaining": 10,
                    "status": "active",
                    "trial_started_at": "2026-07-20T00:00:00Z",
                    "trial_days": 14,
                }
            ),
            _mock_query_delivery_log(sample_delivery_logs),
        ):
            response = client.get("/portal/user-001")

        assert response.status_code == 200
        html = response.text
        assert "Alice Test" in html
        assert "alice@example.com" in html
        assert "user-001" in html
        # Subscription status badge
        assert "trial" in html.lower()
        # Quick stats labels
        assert "Total Deliveries" in html
        assert "Active Subscriptions" in html
        # Subscriptions table
        assert "Subscriptions" in html
        assert "medical-research-processed" in html

    def test_dashboard_missing_user_returns_404_error_page(
        self, client: TestClient
    ):
        with _mock_get_profile(None):
            response = client.get("/portal/nonexistent-user")

        assert response.status_code == 404
        html = response.text
        assert "not found" in html.lower()
        # Navigation still available
        assert "AutoInfo Portal" in html
        assert "/portal/" in html

    def test_dashboard_shows_trial_active(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_check_trial_expiry(
                {"days_remaining": 7, "status": "active", "trial_days": 14}
            ),
            _mock_query_delivery_log(sample_delivery_logs),
        ):
            response = client.get("/portal/user-001")

        assert response.status_code == 200
        assert "Trial is" in response.text
        assert "active" in response.text.lower()
        assert "7 day" in response.text

    def test_dashboard_shows_trial_expired(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_check_trial_expiry(
                {"days_remaining": 0, "status": "expired", "trial_days": 14}
            ),
            _mock_query_delivery_log(sample_delivery_logs),
        ):
            response = client.get("/portal/user-001")

        assert response.status_code == 200
        assert "expired" in response.text.lower()

    def test_dashboard_no_subscriptions(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_delivery_logs: list[DeliveryLog],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions([]),
            _mock_check_trial_expiry(
                {"days_remaining": 10, "status": "active", "trial_days": 14}
            ),
            _mock_query_delivery_log([]),
        ):
            response = client.get("/portal/user-001")

        assert response.status_code == 200
        assert "No subscriptions found" in response.text
        assert "0" in response.text  # active sub count


# ---------------------------------------------------------------------------
# Preferences route
# ---------------------------------------------------------------------------


class TestPortalPreferences:
    """``GET /portal/{user_id}/preferences`` — read-only preferences."""

    def test_preferences_renders_for_valid_user(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        with _mock_get_profile(sample_profile):
            response = client.get("/portal/user-001/preferences")

        assert response.status_code == 200
        html = response.text
        assert "Delivery Preferences" in html
        assert "Read-only" in html
        # Preference keys present
        assert "format" in html
        assert "delivery_channel" in html
        assert "smtp" in html
        assert "timezone" in html
        assert "max_items" in html
        # Raw JSON section
        assert "Raw JSON" in html

    def test_preferences_missing_user_returns_404(
        self, client: TestClient
    ):
        with _mock_get_profile(None):
            response = client.get("/portal/nonexistent/preferences")

        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_preferences_empty_prefs_shows_empty_state(
        self, client: TestClient
    ):
        profile = UserProfile(
            user_id="user-empty",
            name="Empty User",
            email="empty@example.com",
            delivery_preferences={},
        )
        with _mock_get_profile(profile):
            response = client.get("/portal/user-empty/preferences")

        assert response.status_code == 200
        assert "No delivery preferences configured" in response.text

    def test_preferences_is_read_only(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        with _mock_get_profile(sample_profile):
            response = client.get("/portal/user-001/preferences")

        assert response.status_code == 200
        # No form with method=put/post for editing
        assert 'method="put"' not in response.text.lower()
        assert 'method="post"' not in response.text.lower()


# ---------------------------------------------------------------------------
# History route
# ---------------------------------------------------------------------------


class TestPortalHistory:
    """``GET /portal/{user_id}/history`` — paginated delivery log."""

    def test_history_renders_for_valid_user(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log(sample_delivery_logs),
        ):
            response = client.get("/portal/user-001/history")

        assert response.status_code == 200
        html = response.text
        assert "Delivery History" in html
        # Table headers
        assert "Log ID" in html
        assert "Channel" in html
        assert "Type" in html
        assert "Status" in html
        assert "Attempts" in html
        assert "Last Attempt" in html
        # Data rows
        assert "smtp" in html
        assert "webhook" in html
        assert "success" in html
        assert "failed" in html
        # Total count badge
        assert "3 total" in html

    def test_history_missing_user_returns_404(self, client: TestClient):
        with _mock_get_profile(None):
            response = client.get("/portal/nonexistent/history")

        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_history_no_deliveries_shows_empty_state(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log([]),
        ):
            response = client.get("/portal/user-001/history")

        assert response.status_code == 200
        assert "No delivery history found" in response.text

    def test_history_no_subscriptions_shows_empty_state(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions([]),
            _mock_query_delivery_log([]),
        ):
            response = client.get("/portal/user-001/history")

        assert response.status_code == 200
        assert "No delivery history found" in response.text

    def test_history_pagination_controls(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
    ):
        # With limit=2 and 3 entries, page 1 should have next but no prev
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log(sample_delivery_logs),
        ):
            response = client.get(
                "/portal/user-001/history?limit=2&offset=0"
            )

        assert response.status_code == 200
        html = response.text
        assert "Showing 1–2 of 3" in html
        # Prev disabled, Next enabled
        assert "Prev" in html
        assert "Next" in html

    def test_history_pagination_second_page(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log(sample_delivery_logs),
        ):
            response = client.get(
                "/portal/user-001/history?limit=2&offset=2"
            )

        assert response.status_code == 200
        html = response.text
        assert "Showing 3–3 of 3" in html

    def test_history_invalid_limit_returns_422(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        with _mock_get_profile(sample_profile):
            response = client.get("/portal/user-001/history?limit=0")

        assert response.status_code == 422

    def test_history_invalid_offset_returns_422(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        with _mock_get_profile(sample_profile):
            response = client.get("/portal/user-001/history?offset=-1")

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Products route
# ---------------------------------------------------------------------------


class TestPortalProducts:
    """``GET /portal/{user_id}/products`` — product archive."""

    def test_products_renders_for_valid_user(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        products = [
            {
                "id": "medical-research-raw",
                "domain": "medical-research",
                "type": "raw",
                "name": "medical-research RAW Feed",
            },
            {
                "id": "medical-research-processed",
                "domain": "medical-research",
                "type": "processed",
                "name": "medical-research PROCESSED Output",
            },
        ]
        with (
            _mock_get_profile(sample_profile),
            _mock_list_all_products(products),
        ):
            response = client.get("/portal/user-001/products")

        assert response.status_code == 200
        html = response.text
        assert "Products" in html
        assert "medical-research-raw" in html
        assert "medical-research-processed" in html
        assert "medical-research RAW Feed" in html
        assert "2 total" in html

    def test_products_missing_user_returns_404(self, client: TestClient):
        with (
            _mock_get_profile(None),
            _mock_list_all_products([]),
        ):
            response = client.get("/portal/nonexistent/products")

        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_products_empty_shows_empty_state(
        self,
        client: TestClient,
        sample_profile: UserProfile,
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_all_products([]),
        ):
            response = client.get("/portal/user-001/products")

        assert response.status_code == 200
        html = response.text
        assert "No products available" in html
        assert "0 total" in html


# ---------------------------------------------------------------------------
# Cross-cutting: navigation, dark mode, base template
# ---------------------------------------------------------------------------


class TestPortalBaseTemplate:
    """Verify the base template is consistent across all pages."""

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "/preferences",
            "/history",
            "/products",
        ],
    )
    def test_all_pages_have_bootstrap_cdn(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
        path: str,
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log(sample_delivery_logs),
            _mock_list_all_products([]),
            _mock_check_trial_expiry(
                {"days_remaining": 10, "status": "active", "trial_days": 14}
            ),
        ):
            response = client.get(f"/portal/user-001{path}")

        assert response.status_code == 200
        html = response.text
        # Bootstrap 5.3.3 CSS
        assert "bootstrap@5.3.3" in html
        # Bootstrap Icons 1.11.3
        assert "bootstrap-icons@1.11.3" in html
        # Bootstrap bundle JS
        assert "bootstrap.bundle.min.js" in html

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "/preferences",
            "/history",
            "/products",
        ],
    )
    def test_all_pages_have_navigation_links(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
        path: str,
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log(sample_delivery_logs),
            _mock_list_all_products([]),
            _mock_check_trial_expiry(
                {"days_remaining": 10, "status": "active", "trial_days": 14}
            ),
        ):
            response = client.get(f"/portal/user-001{path}")

        assert response.status_code == 200
        html = response.text
        # All four nav links present
        assert '/portal/user-001"' in html  # dashboard
        assert "/portal/user-001/preferences" in html
        assert "/portal/user-001/history" in html
        assert "/portal/user-001/products" in html

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "/preferences",
            "/history",
            "/products",
        ],
    )
    def test_all_pages_have_dark_mode_toggle(
        self,
        client: TestClient,
        sample_profile: UserProfile,
        sample_subscriptions: list[Subscription],
        sample_delivery_logs: list[DeliveryLog],
        path: str,
    ):
        with (
            _mock_get_profile(sample_profile),
            _mock_list_subscriptions(sample_subscriptions),
            _mock_query_delivery_log(sample_delivery_logs),
            _mock_list_all_products([]),
            _mock_check_trial_expiry(
                {"days_remaining": 10, "status": "active", "trial_days": 14}
            ),
        ):
            response = client.get(f"/portal/user-001{path}")

        assert response.status_code == 200
        html = response.text
        assert 'data-bs-theme="auto"' in html
        assert "themeToggle" in html
        assert "autoinfo-theme" in html  # localStorage key

    def test_error_page_has_navigation(self, client: TestClient):
        with _mock_get_profile(None):
            response = client.get("/portal/nonexistent")

        assert response.status_code == 404
        html = response.text
        # Nav still present
        assert "AutoInfo Portal" in html
        # Form to try a different user
        assert "userIdInput" in html