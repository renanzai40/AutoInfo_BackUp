---
title: WiredTiger History Store：文档库里的第三种 MVCC
domain: tech-ai-developer
tier: 01-Raw
entry_id: tech-ai-developer-general-wiredtiger-history-store-mvcc
source_url: https://juejin.cn/post/7677803387145142281
source_type: rss
source_platform: juejin
collected_at: '2026-08-25T13:14:28+00:00'
summary: This article introduces WiredTiger's History Store as a third MVCC approach in document stores, enabling snapshot
  reads after eviction. It compares this method with PostgreSQL's heap versioning and InnoDB undo logs, and explains the transition
  from Lookaside to Du.
tags: []
quality_tier: 1
relevance_score: 0.0
dedup_status: unique
source_score: 90.0
language: zh
user_id: ''
version: 1
previous_version: 0
supersedes: ''
trace_id: 45fb2ade-1acf-4f43-adb5-43b3a44ce9b2
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
WiredTiger 把旧版本挪到 History Store，eviction 后仍能服务快照读。本文对照 PostgreSQL 堆版本与 InnoDB undo，交代 Lookaside 到 Du

## Summary
This article introduces WiredTiger's History Store as a third MVCC approach in document stores, enabling snapshot reads after eviction. It compares this method with PostgreSQL's heap versioning and InnoDB undo logs, and explains the transition from Lookaside to Du.

## Key Points
- WiredTiger's History Store is a novel MVCC mechanism for database storage engines.
- It supports snapshot reads even after data eviction, enhancing read performance.
- The article provides a comparative analysis with PostgreSQL and InnoDB versioning techniques.
- It discusses the evolution from Lookaside to Du in version management systems.


## Entities
- **WiredTiger** (technology, relevance=)
- **History Store** (concept, relevance=)
- **MVCC** (concept, relevance=)
- **PostgreSQL** (technology, relevance=)
- **InnoDB** (technology, relevance=)
- **Lookaside** (concept, relevance=)
- **Du** (concept, relevance=)
