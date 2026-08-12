#!/usr/bin/env python3
"""
Q2b Collector Validation — 12 New Collectors (Happy Path)

Tests each of the 12 new collectors (introduced in v1.8) for:
  1. Basic instantiation
  2. requires_key() check (if defined)
  3. Mock happy-path collection with mock httpx transport

Each collector is tested independently.  Report at the end shows
per-collector PASS/FAIL/SKIP and overall counts.
"""

import json
import os
import sys
import uuid
import traceback
from typing import Any

import httpx

# Ensure we can import from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from autoinfo.models import Item

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

results: list[dict] = []


def test(name: str, fn):
    """Run a named test and record result."""
    try:
        fn()
        results.append({"name": name, "result": PASS})
        print(f"  ✅ {name}")
    except Exception as e:
        results.append({"name": name, "result": FAIL, "error": str(e)})
        print(f"  ❌ {name}: {e}")
        traceback.print_exc()


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: expected {b!r}, got {a!r}")


def assert_in(item, container, msg=""):
    if item not in container:
        raise AssertionError(f"{msg}: {item!r} not in {container!r}")


# ---------------------------------------------------------------------------
# 1. AP API (ap_api) — needs api_key
# ---------------------------------------------------------------------------

def test_ap_api():
    print("\n--- 1. AP API (ap_api) ---")

    # 1a. Instantiation
    from autoinfo.collectors.ap_api import APAPIHandler

    handler = APAPIHandler(api_key="test-ap-key-12345")
    assert handler.api_key == "test-ap-key-12345"

    # 1b. requires_key()
    assert APAPIHandler.requires_key() is True

    # 1c. Mock happy-path collection



# AP API standalone test functions ---------------------------------------

def _ap_instantiation():
    from autoinfo.collectors.ap_api import APAPIHandler
    h = APAPIHandler(api_key="test-key")
    assert h.api_key == "test-key"
    h2 = APAPIHandler()
    assert h2.api_key == ""


def _ap_requires_key():
    from autoinfo.collectors.ap_api import APAPIHandler
    assert APAPIHandler.requires_key() is True


def _ap_mock():
    from autoinfo.collectors.ap_api import APAPIHandler

    def mock_handler(request):
        data = {
            "data": {
                "items": [
                    {
                        "uri": "ap://article/001",
                        "headline": "Global Markets Rally on Tech Earnings",
                        "body": "Stock markets surged worldwide following strong earnings...",
                        "byline": "By John Smith",
                        "published": "2024-06-15T10:30:00Z",
                        "section": "Business",
                        "language": "en",
                        "source": "Associated Press",
                    }
                ]
            }
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.ap_api as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = APAPIHandler(api_key="fake-ap-key")
            articles = h.fetch(limit=10)
            items = [h.to_item(a) for a in articles]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "ap_api")
            assert_eq(items[0].title, "Global Markets Rally on Tech Earnings")
            assert "Stock markets" in items[0].content
        finally:
            mod.httpx.get = orig


test("ap_api: instantiation", _ap_instantiation)
test("ap_api: requires_key", _ap_requires_key)
test("ap_api: mock collection", _ap_mock)


# ---------------------------------------------------------------------------
# 2. Apple Podcasts (apple_podcasts) — no key needed
# ---------------------------------------------------------------------------

def _test_apple_instantiation():
    from autoinfo.collectors.apple_podcasts import ApplePodcastsHandler
    h = ApplePodcastsHandler()
    assert h is not None
    h2 = ApplePodcastsHandler({"term": "AI"})
    assert h2.config.get("term") == "AI"


def _test_apple_mock():
    from autoinfo.collectors.apple_podcasts import ApplePodcastsHandler

    def mock_handler(request):
        data = {
            "resultCount": 1,
            "results": [
                {
                    "trackId": 123456789,
                    "trackName": "AI Frontiers Podcast",
                    "description": "Weekly podcast exploring the latest in AI.",
                    "artistName": "TechMedia Inc.",
                    "feedUrl": "https://feeds.example.com/ai-frontiers",
                    "releaseDate": "2024-01-15T00:00:00Z",
                    "collectionViewUrl": "https://podcasts.apple.com/podcast/id123456789",
                    "primaryGenreName": "Technology",
                    "artworkUrl600": "https://example.com/artwork.jpg",
                    "trackCount": 50,
                    "country": "USA",
                    "genres": ["Technology", "Science"],
                }
            ],
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.apple_podcasts as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = ApplePodcastsHandler({"term": "AI podcast"})
            shows = h.fetch(term="AI podcast", limit=10)
            items = [h.to_item(s) for s in shows]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "apple_podcasts")
            assert_eq(items[0].title, "AI Frontiers Podcast")
            assert items[0].raw_data.get("feed_url") == "https://feeds.example.com/ai-frontiers"
        finally:
            mod.httpx.get = orig


test("apple_podcasts: instantiation", _test_apple_instantiation)
test("apple_podcasts: mock collection", _test_apple_mock)


# ---------------------------------------------------------------------------
# 3. Bilibili (bilibili) — no key needed
# ---------------------------------------------------------------------------

def _test_bilibili_instantiation():
    from autoinfo.collectors.bilibili import BilibiliHandler
    h = BilibiliHandler()
    assert h is not None
    h2 = BilibiliHandler({"query": "大模型"})
    assert h2.query == "大模型"


def _test_bilibili_mock():
    from autoinfo.collectors.bilibili import BilibiliHandler

    def mock_handler(request):
        data = {
            "code": 0,
            "message": "success",
            "data": {
                "result": {
                    "video": [
                        {
                            "aid": 123456789,
                            "bvid": "BV1xx411c7mD",
                            "title": "大模型训练技术详解",
                            "description": "深入讲解大规模语言模型的训练方法...",
                            "author": "AI技术分享",
                            "created": 1700000000,
                            "pic": "https://example.com/thumb.jpg",
                            "stat": {"view": 50000},
                        }
                    ]
                }
            },
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.bilibili as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = BilibiliHandler({"query": "大模型"})
            videos = h.fetch(limit=10)
            items = [h.to_item(v) for v in videos]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "bilibili")
            assert "大模型" in items[0].title
            assert items[0].raw_data.get("bvid") == "BV1xx411c7mD"
        finally:
            mod.httpx.get = orig


test("bilibili: instantiation", _test_bilibili_instantiation)
test("bilibili: mock collection", _test_bilibili_mock)


# ---------------------------------------------------------------------------
# 4. DBLP (dblp) — no key needed
# ---------------------------------------------------------------------------

def _test_dblp_instantiation():
    from autoinfo.collectors.dblp import DBLPHandler
    h = DBLPHandler()
    assert h is not None
    assert h.source_name == "dblp"


def _test_dblp_mock():
    from autoinfo.collectors.dblp import DBLPHandler

    def mock_handler(request):
        data = {
            "result": {
                "hits": {
                    "@total": "2",
                    "hit": [
                        {
                            "@score": "1.0",
                            "@id": "https://dblp.org/rec/conf/nips/Doe2024",
                            "info": {
                                "title": "Neural Network Optimization",
                                "doi": "10.1234/nn2024",
                                "authors": {"author": ["John Smith", "Jane Doe"]},
                                "year": "2024",
                                "venue": "NeurIPS 2024",
                            },
                        },
                        {
                            "@score": "0.8",
                            "@id": "https://dblp.org/rec/journals/ai/Lee2023",
                            "info": {
                                "title": "Symbolic Reasoning in LLMs",
                                "doi": "",
                                "authors": {"author": "Min Lee"},
                                "year": "2023",
                                "venue": "Artificial Intelligence",
                            },
                        },
                    ],
                }
            }
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.dblp as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = DBLPHandler()
            pubs = h.fetch("machine learning", limit=10)
            items = [h.to_item(p) for p in pubs]
            assert_eq(len(items), 2)
            assert_eq(items[0].source_platform, "dblp")
            assert_eq(items[0].title, "Neural Network Optimization")
            assert items[0].raw_data.get("venue") == "NeurIPS 2024"
        finally:
            mod.httpx.get = orig


test("dblp: instantiation", _test_dblp_instantiation)
test("dblp: mock collection", _test_dblp_mock)


# ---------------------------------------------------------------------------
# 5. NYT (nyt) — needs api_key
# ---------------------------------------------------------------------------

def _test_nyt_instantiation():
    from autoinfo.collectors.nyt import NYTHandler
    h = NYTHandler()
    assert h is not None
    h2 = NYTHandler({"api_key": "test-key", "query": "AI"})
    assert h2.api_key == "test-key"


def _test_nyt_mock():
    from autoinfo.collectors.nyt import NYTHandler

    def mock_handler(request):
        data = {
            "response": {
                "docs": [
                    {
                        "_id": "nyt://article/001",
                        "headline": {"main": "AI Startups Raise Record Funding"},
                        "abstract": "Venture capital investment in AI startups reached...",
                        "section_name": "Technology",
                        "subsection_name": "Startups",
                        "pub_date": "2024-06-15T09:00:00Z",
                        "web_url": "https://www.nytimes.com/2024/06/15/technology/ai-funding.html",
                        "byline": {"original": "By Jane Reporter"},
                        "word_count": 850,
                        "document_type": "article",
                    }
                ]
            }
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.nyt as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = NYTHandler({"api_key": "fake-nyt-key", "query": "AI funding"})
            articles = h.fetch(limit=10)
            items = [h.to_item(a) for a in articles]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "nyt")
            assert_eq(items[0].title, "AI Startups Raise Record Funding")
        finally:
            mod.httpx.get = orig


test("nyt: instantiation", _test_nyt_instantiation)
test("nyt: mock collection", _test_nyt_mock)


# ---------------------------------------------------------------------------
# 6. OpenAlex (openalex) — no key needed
# ---------------------------------------------------------------------------

def _test_openalex_instantiation():
    from autoinfo.collectors.openalex import OpenAlexHandler
    h = OpenAlexHandler()
    assert h is not None
    h2 = OpenAlexHandler({"query": "CRISPR"})
    assert h2.config.get("query") == "CRISPR"


def _test_openalex_mock():
    from autoinfo.collectors.openalex import OpenAlexHandler

    def mock_handler(request):
        data = {
            "results": [
                {
                    "id": "https://openalex.org/W4200000001",
                    "title": "Advances in CRISPR Gene Editing",
                    "abstract_inverted_index": {"crispr": [0], "gene": [1], "editing": [2]},
                    "authorships": [{"author": {"display_name": "Jane Doe"}}],
                    "cited_by_count": 42,
                    "publication_date": "2024-06-15",
                },
                {
                    "id": "https://openalex.org/W4200000002",
                    "title": "Machine Learning for Protein Folding",
                    "abstract_inverted_index": None,
                    "authorships": [],
                    "cited_by_count": 0,
                    "publication_date": "2023-01-01",
                },
            ],
            "meta": {"count": 2},
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.openalex as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = OpenAlexHandler({"query": "CRISPR"})
            articles = h.fetch(limit=5)
            items = [h.to_item(a) for a in articles]
            assert_eq(len(items), 2)
            assert_eq(items[0].source_platform, "openalex")
            assert_eq(items[0].title, "Advances in CRISPR Gene Editing")
            assert "crispr" in items[0].content
        finally:
            mod.httpx.get = orig


test("openalex: instantiation", _test_openalex_instantiation)
test("openalex: mock collection", _test_openalex_mock)


# ---------------------------------------------------------------------------
# 7. Reddit (reddit) — no key needed for public access (OAuth2)
# ---------------------------------------------------------------------------

def _test_reddit_instantiation():
    from autoinfo.collectors.reddit import RedditHandler
    h = RedditHandler({
        "client_id": "test", "client_secret": "test",
        "user_agent": "AutoInfo/1.0", "subreddits": ["MachineLearning"],
    })
    assert h is not None
    assert h.subreddits == ["MachineLearning"]


def _test_reddit_mock():
    from autoinfo.collectors.reddit import RedditHandler
    token_called = []

    def mock_handler(request):
        if "/api/v1/access_token" in str(request.url):
            token_called.append(True)
            return httpx.Response(200, json={
                "access_token": "fake-reddit-token-xxxx",
                "token_type": "bearer",
                "expires_in": 3600,
            }, request=request)
        data = {
            "data": {
                "children": [
                    {
                        "data": {
                            "name": "t3_abc123",
                            "title": "Latest advances in reinforcement learning",
                            "selftext": "Researchers at DeepMind have achieved...",
                            "author": "ml_researcher",
                            "subreddit": "MachineLearning",
                            "score": 250,
                            "num_comments": 45,
                            "created_utc": 1700000000.0,
                            "url": "https://reddit.com/r/MachineLearning/comments/abc123",
                        }
                    }
                ]
            }
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.reddit as mod
        orig_post = mod.httpx.post
        orig_get = mod.httpx.get
        mod.httpx.post = client.post
        mod.httpx.get = client.get
        try:
            h = RedditHandler({
                "client_id": "fake-client", "client_secret": "fake-secret",
                "user_agent": "AutoInfo/1.0", "subreddits": ["MachineLearning"],
            })
            posts = h.fetch(query="reinforcement learning", limit=5)
            items = [h.to_item(p) for p in posts]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "reddit")
            assert_eq(items[0].title, "Latest advances in reinforcement learning")
            assert len(token_called) == 1, "OAuth2 token should have been requested"
        finally:
            mod.httpx.post = orig_post
            mod.httpx.get = orig_get


test("reddit: instantiation", _test_reddit_instantiation)
test("reddit: mock collection", _test_reddit_mock)


# ---------------------------------------------------------------------------
# 8. Reuters MCP (reuters_mcp) — needs api_key
# ---------------------------------------------------------------------------

def _test_reuters_instantiation():
    from autoinfo.collectors.reuters_mcp import ReutersMCPHandler
    from autoinfo.config import SourceConfig
    cfg = SourceConfig(name="reuters-test", type="reuters_mcp",
                       url="https://api.reuters.com/content/v1/search",
                       settings={"api_key": "test-key"})
    h = ReutersMCPHandler(cfg)
    assert h is not None


def _test_reuters_requires_key():
    from autoinfo.collectors.reuters_mcp import ReutersMCPHandler
    assert ReutersMCPHandler.requires_key() is True


def _test_reuters_mock():
    from autoinfo.collectors.reuters_mcp import ReutersMCPHandler
    from autoinfo.config import SourceConfig

    def mock_handler(request):
        data = {
            "data": {
                "items": [
                    {
                        "id": "reuters-001",
                        "headline": "Fed Signals Rate Cut",
                        "body": "The Federal Reserve indicated...",
                        "byline": "Reuters Staff",
                        "published": "2024-06-15T08:00:00Z",
                        "section": "Economy",
                        "language": "en",
                        "source": "Reuters",
                        "url": "https://www.reuters.com/article/001",
                    }
                ]
            }
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.reuters_mcp as mod
        orig_post = mod.httpx.post
        mod.httpx.post = client.post
        try:
            cfg = SourceConfig(name="reuters-test", type="reuters_mcp",
                               url="https://api.reuters.com/content/v1/search",
                               settings={"api_key": "fake-reuters-key"})
            h = ReutersMCPHandler(cfg)
            articles = h.fetch(limit=10)
            items = [h.to_item(a) for a in articles]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "reuters_mcp")
            assert_eq(items[0].title, "Fed Signals Rate Cut")
        finally:
            mod.httpx.post = orig_post


test("reuters_mcp: instantiation", _test_reuters_instantiation)
test("reuters_mcp: requires_key", _test_reuters_requires_key)
test("reuters_mcp: mock collection", _test_reuters_mock)


# ---------------------------------------------------------------------------
# 9. Semantic Scholar (semantic_scholar) — needs api_key
# ---------------------------------------------------------------------------

def _test_semantic_scholar_instantiation():
    from autoinfo.collectors.semantic_scholar import SemanticScholarHandler
    h = SemanticScholarHandler()
    assert h is not None
    h2 = SemanticScholarHandler(api_key="test-key")
    assert h2.api_key == "test-key"


def _test_semantic_scholar_mock():
    from autoinfo.collectors.semantic_scholar import SemanticScholarHandler

    def mock_handler(request):
        data = {
            "data": [
                {
                    "paperId": "s2-001",
                    "title": "Deep Learning Survey",
                    "abstract": "A comprehensive survey of deep learning techniques...",
                    "authors": [{"name": "Alice Smith"}],
                    "citationCount": 150,
                    "publicationDate": "2024-03",
                },
                {
                    "paperId": "s2-002",
                    "title": "Transformer Architectures",
                    "abstract": "",
                    "authors": [],
                    "citationCount": 0,
                    "publicationDate": None,
                },
            ]
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.semantic_scholar as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = SemanticScholarHandler()
            papers = h.fetch("deep learning", limit=10)
            items = [h.to_item(p) for p in papers]
            assert_eq(len(items), 2)
            assert_eq(items[0].source_platform, "semantic_scholar")
            assert_eq(items[0].title, "Deep Learning Survey")
        finally:
            mod.httpx.get = orig


test("semantic_scholar: instantiation", _test_semantic_scholar_instantiation)
test("semantic_scholar: mock collection", _test_semantic_scholar_mock)


# ---------------------------------------------------------------------------
# 10. Spotify (spotify) — needs client credentials
# ---------------------------------------------------------------------------

def _test_spotify_instantiation():
    from autoinfo.collectors.spotify import SpotifyHandler
    h = SpotifyHandler({"client_id": "test", "client_secret": "test"})
    assert h is not None
    assert h.client_id == "test"


def _test_spotify_mock():
    from autoinfo.collectors.spotify import SpotifyHandler
    token_called = []

    def mock_handler(request):
        if "accounts.spotify.com" in str(request.url):
            token_called.append(True)
            return httpx.Response(200, json={
                "access_token": "fake-spotify-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }, request=request)
        data = {
            "items": [
                {
                    "id": "ep_001",
                    "name": "The Future of AGI",
                    "description": "A discussion on artificial general intelligence...",
                    "publisher": "Tech Podcasts Inc.",
                    "release_date": "2024-06-10",
                    "duration_ms": 2400000,
                    "languages": ["en"],
                    "external_urls": {"spotify": "https://open.spotify.com/episode/ep_001"},
                    "audio_preview_url": "https://p.scdn.co/mp3-preview/abc123",
                    "show": {
                        "id": "show_42",
                        "name": "Future Tech",
                        "publisher": "Tech Podcasts Inc.",
                        "description": "A podcast about future technology",
                    },
                    "explicit": False,
                    "type": "episode",
                }
            ]
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.spotify as mod
        orig_post = mod.httpx.post
        orig_get = mod.httpx.get
        mod.httpx.post = client.post
        mod.httpx.get = client.get
        try:
            h = SpotifyHandler({
                "client_id": "fake-sp-client", "client_secret": "fake-sp-secret",
                "show_id": "show_42",
            })
            episodes = h.fetch(limit=10, show_id="show_42")
            items = [h.to_item(e) for e in episodes]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "spotify")
            assert_eq(items[0].title, "The Future of AGI")
            assert len(token_called) == 1, "OAuth2 token should have been requested"
        finally:
            mod.httpx.post = orig_post
            mod.httpx.get = orig_get


test("spotify: instantiation", _test_spotify_instantiation)
test("spotify: mock collection", _test_spotify_mock)


# ---------------------------------------------------------------------------
# 11. USPTO (uspto) — no key needed
# ---------------------------------------------------------------------------

def _test_uspto_instantiation():
    from autoinfo.collectors.uspto import USPTOHandler
    h = USPTOHandler()
    assert h is not None


def _test_uspto_mock():
    from autoinfo.collectors.uspto import USPTOHandler

    def mock_handler(request):
        data = {
            "patents": [
                {
                    "patent_number": "US12000123",
                    "patent_title": "CRISPR-based Gene Therapy Method",
                    "patent_abstract": "A novel method for targeted gene therapy using CRISPR-Cas9...",
                    "patent_date": "2024-05-10",
                    "app_date": "2023-01-15",
                    "inventors": [{"inventor_first_name": "Alice", "inventor_last_name": "Johnson"}],
                    "assignee_organization": "GenTech Inc.",
                    "patent_num_cited_by_us_patents": 5,
                    "patent_num_combined_citations": 12,
                }
            ]
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.uspto as mod
        orig_post = mod.httpx.post
        mod.httpx.post = client.post
        try:
            h = USPTOHandler()
            patents = h.fetch("gene therapy", limit=10)
            items = [h.to_item(p) for p in patents]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "uspto")
            assert items[0].raw_data.get("patent_number") == "US12000123"
        finally:
            mod.httpx.post = orig_post


test("uspto: instantiation", _test_uspto_instantiation)
test("uspto: mock collection", _test_uspto_mock)


# ---------------------------------------------------------------------------
# 12. YouTube (youtube) — needs api_key
# ---------------------------------------------------------------------------

def _test_youtube_instantiation():
    from autoinfo.collectors.youtube import YouTubeHandler
    h = YouTubeHandler()
    assert h is not None
    h2 = YouTubeHandler({"api_key": "test-key", "query": "AI"})
    assert h2.api_key == "test-key"


def _test_youtube_requires_key():
    from autoinfo.collectors.youtube import YouTubeHandler
    assert YouTubeHandler.requires_key() is True


def _test_youtube_mock():
    from autoinfo.collectors.youtube import YouTubeHandler

    def mock_handler(request):
        data = {
            "items": [
                {
                    "id": {"videoId": "dQw4w9WgXcQ"},
                    "snippet": {
                        "title": "Understanding Transformers in NLP",
                        "description": "A comprehensive guide to transformer architectures...",
                        "channelTitle": "AI Explained",
                        "channelId": "UC_example",
                        "publishedAt": "2024-05-20T15:00:00Z",
                        "thumbnails": {"default": {"url": "https://img.youtube.com/vi/dQw4/default.jpg"}},
                    },
                }
            ]
        }
        return httpx.Response(200, json=data, request=request)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        import autoinfo.collectors.youtube as mod
        orig = mod.httpx.get
        mod.httpx.get = client.get
        try:
            h = YouTubeHandler({"api_key": "fake-yt-key", "query": "transformers NLP"})
            videos = h.fetch(limit=10)
            items = [h.to_item(v) for v in videos]
            assert_eq(len(items), 1)
            assert_eq(items[0].source_platform, "youtube")
            assert "Transformers" in items[0].title
        finally:
            mod.httpx.get = orig


test("youtube: instantiation", _test_youtube_instantiation)
test("youtube: requires_key", _test_youtube_requires_key)
test("youtube: mock collection", _test_youtube_mock)


# ---------------------------------------------------------------------------
# Summary Report
# ---------------------------------------------------------------------------

print("\n" + "=" * 72)
print("Q2b Collector Validation — Summary Report")
print("=" * 72)

# Group by collector
collectors = {}
for r in results:
    name = r["name"].split(":")[0].strip()
    if name not in collectors:
        collectors[name] = []
    collectors[name].append(r)

total_pass = sum(1 for r in results if r["result"] == PASS)
total_fail = sum(1 for r in results if r["result"] == FAIL)
total_skip = sum(1 for r in results if r["result"] == SKIP)

print(f"\n{'Collector':<25} {'Instantiate':<12} {'requires_key':<14} {'Mock Collect':<14} {'Status':<10}")
print("-" * 75)

for collector_name in [
    "ap_api", "apple_podcasts", "bilibili", "dblp", "nyt",
    "openalex", "reddit", "reuters_mcp", "semantic_scholar",
    "spotify", "uspto", "youtube",
]:
    col_results = collectors.get(collector_name, [])
    inst = next((r for r in col_results if "instantiation" in r["name"]), None)
    rkey = next((r for r in col_results if "requires_key" in r["name"]), None)
    mock = next((r for r in col_results if "mock collection" in r["name"] or "mock" in r["name"]), None)

    inst_r = inst["result"] if inst else "—"
    rkey_r = rkey["result"] if rkey else "—"
    mock_r = mock["result"] if mock else "—"

    fails = [r for r in col_results if r["result"] == FAIL]
    status = "✅ PASS" if not fails else "❌ FAIL"
    if not col_results:
        status = "⏭️ SKIP"

    print(f"{collector_name:<25} {inst_r:<12} {rkey_r:<14} {mock_r:<14} {status:<10}")
    if fails:
        for f in fails:
            print(f"  └─ Error: {f.get('error', '?')}")

print("-" * 75)
print(f"\nTotal: {len(results)} tests | ✅ PASS: {total_pass} | ❌ FAIL: {total_fail} | ⏭️ SKIP: {total_skip}")

if total_fail > 0:
    print("\n❌ OVERALL: SOME COLLECTORS FAILED")
    sys.exit(1)
else:
    print("\n✅ OVERALL: ALL COLLECTORS PASSED")
    sys.exit(0)
