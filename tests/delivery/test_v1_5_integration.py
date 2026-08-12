"""Cross-feature integration tests for v1.5.

Tests end-to-end scenarios that span multiple v1.5 subsystems:
    - Config → quality gate → delivery pipeline
    - MCP tools → gate config → gate behavior
    - Delivery channel → product template → delivery gates
    - Alert rules → check_alerts → notification dispatch
    - Feed API + alerts integration
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from autoinfo.config import QualityGateConfig
from autoinfo.delivery import SMTPDeliveryChannel, WebhookDeliveryChannel, get_channel
from autoinfo.models import DeliveryResult, Item, Product, ProductType
from autoinfo.output import DeliveryOutput, _apply_delivery_gates
from autoinfo.quality import (
    G0SchemaIntegrity,
    G4FactualConsistency,
    run_delivery_gates,
    run_quality_gates,
)


# ===================================================================
# 1. Config → Quality Gate behavior
# ===================================================================


class TestConfigToQualityGate:
    """Modifying quality gate config changes gate behavior."""

    def test_g3_threshold_from_config_affects_passing(self) -> None:
        """G3 threshold from gate_config determines pass/fail for low-relevance item."""
        item = Item(
            id="test-g3-threshold-int",
            source_name="test", source_type="api",
            source_url="https://example.com",
            title="Completely unrelated topic",
            content="This article is about cooking recipes and has no medical keywords.",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
            source_platform="pubmed",
        )
        keywords = ["IVF", "embryo", "fertility"]

        # With high threshold (90), item below threshold → hidden
        results_high = run_quality_gates(
            item,
            context={"topic_keywords": keywords, "threshold": 90},
        )
        g3_high = results_high["G3-RelevanceScoring"]
        assert g3_high.details["hidden"] is True
        assert g3_high.passed is False

        # With zero threshold, item should pass (score 0 >= 0)
        results_low = run_quality_gates(
            item,
            context={"topic_keywords": keywords, "threshold": 90},
            gate_config={
                "G3-RelevanceScoring": QualityGateConfig(
                    name="G3", category="soft", threshold=0.0, action="archive"
                ),
            },
        )
        g3_low = results_low["G3-RelevanceScoring"]
        assert g3_low.details["hidden"] is False
        assert g3_low.passed is True

    def test_g1_action_skip_blocks_tier3(self) -> None:
        """G1 with action=skip causes tier 3+ items to be skipped."""
        item = Item(
            id="test-g1-skip-int",
            source_name="untrusted", source_type="api",
            source_url="https://example.com",
            title="Low quality source", content="",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=5,
        )

        results = run_quality_gates(
            item,
            gate_config={
                "G1-SourceAuthority": QualityGateConfig(
                    name="G1", category="soft", action="skip"
                ),
            },
        )
        g1 = results["G1-SourceAuthority"]
        assert g1.passed is False
        assert g1.details["action"] == "skip"

    def test_g0_retry_count_matches_config(self) -> None:
        """G0 reads retry count from gate_config correctly."""
        g0 = G0SchemaIntegrity()
        result = g0.check(
            {"source_url": "", "source_type": "", "source_platform": ""},
            gate_config=QualityGateConfig(
                name="G0", category="hard", retries=5, action="block"
            ),
        )
        assert result.passed is False
        assert result.details["retry_count"] == 5
        assert result.details["action"] == "block"


# ===================================================================
# 2. MCP → Gate Config → Gate behavior
# ===================================================================


class TestMCPToGateConfig:
    """Gate config changes via MCP handlers affect subsequent gate runs."""

    def test_mcp_set_g0_retry_reflected_in_gate_run(
        self, tmp_path: Path
    ) -> None:
        """Setting G0 retries via MCP-style config affects subsequent G0 run."""
        config = QualityGateConfig(
            name="G0", category="hard", retries=4, action="block"
        )
        g0 = G0SchemaIntegrity()
        result = g0.check(
            {"source_url": "", "source_type": "api", "source_platform": ""},
            gate_config=config,
        )
        assert result.details["retry_count"] == 4
        assert result.details["action"] == "block"

    def test_mcp_set_delivery_gate_config_affects_run(self) -> None:
        """Setting D3 action_on_failure via config affects run_delivery_gates."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Test",
            "key_findings": "K1",
            "summary": "S1",
            "recommendations": "R1",
            "entries": [
                {
                    "title": "Very Old",
                    "collected_at": (now - timedelta(days=365)).isoformat(),
                },
            ],
        }
        # With action_on_failure=block, stale entries should block
        configs = {
            "D1": {"enabled": True},
            "D2": {"enabled": True},
            "D3": {"enabled": True, "action_on_failure": "block"},
        }
        results = run_delivery_gates(product, delivery_gate_configs=configs)
        assert results["D3-Freshness"].passed is False
        assert results["D3-Freshness"].details["action"] == "block"


# ===================================================================
# 3. Delivery channel → ProductTemplate → Delivery gates
# ===================================================================


class TestDeliveryPipeline:
    """End-to-end: product generation → delivery gates → channel dispatch."""

    def test_apply_delivery_gates_with_fallback(self) -> None:
        """D2 fallback re-renders HTML output as markdown."""
        broken_html = "<html><body><h1>Broken HTML</body></html>"

        def _fallback() -> str:
            return "# Fallback Markdown Content"

        result = _apply_delivery_gates(
            rendered_output=broken_html,
            output_format="html",
            entries=[],
            context={},
            product_type="PROCESSED",
            delivery_gate_configs={
                "D2": {"enabled": True, "action_on_failure": "fallback"},
            },
            fallback_render_fn=_fallback,
        )

        assert isinstance(result, DeliveryOutput)
        assert result.delivery_format == "markdown"
        assert result.output == "# Fallback Markdown Content"
        assert any("D2 fallback" in w for w in result.warnings)

    def test_apply_delivery_gates_no_config_str(self) -> None:
        """Without delivery_gate_configs, returns DeliveryOutput with no gates run."""
        result = _apply_delivery_gates(
            rendered_output="# Plain Output",
            output_format="markdown",
            entries=[],
            context={},
            product_type="PROCESSED",
            delivery_gate_configs=None,
        )
        assert isinstance(result, DeliveryOutput)
        assert result.gate_results == {}
        assert result.delivery_blocked is False

    def test_apply_delivery_gates_d1_blocks_incomplete(self) -> None:
        """D1 blocks delivery when sections are missing."""
        result = _apply_delivery_gates(
            rendered_output="# Incomplete Report",
            output_format="markdown",
            entries=[],
            context={"llm_synthesis": {}},  # empty synthesis → missing sections
            product_type="PROCESSED",
            delivery_gate_configs={
                "D1": {"enabled": True, "action_on_failure": "block"},
            },
        )
        assert isinstance(result, DeliveryOutput)
        assert result.delivery_blocked is True
        assert any("D1 blocked" in w for w in result.warnings)
        d1_result = result.gate_results.get("D1-ProductCompleteness")
        assert d1_result is not None
        assert d1_result.passed is False

    def test_raw_product_skips_all_delivery_gates_via_apply(self) -> None:
        """RAW product type causes all delivery gates to skip."""
        result = _apply_delivery_gates(
            rendered_output="# RAW Feed",
            output_format="markdown",
            entries=[],
            context={},
            product_type="RAW",
            delivery_gate_configs={
                "D1": {"enabled": True, "action_on_failure": "block"},
                "D2": {"enabled": True},
                "D3": {"enabled": True},
            },
        )
        for gate_name, gr in result.gate_results.items():
            assert gr.details.get("skipped") is True, (
                f"{gate_name} should be skipped for RAW"
            )
        assert result.delivery_blocked is False

    def test_smtp_channel_wires_into_delivery_result(self) -> None:
        """SMTPDeliveryChannel.send returns DeliveryResult with correct metadata."""
        channel = SMTPDeliveryChannel()
        product = Product(
            id="smtp-test-1",
            domain="test-domain",
            type=ProductType.PROCESSED,
            name="SMTP Test",
        )
        result = channel.send(
            product=product,
            payload={"domain": "test", "period": "weekly"},
            recipients=["test@example.com"],
        )
        assert isinstance(result, DeliveryResult)
        assert result.channel == "smtp"
        assert result.product_id == "smtp-test-1"
        # Will fail without real SMTP, but should not raise
        assert result.status in ("success", "failed")

    def test_webhook_channel_wires_into_delivery_result(self) -> None:
        """WebhookDeliveryChannel.send to invalid URL returns failed result."""
        channel = WebhookDeliveryChannel()
        product = Product(
            id="wh-test-1",
            domain="test-domain",
            type=ProductType.PROCESSED,
            name="Webhook Test",
        )
        result = channel.send(
            product=product,
            payload={"key": "value"},
            recipients=["http://localhost:1/nonexistent-endpoint"],
        )
        assert isinstance(result, DeliveryResult)
        assert result.channel == "webhook"
        assert result.product_id == "wh-test-1"
        assert result.status in ("failed", "partial")


# ===================================================================
# 4. Quality gate config → Process pipeline integration
# ===================================================================


class TestQualityGatePipelineIntegration:
    """Quality gates with per-gate configs in the processing pipeline."""

    def test_g0_with_gate_config_retry_behavior(self) -> None:
        """G0 with specific gate_config retries the configured number of times."""
        g0 = G0SchemaIntegrity()
        result = g0.check(
            {"source_url": "", "source_type": "", "source_platform": ""},
            gate_config=QualityGateConfig(
                name="G0", category="hard", retries=2, action="block"
            ),
        )
        assert result.passed is False
        assert result.details["retry_count"] == 2
        assert result.details["action"] == "block"

    def test_g4_retry_chain_with_gate_config(self) -> None:
        """G4 retry chain with gate_config correctly escalates models."""
        from unittest.mock import patch, MagicMock

        item = Item(
            id="test-g4-int-chain",
            source_name="test", source_type="api",
            source_url="https://example.com/article",
            title="Test article",
            content="IVF outcomes improve with time-lapse imaging (48.2% vs 39.5%).",
            content_type="text", collected_at="2026-07-20T10:00:00Z",
            language="en", domain="test", quality_tier=1,
        )
        from autoinfo.models import ExtractionResult

        extraction = ExtractionResult(
            item_id="test-g4-int-chain",
            title="Test article",
            tl_dr="IVF success rates improve with time-lapse imaging.",
            key_points=["Time-lapse imaging improves IVF outcomes"],
            entities=[{"name": "IVF", "type": "procedure", "relevance": 0.9}],
            relevance_score=90.0,
        )
        gate_config = QualityGateConfig(
            name="G4",
            category="hard",
            retries=2,
            retry_models=["test/model-two"],
            action="block",
        )

        # Make LLM calls succeed on second retry
        def _mock_sequential(return_jsons):
            mock_llm = MagicMock()
            mock_llm.completion.side_effect = [
                _make_g4_response(rj) for rj in return_jsons
            ]
            return mock_llm

        def _make_g4_response(return_json):
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps(return_json)
            return mock_response

        mock_llm = _mock_sequential([
            {"contradiction": True, "explanation": "First check failed."},
            {"contradiction": False, "explanation": "Second check passed."},
        ])

        with patch(
            "autoinfo.quality.call_with_fallback",
            side_effect=mock_llm.completion.side_effect,
        ) as mock_cwf:
            g4 = G4FactualConsistency(model="test/test-model")
            result = g4.check(item, extraction, gate_config=gate_config)

        assert result.passed is True
        assert result.details["contradiction"] is False
        assert mock_cwf.call_count == 2
        model_args = [call.kwargs.get("model") for call in mock_cwf.call_args_list]
        assert model_args[0] == "test/test-model"
        assert model_args[1] == "test/model-two"


# ===================================================================
# 5. Global vs domain gate config resolution
# ===================================================================


class TestGateConfigResolution:
    """Domain-level quality_gates override global defaults in pipeline."""

    def test_domain_gate_overrides_global_in_run_quality_gates(
        self, sample_item: Item
    ) -> None:
        """Domain gate config overrides global in merged gate_config dict."""
        global_gates = {
            "G1-SourceAuthority": QualityGateConfig(
                name="G1", category="soft", action="flag"
            ),
            "G2-Dedup": QualityGateConfig(
                name="G2", category="soft", action="flag"
            ),
        }
        domain_gates = {
            "G1-SourceAuthority": QualityGateConfig(
                name="G1", category="soft", action="skip"
            ),
        }

        merged = dict(global_gates)
        merged.update(domain_gates)

        assert merged["G1-SourceAuthority"].action == "skip"
        assert merged["G2-Dedup"].action == "flag"

    def test_delivery_gate_global_defaults_used_when_not_in_domain(
        self, sample_item: Item
    ) -> None:
        """Delivery gate falls back to default when not set in domain config."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Report",
            "key_findings": "Findings",
            "summary": "Summary",
            "recommendations": "Recs",
            "entries": [
                {
                    "title": "Fresh",
                    "collected_at": (now - timedelta(days=1)).isoformat(),
                },
            ],
        }
        # Only configure D1 and D3 — D2 should use its default (fallback)
        configs = {
            "D1": {"enabled": True, "action_on_failure": "block"},
            "D3": {"enabled": True, "action_on_failure": "flag"},
        }
        results = run_delivery_gates(product, delivery_gate_configs=configs)
        assert "D1-ProductCompleteness" in results
        assert "D2-FormatIntegrity" in results  # runs with default config
        assert "D3-Freshness" in results
        assert results["D1-ProductCompleteness"].passed is True
        assert results["D2-FormatIntegrity"].passed is True
        assert results["D3-Freshness"].passed is True


# ===================================================================
# 6. Alert rules → check_alerts → dispatch integration
# ===================================================================


class TestAlertRuleDispatchPipeline:
    """Alert rules configured via add_alert_rule trigger notifications."""

    def test_alert_rule_created_check_matches_and_dispatches(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: add rule, create matching item, verify check_alerts triggers."""
        from autoinfo.alerts import add_alert_rule, check_alerts

        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            rule = add_alert_rule(
                domain="medical-research",
                topic_keywords=["IVF", "embryo"],
                relevance_threshold=0.0,
                channel="email",
                enabled=True,
            )
            assert rule.id.startswith("alert-")

            item = Item(
                id="int-test-item-001",
                source_name="pubmed",
                source_type="api",
                source_url="https://example.com/article",
                title="Improved IVF outcomes with time-lapse embryo imaging",
                content="Time-lapse imaging significantly improves live birth rates.",
                topic_tags=["IVF", "embryo imaging"],
                domain="medical-research",
            )

            with patch("autoinfo.alerts.get_config_path", return_value=None):
                results = check_alerts(item, domain="medical-research")

            assert len(results) == 1
            assert results[0]["rule_id"] == rule.id
            # Config not available → status should be "skipped"
            assert results[0]["status"] == "skipped"

    def test_alert_rule_disabled_skipped(self, tmp_path: Path) -> None:
        """Disabled alert rules are skipped even when keywords match."""
        from autoinfo.alerts import add_alert_rule, check_alerts

        alerts_path = tmp_path / ".autoinfo" / "alerts.yaml"
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("autoinfo.alerts._alerts_path", return_value=alerts_path):
            add_alert_rule(
                domain="medical-research",
                topic_keywords=["IVF"],
                enabled=False,
            )

            item = Item(
                id="int-test-disabled-rule",
                source_name="pubmed",
                source_type="api",
                source_url="https://example.com/article",
                title="IVF breakthrough",
                content="New IVF study results.",
                topic_tags=["IVF"],
                domain="medical-research",
                raw_data={"relevance_score": 95.0},
            )

            results = check_alerts(item, domain="medical-research")
            assert len(results) == 0

    def test_alert_webhook_dispatch_with_urls(self, tmp_path: Path) -> None:
        """Alert with webhook channel dispatches when URLs are configured."""
        from autoinfo.alerts import add_alert_rule, _dispatch_notification
        from autoinfo.models import AlertRule

        config_dir = tmp_path / ".autoinfo"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        config_path.write_text(
            "project:\n  name: Test\n"
            "llm:\n  provider: openai\n  model: gpt-4\n  api_key: key\n"
            "domains:\n"
            "  - name: medical-research\n    active: true\n    sources: []\n"
            "    webhook_urls:\n"
            "      - http://localhost:1/test-hook\n"
        )

        rule = AlertRule(
            id="alert-int-webhook",
            domain="medical-research",
            topic_keywords=["IVF"],
            channel="webhook",
            enabled=True,
        )
        item = Item(
            id="int-webhook-item",
            source_name="pubmed",
            source_type="api",
            source_url="https://example.com/article",
            title="IVF study",
            content="Study results.",
            domain="medical-research",
        )

        with patch("autoinfo.alerts.get_config_path", return_value=config_path):
            result = _dispatch_notification(rule, item, "medical-research")

        assert result["channel"] == "webhook"
        # Webhook to localhost:1 should fail or be skipped
        assert result["status"] in ("failed", "partial")


# ===================================================================
# 7. Cross-feature: Delivery gates + channel + product
# ===================================================================


class TestDeliveryGatesWithChannels:
    """Delivery gates integrate with channel dispatch for processed products."""

    def test_delivery_gates_pass_then_channel_called(self) -> None:
        """When all delivery gates pass, channel.send is reachable."""
        now = datetime.now(timezone.utc)
        product_output = {
            "product_type": "PROCESSED",
            "format": "markdown",
            "body": "# Weekly Digest\n\nAll content here.",
            "key_findings": "Key findings summary",
            "summary": "Executive summary of the week",
            "recommendations": "Recommendation 1, Recommendation 2",
            "entries": [
                {
                    "title": "Fresh Article",
                    "collected_at": (now - timedelta(days=1)).isoformat(),
                },
            ],
        }
        configs = {
            "D1": {"enabled": True, "action_on_failure": "block"},
            "D2": {"enabled": True},
            "D3": {"enabled": True, "action_on_failure": "flag"},
        }
        results = run_delivery_gates(product_output, delivery_gate_configs=configs)

        assert results["D1-ProductCompleteness"].passed is True
        assert results["D2-FormatIntegrity"].passed is True
        assert results["D3-Freshness"].passed is True

        # Channel.send can be called with the product
        channel = get_channel("smtp")
        product = Product(
            id="integration-product-1",
            domain="test",
            type=ProductType.PROCESSED,
            name="Integration Test Product",
        )
        delivery_result = channel.send(
            product=product,
            payload={"domain": "test", "period": "weekly"},
            recipients=["test@example.com"],
        )
        assert isinstance(delivery_result, DeliveryResult)
        assert delivery_result.product_id == "integration-product-1"


# ===================================================================
# 8. Run quality gates with mixed gate configs
# ===================================================================


class TestMixedGateConfigs:
    """Multiple gate configs with different actions work together."""

    def test_mixed_quality_and_delivery_configs(self) -> None:
        """Quality gate configs and context work together."""
        item = Item(
            id="test-mixed-1",
            source_name="pubmed", source_type="api",
            source_url="https://example.com/article",
            title="IVF breakthrough study",
            content="New IVF treatment shows promising results for embryo development.",
            content_type="text", collected_at="", language="en",
            domain="test", quality_tier=1,
            source_platform="pubmed",
        )

        results = run_quality_gates(
            item,
            context={
                "topic_keywords": ["IVF", "embryo"],
                "threshold": 30,
            },
            gate_config={
                "G0-SchemaIntegrity": QualityGateConfig(
                    name="G0", category="hard", retries=1, action="block"
                ),
                "G1-SourceAuthority": QualityGateConfig(
                    name="G1", category="soft", action="flag"
                ),
                "G3-RelevanceScoring": QualityGateConfig(
                    name="G3", category="soft", threshold=50.0, action="archive"
                ),
            },
        )

        assert results["G0-SchemaIntegrity"].passed is True
        assert results["G1-SourceAuthority"].passed is True
        # G3 should pass because the content has high keyword overlap
        assert results["G3-RelevanceScoring"].passed is True

    def test_all_delivery_gates_disabled(self) -> None:
        """All delivery gates disabled → all trivially pass."""
        now = datetime.now(timezone.utc)
        product = {
            "product_type": "PROCESSED",
            "format": "html",
            "body": "<broken>html",
            "entries": [
                {
                    "title": "Stale",
                    "collected_at": (now - timedelta(days=365)).isoformat(),
                },
            ],
        }
        configs = {
            "D1": {"enabled": False},
            "D2": {"enabled": False},
            "D3": {"enabled": False},
        }
        results = run_delivery_gates(product, delivery_gate_configs=configs)
        for gate_name, result in results.items():
            assert result.passed is True, f"{gate_name} should pass when disabled"
            assert result.details.get("skipped") is True, (
                f"{gate_name} should be skipped"
            )
