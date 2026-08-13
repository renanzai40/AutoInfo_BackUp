<!-- agent: business-context -->
<!-- doc-type: market-positioning -->
<!-- scope: business, competitive-intelligence, pricing, personas -->
<!-- operational: false -->
<!-- source: founder-expectations.md §§6-7 -->
<!-- related: docs/dev/cross-dimensional-catalog.md (keystone matrix derived from here) -->

# Market Positioning & Priority Matrix

## Agent Summary

- **This document is business and market context, not operational.** It defines AutoInfo's priority matrix, competitive landscape, pricing tiers, and target personas. Do not treat it as a pipeline or tooling spec.
- **Agents may consult this doc for competitive intelligence questions** — e.g., "who are AutoInfo's competitors?", "what's the differentiator vs. Feedly?", "what's the pricing strategy?". Use it to answer user-facing positioning questions, not to drive tool calls.
- **Key competitors by category:** RSS readers (Feedly, Inoreader), enterprise intelligence (AlphaSense, CB Insights), AI research tools (EnkiAI, TrendIntel), web extraction APIs (Diffbot, KnowledgeSDK), knowledge platforms (Notion, Obsidian).
- **Core differentiators:** domain-agnostic KB building (not just feed reading), agent-native MCP interface, BYOK cost control, user-defined extraction schemas, full data ownership via files (no SaaS lock-in), affordability for individuals vs. enterprise tools.
- **Two product lines:** RAW (API feeds, webhook streams, bulk export) and PROCESSED (scheduled digests, thematic reports, alert streams). Pricing spans Free → Premium → Enterprise tiers.

---

> Extracted from `founder-expectations.md §§6-7`. References: F30 (Billing), F42 (External Billing), F28 (RAW Products), F29 (PROCESSED Products).
> **Keystone matrix:** [`docs/dev/cross-dimensional-catalog.md`](../cross-dimensional-catalog.md) — the priority fix matrix (§4) and implementation roadmap (§5) in the CD catalog derive from the market priorities defined here.

---

## 6. Founder's Priority Matrix

### 6.1 Implementation Quadrants

| Quadrant | Importance | Effort | Expectations |
|----------|-----------|--------|--------------|
| **🔴 Build first** | HIGH | LOW | **F01-F06** (setup — foundation), **F11** (one-command collect — core loop), **F12** (progress), **G1-G3** (basic gates) |
| **🟡 Core value** | HIGH | HIGH | **F07** (demo domain: medical sources), **F13** (RSS + API handlers), **F15** (LLM extraction), **F16** (summary review), **F20** (KB storage), **F21** (KB search) |
| **🟢 Enhance** | MEDIUM | LOW | **F08** (custom sources), **F09** (topic management), **F10** (localization), **F18** (quality feedback), **G4-G5** (advanced gates) |
| **🔵 Asset phase** | MEDIUM | HIGH | **F17** (Q&A), **F19** (cross-ref), **F22** (knowledge graph), **F24-F26** (outputs) |
| **⚪ Polish** | LOW | VARIES | **F14** (scheduling), **F31-F34** (monitor/iterate) |
| **🔴 Product & Delivery** | CRITICAL | MEDIUM | **F27** (Product Delivery), **F28-F29** (RAW + PROCESSED), **G0/G4** (hard gates), **D1-D3** (delivery gates) |

### 6.2 Demo Domain Implementation Priority

| Demo Domain | v1 Priority | Rationale |
|-------------|-------------|-----------|
| **Medical Research** | 🔴 P0 | Primary validation domain. Most structured data (PubMed API), clearest value. Proves the collection → extraction → KB loop. |
| **Financial/Business Intelligence** | 🔴 P0 | Highest WTP domain validated by market data (Bloomberg $2,665/user/mo, WSJ $44.99/mo). Proves high-value data feed production and institutional-grade delivery. Validates RAW product line for commercial viability. |
| **AI Commercial Intelligence** | 🟡 P1 | Second validation domain. Tests multi-source collection (API + web + feeds). Proves cross-source structuring. |
| **Tech/AI/Developer** | 🟡 P1 | Highest API availability domain — most sources offer free/open APIs. Validates lightweight domain setup with minimal cost. Proves newsletter-style PROCESSED products. |
| **Language Learning (L1 only)** | 🟢 P2 | L1: collect + CEFR tag. Lowest effort to validate. Does not block architecture decisions. |

### 6.3 Immediate Action Items

| Priority | Item | Why |
|----------|------|-----|
| 🔴 P0 | **Build collection core loop** (fetch → parse → dedup → store) | Everything depends on this. Start with RSS handler, then API handler. |
| 🔴 P0 | **Curate medical demo sources** (PubMed API integration) | First validation domain. Needs real API integration, not mock. |
| 🔴 P0 | **Design KB file schema** (YAML frontmatter + Markdown body) | Most consequential architecture decision. Gets harder to change later. |
| 🟡 P1 | **Implement LLM extraction pipeline** (summarization + field extraction) | Primary value-add. Universal, domain-agnostic. |
| 🟡 P1 | **Build G1-G3 quality gates** (source authority, dedup, relevance) | Basic quality control before KB entries are created. |

---

## 7. Market Positioning

### 7.1 Competitive Landscape

AutoInfo occupies an **empty space** between existing tool categories:

| Category | Tools | Price | AutoInfo's differentiator |
|----------|-------|-------|--------------------------|
| **RSS readers** | Feedly, Inoreader | $7-12/mo personal, $1,600+/mo enterprise | KB building, not just feed reading. Structured extraction. Agent-native. BYOK for cost control. |
| **Enterprise intelligence** | AlphaSense, CB Insights | $10K-$100K/user/year | Affordability for individuals. User-defined domains, not predefined verticals. |
| **AI research tools** | EnkiAI, TrendIntel | $17-79/mo | Domain-agnostic KB. User-defined extraction schemas. Full data ownership (files, not SaaS lock-in). |
| **Web extraction APIs** | Diffbot, KnowledgeSDK | $29-$299/mo | User-facing product with KB, search, MCP. Not just a developer API. |
| **Knowledge platforms** | Notion, Obsidian | Free-$10/mo | Built-in collection pipeline. Auto-populated KB. You don't bring your own content. |

### 7.2 Target User (Paying Customer)

AutoInfo serves two distinct customer types corresponding to the two product lines:

**Customer Type A: Information Buyer (RAW products)**
Pays for access to curated, structured information feeds in their domain of interest.

| Attribute | Description |
|-----------|-------------|
| **Title examples** | Pharma competitive intelligence analyst, VC deal sourcing associate, policy research lead, market intelligence manager |
| **Buys** | RAW data feeds: structured paper collections, API access to curated items, bulk exports |
| **Current pain** | Paying $10-100K/year for proprietary databases (Capital IQ, AlphaSense) when public sources + LLM extraction would suffice |
| **Willingness to pay** | $50-500/mo for reliable domain-specific RAW feeds |
| **Quality concern** | Completeness, freshness, source traceability |

**Customer Type B: Knowledge Product Subscriber (PROCESSED products)**
Pays for synthesized, analyzed, ready-to-consume knowledge products.

| Attribute | Description |
|-----------|-------------|
| **Title examples** | Busy clinician, portfolio manager, startup founder, executive decision-maker |
| **Buys** | PROCESSED products: digest bundles, thematic reports, alert streams |
| **Current pain** | No time to read primary sources; needs distilled, trustworthy analysis delivered regularly |
| **Willingness to pay** | $100-2,000/mo for domain-specific processed intelligence |
| **Quality concern** | Factual accuracy, analysis depth, timeliness, presentation quality |

#### 7.2a User Persona by Domain (NEW)

> *Domain-specific user personas derived from the global information payment research report (2024-2026). These personas refine the generic customer types above with detailed demographics, decision patterns, and willingness-to-pay data per domain.*

##### Domain 1: Financial/Business Intelligence

| Attribute | C端 (Individual) | B端 (Institutional) |
|-----------|-----------------|-------------------|
| **Age range** | 30-55 (primary); significantly older than entertainment content consumers | 35-60 (senior decision-makers) |
| **Occupation** | Professional investors, financial analysts, traders, high-net-worth individuals | CIO/CTO/IT directors, heads of research, portfolio managers, corporate strategy |
| **Education** | Bachelor's+ >85% | Advanced degree common (MBA, CFA, PhD) |
| **Income/Revenue** | Household income $100K+ | Firm ACV $50K-$500K |
| **Geography** | Norway (40% news penetration), Sweden (31%), US (22%), China (Caixin model); Nordic/Western Europe highest | North America ~60% of global SaaS spend, EMEA ~25%, APAC ~12% |
| **Decision cycle** | Personal: minutes-days (subscription) | 3-18 months (multi-stakeholder: CIO + legal + finance + business line) |
| **Price sensitivity** | Medium; Bloomberg $2,665/user/mo for retail (terminal); WSJ $44.99/mo for mass premium | Low; ROI-driven, compliant-premium tolerance |
| **Key channels** | Bloomberg Terminal, WSJ, FT, 财新, Wind (China), Alpha Vantage (retail) | Bloomberg, Refinitiv, Wind institutional, Reuters Connect |
| **WTP range** | $20-$2,665/mo (varies by depth) | $50K-$500K ACV |

##### Domain 2: Knowledge Payment / Online Education

| Attribute | C端 (Individual Learner) | B端 (Enterprise L&D) |
|-----------|-------------------------|---------------------|
| **Age range** | 18-40 (80%+); 25-35 most active; 18-35 = 62.3% | 30-50 (L&D managers, HR directors) |
| **Occupation** | Corporate staff (38.5%), freelancers (22.1%), students (19.7%) | CFO, L&D Directors, HR VPs |
| **Education** | Bachelor's+ 60%+ (2024); sub-bachelor growing +31.8% YoY ("knowledge democratization") | — |
| **Income** | ¥8K-¥30K/mo (new middle class, China); $50K-$100K/yr (US) | — |
| **Geography** | Tier 1/new Tier 1/Tier 2 cities (China); global (Coursera) | Global enterprise (Coursera 6,200+ corporate clients) |
| **Decision cycle** | Minutes-days (course purchase); impulse-driven | 3-6 months (fiscal year planning) |
| **Price sensitivity** | High; avg course ¥30-¥80 (China); $39-$79/mo (US) | Medium; ~$1,000/enterprise/yr (Coursera); ROI on upskilling |
| **Key platforms** | 得到 (¥99-¥399/course), Coursera ($59/yr Plus), 知乎盐选, Udemy | Coursera Enterprise, edX for Business, Udemy Business |
| **Repurchase rate** | 41% (audio), 45% professional vs 20% entry-level | >90% annual renewal (corporate SaaS norm) |
| **WTP range** | ¥100-¥500/yr (China); $50-$500/yr (US) | $5K-$100K+/yr |

##### Domain 3: Tech/AI/Developer

| Attribute | Description |
|-----------|-------------|
| **Age range** | 18-34 (dominant); 25-34 fastest-growing segment for AI news consumption (+4pp YoY) |
| **Occupation** | Software developers, ML/AI engineers, data scientists, technical founders, CTOs |
| **Geography** | Global; US/Western Europe (primary), APAC (fastest growth) |
| **Key platforms** | GitHub, arXiv cs.*, ProductHunt, TechCrunch, Substack (tech newsletters), Stack Overflow |
| **Decision cycle** | Personal: minutes (individual sub); Enterprise: 1-3 months (team tool purchase) |
| **Content preference** | Text-heavy (technical blogs, preprints, newsletters) + video (tutorials, conference talks) |
| **AI adoption rate** | Highest of any demographic: <25: 17%, 25-34: 15% weekly use for news; ChatGPT 44% US adult adoption |
| **WTP pattern** | Personal: $5-$20/mo (Substack, ChatGPT Plus); Enterprise: $20-$200/user/mo (Copilot, IDE plugins) |
| **Avg AI subscriptions** | 4 paid AI tools (~$66/mo total); 67% consider AI subscriptions "most important" (Bango 2025) |

##### Domain 4: Enterprise SaaS / B2B Cloud & Software

| Attribute | Description |
|-----------|-------------|
| **Buyer persona** | CIO/CTO/IT director + business line head (dual signature); typical 5-10 stakeholders |
| **Decision cycle** | Median 3-6 months; large enterprise 12-18 months |
| **Budget** | Enterprise software +15.2% YoY (Gartner 2025); ~9pp from price increases, ~6pp real net-new, almost all flowing to AI applications |
| **Geography** | North America ~60% of global SaaS spend, EMEA ~25%, APAC ~12% |
| **Typical ACV** | $50K-$500K (SaaS); significantly higher than consumer subscriptions |
| **Renewal rate** | >90% annual; net retention 110-130% |
| **Purchase criteria** | ROI, TCO, compliance, security, SLA guarantees; price elasticity is low |
| **AI adoption** | 78% of US enterprises plan to deploy AI agents (2026); 51% already in production (Ringly 2026) |
| **Content need** | Competitive intelligence, market analysis, regulatory updates, AI/tech trend tracking |

##### Domain-Level WTP Comparison (C端 vs B端)

| Dimension | Financial (C) | Education (C) | Tech/Dev (C) | Enterprise SaaS (B) |
|-----------|:------------:|:------------:|:------------:|:------------------:|
| **Decision mode** | Minutes-days | Minutes-days | Minutes | 3-18 months |
| **Monthly ARPU** | $4-$2,665 | ¥8-¥33 | $5-$20 | $4K-$42K |
| **Churn rate** | 4-16%/mo | 25-55% | low | <10%/yr |
| **Price sensitivity** | Medium | High | Medium | Low |
| **Key driver** | Information edge | Career advancement | Productivity | ROI & compliance |
| **Agent readiness** | High (86% Wind users) | Low | Medium | High (78% enterprises) |

Pricing is defined by product type and tier, not by platform features:

| Tier | RAW Products | PROCESSED Products | Platform Access |
|------|-------------|-------------------|----------------|
| **Free (dev preview)** | 1 domain, 1 RAW feed (limited to 50 items/mo) | Digest only (weekly, no customization) | CLI + MCP, BYOK |
| **RAW Pro** ($50-200/mo) | Unlimited domains, unlimited RAW feeds, API access, bulk export (JSON/CSV/SQLite) | Digest (daily/weekly + custom instructions), basic reports | CLI + MCP, BYOK, priority collection |
| **PROCESSED Pro** ($500-2,000/mo) | All RAW Pro features | Full product suite: thematic reports, alert streams, tutorials, presentations, custom templates, scheduled delivery | CLI + MCP, BYOK, priority collection + processing, human review on delivery |
| **Enterprise** (Custom) | All features dedicated infrastructure | White-label products, custom SLAs, dedicated delivery channels, editorial review, compliance | Managed hosting, SLA guarantees, SSO |

#### Domain-Level Pricing Benchmarks (Market Reference) (NEW)

> *Actual market pricing across domains, sourced from the global information payment research report. These serve as reference anchors for AutoInfo's product pricing strategy.*

| Domain | Entry-Level | Mid-Tier | Premium | Ultra-Premium (Enterprise) | Notes |
|--------|-----------|---------|---------|--------------------------|-------|
| **Financial Terminal** | Alpha Vantage Premium: $49.99/mo | 同花顺 iFinD: ~¥8,000/yr | Wind: ~¥680/mo (retail); ¥数万-数十万/yr (institutional) | Bloomberg: $2,665/user/mo ($32K/yr); Refinitiv: $2K-$8K+/user/mo | Largest spread: $50-$32K+/mo |
| **Business News/Deep Analysis** | NYT Basic: $17/mo | WSJ: $44.99/mo; 财新: ¥498/yr | FT: £75/mo ($100+/mo); The Information: $199/yr | Bloomberg Terminal: $32K/yr (includes news) | WTP 5-10× for financial vs general news |
| **Professional Knowledge** | Medium: $5/mo | 知乎盐选: ~¥19/mo; 得到: ¥199-365/yr | Coursera Plus: $59/yr; DataCamp: $25/mo | Coursera Enterprise: ~$1,000/org/yr; Degreed: custom | B2B ARPU significantly higher |
| **AI Tools** | ChatGPT Plus: $20/mo; Perplexity Pro: $20/mo | Claude Pro: $20/mo; Gemini Advanced: $20/mo | ChatGPT Team: $25/user/mo; Copilot Pro: $30/mo | ChatGPT Enterprise: custom; Claude Max: $200/mo | AI subs averaging 4 tools/person = ~$66/mo |
| **Developer/Tech** | GitHub Free | Substack paid newsletters: $5-15/mo | Stack Overflow Teams: $12/user/mo | GitHub Enterprise: $21/user/mo | Low ARPU but high volume |
| **Academic Research** | arXiv: Free | PubMed: Free; OpenAlex: Free | IEEE: $30+/mo (personal); Scopus: institutional | Elsevier/SciVal: $10K-$100K+/yr (institutional) | Open access is the norm; premium is institutional |
| **Newsletter/Creator** | Substack free | Substack paid: $5-15/mo | 52 newsletters earning $500K+/yr | Substack Pro advances: $100K-$500K | Creator-led model with platform take rate 10% |
| **Music/Video Streaming** | Spotify Free (ad-supported) | Spotify Premium: $10.99/mo; Netflix Standard: $15.49/mo | Netflix Premium: $22.99/mo; YouTube Premium: $13.99/mo | Apple One Premier: $39.95/mo (bundle) | Entertainment ≠ news/info; different buyer psychology |

#### Key Pricing Insights for AutoInfo

| Insight | Data Point | Implication |
|---------|-----------|-------------|
| **B2B vs B2C price ratio** | $50K-$500K ACV (B2B SaaS) vs $4-$45/mo (C端 subscriptions) — ratio of **100-1000×** | AutoInfo should prioritize B2B PROCESSED products for revenue |
| **Subscription fatigue ceiling** | 47% churn rate (2026, up from 31% in 2024); 87% Gen Z fatigue | Discounts boost conversion by **3.35×** (Journalism Studies 2025); free tier + discount strategy critical |
| **Bundle effect on retention** | Nordic +Alt bundle churn: **0.7%** vs single publication: **16.4%** — LTV gap **26×** | Cross-domain/product bundles are a retention super-weapon |
| **AI premium pricing** | AI users pay 4× subscriptions ($66/mo avg); 67% call AI subs "most important" | Agent-mediated delivery justifies premium pricing |
| **Global market saturation** | Top 20 wealthy nations avg 18% news payment rate; 3 years flat | Growth comes from new domains (financial/legal/tech), not general news |

### 7.4 Product Type Economics

| Dimension | RAW Products | PROCESSED Products |
|-----------|-------------|-------------------|
| **Margin** | Low (commodity — information is available elsewhere) | High (differentiated — synthesis and analysis add value) |
| **Volume** | High (thousands of items per domain) | Low (handful of reports per period) |
| **Automation** | Fully automated (collect → process → deliver) | Semi-automated (LLM generates, human reviews, then delivers) |
| **Delivery** | API endpoints, webhook streams, bulk export | Email digests, scheduled push, REST API, webhook |
| **Customer retention** | Low (switching to another feed is easy) | High (custom analysis creates switching cost) |
| **Quality criticality** | Freshness + completeness | Accuracy + insight + presentation |
| **Gate enforcement** | Soft gates (G1-G3, G5) — flag and filter | Hard gates (G0, G4) + delivery gates (D1-D3) — block on failure |

**Strategic implication**: PROCESSED products are the high-margin revenue driver. RAW products are the moat — they feed the PROCESSED pipeline and make it hard for competitors to replicate the same depth of domain coverage.

### 7.5 Content Sourcing & Agent Ecosystem Strategy (NEW)

> *AutoInfo's strategy for content acquisition, API access, AI agent integration, and navigating the polarized data accessibility landscape.*

#### 7.5.1 Content Accessibility Tier System

Based on the API capability matrix (F07b), all potential sources fall into three tiers:

| Tier | Definition | Examples | AutoInfo Approach |
|------|-----------|---------|-----------------|
| **Tier A: Open Access** (Free/Open API) | Public APIs with generous rate limits, no payment required | arXiv, PubMed, OpenAlex, CrossRef, Semantic Scholar, FRED, GitHub, YouTube (free tier), Reddit (non-commercial) | **First-class citizens**. Default pre-configured sources. Full automation with no cost barrier. |
| **Tier B: Freemium/Low-Cost** (Free tier with paid premium) | Usable free tier exists; premium unlocks higher limits or additional data | Alpha Vantage ($49.99/mo premium), AP ($100/min key), NYT (10 req/min free), Substack (free metadata) | **Default pre-configured at free tier**. Premium tier available as user-configured upgrade. Agent can suggest upgrade when limits hit. |
| **Tier C: Paid Only** (No free access) | Requires paid subscription or institutional license | Bloomberg ($2,665/user/mo), Wind (¥数十万/yr institutional), Reuters Connect ($2K-$15K/mo), 知乎 (no API), 微信公众号 (no API) | **Not pre-configured**. Supported as user-configured sources under F08. User provides their own API key/access credentials. AutoInfo provides the handler. Agent warns about cost when user adds these. |

**Strategic principle**: AutoInfo's default demo domains ship with Tier A and Tier B sources exclusively. Tier C sources are available for user-configured domains where the expected ROI justifies the cost. This ensures the free/dev tier remains functional without requiring users to spend on data access.

#### 7.5.2 AI Agent Integration Strategy

AutoInfo is designed as an **agent-native content supply platform**. As the research report confirms, "Agent-mediated reach" is Reuters Institute's #2 theme for 2026, with 78% of US enterprises planning to deploy AI agents.

**AutoInfo's role in the Agent ecosystem**:

| Layer | AutoInfo's Role | Technical Implementation |
|-------|----------------|------------------------|
| **Content supply** | Provide structured, source-verified content that agents can consume via MCP | All KB data accessible via MCP tools: `search_knowledge_base`, `get_kb_entry`, `export_kb` |
| **Agent-triggered collection** | Agents trigger collection on demand, not just scheduled | `collect_sources(context="agent_query: user asked about X")` — collection tied to agent interaction |
| **Agent-native output delivery** | PROCESSED products delivered as tool results, not just email/files | Agent calls `generate_digest()` → returns structured dict → agent formats for user |
| **RSS Feed as product output** | RAW and PROCESSED products exportable as RSS/Atom feeds for agent and human subscription | `export_kb(format="rss")` → returns RSS feed XML for any domain/topic/collection |

**Market context — content licensing landscape** (data from research report):

| Transaction | AI Company | Publisher | Value | Significance |
|------------|-----------|-----------|-------|--------------|
| Landmark AI deal | OpenAI | News Corp (WSJ, Barron's, etc.) | **$250M / 5 years** | Largest known deal; sets market benchmark |
| AI partnership | OpenAI | Axel Springer (Politico, BI) | ~$13M/yr × 3yr | First "full-stack" deal including paywalled content |
| Enterprise license | OpenAI | Financial Times | $5-10M/yr | Paywalled financial news + attribution |
| Data licensing | Google | Reddit | **$60M/yr** | API-based training data paradigm |
| AI training deal | Amazon | NYT | **$20-25M/yr** | For Alexa/Rufus, excludes ChatGPT/Claude/Perplexity |
| Revenue share | Perplexity | 100+ publishers | 80% of Comet Plus ($5/mo) pool = **$42.5M** | Agent→publisher revenue sharing model |

**Implication**: The AI training data licensing market has matured from pilot (2023-2024) to established revenue stream (2025-2026). AutoInfo's position as an agent-native platform aligns with this trend — content collected and processed by AutoInfo can serve as both human-readable products and agent-consumable structured data.

#### 7.5.3 Content Licensing Strategy for AutoInfo

| Product Type | Licensing Model | Target Customer |
|-------------|----------------|----------------|
| **RAW Products (Tier A sources)** | Included in subscription — no additional licensing cost | All tiers |
| **RAW Products (Tier B/C sources)** | Pass-through: user pays source cost + AutoInfo service fee | RAW Pro / Enterprise |
| **PROCESSED Products (Tier A)** | Included — LLM synthesis of open-access content | PROCESSED Pro |
| **PROCESSED Products (Tier B/C)** | Premium tier — value-add on paid data sources | Enterprise |
| **AI Training Data License** (v2+) | Separate data license agreement — customer trains models on AutoInfo-curated datasets | Enterprise / Strategic Partners |

#### 7.5.4 Chinese Content Ecosystem Boundary

The research report identifies a critical structural gap:

| Aspect | Chinese Ecosystem | Western Ecosystem | Implication |
|--------|-----------------|------------------|-------------|
| **Official MCP support** | **Zero** — 知乎, 得到, 微信公众号, B站, 抖音, 小红书, 微博 have NO official MCP | **Growing** — Reuters MCP (2026-07), Wind MCP, Thomson Reuters Westlaw MCP | Chinese content platforms cannot be reliably accessed via agent protocols |
| **API accessibility** | Nearly all Chinese platforms lack open APIs or have restrictive paid APIs | Many Western platforms offer free/open APIs (academic, selected news, social with rate limits) | Chinese-language content tracking requires alternative approaches |
| **Anti-crawl posture** | Strongest globally — TLS fingerprinting, device fingerprint, CAPTCHA, dynamic tokens | Cloudflare/Akamai common but less aggressive for public content | Web scraping Chinese platforms is high-risk and low-reliability |
| **AI regulation** | 生成式AI暂行办法 (2023/8); training data must be legally sourced, IP-compliant | EU AI Act (2025/8 GPAI obligations); US litigation-driven (NYT v. OpenAI etc.) | Compliance requirements differ significantly |

**AutoInfo's strategy for Chinese content**:
1. **Track Chinese-language open-access sources** (arXiv Chinese authors, CNKI open-access, government open data, WeChat public account RSS-like aggregators where legally available)
2. **Support user-configured premium Chinese sources** (用户自行提供 财新/知网/得到 订阅凭据)
3. **Leverage Chinese AI agent platforms** (字节扣子Coze, 腾讯元器) for content distribution rather than collection
4. **The "财新 × Kimi" model** (Kimi answers cite Caixin with attribution + links) as the reference for Chinese content agent partnership

### 7.6 Regional Strategy & Regulatory Compliance (NEW)

> *Regional market characteristics, user behavior differences, and regulatory requirements that inform AutoInfo's go-to-market strategy.*

#### 7.6.1 Regional Comparison Matrix

| Dimension | 🇺🇸 North America | 🇪🇺 Europe | 🇨🇳 China | 🇯🇵🇰🇷 Japan/Korea |
|-----------|:----------------:|:---------:|:---------:|:---------------:|
| **Global SaaS spend share** | ~60% | ~25% | ~8% | ~5% |
| **News payment rate** | 22% (US) | Norway 40%, Sweden 31%, UK 8%, Germany 13%, France 11% | No unified paywall; skews toward knowledge payment (¥350B market) | Japan 9%, Korea low (music 5% — global lowest) |
| **Top content format** | Video (72% watch news video 2025, up from 55% in 2021) | Text (55% average); German 18-24: 49% text, 33% video | Short video (抖音 7.1B DAU); AI apps (6.02B users) | Text (Japan); Mobile-first |
| **AI news adoption** | 6% (flat 2025→2026); ChatGPT 44% adult adoption | 4-5% (UK, FR, DE flat); Spain doubled YoY | AI users 602M (42.8% penetration);豆包 382M MAU | Korea 14% (doubled YoY); Japan <5% |
| **AI Agent adoption** | 78% enterprises plan to deploy; 51% in production | EU AI Act compliance driving structured adoption | ByteDance Coze, Tencent Yuanshi; zero official MCP | Korea leading Asia in AI news |
| **Key regulation** | Litigation-driven (NYT v. OpenAI, CNN v. Perplexity) | EU AI Act (GPAI obligations since 2025/8/2); DSM Directive Art. 4 opt-out | 生成式AI暂行办法; 网信办 content review; training data compliance | Japan AI guidelines; Korea AI Basic Act |
| **Payment preference** | Credit card; PayPal; Apple Pay | SEPA; credit card; PayPal | WeChat Pay; Alipay; bank transfer | Credit card; convenience store; carrier billing |
| **Subscription behavior** | 89% underestimate monthly sub spend ($273/mo avg); 47% churn rate (2026) | Lower churn in Nordic (bundle 0.7%); higher in UK | Knowledge payment growing;得到 35% payment conversion | Long-tail subscriptions; low churn |

#### 7.6.2 Regulatory Compliance Requirements

**EU AI Act — GPAI obligations (effective 2025/8/2)**:
- AutoInfo must respect TDM opt-out signals (robots.txt, `llms.txt`, machine-readable rights reservations)
- Training data for any GPAI model using AutoInfo-curated data must have copyright policy and respect opt-out
- **Required tool**: `check_source_compliance(source_url)` — verify opt-out status before collection

**China — 生成式人工智能服务管理暂行办法**:
- Training data must be legally sourced, IP-compliant
- Personal information in training data requires consent
- **Implication**: AutoInfo's Chinese-language collection must stay within open-access, properly licensed sources

**US — Litigation-driven**:
- No comprehensive federal AI law; court decisions set precedent
- NYT v. OpenAI (2023-12, ongoing): fair use defense for training data challenged
- **Implication**: AutoInfo should prioritize opt-in, licensed data sources for any commercial AI training use case

#### 7.6.3 Regional Go-to-Market Priority

| Priority | Region | Rationale | AutoInfo Readiness |
|----------|--------|-----------|-------------------|
| 🥇 **Primary** | North America + Western Europe | Highest WTP; mature subscription economy; English-dominant content readily available via open APIs | ✅ Default language; most sources Tier A/B |
| 🥈 **Secondary** | China (outbound: Chinese → English; enterprise Chinese content) | Largest knowledge payment market (¥3,508B); growing AI user base (602M); weak API access = less competition | ⚠️ Chinese sources Tier C (user-configured);适合追踪中英文内容的跨语言领域 |
| 🥉 **Tertiary** | APAC (Japan/Korea/SEA) | Korea fastest AI news growth (+100% YoY); Japan low payment but high trust | ⏸ Future expansion |

### 7.7 Market Trends & Business Model Innovation (NEW)

> *Key industry inflection points and emerging business models that validate AutoInfo's approach and inform future feature priorities.*

#### 7.7.1 2024-2026 Key Inflection Points

| Trend | Data Point | Impact on AutoInfo |
|-------|-----------|-------------------|
| **Social/video surpasses direct access** | US social/video news 54% > websites 51% (2026, Reuters Institute) | Agent-mediated distribution becomes critical — users won't visit websites, content must go to them |
| **Search referral collapse** | Google publisher traffic -33% (2025); AI Overviews CTR decline up to 89%; zero-click queries 60% | AutoInfo's "collect once, deliver anywhere" model insulates against platform dependency |
| **Agent-mediated reach** | Reuters Institute #2 theme for 2026; 78% US enterprises deploying agents | AutoInfo's agent-native architecture is future-proof by design |
| **AI training data licensing** | Reddit-Google $60M/yr; News Corp-OpenAI $250M/5yr — new revenue category emerged 2024-2026 | RAW products have AI training data licensing as an additional monetization path |
| **Publisher "double bleed"** | Search traffic -33% + AI clickback rate 4% (vs search 19%, social 17%) | Publishers need AutoInfo-style tools to create their own AI-mediated distribution |
| **Subscription fatigue acceleration** | 31%→47% churn (2024→2026); 87% Gen Z fatigue; discount lifts conversion 3.35× | Free tier + discount-first strategy essential; bundle pricing (Nordic 0.7% churn vs single 16.4%) should be default |
| **Bundling as retention super-weapon** | Nordic +Alt bundle 0.7% churn vs single publication 16.4% — LTV difference **26×** | Cross-domain/product bundles should be AutoInfo's default pricing architecture |

#### 7.7.2 Business Model Innovation Reference

| Model | Example | Mechanism | Application to AutoInfo |
|-------|---------|-----------|----------------------|
| **Agent revenue share** | Perplexity Comet Plus ($5/mo, 80% to publishers = $42.5M pool, 100+ publishers) | Agent subscription → agent queries publisher content → publisher gets majority of revenue | Future Agent tier: AutoInfo as "content supply" for third-party agents, with usage-based revenue share |
| **Token/credit economy** | Wind Alice personal: 100 yuan = 10,000 credits; first purchase bonus 10% | Points-based metering → consumption-based billing | Alternative payment model for agent-mediated access: "pay per KB entry consumed" |
| **Effectiveness-based pricing (RaaS)** | 蚂蚁数科RaaS; e签宝智能合同Agent: ¥1亿+/yr revenue | Price tied to measurable business outcome (GMV share, ROI) | Enterprise tier: price by items collected, time saved, or analysis quality |
| **API licensing** | Reddit-Google $60M/yr; OpenAI 14+ publisher deals | Fixed annual fee for API access + training data rights | Enterprise RAW tier: bulk data access + AI training rights |
| **Content bundling cross-sell** | NYT bundle: 6.48M subscribers (ARPU $12.67 vs single $3.47); +24.3% YoY | Multiple products sold as a package at premium but per-product discount | Domain bundles: "Financial + Tech + Medical" at package discount — drives retention (bundle churn 0.7% vs single 16.4%) |
| **Human review premium** | 43% comfort if AI + human-supervised vs 12% if purely AI-generated (Reuters 2025) | Premium tier includes human editorial review | PROCESSED Pro includes human QA gate; justifies 4-10× price over fully automated RAW |

#### 7.7.3 Content Format Commercialization Data

| Format | Market Data | AutoInfo Support | Commercial Potential |
|--------|-----------|-----------------|---------------------|
| **Audio digest** | Avg price ¥30-80, repurchase rate 41% | ✅ Supported — TTS audio digest via `format='audio'` + audiobook (`format='audiobook'`) shipped | 🔴 High — 14% user preference, 42% payment intent for news podcasts |
| **Short video summary** | 75.7% of paid learning sessions (2022); 72% user penetration (2024) | ❌ Not yet supported (text-only) | 🟡 Medium — requires TTS + video generation pipeline |
| **Newsletter (email)** | Substack 8.4M paid (+68%); 52 newsletters earning $500K+/yr | ✅ SMTP sending supported; Agent-generated digest | ✅ High — core delivery channel |
| **RSS Feed as product** | RSS adoption +34% YoY (2026); 400M+ podcasts distributed via RSS | ✅ Supported — RSS 2.0 delivery channel (C11 podcast RSS) + `export_kb(format='rss')` shipped | ✅ High — standard format for both human and agent consumption |
| **Structured data API** | Bloomberg $2,665/user/mo; Alpha Vantage $49.99/mo; Wind ¥680/mo | ✅ REST API + webhook + bulk export | ✅ Core RAW product delivery |
| **Agent-native output** | ChatGPT 10B MAU; Perplexity 100M+ MAU (2026 Q2) | ✅ MCP tools for KB search + digest generation | ✅ Highest growth channel — agent-mediated delivery is the 2026 inflection point |

#### 7.7.4 The Shift: From "People Find Information" to "Agent Finds Information"

```
Traditional (SEO era):
  Publisher website → Google Search → User click → Read (ads/subscription wall) → Return visit

Current (AI summary era):
  Publisher API/feed/RSS → AI Agent (ChatGPT/Perplexity/Claude/Gemini) → User prompt → Summary/answer (attribution + link)

AutoInfo's Position:
  Source (Tier A/B/C) → AutoInfo Collection → KB Pipeline (Raw→Draft→Wiki) 
    → RAW Products (API/Webhook/Export) → Agent/Human consumption
    → PROCESSED Products (Digest/Report/Tutorial) → Agent-mediated delivery
    → AI Training Data License (v2+) → Enterprise model training
```

**Key differences** between SEO era and Agent era:

| Dimension | SEO Era | Agent Era | AutoInfo Advantage |
|-----------|---------|-----------|-------------------|
| **User identity** | Publisher-owned (cookies, registration) | Platform-owned (OpenAI/Perplexity/Google) | AutoInfo agents operate on behalf of the user; identity stays with subscriber |
| **Ad inventory** | Publisher web pages (banners, native) | Zero (LLMs don't display publisher ads) | AutoInfo's product model doesn't depend on advertising |
| **Brand exposure** | Full-article reading (high) | Summary reading (low) | PROCESSED products restore brand value through curated, attributed synthesis |
| **Revenue model** | Subscription + advertising (high CPM) | One-time license fee ($1-50M/yr) + micro revenue share (Comet: 80% back) | Multiple revenue streams: subscription + licensing + future revenue share |
| **Publisher control** | Full (SEO optimization, paywall) | Low (AI decides what to cite) | AutoInfo gives publishers control over how their content is packaged for agent consumption |
| **Data回流** | Complete (UTM, click tracking) | Almost none (citation count only) | AutoInfo maintains full provenance + usage analytics |

---

### 7.8 Scope Note: End-User Uniformity

> **All end-user types are treated uniformly.** The persona-based differentiation described in this document's market analysis (e.g., "researcher" vs "clinician" vs "executive" vs "student" in §7.5.2, regional demographics in §7.6) is **market research reference only**. The AutoInfo product itself applies **no demographic, role-based, or accessibility-based segmentation** to end-user profiles.
>
> The `target_audience` parameter available on digest and report generation is a **content-level output feature** that adjusts LLM tone and depth — it is not a user-profile attribute, not a gating mechanism, and not a segmentation strategy. All end users, regardless of their role, region, or accessibility needs, receive the same product capabilities.
>
> This is a deliberate architectural decision: AutoInfo remains a general-purpose information platform. Market-specific variations (persona preferences, payment methods, regulatory requirements, accessibility standards) are handled by the **domain configuration layer** (topic sets, extraction schemas, output templates) and by the **delivery channel's own capabilities**, not by differentiated end-user profiles.
