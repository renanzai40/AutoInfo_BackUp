---
title: 'Show HN: Gibson ADK and Security Runtime'
domain: tech-ai-developer
tier: 01-Raw
entry_id: tech-ai-developer-general-show-hn-gibson-adk-and-security-runtime
source_url: https://www.zeroroot.ai
source_type: rss
source_platform: hnrss
collected_at: '2026-08-25T15:35:18+00:00'
summary: The article presents Gibson ADK and Security Runtime, a tool developed by a DevSecOps and offensive security expert
  for securely deploying AI agents in production. It features permission-based access controls, isolated execution via Firecracker
  microVMs, append-only logging, and knowledge graphs for persistent memory. The creator is seeking advice on commercialization
  strategies, such as open sourcing, platform development, or focusing on offensive security tools.
tags: []
quality_tier: 1
relevance_score: 0.0
dedup_status: unique
source_score: 90.0
language: en
user_id: ''
version: 1
previous_version: 0
supersedes: ''
trace_id: d8f8f866-6757-486e-87ad-3fa806b0b38d
quality_flags:
  G0-SchemaIntegrity: false
  G1-SourceAuthority: false
  G1-TosCompliance: false
  G2-Dedup: false
  G3-RelevanceScoring: true
  G4-SummaryFactual: false
tos_compliant: true
tos_classification: open
---

## Original Content
<p>I have spent 15 years in DevSecOps, platform engineering and offensive security. Over the last year I did most of the things HN says not to do. I wrote a lot of code alone in a vacuum and built this thing far past an MVP.<p>It started as a way to automate my bug bounty hobby and to try to find an edge so I could get more findings (scale, automation etc). I wanted agents that could run recon, triage what they found, keep a record etc etc.<p>Then I noticed the same patterns at every client I had worked with, (mainly banks and gov teams) and pivoted. 
What it is now: an all-in-one solution to getting your agents into prod.<p>You keep your framework, or build from scratch with gibson. A named person grants each agent read, write or execute on specific things, and the grant cannot exceed what that person holds. Every model call and tool call goes through the runtime first, and a call outside the grant never executes. Untrusted work runs in its own Firecracker microVM. Every action lands in an append-only record you can replay to any moment. Everything an agent finds goes into a knowledgegraph (on going memory for all agents), so the next run starts from it. It runs in Kubernetes, hosted or in your own cluster, can be air-gapped.<p>This could also have been an Ask HN. I am trying to figure out how to go to market.  Im not sure if I should open source it, do a true platform or move back entirely and go deep into what I truly like doing which is red team/hacking and re-release it as an offsec focused tool and try to innovate there with the framework. Any advice/suggestions would be awesome.  Thanks!</p>
<hr />
<p>Comments URL: <a href="https://news.ycombinator.com/item?id=49435908">https://news.ycombinator.com/item?id=49435908</a></p>
<p>Points: 1</p>
<p># Comments: 0</p>

## Summary
The article presents Gibson ADK and Security Runtime, a tool developed by a DevSecOps and offensive security expert for securely deploying AI agents in production. It features permission-based access controls, isolated execution via Firecracker microVMs, append-only logging, and knowledge graphs for persistent memory. The creator is seeking advice on commercialization strategies, such as open sourcing, platform development, or focusing on offensive security tools.

## Key Points
- Gibson ADK provides a secure runtime for agent deployment with permission grants tied to named individuals, ensuring no action exceeds the grantor's rights.
- Untrusted workloads run in isolated Firecracker microVMs to enhance security and prevent unauthorized access.
- All model and tool calls are logged in an append-only record for auditing and replayability.
- Knowledge graphs are used to maintain shared memory across agent runs, improving continuity.
- The system is designed to run in Kubernetes environments, supporting hosted or on-premise deployments with air-gap capability.


## Entities
- **Gibson ADK** (technology, relevance=)
- **Security Runtime** (technology, relevance=)
- **Firecracker microVMs** (technology, relevance=)
- **Kubernetes** (technology, relevance=)
- **DevSecOps** (concept, relevance=)
- **platform engineering** (concept, relevance=)
- **offensive security** (concept, relevance=)
- **bug bounty** (procedure, relevance=)
- **agents** (concept, relevance=)
- **knowledge graphs** (concept, relevance=)
