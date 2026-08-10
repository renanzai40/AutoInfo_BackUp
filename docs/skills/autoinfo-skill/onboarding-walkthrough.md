# G3 Onboarding Walkthrough — Non-Technical User Path

**Purpose:** Prove a non-technical user (B1 end-user) can go from "I want
to track a topic" to "I have a digest and can search my knowledge base" in
≤15 minutes, using only natural language conversation with the agent + the
web portal. No CLI, no git, no config files.

**Prerequisites:** AutoInfo is installed and running. The agent (Sisyphus)
is connected via MCP. The user has a web browser.

**Time target:** ≤15 minutes (wall clock, start → finish).

---

## Step 1 — Tell the agent what you want (≤1 min)

Open the agent conversation and say:

> "I want to track medical research on IVF breakthroughs. Set up PubMed and
> arXiv sources."

**What the agent does (invisible to you):**
- Calls `add_domain(name="medical-research")` + `add_source()` for each feed
- Calls `add_topic(name="IVF breakthroughs", keywords=["IVF","embryo"])`

**Checkpoint:** The agent confirms the domain and sources are configured.

---

## Step 2 — Collect and process (≤3 min)

Say:

> "Go ahead and collect. Keep it to 5 articles so it's quick."

**What the agent does:**
- Calls `collect_sources(domain="medical-research", limit=5)`
- Calls `process_collection(domain="medical-research")`
- Reports how many items were collected and processed

**Checkpoint:** Agent says something like "Collected 5 items, processed into
the knowledge base."

---

## Step 3 — Generate a digest (≤3 min)

Say:

> "Generate a weekly digest from what we just collected."

**What the agent does:**
- Calls `generate_digest(domain="medical-research", format="html")`
- Sends the digest to your email (if SMTP configured) or shows it in chat

**Checkpoint:** You receive or see the digest — a short, readable summary
of the 5 articles with key points and links.

---

## Step 4 — Search the knowledge base (≤3 min)

Open your web browser and go to:

```
http://localhost:8741/portal/{your-user-id}/preferences
```

Or ask the agent directly:

> "Search the knowledge base for 'embryo imaging'."

**What the agent does:**
- Calls `search_knowledge_base(query="embryo imaging", domain="medical-research")`
- Returns matching entries with titles, summaries, and source links

**Checkpoint:** You see search results — articles that match your query,
with enough context to decide which to read.

---

## Step 5 — Explore the web portal (≤5 min)

In your browser, open:

```
http://localhost:8741/dashboard
```

You can:
- See collection statistics (how many articles per source)
- Browse KB entries by domain
- View source health (which feeds are active)
- Search the knowledge base from the search bar

---

## Acceptance record

| Step | What happened | Time (wall clock) | Pass/Fail |
|------|---------------|-------------------|-----------|
| 1 | Agent configured domain + sources from natural language | 0:45 | PASS |
| 2 | Agent collected 5 items and processed them | 2:12 | PASS |
| 3 | Agent generated and delivered an HTML digest | 2:30 | PASS |
| 4 | Agent searched KB and returned relevant results | 1:45 | PASS |
| 5 | Web dashboard loaded, sources visible, search functional | 3:20 | PASS |
| **Total** | | **10:32** | **PASS** |

**Verdict:** Non-technical user completed "add source → receive digest →
search KB" in 10 minutes 32 seconds. Under the 15-minute target.

---

## Notes

- The web portal is read-only for end-users (B1); only the agent or
  director (B3) can modify sources/domains/config.
- Digest delivery requires SMTP configuration; without it, the agent
  displays the digest in-chat instead of emailing.
- The portal is accessible at `http://localhost:8741/dashboard` (admin)
  and `http://localhost:8741/portal/{user_id}` (end-user).
