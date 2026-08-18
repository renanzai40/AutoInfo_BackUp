# Required API Keys & Environment Variables

> Reference catalog of every environment variable AutoInfo reads at runtime.
> Used by error messages (Task 15) and CLI help (Task 18) to point operators at
> the exact variable they need to set.
>
> **This document never contains actual key values.** It only names the
> variables and explains where each one is consumed.

## How AutoInfo resolves credentials

Most variables follow a two-tier lookup:

1. The source's `settings` block in `.autoinfo/config.yaml` (or the
   `add_source` MCP tool's `settings` argument).
2. The environment variable listed below.

Config dict wins; env var is the fallback. This means you can either
`export` the variable in your shell or hand it to `add_source` via the
MCP tool. The `configure_llm` MCP tool writes an env var *reference*
(`${AUTOINFO_LLM_API_KEY}`) into config rather than the raw key, so the
secret stays in your environment.

### `llm.fallback[].api_key` — per-entry key semantics

Each `llm.fallback` entry may carry its own `api_key` field. The value is
either a raw key or a `${ENV_VAR}` reference (resolved from the
environment at call time, same rule as the primary `llm.api_key`). An
empty `api_key` (`''`) inherits the primary key / `AUTOINFO_LLM_API_KEY`
environment variable; an empty `provider` (`''`) inherits the primary
provider. `configure_llm(llm_fallback=[...])` writes these entries
verbatim — never store a raw key in a fallback entry when a `${ENV}`
reference works.

## Core (required for any processing)

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `AUTOINFO_LLM_API_KEY` | API key for the configured LLM provider (OpenRouter, OpenAI, DeepSeek, Ollama, Azure, etc.). Drives extraction, summarization, Q&A synthesis, CEFR classification, translation, and TTS rendering. | **Required** for collection processing, KB extraction, Q&A, and audio output. Optional only if you never run `process`, `qa`, `cefr`, or `format=audio`. | `src/autoinfo/llm.py`, `src/autoinfo/qa.py`, `src/autoinfo/doctor.py`, `src/autoinfo/config.py`, `src/autoinfo/cli/init.py`, `src/autoinfo/mcp/server.py`, `src/autoinfo/output/__init__.py` |
| `OPENAI_API_KEY` | Fallback key for OpenAI Text-to-Speech when `AUTOINFO_LLM_API_KEY` is unset and `llm.api_key` is blank. Only consulted by the audio renderer. | Optional. Only needed for `format=audio` output via OpenAI TTS. | `src/autoinfo/output/__init__.py` (`_render_audio_openai`) |

## Runtime tuning

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `AUTOINFO_DB_BUSY_TIMEOUT_MS` | SQLite `PRAGMA busy_timeout` in milliseconds. Controls how long a write waits for the database lock before returning `SQLITE_BUSY`. Default 30000 (30s). | Optional. Only tune if you see `database is locked` errors under heavy concurrent writes. | `src/autoinfo/kb.py` (`_db_busy_timeout_ms`) |

## Audit actor identity

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `AUTOINFO_ACTOR` | Stable actor id recorded on dispatch-level audit rows. Set by launchers (cron wrapper, CLI shim) to identify the caller taxonomy (`agent:<session>`, `cli`, `cron`, `system`). Defaults to `agent:mcp` when unset. | Optional. Only needed when you want launcher-specific actor attribution in the audit log. | `src/autoinfo/mcp/server.py` (`_resolve_actor`), audit hook |

## Collectors

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `AUTOINFO_NYT_API_KEY` | New York Times Article API key. The NYT collector refuses to fetch without it. | **Required** for the `nyt` source type. | `src/autoinfo/collectors/nyt.py` |
| `AUTOINFO_AP_API_KEY` | Associated Press API key for the paid AP feed collector. | **Required** for the `ap_api` source type. | `src/autoinfo/collectors/ap_api.py` |
| `AUTOINFO_REUTERS_API_KEY` | Reuters MCP endpoint API key for the paid Reuters feed collector. | **Required** for the `reuters_mcp` source type. | `src/autoinfo/collectors/reuters_mcp.py` |
| `AUTOINFO_YOUTUBE_API_KEY` | YouTube Data API v3 key. Needed for search, channel fetch, and caption retrieval. | **Required** for the `youtube` source type. | `src/autoinfo/collectors/youtube.py` |
| `AUTOINFO_SPOTIFY_CLIENT_ID` | Spotify app client ID for podcast collection. | **Required** for the `spotify` source type (paired with the secret). | `src/autoinfo/collectors/spotify.py` |
| `AUTOINFO_SPOTIFY_CLIENT_SECRET` | Spotify app client secret. | **Required** for the `spotify` source type. | `src/autoinfo/collectors/spotify.py` |
| `AUTOINFO_QUANDL_API_KEY` | Quandl/Nasdaq Data Link API key for financial datasets. | **Required** for the `quandl` source type. | `src/autoinfo/collectors/quandl.py` |
| `AUTOINFO_PUBMED_API_KEY` | NCBI E-utilities API key. PubMed works without it but at a lower rate limit (3 req/s vs 10 req/s). | Optional. Recommended for any non-trivial PubMed volume. | `src/autoinfo/collectors/pubmed.py` |
| `AUTOINFO_S2_API_KEY` | Semantic Scholar API key for higher rate limits. The public endpoint works without it. | Optional. Recommended for bulk academic collection. | `src/autoinfo/collectors/semantic_scholar.py` |
| `AUTOINFO_USPTO_API_KEY` | PatentsView API key for higher rate limits. The PatentsView REST API works without it; the RSS fallback needs no key at all. | Optional. | `src/autoinfo/collectors/uspto.py` |
| `AUTOINFO_HTTP_API_KEY` | Generic bearer token for arbitrary REST API sources configured via the `http_api` handler. | Optional. Only used when the source's `settings` block does not supply `api_key`. | `src/autoinfo/collectors/http_api.py` |
| `FINNHUB_API_KEY` | Finnhub API key for the Finnhub source in the financial-intelligence demo domain (quality-tiered `api` source; the key travels in the `token` query parameter). | **Required** for the Finnhub source (financial-intelligence demo domain). | `src/autoinfo/data/domains/financial-intelligence/sources.yaml` |
| `FRED_API_KEY` | FRED (Federal Reserve Economic Data) API key for the FRED source in the financial-intelligence demo domain. Free registration at research.stlouisfed.org. Collected via the generic `http_api` handler (`auth_mode: query`). Also gates the `sources-a6-keyed` validation scenario (reports `unconfigured` when unset — never a silent skip). | **Required** for the FRED source (financial-intelligence demo domain) and the `sources-a6-keyed` validation scenario. | `src/autoinfo/data/domains/financial-intelligence/sources.yaml`, `src/autoinfo/mcp/scenarios/sources-a6-keyed.yaml` |
| `AUTOINFO_EMAIL_PASSWORD` | IMAP password for the email collector. Falls back to `email.password` in config. | Optional. Only needed when collecting from an IMAP mailbox. | `src/autoinfo/collect.py` |
| `KAGGLE_USERNAME` | Kaggle username for the HuggingFace/Kaggle collector (`provider="kaggle"`). | **Required** for the `kaggle` source type (paired with `KAGGLE_KEY`). | `src/autoinfo/collectors/huggingface.py` |
| `KAGGLE_KEY` | Kaggle API key for the HuggingFace/Kaggle collector (`provider="kaggle"`). | **Required** for the `kaggle` source type (paired with `KAGGLE_USERNAME`). | `src/autoinfo/collectors/huggingface.py` |

Collectors that need no key at all: `arxiv`, `crossref`, `dblp`, `openalex`, `rss`, `web`, `reddit`, `bilibili`, `apple_podcasts`, `pdf`, `webhook`, `akshare`, `sec_edgar`, `edx_sitemap`.

## Delivery channels

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `AUTOINFO_SMTP_HOST` | SMTP server host for email delivery. Used by the channel health check. | Optional. Email delivery also reads `email.smtp_host` from config. | `src/autoinfo/delivery/__init__.py` |
| `AUTOINFO_SMTP_PORT` | SMTP server port. | Optional. Same fallback as above. | `src/autoinfo/delivery/__init__.py` |
| `AUTOINFO_SMTP_PASS` | SMTP password. Referenced in the default config template as `${AUTOINFO_SMTP_PASS}`. | Optional. Only when SMTP auth is enabled. | `src/autoinfo/data/default_config.yaml` |
| `AUTOINFO_SMTP_USER` | SMTP username for authenticated email delivery. Used alongside `AUTOINFO_SMTP_HOST`/`AUTOINFO_SMTP_PORT`/`AUTOINFO_SMTP_PASS`. | Optional. Only when the SMTP server requires login. | `src/autoinfo/delivery/__init__.py` |
| `AUTOINFO_WEBHOOK_URL` | Default webhook target URL for the webhook delivery channel health check. | Optional. Per-source webhooks use `set_domain_webhooks` instead. | `src/autoinfo/delivery/__init__.py` |
| `AUTOINFO_REST_API_URL` | Default REST API target for the `rest_api` delivery channel health check. | Optional. | `src/autoinfo/delivery/__init__.py` |
| `AUTOINFO_EXPORT_DIR` | Output directory for the `file_export` delivery channel. Defaults to the current working directory. | Optional. | `src/autoinfo/delivery/__init__.py` |
| `AUTOINFO_RSS_DIR` | Output directory for the `rss` delivery channel. Defaults to the current working directory. | Optional. | `src/autoinfo/delivery/rss.py` |
| `AUTOINFO_TMPDIR` | Scratch directory for video/audio rendering. Defaults to `/tmp/autoinfo/video`. | Optional. | `src/autoinfo/output/__init__.py` |
| `AUTOINFO_ADMIN_EMAIL` | Admin recipient for cron failure notices. Falls back to `email.to_addrs` from config. | Optional. Only needed if you want cron error mail distinct from normal digest recipients. | `src/autoinfo/cli/cron.py` |

## Third-party delivery platform tokens

These are only read by their respective channel adapters. Set the ones for the
channels you actually deliver to.

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `DISCORD_BOT_TOKEN` | Discord bot token for the `discord` channel. | Optional. Required only if you deliver via Discord. | `src/autoinfo/delivery/discord.py` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for the `telegram` channel. | Optional. Required only if you deliver via Telegram. | `src/autoinfo/delivery/telegram.py` |
| `WECHAT_WORK_CORPID` | WeChat Work corporation ID. | Optional. Required only for the `wechat_work` channel. | `src/autoinfo/delivery/wechat_work.py` |
| `WECHAT_WORK_CORPSECRET` | WeChat Work corporation secret. | Optional. Paired with the corp ID. | `src/autoinfo/delivery/wechat_work.py` |
| `WECHAT_OA_APPID` | WeChat Official Account app ID. | Optional. Required only for the `wechat_oa` channel. | `src/autoinfo/delivery/wechat_oa.py` |
| `WECHAT_OA_APPSECRET` | WeChat Official Account app secret. | Optional. Paired with the app ID. | `src/autoinfo/delivery/wechat_oa.py` |
| `DINGTALK_APP_KEY` | DingTalk app key. | Optional. Required only for the `dingtalk` channel. | `src/autoinfo/delivery/dingtalk.py` |
| `DINGTALK_APP_SECRET` | DingTalk app secret. | Optional. Paired with the app key. | `src/autoinfo/delivery/dingtalk.py` |
| `FEISHU_APP_ID` | FeiShu (Lark) app ID. | Optional. Required only for the `feishu` channel. | `src/autoinfo/delivery/feishu.py` |
| `FEISHU_APP_SECRET` | FeiShu app secret. | Optional. Paired with the app ID. | `src/autoinfo/delivery/feishu.py` |
| `SOCIAL_PUBLISH_TOKEN` | Auth token for the generic `social_publish` channel. Also resolved from `${VAR}` references in channel config. | Optional. | `src/autoinfo/delivery/social.py` |
| `SOCIAL_PUBLISH_ENDPOINT` | Custom endpoint for the `social_publish` channel. | Optional. | `src/autoinfo/delivery/social.py` |

## Billing (Stripe)

Only relevant if you run the subscription/billing stack.

| Env Var | Purpose | Required? | Source |
|---------|---------|-----------|--------|
| `STRIPE_API_KEY` | Stripe secret API key for checkout, invoices, and customer management. | Optional. Required only for live billing. | `src/autoinfo/billing.py` |
| `STRIPE_API_BASE` | Override the Stripe API base URL. Defaults to `http://localhost:12111` for local `stripe-mock` development. | Optional. | `src/autoinfo/billing.py` |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret for signature verification on the `/webhooks/stripe` endpoint. | Optional. Required only when receiving Stripe webhooks. | `src/autoinfo/api/server.py` |

## LiteLLM provider keys

AutoInfo routes LLM calls through LiteLLM. When your `llm.provider` is set to a
specific vendor, LiteLLM reads that vendor's canonical env var directly
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`,
etc.). AutoInfo itself only reads `AUTOINFO_LLM_API_KEY` and forwards it as the
LiteLLM `api_key` argument, so for most setups a single
`AUTOINFO_LLM_API_KEY` export is enough. Set the vendor-native variable only
when you want LiteLLM's fallback path or when a tool (TTS) reads it directly.

See the LiteLLM provider docs for the full list of vendor env var names.

## Quick start: the minimum viable set

For a single-domain demo with email digest delivery:

```bash
export AUTOINFO_LLM_API_KEY="sk-..."        # required
export AUTOINFO_SMTP_HOST="smtp.example.com" # if you want email delivery
export AUTOINFO_SMTP_PORT="587"
```

Everything else is opt-in per source and per channel.