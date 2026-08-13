"""Tests for v1.5 alert stream configuration (Task 13).

Covers: AlertRule CRUD (YAML persistence), check_alerts() matching logic,
and notification dispatch via configured channels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from autoinfo.alerts import (
    add_alert_rule,
    check_alerts,
    list_alert_rules,
    load_alerts,
    remove_alert_rule,
    save_alerts,
)
from autoinfo.models import AlertRule, Item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    item_id: str = "test-item-001",
    title: str = "Improved IVF outcomes with time-lapse embryo imaging",
    content: str = "Time-lapse imaging significantly improves live birth rates in IVF patients.",
    topic_tags: list[str] | None = None,
    domain: str = "medical-research",
) -> Item:
    """Create a minimal Item for testing."""
    return Item(
        id=item_id,
        source_name="pubmed",
        source_type="api",
        source_url="https://example.com/article",
        title=title,
        content=content,
        topic_tags=topic_tags or ["IVF", "embryo imaging"],
        domain=domain,
        raw_data={"relevance_score": 85.0},
    )


def _assert_yaml_contains(
    alerts_path: Path, expected_rule_ids: set[str],
) -> None:
    """Assert that the YAML file at *alerts_path* contains the given rule IDs."""
    assert alerts_path.is_file(), f"Expected {alerts_path} to exist"
    with open(alerts_path, "r") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), "YAML root should be a dict"
    stored_ids = set(data.get("alerts", {}).keys())
    assert expected_rule_ids.issubset(stored_ids), (
        f"Expected rule IDs {expected_rule_ids} not found in stored {stored_ids}"
    )


# ===================================================================
# YAML persistence (CRUD)
# ===================================================================


class TestAlertRulePersistence:
    """Alert rules persist to/from YAML correctly."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Round-trip: save rules, reload, verify contents."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        # --- Patch the path resolver to use tmp_path -----------------------
        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            # Create a rule
            rule = add_alert_rule(
                domain="medical-research",
                topic_keywords=["IVF", "embryo"],
                relevance_threshold=50.0,
                channel="email",
                enabled=True,
            )
            assert rule.id.startswith("alert-")
            assert rule.domain == "medical-research"
            assert rule.topic_keywords == ["IVF", "embryo"]
            assert rule.relevance_threshold == 50.0
            assert rule.channel == "email"
            assert rule.enabled is True

            # Verify YAML file exists
            _assert_yaml_contains(alerts_path, {rule.id})

            # Reload from disk
            reloaded = load_alerts()
            assert rule.id in reloaded
            reloaded_rule = reloaded[rule.id]
            assert reloaded_rule.domain == "medical-research"
            assert reloaded_rule.topic_keywords == ["IVF", "embryo"]
            assert reloaded_rule.relevance_threshold == 50.0

            # Add another rule
            rule2 = add_alert_rule(domain="ai-commercial", topic_keywords=["GPT"])
            assert rule2.id not in (rule.id,)

            # Both should be present
            all_rules = list_alert_rules()
            ids = {r.id for r in all_rules}
            assert rule.id in ids
            assert rule2.id in ids

    def test_remove_rule(self, tmp_path: Path) -> None:
        """Removing a rule removes it from YAML."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            rule = add_alert_rule(domain="medical-research", topic_keywords=["test"])
            assert remove_alert_rule(rule.id) is True
            assert remove_alert_rule("non-existent") is False
            assert rule.id not in {r.id for r in list_alert_rules()}

    def test_list_filtered_by_domain(self, tmp_path: Path) -> None:
        """list_alert_rules(domain=...) returns only rules for that domain."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            r1 = add_alert_rule(domain="medical-research", topic_keywords=["IVF"])
            r2 = add_alert_rule(domain="medical-research", topic_keywords=["embryo"])
            _ = add_alert_rule(domain="ai-commercial", topic_keywords=["GPT"])

            medical = list_alert_rules(domain="medical-research")
            assert len(medical) == 2
            assert {r.id for r in medical} == {r1.id, r2.id}

    def test_persistence_across_restarts(self, tmp_path: Path) -> None:
        """Alert rules survive a fresh load (simulates process restart).

        This is the key persistence test: write rules, then simulate a
        restart by creating a fresh module-level load_alerts() call.
        """
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            # --- "First run": add a rule -----------------------------------
            rule = add_alert_rule(
                domain="medical-research",
                topic_keywords=["IVF"],
                relevance_threshold=50.0,
                channel="webhook",
            )

            # --- "Restart": clear in-memory caches and reload --------------
            # (no in-memory cache in alerts.py, so this is a fresh load)
            fresh = load_alerts()
            assert rule.id in fresh
            restored = fresh[rule.id]
            assert restored.domain == "medical-research"
            assert restored.topic_keywords == ["IVF"]
            assert restored.relevance_threshold == 50.0
            assert restored.channel == "webhook"
            assert restored.enabled is True

            # Verify the YAML file is human-readable
            with open(alerts_path, "r") as fh:
                raw = yaml.safe_load(fh)
            assert "alerts" in raw
            assert rule.id in raw["alerts"]

    def test_save_alerts_overwrites_existing(self, tmp_path: Path) -> None:
        """save_alerts replaces the entire alerts dict."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            r1 = add_alert_rule(domain="medical-research", topic_keywords=["A"])
            r2 = add_alert_rule(domain="medical-research", topic_keywords=["B"])

            # Save only r1
            save_alerts({r1.id: r1})
            remaining = load_alerts()
            assert r1.id in remaining
            assert r2.id not in remaining


# ===================================================================
# Alert matching logic
# ===================================================================


class TestCheckAlertsMatching:
    """check_alerts() correctly matches or skips items."""

    _patcher: Any | None = None

    def _setup(
        self, tmp_path: Path, rules: list[dict[str, Any]]
    ) -> Item:
        """Create a clean alerts.yaml with given rules and return a test item."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        patcher = patch("autoinfo.alerts._alerts_path", return_value=alerts_path)
        patcher.start()
        self._patcher = patcher  # keep for teardown

        for r in rules:
            add_alert_rule(**r)

        return _make_item()

    def teardown_method(self) -> None:
        if self._patcher is not None:
            self._patcher.stop()

    # --- Test 1: matching keywords trigger notification ---------------------

    def test_matching_keywords_triggers(self, tmp_path: Path) -> None:
        """Alert rule with matching keywords triggers notification."""
        item = self._setup(
            tmp_path,
            [
                {
                    "domain": "medical-research",
                    "topic_keywords": ["IVF"],
                    "relevance_threshold": 0.0,
                    "channel": "email",
                }
            ],
        )

        # check_alerts calls _dispatch_notification → _notify_email
        # which tries to load config.  We don't care about the actual
        # delivery — we just verify that the matching logic fires.
        # Patch get_config_path to return None so it skips sending.
        with patch("autoinfo.alerts.get_config_path", return_value=None):
            results = check_alerts(item, domain="medical-research")

        # Should match → _dispatch was called → result returned
        assert len(results) == 1, f"Expected 1 match, got {len(results)}: {results}"
        assert results[0]["rule_id"].startswith("alert-")
        # Channel said "email", but config not available → should be "skipped"
        assert results[0]["status"] == "skipped"

    # --- Test 2: non-matching keywords do NOT trigger -----------------------

    def test_non_matching_keywords_does_not_trigger(self, tmp_path: Path) -> None:
        """Alert rule with non-matching keywords does NOT trigger."""
        item = self._setup(
            tmp_path,
            [
                {
                    "domain": "medical-research",
                    "topic_keywords": ["CRISPR", "gene editing"],
                    "relevance_threshold": 0.0,
                    "channel": "email",
                }
            ],
        )

        results = check_alerts(item, domain="medical-research")
        assert len(results) == 0, (
            f"Expected 0 matches for non-matching keywords, got {len(results)}"
        )

    def test_disabled_rule_skipped(self, tmp_path: Path) -> None:
        """Disabled alert rules are never triggered."""
        item = self._setup(
            tmp_path,
            [
                {
                    "domain": "medical-research",
                    "topic_keywords": ["IVF"],
                    "relevance_threshold": 0.0,
                    "channel": "email",
                    "enabled": False,
                }
            ],
        )

        results = check_alerts(item, domain="medical-research")
        assert len(results) == 0

    def test_relevance_below_threshold_skips(self, tmp_path: Path) -> None:
        """Item below relevance threshold is not triggered."""
        item = self._setup(
            tmp_path,
            [
                {
                    "domain": "medical-research",
                    "topic_keywords": ["IVF"],
                    "relevance_threshold": 90.0,  # item has 85.0
                    "channel": "email",
                }
            ],
        )

        results = check_alerts(item, domain="medical-research")
        assert len(results) == 0

    def test_empty_keywords_matches_all(self, tmp_path: Path) -> None:
        """Empty keyword list matches every item in the domain."""
        item = self._setup(
            tmp_path,
            [
                {
                    "domain": "medical-research",
                    "topic_keywords": [],  # matches all
                    "relevance_threshold": 0.0,
                    "channel": "email",
                }
            ],
        )

        with patch("autoinfo.alerts.get_config_path", return_value=None):
            results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_wrong_domain_skips(self, tmp_path: Path) -> None:
        """Alert rule for a different domain is not triggered."""
        item = self._setup(
            tmp_path,
            [
                {
                    "domain": "ai-commercial",
                    "topic_keywords": ["IVF"],
                    "relevance_threshold": 0.0,
                    "channel": "email",
                }
            ],
        )

        results = check_alerts(item, domain="medical-research")
        assert len(results) == 0


# ===================================================================
# Content matching edge cases
# ===================================================================


class TestKeywordMatchingEdgeCases:
    """Edge cases for keyword matching in _matches_keywords."""

    def test_match_in_title(self, tmp_path: Path) -> None:
        """Keyword match in title triggers."""
        item = _make_item(title="CRISPR gene editing shows promise")
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["CRISPR"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_match_in_topic_tags(self, tmp_path: Path) -> None:
        """Keyword match in topic_tags triggers."""
        item = _make_item(title="Some article", topic_tags=["gene-therapy", "clinical"])
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["gene-therapy"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_case_insensitive_match(self, tmp_path: Path) -> None:
        """Keyword matching is case-insensitive."""
        item = _make_item(title="IVF breakthroughs in 2026")
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["ivf"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_unicode_keywords_match(self, tmp_path: Path) -> None:
        """Unicode keywords match correctly."""
        item = _make_item(title="CRISPR基因编辑技术在临床应用中的进展")
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["基因编辑"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_match_in_content_but_not_title(self, tmp_path: Path) -> None:
        """Keyword match in content (not title) triggers."""
        item = _make_item(
            title="Some medical article",
            content="This article discusses CRISPR gene editing therapy outcomes.",
            topic_tags=[],
        )
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["CRISPR"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_none_content_does_not_crash(self, tmp_path: Path) -> None:
        """Item with None content does not crash keyword matching."""
        item = _make_item(title="Test", content=None)  # type: ignore[arg-type]
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["test"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1

    def test_empty_topic_tags_does_not_crash(self, tmp_path: Path) -> None:
        """Item with None topic_tags does not crash keyword matching."""
        item = _make_item(title="Test article", topic_tags=None)  # type: ignore[arg-type]
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["test"])
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 1


# ===================================================================
# Notification dispatch
# ===================================================================


class TestNotificationDispatch:
    """Tests for _dispatch_notification and its channel-specific paths."""

    def test_email_disabled_in_config(self, tmp_path: Path) -> None:
        """Email notification is skipped when email is not enabled in config."""
        from autoinfo.alerts import _dispatch_notification

        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        # Write a config with email disabled
        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\n"
            "llm:\n  provider: openai\n  model: gpt-4\n  api_key: key\n"
            "domains:\n  - name: medical-research\n    active: true\n    sources: []\n"
            "email:\n  enabled: false\n"
        )

        rule = AlertRule(
            id="alert-test-email-disabled",
            domain="medical-research",
            topic_keywords=["IVF"],
            channel="email",
            enabled=True,
        )
        item = _make_item()

        with patch("autoinfo.alerts.get_config_path", return_value=config_path):
            result = _dispatch_notification(rule, item, "medical-research")
        assert result["status"] == "skipped"
        assert result["reason"] == "email_not_enabled"

    def test_webhook_no_urls_skips(self, tmp_path: Path) -> None:
        """Webhook notification is skipped when no webhook URLs configured."""
        from autoinfo.alerts import _dispatch_notification

        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\n"
            "llm:\n  provider: openai\n  model: gpt-4\n  api_key: key\n"
            "domains:\n  - name: medical-research\n    active: true\n    sources: []\n"
        )

        rule = AlertRule(
            id="alert-test-webhook-no-urls",
            domain="medical-research",
            topic_keywords=["IVF"],
            channel="webhook",
            enabled=True,
        )
        item = _make_item()

        with patch("autoinfo.alerts.get_config_path", return_value=config_path):
            result = _dispatch_notification(rule, item, "medical-research")
        assert result["status"] == "skipped"
        assert result["reason"] == "no_webhook_urls"

    def test_multiple_rules_match_same_item(self, tmp_path: Path) -> None:
        """Multiple alert rules matching the same item all trigger."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(domain="medical-research", topic_keywords=["IVF"])
            add_alert_rule(domain="medical-research", topic_keywords=["embryo"])
            add_alert_rule(domain="medical-research", topic_keywords=["time-lapse"])
            item = _make_item()
            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")
        assert len(results) == 3  # all three rules match


# ===================================================================
# Edge cases for internal helpers
# ===================================================================


class TestInternalHelpers:
    """Tests for _get_relevance_score and save_alerts edge cases."""

    def test_relevance_score_non_dict_raw_data(self) -> None:
        """_get_relevance_score returns 1.0 when raw_data is not a dict."""
        from autoinfo.alerts import _get_relevance_score
        item = _make_item()
        item.raw_data = "not a dict"  # type: ignore[assignment]
        assert _get_relevance_score(item) == 1.0

    def test_relevance_score_none_score(self) -> None:
        """_get_relevance_score returns 1.0 when relevance_score is None."""
        from autoinfo.alerts import _get_relevance_score
        item = _make_item()
        item.raw_data = {"relevance_score": None}
        assert _get_relevance_score(item) == 1.0

    def test_relevance_score_invalid_type(self) -> None:
        """_get_relevance_score returns 1.0 when score cannot be converted to float."""
        from autoinfo.alerts import _get_relevance_score
        item = _make_item()
        item.raw_data = {"relevance_score": "not-a-number"}
        assert _get_relevance_score(item) == 1.0

    def test_save_alerts_empty_dict(self, tmp_path: Path) -> None:
        """save_alerts with empty dict writes valid YAML."""
        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            save_alerts({})
            loaded = load_alerts()
        assert loaded == {}

    def test_corrupted_yaml_returns_empty(self, tmp_path: Path) -> None:
        """Corrupted alerts YAML is handled gracefully, returning empty dict."""
        from autoinfo.alerts import load_alerts, _alerts_path

        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)
        alerts_path.write_text("!!broken yaml [\n")

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            loaded = load_alerts()
        assert loaded == {}
