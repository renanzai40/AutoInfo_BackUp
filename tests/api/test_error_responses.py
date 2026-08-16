# mypy: ignore-errors
"""Tests for REST API error responses.

Verifies that all error paths return the canonical error envelope:

    ``{success: False, error: {code, message, actionable}}``

Covers:
    - Unhandled exception (catch-all ``@app.exception_handler(Exception)``)
    - ``ValueError`` → 400 ``ValidationError``
    - ``KeyError`` → 400 ``ValidationError``
    - ``HTTPException`` → mapped status with ``ValidationError`` / ``InternalError``
    - Pydantic validation → 422 (FastAPI default ``detail`` list)
    - Nonexistent domain → 404 ``DomainNotFound`` (middleware + route handler)
    - Error envelope format on every custom error path
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from autoinfo.kb import KBStore

# ---------------------------------------------------------------------------
# Fixture: isolated TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Return a ``TestClient`` with isolated config + working directory.

    Creates a minimal ``.autoinfo/config.yaml`` with *no* domains configured,
    changes the CWD to *tmp_path* so ``KBStore`` creates its SQLite database
    in an isolated directory, and patches ``get_config_path`` so that
    ``_known_domains()`` returns an empty set.
    """
    import autoinfo.api.routes as routes
    from autoinfo.api.server import app

    # -- minimal config (no domains → _known_domains() returns empty) ---------
    config_dir = tmp_path / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        "rest_api:\n  host: 127.0.0.1\n  port: 8741\n"
    )

    # -- isolate the KB store inside tmp_path --------------------------------
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    with patch("autoinfo.config.get_config_path", return_value=config_path):
        yield TestClient(app, raise_server_exceptions=False)

    os.chdir(old_cwd)
    routes._store = None


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------


def _assert_error_envelope(
    response, status_code: int, error_code: str, *, actionable: bool | None = None,
) -> None:
    """Assert that *response* has the canonical
    ``{success, error: {code, message, actionable}}`` envelope.
    """
    assert response.status_code == status_code, (
        f"Expected status {status_code}, got {response.status_code}: {response.text[:200]}"
    )
    try:
        data = response.json()
    except Exception:
        pytest.fail(f"Response body is not valid JSON: {response.text[:200]}")

    assert data.get("success") is False, (
        f"Expected success=False, got {data}"
    )
    assert "error" in data, f"Expected 'error' key in response: {data}"
    error = data["error"]
    assert error.get("code") == error_code, (
        f"Expected error code '{error_code}', got '{error.get('code')}': {data}"
    )
    assert isinstance(error.get("message"), str) and len(error["message"]) > 0, (
        f"Expected non-empty error message, got {error.get('message')!r}"
    )
    assert "actionable" in error, f"Missing 'actionable' field in error: {error}"
    if actionable is not None:
        assert error["actionable"] is actionable, (
            f"Expected actionable={actionable}, got {error['actionable']}"
        )


def _assert_success_envelope(
    response, status_code: int = 200, *, data_check=None,
) -> dict:
    """Assert *response* has the canonical ``{success: True, data: ...}`` envelope.

    Returns the unwrapped ``data`` value for further assertions.
    """
    assert response.status_code == status_code, (
        f"Expected status {status_code}, got {response.status_code}: {response.text[:200]}"
    )
    try:
        data = response.json()
    except Exception:
        pytest.fail(f"Response body is not valid JSON: {response.text[:200]}")

    assert data.get("success") is True, (
        f"Expected success=True, got {data}"
    )
    assert "data" in data, f"Expected 'data' key in response: {data}"
    if data_check is not None:
        data_check(data["data"])
    return data["data"]


# ===================================================================
# Tests
# ===================================================================


class TestUnhandledException:
    """``@app.exception_handler(Exception)`` — catch-all → 500 InternalError."""

    def test_runtime_error_returns_500_envelope(self, client: TestClient) -> None:
        """An unhandled ``RuntimeError`` from within a route handler returns
        a 500 response with the canonical error envelope and ``InternalError``
        code.
        """
        with patch.object(
            KBStore,
            "store_entry",
            side_effect=RuntimeError("database connection failed"),
        ):
            resp = client.post(
                "/api/v1/entries",
                json={
                    "title": "Test Article",
                    "content": (
                        "This is a sufficiently long body for the "
                        "exception-mapping tests, well above the "
                        "fifty-character minimum content guard that every "
                        "KB write boundary now enforces."
                    ),
                },
            )

        _assert_error_envelope(resp, 500, "InternalError", actionable=False)
        assert "database connection failed" in resp.json()["error"]["message"]

    def test_arbitrary_exception_returns_internal_error(
        self, client: TestClient
    ) -> None:
        """Any exception class not specifically registered gets mapped to
        ``InternalError`` (500).
        """
        with patch.object(
            KBStore,
            "store_entry",
            side_effect=ConnectionError("upstream service unavailable"),
        ):
            resp = client.post(
                "/api/v1/entries",
                json={
                    "title": "Fail",
                    "content": (
                        "This is a sufficiently long body for the "
                        "exception-mapping tests, well above the "
                        "fifty-character minimum content guard that every "
                        "KB write boundary now enforces."
                    ),
                },
            )

        _assert_error_envelope(resp, 500, "InternalError", actionable=False)
        assert "upstream service unavailable" in resp.json()["error"]["message"]


class TestValueError:
    """``@app.exception_handler(ValueError)`` → 400 ValidationError."""

    def test_value_error_returns_400_envelope(self, client: TestClient) -> None:
        """A ``ValueError`` raised during response construction returns 400
        with ``ValidationError`` code.
        """
        with patch(
            "autoinfo.api.routes._entry_to_response",
            side_effect=ValueError("invalid field value"),
        ):
            resp = client.post(
                "/api/v1/entries",
                json={
                    "title": "Test Article",
                    "content": (
                        "This is a sufficiently long body for the "
                        "exception-mapping tests, well above the "
                        "fifty-character minimum content guard that every "
                        "KB write boundary now enforces."
                    ),
                },
            )

        _assert_error_envelope(resp, 400, "ValidationError", actionable=True)
        assert "invalid field value" in resp.json()["error"]["message"]


class TestKeyError:
    """``@app.exception_handler(KeyError)`` → 400 ValidationError."""

    def test_key_error_returns_400_envelope(self, client: TestClient) -> None:
        """A ``KeyError`` raised during response construction returns 400
        with ``ValidationError`` code.
        """
        with patch(
            "autoinfo.api.routes._entry_to_response",
            side_effect=KeyError("missing_key"),
        ):
            resp = client.post(
                "/api/v1/entries",
                json={
                    "title": "Test Article",
                    "content": (
                        "This is a sufficiently long body for the "
                        "exception-mapping tests, well above the "
                        "fifty-character minimum content guard that every "
                        "KB write boundary now enforces."
                    ),
                },
            )

        _assert_error_envelope(resp, 400, "ValidationError", actionable=True)
        assert "missing_key" in resp.json()["error"]["message"]


class TestHTTPException:
    """``@app.exception_handler(HTTPException)`` — mapped to envelope."""

    def test_entry_not_found_returns_404_envelope(self, client: TestClient) -> None:
        """Requesting a non-existent entry returns 404 with ``ValidationError``."""
        resp = client.get("/api/v1/entries/non-existent-entry-999")

        _assert_error_envelope(resp, 404, "ValidationError", actionable=True)
        assert "not found" in resp.json()["error"]["message"].lower()
        assert "non-existent-entry-999" in resp.json()["error"]["message"]

    def test_permission_error_returns_400_envelope(self, client: TestClient) -> None:
        """``PermissionError`` (e.g. write to 03-Wiki) maps to 400."""
        with patch.object(
            KBStore,
            "store_entry",
            side_effect=PermissionError("Cannot write to 03-Wiki"),
        ):
            resp = client.post(
                "/api/v1/entries",
                json={
                    "title": "Test",
                    "content": (
                        "This is a sufficiently long body for the "
                        "exception-mapping tests, well above the "
                        "fifty-character minimum content guard that every "
                        "KB write boundary now enforces."
                    ),
                },
            )

        _assert_error_envelope(resp, 400, "ValidationError", actionable=True)
        assert "Cannot write to 03-Wiki" in resp.json()["error"]["message"]

    def test_deleted_entry_via_delete_returns_204(self, client: TestClient) -> None:
        """DELETE on a non-existent entry returns 404 envelope (not 204)."""
        # The KB store is empty, so delete_entry returns {"deleted": False}
        with patch.object(
            KBStore,
            "delete_entry",
            return_value={"deleted": False, "error": "Entry 'ghost' not found"},
        ):
            resp = client.delete("/api/v1/entries/ghost")

        _assert_error_envelope(resp, 404, "ValidationError", actionable=True)
        assert "not found" in resp.json()["error"]["message"].lower()


class TestMissingParams:
    """Pydantic validation → 422 with canonical error envelope."""

    def test_missing_title_returns_422(self, client: TestClient) -> None:
        """POST without the required ``title`` field returns 422 with a
        canonical error envelope and ``ValidationError`` code.
        """
        resp = client.post("/api/v1/entries", json={})
        _assert_error_envelope(resp, 422, "ValidationError", actionable=True)

    def test_empty_title_returns_422(self, client: TestClient) -> None:
        """POST with an empty ``title`` returns 422 envelope."""
        resp = client.post("/api/v1/entries", json={"title": ""})
        _assert_error_envelope(resp, 422, "ValidationError", actionable=True)

    def test_invalid_limit_returns_422(self, client: TestClient) -> None:
        """GET with ``limit`` outside the allowed range returns 422 envelope."""
        resp = client.get("/api/v1/search?q=test&limit=999")
        _assert_error_envelope(resp, 422, "ValidationError", actionable=True)

    def test_search_without_query_returns_422(self, client: TestClient) -> None:
        """GET ``/api/v1/search`` without ``q`` returns 422 envelope."""
        resp = client.get("/api/v1/search")
        _assert_error_envelope(resp, 422, "ValidationError", actionable=True)


class TestDomainNotFound:
    """Nonexistent domain → 404 DomainNotFound (middleware + route handler)."""

    def test_get_with_nonexistent_domain_returns_domain_not_found(
        self, client: TestClient
    ) -> None:
        """GET ``/api/v1/entries?domain=nonexistent`` → 404 DomainNotFound
        via the domain validation **middleware**.
        """
        resp = client.get("/api/v1/entries?domain=completely-fake-domain")

        _assert_error_envelope(resp, 404, "DomainNotFound", actionable=True)
        msg = resp.json()["error"]["message"]
        assert "completely-fake-domain" in msg
        assert "add_domain" in msg

    def test_delete_with_nonexistent_domain_returns_domain_not_found(
        self, client: TestClient
    ) -> None:
        """DELETE with ``domain=nonexistent`` → 404 DomainNotFound
        via middleware.
        """
        resp = client.delete(
            "/api/v1/entries/some-entry?domain=non-existent-domain"
        )

        _assert_error_envelope(resp, 404, "DomainNotFound", actionable=True)
        assert "non-existent-domain" in resp.json()["error"]["message"]

    def test_post_with_nonexistent_domain_returns_domain_not_found(
        self, client: TestClient
    ) -> None:
        """POST ``/api/v1/entries`` with ``domain`` set to a domain that
        does not exist → 404 DomainNotFound via the route handler.
        """
        resp = client.post(
            "/api/v1/entries",
            json={
                "title": "Test",
                "content": (
                    "This is a sufficiently long body for the "
                    "exception-mapping tests, well above the "
                    "fifty-character minimum content guard that every "
                    "KB write boundary now enforces."
                ),
                "domain": "non-existent-domain",
            },
        )

        _assert_error_envelope(resp, 404, "DomainNotFound", actionable=True)
        assert "non-existent-domain" in resp.json()["error"]["message"]
        assert "add_domain" in resp.json()["error"]["message"]

    def test_known_domain_passes_middleware(self, client: TestClient) -> None:
        """When a domain is known, the middleware lets the request pass
        through.  The route handler then processes the request normally.
        """
        # Patch _known_domains to include 'test-domain'
        with patch(
            "autoinfo.api.server._known_domains",
            return_value={"test-domain"},
        ):
            resp = client.get("/api/v1/entries?domain=test-domain")

        # The request passed middleware; with an empty KB we get an
        # empty list (200), not a domain error.
        assert resp.status_code == 200

    def test_default_domain_skips_routes_check(self, client: TestClient) -> None:
        """POST with ``domain="default"`` skips the inline domain check
        and proceeds to create the entry (or fail on a different error).
        """
        resp = client.post(
            "/api/v1/entries",
            json={
                "title": "Default Domain Entry",
                "domain": "default",
            },
        )

        # It reached the handler — with an empty KB the store_entry
        # may succeed or fail; we only care that it's NOT a DomainNotFound.
        assert resp.status_code != 404 or "DomainNotFound" not in resp.text

    def test_omitted_domain_skips_middleware_check(
        self, client: TestClient
    ) -> None:
        """GET without a ``domain`` param passes the middleware check."""
        resp = client.get("/api/v1/entries")

        # Should pass middleware; empty KB → 200 with empty list
        assert resp.status_code == 200


class TestErrorEnvelopeConsistency:
    """All custom error paths produce the ``{success, error}`` envelope."""

    ERROR_PATHS = [
        # (endpoint, method, expected_status, expected_code)
        ("/api/v1/entries/non-existent-id", "get", 404, "ValidationError"),
    ]

    @pytest.mark.parametrize(
        ("path", "method", "expected_status", "expected_code"),
        [
            ("/api/v1/entries/non-existent-id", "get", 404, "ValidationError"),
            ("/api/v1/entries?domain=unknown-xyz", "get", 404, "DomainNotFound"),
        ],
    )
    def test_envelope_on_error_paths(
        self,
        client: TestClient,
        path: str,
        method: str,
        expected_status: int,
        expected_code: str,
    ) -> None:
        """Every known error path produces the canonical envelope."""
        if method == "get":
            resp = client.get(path)
        elif method == "delete":
            resp = client.delete(path)
        else:
            pytest.skip(f"Unsupported method {method!r}")

        _assert_error_envelope(resp, expected_status, expected_code)
