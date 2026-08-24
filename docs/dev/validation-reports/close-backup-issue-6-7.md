# Backup Issue #6 / #7 Closure Evidence — Mainland-CN Source Reachability

<!-- doc-type: closure-evidence -->

Closes backup-repo issues [#6](https://github.com/renanzai40/AutoInfo_BackUp/issues/6)
(financial domain sources blocked/anti-scraped on mainland CN) and
[#7](https://github.com/renanzai40/AutoInfo_BackUp/issues/7) (13-domain
reachability audit + reachable replacements).

## What was verified (2026-08-24, live mainland-CN probes)

3-level probe (DNS → TCP:443 → HTTP) over all 13 demo domains using the
collector's real bot UA (`AutoInfo/1.8`). Two key insights that shrank the
problem:

- **Browser-UA 403s are false positives** — the collector's bot UA gets HTTP
  200 on microsoft-newsroom, wired, crunchbase-news, HN-firebaseio and
  SEC-EDGAR. The genuinely unreachable set is far smaller than a browser-UA
  audit suggests.
- **主站被墙 ≠ RSS 不可达** — WSJ/MW main sites are GFW-blocked but their RSS
  feed domains (`feeds.content.dowjones.io`, `feeds.marketwatch.com`) are
  reachable (40 / 10 entries parsed). Swap the collection URL, not the source.

## What was changed

17 verified-reachable replacements added; 29 dead/GFW-blocked feeds set
`enabled: false` (with inline reason comments) across 10 domains. Disabled
feeds stay in the config so keyed/geo-specific setups can re-enable them.

| Domain | Added (verified entries) | Disabled (reason) |
|--------|--------------------------|-------------------|
| financial-news | WSJ RSS (40), MW RSS (10) | reuters-business (404), ft-alphaville (GFW), businesswire (0 entries), prnewswire (404), nvidia-newsroom (bozo) |
| general-news | france24 (23), NPR (10), Ars (20), Verge (10), Engadget (20), SpaceNews (19) | google-news-rss / nyt / medium×3 / the-atlantic / time (GFW), mastodon / bluesky (GFW), gdelt (429) |
| tech-ai-developer | HN Algolia API (JSON), GitHub Blog (10) | — (HackerNews firebaseio DNS-fails) |
| online-video | Bilibili popular (JSON), TheWrap (10) | youtube-mkbhd (GFW), apple-music (dead 404) |
| gaming | GameSpot (30), PC Gamer (50), Eurogamer (100) | polygon (conn-reset), yystv-via-google-news (GFW) |
| b2b | SaaStr (10) | a16z (404) |
| financial-intelligence | MarketWatch Markets (DJ) (10) | — |
| online-education | — | edsurge (conn refused), class-central (403), khan-academy (bozo), dedao / ncpssd (rsshub.app GFW) |
| retail | — | ebrun-via-google-news (GFW) |
| legal-compliance | — | iapp-privacy (404), law-com (404) |

## Bonus bug fixed (RED→GREEN)

`_resolve_sources` (src/autoinfo/collect.py) returned every configured source
regardless of `enabled`, so a disabled feed (GFW-blocked / 404) was still
fetched during `collect`. Enabled sources are now filtered at resolution,
whether requested by name or collected by default.

- RED: 3 new tests in `tests/cli/test_cli_collect_sources.py` failed —
  `_resolve_sources` returned disabled sources.
- GREEN: all 3 pass after the fix; full config+collectors+mcp suite green.

## Acceptance evidence (real collection runs)

| Domain | Result |
|--------|--------|
| financial-intelligence (`--limit 25`) | **60 new items** — CNBC 25 / TheStreet 25 / **MarketWatch Markets (DJ) 10**; **zero** Network-unreachable/403 on news feeds |
| general-news (`--limit 15`) | 74 new items — all six replacements producing (france24 15, NPR 10, Ars 15, Verge 10, Engadget 15, SpaceNews 15); GFW-blocked feeds **skipped** after the fix |
| gaming (`--limit 15`) | 75 new items — GameSpot/PC Gamer/Eurogamer producing |
| tech-ai-developer (`--limit 15`) | 50 new items — HN Algolia 15, GitHub Blog 10 |

`regression-financial-sources` scenario: **GREEN** (was RED — the
`MarketWatch Markets (DJ)` keyless feed the scenario requires was missing;
now present). Full test suite: **2984 passed, 8 skipped, 1 pre-existing
failure** (`test_release_workflow` — the backup mirror removed
release-please.yml in an earlier commit; unrelated to this work, fails on the
unchanged HEAD too).

## Commits

- `03dc3a2` fix(collectors): replace GFW-blocked/anti-scraped demo sources with verified-reachable feeds (#6, #7)
- `727761a` fix(collect): honor enabled: false in _resolve_sources; sync source snapshots (#6, #7)
- `bae8605` docs(backup): mainland-CN reachability findings + source matrix + README/CHANGELOG (#6, #7)
- this commit: closure evidence for #6/#7
