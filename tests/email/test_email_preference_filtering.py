"""Email-path ``content_preference`` filtering consistency tests (P1 fixes).

Covers the two P1 defects where a scheduled digest (or an MCP-triggered
digest) destined for the email channel could silently bypass the user's
stored ``content_preference`` filter:

- P1-A: :func:`autoinfo.delivery.scheduler._deliver_via_email` re-generated
  the digest via ``send_digest`` *without* the schedule's ``user_id``,
  discarding the already-filtered content. Now ``user_id`` is threaded
  through ``_deliver_output`` → ``_deliver_via_email`` → ``send_digest``.
- P1-B: :func:`autoinfo.email_sender.send_digest` and the MCP tool
  ``send_email_digest`` had no ``user_id`` parameter at all. Now both
  accept and forward it.

Empty ``user_id`` (default ``""``) must preserve the existing behavior
(no preference lookup → ``"both"`` → no filtering).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from autoinfo.config import Config, EmailConfig

_EMAIL_CONFIG = Config(
    email=EmailConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user",
        smtp_pass="pass",
        from_addr="test@example.com",
        to_addrs=["recipient@example.com"],
    ),
)


def _schedule(**overrides: Any) -> Any:
    """Build a ``DeliverySchedule`` with sensible defaults for the email path."""
    from autoinfo.delivery.scheduler import DeliverySchedule

    kwargs: dict[str, Any] = {
        "id": "sched-email-1",
        "cron_expression": "0 8 * * 1",
        "domain": "test-domain",
        "output_type": "digest",
        "format": "markdown",
        "channel": "email",
        "user_id": "",
    }
    kwargs.update(overrides)
    return DeliverySchedule(**kwargs)


# ---------------------------------------------------------------------------
# P1-A — scheduled digest + email channel delivers user_id-filtered content
# ---------------------------------------------------------------------------


class TestScheduledEmailUserID:
    """The email delivery path threads the schedule's user_id through.

    ``_deliver_via_email`` re-renders the digest for HTML formatting, but
    it must forward ``user_id`` to ``send_digest`` so the user's stored
    ``content_preference`` is honored — never silently bypassed.
    """

    def test_email_channel_forwards_schedule_user_id(self) -> None:
        """A digest scheduled with user_id reaches send_digest with user_id."""
        sched = _schedule(user_id="u-42")

        with (
            patch(
                "autoinfo.delivery.scheduler.DeliveryScheduler"
            ) as mock_sched_cls,
            patch(
                "autoinfo.output.generate_digest", return_value="DIGEST"
            ) as mock_gen,
            patch("autoinfo.email_sender.send_digest") as mock_send,
        ):
            mock_sched_cls.return_value.get_due_schedules.return_value = [sched]
            from autoinfo.delivery.scheduler import run_delivery_schedules

            results = run_delivery_schedules()

        assert len(results) == 1
        assert results[0]["ran"] is True
        # The email sender receives the schedule's user_id → preference filter
        # is honored during the email rendering regeneration.
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["user_id"] == "u-42"
        # The scheduler's own generation happens exactly once, with user_id —
        # nothing is regenerated without it.
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-42"

    def test_email_channel_defaults_empty_user_id(self) -> None:
        """A schedule without user_id keeps the legacy un-filtered behavior."""
        sched = _schedule(user_id="")

        with (
            patch(
                "autoinfo.delivery.scheduler.DeliveryScheduler"
            ) as mock_sched_cls,
            patch(
                "autoinfo.output.generate_digest", return_value="DIGEST"
            ) as mock_gen,
            patch("autoinfo.email_sender.send_digest") as mock_send,
        ):
            mock_sched_cls.return_value.get_due_schedules.return_value = [sched]
            from autoinfo.delivery.scheduler import run_delivery_schedules

            results = run_delivery_schedules()

        assert len(results) == 1
        assert results[0]["ran"] is True
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["user_id"] == ""
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == ""


# ---------------------------------------------------------------------------
# P1-B — send_digest forwards user_id to generate_digest
# ---------------------------------------------------------------------------


class TestSendDigestUserID:
    """``email_sender.send_digest`` accepts and forwards ``user_id``."""

    def _call_send_digest(self, **overrides: Any) -> MagicMock:
        from autoinfo.email_sender import send_digest

        with (
            patch(
                "autoinfo.email_sender.generate_digest", return_value="# Digest"
            ) as mock_gen,
            patch(
                "autoinfo.email_sender._md_to_html", return_value="<h1>Digest</h1>"
            ),
            patch("autoinfo.email_sender._send_smtp") as mock_smtp,
        ):
            result = send_digest(domain="test-domain", config=_EMAIL_CONFIG, **overrides)
            assert result["success"] is True
            mock_smtp.assert_called_once()
            return mock_gen

    def test_forwards_user_id(self) -> None:
        """user_id="u-7" reaches generate_digest."""
        mock_gen = self._call_send_digest(user_id="u-7")
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-7"

    def test_empty_user_id_default(self) -> None:
        """Default user_id="" keeps the legacy no-lookup behavior."""
        mock_gen = self._call_send_digest()
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == ""


# ---------------------------------------------------------------------------
# P1-B — MCP send_email_digest forwards user_id
# ---------------------------------------------------------------------------


class TestMcpSendEmailDigestUserID:
    """The MCP tool ``send_email_digest`` accepts and forwards ``user_id``."""

    def test_handler_forwards_user_id(self) -> None:
        """user_id="u-3" reaches email_sender.send_digest."""
        from autoinfo.mcp.server import _handle_send_email_digest

        with (
            patch("autoinfo.mcp.server._load_config", return_value=_EMAIL_CONFIG),
            patch(
                "autoinfo.email_sender.send_digest",
                return_value={"success": True},
            ) as mock_send,
        ):
            result = _handle_send_email_digest(domain="test-domain", user_id="u-3")

        assert result.get("success") is True
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["user_id"] == "u-3"

    def test_handler_empty_user_id_default(self) -> None:
        """Default user_id="" keeps the legacy no-lookup behavior."""
        from autoinfo.mcp.server import _handle_send_email_digest

        with (
            patch("autoinfo.mcp.server._load_config", return_value=_EMAIL_CONFIG),
            patch(
                "autoinfo.email_sender.send_digest",
                return_value={"success": True},
            ) as mock_send,
        ):
            result = _handle_send_email_digest(domain="test-domain")

        assert result.get("success") is True
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["user_id"] == ""

    def test_tool_schema_exposes_user_id(self) -> None:
        """The registered MCP tool schema declares the user_id parameter."""
        from autoinfo.mcp.server import list_tools

        tools = asyncio.run(list_tools())
        tool = next(t for t in tools if t.name == "send_email_digest")
        properties = tool.inputSchema.get("properties", {})
        assert "user_id" in properties
        assert properties["user_id"]["type"] == "string"
