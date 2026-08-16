# AC4 Remaining Source-Gap Verdicts (issue #277)

<!-- doc-type: verdicts -->

> Evidence-backed from the 2026-08-16 AC4 wave (issue #277, `[AC4] Coverage
> gap implementation list`). Moved from
> `.omo/evidence/validation-runs/2026-08-16_ac4-w4-matrix/` into durable
> `docs/dev/` on 2026-08-16; the verdict classifications below are recorded
> verbatim from live probes — do not re-derive them.

Evidence-backed classification of the 49 source gaps that remain after
W1–W5 (config sync 89/89, scanner fix, #182 guard fix, KB tiers). Every
gap below was probed on this machine (2026-08-16) via live collection runs
or run-metadata inspection. None is closable without incoming user input
(API keys) or an egress proxy.

## 1. Key-blocked (11) — await user keys (W2B)

Guide: `docs/dev/ac4-gap-key-acquisition.md` (commit 78c7091).

| Domain | Source | Config consumer |
|--------|--------|-----------------|
| financial-intelligence | Alpha Vantage | `settings` `${...}` ref |
| financial-intelligence | FRED | `settings` `${...}` ref |
| financial-intelligence | Finnhub | env `FINNHUB_API_KEY` (runtime `token` param) |
| financial-intelligence | Twelve Data | `settings` `${...}` ref |
| financial-intelligence | Quandl/Nasdaq Data Link | env `AUTOINFO_QUANDL_API_KEY` |
| tech-ai-developer | Reddit | env / settings |
| tech-ai-developer | Spotify AI Podcasts | env `AUTOINFO_SPOTIFY_CLIENT_ID/SECRET` |
| online-education | wanfang | headers `X-Ca-AppKey` / `Authorization` `${WANFANG_APP_KEY}` / `${WANFANG_APP_CODE}` |
| general-news | NYT | env `AUTOINFO_NYT_API_KEY` |
| general-news | AP API | env `AUTOINFO_AP_API_KEY` |
| general-news | Guardian Open Platform | env / settings |

## 2. Dead / retired upstream (5) — verdicts recorded in W2

| Source | Domain | Evidence |
|--------|--------|----------|
| apple-music | online-video | Apple retired the RSS API — 404 on all variants (rss.marketingtools.apple.com / rss.applemarketingtools.com) |
| mastodon | general-news | Errno 101 Network unreachable (egress blocked) |
| bluesky | general-news | Errno 101 Network unreachable (egress blocked) |
| gdelt | general-news | 429 upstream throttle even after long cooldown; handler swallows as `[]` |
| uspto | medical-research | 301 retired (patentsview) |

## 3. Egress-blocked by this machine's network (GFW) (~14)

All failed with `[Errno 101] Network is unreachable` on live probes:

youtube-mkbhd (online-video), ft-alphaville (financial-news),
dedao (online-education, rsshub.app), ncpssd (online-education, rsshub.app),
google-news-rss (general-news), medium-user / medium-publication /
medium-tag (general-news), the-atlantic (general-news),
time-magazine (general-news), yystv-via-google-news (gaming),
ebrun-via-google-news (retail).

Also egress-sensitive (429 / conn-reset on live probe):
yahoo-finance (financial-news, HTTP 429), polygon-rss (gaming,
server disconnected).

## 4. Dead or malformed feed URLs (14) — upstream URL drift

| Source | Domain | Evidence |
|--------|--------|----------|
| reuters-business | financial-news | RSS parse error (bozo, invalid token at :75:40) |
| businesswire-technology | financial-news | feed returns zero entries (`feed.businesswire.com/mrss/home/?rss=industry/technology`) |
| prnewswire-financial-services | financial-news | HTTP 404 |
| nvidia-newsroom | financial-news | RSS parse error (bozo at :6:0) |
| microsoft-newsroom | financial-news | HTTP 403 Forbidden |
| edsurge | online-education | Errno 111 Connection refused |
| class-central | online-education | HTTP 403 Forbidden |
| khan-academy | online-education | RSS parse error (bozo at :15:4) |
| iapp-privacy | legal-compliance | HTTP 404 |
| law-com | legal-compliance | HTTP 404 + parse error |
| oyez | legal-compliance | RSS parse error (bozo at :2:0) |
| a16z | b2b | HTTP 404 (`a16z.com/feed/` moved) |
| arXiv | medical-research | rss/bio 400; rss/q-bio zero entries (config already fixed at q-bio) |
| semantic-scholar | medical-research | 429 without API key — needs `AUTOINFO_S2_API_KEY` (optional 12th key) |

## 5. Update: project-gutenberg gap CLOSED (2026-08-16)

Runtime config carried the stale dead URL (`today.epub.xml`, HTTP 404)
while the demo config and live feed use `today.rss` (HTTP 200). Fixed via
CLI (never hand-edited config): `sources add` the corrected URL, then
`channels`/`sources remove` the dead duplicate by name (same pattern as the
earlier HackerNews firebaseio reconciliation). Re-collect succeeded:
**total_found 5, total_new 5, status success**; 5 item JSONs now under
`collections/language-learning/project-gutenberg/2026-08-16/`.
Coverage matrix re-scan (2026-08-16, `2026-08-16_ac4-w4b-matrix`):
**source_gaps 49 → 48**; kb_tier_gaps stays 0.

## 6. Query-driven keyless sources — dispatch confirmed, topic-gated (2)

| Source | Domain | Probe result (2026-08-16) |
|--------|--------|---------------------------|
| dblp | medical-research | dispatches successfully; with `--topic "machine learning"` finds 5 but all 5 filtered (topic-relevance filter) → 0 stored; without `--topic` returns 0 (query-driven, requires topic) |
| Bilibili (B站) | tech-ai-developer | dispatches successfully (`status: success`) but returns 0 items — search API yields nothing without a working query / egress-limited |

These are not blocked by keys; they are topic-gated or API-return-empty on
this machine. Scope-restricted: closing them would require selecting
matching topics per run or upstream API changes.

## Summary

| Category | Count |
|----------|-------|
| Key-blocked (await user) | 11 |
| Dead / retired upstream | 5 |
| Egress-blocked (GFW/429/conn) | ~15 |
| Dead/malformed feed URLs | 14 |
| Query-driven / API-empty (topic-gated) | 2 |
| Closed to date (project-gutenberg) | 1 |
| **Total remaining** | **48** (matches `source_gaps` in W4b re-scan) |

kb_tier_gaps = 0 (all 13 domains × 3 tiers filled, verified
2026-08-16). No further gap closure is possible on this machine without
user-supplied keys, a proxy egress, or upstream feed fixes.