"""End-to-end ``content_preference`` consistency tests (D1 fixes).

Verifies that the ``content_preference`` tier gate (B-001) is applied
on every end-user-reachable output path, not just ``generate_digest`` /
``generate_report``:

- P1-3: ``generate_tutorial`` / ``generate_presentation`` filter KB
  entries by the user's stored preference.
- P1-2: the ``generate_cross_domain_report`` MCP handler forwards
  ``user_id`` to ``generate_report``.
- P1-1: the delivery scheduler forwards ``user_id`` (persisted on
  ``DeliverySchedule``) into ``generate_digest`` / ``generate_report``,
  and the ``add_delivery_schedule`` MCP handler accepts/stores it.
- P1-4: ``send_to_enduser`` blocks deliveries whose product kind
  conflicts with the user's stored preference instead of silently
  bypassing the gate.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

_RAW_ENTRY: dict[str, Any] = {
    "entry_id": "raw-001",
    "title": "Raw tier article one",
    "domain": "test-domain",
    "tier": "01-Raw",
    "source_url": "https://example.com/raw-001",
    "source_type": "rss",
    "source_platform": "demo",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Collected but not yet processed.",
    "tags": "[]",
    "quality_tier": 1,
    "relevance_score": 80.0,
    "dedup_status": "unique",
    "file_path": "",
}

_DRAFT_ENTRY: dict[str, Any] = {
    "entry_id": "draft-001",
    "title": "Draft tier article one",
    "domain": "test-domain",
    "tier": "02-Draft",
    "source_url": "https://example.com/draft-001",
    "source_type": "rss",
    "source_platform": "demo",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Agent processed, awaiting human promotion.",
    "tags": "[]",
    "quality_tier": 2,
    "relevance_score": 90.0,
    "dedup_status": "unique",
    "file_path": "",
}

_WIKI_ENTRY: dict[str, Any] = {
    "entry_id": "wiki-001",
    "title": "Wiki tier article one",
    "domain": "test-domain",
    "tier": "03-Wiki",
    "source_url": "https://example.com/wiki-001",
    "source_type": "rss",
    "source_platform": "demo",
    "collected_at": (date.today() - timedelta(days=1)).isoformat(),
    "summary": "Human promoted, append-only.",
    "tags": "[]",
    "quality_tier": 3,
    "relevance_score": 95.0,
    "dedup_status": "unique",
    "file_path": "",
}

_ALL_ENTRIES: list[dict[str, Any]] = [_RAW_ENTRY, _DRAFT_ENTRY, _WIKI_ENTRY]


def _prefs_result(preferences: dict[str, Any]) -> dict[str, Any]:
    """Shape returned by ``autoinfo.user_store.get_preferences``."""
    return {"user_id": "u-1", "preferences": preferences}


def _kb_store_mock() -> MagicMock:
    store = MagicMock()
    store.list_entries.return_value = _ALL_ENTRIES
    return store


def _llm_prompt(mock_llm: MagicMock) -> str:
    """Extract the prompt passed to the mocked LLM call."""
    return str(mock_llm.call_args[0][0])


# ---------------------------------------------------------------------------
# P1-3 — generate_tutorial preference filtering
# ---------------------------------------------------------------------------


class TestTutorialContentPreference:
    """``generate_tutorial`` filters entries by stored content_preference."""

    def _call_tutorial(self, preferences: dict[str, Any], user_id: str = "u-1") -> MagicMock:
        from autoinfo.output import generate_tutorial

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_tutorial") as mock_llm,
            patch("autoinfo.user_store.get_preferences") as mock_prefs,
        ):
            mock_llm.return_value = {"title": "Tutorial", "duration": "30 minutes"}
            mock_kb_cls.return_value = _kb_store_mock()
            mock_prefs.return_value = _prefs_result(preferences)
            generate_tutorial(domain="test-domain", user_id=user_id)
            return mock_llm

    def test_raw_only_excludes_processed_tiers(self) -> None:
        prompt = _llm_prompt(self._call_tutorial({"content_preference": "raw_only"}))
        assert "Raw tier article one" in prompt
        assert "Draft tier article one" not in prompt
        assert "Wiki tier article one" not in prompt

    def test_processed_only_excludes_raw_tier(self) -> None:
        prompt = _llm_prompt(self._call_tutorial({"content_preference": "processed_only"}))
        assert "Raw tier article one" not in prompt
        assert "Draft tier article one" in prompt
        assert "Wiki tier article one" in prompt

    def test_both_includes_all_tiers(self) -> None:
        prompt = _llm_prompt(self._call_tutorial({"content_preference": "both"}))
        assert "Raw tier article one" in prompt
        assert "Draft tier article one" in prompt
        assert "Wiki tier article one" in prompt

    def test_no_user_id_unchanged(self) -> None:
        """No user_id means no preference lookup, all tiers included."""
        from autoinfo.output import generate_tutorial

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_tutorial") as mock_llm,
        ):
            mock_llm.return_value = {"title": "Tutorial", "duration": "30 minutes"}
            mock_kb_cls.return_value = _kb_store_mock()
            generate_tutorial(domain="test-domain")

        prompt = _llm_prompt(mock_llm)
        assert "Raw tier article one" in prompt
        assert "Draft tier article one" in prompt
        assert "Wiki tier article one" in prompt


# ---------------------------------------------------------------------------
# P1-3 — generate_presentation preference filtering
# ---------------------------------------------------------------------------


class TestPresentationContentPreference:
    """``generate_presentation`` filters entries by stored content_preference."""

    def _call_presentation(self, preferences: dict[str, Any], user_id: str = "u-1") -> MagicMock:
        from autoinfo.output import generate_presentation

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_presentation") as mock_llm,
            patch("autoinfo.user_store.get_preferences") as mock_prefs,
        ):
            mock_llm.return_value = {"title": "Deck", "description": "", "slides": []}
            mock_kb_cls.return_value = _kb_store_mock()
            mock_prefs.return_value = _prefs_result(preferences)
            # Topic matches every fixture entry title, so tier filtering is
            # the only thing that distinguishes the prompt content.
            generate_presentation(
                domain="test-domain", topic="article one",
                user_id=user_id, allow_empty=True,
            )
            return mock_llm

    def test_raw_only_excludes_processed_tiers(self) -> None:
        prompt = _llm_prompt(self._call_presentation({"content_preference": "raw_only"}))
        assert "Raw tier article one" in prompt
        assert "Draft tier article one" not in prompt
        assert "Wiki tier article one" not in prompt

    def test_processed_only_excludes_raw_tier(self) -> None:
        prompt = _llm_prompt(
            self._call_presentation({"content_preference": "processed_only"})
        )
        assert "Raw tier article one" not in prompt
        assert "Draft tier article one" in prompt
        assert "Wiki tier article one" in prompt

    def test_no_user_id_unchanged(self) -> None:
        """No user_id means no preference lookup, all tiers included."""
        from autoinfo.output import generate_presentation

        with (
            patch("autoinfo.output.KBStore") as mock_kb_cls,
            patch("autoinfo.output._call_llm_for_presentation") as mock_llm,
        ):
            mock_llm.return_value = {"title": "Deck", "description": "", "slides": []}
            mock_kb_cls.return_value = _kb_store_mock()
            generate_presentation(domain="test-domain", topic="article one", allow_empty=True)

        prompt = _llm_prompt(mock_llm)
        assert "Raw tier article one" in prompt
        assert "Draft tier article one" in prompt
        assert "Wiki tier article one" in prompt


# ---------------------------------------------------------------------------
# P1-3 — MCP handlers forward user_id to tutorial/presentation
# ---------------------------------------------------------------------------


class TestMCPHandlerUserIDForwarding:
    """MCP handlers forward ``user_id`` into the output generators."""

    def test_generate_tutorial_handler_forwards_user_id(self) -> None:
        from autoinfo.mcp.server import _handle_generate_tutorial

        with patch("autoinfo.output.generate_tutorial") as mock_gen:
            mock_gen.return_value = "TUTORIAL"
            result = _handle_generate_tutorial(domain="test-domain", user_id="u-1")

        assert result["success"] is True
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-1"

    def test_generate_presentation_handler_forwards_user_id(self) -> None:
        from autoinfo.mcp.server import _handle_generate_presentation

        with patch("autoinfo.output.generate_presentation") as mock_gen:
            mock_gen.return_value = "DECK"
            result = _handle_generate_presentation(
                domain="test-domain", topic="article one", user_id="u-1"
            )

        assert result["success"] is True
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-1"


# ---------------------------------------------------------------------------
# P1-2 — cross-domain report forwards user_id
# ---------------------------------------------------------------------------


class TestCrossDomainReportUserID:
    """``generate_cross_domain_report`` MCP handler forwards user_id."""

    def test_forwards_user_id_to_generate_report(self) -> None:
        from autoinfo.mcp.server import _handle_generate_cross_domain_report

        config = SimpleNamespace(
            domains=[
                SimpleNamespace(name="medical-research"),
                SimpleNamespace(name="ai-commercial"),
            ]
        )
        with (
            patch("autoinfo.mcp.server._load_config", return_value=config),
            patch("autoinfo.output.generate_report", return_value="REPORT") as mock_report,
        ):
            result = _handle_generate_cross_domain_report(
                domains=["medical-research", "ai-commercial"],
                user_id="u-1",
            )

        assert result["success"] is True
        mock_report.assert_called_once()
        assert mock_report.call_args.kwargs["user_id"] == "u-1"
        assert mock_report.call_args.kwargs["domains"] == [
            "medical-research",
            "ai-commercial",
        ]

    def test_no_user_id_backward_compatible(self) -> None:
        """Omitting user_id defaults to empty string (no preference lookup)."""
        from autoinfo.mcp.server import _handle_generate_cross_domain_report

        config = SimpleNamespace(
            domains=[
                SimpleNamespace(name="medical-research"),
                SimpleNamespace(name="ai-commercial"),
            ]
        )
        with (
            patch("autoinfo.mcp.server._load_config", return_value=config),
            patch("autoinfo.output.generate_report", return_value="REPORT") as mock_report,
        ):
            result = _handle_generate_cross_domain_report(
                domains=["medical-research", "ai-commercial"],
            )

        assert result["success"] is True
        assert mock_report.call_args.kwargs["user_id"] == ""


# ---------------------------------------------------------------------------
# P1-1 — delivery scheduler user_id passthrough
# ---------------------------------------------------------------------------


class TestSchedulerUserID:
    """The delivery scheduler forwards ``user_id`` into output generation."""

    def test_generate_output_forwards_user_id_to_digest(self) -> None:
        from autoinfo.delivery.scheduler import _generate_output

        with patch("autoinfo.output.generate_digest", return_value="DIGEST") as mock_gen:
            result = _generate_output(
                domain="test-domain",
                output_type="digest",
                format="markdown",
                period="weekly",
                user_id="u-1",
            )

        assert result == "DIGEST"
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-1"

    def test_generate_output_forwards_user_id_to_report(self) -> None:
        from autoinfo.delivery.scheduler import _generate_output

        with patch("autoinfo.output.generate_report", return_value="REPORT") as mock_gen:
            result = _generate_output(
                domain="test-domain",
                output_type="report",
                format="markdown",
                period="monthly",
                user_id="u-2",
            )

        assert result == "REPORT"
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-2"

    def test_generate_output_no_user_id_backward_compatible(self) -> None:
        from autoinfo.delivery.scheduler import _generate_output

        with patch("autoinfo.output.generate_digest", return_value="DIGEST") as mock_gen:
            _generate_output(
                domain="test-domain",
                output_type="digest",
                format="markdown",
                period="weekly",
            )

        assert mock_gen.call_args.kwargs["user_id"] == ""

    def test_schedule_user_id_persists_round_trip(self, tmp_path) -> None:
        """user_id survives YAML save/load of DeliverySchedule."""
        from autoinfo.delivery.scheduler import (
            DeliverySchedule,
            DeliveryScheduler,
        )

        with patch(
            "autoinfo.delivery.scheduler.SCHEDULES_PATH",
            tmp_path / "delivery_schedules.yaml",
        ):
            scheduler = DeliveryScheduler()
            sched = DeliverySchedule(
                cron_expression="0 8 * * 1",
                domain="test-domain",
                user_id="u-7",
            )
            scheduler.add_schedule(sched)

            reloaded = DeliveryScheduler()
            loaded = reloaded.get_schedule(sched.id)
            assert loaded is not None
            assert loaded.user_id == "u-7"

    def test_run_delivery_schedules_forwards_schedule_user_id(self, tmp_path) -> None:
        """run_delivery_schedules passes the schedule's user_id to the generator."""
        from autoinfo.delivery.scheduler import DeliverySchedule

        sched = DeliverySchedule(
            id="sched-1",
            cron_expression="0 8 * * 1",
            domain="test-domain",
            output_type="digest",
            format="markdown",
            channel="email",
            user_id="u-9",
        )
        with (
            patch(
                "autoinfo.delivery.scheduler.DeliveryScheduler"
            ) as mock_sched_cls,
            patch("autoinfo.delivery.scheduler._deliver_output") as mock_deliver,
            patch("autoinfo.output.generate_digest", return_value="DIGEST") as mock_gen,
        ):
            mock_sched_cls.return_value.get_due_schedules.return_value = [sched]
            from autoinfo.delivery.scheduler import run_delivery_schedules

            results = run_delivery_schedules()

        assert len(results) == 1
        assert results[0]["ran"] is True
        mock_gen.assert_called_once()
        assert mock_gen.call_args.kwargs["user_id"] == "u-9"
        mock_deliver.assert_called_once()

    def test_add_delivery_schedule_mcp_handler_stores_user_id(self, tmp_path) -> None:
        """The add_delivery_schedule MCP handler accepts and persists user_id."""
        from autoinfo.mcp.server import _handle_add_delivery_schedule

        with patch(
            "autoinfo.delivery.scheduler.SCHEDULES_PATH",
            tmp_path / "delivery_schedules.yaml",
        ):
            result = _handle_add_delivery_schedule(
                domain="test-domain",
                cron_expression="0 8 * * 1",
                output_format="markdown",
                user_id="u-5",
            )

        assert result.get("created") is True
        assert result["schedule"]["user_id"] == "u-5"


# ---------------------------------------------------------------------------
# P1-4 — send_to_enduser delivery-time preference guard
# ---------------------------------------------------------------------------


def _enduser_profile(preferences: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        email="user@example.com",
        delivery_preferences={},
        preferences=preferences,
    )


class TestSendToEnduserGuard:
    """``send_to_enduser`` blocks deliveries conflicting with the user's
    stored content_preference."""

    def _dispatch(
        self, preferences: dict[str, Any], product_type: str
    ) -> tuple[dict[str, Any], MagicMock, MagicMock]:
        from autoinfo.mcp.server import _handle_send_to_enduser

        profile = _enduser_profile(preferences)
        delivered = SimpleNamespace(status="sent", recipient_count=1, error=None)
        with (
            patch("autoinfo.user_store.get_profile", return_value=profile),
            patch("autoinfo.delivery.get_channel") as mock_channel,
            patch(
                "autoinfo.delivery.deliver_with_retry", return_value=delivered
            ) as mock_deliver,
        ):
            result = _handle_send_to_enduser(
                end_user_id="u-1",
                product_type=product_type,
                product_id="medical-research-processed",
            )
        return result, mock_channel, mock_deliver

    def test_processed_product_blocked_for_raw_only_user(self) -> None:
        result, _mock_channel, mock_deliver = self._dispatch(
            {"content_preference": "raw_only"}, "processed"
        )
        assert result["success"] is False
        assert "raw_only" in result["error"]["message"]
        assert result["error"]["actionable"] is True
        mock_deliver.assert_not_called()

    def test_raw_product_blocked_for_processed_only_user(self) -> None:
        result, _mock_channel, mock_deliver = self._dispatch(
            {"content_preference": "processed_only"}, "raw"
        )
        assert result["success"] is False
        assert "processed_only" in result["error"]["message"]
        mock_deliver.assert_not_called()

    def test_matching_preference_allowed(self) -> None:
        result, _mock_channel, mock_deliver = self._dispatch(
            {"content_preference": "raw_only"}, "raw"
        )
        assert result["status"] == "sent"
        mock_deliver.assert_called_once()

    def test_default_both_unaffected(self) -> None:
        """Users without a stored preference (default 'both') are unaffected."""
        result, _mock_channel, mock_deliver = self._dispatch({}, "processed")
        assert result["status"] == "sent"
        mock_deliver.assert_called_once()
