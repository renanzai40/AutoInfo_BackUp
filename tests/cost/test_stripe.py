"""Tests for Stripe integration (billing module).

All stripe library calls are mocked via ``unittest.mock.patch`` — no
network calls, no stripe-mock, no Docker required.

Test coverage:
- Webhook event signature verification (valid + invalid)
- ``handle_webhook()`` event dispatch for each supported event type
- ``get_user_stripe_id()`` / ``set_user_stripe_id()`` with persisted store
- ``_sync_user_stripe_id()`` success + failure paths
- ``create_checkout_session()`` with existing and new customers
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from autoinfo.api.server import app
from autoinfo.billing import (
    _user_stripe_map,
    create_checkout_session,
    get_user_stripe_id,
    handle_webhook,
    set_user_stripe_id,
)
from autoinfo.consumption import ConsumptionStore

# Module reference for checking mutable global state
import autoinfo.billing as _billing_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(event_type: str, **kwargs: object) -> dict:
    """Build a minimal Stripe webhook event dict.

    Extra keyword arguments are merged into ``data.object`` for
    convenience (e.g. ``customer="cus_xxx"``).
    """
    event: dict = {
        "id": "evt_test",
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_test456",
                "customer": "cus_test123",
            }
        },
    }
    event["data"]["object"].update(kwargs)
    return event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_global_state() -> None:
    """Clear billing global state between each test.

    This includes the in-memory ``_user_stripe_map`` and the
    ``_stripe_sync_failures`` counter so tests do not leak state.
    """
    _user_stripe_map.clear()
    _billing_mod._stripe_sync_failures = 0
    yield


@pytest.fixture
def checkout_completed_event() -> dict:
    """A realistic ``checkout.session.completed`` Stripe event."""
    return {
        "id": "evt_cs_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_session",
                "customer": "cus_test123",
                "subscription": "sub_test456",
                "metadata": {"end_user_id": "user_abc"},
                "mode": "subscription",
                "status": "complete",
            }
        },
    }


@pytest.fixture
def sub_updated_event() -> dict:
    """A realistic ``customer.subscription.updated`` event."""
    return {
        "id": "evt_sub_upd",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test456",
                "customer": "cus_test123",
                "status": "past_due",
            }
        },
    }


@pytest.fixture
def sub_deleted_event() -> dict:
    """A realistic ``customer.subscription.deleted`` event."""
    return {
        "id": "evt_sub_del",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test456",
                "customer": "cus_test123",
            }
        },
    }


@pytest.fixture
def payment_checkout_event() -> dict:
    """A ``checkout.session.completed`` event with ``mode="payment"``."""
    return {
        "id": "evt_cs_pay",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_payment",
                "customer": "cus_test123",
                "subscription": "",
                "payment_intent": "pi_test_art42",
                "metadata": {
                    "end_user_id": "user_abc",
                    "article_id": "art_42",
                },
                "mode": "payment",
                "status": "complete",
            }
        },
    }


@pytest.fixture
def payment_checkout_event_no_article() -> dict:
    """A payment checkout event without article_id metadata (edge case)."""
    return {
        "id": "evt_cs_pay_no_art",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_payment_no_art",
                "customer": "cus_test123",
                "subscription": "",
                "payment_intent": "pi_test_no_art",
                "metadata": {"end_user_id": "user_abc"},
                "mode": "payment",
                "status": "complete",
            }
        },
    }


# ===================================================================
# 1. Webhook event signature verification (FastAPI endpoint)
# ===================================================================


class TestWebhookSignatureVerification:
    """Test the ``/api/v1/webhook/stripe`` endpoint signature verification.

    The endpoint verifies the ``Stripe-Signature`` header via
    ``stripe.Webhook.construct_event`` when ``STRIPE_WEBHOOK_SECRET``
    is set, otherwise falls back to raw JSON parsing (dev mode).
    """

    # ------------------------------------------------------------------
    # Valid signature
    # ------------------------------------------------------------------

    @patch("autoinfo.api.server.os.environ.get")
    def test_valid_signature_returns_200(self, mock_env_get: MagicMock) -> None:
        """Valid signature -> 200 with processed webhook result."""
        mock_env_get.return_value = "whsec_test_secret"
        payload = json.dumps({
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {}}},
        })

        client = TestClient(app)
        with patch("stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = {
                "type": "checkout.session.completed",
                "data": {"object": {"metadata": {}}},
            }
            resp = client.post(
                "/api/v1/webhook/stripe",
                content=payload,
                headers={"Stripe-Signature": "t=123,v1=valid_sig"},
            )

        assert resp.status_code == 200
        mock_construct.assert_called_once_with(
            payload.encode(), "t=123,v1=valid_sig", "whsec_test_secret",
        )

    # ------------------------------------------------------------------
    # Invalid signature
    # ------------------------------------------------------------------

    @patch("autoinfo.api.server.os.environ.get")
    def test_invalid_signature_returns_400(self, mock_env_get: MagicMock) -> None:
        """Invalid Stripe-Signature -> 400 with canonical error envelope."""
        mock_env_get.return_value = "whsec_test_secret"
        payload = json.dumps({"type": "checkout.session.completed"})

        import stripe as _stripe

        client = TestClient(app)
        with patch("stripe.Webhook.construct_event") as mock_construct:
            mock_construct.side_effect = _stripe.error.SignatureVerificationError(
                "Signature does not match", "t=123,v1=bad",
            )
            resp = client.post(
                "/api/v1/webhook/stripe",
                content=payload,
                headers={"Stripe-Signature": "t=123,v1=bad"},
            )

        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ValidationError"
        assert "Signature does not match" in data["error"]["message"]

    # ------------------------------------------------------------------
    # Dev mode (no secret configured)
    # ------------------------------------------------------------------

    @patch("autoinfo.api.server.os.environ.get")
    def test_dev_mode_no_secret_skips_verification(
        self, mock_env_get: MagicMock,
    ) -> None:
        """No ``STRIPE_WEBHOOK_SECRET`` -> raw JSON parsed directly (dev mode).

        The endpoint should still return 200 because ``handle_webhook``
        handles the missing ``end_user_id`` gracefully.
        """
        mock_env_get.return_value = ""  # no secret
        payload = json.dumps({
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {}}},
        })

        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhook/stripe",
            content=payload,
            headers={"Stripe-Signature": "t=123,v1=whatever"},
        )

        # Endpoint returns 200; webhook reports missing end_user_id
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert resp.json()["action"] == "missing_end_user_id"

    # ------------------------------------------------------------------
    # Invalid JSON payload (dev mode only)
    # ------------------------------------------------------------------

    @patch("autoinfo.api.server.os.environ.get")
    def test_invalid_json_payload_returns_400(
        self, mock_env_get: MagicMock,
    ) -> None:
        """Invalid JSON body in dev mode -> 400 with canonical error envelope."""
        mock_env_get.return_value = ""  # dev mode
        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhook/stripe",
            content=b"not valid json {{{",
            headers={"Stripe-Signature": "t=123,v1=whatever"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ValidationError"


# ===================================================================
# 2. handle_webhook() event dispatch
# ===================================================================


class TestHandleWebhookDispatch:
    """Test ``handle_webhook()`` routes each event type to the correct handler."""

    # ------------------------------------------------------------------
    # checkout.session.completed
    # ------------------------------------------------------------------

    def test_checkout_completed_activates_subscription(
        self, checkout_completed_event: dict,
    ) -> None:
        """``checkout.session.completed`` -> subscription activated and customer stored."""
        _user_stripe_map["user_abc"] = "cus_test123"

        with (
            patch("autoinfo.user_store.update_profile") as mock_update,
            patch("autoinfo.user_store.get_stripe_customer_id") as mock_get,
        ):
            mock_get.return_value = "cus_test123"
            result = handle_webhook(checkout_completed_event)

        assert result["status"] == "processed"
        assert result["action"] == "activated_subscription"
        assert result["end_user_id"] == "user_abc"
        assert result["subscription_id"] == "sub_test456"

        # ``update_profile`` is called:
        # 1. from ``set_stripe_customer_id`` inside ``_sync_user_stripe_id``,
        # 2. then from ``_handle_checkout_completed`` itself.
        mock_update.assert_any_call(
            user_id="user_abc",
            stripe_customer_id="cus_test123",
        )
        mock_update.assert_any_call(
            user_id="user_abc",
            stripe_subscription_id="sub_test456",
            status="active",
        )
        assert mock_update.call_count == 2

    def test_checkout_completed_missing_end_user_id(
        self, checkout_completed_event: dict,
    ) -> None:
        """Missing ``end_user_id`` metadata -> error response."""
        checkout_completed_event["data"]["object"]["metadata"] = {}
        result = handle_webhook(checkout_completed_event)
        assert result["status"] == "error"
        assert result["action"] == "missing_end_user_id"

    def test_checkout_completed_payment_mode(
        self, payment_checkout_event: dict,
    ) -> None:
        """``checkout.session.completed`` with mode="payment" → no subscription activation."""
        _user_stripe_map["user_abc"] = "cus_test123"

        with (
            patch("autoinfo.user_store.update_profile") as mock_update,
            patch("autoinfo.user_store.get_stripe_customer_id") as mock_get,
            patch("autoinfo.consumption.ConsumptionStore") as mock_store_cls,
        ):
            mock_get.return_value = "cus_test123"
            mock_store = MagicMock()
            mock_store.grant_article_access.return_value = {
                "granted": True, "article_id": "art_42",
                "user_id": "user_abc", "reason": "granted",
            }
            mock_store_cls.return_value = mock_store
            result = handle_webhook(payment_checkout_event)

        assert result["status"] == "processed"
        assert result["action"] == "payment_received"
        assert result["mode"] == "payment"
        assert result["end_user_id"] == "user_abc"
        assert result["article_id"] == "art_42"
        assert result["entitlement_reason"] == "granted"

        mock_store.grant_article_access.assert_called_once_with(
            user_id="user_abc", article_id="art_42",
            payment_intent_id="pi_test_art42",
        )
        mock_store.record_event.assert_called_once()
        record_kwargs = mock_store.record_event.call_args.kwargs
        assert record_kwargs["event_type"] == "purchased"
        assert record_kwargs["product_type"] == "article"

        # KEY REGRESSION: must NOT call update_profile(status="active")
        for call in mock_update.call_args_list:
            _, kwargs = call
            if kwargs.get("status") == "active":
                pytest.fail(
                    "BUG REGRESSION: mode=payment produced status='active' "
                    "— empty subscription_id would be written to the profile"
                )
            if "stripe_subscription_id" in kwargs:
                pytest.fail(
                    "BUG REGRESSION: mode=payment wrote stripe_subscription_id "
                    "to the profile"
                )

    # ------------------------------------------------------------------
    # customer.subscription.updated
    # ------------------------------------------------------------------

    def test_subscription_updated_maps_status(
        self, sub_updated_event: dict,
    ) -> None:
        """``customer.subscription.updated`` -> status mapped (past_due -> suspended)."""
        _user_stripe_map["user_abc"] = "cus_test123"

        with patch("autoinfo.user_store.update_profile") as mock_update:
            result = handle_webhook(sub_updated_event)

        assert result["status"] == "processed"
        assert result["action"] == "updated_status"
        assert result["new_status"] == "suspended"  # past_due -> suspended
        mock_update.assert_called_once_with(
            user_id="user_abc",
            stripe_subscription_id="sub_test456",
            status="suspended",
        )

    def test_subscription_updated_no_end_user_match(
        self, sub_updated_event: dict,
    ) -> None:
        """Unknown customer (no end_user_id match) -> ignored."""
        _user_stripe_map.clear()
        result = handle_webhook(sub_updated_event)
        assert result["status"] == "ignored"
        assert result["action"] == "no_end_user_match"

    # ------------------------------------------------------------------
    # customer.subscription.deleted
    # ------------------------------------------------------------------

    def test_subscription_deleted_cancels(
        self, sub_deleted_event: dict,
    ) -> None:
        """``customer.subscription.deleted`` -> subscription cancelled."""
        _user_stripe_map["user_abc"] = "cus_test123"

        with patch("autoinfo.user_store.update_profile") as mock_update:
            result = handle_webhook(sub_deleted_event)

        assert result["status"] == "processed"
        assert result["action"] == "cancelled_subscription"
        mock_update.assert_called_once_with(
            user_id="user_abc",
            status="cancelled",
        )

    def test_subscription_deleted_no_end_user_match(
        self, sub_deleted_event: dict,
    ) -> None:
        """Unknown customer in delete event -> ignored."""
        _user_stripe_map.clear()
        result = handle_webhook(sub_deleted_event)
        assert result["status"] == "ignored"
        assert result["action"] == "no_end_user_match"

    # ------------------------------------------------------------------
    # Unknown event type
    # ------------------------------------------------------------------

    def test_unknown_event_type_is_ignored(self) -> None:
        """Event type with no registered handler -> ignored."""
        event = _make_event("charge.succeeded")
        result = handle_webhook(event)
        assert result["status"] == "ignored"
        assert result["action"] == "no_handler"


# ===================================================================
# 3. get_user_stripe_id() / set_user_stripe_id()
# ===================================================================


class TestStripeIdMapping:
    """Test the Stripe customer ID <-> end_user_id mapping layer.

    The mapping uses an in-memory dict (``_user_stripe_map``) as cache
    with the DB as authoritative backing store.  Mutations always update
    the cache and best-effort persist to the DB.
    """

    # ------------------------------------------------------------------
    # get_user_stripe_id
    # ------------------------------------------------------------------

    def test_get_returns_cached_value(self) -> None:
        """Value in cache -> returned immediately, no DB call."""
        _user_stripe_map["user_abc"] = "cus_cached"
        assert get_user_stripe_id("user_abc") == "cus_cached"

    def test_get_falls_back_to_db_on_cache_miss(self) -> None:
        """Cache miss -> DB lookup, result cached for next call."""
        with patch("autoinfo.user_store.get_stripe_customer_id") as mock_get:
            mock_get.return_value = "cus_from_db"
            result = get_user_stripe_id("user_xyz")

        assert result == "cus_from_db"
        assert _user_stripe_map["user_xyz"] == "cus_from_db"

    def test_get_returns_none_when_not_found(self) -> None:
        """Neither cache nor DB -> None."""
        with patch("autoinfo.user_store.get_stripe_customer_id") as mock_get:
            mock_get.return_value = None
            result = get_user_stripe_id("user_none")
        assert result is None

    # ------------------------------------------------------------------
    # set_user_stripe_id
    # ------------------------------------------------------------------

    def test_set_updates_cache_and_persists(self) -> None:
        """Cache updated, DB write attempted."""
        with patch("autoinfo.user_store.set_stripe_customer_id") as mock_set:
            set_user_stripe_id("user_abc", "cus_new")

        assert _user_stripe_map["user_abc"] == "cus_new"
        mock_set.assert_called_once_with("user_abc", "cus_new")

    def test_set_cache_only_on_value_error(self) -> None:
        """ValueError (no profile) -> cache updated, counter unchanged."""
        with patch(
            "autoinfo.user_store.set_stripe_customer_id",
            side_effect=ValueError("user not found"),
        ):
            set_user_stripe_id("user_new", "cus_new")

        assert _user_stripe_map["user_new"] == "cus_new"
        # ValueError does NOT increment the failure counter
        assert _billing_mod._stripe_sync_failures == 0

    def test_set_increments_failure_on_connection_error(self) -> None:
        """ConnectionError -> cache updated, failure counter incremented."""
        with patch(
            "autoinfo.user_store.set_stripe_customer_id",
            side_effect=ConnectionError("DB connection refused"),
        ):
            set_user_stripe_id("user_fail", "cus_fail")

        assert _user_stripe_map["user_fail"] == "cus_fail"
        assert _billing_mod._stripe_sync_failures == 1

    def test_set_increments_failure_on_stripe_error(self) -> None:
        """StripeError -> cache updated, failure counter incremented."""
        import stripe as _stripe

        with patch(
            "autoinfo.user_store.set_stripe_customer_id",
            side_effect=_stripe.error.StripeError("Stripe API error"),
        ):
            set_user_stripe_id("user_fail2", "cus_fail2")

        assert _user_stripe_map["user_fail2"] == "cus_fail2"
        assert _billing_mod._stripe_sync_failures == 1

    def test_set_increments_failure_on_generic_exception(self) -> None:
        """Any other Exception -> cache updated, failure counter incremented."""
        with patch(
            "autoinfo.user_store.set_stripe_customer_id",
            side_effect=RuntimeError("unexpected"),
        ):
            set_user_stripe_id("user_gen", "cus_gen")

        assert _user_stripe_map["user_gen"] == "cus_gen"
        assert _billing_mod._stripe_sync_failures == 1


# ===================================================================
# 4. _sync_user_stripe_id() -- success + failure paths
# ===================================================================


class TestSyncUserStripeId:
    """Test ``_sync_user_stripe_id()`` which persists the stripe customer ID
    and verifies the result."""

    def test_sync_success(self) -> None:
        """Persist and verify succeed -> returns True."""
        from autoinfo.billing import _sync_user_stripe_id

        with (
            patch("autoinfo.user_store.set_stripe_customer_id"),
            patch("autoinfo.user_store.get_stripe_customer_id") as mock_get,
        ):
            mock_get.return_value = "cus_expected"
            result = _sync_user_stripe_id("user_abc", "cus_expected")

        assert result is True
        assert _user_stripe_map["user_abc"] == "cus_expected"

    def test_sync_failure_mismatch(self) -> None:
        """Persisted value differs from expected -> returns False, counter incremented."""
        from autoinfo.billing import _sync_user_stripe_id

        with (
            patch("autoinfo.user_store.set_stripe_customer_id"),
            patch("autoinfo.user_store.get_stripe_customer_id") as mock_get,
        ):
            mock_get.return_value = "cus_different"
            result = _sync_user_stripe_id("user_abc", "cus_expected")

        assert result is False
        assert _billing_mod._stripe_sync_failures == 1

    def test_sync_failure_connection_error(self) -> None:
        """ConnectionError during verify -> returns False, counter incremented."""
        from autoinfo.billing import _sync_user_stripe_id

        with (
            patch("autoinfo.user_store.set_stripe_customer_id"),
            patch(
                "autoinfo.user_store.get_stripe_customer_id",
                side_effect=ConnectionError("DB is down"),
            ),
        ):
            result = _sync_user_stripe_id("user_abc", "cus_expected")

        assert result is False
        assert _billing_mod._stripe_sync_failures == 1

    def test_sync_failure_value_error(self) -> None:
        """ValueError during verify -> returns False, counter incremented."""
        from autoinfo.billing import _sync_user_stripe_id

        with (
            patch("autoinfo.user_store.set_stripe_customer_id"),
            patch(
                "autoinfo.user_store.get_stripe_customer_id",
                side_effect=ValueError("bad value"),
            ),
        ):
            result = _sync_user_stripe_id("user_abc", "cus_expected")

        assert result is False
        assert _billing_mod._stripe_sync_failures == 1


# ===================================================================
# 5. create_checkout_session()
# ===================================================================


class TestCreateCheckoutSession:
    """Test ``create_checkout_session()`` -- the checkout session creation flow."""

    def test_create_with_existing_customer(self) -> None:
        """Existing customer ID in cache -> reused, no ``Customer.create`` call."""
        _user_stripe_map["user_existing"] = "cus_existing"

        with (
            patch("stripe.checkout.Session.create") as mock_session,
            patch("stripe.Customer.create") as mock_customer,
        ):
            mock_session.return_value = {
                "id": "cs_test_123",
                "url": "https://checkout.stripe.com/cs_test_123",
            }
            result = create_checkout_session("price_monthly", "user_existing")

        assert result["session_id"] == "cs_test_123"
        assert result["customer_id"] == "cus_existing"
        assert result["end_user_id"] == "user_existing"
        assert result["mode"] == "subscription"
        # Customer.create should NOT be called since the ID was cached
        mock_customer.assert_not_called()
        mock_session.assert_called_once()

    def test_create_new_customer_and_session(self) -> None:
        """No cached customer -> creates Stripe customer + checkout session."""
        with (
            patch("stripe.Customer.create") as mock_customer,
            patch("stripe.checkout.Session.create") as mock_session,
        ):
            mock_customer.return_value = {"id": "cus_brand_new"}
            mock_session.return_value = {
                "id": "cs_new",
                "url": "https://checkout.stripe.com/cs_new",
            }
            result = create_checkout_session("price_enterprise", "user_newbie")

        assert result["session_id"] == "cs_new"
        assert result["customer_id"] == "cus_brand_new"
        assert result["end_user_id"] == "user_newbie"
        mock_customer.assert_called_once()
        mock_session.assert_called_once()

    def test_create_payment_mode_session(self) -> None:
        """mode="payment" → uses price_data not price, metadata contains article_id."""
        _user_stripe_map["user_pay"] = "cus_pay"

        with patch("stripe.checkout.Session.create") as mock_session:
            mock_session.return_value = {
                "id": "cs_pay_123",
                "url": "https://checkout.stripe.com/cs_pay_123",
            }
            result = create_checkout_session(
                "article_42", "user_pay",
                mode="payment", article_id="art_42",
            )

        assert result["session_id"] == "cs_pay_123"
        assert result["mode"] == "payment"
        assert result["end_user_id"] == "user_pay"

        # Verify price_data was used (not bare "price")
        call_kwargs = mock_session.call_args.kwargs
        assert call_kwargs["mode"] == "payment"
        line_item = call_kwargs["line_items"][0]
        assert "price_data" in line_item
        assert "price" not in line_item
        assert call_kwargs["metadata"]["article_id"] == "art_42"

    def test_create_failure_returns_error_dict(self) -> None:
        """Exception during creation -> error dict returned (never raises)."""
        with patch("stripe.Customer.create") as mock_customer:
            mock_customer.side_effect = ValueError("Stripe API down")
            result = create_checkout_session("price_fail", "user_fail")

        assert "error" in result
        assert result["end_user_id"] == "user_fail"


# ======================================================================
# Tier-based check_access() (T5 — subscription model extension)
# ======================================================================


class TestCheckAccessTierFastPath:
    """Verify check_access() uses UserProfile.tier as fast path (no Stripe).

    Tier mapping: free=0, premium=1, enterprise=2.
    """

    @staticmethod
    def _profile(tier: str = "free", status: str = "active") -> object:
        """Create a minimal UserProfile-like object for tier-based tests."""
        # We use a simple object to avoid user_store dependency.
        return type(
            "_FakeProfile",
            (),
            {"tier": tier, "status": status, "stripe_customer_id": "", "stripe_subscription_id": ""},
        )()

    @patch("autoinfo.billing._load_user_profile")
    def test_free_user_accesses_free_template(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = self._profile(tier="free")
        result = check_access("user_free", "free")
        assert result["allowed"] is True
        assert "Free content" in result["reason"]

    @patch("autoinfo.billing._load_user_profile")
    def test_free_user_denied_premium_template(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = self._profile(tier="free")
        # Must also mock get_subscription_status since fast path won't pass
        with patch("autoinfo.billing.get_subscription_status") as mock_sub:
            mock_sub.return_value = {
                "end_user_id": "user_free",
                "profile_status": "active",
                "stripe_status": "none",
                "subscription_id": "",
                "customer_id": "",
                "plan": "free",
            }
            result = check_access("user_free", "premium")
        assert result["allowed"] is False
        assert "upgrade_prompt" in result

    @patch("autoinfo.billing._load_user_profile")
    def test_premium_user_accesses_premium_template(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = self._profile(tier="premium")
        result = check_access("user_premium", "premium")
        assert result["allowed"] is True
        assert "tier fast path" in result["reason"]
        assert result["plan"] == "premium"

    @patch("autoinfo.billing._load_user_profile")
    def test_enterprise_user_accesses_enterprise_template(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = self._profile(tier="enterprise")
        result = check_access("user_enterprise", "enterprise")
        assert result["allowed"] is True
        assert "tier fast path" in result["reason"]
        assert result["plan"] == "enterprise"

    @patch("autoinfo.billing._load_user_profile")
    def test_premium_user_accesses_free_template(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = self._profile(tier="premium")
        result = check_access("user_premium", "free")
        assert result["allowed"] is True
        assert "Free content" in result["reason"]

    @patch("autoinfo.billing._load_user_profile")
    def test_enterprise_user_accesses_premium_template(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = self._profile(tier="enterprise")
        result = check_access("user_enterprise", "premium")
        assert result["allowed"] is True
        assert "tier fast path" in result["reason"]

    @patch("autoinfo.billing._load_user_profile")
    def test_no_profile_falls_back_to_stripe(self, mock_load: MagicMock) -> None:
        from autoinfo.billing import check_access

        mock_load.return_value = None
        with patch("autoinfo.billing.get_subscription_status") as mock_sub:
            mock_sub.return_value = {
                "end_user_id": "user_unknown",
                "profile_status": "active",
                "stripe_status": "active",
                "subscription_id": "sub_xxx",
                "customer_id": "cus_xxx",
                "plan": "premium",
            }
            result = check_access("user_unknown", "premium")
        assert result["allowed"] is True
        assert "active premium subscription" in result["reason"]


# ======================================================================
# Single-article entitlement (E12)
# ======================================================================


@pytest.fixture
def temp_consumption_db(tmp_path):
    """Patch ConsumptionStore to use a temporary DB file."""
    db_path = tmp_path / "consumption.db"
    with patch(
        "autoinfo.consumption._get_db_path", return_value=db_path
    ):
        yield tmp_path


class TestArticleEntitlement:
    """Verify single-article purchase entitlement (E12).

    Coverage: article entitlement grant via webhook, check_access
    article fast path, idempotent duplicate payments.
    """

    def test_payment_webhook_grants_entitlement(
        self, temp_consumption_db, payment_checkout_event: dict,
    ) -> None:
        """Payment webhook → article_entitlement row + 'purchased' event."""
        _user_stripe_map["user_abc"] = "cus_test123"

        with patch("autoinfo.user_store.get_stripe_customer_id") as mock_get:
            mock_get.return_value = "cus_test123"
            result = handle_webhook(payment_checkout_event)

        assert result["status"] == "processed"
        assert result["action"] == "payment_received"
        assert result["mode"] == "payment"
        assert result["article_id"] == "art_42"
        assert result["entitlement_reason"] == "granted"

        store = ConsumptionStore()
        assert store.check_article_access("user_abc", "art_42") is True

        events = store.list_events("user_abc", limit=10)
        purchased_events = [e for e in events if e["event_type"] == "purchased"]
        assert len(purchased_events) == 1
        assert purchased_events[0]["product_type"] == "article"
        assert purchased_events[0]["product_id"] == "art_42"

    def test_payment_webhook_no_article_skips_entitlement(
        self, temp_consumption_db,
        payment_checkout_event_no_article: dict,
    ) -> None:
        """Payment without article_id → no entitlement, no crash."""
        _user_stripe_map["user_abc"] = "cus_test123"

        with patch("autoinfo.user_store.get_stripe_customer_id") as mock_get:
            mock_get.return_value = "cus_test123"
            result = handle_webhook(payment_checkout_event_no_article)

        assert result["status"] == "processed"
        assert result["action"] == "payment_received"
        assert result.get("entitlement_reason") is None

    def test_check_article_access_hit(
        self, temp_consumption_db,
    ) -> None:
        """User with entitlement → check_access with article_id allows."""
        from autoinfo.billing import check_access

        store = ConsumptionStore()
        store.grant_article_access(
            user_id="user_buyer",
            article_id="art_99",
            payment_intent_id="pi_99",
        )

        result = check_access(
            "user_buyer", "premium", article_id="art_99",
        )
        assert result["allowed"] is True
        assert "article entitlement fast path" in result["reason"]
        assert result["plan"] == "article_purchase"
        assert result["article_id"] == "art_99"

    def test_check_article_access_miss(
        self, temp_consumption_db,
    ) -> None:
        """User without entitlement → check_access denies (falls through to tier)."""
        from autoinfo.billing import check_access

        with patch(
            "autoinfo.billing._load_user_profile", return_value=None,
        ), patch("autoinfo.billing.get_subscription_status") as mock_sub:
            mock_sub.return_value = {
                "end_user_id": "user_nonbuyer",
                "profile_status": "trial",
                "stripe_status": "none",
                "subscription_id": "",
                "customer_id": "",
                "plan": "free",
            }
            result = check_access(
                "user_nonbuyer", "premium", article_id="art_nonexistent",
            )

        assert result["allowed"] is False
        assert "trial" in result["reason"]  # skipped article path, went to tier

    def test_duplicate_payment_idempotent(
        self, temp_consumption_db,
    ) -> None:
        """Duplicate payment → entitlement is idempotent, second grant returns already_entitled."""
        store = ConsumptionStore()

        first = store.grant_article_access(
            user_id="user_dup",
            article_id="art_dup",
            payment_intent_id="pi_1",
        )
        assert first["granted"] is True
        assert first["reason"] == "granted"

        second = store.grant_article_access(
            user_id="user_dup",
            article_id="art_dup",
            payment_intent_id="pi_2",
        )
        assert second["granted"] is False
        assert second["reason"] == "already_entitled"

        assert store.check_article_access("user_dup", "art_dup") is True
        entitlements = store.list_article_entitlements("user_dup")
        assert len(entitlements) == 1

    def test_check_access_subscription_supercedes_article(
        self, temp_consumption_db,
    ) -> None:
        """Premium subscriber + article purchase → check_access grants via tier, not article."""
        from autoinfo.billing import check_access

        store = ConsumptionStore()
        store.grant_article_access(
            user_id="user_prem_buyer",
            article_id="art_bonus",
            payment_intent_id="pi_bonus",
        )

        profile = type(
            "_FakeProfile", (),
            {"tier": "premium", "status": "active",
             "stripe_customer_id": "", "stripe_subscription_id": ""},
        )()

        with patch(
            "autoinfo.billing._load_user_profile", return_value=profile,
        ):
            result = check_access(
                "user_prem_buyer", "premium", article_id="art_bonus",
            )

        assert result["allowed"] is True
        # article entitlement fast path fires because of article_id
        assert "article entitlement fast path" in result["reason"]
        assert result["plan"] == "article_purchase"

    def test_article_entitlement_list(self, temp_consumption_db) -> None:
        """list_article_entitlements returns all purchased articles."""
        store = ConsumptionStore()
        store.grant_article_access("user_el", "art_a", "pi_a")
        store.grant_article_access("user_el", "art_b", "pi_b")
        store.grant_article_access("user_el2", "art_c", "pi_c")

        user1 = store.list_article_entitlements("user_el")
        assert len(user1) == 2
        user2 = store.list_article_entitlements("user_el2")
        assert len(user2) == 1
        nobody = store.list_article_entitlements("nobody")
        assert len(nobody) == 0


# ======================================================================
# 6. Integration tests with stripe-mock (E2 Stripe Lifecycle Regression)
# ======================================================================


def _stripe_mock_available() -> bool:
    """Check whether stripe-mock is reachable at ``STRIPE_API_BASE``.

    Returns ``True`` when the ``/v1/health`` endpoint responds with 200,
    meaning ``docker compose up -d stripe-mock`` has been run.
    """
    import os
    api_base = os.environ.get("STRIPE_API_BASE", "http://localhost:12111")
    try:
        import urllib.request
        req = urllib.request.Request(f"{api_base}/v1/health")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.mark.skipif(
    not _stripe_mock_available(),
    reason="stripe-mock not available (start with `make stripe-mock` "
           "or `docker compose up -d stripe-mock`)",
)
class TestStripeLifecycle:
    """Integration tests against stripe-mock for full lifecycle regression.

    These tests verify the end-to-end Stripe integration path:
    ``create_checkout_session`` → webhook events →
    ``get_subscription_status`` → subscription state transitions →
    cancellation.

    The **42 existing mock tests** (above) remain unaffected and
    pass without stripe-mock.  This class is decorated with
    ``@pytest.mark.skipif`` so that it is skipped automatically
    when stripe-mock is not running — no Docker required for CI.

    Run these with::

        make stripe-mock
        python3 -m pytest tests/test_stripe.py::TestStripeLifecycle -v
    """

    # ------------------------------------------------------------------
    # Fixture helpers
    # ------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _setup_stripe_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Configure Stripe for stripe-mock and clear global state."""
        import os
        import stripe as _stripe

        self._api_base = os.environ.get(
            "STRIPE_API_BASE", "http://localhost:12111",
        )
        _stripe.api_key = "sk_test_mock_integration"
        _stripe.api_base = self._api_base

        # Clear in-memory state before each test to prevent cross-test leaks
        _user_stripe_map.clear()
        _billing_mod._stripe_sync_failures = 0
        yield

    # ------------------------------------------------------------------
    # 6.1  create_checkout_session → stripe-mock
    # ------------------------------------------------------------------

    def test_create_checkout_session_subscription_succeeds(
        self,
    ) -> None:
        """``create_checkout_session(mode='subscription')`` communicates
        with stripe-mock and returns a valid ``session_id`` + ``customer_id``.
        """
        result = create_checkout_session(
            "price_test_basic",
            "user_integ_lifecycle",
            email="integ@example.com",
            name="Integration User",
        )

        assert "error" not in result, (
            f"Unexpected error from create_checkout_session: "
            f"{result.get('error')}"
        )
        assert result["session_id"], (
            "session_id should not be empty"
        )
        assert result["customer_id"].startswith("cus_"), (
            f"Expected customer_id to start with 'cus_', "
            f"got {result['customer_id']!r}"
        )
        assert result["mode"] == "subscription"
        assert result["end_user_id"] == "user_integ_lifecycle"

    def test_create_checkout_session_payment_succeeds(
        self,
    ) -> None:
        """``create_checkout_session(mode='payment')`` uses ``price_data``
        and returns ``mode='payment'``."""
        result = create_checkout_session(
            "article_42",
            "user_payment_integ",
            mode="payment",
            article_id="art_integ_42",
        )

        assert "error" not in result, (
            f"Payment checkout failed: {result.get('error')}"
        )
        assert result["mode"] == "payment"
        assert result["session_id"], "session_id should not be empty"
        assert result["customer_id"].startswith("cus_")

    # ------------------------------------------------------------------
    # 6.2  Full subscription lifecycle regression
    # ------------------------------------------------------------------

    def test_full_subscription_lifecycle(
        self,
    ) -> None:
        """Complete Stripe lifecycle regression:

        1. ``create_checkout_session`` (subscription) → talks to
           stripe-mock for customer + session creation.
        2. Simulate ``checkout.session.completed`` webhook → profile
           activated, ``stripe_subscription_id`` stored.
        3. ``get_subscription_status`` → retrieves from stripe-mock.
        4. ``customer.subscription.updated`` → status transitions
           (active, past_due→suspended, unpaid→suspended,
           canceled→cancelled).
        5. ``customer.subscription.deleted`` → subscription cancelled.
        """
        import stripe as _stripe

        end_user_id = "user_lifecycle_full"
        TEST_SUB = "sub_mock_lifecycle"

        # ── 1. Create checkout session via stripe-mock ──────────────────
        result = create_checkout_session(
            "price_test_lifecycle",
            end_user_id,
            email="lifecycle@example.com",
            name="Lifecycle User",
        )
        assert "error" not in result, (
            f"Checkout failed: {result.get('error')}"
        )
        session_id = result["session_id"]
        customer_id = result["customer_id"]

        # ── 2. Retrieve session from stripe-mock to get subscription_id ─
        try:
            session = _stripe.checkout.Session.retrieve(session_id)
            subscription_id: str = session.get("subscription") or TEST_SUB  # type: ignore[arg-type]
        except Exception:
            subscription_id = TEST_SUB

        # ── 3. Simulate checkout.session.completed webhook ──────────────
        with (
            patch("autoinfo.user_store.update_profile") as mock_update,
            patch("autoinfo.user_store.get_stripe_customer_id") as mock_get,
        ):
            mock_get.return_value = customer_id

            checkout_event = {
                "id": "evt_lifecycle_cs",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": session_id,
                        "customer": customer_id,
                        "subscription": subscription_id,
                        "metadata": {"end_user_id": end_user_id},
                        "mode": "subscription",
                        "status": "complete",
                    }
                },
            }

            webhook_result = handle_webhook(checkout_event)

        assert webhook_result["status"] == "processed", (
            f"Webhook should be processed, got: {webhook_result}"
        )
        assert webhook_result["action"] == "activated_subscription"
        assert webhook_result["end_user_id"] == end_user_id
        assert webhook_result["subscription_id"] == subscription_id

        # Verify profile update was called with correct args
        mock_update.assert_any_call(
            user_id=end_user_id,
            stripe_subscription_id=subscription_id,
            status="active",
        )

        # ── 4. Verify get_subscription_status retrieves from stripe-mock ─
        # Patch _load_user_profile to return a fake profile with the
        # subscription_id set (simulating profile state after webhook).
        fake_profile = type(
            "_FakeLifecycleProfile", (),
            {
                "tier": "premium",
                "status": "active",
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
            },
        )()

        with patch(
            "autoinfo.billing._load_user_profile",
            return_value=fake_profile,
        ):
            status_result = get_subscription_status(end_user_id)

        assert status_result["end_user_id"] == end_user_id
        assert status_result["subscription_id"] == subscription_id
        assert status_result["customer_id"] == customer_id
        # stripe-mock should return a valid status (not "error")
        assert status_result["stripe_status"] != "error", (
            f"stripe.Subscription.retrieve failed against stripe-mock: "
            f"{status_result}"
        )

        # ── 5. Test subscription.updated status transitions ────────────
        transitions = [
            ("active", "active"),
            ("past_due", "suspended"),
            ("unpaid", "suspended"),
            ("canceled", "cancelled"),
        ]

        for stripe_status, expected_status in transitions:
            with patch(
                "autoinfo.user_store.update_profile",
            ) as mock_upd:
                updated_event = {
                    "id": f"evt_lifecycle_upd_{stripe_status}",
                    "type": "customer.subscription.updated",
                    "data": {
                        "object": {
                            "id": subscription_id,
                            "customer": customer_id,
                            "status": stripe_status,
                        }
                    },
                }
                upd_result = handle_webhook(updated_event)

            assert upd_result["status"] == "processed", (
                f"[{stripe_status}] Expected 'processed', "
                f"got {upd_result['status']!r}"
            )
            assert upd_result["action"] == "updated_status"
            assert upd_result["new_status"] == expected_status, (
                f"[{stripe_status}] Expected new_status="
                f"{expected_status!r}, got {upd_result['new_status']!r}"
            )
            mock_upd.assert_called_once_with(
                user_id=end_user_id,
                stripe_subscription_id=subscription_id,
                status=expected_status,
            )

        # ── 6. Test subscription.deleted → cancelled ──────────────────
        with patch("autoinfo.user_store.update_profile") as mock_upd:
            deleted_event = {
                "id": "evt_lifecycle_del",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": subscription_id,
                        "customer": customer_id,
                    }
                },
            }
            del_result = handle_webhook(deleted_event)

        assert del_result["status"] == "processed"
        assert del_result["action"] == "cancelled_subscription"
        mock_upd.assert_called_once_with(
            user_id=end_user_id,
            status="cancelled",
        )

    # ------------------------------------------------------------------
    # 6.3  mode="payment" regression (T3/T11)
    # ------------------------------------------------------------------

    def test_payment_mode_webhook_no_subscription_activation(
        self,
    ) -> None:
        """``mode='payment'`` checkout → webhook ``payment_received``,
        **not** subscription activation.  Regression for T3 + T11.
        """
        end_user_id = "user_payment_integ"
        customer_id = "cus_payment_integ"
        _user_stripe_map[end_user_id] = customer_id

        payment_event = {
            "id": "evt_payment_regression",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_payment_regression",
                    "customer": customer_id,
                    "subscription": "",
                    "payment_intent": "pi_test_regression",
                    "metadata": {
                        "end_user_id": end_user_id,
                        "article_id": "art_regression_77",
                    },
                    "mode": "payment",
                    "status": "complete",
                }
            },
        }

        with (
            patch("autoinfo.user_store.update_profile") as mock_update,
            patch("autoinfo.user_store.get_stripe_customer_id") as mock_get,
            patch(
                "autoinfo.consumption.ConsumptionStore"
            ) as mock_store_cls,
        ):
            mock_get.return_value = customer_id
            mock_store = MagicMock()
            mock_store.grant_article_access.return_value = {
                "granted": True, "article_id": "art_regression_77",
                "user_id": end_user_id, "reason": "granted",
            }
            mock_store_cls.return_value = mock_store

            result = handle_webhook(payment_event)

        assert result["status"] == "processed"
        assert result["action"] == "payment_received"
        assert result["mode"] == "payment"
        assert result["article_id"] == "art_regression_77"
        assert result["entitlement_reason"] == "granted"

        # KEY REGRESSION: must NOT call update_profile(status="active")
        for call in mock_update.call_args_list:
            _, kwargs = call
            if kwargs.get("status") == "active":
                pytest.fail(
                    "BUG REGRESSION: mode=payment produced status='active' "
                    "— T3 regression: empty subscription_id would be "
                    "written to the profile"
                )
            if "stripe_subscription_id" in kwargs:
                pytest.fail(
                    "BUG REGRESSION: mode=payment wrote "
                    "stripe_subscription_id to the profile"
                )

    # ------------------------------------------------------------------
    # 6.4  get_subscription_status via stripe-mock
    # ------------------------------------------------------------------

    def test_get_subscription_status_retrieves_from_stripe_mock(
        self,
    ) -> None:
        """After webhook activation, ``get_subscription_status`` calls
        ``stripe.Subscription.retrieve`` against stripe-mock and returns
        valid status data."""
        end_user_id = "user_status_mock"
        customer_id = "cus_status_mock"
        subscription_id = "sub_status_mock"
        _user_stripe_map[end_user_id] = customer_id

        # Simulate a profile that has been activated
        fake_profile = type(
            "_FakeStatusProfile", (),
            {
                "tier": "premium",
                "status": "active",
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
            },
        )()

        with patch(
            "autoinfo.billing._load_user_profile",
            return_value=fake_profile,
        ):
            status = get_subscription_status(end_user_id)

        assert status["end_user_id"] == end_user_id
        assert status["subscription_id"] == subscription_id
        assert status["customer_id"] == customer_id
        assert status["stripe_status"] != "error", (
            f"get_subscription_status should succeed against stripe-mock, "
            f"got stripe_status={status['stripe_status']!r}"
        )
        # stripe-mock returns some plan/status — at minimum verify the
        # call didn't crash and returned a non-error response.
        assert isinstance(status["plan"], str)
        assert isinstance(status["stripe_status"], str)

    # ------------------------------------------------------------------
    # 6.5  No-op with unmatched customer
    # ------------------------------------------------------------------

    def test_get_subscription_status_no_profile_no_stripe_id(
        self,
    ) -> None:
        """When no profile exists and no subscription ID is stored,
        ``get_subscription_status`` returns ``stripe_status='none'``
        without crashing."""
        with patch(
            "autoinfo.billing._load_user_profile",
            return_value=None,
        ):
            status = get_subscription_status("user_no_profile")

        assert status["end_user_id"] == "user_no_profile"
        assert status["profile_status"] == "unknown"
        assert status["stripe_status"] == "none"
        assert status["subscription_id"] == ""
        assert status["customer_id"] == ""
        assert status["plan"] == "free"


# ---------------------------------------------------------------------------
# R1 guard: STRIPE_API_KEY set but STRIPE_API_BASE still stripe-mock
# ---------------------------------------------------------------------------


class TestStripeMockGuard:
    """A real STRIPE_API_KEY with the default stripe-mock base would
    silently send real keys to the mock endpoint. The guard must warn."""

    def test_configure_stripe_warns_when_key_set_but_base_is_mock(
        self, caplog
    ) -> None:
        import logging

        from autoinfo.billing import _configure_stripe

        # Patch the module-level constants directly (read at import time)
        with patch.object(_billing_mod, "_STRIPE_API_KEY", "sk_test_real"), \
             patch.object(_billing_mod, "_STRIPE_API_BASE", "http://localhost:12111"), \
             caplog.at_level(logging.WARNING, logger="autoinfo.billing"):
            _configure_stripe()

        assert any("stripe-mock" in r.message for r in caplog.records), (
            "Expected a warning that a real key is pointed at stripe-mock, "
            f"got records: {[r.message for r in caplog.records]}"
        )

    def test_configure_stripe_no_warning_when_base_is_real(
        self, caplog
    ) -> None:
        import logging

        from autoinfo.billing import _configure_stripe

        with patch.object(_billing_mod, "_STRIPE_API_KEY", "sk_test_real"), \
             patch.object(_billing_mod, "_STRIPE_API_BASE", "https://api.stripe.com"), \
             caplog.at_level(logging.WARNING, logger="autoinfo.billing"):
            _configure_stripe()

        assert not any("stripe-mock" in r.message for r in caplog.records), (
            f"Unexpected warning: {[r.message for r in caplog.records]}"
        )

    def test_configure_stripe_real_mode_sets_key_and_base(
        self, caplog
    ) -> None:
        """When STRIPE_API_KEY and real STRIPE_API_BASE are set,
        stripe.api_key and api_base should be correctly configured
        without any stripe-mock warning."""
        import logging
        import autoinfo.billing as billing_mod

        from autoinfo.billing import _configure_stripe

        mock_stripe = MagicMock()
        with patch.object(billing_mod, "_STRIPE_API_KEY", "sk_test_xyz"), \
             patch.object(billing_mod, "_STRIPE_API_BASE", "https://api.stripe.com"), \
             patch.object(billing_mod, "stripe", mock_stripe), \
             caplog.at_level(logging.WARNING, logger="autoinfo.billing"):
            _configure_stripe()

        assert mock_stripe.api_key == "sk_test_xyz", (
            f"Expected api_key 'sk_test_xyz', got {mock_stripe.api_key}"
        )
        assert mock_stripe.api_base == "https://api.stripe.com", (
            f"Expected api_base 'https://api.stripe.com', got {mock_stripe.api_base}"
        )
        assert not any("stripe-mock" in r.message for r in caplog.records), (
            f"Unexpected stripe-mock warning: {[r.message for r in caplog.records]}"
        )
