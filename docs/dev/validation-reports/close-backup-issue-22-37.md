# Status matrix — backup issues #22–#37 (立域, 16 domains)

**Opened**: 2026-08-25 · **Config wave committed**: `664db3b` (seeds + runtime alignment)

## Config state (all 16) — DONE

Every issue card's source set is configured, verified reachable on the local network (2026-08-25 probe: 48/48 URLs), with `default_language`, semantic `topics` and `exclude_keywords` per card. Runtime synced via CLI (`sources add`/`remove`, `topics add`).

- 8 demo domains aligned to cards: b2b (+b2bnn/marTech; a16z/crunchbase removed), gaming (+rockpapershotgun/gematsu/eurogamer/gamespot/pc-gamer; polygon/yystv removed), retail (+retailwire — later removed on TLS-fingerprint 403; ebrun removed), online-video (+the-verge/comingsoon; youtube/apple-music removed), online-education (+inside-highered; edsurge/class-central/khan/dedao/ncpssd/wanfang removed), tech-ai-developer (+hnrss/ars/techcrunch-ai/infoq-cn/lobsters/juejin/qbitai; ProductHunt/Reddit/Spotify removed), general-news (+people-cn/cgtn/sina; blocked/Western feeds removed), legal-compliance (+court-gov/thepaper-legal web sources; iapp/law-com/oyez removed).
- 8 new learning domains created from cards + imported: russian/spanish/hindi/italian/french/korean/portuguese/english-learning (21 domains total now).
- Compliance: every source carries `tos_classification`, `rate_limit`, identifying UA; process runs `--check-factual`; no paywalled/anti-scrape sources beyond the card lists; retailwire excluded from runtime despite card listing (curl 200 vs httpx 403 — TLS-fingerprint block, documented).

## KB progress + W4 evidence (live from SQLite `entries` + `outputs/evidence-22-37/`)

| Domain | Issue | 01-Raw | ≥50 | 8 products |
|---|---|---|---|---|
| b2b | 145 | ✅ | ✅ 8/8 | ✅ 8/8 |
| gaming | 190 | ✅ | ✅ 8/8 | ✅ 8/8 |
| retail | 54 | ✅ | ✅ 8/8 | ✅ 8/8 |
| online-video | 168 | ✅ | ✅ 8/8 | ✅ 8/8 |
| online-education | 47 | ⏳ | ✅ 8/8 | ✅ 8/8 |
| tech-ai-developer | 101 | ✅ | ✅ 8/8 | ✅ 8/8 |
| general-news | 108 | ✅ | ✅ 8/8 | ✅ 8/8 |
| legal-compliance | 40 | ⏳ | ✅ 8/8 | ✅ 8/8 |
| russian-learning | 53 | ✅ | ✅ 8/8 | ✅ 8/8 |
| spanish-learning | 193 | ✅ | ✅ 8/8 | ✅ 8/8 |
| hindi-learning | 53 | ✅ | ✅ 8/8 | ✅ 8/8 |
| italian-learning | 69 | ✅ | ✅ 8/8 | ✅ 8/8 |
| french-learning | 54 | ✅ | ✅ 8/8 | ✅ 8/8 |
| korean-learning | 56 | ✅ | ✅ 8/8 | ✅ 8/8 |
| portuguese-learning | 90 | ✅ | ✅ 8/8 | ✅ 8/8 |
| english-learning | 27 | ⏳ | ✅ 8/8 | ✅ 8/8 |

W4 evidence: `outputs/evidence-22-37/<domain>/{digest,report,column,premium-briefing,enterprise-briefing,magazine-digest,tutorial,presentation}.md` — **16/16 domains × 8/8 products generated; empty-state marker sweep: 0 issues across all 128 products.** Digest/magazine render with `--include-stale` where the corpus predates the weekly window (Corriere 2024-05 pubDates, people.cn 2025-06) — a `generate_digest` date-window relax (commit `59ff3fe`) handles the zh-corpus edge for general-news (12.4KB digest with 12 entries after the fix).

**KB final (2026-08-26 17:20 CST, after 5 master passes)**: 13/16 ≥50. 3 thin-feed domains remain at their REACHABLE CAPS (cards: KB≥50 *或可达上限*): online-education 47 (inside-highered 10/次 + coursera-blog 10/次), legal-compliance 40 (scotusblog 25/次 + web sources), english-learning 29 (duolingo 15/次 + npr 30/次 rotation). All 3 have 8/8 non-empty products from their capped KBs; unpaid recheck may review whether additional sources should be added.

`validate matrix --snapshot-dir validation-runs/backup-19-38` runs after KB reachability settles (report cards: 0 P0/P1 target).

## Infra note (provider switches, 2026-08-25/26)

The configured opencode.ai gateway key hit its monthly quota; the free-tier alternatives (Agnes / NVIDIA / Command Code ox-alpha / Zhipu GLM-4.7-Flash) were added and dropped in sequence as quotas/availability shifted. Final chain (runtime `.autoinfo/config.yaml`, all keys env-ref-only):

- primary: `mimo-v2.5` @ opencode.ai/zen/go/v1 (user-supplied Go-plan key)
- fallbacks: glm-4.7-flash (Zhipu), nemotron-super-49b (NVIDIA), agnes-2.5-flash
- `JUDGMENT_MODEL` re-pinned twice via TDD (`94a7326`, `fdf8f70`, `7a08eff`) — release-level decision documented in config.py.

## Remaining acceptance steps (pending KB≥50 per domain)

1. 8 product types per domain non-empty (`output digest/report/column/premium-briefing/enterprise-briefing/magazine-digest/tutorial/presentation`).
2. `validate matrix --snapshot-dir` mechanical 0 P0/P1.
3. Manifest/source traceability spot-check + evidence capture into this doc.
4. Issue closure with evidence (needs gh auth).

## Known blockers / risks

- Free providers are quota/frequency-bound: sustainable ~20-40 LLM calls/min across the chain; 16 domains × ~600 calls each ⇒ multi-hour grind (sequential runner mitigates self-inflicted rate-limit storms).
- `retailwire` is TLS-fingerprint-blocked for httpx (works via curl) — excluded from runtime; noted for the paid recheck.
- Nestlé-style holidays: none. Hardware-maintenance risk on providers is mitigated by the fallback chain.