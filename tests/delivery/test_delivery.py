"""Tests for delivery channel adapters and retry logic.

Covers all 10 adapters (discord, telegram, wechat_work, wechat_oa,
dingtalk, feishu, rss, webhook, rest_api, file_export) plus
deliver_with_retry.  All HTTP adapters use mocked httpx.Client —
zero network calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from autoinfo.delivery import (
    FileExportDeliveryChannel,
    RESTAPIDeliveryChannel,
    WebhookDeliveryChannel,
    deliver_with_retry,
)
from autoinfo.delivery.dingtalk import DingTalkDeliveryChannel
from autoinfo.delivery.discord import DiscordDeliveryChannel
from autoinfo.delivery.feishu import FeiShuDeliveryChannel
from autoinfo.delivery.rss import RSSDeliveryChannel
from autoinfo.delivery.telegram import TelegramDeliveryChannel
from autoinfo.delivery.wechat_oa import WeChatOADeliveryChannel
from autoinfo.delivery.wechat_work import WeChatWorkDeliveryChannel
from autoinfo.models import DeliveryResult, Product, ProductType


# ============================================================================
# Helpers
# ============================================================================


def _make_product(
    product_id: str = "prod-001",
    domain: str = "test-domain",
    **config: object,
) -> Product:
    """Create a minimal Product for testing."""
    return Product(
        id=product_id,
        domain=domain,
        type=ProductType.PROCESSED,
        name="test-digest",
        config={k: v for k, v in config.items()},  # type: ignore[misc]
    )


def _make_mock_httpx(
    status_code: int = 200,
    json_data: dict | None = None,
) -> MagicMock:
    """Create an httpx.Client mock that works inside a context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    if json_data is not None:
        mock_response.json.return_value = json_data
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response
    mock_client.get.return_value = mock_response

    return mock_client


# ============================================================================
# Discord
# ============================================================================


class TestDiscordDeliveryChannel:
    """Discord Bot API — REST POST to /channels/{id}/messages."""

    def test_validate_config_valid(self) -> None:
        channel = DiscordDeliveryChannel()
        assert channel.validate_config({"bot_token": "discord-token-abc"}) is True

    def test_validate_config_legacy_key(self) -> None:
        """Legacy discord_bot_token key also accepted."""
        channel = DiscordDeliveryChannel()
        assert channel.validate_config({"discord_bot_token": "legacy-token"}) is True

    def test_validate_config_invalid(self) -> None:
        channel = DiscordDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"bot_token": ""}) is False
        assert channel.validate_config({"bot_token": "  "}) is False
        assert channel.validate_config({"other": "value"}) is False

    def test_send_mocked(self) -> None:
        """Successful Discord delivery with mocked httpx."""
        product = _make_product(bot_token="test-bot-token")
        channel = DiscordDeliveryChannel()

        mock_http = _make_mock_httpx()
        with patch("autoinfo.delivery.discord.httpx.Client", return_value=mock_http):
            result = channel.send(
                product=product,
                payload={"content": "Hello Discord!"},
                recipients=["1234567890"],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "discord"
        assert result.product_id == "prod-001"
        assert result.recipient_count == 1


# ============================================================================
# Telegram
# ============================================================================


class TestTelegramDeliveryChannel:
    """Telegram Bot API — POST /bot{token}/sendMessage."""

    def test_validate_config_valid(self) -> None:
        channel = TelegramDeliveryChannel()
        assert channel.validate_config({"bot_token": "tg-token-xyz"}) is True

    def test_validate_config_invalid(self) -> None:
        channel = TelegramDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"bot_token": ""}) is False
        assert channel.validate_config({"bot_token": "  "}) is False

    def test_send_mocked(self) -> None:
        """Successful Telegram delivery with mocked httpx."""
        product = _make_product(bot_token="tg-test-token")
        channel = TelegramDeliveryChannel()

        mock_http = _make_mock_httpx()
        with patch("autoinfo.delivery.telegram.httpx.Client", return_value=mock_http):
            result = channel.send(
                product=product,
                payload={"text": "Hello Telegram!"},
                recipients=["-1001234567890"],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "telegram"
        assert result.recipient_count == 1


# ============================================================================
# WeChat Work
# ============================================================================


class TestWeChatWorkDeliveryChannel:
    """WeChat Work (企业微信) — app message send with access_token."""

    def test_validate_config_valid(self) -> None:
        channel = WeChatWorkDeliveryChannel()
        assert channel.validate_config({
            "corp_id": "corp-123",
            "corp_secret": "secret-456",
            "agent_id": "1000001",
        }) is True

    def test_validate_config_invalid(self) -> None:
        channel = WeChatWorkDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"corp_id": "x"}) is False
        assert channel.validate_config({
            "corp_id": "x", "corp_secret": "y"
        }) is False  # missing agent_id

    def test_send_mocked(self) -> None:
        """Successful WeChat Work delivery — token acquired, message sent."""
        product = _make_product(
            corp_id="test-corp",
            corp_secret="test-secret",
            agent_id="1000001",
        )
        channel = WeChatWorkDeliveryChannel()

        # Mock both token GET and message POST
        token_json = {"errcode": 0, "access_token": "mock-access-token", "expires_in": 7200}
        send_json = {"errcode": 0, "errmsg": "ok"}

        mock_response_get = MagicMock()
        mock_response_get.status_code = 200
        mock_response_get.json.return_value = token_json
        mock_response_get.raise_for_status = MagicMock()

        mock_response_post = MagicMock()
        mock_response_post.status_code = 200
        mock_response_post.json.return_value = send_json

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_response_get
        mock_client.post.return_value = mock_response_post

        with patch("autoinfo.delivery.wechat_work.httpx.Client", return_value=mock_client):
            result = channel.send(
                product=product,
                payload={"content": "Hello WeChat Work!", "msgtype": "text"},
                recipients=["user001", "user002"],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "wechat_work"
        assert result.recipient_count == 2


# ============================================================================
# WeChat OA
# ============================================================================


class TestWeChatOADeliveryChannel:
    """WeChat Official Account (公众号) — template message send."""

    def test_validate_config_valid(self) -> None:
        channel = WeChatOADeliveryChannel()
        assert channel.validate_config({
            "app_id": "wx-app-123",
            "app_secret": "wx-secret-456",
            "template_id": "tmpl-789",
        }) is True

    def test_validate_config_invalid(self) -> None:
        channel = WeChatOADeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"app_id": "x"}) is False
        assert channel.validate_config({
            "app_id": "x", "app_secret": "y"
        }) is False  # missing template_id

    def test_send_mocked(self) -> None:
        """Successful WeChat OA delivery — token acquired, template sent."""
        product = _make_product(
            app_id="wx-test-app",
            app_secret="wx-test-secret",
            template_id="tmpl-test",
        )
        channel = WeChatOADeliveryChannel()

        token_json = {"errcode": 0, "access_token": "oa-token", "expires_in": 7200}
        send_json = {"errcode": 0, "errmsg": "ok", "msgid": 123456}

        mock_response_get = MagicMock()
        mock_response_get.status_code = 200
        mock_response_get.json.return_value = token_json
        mock_response_get.raise_for_status = MagicMock()

        mock_response_post = MagicMock()
        mock_response_post.status_code = 200
        mock_response_post.json.return_value = send_json

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_response_get
        mock_client.post.return_value = mock_response_post

        with patch("autoinfo.delivery.wechat_oa.httpx.Client", return_value=mock_client):
            result = channel.send(
                product=product,
                payload={
                    "data": {
                        "first": {"value": "Hello", "color": "#173177"},
                    },
                },
                recipients=["openid-001", "openid-002"],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "wechat_oa"
        assert result.recipient_count == 2


# ============================================================================
# DingTalk
# ============================================================================


class TestDingTalkDeliveryChannel:
    """DingTalk (钉钉) — robot webhook or app API mode."""

    # -- validate_config -------------------------------------------------

    def test_validate_config_webhook_valid(self) -> None:
        channel = DingTalkDeliveryChannel()
        assert channel.validate_config({
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        }) is True

    def test_validate_config_access_token_valid(self) -> None:
        """access_token alone builds a valid webhook URL."""
        channel = DingTalkDeliveryChannel()
        assert channel.validate_config({"access_token": "my-token"}) is True

    def test_validate_config_app_key_secret_valid(self) -> None:
        channel = DingTalkDeliveryChannel()
        assert channel.validate_config({
            "app_key": "ding-app", "app_secret": "ding-secret"
        }) is True

    def test_validate_config_invalid(self) -> None:
        channel = DingTalkDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"webhook_url": "https://other.com/robot"}) is False
        assert channel.validate_config({"app_key": "x"}) is False  # no app_secret

    # -- send mocked: robot webhook -------------------------------------

    def test_send_robot_mocked(self) -> None:
        """DingTalk robot webhook delivery with mocked httpx."""
        product = _make_product(
            webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
        )
        channel = DingTalkDeliveryChannel()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("autoinfo.delivery.dingtalk.httpx.Client", return_value=mock_client):
            result = channel.send(
                product=product,
                payload={"content": "DingTalk hello!", "msgtype": "text"},
                recipients=[],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "dingtalk"
        assert result.recipient_count == 1  # robot mode counts as 1

    # -- send mocked: app API -------------------------------------------

    def test_send_api_mocked(self) -> None:
        """DingTalk API mode delivery with mocked httpx."""
        product = _make_product(
            app_key="ding-api-key",
            app_secret="ding-api-secret",
            robot_code="robot-001",
        )
        channel = DingTalkDeliveryChannel()

        # OAuth token response
        token_json = {"accessToken": "api-token-abc", "expiresIn": 7200}
        # Batch send response
        send_json = {"errcode": 0, "errmsg": "ok"}

        mock_response_token = MagicMock()
        mock_response_token.status_code = 200
        mock_response_token.json.return_value = token_json
        mock_response_token.raise_for_status = MagicMock()

        mock_response_send = MagicMock()
        mock_response_send.status_code = 200
        mock_response_send.json.return_value = send_json

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        # First call: OAuth token POST
        mock_client.post.side_effect = [mock_response_send, mock_response_token]
        # Actually token is called FIRST, then batch send.
        # Let's use side_effect in the right order:
        mock_client.post.side_effect = None
        mock_client.post.return_value = mock_response_send

        with patch("autoinfo.delivery.dingtalk.httpx.Client", return_value=mock_client):
            # Patch the OAuth token fetch separately since it also creates
            # an httpx.Client
            with patch.object(
                DingTalkDeliveryChannel, "_get_oauth_token",
                return_value="api-token-abc",
            ):
                result = channel.send(
                    product=product,
                    payload={"content": "API hello!", "msgtype": "sampleText"},
                    recipients=["user001", "user002"],
                )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "dingtalk"
        assert result.recipient_count == 2


# ============================================================================
# FeiShu
# ============================================================================


class TestFeiShuDeliveryChannel:
    """FeiShu (飞书 / Lark) — webhook bot or app API mode."""

    def test_validate_config_webhook_valid(self) -> None:
        channel = FeiShuDeliveryChannel()
        assert channel.validate_config({
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc-123",
        }) is True

    def test_validate_config_webhook_http(self) -> None:
        """HTTP webhook URL is also accepted."""
        channel = FeiShuDeliveryChannel()
        assert channel.validate_config({
            "webhook_url": "http://my-lark.internal/hook",
        }) is True

    def test_validate_config_api_valid(self) -> None:
        channel = FeiShuDeliveryChannel()
        assert channel.validate_config({
            "mode": "api",
            "app_id": "feishu-app",
            "app_secret": "feishu-secret",
        }) is True

    def test_validate_config_invalid(self) -> None:
        channel = FeiShuDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"mode": "api"}) is False
        assert channel.validate_config({
            "mode": "api", "app_id": "x"
        }) is False  # missing app_secret
        assert channel.validate_config({"mode": "invalid"}) is False

    def test_send_webhook_mocked(self) -> None:
        """FeiShu webhook delivery with mocked httpx."""
        product = _make_product(
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test-key",
        )
        channel = FeiShuDeliveryChannel()

        mock_http = _make_mock_httpx()
        with patch("autoinfo.delivery.feishu.httpx.Client", return_value=mock_http):
            result = channel.send(
                product=product,
                payload={"content": "FeiShu hello!"},
                recipients=[],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "feishu"

    def test_send_api_mocked(self) -> None:
        """FeiShu API mode delivery with mocked httpx."""
        product = _make_product(
            mode="api",
            app_id="feishu-app-id",
            app_secret="feishu-app-secret",
        )
        channel = FeiShuDeliveryChannel()

        # Tenant token response
        token_json = {"code": 0, "tenant_access_token": "t-token", "expire": 7200}
        # Send response
        send_json = {"code": 0, "msg": "ok", "data": {"message_id": "msg-001"}}

        mock_response_token = MagicMock()
        mock_response_token.status_code = 200
        mock_response_token.json.return_value = token_json
        mock_response_token.raise_for_status = MagicMock()

        mock_response_send = MagicMock()
        mock_response_send.status_code = 200
        mock_response_send.json.return_value = send_json

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response_send

        with patch("autoinfo.delivery.feishu.httpx.Client", return_value=mock_client):
            with patch.object(
                FeiShuDeliveryChannel, "_get_token",
                return_value="t-token",
            ):
                result = channel.send(
                    product=product,
                    payload={"content": "FeiShu API hello!"},
                    recipients=["ou_abc123"],
                )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "feishu"


# ============================================================================
# RSS
# ============================================================================


class TestRSSDeliveryChannel:
    """RSS 2.0 XML generation — pure XML, no network."""

    def test_validate_config_valid(self) -> None:
        channel = RSSDeliveryChannel()
        assert channel.validate_config({
            "feed_url": "/tmp/feed.xml",
            "title": "My Feed",
            "description": "A test RSS feed",
        }) is True

    def test_validate_config_invalid(self) -> None:
        channel = RSSDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"feed_url": "/tmp/feed.xml"}) is False
        assert channel.validate_config({
            "feed_url": "/tmp/feed.xml", "title": "Feed"
        }) is False  # missing description
        assert channel.validate_config({
            "feed_url": "  ", "title": "T", "description": "D"
        }) is False

    def test_send_mocked(self, tmp_path: Path) -> None:
        """RSS feed generated and written to disk — no network needed."""
        feed_file = tmp_path / "output" / "feed.xml"
        product = _make_product()

        channel = RSSDeliveryChannel()
        result = channel.send(
            product=product,
            payload={
                "feed_url": str(feed_file),
                "title": "Test RSS Feed",
                "description": "Unit test generated feed",
                "entries": [
                    {
                        "title": "Entry One",
                        "source_url": "https://example.com/1",
                        "summary": "First entry summary",
                        "entry_id": "entry-001",
                        "collected_at": "2026-07-15T10:30:00+00:00",
                    },
                ],
            },
            recipients=[],
        )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.recipient_count == 1
        assert feed_file.exists()

        raw = feed_file.read_text(encoding="utf-8")
        assert "<?xml" in raw
        assert "<rss" in raw
        assert "Test RSS Feed" in raw
        assert "Entry One" in raw
        assert "https://example.com/1" in raw

    def test_send_no_entries_generates_empty_feed(self, tmp_path: Path) -> None:
        """RSS with no entries still generates a valid XML feed."""
        feed_file = tmp_path / "empty.xml"
        product = _make_product()

        channel = RSSDeliveryChannel()
        result = channel.send(
            product=product,
            payload={
                "feed_url": str(feed_file),
                "title": "Empty Feed",
                "description": "No entries feed",
                "entries": [],
            },
            recipients=[],
        )

        assert result.status == "success"
        assert feed_file.exists()
        content = feed_file.read_text(encoding="utf-8")
        assert "<rss" in content
        assert "<channel" in content
        assert "<item>" not in content  # no items


# ============================================================================
# Webhook
# ============================================================================


class TestWebhookDeliveryChannel:
    """HTTP POST webhook channel."""

    def test_validate_config_valid(self) -> None:
        channel = WebhookDeliveryChannel()
        assert channel.validate_config({"url": "https://hooks.example.com/abc"}) is True
        assert channel.validate_config({"url": "http://localhost:8080/hook"}) is True

    def test_validate_config_invalid(self) -> None:
        channel = WebhookDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"url": ""}) is False
        assert channel.validate_config({"url": "ftp://example.com"}) is False
        assert channel.validate_config({"url": 42}) is False  # type: ignore[arg-type]

    def test_send_mocked(self) -> None:
        """Successful webhook delivery with mocked httpx."""
        product = _make_product()
        channel = WebhookDeliveryChannel()

        mock_http = _make_mock_httpx()
        with patch("autoinfo.delivery.httpx.Client", return_value=mock_http):
            result = channel.send(
                product=product,
                payload={"event": "test"},
                recipients=["https://hooks.example.com/test"],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "webhook"
        assert result.recipient_count == 1


# ============================================================================
# REST API
# ============================================================================


class TestRESTAPIDeliveryChannel:
    """HTTP POST to a REST API endpoint."""

    def test_validate_config_valid(self) -> None:
        channel = RESTAPIDeliveryChannel()
        assert channel.validate_config({"url": "https://api.example.com/v1/data"}) is True

    def test_validate_config_invalid(self) -> None:
        channel = RESTAPIDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"url": ""}) is False
        assert channel.validate_config({"url": "file:///tmp"}) is False
        assert channel.validate_config({"url": 123}) is False  # type: ignore[arg-type]

    def test_send_mocked(self) -> None:
        """Successful REST API delivery with mocked httpx."""
        product = _make_product(api_key="test-api-key")
        channel = RESTAPIDeliveryChannel()

        mock_http = _make_mock_httpx()
        with patch("autoinfo.delivery.httpx.Client", return_value=mock_http):
            result = channel.send(
                product=product,
                payload={"key": "value"},
                recipients=["https://api.example.com/v1/data"],
            )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.channel == "rest_api"
        assert result.recipient_count == 1


# ============================================================================
# File Export
# ============================================================================


class TestFileExportDeliveryChannel:
    """Write payload as JSON to a local file."""

    def test_validate_config_valid(self) -> None:
        channel = FileExportDeliveryChannel()
        assert channel.validate_config({"export_path": "/tmp/output.json"}) is True
        assert channel.validate_config({"path": "/tmp/output.json"}) is True

    def test_validate_config_invalid(self) -> None:
        channel = FileExportDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"export_path": ""}) is False
        assert channel.validate_config({"export_path": "  "}) is False

    def test_send_via_recipients(self, tmp_path: Path) -> None:
        """Write payload to path specified in recipients."""
        out_file = tmp_path / "delivery.json"
        product = _make_product()
        channel = FileExportDeliveryChannel()

        result = channel.send(
            product=product,
            payload={"key": "value", "nested": {"a": 1}},
            recipients=[str(out_file)],
        )

        assert result.status == "success"
        assert result.recipient_count == 1
        assert out_file.exists()

        import json
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data == {"key": "value", "nested": {"a": 1}}

    def test_send_via_config_export_path(self, tmp_path: Path) -> None:
        """Write payload to path from config['export_path']."""
        out_file = tmp_path / "config_export.json"
        product = _make_product(export_path=str(out_file))
        channel = FileExportDeliveryChannel()

        result = channel.send(
            product=product,
            payload={"mode": "config"},
            recipients=[],
        )

        assert result.status == "success"
        assert out_file.exists()

    def test_send_no_path_returns_failed(self) -> None:
        """Missing path results in failed delivery."""
        product = _make_product()
        channel = FileExportDeliveryChannel()

        result = channel.send(
            product=product,
            payload={"data": "test"},
            recipients=[],
        )

        assert result.status == "failed"
        assert "No output path" in (result.error or "")


# ============================================================================
# deliver_with_retry
# ============================================================================


class TestDeliverWithRetry:
    """Retry / SLA logic in deliver_with_retry()."""

    def test_success_first_attempt(self) -> None:
        """Returns success immediately when channel.send() succeeds."""
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.return_value = DeliveryResult(
            product_id="p1",
            channel="test-channel",
            status="success",
            recipient_count=1,
        )

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                result = deliver_with_retry(
                    channel=mock_channel,
                    product=product,
                    payload={"k": "v"},
                    recipients=["r1"],
                )

        assert result.status == "success"
        mock_channel.send.assert_called_once()

    def test_retry_on_failure_then_succeed(self) -> None:
        """Retries when send returns 'failed', then succeeds."""
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.side_effect = [
            DeliveryResult(product_id="p1", channel="test", status="failed",
                           error="transient error"),
            DeliveryResult(product_id="p1", channel="test", status="failed",
                           error="transient error"),
            DeliveryResult(product_id="p1", channel="test", status="success",
                           recipient_count=1),
        ]

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                result = deliver_with_retry(
                    channel=mock_channel,
                    product=product,
                    payload={"k": "v"},
                    recipients=["r1"],
                )

        assert result.status == "success"
        assert mock_channel.send.call_count == 3

    def test_retries_exhausted_on_failure(self) -> None:
        """Returns failed after exhausting all retries."""
        failed = DeliveryResult(product_id="p1", channel="test", status="failed",
                                error="persistent error")
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.return_value = failed

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                result = deliver_with_retry(
                    channel=mock_channel,
                    product=product,
                    payload={"k": "v"},
                    recipients=["r1"],
                )

        assert result.status == "failed"
        # standard tier: max_retries=3, total attempts = 4
        assert mock_channel.send.call_count == 4
        assert result.error == "persistent error"

    def test_exception_with_retries_exhausted(self) -> None:
        """Returns failed after exceptions exhaust retries."""
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.side_effect = RuntimeError("network down")

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                result = deliver_with_retry(
                    channel=mock_channel,
                    product=product,
                    payload={"k": "v"},
                    recipients=["r1"],
                )

        assert result.status == "failed"
        assert mock_channel.send.call_count == 4
        assert "network down" in (result.error or "")

    def test_sla_tier_determines_retries(self) -> None:
        """SLA tier controls max retry count."""
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.return_value = DeliveryResult(
            product_id="p1", channel="test", status="failed", error="err"
        )

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                # critical: max_retries=5, total=6
                _ = deliver_with_retry(
                    channel=mock_channel, product=product,
                    payload={}, recipients=[], sla_tier="critical",
                )
                assert mock_channel.send.call_count == 6
                mock_channel.send.reset_mock()

                # standard: max_retries=3, total=4
                _ = deliver_with_retry(
                    channel=mock_channel, product=product,
                    payload={}, recipients=[], sla_tier="standard",
                )
                assert mock_channel.send.call_count == 4
                mock_channel.send.reset_mock()

                # bulk: max_retries=1, total=2
                _ = deliver_with_retry(
                    channel=mock_channel, product=product,
                    payload={}, recipients=[], sla_tier="bulk",
                )
                assert mock_channel.send.call_count == 2

    def test_unknown_sla_tier_falls_back_to_standard(self) -> None:
        """Unknown SLA tier falls back to standard (3 retries)."""
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.return_value = DeliveryResult(
            product_id="p1", channel="test", status="failed", error="err"
        )

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                _ = deliver_with_retry(
                    channel=mock_channel, product=product,
                    payload={}, recipients=[], sla_tier="unknown",
                )

        # standard: 3 retries + 1 initial = 4
        assert mock_channel.send.call_count == 4

    def test_partial_status_returns_immediately(self) -> None:
        """'partial' status is returned without retrying."""
        mock_channel = MagicMock()
        mock_channel.name = "test-channel"
        mock_channel.send.return_value = DeliveryResult(
            product_id="p1", channel="test", status="partial",
            recipient_count=2, error="1 of 3 failed",
        )

        product = _make_product()

        with patch("autoinfo.delivery.append_delivery_log"):
            with patch("time.sleep"):
                result = deliver_with_retry(
                    channel=mock_channel,
                    product=product,
                    payload={"k": "v"},
                    recipients=["r1", "r2"],
                )

        assert result.status == "partial"
        mock_channel.send.assert_called_once()
