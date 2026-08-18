# Director User Guide: Working with the AutoInfo Agent

> **Audience**: The human commander who tells the agent what to do.
> **Purpose**: Understand how to communicate intent, review work, and stay in control.
> **Principle**: You direct. The agent executes. AutoInfo serves.

---

## 1. Overview & Role Definition

### Who Is the Director User?

You are the human in charge. You do not touch AutoInfo directly. You speak to an AI agent in natural language -- English, Chinese, or whatever works for you -- and the agent translates your intent into precise MCP tool calls that drive the AutoInfo platform.

AutoInfo has three distinct user roles. This document is for the first one:

| Role | Description | Interface | Example |
|------|-------------|-----------|---------|
| **Director User** (人类指挥者) | **You.** Gives high-level intent in natural language. Never touches AutoInfo directly. The agent is your interface. | Natural language conversation with the agent | "帮我追踪本周辅助生殖领域的重要论文，按创新程度排序，出一份简报" |
| **Direct User** (Agent / 直接执行者) | The AI agent that executes commands. Translates your NL into MCP tool calls, runs collection pipelines, generates output, reports results. | MCP tools (146 tools, 35 categories). CLI is fallback. | Calling `collect_sources()`, `generate_digest()`, `search_knowledge_base()` |
| **End User** (最终用户 / 付费客户) | The paying customer who consumes the knowledge products you produce. They receive digests, reports, data feeds. You never talk to them through AutoInfo -- the system delivers to them. | Email digests, Telegram messages, WeChat pushes, API feeds | A pharmaceutical company receiving "IVF Research Weekly" via email |

See `docs/dev/founder-expectations.md` SS1.3 for the full role specification.

### What Makes This Relationship Different

- **You do not click buttons.** There is no dashboard you operate. You talk to an agent who does the clicking.
- **You do not run commands.** The agent handles `autoinfo collect`, `autoinfo process`, etc. You can use CLI as a fallback, but the primary channel is conversation.
- **You stay strategic.** The agent handles tactical execution: finding sources, configuring topics, running pipelines, generating output. You decide the direction.
- **You are the final gate.** Some operations are human-only: permanent deletion, removing domains or sources. The agent cannot do these without you. (KB Draft→Wiki promotion is **not** in this class — the agent promotes as part of the production pipeline, by design.)

---

## 2. Operating Model

### The Interaction Chain

```
You (Director) ──── natural language ────> Agent (Direct User)
                                                 │
                                          translates to MCP tool calls
                                                 │
                                                 v
                                          AutoInfo MCP Server
                                                 │
                                          executes: collect, process,
                                          search, generate, deliver
                                                 │
                                          returns structured results
                                                 │
                                                 v
                                          Agent (Direct User)
                                                 │
                                          summarizes, interprets,
                                          asks clarifying questions
                                                 │
                                                 v
                                   You review, iterate, or approve
```

The flow is always the same:

1. **You speak** -- "I want to track AI commercial news about enterprise pricing"
2. **Agent translates** -- calls `add_topic()`, `collect_sources()`, `process_collection()`
3. **AutoInfo executes** -- fetches from sources, runs LLM extraction, stores results
4. **Agent reports** -- "Found 8 relevant articles. 3 mention pricing changes. Here is a summary."
5. **You decide** -- "Generate a digest. Focus on OpenAI and Anthropic." or "Not relevant, try different keywords."

### What the Agent Can Do (In Brief)

The agent has 146 MCP tools organized into 35 categories. Everything AutoInfo can do, the agent can do on your behalf:

- Configure domains, sources, and topics
- Run collection and processing pipelines
- Search and query the knowledge base
- Generate digests, reports, tutorials, presentations
- Send emails, configure cron schedules
- Manage keywords, alert rules, and quality gate thresholds
- Track costs and audit operations

See `AGENTS.md` for the full tool catalog.

### What the Agent Cannot Do (Human-Only Operations)

These operations require your direct action. The agent will tell you when they are needed and wait for your instruction:

- Promote Draft-to-Wiki is **agent-driven** (`promote_kb_draft`, no human gate — the KB is a production database). Permanent deletion and removing domains/sources require you.
- Permanently delete or purge data
- Remove sources or domains
- Run `autoinfo init` (but can run `init_project` MCP tool)
- Manage API keys
- Directly edit `.autoinfo/config.yaml`

---

## 3. Interaction Lifecycle

Every task follows a six-phase lifecycle. You and the agent move through these phases together.

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │                      INTERACTION LIFECYCLE                          │
 ├──────────────────────────────────────────────────────────────────────┤
 │                                                                      │
 │  1. INTENT CAPTURE                                                   │
 │     You express a goal or need                                       │
 │     ↓                                                                │
 │  2. AGENT CONFIRMATION                                               │
 │     Agent clarifies scope, asks for missing info, or confirms plan   │
 │     ↓                                                                │
 │  3. EXECUTION                                                        │
 │     Agent translates intent to tool calls, runs pipeline             │
 │     ↓                                                                │
 │  4. REVIEW                                                           │
 │     Agent presents results. You inspect, ask questions, give feedback│
 │     ↓                                                                │
 │  5. ITERATION                                                        │
 │     You refine. Agent adjusts. Repeat 3-4 until done.                │
 │     ↓                                                                │
 │  6. COMPLETION                                                       │
 │     You approve. Agent summarizes what was done.                     │
 │                                                                      │
 └──────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Intent Capture

You express what you want. This can be broad or specific.

**Broad intent**: "I want to stay on top of AI commercial news."
**Specific intent**: "Set up a daily digest of IVF breakthroughs from PubMed, focus on clinical trials, send it to my email every morning."
**Chinese intent**: "帮我追踪本周辅助生殖领域的重要论文，按创新程度排序。"

The agent listens for the core elements: domain, topic, sources, output format, schedule, audience.

### Phase 2: Agent Confirmation

The agent does not blindly execute. It first confirms understanding, fills gaps, and presents a plan.

> **You**: "I want to stay on top of AI commercial news."
>
> **Agent**: I can set that up. Let me confirm a few things:
>
> - **Domain**: `ai-commercial` is already configured with sources (TechCrunch RSS, ProductHunt API, Crunchbase, LMSYS). Should I use this domain?
> - **Topics**: I see AI commercial news could cover: enterprise pricing, startup funding, product launches, competitive moves. Which topics interest you?
> - **Output**: I can generate a daily or weekly digest. What format do you prefer?
> - **Delivery**: Email, or just for review in chat?
>
> Or you can say "just set up something reasonable and show me" and the agent will use defaults.

This phase avoids wasted execution. The agent is designed to ask, not assume.

### Phase 3: Execution

The agent runs the tool calls. You see progress updates:

- "Checking source health for ai-commercial... all 4 sources healthy."
- "Collecting from 4 sources... 18 new items found."
- "Processing collection with LLM extraction... quality gates passed."
- "Draft digest generated. Reviewing before presenting to you."

Execution can be async. Long operations (collection, processing, report generation) return a `job_id`. The agent polls progress and reports back when done. See `AGENTS.md` "Monitor long-running collection or processing".

### Phase 4: Review

The agent presents results in a readable format. This is where you evaluate:

- **Collection results**: "Found 18 items, 12 passed quality gates, 6 were filtered as duplicates or low relevance."
- **Summaries**: "Here are the top 5 articles ranked by relevance to IVF breakthroughs."
- **Drafts**: "3 Draft entries created from Raw. Would you like to review before promoting to Wiki?"
- **Digests**: "Weekly digest generated. Key topics: endometriosis biomarkers, embryo grading AI, ovarian stimulation protocols."

You can dive deeper at any point: "Show me the full text of article #3" or "Search for 'mitochondrial replacement therapy' in the new items."

### Phase 5: Iteration

You refine. The agent adjusts. Common iteration patterns:

- **Refine scope**: "This is too broad. Narrow to clinical trials only."
- **Change output**: "Generate a report instead of a digest. Format as PDF."
- **Adjust quality**: "Set relevance threshold higher -- only show items with score above 80."
- **Redo with different params**: "Force re-collection, skip dedup this time."
- **Translate**: "Localize this to Chinese for my end users."

Each iteration loops back through phases 3-4.

### Phase 6: Completion

You approve. The agent summarizes:

> **Agent**: All done. Here is what I set up:
>
> - Topic "IVF Clinical Trials" added to medical-research domain
> - Daily collection scheduled at 8 AM
> - Weekly digest generated every Monday, sent to your email
> - 3 Draft entries awaiting your Wiki promotion
>
> To adjust later, just tell me. For example: "Change the digest to bi-weekly" or "Add a new source for clinical trial data."

---

## 4. Communication Patterns

### 4.1 Explicit Instruction

You know exactly what you want and say it clearly.

> **You**: "Set up a daily IVF digest for the medical-research domain. Send it to my email zhang@example.com at 8 AM every weekday. Focus on clinical trials and include DOI links."

The agent has enough information to act without asking many questions. It confirms the plan and executes.

**When to use**: You have a clear outcome in mind. You know the domain, topic, format, and delivery.

### 4.2 Implicit Intent

You have a general need but not a precise plan. The agent must help you scope it.

> **You**: "I want to stay on top of AI commercial news."

The agent should not just start collecting. It should pause and clarify:

> **Agent**: I can help with that. Let me understand what you need:
>
> - We have an `ai-commercial` domain configured with 4 sources. Does that cover what you need?
> - Are you interested in: enterprise pricing, product launches, funding rounds, competitive moves?
> - How often do you want updates? Daily, weekly?
> - Where should I deliver the updates?

**When to use**: You have a vague goal. You want the agent to help shape it into a concrete plan.

**What the agent should do**: Never guess silently. Ask targeted questions. Propose a concrete plan for your approval before executing.

### 4.3 Preference Setting

You tell the agent your preferences. The agent should remember them for the session (and ideally across sessions).

> **You**: "Always prefer Chinese-language sources for the financial domain."

The agent should:

1. Acknowledge the preference: "Noted. For the financial-intelligence domain, I will prioritize Chinese-language sources."
2. Apply it consistently in this session: when listing sources, filtering results, generating output.
3. Reference it proactively: "I found 5 English articles and 3 Chinese articles. Would you like me to summarize the Chinese ones first?"

> **You**: "When presenting medical research, always show the journal impact factor and DOI."

> **You**: "I prefer weekly digests over daily. Saves my inbox."

**When to use**: You have recurring preferences. Telling the agent once is more efficient than repeating them each time.

### 4.4 Override

You want to change default behavior for a specific task. Overrides are one-time exceptions, not permanent preferences.

> **You**: "Force full re-collection for the tech domain. Skip dedup this time."

The agent adjusts the parameters: `collect_sources(domain="tech-ai-developer", skip_dedup=true, force_refresh=true)`.

> **You**: "For this digest, ignore the relevance threshold. Include everything from this week."

> **You**: "Do not send the email. Just show me the result in chat."

**When to use**: Default behavior is not what you need right now. You want an exception.

### 4.5 Escalation

The agent hits a boundary and needs your input. This can be:

- **Uncertainty**: "I found 3 possible domains that match 'AI'. Which one should I use?"
- **Error**: "PubMed API returned HTTP 503. All 4 sources failed. What should I do?"
- **Authorization needed**: "This would remove the 'tech-crunch' source from ai-commercial. Should I proceed?"
- **Ambiguous intent**: "You said 'track AI news' but we have both ai-commercial and tech-ai-developer domains. Which one?"

See Section 7 (Escalation Protocol) for the full decision tree.

> **You**: "Noted. Pause the PubMed source and try again tomorrow."

or

> **You**: "Use the ai-commercial domain. I'll set up tech-ai-developer later."

---

## 5. Human-Only Operations

These actions require **your explicit approval or direct execution**. The agent cannot perform them autonomously. The agent will inform you when they are needed and wait for your instruction.

### 5.1 Promote Draft to Wiki

The 4-tier KB pipeline is:

```
Collected Item → 01-Raw → 02-Draft → 03-Wiki
                     ↑          ↑           ↑
                  Auto-ingest  Agent can   Agent promotes
                  from source  create      Draft → Wiki via
                               Draft       promote_kb_draft
```

The agent creates Draft entries from Raw **and promotes Draft to Wiki itself** (`promote_kb_draft`, KB-tier guard, no human gate). AutoInfo's KB is a **database** for raw/processed data production — not a human-curated knowledge base (director decision 2026-08-08). Promotion is a production step in the agent's pipeline; requiring your approval on every promotion would cripple throughput. The agent will surface promotions in its reports so you can monitor quality, but you are **not** in the promote loop:

> **Agent**: "3 entries promoted to 03-Wiki this cycle (2 accepted, 1 flagged for re-check), 1 Draft rejected for missing sources:
>
> 1. **Endometrial Receptivity Biomarkers** -- promoted
> 2. **AI in Embryo Grading** -- promoted
> 3. **Ovarian Stimulation Protocols** -- flagged (low relevance), Draft retained"

You can still act if you disagree (quality oversight, not a gate):

- **Force-promote**: Tell the agent "Promote #3 anyway" -- agent calls `promote_kb_draft()`
- **Reject**: Tell the agent "Reject #3, needs more sources" -- agent calls `reject_kb_draft()`
- **Request changes**: Tell the agent "Re-process #2 before promotion" -- the agent edits the Draft

03-Wiki remains **append-only**: the agent cannot demote or delete Wiki entries; deprecation happens only on your explicit command.

See `docs/dev/specs/expectations.md` F20 and `docs/dev/specs/pipeline.md` for the full KB pipeline spec.

### 5.2 Permanent Deletion / Purge

Soft-delete (marking entries as deleted with recoverable status) is safe for the agent. Permanent physical deletion requires you.

The agent can:

- Call `soft_delete_entry(entry_id, reason)` -- marks as deleted, fully recoverable
- Call `restore_entry(entry_id)` -- recovers soft-deleted entries

But only you can:

- Run `autoinfo kb delete --purge <entry-id>` -- physically removes data
- Run `delete_user_data(user_id, scope)` -- GDPR compliance deletion
- Approve auto-cleanup of expired entries older than 30 days

See `docs/dev/specs/expectations.md` F47.

### 5.3 Remove Sources or Domains

The agent can add sources and add domains. But removing them requires your explicit instruction.

The agent will ask for confirmation:

> **Agent**: "Source 'TechCrunch RSS' has been failing for 7 days. Should I remove it from the ai-commercial domain?"

You say "Yes, remove it" and the agent proceeds. The agent will never delete sources or domains without your go-ahead.

### 5.4 Run `autoinfo init` (CLI)

The CLI `autoinfo init` is a human-only operation. The agent uses the `init_project` MCP tool instead, which is the equivalent for agent workflows. If you prefer to run init yourself, you use the CLI directly.

### 5.5 Manage API Keys

API keys are configured via environment variables (`AUTOINFO_LLM_API_KEY`) or `.autoinfo/config.yaml`. The agent never stores, generates, or transmits keys. If keys need to change, you do it directly.

See `docs/dev/required-api-keys.md` for the full catalog of required API keys and environment variables across all collectors and integrations.

### 5.6 Direct Config Editing

The agent does not modify `.autoinfo/config.yaml` directly. It uses MCP tools (`add_source`, `add_topic`, `set_gate_config`) for configuration changes. You can edit the config file directly if you prefer, but the agent will not.

---

## 6. Custom Instructions & Preferences

### Using Custom Instructions

When generating output (digests, reports, tutorials), you can pass instructions that shape the LLM output. The agent calls these tools with your custom instructions:

```
generate_digest(domain="medical-research", period="week",
    custom_instructions="Focus on clinical trials. Highlight novel biomarkers.
    Include DOI links. Write for a clinician audience.")
```

The `custom_instructions` parameter is available on these MCP tools:

| Tool | Custom Instructions Effect |
|------|---------------------------|
| `generate_digest` | Shapes what the digest emphasizes, what to include/exclude, writing style |
| `generate_report` | Defines structure, depth, focus areas, audience level |
| `generate_tutorial` | Sets learning objectives, complexity, prerequisites |
| `generate_presentation` | Controls slide content emphasis, narrative arc |
| `localize_content` | Specifies tone, formality level, regional variants |

See `docs/dev/specs/expectations.md` F29 and `docs/dev/specs/delivery.md`.

### Examples

> **You**: "Generate this week's digest. Focus on CRISPR applications in IVF. Write for a researcher audience."

Agent calls `generate_digest(domain="medical-research", period="week", custom_instructions="Focus on CRISPR applications in IVF. Audience: researcher.")`

> **You**: "Generate a tutorial on interpreting AMH levels for clinicians."

Agent calls `generate_tutorial(domain="medical-research", topic="AMH interpretation", audience="clinician")`

### Remembering Preferences

The agent can remember your preferences within a session and, depending on the platform, across sessions. Tell the agent your preferences once:

- "Always show DOI links in medical summaries."
- "Prefer Chinese output for the financial domain."
- "Weekly digests, not daily."
- "When I say 'track X', automatically set up collection and a weekly digest."

If the agent forgets, remind it. The agent should adapt within the conversation.

**Note**: AutoInfo does not have a persistent user preference database. Preferences are remembered by the agent's session context. For truly persistent preferences, you may want to document them in a shared location that your agent can read at the start of each session.

---

## 7. Escalation Protocol

The agent should know when to act and when to ask you. Here is the decision tree.

### Escalation Decision Tree

```
                          ┌─────────────────────────┐
                          │   User gives instruction │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │  Is the intent clear?    │
                          └────────────┬────────────┘
                         YES│          │NO
                    ┌─────────┐        │
                    │         │        │
          ┌─────────▼──┐     │        ┌▼──────────────────┐
          │ Has all    │     │        │ ASK: Clarify       │
          │ required   │     │        │ intent. Present    │
          │ parameters? │    │        │ options.           │
          └─────┬──────┘     │        └───────────────────┘
               YES│          │
          ┌─────────┐       │
          │         │       │
   ┌──────▼──┐     │       │
   │ Can     │     │       │
   │ agent   │     │       │
   │ do it?  │     │       │
   └──┬───┬──┘     │       │
      │   │        │       │
   YES│   │NO      │       │
  ┌─────┐│        │       │
  │     ││        │       │
  │ ┌───▼┐       │       │
  │ │ Is │       │       │
  │ │ it │       │       │
  │ │ an │       │       │
  │ │auth │      │       │
  │ │bound?      │       │
  │ └┬───┘      │       │
  │ YES│ │NO    │       │
  │ ┌──▼┐│     │       │
  │ │ASK││     │       │
  │ │for││┌────▼──┐   │
  │ │OK │││ ACT:  │   │
  │ │to │││Execute│   │
  │ │proc│││tools │   │
  │ │eed││└────┬──┘   │
  │ └───┘│     │      │
  │      │     │      │
  │      │  ┌──▼──┐   │
  │      │  │ Any │   │
  │      │  │error│   │
  │      │  │?    │   │
  │      │  └─┬┬──┘   │
  │      │   YES││NO  │
  │      │  ┌──▼┐│   │
  │      │  │ASKn│   │
  │      │  │how │   │
  │      │  │to  │   │
  │      │  │fix │   │
  │      │  └────┘   │
  │      │           │
  │      │           │
  │   ┌──▼───────────▼──┐
  │   │ REPORT results   │
  │   │ and ask for      │
  │   │ next action      │
  │   └─────────────────┘
  │
  └─────────────────────────────────────┘
```

### When the Agent Should Pause and Ask

The agent should always ask you when:

#### 1. Ambiguous Intent

The instruction could mean multiple things.

> **You**: "Track CRISPR developments."
>
> **Agent**: "CRISPR could apply to several domains. Our medical-research domain covers therapeutic applications, while tech-ai-developer covers gene editing tools. Which domain should I use? Or both?"

> **You**: "给我一份这周的简报."
>
> **Agent**: "I can generate a weekly digest. Which domain? medical-research, ai-commercial, or another?"

#### 2. Missing Information

The instruction lacks a required parameter.

> **You**: "Generate a digest."
>
> **Agent**: "Which domain? And for what period (daily, weekly, monthly)? Do you want it delivered to email or just shown here?"

#### 3. Error Conditions

Something went wrong during execution.

> **You**: "Collect from all medical research sources."
>
> **Agent**: "3 of 4 sources collected successfully. PubMed API returned an error (HTTP 503). Here are the details:
>
> - PubMed: failed (503) -- last success was 3 days ago
> - arXiv: 5 new items collected
> - CrossRef: 2 new items collected
> - CrossRef: 1 new item collected
>
> Options:
> 1. Retry PubMed now
> 2. Pause PubMed and continue with other sources
> 3. Investigate the PubMed error
> 4. Remove PubMed source
>
> What would you like to do?"

#### 4. Authorization Boundary

The action requires human approval.

> **Agent**: "The weekly collection found 25 duplicate items (same URLs as last run). I can skip them automatically. But 3 items are cross-source duplicates (same paper on PubMed and arXiv). Would you like me to merge them into a single Draft entry? I will keep both source URLs."

> **Agent**: "You asked me to remove the 'TechCrunch RSS' source from ai-commercial. This will stop all collection from that source. Should I proceed?"

#### 5. Quality Gate Block

A hard gate blocked the pipeline.

> **Agent**: "G4 (Factual Consistency) failed for 2 items after 3 retries. The LLM could not verify factual claims in the extracted summaries. These items have been moved to `collections/medical-research/_failed/`. Would you like me to investigate the extraction configuration, or skip these items?"

#### 6. Source Health Degradation

The agent detects a pattern of failures.

Following the agent-alerting pattern documented in `docs/dev/agent-alerting.md`:

> **Agent**: "Source 'PubMed API' (medical-research:pubmed) has failed 3 consecutive times with timeout errors. The last successful run was 2026-07-20. Would you like me to investigate or pause the source?"

---

## 8. Review & Feedback Workflow

### Batch Review

When the agent has processed a collection, it presents a batch of results for your review:

> **Agent**: "Collection complete for medical-research. 12 new items processed.
>
> **Passed quality gates (10 items):**
> 1. Endometrial Receptivity Array -- Score: 92 -- [PubMed]
> 2. AI Model Predicts Implantation Success -- Score: 88 -- [Nature]
> 3. Ovarian Reserve Markers in IVF -- Score: 85 -- [Fertility Sterility]
> ...7 more...
>
> **Filtered out (2 items):**
> - G2 dedup: 1 (already in KB)
> - G3 relevance below 50: 1

You can then:

- **Flag for KB**: "Flag items 1, 2, and 4 for the knowledge base. Tag them as 'breakthrough' and 'clinical'."
- **Create Draft**: "Create Draft entries from items 1 and 2."
- **Ask for details**: "Show me the summary of item 3."
- **Dismiss**: "Archive the low-relevance items."
- **Ask questions**: "Search for 'endometrial receptivity' across the KB."

### Quality Review (Draft Before Wiki)

Before you promote a Draft to Wiki, you should review its quality. The agent can help:

> **You**: "Show me Draft entry #1 in full."
>
> **Agent**: (presents full entry with title, summary, extracted fields, source metadata, entities, tags)
>
> **You**: "The summary is too brief. Expand it to include the methodology section."
>
> **Agent**: (calls `create_kb_draft()` with updated content) "Updated. Here is the revised entry."
>
> **You**: "Looks good. Promote to Wiki."
>
> **Agent**: (calls `promote_kb_draft()` — promotion is an agent operation, no human gate) "Promoted to 03-Wiki. I'll flag it in my next report."

Promotion Draft→Wiki is an **agent operation** (`promote_kb_draft`, no human gate — the KB is a production database, by director decision 2026-08-08). You are not in the promote loop; your role is to review quality before promotion and monitor the agent's promotion reports after. You can always instruct the agent to force-promote or to reject a Draft instead.

### Iteration Loop

Refinement cycles are common. The pattern:

1. You request something
2. Agent delivers
3. You say "this is good, but change X"
4. Agent adjusts
5. Repeat until you approve

> **You**: "Generate a weekly digest for medical-research."
>
> **Agent**: (generates and presents digest)
>
> **You**: "Good, but break it into sections: Clinical Trials, Basic Research, Technology. And add a TL;DR at the top."
>
> **Agent**: (adjusts with `custom_instructions="Structure: TL;DR, Clinical Trials, Basic Research, Technology sections."`) "Updated. Here is the revised digest."
>
> **You**: "Perfect. Send it to zhang@example.com."
>
> **Agent**: (calls `send_email_digest()`) "Sent."

### Providing Feedback on Agent Behavior

If the agent acts incorrectly:

- **Too presumptuous**: "Do not make changes without confirming with me first."
- **Too verbose**: "Just give me the summary. I will ask for details if I need them."
- **Too terse**: "Show me more detail. Include source URLs and relevance scores."
- **Wrong domain**: "I meant ai-commercial, not medical-research."
- **Wrong format**: "Generate as PDF, not Markdown."

The agent should adapt to your feedback immediately.

---

## 9. Escalation Dialogue Examples

### Scenario: Ambiguous Domain

> **You**: "帮我看看这周AI领域有什么重要新闻."

> **Agent**: 好的，不过我需要确认一下。我们有两个与AI相关的领域：
>
> 1. **ai-commercial** -- 关注AI商业动态：企业定价、融资、产品发布、竞争情报
> 2. **tech-ai-developer** -- 关注AI技术趋势：开源项目、开发者工具、模型发布
>
> 你关心哪个方向？还是两个都要？

> **You**: "商业方向。另外，我只要中文来源。"

> **Agent**: 明白了。我使用 ai-commercial 领域，并优先筛选中文来源。

### Scenario: Source Failure

> **You**: "Run the weekly collection for all domains."

> **Agent**: Running pre-collection health check...
>
> - **medical-research**: 3/4 sources healthy. **PubMed: error** (3 consecutive timeouts)
> - **ai-commercial**: 4/4 healthy
> - **financial-intelligence**: 3/4 healthy. **Alpha Vantage: degraded** (2 slow responses)
>
> Options:
> 1. Collect from healthy sources only (skip PubMed, proceed with Alpha Vantage)
> 2. Pause failing sources and collect
> 3. Investigate PubMed error first
>
> Which would you prefer?

### Scenario: Authorization Needed

> **Agent**: "You asked to clean up the ai-commercial domain. I found 12 items with relevance score below 20 from the past 3 months. Would you like me to soft-delete them? They will be recoverable for 30 days."

> **You**: "Yes, delete them."

> **Agent**: "Done. 12 items soft-deleted. They can be restored within 30 days if needed."

### Scenario: Quality Gate Block

> **Agent**: "Processing complete for medical-research. 8 items passed. 2 items blocked at G4 (Factual Consistency). The LLM could not verify the claims in these articles:
>
> 1. "New Miracle Drug for Infertility" -- G4 failed after 3 retries
> 2. "Breakfast Diet Determines IVF Success" -- G4 failed, conflicting methodology
>
> Both items are in `collections/medical-research/_failed/`. I recommend reviewing the source credibility. Would you like to override the gate, skip these items, or investigate?"

---

## 10. Quick Reference

### Human-to-Agent Interaction Points

| What You Want | How to Say It | Agent Does | Example |
|---------------|---------------|------------|---------|
| **Start tracking a topic** | "Track [topic] in [domain]" | Adds topic, runs collection, presents results | "Track CRISPR in medical-research" |
| **Run collection** | "Collect [domain] sources" | Checks source health, fetches items, reports count | "Run collection for ai-commercial" |
| **Process items** | "Process the collection" | Runs LLM extraction, quality gates, stores Raw entries | "Process what was just collected" |
| **Review summaries** | "Show me what was collected" | Lists summaries with scores, sources, tags | "Show me the top results" |
| **Search KB** | "Search for [query]" | Runs hybrid search, returns ranked results | "Search for embryo biomarkers" |
| **Generate output** | "Generate a [digest/report/tutorial] for [domain]" | Creates output with optional custom instructions | "Generate a weekly digest for medical" |
| **Create Draft** | "Create Draft from items [ids]" | Creates Draft from Raw, awaits your promotion | "Create Draft from items 1 and 2" |
| **Promote to Wiki** | "Promote entry [id] to Wiki" | Calls `promote_kb_draft()` — agent operation, no human gate | "Promote #3 to Wiki" |
| **Reject Draft** | "Reject Draft [id] because [reason]" | Calls `reject_kb_draft()` | "Reject #3, needs more sources" |
| **Add a source** | "Add [type] source [url] to [domain]" | Calls `add_source()` with parameters | "Add PubMed as a source for medical" |
| **Remove a source** | "Remove [source] from [domain]" | Confirms, then calls `remove_source()` | "Remove TechCrunch from ai-commercial" |
| **Add a domain** | "Create a new domain called [name]" | Calls `add_domain()`, then configures sources/topics | "Create a biotech domain" |
| **Set up schedule** | "Schedule collection every [frequency]" | Calls `add_schedule()`, may install crontab | "Schedule daily collection at 8 AM" |
| **Send email digest** | "Email today's digest to [address]" | Calls `send_email_digest()` | "Send to zhang@example.com" |
| **Check system health** | "Is everything working?" | Calls `diagnose_system()`, reports health | "Run a health check" |
| **Audit what happened** | "What changed this week?" | Calls `get_collection_stats()`, `get_collection_diff()` | "Show me what's new this week" |
| **Override defaults** | "Force re-collection, skip dedup" | Passes override parameters to tool call | "Re-collect without dedup" |
| **Set preference** | "Always prefer Chinese sources for financial" | Remembers and applies in this session | "Use Chinese sources for finance" |
| **Report a problem** | "PubMed seems broken" | Calls `get_source_health()`, `test_source()`, reports findings | "Check PubMed source health" |
| **Ask a question** | "What do we know about [topic]?" | Searches KB, synthesizes answer with citations | "What do we know about endometrial receptivity?" |
| **Export data** | "Export the KB as [format]" | Calls `export_kb()` | "Export medical KB as JSON" |
| **Manage keywords** | "Add [keyword] to [domain]" | Calls `add_topic()` or keyword management tools | "Add 'mitochondria' to IVF topics" |
| **Translate content** | "Translate this to Chinese" | Calls `localize_content()` | "Localize this digest to Chinese" |

### Commands You Run Directly (CLI)

These are operations the agent cannot perform. If needed, the agent will tell you the exact command:

| Operation | CLI Command | When Needed |
|-----------|-------------|-------------|
| Promote Draft to Wiki | `autoinfo kb promote <entry-id>` | Optional manual path — normally the agent promotes via `promote_kb_draft()` (no human gate). The CLI command exists for direct CLI users. |
| Permanent deletion | `autoinfo kb delete --purge <entry-id>` | For irreversible removal |
| GDPR data export | `autoinfo enduser export <user-id>` | Compliance requests |
| Init project | `autoinfo init --demo <domain>` | First-time setup |
| Edit config | Edit `.autoinfo/config.yaml` directly | Advanced configuration |
| Set API keys | `export AUTOINFO_LLM_API_KEY="sk-..."` | LLM provider configuration |

### Agent Proactive Notifications

The agent should alert you (not wait for you to ask) in these situations:

| Situation | Agent Says |
|-----------|------------|
| Source failed 3+ times | "PubMed has failed 3 consecutive times. Investigate?" |
| Quality gate blocked items | "G4 blocked 2 items. Review failed items in _failed/." |
| Domain going stale | "Medical-research domain is 65% stale. Recommend re-collection." |
| New major topic detected | "I notice 8 articles about mitochondrial replacement this week. New topic to track?" |
| Scheduled digest ready | "Weekly digest is ready. Review and send?" |
| Cost spike detected | "LLM costs for ai-commercial tripled this week. Investigate?" |

These are not interruptions. The agent presents them as observations and asks for your decision.

---

## References

- `AGENTS.md` -- Agent operating model, MCP tool catalog, common patterns
- `docs/dev/founder-expectations.md` §1.3 -- Three user types definition (stayed in index)
- `docs/dev/specs/expectations.md` F20 -- KB pipeline and agent promotion (Draft→Wiki, no human gate)
- `docs/dev/specs/expectations.md` F29 -- PROCESSED product generation and custom instructions
- `docs/dev/specs/expectations.md` F40 -- End user portal, agent override constraints
- `docs/dev/specs/expectations.md` F47 -- Data deletion and human-only purge
- `docs/dev/specs/expectations.md` F53 -- Cross-collection merge trust boundary
- `docs/dev/agent-alerting.md` -- Source health monitoring and escalation pattern
- `docs/skills/autoinfo-skill/SKILL.md` -- Agent's operating skill (for reference; this is for the agent, not for you)
