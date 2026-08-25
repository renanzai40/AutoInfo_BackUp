# Status matrix — backup issues #22–#37 (立域, 16 domains)

**Opened**: 2026-08-25 · **Config wave committed**: `664db3b` (seeds + runtime alignment)

## Config state (all 16) — DONE

Every issue card's source set is configured, verified reachable on the local network (2026-08-25 probe: 48/48 URLs), with `default_language`, semantic `topics` and `exclude_keywords` per card. Runtime synced via CLI (`sources add`/`remove`, `topics add`).

- 8 demo domains aligned to cards: b2b (+b2bnn/marTech; a16z/crunchbase removed), gaming (+rockpapershotgun/gematsu/eurogamer/gamespot/pc-gamer; polygon/yystv removed), retail (+retailwire — later removed on TLS-fingerprint 403; ebrun removed), online-video (+the-verge/comingsoon; youtube/apple-music removed), online-education (+inside-highered; edsurge/class-central/khan/dedao/ncpssd/wanfang removed), tech-ai-developer (+hnrss/ars/techcrunch-ai/infoq-cn/lobsters/juejin/qbitai; ProductHunt/Reddit/Spotify removed), general-news (+people-cn/cgtn/sina; blocked/Western feeds removed), legal-compliance (+court-gov/thepaper-legal web sources; iapp/law-com/oyez removed).
- 8 new learning domains created from cards + imported: russian/spanish/hindi/italian/french/korean/portuguese/english-learning (21 domains total now).
- Compliance: every source carries `tos_classification`, `rate_limit`, identifying UA; process runs `--check-factual`; no paywalled/anti-scrape sources beyond the card lists; retailwire excluded from runtime despite card listing (curl 200 vs httpx 403 — TLS-fingerprint block, documented).

## KB progress (01-Raw, live from SQLite `entries`)

| Domain | Issue | 01-Raw | ≥50 |
|---|---|---|---|
| russian-learning | #30 | 53 | ✅ |
| gaming | #23 | 190 | ✅ |
| online-video | #25 | 168 | ✅ |
| general-news | #28 | 55 | ✅ |
| medical-research | (reference) | 73 | ✅ |
| portuguese-learning | #36 | 47 | processing… |
| financial-intelligence | (reference) | 42 | — |
| italian-learning | #33 | 20 | grinding |
| hindi-learning | #32 | 19 | grinding |
| korean-learning | #35 | 15 | grinding |
| english-learning | #37 | 23 | grinding |
| b2b | #22 | 8 | grinding |
| tech-ai-developer | #27 | 8 | grinding |
| retail | #24 | 20 | grinding |
| online-education | #26 | 10 | grinding |
| legal-compliance | #29 | 10 | grinding |
| spanish-learning | #31 | 4 | grinding |
| french-learning | #34 | 0 | queued |

Progress is bottlenecked by free-tier LLM provider capacity (see infra note below): the sequential master runner (`/tmp/opencode/master.sh`) processes one domain at a time, `AUTOINFO_LLM_MAX_CONCURRENCY=4`, `--check-factual`.

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