# AC4 Gap-Closure: API Key Acquisition Guide (Issue #277)

> Companion to `docs/dev/required-api-keys.md`. Lists the **11 key-required sources**
> blocking closure of the AC4 coverage gaps (issue #277, `[AC4] Coverage gap
> implementation list: 12 report×video + 89 source gaps + 39 KB tier gaps`).
> Every other gap source is keyless and does not need anything from you.
>
> **This document contains no secrets — only where to get keys and which
> environment variable / config field consumes each one.**

## How the key reaches AutoInfo

1. **Env-var collectors** (NYT, AP, Spotify, Quandl, Finnhub, FRED): the collector
   reads its environment variable directly. `export` it in the shell that runs
   `autoinfo` / the MCP server, or add it to the launch environment.
2. **Generic HTTP-API sources** (Alpha Vantage, Twelve Data, Guardian, Wanfang):
   the per-source `settings` block in `.autoinfo/config.yaml` carries the key as a
   `${VAR}` environment reference (never a raw value). You just obtain the key and
   tell the agent the value; the agent wires it as a `${REF}` with the value
   sourced from your environment.

## The 11 keys

| # | Source | How to get it (signup → key) | Env var / config consumed by | Notes |
|---|--------|------------------------------|------------------------------|-------|
| 1 | **NYT** (`nyt` collector) | <https://developer.nytimes.com/get-started> — register free, instant key; enable **Article Search API** | `AUTOINFO_NYT_API_KEY` (env) | Collector refuses without it — verified in `src/autoinfo/collectors/nyt.py` |
| 2 | **AP API** (`ap_api` collector) | <https://developer.ap.org> — AP developer portal registration (business contact required; trial access may take review) | `AUTOINFO_AP_API_KEY` (env) | Paid/licensed feed; collector refuses without key |
| 3 | **Spotify AI Podcasts** (`spotify` collector) | <https://developer.spotify.com/dashboard> — log in, **Create app** → copy **Client ID** + **Client Secret** (free) | `AUTOINFO_SPOTIFY_CLIENT_ID` + `AUTOINFO_SPOTIFY_CLIENT_SECRET` (env, **pair**) | Both required; collector refuses without them |
| 4 | **Quandl / Nasdaq Data Link** (`quandl` collector) | <https://data.nasdaq.com/sign-up> — free account → key under **Account → API Key** | `AUTOINFO_QUANDL_API_KEY` (env) | Collector logs "No Quandl API key configured" and returns `[]` without it (verified `quandl.py`) |
| 5 | **Finnhub** (http-api source) | <https://finnhub.io/register> — free sandbox key, 60 calls/min | `FINNHUB_API_KEY` (env) + source `settings: {token: "${FINNHUB_API_KEY}"}`; key travels in `token` query param | Required for the `financial-intelligence` demo domain source |
| 6 | **FRED** (http-api source) | <https://fredaccount.stlouisfed.org/apikeys> — free account at research.stlouisfed.org → **API Keys** | `FRED_API_KEY` (env) — agent adds source `settings.api_key: "${FRED_API_KEY}"` at key-delivery time (`auth_mode: query` already in the demo config) | Free registration; also gates the `sources-a6-keyed` validation scenario |
| 7 | **Alpha Vantage** (http-api source) | <https://www.alphavantage.co/support/#api-key> — free key emailed instantly | Source `settings: {api_key: "${ALPHA_VANTAGE_API_KEY}", auth_mode: query}` (handler sends `api_key=`; source expects `apikey=` — agent wires the correct param) | Free tier 25 req/day |
| 8 | **Twelve Data** (http-api source) | <https://twelvedata.com/register> — free **Basic** plan, key on dashboard (800 calls/day, 8/min) | Source `settings: {api_key: "${TWELVE_DATA_API_KEY}", ...}` (agent wires it at key-delivery time — demo config currently carries a literal `YOUR_TWELVEDATA_KEY` placeholder in `params` that must be replaced by the `${VAR}` ref) | Key shown immediately after account creation |
| 9 | **Guardian Open Platform** (http-api source) | <https://open-platform.theguardian.com/access/> — register → **Developer key** tier, emailed instantly (5,000 calls/day, 12/sec) | Source `settings: {api_key: "${GUARDIAN_API_KEY}", auth_mode: query}` (Guardian expects `api-key=` param — agent wires it) | Free tier is non-commercial |
| 10 | **Reddit** (`reddit` collector) | <https://www.reddit.com/prefs/apps> → **create another app** → type **script** → note the **client ID** (under the app name) and **secret** | Source `settings: {client_id: …, client_secret: …, user_agent: "AutoInfo/1.0", subreddits: […]}` (no env mechanism — config only; agent fills in `client_id`/`client_secret`/`user_agent` at key-delivery time — demo config currently carries only `subreddits`) | OAuth2 client-credentials; `_authenticate` raises without client_id+client_secret (verified `reddit.py`) |
| 11 | **wanfang (万方)** (http-api source) | 万方数据开放平台 — <https://open.wanfangdata.com.cn> (or Aliyun Marketplace "万方数据" API → APPCODE) | Source `settings: {headers: {…APPCODE…}}` | ⚠️ **Extra work**: source requires `POST` transport, but the generic handler is GET-only. A key alone is insufficient — a small code change (POST-capable transport or dedicated handler) is a separate unit of work, tracked with a regression scenario. |

## How to hand the keys over

**Option A — export env vars yourself** (recommended for env-var collectors):

```bash
export AUTOINFO_NYT_API_KEY="..."
export AUTOINFO_AP_API_KEY="..."
export AUTOINFO_SPOTIFY_CLIENT_ID="..."
export AUTOINFO_SPOTIFY_CLIENT_SECRET="..."
export AUTOINFO_QUANDL_API_KEY="..."
export FINNHUB_API_KEY="..."
export FRED_API_KEY="..."
export ALPHA_VANTAGE_API_KEY="..."
export TWELVE_DATA_API_KEY="..."
export GUARDIAN_API_KEY="..."
```

Then tell the agent "keys exported". The agent wires the http-api sources to
the env refs and runs the blocked-source collection wave.

**Option B — paste the values in chat.** The agent wires them as `${VAR}`
references in source `settings` and records nothing literal in git. Prefer A
when possible (keys never transit the agent session).

## What happens after the keys arrive

1. For http-api sources (Finnhub, FRED, Alpha Vantage, Twelve Data, Guardian)
   the agent adds the `${VAR}` `settings.api_key` ref to each source config
   (never a raw value) and fills Reddit's `client_id`/`client_secret`/
   `user_agent`; the env-var collectors (NYT/AP/Spotify/Quandl) need nothing
   further once the variable is exported. wanfang still needs the POST
   transport first — see row 11.
2. The key-blocked collection wave runs `autoinfo collect` per source;
   `collections/<domain>/<source>/` gains real JSON items.
3. Coverage matrix regenerates: the key-closable source gaps close
   (`source_gaps` 48 → ~37; the ~37 remainder are the egress-blocked /
   dead-feed verdicts recorded in
   `docs/dev/remaining-source-gap-verdicts.md`).
   `kb_tier_gaps` is already 0; report×video already 0.
4. Full test suite + evidence capture + atomic commits (per the W0–W5 plan).

Sources that still cannot be collected after keys (dead endpoint, policy, or the
wanfang POST transport) are **flagged in the wave report, never silently
dropped** — per the "flag rather than half-fix" rule.