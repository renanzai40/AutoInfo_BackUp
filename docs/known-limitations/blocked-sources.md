# Blocked High-Value Information Sources

## Overview

AutoInfo aims for universal information access. Some high-value sources cannot be
integrated due to cost, platform policy, or technical limitations. This document
catalogs those sources and identifies potential alternatives — whether within
AutoInfo, via other free/open platforms, or through complementary tools.

**Already integrated and provided as comparison**: AutoInfo includes free/open
sources like PubMed, arXiv, Alpha Vantage, FRED, SEC EDGAR, GitHub Trending,
HackerNews, Project Gutenberg, and RSS feeds. These demonstrate what's possible
when a source has a public API, RSS feed, or permissive scraping policy.

---

## Sources

### Financial Data & Terminal Services

#### Bloomberg Terminal
- **Type**: Proprietary terminal / API
- **Blocking Reason**: Cost: ~$2,000/user/month. Closed ecosystem with no public API.
- **Alternative**: Alpha Vantage (free tier), FRED (free), SEC EDGAR (free), Twelve Data (free tier), World Bank Data (free) — all integrated in AutoInfo's financial-intelligence domain.
- **Feasibility**: Unlikely. Cost structure is incompatible with AutoInfo's BYOK model. Only viable if Bloomberg launches an affordable developer API tier.

#### Reuters Eikon / LSEG Workspace (Refinitiv)
- **Type**: Proprietary terminal / API
- **Blocking Reason**: Cost: ~$1,500/user/month. Enterprise-only licensing. Refinitiv (acquired by LSEG in 2021, now branded LSEG Workspace) provides the same data feed formerly known as Reuters Eikon. No public developer API tier.
- **Alternative**: Alpha Vantage + World Bank Data (integrated). For news, RSS feeds from financial publishers may partially substitute.
- **Feasibility**: Unlikely. Same cost barrier as Bloomberg. LSEG Data & Analytics has no publicly documented affordable API tier.

#### Wind (万得)
- **Type**: Proprietary terminal / API
- **Blocking Reason**: Cost: ~¥20,000/user/year (enterprise pricing, China-only). Wind is China's dominant financial data terminal (analogous to Bloomberg for Chinese markets). No public API. Closed ecosystem with institutional licensing only. China-based sales and support.
- **Alternative**: For Chinese market data, free alternatives are limited. Sina Finance RSS and Eastmoney (东方财富) RSS provide basic stock/news data. Alpha Vantage (integrated) covers some Chinese equities. For macro data, FRED (integrated) covers US series; World Bank Data (integrated) covers international indicators.
- **Feasibility**: Unlikely. Wind's business model mirrors Bloomberg's exclusivity. No developer program. Only viable if Wind launches an affordable API tier for the Chinese developer market.

#### Capital IQ / S&P Global Market Intelligence
- **Type**: Proprietary platform / API
- **Blocking Reason**: Cost: enterprise (undisclosed, typically 5–6 figures/year). No individual/developer tier.
- **Alternative**: SEC EDGAR (integrated) for filings, FRED (integrated) for economic data.
- **Feasibility**: Unlikely without S&P launching a self-serve developer program.

#### Dow Jones / Factiva
- **Type**: Proprietary news database / API
- **Blocking Reason**: Cost: enterprise (undisclosed). Requires institutional subscription.
- **Alternative**: RSS feeds from individual publishers (e.g., Reuters RSS, MarketWatch RSS), Google News RSS. AutoInfo's RSS collector can aggregate from multiple news sources.
- **Feasibility**: Unlikely. Enterprise-only licensing with no public API documentation.

---

### News & Media (Paywalled)

#### Wall Street Journal (WSJ)
- **Type**: Web (subscription paywall)
- **Blocking Reason**: Hard paywall. No public API. Anti-scraping measures in ToS.
- **Alternative**: Free financial news via Yahoo Finance RSS, MarketWatch RSS, CNBC.com (free articles). WSJ headlines are available via RSS but full-text requires subscription.
- **Feasibility**: Likely — if WSJ launches a content licensing API for developers. Otherwise, AutoInfo can ingest WSJ RSS headlines (public) but not full-text articles.

#### Financial Times (FT)
- **Type**: Web (subscription paywall)
- **Blocking Reason**: Metered/hard paywall. No public content API.
- **Alternative**: Free financial news via Reuters RSS, Bloomberg.com (free articles), MarketWatch RSS.
- **Feasibility**: Unlikely. FT's business model is subscription-first. Headlines-only RSS is public; full-text requires institutional license.

#### The Economist
- **Type**: Web (subscription paywall)
- **Blocking Reason**: Hard paywall. No public API. Limited free articles per month.
- **Alternative**: World Bank Data (integrated) for economic data. VOA News RSS for international affairs (free).
- **Feasibility**: Unlikely. No developer API available.

#### CNBC Pro
- **Type**: Web (subscription paywall)
- **Blocking Reason**: Premium tier paywall (~$30/month). No API for Pro content.
- **Alternative**: CNBC.com free articles via RSS, Yahoo Finance RSS, MarketWatch RSS.
- **Feasibility**: Likely — if CNBC opens a Pro API. Currently, free CNBC content is accessible via RSS.

#### 财新 (Caixin Media)
- **Type**: Web (subscription paywall, Chinese)
- **Blocking Reason**: Hard paywall. Caixin is one of China's most respected financial news outlets. No public API. Full-text requires paid subscription (~¥498/year). RSS feed exists but delivers headlines/teasers only.
- **Alternative**: Free Chinese financial news via 36kr (integrated in ai-commercial domain), Sina Finance RSS, Reuters China RSS. For English-language China coverage, Reuters RSS and Bloomberg.com free articles.
- **Feasibility**: Unlikely. Caixin's business model depends on subscription revenue. No developer API announced. Headlines-only RSS is public but full-text is gated.

#### 新华社 (Xinhua News Agency)
- **Type**: News agency / Web
- **Blocking Reason**: Xinhua is China's official state news agency. While xinhuanet.com publishes free articles, there is no public content API for bulk retrieval. The commercial Xinhua News Service (paid wire feed) targets institutional clients and is not sold to individual developers. ToS restricts automated scraping.
- **Alternative**: Xinhua's free website RSS feeds (limited), Reuters RSS for international wire coverage, Google News RSS for aggregated headlines. For Chinese-language news, People's Daily RSS and China Daily RSS are free.
- **Feasibility**: Partially likely. Free RSS feeds exist for headlines, but bulk full-text access requires an institutional wire subscription. AutoInfo's RSS collector can ingest the public headline feeds.

---

### Academic & Research

#### Nature / Science / Cell
- **Type**: Web (subscription paywall)
- **Blocking Reason**: Institutional subscription required. No public API. Individual article costs $30–$50.
- **Alternative**: PubMed (integrated, free) indexes 36M+ biomedical abstracts including Nature/Science/Cell papers. Many authors post preprints on bioRxiv/medRxiv (free, RSS-accessible). arXiv (integrated, free) covers physics, math, CS, and related fields.
- **Feasibility**: Partially likely. Abstracts are free on journal websites — AutoInfo could scrape abstracts with proper attribution, but full-text requires institutional access. Note: abstracts are already discoverable via PubMed.

#### IEEE Xplore / ACM Digital Library
- **Type**: Digital library (subscription paywall)
- **Blocking Reason**: Institutional subscription required. Pay-per-article otherwise (~$33/article IEEE, ~$15/article ACM).
- **Alternative**: arXiv (integrated, free) — most CS/EE papers appear as preprints. Semantic Scholar (free API) indexes and links to open-access versions. Google Scholar for discovery.
- **Feasibility**: Partially likely for abstracts only. Full-text requires institutional license. arXiv preprints cover a large overlap for CS/EE.

---

### Social Media & Platforms

#### Twitter / X API v2
- **Type**: REST API
- **Blocking Reason**: Cost: Basic tier $100/month (10K posts), Pro tier $5,000/month (1M posts). Free tier limited to 1,500 posts/month (write-only; read access restricted). API terms restrict bulk data collection and redistribution.
- **Alternative**: RSS feeds from accounts that cross-post (many journalists and researchers mirror to RSS-enabled blogs or newsletters). Reddit API (free tier still usable) for community discussion. HackerNews API (integrated, free) for tech discussion.
- **Feasibility**: Under review. Pro tier ($5,000/month) is cost-prohibitive for most users. Basic tier ($100/month) may become viable for enterprise AutoInfo deployments if ROI can be demonstrated. Blocked indefinitely for free-tier users.

#### LinkedIn API
- **Type**: REST API (OAuth 2.0)
- **Blocking Reason**: Restricted. LinkedIn's API access requires approved use cases (recruiting, marketing, sales). General content search and knowledge extraction are NOT approved use cases. No public feed/content search endpoint.
- **Alternative**: Company blogs and RSS feeds for corporate news. Crunchbase API (integrated in ai-commercial domain) for company data. AngelList/WellFound for startup data.
- **Feasibility**: Unlikely. LinkedIn's API strategy is product-integration focused, not open-access. Content search is explicitly excluded from approved use cases.

#### Facebook / Instagram Graph API
- **Type**: REST API (OAuth 2.0)
- **Blocking Reason**: Read-only for approved use cases (Page management, Instagram business). No general content search. No public feed access. Instagram Basic Display API deprecated in 2024.
- **Alternative**: Public RSS feeds from organizations that also post on Facebook/Instagram. Many businesses maintain blogs or press pages with RSS.
- **Feasibility**: Very unlikely. Meta's API strategy is tightly restricted to business integrations. No path to general content access.

#### TikTok API
- **Type**: REST API (OAuth 2.0)
- **Blocking Reason**: Restricted. TikTok's Research API requires academic/research institution affiliation and approved application. TikTok for Developers API is for content creation/management, not consumption. Region-locked in some countries.
- **Alternative**: For trend monitoring: Google Trends API (free tier). For creator content: YouTube RSS feeds (public, free) for creators who cross-post.
- **Feasibility**: Very unlikely. Research API is narrowly scoped and not designed for general knowledge tracking.

#### 微博 (Weibo)
- **Type**: REST API (OAuth 2.0)
- **Blocking Reason**: Weibo Open Platform API is restricted. The open search/timeline endpoints were deprecated or heavily rate-limited after 2018 regulatory tightening. Current API access requires enterprise verification (Chinese business license) and approved use cases. Bulk content collection and redistribution are prohibited by ToS.
- **Alternative**: For Chinese social discussion, Reddit (integrated) has Chinese-language communities. For trending topics, Google Trends API (free tier) covers regional interest. Bilibili (integrated) for video-based discussion.
- **Feasibility**: Unlikely. Weibo's API strategy is closed to general developers. No path to affordable content search access.

#### 抖音 (Douyin)
- **Type**: REST API (OAuth 2.0)
- **Blocking Reason**: Douyin (the Chinese domestic version of TikTok) Open Platform API is restricted to enterprise partners for content creation and e-commerce management. There is no public content search or feed retrieval API. ToS prohibits automated scraping. Distinct from international TikTok API (covered above), which has its own restrictions.
- **Alternative**: Bilibili (integrated) for Chinese video content and creator discussion. YouTube RSS (free) for creators who cross-post to international platforms.
- **Feasibility**: Very unlikely. Douyin's API is commerce-focused, not content-consumption-focused. No developer path to general knowledge tracking.

#### 小红书 (Xiaohongshu / RED)
- **Type**: Web / mobile app
- **Blocking Reason**: No public API of any kind. Xiaohongshu (RED) is a Chinese lifestyle and product review platform with no developer program. Aggressive anti-scraping measures (device fingerprinting, behavioral detection). ToS prohibits automated collection.
- **Alternative**: For product/lifestyle trends, Reddit (integrated) has relevant communities. For Chinese consumer sentiment, manual monitoring or third-party analytics services (paid) are the only options.
- **Feasibility**: Very unlikely. No API, no developer program, active anti-scraping. No viable integration path.

---

### Chinese Knowledge Platforms

#### 知乎 (Zhihu)
- **Type**: Web / REST API (limited)
- **Blocking Reason**: Zhihu's public API was deprecated in 2018. Current API access requires enterprise partnership and approved use cases. The platform uses aggressive anti-scraping (device fingerprinting, rate limiting, CAPTCHA). ToS prohibits automated content collection. Anonymous browsing is limited; most content requires login after a small quota.
- **Alternative**: For Q&A-style knowledge, Stack Exchange (integrated in tech-ai-developer domain) covers technical topics. Reddit (integrated) has r/China and topic-specific communities. For Chinese-language expertise, manual browsing remains the only option.
- **Feasibility**: Unlikely. Zhihu has no public developer API and actively blocks scraping. No viable automated integration path.

#### 得到 (Dedao)
- **Type**: Mobile app / Web (subscription paywall)
- **Blocking Reason**: Dedao is a Chinese knowledge-paying platform (audio courses, e-books, columns). No public API. All content is behind a paid subscription. ToS prohibits scraping and redistribution. Content is DRM-protected audio and text.
- **Alternative**: For audio knowledge content, Spotify podcasts (integrated) and Apple Podcasts (integrated) offer free alternatives on similar topics. Project Gutenberg (integrated) for free e-books. For Chinese-language learning content, news-in-levels (integrated) covers reading practice.
- **Feasibility**: Very unlikely. Dedao's entire business model is paid content. No API, no free tier, DRM protection. No integration path.

#### 微信公众号 (WeChat Official Account)
- **Type**: Platform API (OAuth 2.0)
- **Blocking Reason**: WeChat OA Platform API is restricted to account management (for OA owners) and customer service. There is no public API to search or retrieve articles across official accounts. Articles are only accessible within the WeChat app or via individual article URLs (no index, no RSS). Sogou WeChat Search provides partial indexing but is rate-limited and ToS-restricted. China-only platform with regional restrictions.
- **Alternative**: For organizations that also publish to the open web, general RSS feeds and AutoInfo's web collector (trafilatura + Playwright) can capture cross-posted content. For Chinese news, 36kr (integrated) and Sina Finance RSS provide free alternatives.
- **Feasibility**: Unlikely. WeChat's walled-garden design prevents external indexing. No API for content search. Only individual article URLs (when known) can be fetched via the web collector.

---

### Legal & Regulatory

#### Westlaw / Thomson Reuters
- **Type**: Proprietary platform / API
- **Blocking Reason**: Cost: enterprise (typically 5-figures/year per seat). No public API. Tightly controlled legal database.
- **Alternative**: CourtListener (free, RECAP archive) for US federal court documents. GovInfo.gov (free) for US legislation and regulations. EUR-Lex (free) for EU law.
- **Feasibility**: Unlikely. Westlaw's business model is built on exclusivity. No path to affordable access.

#### LexisNexis
- **Type**: Proprietary platform / API
- **Blocking Reason**: Cost: enterprise (typically 5-figures/year per seat). No public API for general search.
- **Alternative**: Same as Westlaw: CourtListener, GovInfo.gov, EUR-Lex. Some state-level court systems provide free docket access.
- **Feasibility**: Unlikely. LexisNexis developer portal exists but is focused on risk/fraud APIs, not legal content search.

---

### Comparison: Free Sources Already Integrated

These sources demonstrate what AutoInfo can achieve when APIs are open and accessible:

| Source | Type | Domain | Note |
|--------|------|--------|------|
| **PubMed** | REST API (E-utilities) | medical-research | 36M+ biomedical abstracts. Free, no key required. |
| **arXiv** | REST API + RSS | medical-research, tech-ai-developer | 2.4M+ preprints. Free, bulk access supported. |
| **CrossRef** | REST API | medical-research | DOI metadata. Free, no key required. |
| **Alpha Vantage** | REST API | financial-intelligence | Stock/forex/crypto data. Free tier: 25 req/day. |
| **FRED** | REST API | financial-intelligence | 823K+ US economic series. Free, key required. |
| **SEC EDGAR** | REST API (xbrl) | financial-intelligence | All public company filings. Free, no key. |
| **HackerNews** | Firebase API | tech-ai-developer | Tech community discussion. Free, no key. |
| **GitHub Trending** | Web scraping | tech-ai-developer | Developer project discovery. Public pages. |

---

## Summary

| Source | Reason | Alternative | Feasibility |
|--------|--------|-------------|-------------|
| Bloomberg Terminal | Cost: $2,000/user/mo | Alpha Vantage, FRED, SEC EDGAR (integrated) | Unlikely |
| Reuters Eikon / Refinitiv | Cost: $1,500/user/mo | Alpha Vantage, World Bank Data (integrated) | Unlikely |
| Wind (万得) | Cost: ~¥20,000/user/yr, China-only | Alpha Vantage, Sina Finance RSS (partial) | Unlikely |
| Capital IQ / S&P Global | Cost: enterprise | SEC EDGAR, FRED (integrated) | Unlikely |
| Twitter / X API v2 | Cost: $100–$5,000/mo, policy | RSS from cross-posting accounts, HackerNews | Under review |
| 微博 (Weibo) | Policy: restricted, enterprise-only | Reddit, Bilibili (integrated) | Unlikely |
| 抖音 (Douyin) | Policy: commerce-only API, no search | Bilibili, YouTube RSS (integrated) | Very unlikely |
| 小红书 (Xiaohongshu) | No API, anti-scraping | Reddit (integrated) for trends | Very unlikely |
| 知乎 (Zhihu) | No public API, anti-scraping | Stack Exchange, Reddit (integrated) | Unlikely |
| 得到 (Dedao) | Paid content, DRM, no API | Spotify/Apple Podcasts, Gutenberg (integrated) | Very unlikely |
| 微信公众号 (WeChat OA) | Platform: China-only, walled garden | 36kr, Sina Finance RSS (integrated) | Unlikely |
| LinkedIn API | Policy: restricted use cases | Crunchbase (integrated), company RSS | Unlikely |
| Facebook/Instagram Graph API | Policy: no content search | Organization RSS, press pages | Very unlikely |
| TikTok API | Policy: restricted, region-locked | YouTube RSS for cross-posters | Very unlikely |
| Westlaw | Cost: enterprise | CourtListener, GovInfo.gov (free) | Unlikely |
| LexisNexis | Cost: enterprise | CourtListener, EUR-Lex (free) | Unlikely |
| Dow Jones / Factiva | Cost: enterprise | Publisher RSS feeds (free) | Unlikely |
| CNBC Pro | Cost: ~$30/mo paywall | CNBC free RSS, Yahoo Finance RSS | Likely |
| Wall Street Journal | Cost: subscription paywall | Yahoo Finance RSS, MarketWatch RSS | Likely |
| Financial Times | Cost: subscription paywall | Reuters RSS, MarketWatch RSS | Unlikely |
| 财新 (Caixin) | Cost: subscription paywall (¥498/yr) | 36kr, Reuters China RSS (integrated) | Unlikely |
| 新华社 (Xinhua) | No public API, wire subscription | Reuters RSS, China Daily RSS (free) | Partially likely (headlines) |
| The Economist | Cost: subscription paywall | VOA News RSS, World Bank Data | Unlikely |
| Nature / Science / Cell | Cost: subscription/institutional | PubMed, arXiv (integrated, free) | Partially likely (abstracts) |
| IEEE / ACM Digital Libraries | Cost: subscription/institutional | arXiv, Semantic Scholar (free) | Partially likely (abstracts) |

---

## How to Contribute

When evaluating a new source for integration, check:

1. **API availability** — Does the source have a documented public API?
2. **Cost structure** — Is there a free tier or affordable developer plan?
3. **Terms of Service** — Does the ToS permit automated collection and knowledge-base storage?
4. **RSS/Atom feed** — Even without an API, many sources offer RSS feeds.

If a source is blocked, document it here with the blocking reason, any alternative sources already integrated in AutoInfo, and a feasibility assessment.

---

## Mainland-CN reachability pass (2026-08-24, issues #6/#7)

Live 3-level probe (DNS → TCP:443 → HTTP) from a mainland-CN network
(2026-08-24) over all 13 demo domains, using the collector's real bot UA
(`AutoInfo/1.8`). Key insight: **browser-UA 403s are false positives** — the
collector's bot UA gets 200 on microsoft-newsroom, wired, crunchbase-news,
HN-firebaseio, SEC-EDGAR. The genuinely unreachable set is small and is now
`enabled: false` in the domain configs, with verified-reachable replacements:

| Domain | Disabled (reason) | Added replacement (verified entries) |
|--------|-------------------|--------------------------------------|
| financial-news | reuters-business (404), ft-alphaville (GFW), businesswire (0 entries), prnewswire (404), nvidia-newsroom (bozo) | WSJ RSS (40), MW RSS (10) |
| general-news | google-news-rss / nyt / medium×3 / the-atlantic / time (GFW), mastodon / bluesky (GFW), gdelt (429) | france24 (23), NPR (10), Ars (20), Verge (10), Engadget (20), SpaceNews (19) |
| tech-ai-developer | — | HN Algolia API (JSON), GitHub Blog (10) |
| online-video | youtube-mkbhd (GFW), apple-music (dead 404) | Bilibili popular (JSON), TheWrap (10) |
| gaming | polygon (conn-reset), yystv-via-google-news (GFW) | GameSpot (30), PC Gamer (50), Eurogamer (100) |
| b2b | a16z (404) | SaaStr (10) |
| online-education | edsurge (conn refused), class-central (403), khan-academy (bozo), dedao / ncpssd (rsshub.app GFW) | — (documented, no verified replacement) |
| retail | ebrun-via-google-news (GFW) | — |
| legal-compliance | iapp-privacy (404), law-com (404) | — |

Key findings:
- **主站被墙 ≠ RSS 不可达**: WSJ/MW main sites are GFW-blocked but their feed
  domains (`feeds.content.dowjones.io`, `feeds.marketwatch.com`) are reachable —
  swap the collection URL, not the source.
- **反爬 ≠ 换源**: several 403s vanish when probing with the collector's actual
  bot UA instead of a browser UA.
- Disabled sources remain in the config (`enabled: false` + reason comment) so
  keyed/geo-specific setups can re-enable them; `required_sources` in
  `docs/dev/specs/end-user-matrix.yaml` tracks the 78 enabled sources.

---

*Last updated: 2026-08-24. This is a living document — sources change their API policies and pricing over time.*
