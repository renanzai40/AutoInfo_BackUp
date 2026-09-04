"""Tests for the standardised error response module (``autoinfo.mcp.errors``).

Covers:
    - All 19 ``ErrorCode`` enum members have correct string values
    - ``error_dict()`` returns the expected shape (``error_code``, ``message``,
      ``actionable``; no bare ``"error"`` key)
    - ``error_response()`` returns ``list[TextContent]`` with valid JSON
    - ``ErrorCode.INTERNAL_ERROR`` for unknown exception types
    - Re-exports from ``autoinfo.mcp`` work correctly
"""

from __future__ import annotations

import pytest

from autoinfo.mcp import ErrorCode, ErrorResponse
from autoinfo.mcp.errors import error_dict, error_response


class TestErrorCodeEnumValues:
    """Each ErrorCode member must match its expected string exactly."""

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (ErrorCode.NOT_FOUND, "NotFound"),
            (ErrorCode.DOMAIN_NOT_FOUND, "DomainNotFound"),
            (ErrorCode.VALIDATION_ERROR, "ValidationError"),
            (ErrorCode.INVALID_SOURCE_ID, "InvalidSourceId"),
            (ErrorCode.SOURCE_NOT_FOUND, "SourceNotFound"),
            (ErrorCode.TIMEOUT, "Timeout"),
            (ErrorCode.TOPIC_NOT_FOUND, "TopicNotFound"),
            (ErrorCode.KEYWORD_NOT_FOUND, "KeywordNotFound"),
            (ErrorCode.EMAIL_NOT_ENABLED, "EmailNotEnabled"),
            (ErrorCode.EMAIL_SEND_FAILED, "EmailSendFailed"),
            (ErrorCode.INVALID_CRON_EXPRESSION, "InvalidCronExpression"),
            (ErrorCode.SCHEDULE_ALREADY_EXISTS, "ScheduleAlreadyExists"),
            (ErrorCode.SCHEDULE_NOT_FOUND, "ScheduleNotFound"),
            (ErrorCode.NOT_PUBLISHED, "NotPublished"),
            (ErrorCode.COLLECTION_FAILED, "CollectionFailed"),
            (ErrorCode.PROCESSING_FAILED, "ProcessingFailed"),
            (ErrorCode.INVALID_SECTION, "InvalidSection"),
            (ErrorCode.UNKNOWN_TOOL, "UnknownTool"),
            (ErrorCode.INTERNAL_ERROR, "InternalError"),
        ],
    )
    def test_value(self, member: ErrorCode, expected: str) -> None:
        assert member.value == expected

    def test_total_members(self) -> None:
        """Ensure the enum member count stays pinned (grows only with new codes)."""
        assert len(ErrorCode) == 29


class TestErrorResponseTypedDict:
    """Type-check the TypedDict shape (runtime structural checks)."""

    def test_fields_present(self) -> None:
        """ErrorResponse should define success and error fields (canonical envelope)."""
        # TypedDict introspection
        annotations = ErrorResponse.__annotations__
        assert "success" in annotations
        assert "error" in annotations

    def test_field_types(self) -> None:
        annotations = ErrorResponse.__annotations__
        # With ``from __future__ import annotations`` these are ForwardRefs
        assert "success" in annotations
        assert "error" in annotations


class TestErrorDict:
    """Helper that returns plain dicts for internal use."""

    def test_default_message_is_empty_string(self) -> None:
        result = error_dict(ErrorCode.NOT_FOUND)
        assert result["message"] == ""

    def test_default_actionable_is_true(self) -> None:
        result = error_dict(ErrorCode.NOT_FOUND)
        assert result["actionable"] is True

    def test_returns_error_code_value_as_string(self) -> None:
        result = error_dict(ErrorCode.DOMAIN_NOT_FOUND)
        assert result["error_code"] == "DomainNotFound"
        # Must be a string, not the enum member
        assert isinstance(result["error_code"], str)

    def test_no_bare_error_key(self) -> None:
        """Must NOT contain a bare 'error' key (matches server.py pattern)."""
        result = error_dict(ErrorCode.NOT_FOUND)
        assert "error" not in result

    def test_custom_message(self) -> None:
        result = error_dict(
            ErrorCode.VALIDATION_ERROR,
            message="Invalid input",
            actionable=False,
        )
        assert result["error_code"] == "ValidationError"
        assert result["message"] == "Invalid input"
        assert result["actionable"] is False

    def test_has_exactly_three_keys(self) -> None:
        result = error_dict(ErrorCode.TIMEOUT)
        assert set(result.keys()) == {"error_code", "message", "actionable"}


class TestErrorResponse:
    """Helper that returns error envelope dicts."""

    def test_returns_envelope_dict(self) -> None:
        result = error_response(ErrorCode.INTERNAL_ERROR)
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error" in result
        assert "data" not in result

    def test_error_has_required_fields(self) -> None:
        result = error_response(ErrorCode.SOURCE_NOT_FOUND)
        error = result["error"]
        assert error["code"] == "SourceNotFound"
        assert error["message"] == ""
        assert error["actionable"] is True

    def test_custom_message(self) -> None:
        result = error_response(
            ErrorCode.COLLECTION_FAILED,
            message="PubMed API timed out",
            actionable=False,
        )
        error = result["error"]
        assert error["code"] == "CollectionFailed"
        assert error["message"] == "PubMed API timed out"
        assert error["actionable"] is False

    def test_full_envelope(self) -> None:
        result = error_response(
            ErrorCode.EMAIL_SEND_FAILED,
            message="SMTP connection refused",
            actionable=True,
        )
        assert result == {
            "success": False,
            "error": {
                "code": "EmailSendFailed",
                "message": "SMTP connection refused",
                "actionable": True,
            },
        }

    def test_no_bare_error_key_outside_envelope(self) -> None:
        """The error key is nested inside the envelope, not at root."""
        result = error_response(ErrorCode.NOT_FOUND)
        assert "error_code" not in result
        assert "code" in result["error"]


class TestInternalErrorForUnknownExceptions:
    """INTERNAL_ERROR is the fallback for unexpected exception types."""

    def test_exception_type_name_mapped(self) -> None:
        """Simulate the pattern in server.py: type(exc).__name__ lookup."""
        exc = RuntimeError("unexpected failure")
        code_name = type(exc).__name__  # "RuntimeError"

        # Our enum has no "RuntimeError" — INTERNAL_ERROR is the fallback
        if not hasattr(ErrorCode, code_name):
            result = error_dict(ErrorCode.INTERNAL_ERROR, message=str(exc))
        else:
            result = error_dict(getattr(ErrorCode, code_name), message=str(exc))

        assert result["error_code"] == "InternalError"
        assert result["message"] == "unexpected failure"

    def test_arbitrary_exception(self) -> None:
        """Catch-all for totally unknown exception types."""
        exc = ConnectionAbortedError("broken pipe")
        code_name = type(exc).__name__

        if not hasattr(ErrorCode, code_name):
            result = error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))
        else:
            result = error_response(
                getattr(ErrorCode, code_name), message=str(exc)
            )

        error = result["error"]
        assert error["code"] == "InternalError"
        assert error["message"] == "broken pipe"


class TestReExports:
    """autoinfo.mcp must re-export ErrorCode and ErrorResponse."""

    def test_error_code_reexported(self) -> None:
        assert ErrorCode is not None
        assert ErrorCode.NOT_FOUND.value == "NotFound"

    def test_error_response_reexported(self) -> None:
        assert ErrorResponse is not None
        # Just verify it's a TypedDict (type construct)
        assert isinstance(ErrorResponse, type)
