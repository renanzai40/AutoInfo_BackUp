"""Tests for podcast RSS generation with enclosures + MP3 hosting.

Covers:
- PodcastRSSDeliveryChannel: XML generation with enclosure + itunes:*
- _build_podcast_rss: standalone builder with itunes namespace
- MP3 persistence via _render_audio persist_path
- Regression: plain RSS _export_rss has no enclosure
- GET /media/{file_path} endpoint
"""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from autoinfo.api.server import app
from autoinfo.delivery.rss import (
    ITUNES_NS,
    PodcastRSSDeliveryChannel,
    _build_podcast_rss,
)
from autoinfo.models import DeliveryResult, Product, ProductType

NS = {"itunes": ITUNES_NS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    product_id: str = "prod-podcast-001",
    domain: str = "test-podcast",
    **config: object,
) -> Product:
    return Product(
        id=product_id,
        domain=domain,
        type=ProductType.PROCESSED,
        name="test-podcast",
        config={k: v for k, v in config.items()},
    )


def _minimal_episodes() -> list[dict]:
    return [
        {
            "title": "Episode 1 — Hello World",
            "description": "Our first podcast episode.",
            "audio_url": "media/exports/test-podcast/podcast/ep-001.mp3",
            "duration": "05:30",
            "guid": "ep-001",
            "pub_date": "2026-08-02T12:00:00+00:00",
            "episode_type": "full",
            "season": 1,
            "episode": 1,
        },
    ]


# ---------------------------------------------------------------------------
# _build_podcast_rss — standalone builder
# ---------------------------------------------------------------------------


class TestBuildPodcastRSS:
    def test_generates_valid_xml_with_enclosure(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="Test Podcast",
            description="A test podcast feed",
            link="https://example.com",
            language="en",
            author="Test Author",
            image_url="https://example.com/cover.jpg",
            explicit="no",
            category="Technology",
            subcategory="Podcasts",
            episodes=_minimal_episodes(),
            base_url="http://localhost:8741",
        )
        root = ET.fromstring(xml_bytes)
        assert root.tag == "rss"
        assert root.get("version") == "2.0"

        channel = root.find("channel")
        assert channel is not None
        assert channel.find("title").text == "Test Podcast"  # type: ignore[union-attr]
        assert channel.find("language").text == "en"  # type: ignore[union-attr]
        assert channel.find("generator").text == "AutoInfo"  # type: ignore[union-attr]

        enclosure = channel.find(".//enclosure")
        assert enclosure is not None, "Missing <enclosure> element"
        assert enclosure.get("type") == "audio/mpeg"
        assert enclosure.get("url") == (
            "http://localhost:8741/media/exports/test-podcast/podcast/ep-001.mp3"
        )

    def test_preserves_xml_declaration(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A", image_url="", explicit="no",
            category="Tech", subcategory="", episodes=_minimal_episodes(),
            base_url="http://localhost:8741",
        )
        xml_str = xml_bytes.decode("utf-8")
        assert xml_str.startswith('<?xml')

    def test_itunes_namespace_declared(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A", image_url="", explicit="no",
            category="Tech", subcategory="", episodes=_minimal_episodes(),
            base_url="http://localhost:8741",
        )
        root = ET.fromstring(xml_bytes)
        declared_uri = root.get(f"{{{ITUNES_NS}}}") if False else None
        attr_key = f"xmlns:itunes"
        # ET normalizes namespace prefixes; check root attrib for xmlns:itunes
        raw = xml_bytes.decode("utf-8")
        assert 'xmlns:itunes' in raw
        assert ITUNES_NS in raw

    def test_itunes_author_present(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="Test Author", image_url="",
            explicit="no", category="Tech", subcategory="",
            episodes=_minimal_episodes(), base_url="http://localhost:8741",
        )
        raw = xml_bytes.decode("utf-8")
        assert "<itunes:author>Test Author</itunes:author>" in raw

    def test_itunes_explicit_present(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A", image_url="", explicit="clean",
            category="Tech", subcategory="", episodes=_minimal_episodes(),
            base_url="http://localhost:8741",
        )
        raw = xml_bytes.decode("utf-8")
        assert "<itunes:explicit>clean</itunes:explicit>" in raw

    def test_itunes_image_when_provided(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A",
            image_url="https://example.com/cover.jpg",
            explicit="no", category="Tech", subcategory="",
            episodes=_minimal_episodes(), base_url="http://localhost:8741",
        )
        raw = xml_bytes.decode("utf-8")
        assert '<itunes:image' in raw
        assert 'href="https://example.com/cover.jpg"' in raw

    def test_itunes_category_and_subcategory(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A", image_url="", explicit="no",
            category="Technology", subcategory="Podcasts",
            episodes=_minimal_episodes(), base_url="http://localhost:8741",
        )
        raw = xml_bytes.decode("utf-8")
        assert '<itunes:category text="Technology">' in raw
        assert '<itunes:category text="Podcasts"' in raw

    def test_itunes_per_episode_metadata(self) -> None:
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A", image_url="", explicit="no",
            category="Tech", subcategory="", episodes=_minimal_episodes(),
            base_url="http://localhost:8741",
        )
        raw = xml_bytes.decode("utf-8")
        assert "<itunes:duration>05:30</itunes:duration>" in raw
        assert "<itunes:episodeType>full</itunes:episodeType>" in raw
        assert "<itunes:season>1</itunes:season>" in raw
        assert "<itunes:episode>1</itunes:episode>" in raw

    def test_no_enclosure_when_no_audio_url(self) -> None:
        episodes = [{"title": "No Audio", "description": "No audio file"}]
        xml_bytes = _build_podcast_rss(
            title="T", description="D", link="http://x.com",
            language="en", author="A", image_url="", explicit="no",
            category="Tech", subcategory="", episodes=episodes,
            base_url="http://localhost:8741",
        )
        raw = xml_bytes.decode("utf-8")
        assert "<enclosure" not in raw


# ---------------------------------------------------------------------------
# PodcastRSSDeliveryChannel
# ---------------------------------------------------------------------------


class TestPodcastRSSDeliveryChannel:
    def test_validate_config_valid(self) -> None:
        channel = PodcastRSSDeliveryChannel()
        assert channel.validate_config({
            "feed_url": "/tmp/podcast.xml",
            "title": "My Podcast",
            "description": "A test podcast",
            "author": "Test Author",
        }) is True

    def test_validate_config_invalid(self) -> None:
        channel = PodcastRSSDeliveryChannel()
        assert channel.validate_config({}) is False
        assert channel.validate_config({"feed_url": "/tmp/podcast.xml"}) is False
        assert channel.validate_config({
            "feed_url": "/tmp/podcast.xml",
            "title": "My Podcast",
            "description": "A test podcast",
            # missing author
        }) is False

    def test_send_generates_podcast_rss(self, tmp_path: Path) -> None:
        feed_file = tmp_path / "podcast" / "feed.xml"
        product = _make_product()
        channel = PodcastRSSDeliveryChannel()

        result = channel.send(
            product=product,
            payload={
                "feed_url": str(feed_file),
                "title": "AutoInfo Podcast",
                "description": "AI-generated podcast",
                "author": "Test Author",
                "episodes": _minimal_episodes(),
            },
            recipients=[],
        )

        assert isinstance(result, DeliveryResult)
        assert result.status == "success"
        assert result.recipient_count == 1
        assert feed_file.exists()

        raw = feed_file.read_text(encoding="utf-8")
        assert '<?xml' in raw
        assert '<rss' in raw
        assert 'xmlns:itunes' in raw
        assert '<enclosure' in raw
        assert '<itunes:author>Test Author</itunes:author>' in raw

    def test_send_no_episodes_but_valid_xml(self, tmp_path: Path) -> None:
        feed_file = tmp_path / "empty-podcast.xml"
        product = _make_product()
        channel = PodcastRSSDeliveryChannel()

        result = channel.send(
            product=product,
            payload={
                "feed_url": str(feed_file),
                "title": "Empty Podcast",
                "description": "No episodes yet",
                "author": "Test Author",
                "episodes": [],
            },
            recipients=[],
        )

        assert result.status == "success"
        assert feed_file.exists()
        raw = feed_file.read_text(encoding="utf-8")
        assert '<channel' in raw
        assert '<enclosure' not in raw

    def test_health_check(self) -> None:
        channel = PodcastRSSDeliveryChannel()
        health = channel.health_check()
        assert isinstance(health, dict)
        assert "healthy" in health
        assert health["channel"] == "podcast-rss"

    def test_name(self) -> None:
        channel = PodcastRSSDeliveryChannel()
        assert channel.name == "podcast-rss"


# ---------------------------------------------------------------------------
# MP3 persistence — _render_audio with persist_path
# ---------------------------------------------------------------------------


class TestAudioPersistence:
    def test_persist_path_writes_file(self, tmp_path: Path) -> None:
        from autoinfo.output import _maybe_persist_audio

        test_bytes = b"fake-mp3-data"
        persist = tmp_path / "exports" / "test-domain" / "podcast" / "ep-001.mp3"

        _maybe_persist_audio(test_bytes, str(persist))

        assert persist.exists()
        assert persist.read_bytes() == test_bytes

    def test_persist_creates_parent_dirs(self, tmp_path: Path) -> None:
        from autoinfo.output import _maybe_persist_audio

        test_bytes = b"fake-mp3-data"
        persist = tmp_path / "deeply" / "nested" / "dir" / "ep-001.mp3"

        _maybe_persist_audio(test_bytes, str(persist))

        assert persist.exists()
        assert persist.read_bytes() == test_bytes

    def test_make_audio_persist_path(self) -> None:
        from autoinfo.output import _make_audio_persist_path

        path = _make_audio_persist_path("my-domain")
        assert path.startswith("exports/my-domain/podcast/ep-")
        assert path.endswith(".mp3")

    def test_make_audio_persist_path_none_domain(self) -> None:
        from autoinfo.output import _make_audio_persist_path

        path = _make_audio_persist_path(None)
        assert path.startswith("exports/all/podcast/ep-")
        assert path.endswith(".mp3")


# ---------------------------------------------------------------------------
# REST API — GET /media/{file_path}
# ---------------------------------------------------------------------------


class TestMediaEndpoint:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def test_serves_mp3_from_exports(self, client: TestClient, tmp_path: Path) -> None:
        mp3_dir = tmp_path / "exports" / "test-podcast" / "podcast"
        mp3_dir.mkdir(parents=True, exist_ok=True)
        mp3_file = mp3_dir / "ep-001.mp3"
        mp3_file.write_bytes(b"fake-mp3-bytes")

        with patch("autoinfo.api.server.Path.cwd", return_value=tmp_path):
            response = client.get(
                "/media/exports/test-podcast/podcast/ep-001.mp3",
            )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert response.content == b"fake-mp3-bytes"

    def test_media_404_for_nonexistent_file(self, client: TestClient, tmp_path: Path) -> None:
        with patch("autoinfo.api.server.Path.cwd", return_value=tmp_path):
            response = client.get("/media/exports/nonexistent/ep-001.mp3")

        assert response.status_code == 404

    def test_media_404_for_path_traversal(self, client: TestClient, tmp_path: Path) -> None:
        with patch("autoinfo.api.server.Path.cwd", return_value=tmp_path):
            response = client.get("/media/../../../etc/passwd")

        assert response.status_code == 404

    def test_serves_file_from_data_dir(self, client: TestClient, tmp_path: Path) -> None:
        data_dir = tmp_path / "data" / "podcast"
        data_dir.mkdir(parents=True, exist_ok=True)
        mp3_file = data_dir / "ep-002.mp3"
        mp3_file.write_bytes(b"data-mp3-bytes")

        with patch("autoinfo.api.server.Path.cwd", return_value=tmp_path):
            response = client.get("/media/data/podcast/ep-002.mp3")

        assert response.status_code == 200
        assert response.content == b"data-mp3-bytes"


# ---------------------------------------------------------------------------
# Regression — plain RSS _export_rss has no enclosure
# ---------------------------------------------------------------------------


class TestPlainRSSNoEnclosureRegression:
    def test_export_rss_no_enclosure(self, tmp_path: Path) -> None:
        from autoinfo.output import _export_rss

        entries = [
            {
                "title": "Test Entry",
                "source_url": "https://example.com/1",
                "summary": "A test summary",
                "entry_id": "entry-001",
                "collected_at": "2026-08-02T12:00:00+00:00",
            },
        ]

        result = _export_rss(
            export_dir=tmp_path / "exports",
            domain="test-domain",
            entries=entries,
            timestamp="20260802_120000",
            domain_label="test-domain",
        )

        assert result["success"] is True
        assert result["format"] == "rss"

        path = result["path"]
        raw = Path(path).read_text(encoding="utf-8")
        assert '<enclosure' not in raw, "Plain RSS _export_rss must NOT have enclosure"
        assert 'itunes:' not in raw, "Plain RSS _export_rss must NOT have itunes namespace"
