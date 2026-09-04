"""Standardised error types and helpers for MCP tool responses.

Provides ``ErrorCode`` enum for consistent error classification,
``ErrorResponse`` TypedDict for type-safe error dicts, and helper
functions to build error responses in the shape expected by agents.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class ErrorCode(str, Enum):
    """Error codes for MCP tool responses.

    Each member maps to a string value used as the ``error_code`` field
    in error dicts.  Unknown/unexpected exceptions map to ``INTERNAL_ERROR``.
    """

    NOT_FOUND = "NotFound"
    DOMAIN_NOT_FOUND = "DomainNotFound"
    VALIDATION_ERROR = "ValidationError"
    INVALID_SOURCE_ID = "InvalidSourceId"
    SOURCE_NOT_FOUND = "SourceNotFound"
    TIMEOUT = "Timeout"
    TOPIC_NOT_FOUND = "TopicNotFound"
    KEYWORD_NOT_FOUND = "KeywordNotFound"
    EMAIL_NOT_ENABLED = "EmailNotEnabled"
    EMAIL_SEND_FAILED = "EmailSendFailed"
    INVALID_CRON_EXPRESSION = "InvalidCronExpression"
    SCHEDULE_ALREADY_EXISTS = "ScheduleAlreadyExists"
    SCHEDULE_NOT_FOUND = "ScheduleNotFound"
    NOT_PUBLISHED = "NotPublished"
    COLLECTION_FAILED = "CollectionFailed"
    PROCESSING_FAILED = "ProcessingFailed"
    INVALID_SECTION = "InvalidSection"
    UNKNOWN_TOOL = "UnknownTool"
    CONFIRMATION_REQUIRED = "ConfirmationRequired"
    INTERNAL_ERROR = "InternalError"
    AUTH_REQUIRED = "AuthRequired"
    RATE_LIMITED = "RateLimited"
    SESSION_EXPIRED = "SessionExpired"
    LLM_NOT_CONFIGURED = "LLMNotConfigured"
    NO_CACHED_ITEMS = "NoCachedItems"
    EMPTY_RESULT = "EmptyResult"
    CONFIG_NOT_FOUND = "ConfigNotFound"
    DIRECTOR_ONLY = "DIRECTOR_ONLY"
    READ_ONLY_SERVER = "READ_ONLY_SERVER"
    FREE_TIER_LIMIT = "FreeTierLimit"


class ErrorDetail(TypedDict):
    """Shape of the ``error`` field inside the canonical error envelope."""

    code: str
    message: str
    actionable: bool


class ErrorResponse(TypedDict):
    """Canonical error envelope shape ``{success: False, error: {code, message, actionable}}``.

    Returned by :func:`error_response`.  The legacy flat shape
    (``error_code`` / ``message`` / ``actionable``) from :func:`error_dict`
    is deprecated.
    """

    success: bool
    error: ErrorDetail


def error_dict(
    error_code: ErrorCode,
    message: str = "",
    actionable: bool = True,
) -> dict[str, Any]:
    """Build a standardised error dict.

    .. deprecated::
        **Deprecated** — use :func:`error_response` for new code.
        This function returns only the flat fields (``error_code`` /
        ``message`` / ``actionable``) *without* the ``success/error``
        envelope.  Kept for backward compatibility; new callers MUST
        use :func:`error_response`.

        .. warning::
            ``DeprecationWarning`` — This function will be removed in
            a future release.

    Returns a dict with ``error_code`` (the enum *value* string),
    ``message``, and ``actionable`` — the same shape used throughout
    the MCP server.
    """
    return {
        "error_code": error_code.value,
        "message": message,
        "actionable": actionable,
    }


def success_response(
    data: dict[str, Any] | list[Any] | str,
) -> dict[str, Any]:
    """Return a success envelope ``{success: True, data: ...}``.

    This is the standard success response for all non-health MCP tools.
    Pairs with :func:`error_response` which returns the error counterpart
    ``{success: False, error: {code, message, actionable}}``.
    """
    return {"success": True, "data": data}


def error_response(
    code: str | ErrorCode,
    message: str = "",
    actionable: bool = True,
) -> dict[str, Any]:
    """Return an error envelope ``{success: False, error: {code, message, actionable}}``.

    Parameters
    ----------
    code:
        Error code string or ``ErrorCode`` enum member.
    message:
        Human-readable description of the error.
    actionable:
        Whether the agent can retry the operation.
    """
    code_str = code.value if isinstance(code, ErrorCode) else code
    return {
        "success": False,
        "error": {
            "code": code_str,
            "message": message,
            "actionable": actionable,
        },
    }
