"""Tests for end-user preference persistence, including the
``content_preference`` field (B-001 launch blocker).

Covers:
- invalid ``content_preference`` rejected with the standard error envelope
- valid ``content_preference`` values persist and round-trip
- default is ``"both"`` when unset (``resolve_content_preference``)
- backward compatibility with already-stored preference dicts
- MCP handler ``_handle_update_preferences`` mirrors the validation
"""

from __future__ import annotations

from typing import Any

import pytest

from autoinfo.user_store import (
    CONTENT_PREFERENCE_DEFAULT,
    CONTENT_PREFERENCE_VALUES,
    create_profile,
    get_preferences,
    resolve_content_preference,
    update_preferences,
)


@pytest.fixture
def user_db(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the user-store SQLite DB in a temp dir."""
    monkeypatch.setattr("autoinfo.user_store._DB_PATH", None)
    monkeypatch.setattr(
        "autoinfo.user_store._get_db_path", lambda: tmp_path / "users.db"
    )
    yield tmp_path


@pytest.fixture
def stored_user(user_db: Any) -> str:
    """Create a user profile and return its user_id."""
    create_profile(user_id="cp-user-001", name="CP Test User")
    return "cp-user-001"


class TestUpdatePreferencesContentPreference:
    """``update_preferences`` validation and persistence of content_preference."""

    def test_invalid_value_rejected_with_error_envelope(
        self, stored_user: str
    ) -> None:
        result = update_preferences(
            stored_user, {"content_preference": "everything"}
        )
        assert result["success"] is False
        assert result["error"]["code"] == "ValidationError"
        assert result["error"]["actionable"] is True
        for allowed in ("raw_only", "processed_only", "both"):
            assert allowed in result["error"]["message"]

    def test_invalid_value_nothing_persisted(self, stored_user: str) -> None:
        update_preferences(
            stored_user,
            {"content_preference": "everything", "format": "json"},
        )
        stored = get_preferences(stored_user)["preferences"]
        assert "content_preference" not in stored
        assert "format" not in stored

    def test_valid_raw_only_persists(self, stored_user: str) -> None:
        result = update_preferences(
            stored_user, {"content_preference": "raw_only"}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["content_preference"] == "raw_only"

    def test_valid_processed_only_persists(self, stored_user: str) -> None:
        result = update_preferences(
            stored_user, {"content_preference": "processed_only"}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["content_preference"] == "processed_only"

    def test_valid_both_persists(self, stored_user: str) -> None:
        result = update_preferences(
            stored_user, {"content_preference": "both"}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["content_preference"] == "both"

    def test_merge_keeps_existing_keys(self, stored_user: str) -> None:
        update_preferences(stored_user, {"format": "html"})
        result = update_preferences(
            stored_user, {"content_preference": "raw_only"}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["format"] == "html"
        assert stored["content_preference"] == "raw_only"

    def test_backward_compat_without_content_preference(
        self, stored_user: str
    ) -> None:
        result = update_preferences(
            stored_user, {"format": "markdown", "timezone": "UTC"}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["format"] == "markdown"
        assert "content_preference" not in stored

    def test_missing_user_returns_not_found(self, user_db: Any) -> None:
        result = update_preferences(
            "no-such-user", {"content_preference": "both"}
        )
        assert result["error_code"] == "NotFound"


class TestResolveContentPreference:
    """``resolve_content_preference`` defaulting semantics."""

    def test_default_both_when_unset(self) -> None:
        assert resolve_content_preference({}) == "both"
        assert resolve_content_preference(None) == "both"
        assert resolve_content_preference({"format": "json"}) == "both"

    def test_returns_valid_values(self) -> None:
        for value in CONTENT_PREFERENCE_VALUES:
            assert (
                resolve_content_preference({"content_preference": value})
                == value
            )

    def test_invalid_stored_value_defaults_to_both(self) -> None:
        assert (
            resolve_content_preference({"content_preference": "nope"})
            == "both"
        )

    def test_default_constant_is_both(self) -> None:
        assert CONTENT_PREFERENCE_DEFAULT == "both"
        assert CONTENT_PREFERENCE_VALUES == frozenset(
            {"raw_only", "processed_only", "both"}
        )


class TestMCPUpdatePreferencesHandler:
    """MCP-level ``_handle_update_preferences`` error envelope behavior."""

    def test_invalid_value_returns_envelope(self, stored_user: str) -> None:
        from autoinfo.mcp.server import _handle_update_preferences

        result = _handle_update_preferences(
            stored_user, {"content_preference": "everything"}
        )
        assert result["success"] is False
        assert result["error"]["code"] == "ValidationError"
        assert result["error"]["actionable"] is True
        assert "raw_only" in result["error"]["message"]

    def test_valid_value_stores(self, stored_user: str) -> None:
        from autoinfo.mcp.server import _handle_update_preferences

        result = _handle_update_preferences(
            stored_user, {"content_preference": "processed_only"}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["content_preference"] == "processed_only"

    def test_unknown_user_not_found(self, user_db: Any) -> None:
        from autoinfo.mcp.server import _handle_update_preferences

        result = _handle_update_preferences(
            "nobody", {"content_preference": "both"}
        )
        assert result["error_code"] == "NotFound"

    def test_without_content_preference_passes_through(
        self, stored_user: str
    ) -> None:
        from autoinfo.mcp.server import _handle_update_preferences

        result = _handle_update_preferences(
            stored_user, {"format": "html", "max_items": 5}
        )
        assert result["success"] is True
        stored = get_preferences(stored_user)["preferences"]
        assert stored["format"] == "html"
        assert stored["max_items"] == 5


class TestGetPreferencesCompat:
    """``get_preferences`` stays backward compatible."""

    def test_returns_preferences_for_unknown_prefs(
        self, stored_user: str
    ) -> None:
        result = get_preferences(stored_user)
        assert result["user_id"] == stored_user
        assert result["preferences"] == {}

    def test_missing_user_not_found(self, user_db: Any) -> None:
        result = get_preferences("no-such-user")
        assert result["error_code"] == "NotFound"
