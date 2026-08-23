# AutoInfo End-User Capabilities Guide

AutoInfo is a domain-agnostic information tracking & knowledge base platform: you configure sources and topics, and it handles automated collection, LLM-based extraction, and builds a queryable knowledge base plus finished knowledge products.

---

## 1. What AutoInfo Offers

AutoInfo splits into two halves:

**Raw data gathering.** AutoInfo pulls items from over 30 collector handlers across 29 source types. Anything collected lands in the 4-tier knowledge base (01-Raw sole entry; 00-Inbox deprecated) with full source provenance.

**Processed data generation.** Once raw content sits in the knowledge base, AutoInfo runs LLM extraction (TL;DR, key points, entities, relevance), then generates finished products: digests, reports, tutorials, presentations, exports, translations, and CEFR-classified or simplified content.

One note that shapes everything below: AutoInfo is agent-first. Every capability described in this guide is also exposed as an MCP tool, so a connected AI agent can drive the same workflows with `collect_sources`, `process_collection`, `generate_digest`, `search_knowledge_base`, and friends. The CLI commands shown here are the human-facing path to the same features.

---

## 2. Raw Data Gathering

### 2.1 Capability table

The platform ships 30 collector handlers covering 29 valid source types. Grouped by category:

| Category | Collectors / source types |
|----------|---------------------------|
| Academic | PubMed, Semantic Scholar, DBLP, OpenAlex, USPTO, SSRN, Unpaywall/CORE, edX sitemap, core, dblp, openalex, ssrn, unpaywall |
| Financial | Yahoo Finance, Quandl, AKShare, SEC EDGAR, akshare, quandl, yahoo_finance, sec_edgar |
| News | NYT, GDELT, AP API (paid), Reuters MCP (paid), nyt, gdelt, ap_api, reuters_mcp |
| Social / community | Reddit, HackerNews, reddit, hackernews |
| Video / podcast | YouTube, Bilibili, Spotify, Apple Podcasts, youtube, bilibili, spotify, apple_podcasts |
| Chinese platforms | Bilibili, AKShare |
| Enterprise / other | RSS, Web, Web Playwright, generic http_api (JSON API), webhook, email (IMAP), PDF, huggingface, kaggle, api, web, webhook, email, email_imap, pdf |

The named collectors are the ready-made handlers; the lowercase source types are the identifiers you pass to `sources add` when wiring up a feed yourself. The full list of 29 valid source types: `akshare`, `api`, `ap_api`, `apple_podcasts`, `bilibili`, `core`, `dblp`, `edx_sitemap`, `email`, `email_imap`, `gdelt`, `hackernews`, `huggingface`, `kaggle`, `nyt`, `openalex`, `pdf`, `quandl`, `reddit`, `reuters_mcp`, `rss`, `sec_edgar`, `spotify`, `ssrn`, `unpaywall`, `web`, `webhook`, `yahoo_finance`, `youtube`.

### 2.2 Demo domains

Thirteen demo domains ship with the platform. Each is a preconfigured bundle of sources and topics for that field. They are configurations, not hardcoded features; your own domain works the same way.

| Demo domain | Focus |
|-------------|-------|
| medical-research | Biomedical literature and clinical research |
| ai-commercial | AI industry and commercialization |
| financial-intelligence | Markets, companies, financial signals |
| tech-ai-developer | Developer tooling and AI engineering |
| language-learning | Language content and learning material |
| online-video | Video platforms and creators |
| financial-news | Financial journalism and headlines |
| online-education | Courses, curricula, learning platforms |
| legal-compliance | Law, regulation, compliance |
| general-news | Broad news coverage |
| gaming | Gaming industry and culture |
| b2b | Business-to-business markets |
| retail | Retail industry and consumer markets |

### 2.3 How to gather raw data

**Step 1. Scaffold a project with a demo domain.**

```bash
autoinfo init --demo medical-research
```

This creates the project config with the medical-research domain active. (Run it once per project; skip it if you already have a project.)

**Step 2. Add a topic to track.**

```bash
autoinfo topics add --domain medical-research --name "IVF breakthroughs" --keywords ivf,embryo,fertility
```

Topics are the tracking units. Keywords feed the relevance scoring later.

**Step 3. Add or inspect sources.**

The demo domain already has sources, but you can add your own feed to any domain:

```bash
autoinfo sources add --name "My RSS Feed" --url https://example.com/feed.xml --type rss --domain medical-research
autoinfo sources list --domain medical-research
```

Test a source before committing to it:

```bash
autoinfo sources test --url https://example.com/feed.xml --type rss
```

Group topics if you want a hierarchy:

```bash
autoinfo topic-group add --domain medical-research --group "reproductive-health" --topic "IVF breakthroughs"
```

**Step 4. Collect.**

```bash
autoinfo collect --domain medical-research --topic "IVF breakthroughs" --limit 5
```

Collection fetches items from the configured sources in parallel and caches them. Preview without storing anything with `--dry-run`. To collect all active domains at once, use `--all` (or `-A`). Other useful flags: `--source <source>` to limit to one source, `--auto-process` to run processing right after collection, and `--force-full` to ignore incremental state.

**Step 5. Process.**

```bash
autoinfo process --domain medical-research
```

Processing reads the cached raw items and runs LLM extraction (TL;DR, key points, entities, relevance) plus the quality gates G1-G5. G0 (schema integrity) and G4 (factual consistency) are hard gates: they retry up to three times, then block. G1, G2, G3, and G5 are soft gates with configurable actions. Items that pass land in the knowledge base as 01-Raw entries. You can pick the model with `--model <model>`, set the batch size with `--batch-size N`, and enable extra checks with `--check-factual` and `--check-translation`.

Check collection stats any time:

```bash
autoinfo status
```

You can also import existing files straight into 01-Raw without a collector:

```bash
autoinfo import-kb --domain medical-research --format markdown --file path/to/entry.md
```

Supported import formats: `markdown` (YAML+Markdown frontmatter), `json`, `csv`, and `opml`. Every imported entry lands in 01-Raw.

**MCP equivalents:** `add_source`, `add_sources`, `test_source`, `list_sources`, `get_source_health`, `add_topic`, `collect_sources`, `get_collection_progress`, `process_collection`, `import_kb`.

---

## 3. The Knowledge Base

Everything collected flows through a 4-tier pipeline (00-Inbox deprecated → 01-Raw → 02-Draft → 03-Wiki):

```
00-Inbox (deprecated) → 01-Raw → 02-Draft → 03-Wiki
```

- **01-Raw** is the sole entry point for collected content. Every item keeps complete source provenance (`source_url`, `source_type`, `source_platform`).
- **02-Draft** is where an agent can process and refine content, but a Draft can only be created from 01-Raw.
- **03-Wiki** is the final production tier. Promotion Draft→Wiki is an **agent operation** (`promote_kb_draft`, no human gate — the KB is a database for raw/processed production), and Wiki is append-only: entries there are not demoted or deleted.

Browse and manage the tiers:

```bash
autoinfo kb list-tiers --domain medical-research
autoinfo kb create-draft --raw-id <raw-entry-id> --title "<title>"   # compile Raw entries into a Draft
autoinfo kb reject-draft <draft-id>                                  # reject a Draft back out
autoinfo kb promote --entry-id <draft-id>   # promote Draft to Wiki (also available to agents via promote_kb_draft)
```

Promotion Draft→Wiki is an **agent operation** (`promote_kb_draft`, no human gate — the KB is a database for raw/processed production). Human-director review happens before promotion (quality review of Drafts), not as a gate inside the promote step.

**Search.**

```bash
autoinfo kb search --query "embryo selection" --domain medical-research --limit 5
```

Omit `--domain` to search across all domains. The MCP equivalent, `search_knowledge_base`, adds modes: `hybrid` (FTS5 + vector), `vector` (semantic only), and `faceted` with filters.

**Summaries and Q&A.**

```bash
autoinfo summaries list
autoinfo summaries show <summary-id>
autoinfo summaries flag <summary-id> --tag clinical --importance 4
```

`show` prints the full detail for one summary (pass its ID from `list`). `flag` marks a summary for the knowledge base — pass the summary ID as the positional argument, and use `--tag <tag>` repeatedly plus `--importance 1-5` to weight it.

Ask questions directly over collected content:

```bash
autoinfo query-collected --query "What are the latest IVF success rate findings?" --domain medical-research
```

This runs FTS5 retrieval plus LLM synthesis with source citations.

**MCP equivalents:** `search_knowledge_base`, `get_kb_entry`, `list_summaries`, `get_summary`, `flag_for_knowledge_base`, `create_kb_draft` (from Raw only), `reject_kb_draft`, `list_kb_tier`, `link_items`, `get_item_relations`, `query_knowledge_graph`, `knowledge_graph_export`, `recommend_content`.

---

## 4. Processed Data Generation

### 4.1 Capability table

| Product | What you get | Formats |
|---------|--------------|---------|
| Digest | Periodic roundup of the latest collected content | markdown, html, json, agent (MCP also: epub, audiobook) |
| Report | Structured analysis, typed by `report_type` | markdown, json, agent (MCP also: html, audio, video, epub, audiobook) |
| Tutorial | Step-by-step teaching content | markdown (MCP: md, agent) |
| Presentation | Slide-ready outline | markdown (MCP: md, agent) |
| Export | The knowledge base or a domain, portable | json, markdown, sqlite, pdf, bundle, agent (MCP also: rss, csv, graphml, sitemap, epub, mobi) |
| Translate | LLM translation of content or arbitrary text | source/target language pair |
| CEFR classify | Level classification EN / ZH / JA | classify, batch |
| Simplify | CEFR-parameterized text simplification (A1-C1) | MCP `simplify_content` |

Eight product templates exist behind these: digest, report, tutorial, presentation, premium-briefing, column, magazine-digest, enterprise-briefing. Column is the paid deep-dive type, premium-gated.

Report types: `standard`, `industry`, `competitive`, `trend`, `daily-briefing`, `column`. Audiences: `researcher`, `clinician`, `executive`, `student`, `investor`.

Two special formats worth calling out:

- **`agent`** returns JSON-LD (`@type: KnowledgeDigest`) that an LLM can re-consume directly.
- **`audiobook`** (MCP) renders a chaptered MP3 plus ZIP. `export_kb` with `epub` or `mobi` covers ebook needs.

### 4.2 How to generate processed output

**Digest.**

```bash
autoinfo output digest --domain medical-research --period weekly --format markdown
```

Periods: `daily`, `weekly`, `monthly`. Formats: `markdown`, `html`, `json`, `agent`.

**Report.**

```bash
autoinfo output report --domain medical-research --type daily-briefing --audience clinician --format markdown
```

A single-domain report takes `--domain`. For a cross-domain report, repeat `--domains` instead:

```bash
autoinfo output report --domains medical-research --domains ai-commercial --type trend --format markdown
```

**Export.**

```bash
autoinfo output export --domain medical-research --format bundle
```

Formats for the CLI: `json`, `markdown`, `sqlite`, `pdf`, `bundle`, `agent`. Output is written to `exports/`.

**Translate.**

```bash
autoinfo output translate --content "CRISPR shows promise in clinical trials" --source-lang en --target-lang zh
```

Or translate an existing content item by ID instead of raw text:

```bash
autoinfo output translate --content-id <id> --source-lang en --target-lang zh --domain medical-research
```

**Tutorials and presentations.**

```bash
autoinfo output tutorial --domain medical-research
autoinfo output presentation --domain medical-research --topic "IVF breakthroughs" --slides 10
autoinfo output list-templates
```

**CEFR classification.**

```bash
autoinfo cefr classify --lang en --texts "This is a sample text."
autoinfo cefr batch --lang en --texts "Text one." "Text two."   # or --input file.txt, one text per line
```

Supports English, Chinese, and Japanese.

**MCP equivalents:** `generate_digest`, `generate_report`, `generate_cross_domain_report`, `generate_tutorial`, `generate_presentation`, `localize_content`, `export_kb`, `classify_cefr`, `cefr_batch`, `simplify_content`, `extract_fields`, `get_extraction`.

---

## 5. End-to-End Worked Example

Scenario: track IVF breakthroughs in the medical-research domain, review what came in, and produce a clinician-facing briefing.

**1. Scaffold the project.**

```bash
autoinfo init --demo medical-research
```

Sets up the project with the medical-research demo domain.

**2. Add the topic.**

```bash
autoinfo topics add --domain medical-research --name "IVF breakthroughs" --keywords ivf,embryo,fertility
```

Creates the tracking topic with keywords for relevance scoring.

**3. Collect a small batch.**

```bash
autoinfo collect --domain medical-research --topic "IVF breakthroughs" --limit 5
```

Fetches up to 5 recent items from the domain's sources and caches them.

**4. Process.**

```bash
autoinfo process --domain medical-research
```

Runs LLM extraction and quality gates, creating 01-Raw KB entries.

**5. Browse the summaries.**

```bash
autoinfo summaries list
```

Shows the extracted summaries for the processed items.

**6. Flag the useful ones.**

```bash
autoinfo summaries flag <summary-id> --tag clinical --importance 4
```

Marks a summary (ID from the `list` step) as relevant with a clinical tag.

**7. Search the knowledge base.**

```bash
autoinfo kb search --query "embryo selection" --domain medical-research --limit 5
```

Finds the relevant entries across the domain.

**8. Generate the weekly digest.**

```bash
autoinfo output digest --domain medical-research --period weekly --format markdown
```

Produces a markdown roundup of the week's collected content.

**9. Generate a clinician daily briefing.**

```bash
autoinfo output report --domain medical-research --type daily-briefing --audience clinician --format markdown
```

Runs the same collected content through the daily-briefing report type, tuned for clinicians.

**10. Promotion (agent operation).**

The final step is agent-driven: promoting a Draft to the append-only Wiki tier via `promote_kb_draft` (KB-tier guard, no human gate). The CLI equivalent exists for direct CLI users:

```bash
autoinfo kb promote --entry-id <id>
```

---

## 6. Delivery & Scheduling (Brief)

AutoInfo delivers products through 13 channels: `smtp`, `webhook`, `rest_api`, `file_export`, `discord`, `telegram`, `wechat_work`, `wechat_oa`, `dingtalk`, `feishu`, `rss`, `social_publish`, `push`.

For scheduled delivery, the MCP tools `add_delivery_schedule`, `list_delivery_schedules`, and `remove_delivery_schedule` manage cron-based schedules. `send_email_digest` sends a digest over SMTP, and `send_to_enduser` delivers a product to a registered end user.

---

## 7. LLM Key Requirement

The processing and generation steps run on your own LLM key (BYOK). Set it before you start:

```bash
export AUTOINFO_LLM_API_KEY=your-key-here
```

Without a configured key, the LLM-required tools are skipped or return `LLM_NOT_CONFIGURED` at dispatch. Everything upstream of the LLM, such as plain collection into the cache, still works; the extraction and generation steps do not.
