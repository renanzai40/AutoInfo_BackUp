<!-- agent: ops-runbook -->
# Operations Runbook: Backup, Disaster Recovery, Monitoring & Scaling

## Agent Quick Reference

This runbook targets human operators running bash procedures. Agents should use the MCP tools below instead of executing scripts directly. Where no MCP tool exists, escalate to a human.

- **Health check:** Agent calls `diagnose_system()` MCP tool. Returns structured health data covering LLM key, sources, disk, and DB. Do not run `autoinfo doctor` CLI.
- **Backup status:** Agent calls `health_check()` MCP tool and inspects the `last_backup` field to verify the most recent backup timestamp. No MCP tool triggers a new backup; the existing `make backup` target and `scripts/backup-db.sh` are human-operated.
- **Recovery (restore from backup):** No DR MCP tools exist yet. Agent must escalate to a human operator, who runs `scripts/restore-db.sh` manually. Do not attempt restore via shell commands.
- **Monitoring:** Agent calls `get_metrics()` or `get_prometheus_metrics()` for runtime metrics, and `get_channel_health()` for delivery channel status. Prometheus endpoint at `http://localhost:8741/metrics` is human-facing.
- **Cron health:** Agent calls `get_schedule_status()` to inspect schedule state. The `autoinfo cron health` CLI (heartbeat + missed-schedule detection) is human-facing.

### Operations that require human intervention

The following operations have no MCP tool equivalent and must be escalated to a human operator:

- **Restore from backup** — `scripts/restore-db.sh` (no DR MCP tools yet)
- **Trigger a manual backup** — `make backup` or `scripts/backup-db.sh` (no backup MCP tool)
- **Off-site backup replication** — rsync/S3 sync of `/var/backups/autoinfo/` (infrastructure-level)
- **Cron job installation** — `autoinfo cron install` writes system crontab entries (host-level)
- **Disk space remediation** — clearing `/var/backups/autoinfo/` retention or expanding storage
- **Process restart / scaling** — restarting the FastAPI server, MCP server, or scaling horizontally (no scaling MCP tools)
- **Secret rotation** — LLM API keys, SMTP credentials, webhook secrets (env vars / config file, not agent-managed)
- **Disaster recovery plan execution** — full DR failover procedure (spec, not implemented)

> **Date:** 2026-07-27
> **Status:** 🔴 Spec — not implemented. All procedures are designed for future implementation.
> **Status 2026-08-04:** Partially implemented — SQLite backup (`scripts/backup-db.sh` / `scripts/restore-db.sh`, keeps last 7), cron health (`autoinfo cron health` — heartbeat + missed-schedule detection), and channel health (`get_channel_health`) are shipped; remaining items spec-only.
> **References:** `cross-dimensional-catalog.md` (CD-004 Cron Reliability & Backup, CD-007 Delivery Channel Health, CD-013 Live Operations Dashboard, CD-014 Backup & Disaster Recovery, CD-015 Horizontal Scaling Strategy), `operations.md` §4 (Observability), `pipeline.md` (Collection & KB pipeline).
> **Current Reality:** AutoInfo runs as a single-node SQLite application. Backup is a manual `make backup` target. No automated monitoring alerts. No DR plan. No scaling beyond the single process.

---

## 1. Backup & Restore

> **Cross-ref:** CD-004 (Cron Reliability & Backup), CD-014 (Backup & Disaster Recovery).
> **Current gap:** `Makefile` has a `backup` target that creates a `.bak` file. No cron-based automation, no off-site storage, no restore procedure, no backup verification.

### 1.1 Backup Strategy

AutoInfo's primary datastore is a SQLite database file. All state lives in three locations:

| Location | Content | Backup Priority | Frequency |
|----------|---------|-----------------|-----------|
| `{project}/autoinfo.db` | SQLite — KB entries, summaries, users, subscriptions, delivery logs, audit logs, cost logs | 🔴 P0 | Hourly |
| `{project}/knowledge/` | Markdown KB files (git-tracked) | 🟡 P1 | Daily (covered by git push) |
| `{project}/.autoinfo/config.yaml` | Domain config, sources, topics, schedules, alert rules | 🟡 P1 | On change + daily |
| `{project}/collections/` | Raw JSON cache | 🟢 P2 | Weekly (rebuildable via re-collection) |

**Philosophy:** SQLite backup is the primary concern. KB Markdown files are git-tracked (backed up by push). Collection cache is disposable (re-collection recovers).

### 1.2 Automated SQLite Backup

#### Cron-Based Backup Job

```bash
# /etc/cron.d/autoinfo-backup
0 * * * * autoinfo-user /usr/local/bin/autoinfo-backup hourly
0 2 * * * autoinfo-user /usr/local/bin/autoinfo-backup daily
0 3 * * 0 autoinfo-user /usr/local/bin/autoinfo-backup weekly
```

The `autoinfo-backup` script wraps `sqlite3 .backup` with retention and verification:

```bash
#!/bin/bash
# /usr/local/bin/autoinfo-backup
set -euo pipefail

PROJECT_DIR="${AUTOINFO_PROJECT_DIR:-$(pwd)}"
DB_PATH="${PROJECT_DIR}/autoinfo.db"
BACKUP_ROOT="${AUTOINFO_BACKUP_DIR:-/var/backups/autoinfo}"
RETENTION_HOURLY=24    # Keep 24 hourly backups
RETENTION_DAILY=7      # Keep 7 daily backups
RETENTION_WEEKLY=4     # Keep 4 weekly backups

TYPE="${1:-hourly}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_ROOT}/${TYPE}/autoinfo-${TIMESTAMP}.db.gz"

mkdir -p "$(dirname "$BACKUP_FILE")"

# Step 1: SQLite online backup (safe on live DB — uses SQLite backup API)
sqlite3 "$DB_PATH" ".backup /tmp/autoinfo-backup-tmp.db"

# Step 2: Compress
gzip -c /tmp/autoinfo-backup-tmp.db > "$BACKUP_FILE"
rm /tmp/autoinfo-backup-tmp.db

# Step 3: Checksum
sha256sum "$BACKUP_FILE" > "${BACKUP_FILE}.sha256"

# Step 4: Retention cleanup
find "${BACKUP_ROOT}/${TYPE}" -name "*.db.gz" -mtime "+${RETENTION_HOURLY}" -delete 2>/dev/null || true

# Step 5: Optional S3 sync (if configured)
if [ -n "${AUTOINFO_S3_BUCKET:-}" ]; then
    aws s3 cp "$BACKUP_FILE" "s3://${AUTOINFO_S3_BUCKET}/backups/${TYPE}/" --storage-class STANDARD_IA
    aws s3 cp "${BACKUP_FILE}.sha256" "s3://${AUTOINFO_S3_BUCKET}/backups/${TYPE}/"
fi

echo "Backup complete: $BACKUP_FILE"
```

**Why `sqlite3 .backup` not `cp`:** The `.backup` command uses SQLite's online backup API, which acquires a shared lock and copies a transactionally consistent snapshot. `cp` on a live database can produce a corrupt copy if a write is in progress.

#### Backup Schedule Summary

| Frequency | Cron | Retention | Purpose |
|-----------|------|-----------|---------|
| **Hourly** | `@hourly` | 24 backups (1 day) | Short-term point-in-time recovery |
| **Daily** | 2:00 AM | 7 backups (1 week) | Daily snapshots for medium-term recovery |
| **Weekly** | Sunday 3:00 AM | 4 backups (4 weeks) | Long-term archival |

### 1.3 Backup Storage Strategy

#### Tier 1: Local Disk (Always)

Backups stored on the application server at `/var/backups/autoinfo/{hourly,daily,weekly}/`.

**Space estimate:** SQLite DB ~100 MB compressed → 24 × 100 MB = 2.4 GB/hourly + 700 MB/daily + 400 MB/weekly ≈ **3.5 GB** total for 35 backup files.

#### Tier 2: S3 / Cloud Object Storage (Optional, Strongly Recommended)

Configure via environment variables:

```bash
export AUTOINFO_S3_BUCKET="my-autoinfo-backups"
export AWS_REGION="us-east-1"
# Credentials via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or IAM role
```

Backups synced to S3 with `STANDARD_IA` storage class (cheaper for infrequent access). Lifecycle policy on the S3 bucket auto-expires backups older than 90 days.

#### Tier 3: Cross-Region Replication (Production Only)

For production deployments, enable S3 cross-region replication on the backup bucket to a secondary region. Protects against regional AWS outages. Estimated cost: $0.02/GB replication + storage in secondary region.

### 1.4 Point-in-Time Recovery Procedure

SQLite is a single-file database. Point-in-time recovery is limited to the granularity of backup snapshots (1 hour best case). For finer granularity, enable SQLite WAL mode and back up WAL files separately.

#### Recovery Steps

```bash
# 1. Stop AutoInfo services (prevent writes during restore)
systemctl stop autoinfo-mcp autoinfo-api

# 2. Locate the desired backup
ls -la /var/backups/autoinfo/hourly/
# Pick the backup closest to (but before) the desired recovery point

# 3. Verify backup integrity
sha256sum -c /var/backups/autoinfo/hourly/autoinfo-20260727-140000.db.gz.sha256

# 4. Restore
gunzip -c /var/backups/autoinfo/hourly/autoinfo-20260727-140000.db.gz \
    > /tmp/autoinfo-restored.db

# 5. Quick integrity check on restored DB
sqlite3 /tmp/autoinfo-restored.db "PRAGMA integrity_check;"
# Expected output: "ok"

# 6. Move into place
cp /tmp/autoinfo-restored.db /path/to/project/autoinfo.db

# 7. (Optional) Replay WAL if available
# sqlite3 /path/to/project/autoinfo.db ".recover" > recovered.sql

# 8. Restart services
systemctl start autoinfo-mcp autoinfo-api

# 9. Verify system health
python -m autoinfo.cli doctor --verbose
```

#### Recovery Time Estimate

| Step | Time |
|------|------|
| Stop services | < 10 seconds |
| Locate + download backup | < 30 seconds (local) / < 2 min (S3) |
| Verify checksum | < 5 seconds |
| Decompress + integrity check | < 30 seconds |
| Move into place | < 5 seconds |
| Restart + health check | < 30 seconds |
| **Total (local backup)** | **~2 minutes** |
| **Total (S3 backup)** | **~4 minutes** |

### 1.5 Backup Verification

**Automated verification** runs after each backup as a sub-step and weekly as a full restore test.

#### Post-Backup Checksum Verification

The `sha256sum` computed at backup time is stored alongside the backup file. On restore, verify before decompressing.

#### Weekly Restore Test (Automated)

```bash
#!/bin/bash
# /etc/cron.weekly/autoinfo-backup-test
# Runs every Sunday at 4:00 AM

BACKUP_DIR="/var/backups/autoinfo/daily"
LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/*.db.gz | head -1)
TEST_DB="/tmp/autoinfo-restore-test.db"

# Restore to temp location
gunzip -c "$LATEST_BACKUP" > "$TEST_DB"

# Run integrity checks
INTEGRITY=$(sqlite3 "$TEST_DB" "PRAGMA integrity_check;")
TABLE_COUNT=$(sqlite3 "$TEST_DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
KB_COUNT=$(sqlite3 "$TEST_DB" "SELECT COUNT(*) FROM kb_entries;" 2>/dev/null || echo "N/A")

# Log results
echo "[$(date)] Backup test: integrity=$INTEGRITY, tables=$TABLE_COUNT, kb_entries=$KB_COUNT" \
    >> /var/log/autoinfo/backup-test.log

# Cleanup
rm "$TEST_DB"

# Alert on failure
if [ "$INTEGRITY" != "ok" ]; then
    # Trigger P0 alert (see §3)
    /usr/local/bin/autoinfo-alert "backup_integrity_failed" "Integrity check failed: $INTEGRITY"
fi
```

**MCP tool** (spec'd, not implemented):

> **Status 2026-08-04:** SQLite backup shipped via `scripts/backup-db.sh` / `scripts/restore-db.sh` (keeps last 7 backups; `make backup`). The backup MCP tools below remain spec-only.

| Tool | Description |
|------|-------------|
| `verify_backup(backup_id)` | Verify backup integrity (checksum + sqlite3 integrity_check) |
| `list_backups(period)` | List available backups with timestamps and sizes |
| `restore_backup(backup_id, target_dir)` | Restore database from backup to target directory (dry-run by default) |

---

## 2. Disaster Recovery

> **Cross-ref:** CD-014 (Backup & Disaster Recovery).
> **Current gap:** No RPO/RTO defined, no failover procedure, no DR testing schedule.

### 2.1 RPO & RTO Targets

| Metric | Target | Rationale |
|--------|--------|-----------|
| **RPO** (Recovery Point Objective) | **1 hour** | Maximum data loss: 1 hour of collection + processing. KB content is re-collectable from sources. User/subscription/cost data is the critical loss. Configurable per deployment. |
| **RTO** (Recovery Time Objective) | **4 hours** | Time from detection to fully operational. Includes: alerting delay (≤5 min), human acknowledgment (≤30 min), restore from backup (≤15 min), service verification (≤30 min), DNS/cutover if needed (≤2 hours buffer). Configurable per deployment. |

**Configurable in `config.yaml`:**

```yaml
disaster_recovery:
  rpo_hours: 1
  rto_hours: 4
  auto_failover: false          # Manual failover only (single-node SQLite limitation)
  dr_test_schedule: "0 4 1 */3 *"  # First day of each quarter at 4 AM
```

**RPO tradeoffs:** Reducing RPO below 1 hour requires WAL archiving (ship WAL files every 5-15 minutes to S3). This adds operational complexity. For single-node SQLite, 1 hour is the practical minimum without WAL shipping.

### 2.2 Failure Scenarios & Recovery Procedures

#### Scenario 1: SQLite Database Corruption

**Detection:** `PRAGMA integrity_check` returns non-"ok". Queries return `SQLITE_CORRUPT` errors. `diagnose_system()` reports degraded status.

**Recovery:**
1. Stop all AutoInfo processes immediately (prevent further writes on corrupted DB)
2. Identify the most recent verified backup (from backup-test logs)
3. Execute restore procedure (§1.4, steps 1-9)
4. Validate: run `autoinfo doctor --verbose`, check KB entry count, verify recent delivery logs
5. Notify affected users if data loss exceeds RPO (see §3.2 for alert routing)

**Data loss scope:** Any items collected/processed between last successful backup and corruption event. Items are re-collectable (sources are external), but summaries/extractions are lost and require re-processing.

#### Scenario 2: Application Server Failure (OS crash, disk failure)

**Detection:** MCP server unresponsive, API endpoint returns 502/503, health check fails.

**Recovery:**
1. Provision new server (or restore VM from snapshot)
2. Install AutoInfo + dependencies (`pip install autoinfo`)
3. Restore from latest S3 backup (or local if disk survived)
4. Restore KB Markdown files from git (`git clone` / `git pull`)
5. Restore config from backup or git
6. Verify: `autoinfo doctor --verbose`
7. Update DNS if IP changed
8. Run `autoinfo cron install` to re-register cron jobs
9. Trigger a test collection to verify source connectivity

**Time estimate:** 1-3 hours (excluding server provisioning time). Within RTO if backup is readily accessible.

#### Scenario 3: Accidental Data Deletion (Human Error)

**Detection:** User reports missing entries. KB search returns fewer results than expected.

**Recovery:**
1. Identify deletion time from audit log (`autoinfo audit query --action soft_delete`)
2. If soft-deleted (within 30-day window): use `restore_entry` MCP tool
3. If hard-deleted or outside window: restore from backup to temp location, extract the missing entries, re-import
4. KB Markdown files: restore from git history (`git checkout <commit> -- knowledge/`)

### 2.3 Data Integrity Verification After Restore

After any restore, run the following verification checklist:

```bash
# 1. SQLite integrity
sqlite3 autoinfo.db "PRAGMA integrity_check;"
# Expected: "ok"

# 2. Foreign key consistency
sqlite3 autoinfo.db "PRAGMA foreign_key_check;"
# Expected: no rows returned

# 3. KB tier consistency (every Draft must have a Raw parent)
sqlite3 autoinfo.db "
  SELECT COUNT(*) FROM kb_entries e
  WHERE tier = '02-Draft'
  AND e.id NOT IN (
    SELECT draft_id FROM kb_entries WHERE tier = '01-Raw'
  );
"
# Expected: 0

# 4. System health check
python -m autoinfo.cli doctor --verbose

# 5. Smoke test: search, Q&A, digest generation
python -m autoinfo.cli kb search --query "test" --domain {domain}
python -m autoinfo.cli output digest --domain {domain} --period daily --dry-run
```

**Automated post-restore validation script** (`autoinfo validate-restore`): Runs steps 1-5 and returns pass/fail with diagnostic output. Must pass before declaring recovery complete.

### 2.4 DR Testing Schedule

| Frequency | Activity | Duration | Owner |
|-----------|----------|----------|-------|
| **Weekly** | Backup restore test (automated) — restore latest daily backup to temp location, run integrity check | 5 min (automated) | Cron job |
| **Monthly** | Manual restore drill — operator performs full restore to a staging environment, runs smoke tests | 30 min | Operations |
| **Quarterly** | Full DR simulation — simulate server loss, restore from S3 backup to a clean VM, verify all services operational | 2 hours | Operations + Engineering |
| **Annual** | Cross-region DR test — restore from cross-region replica, verify RPO/RTO compliance | 4 hours | Operations + Engineering |

**Quarterly DR test checklist:**
1. [ ] Timestamp: note current time for RTO measurement
2. [ ] Simulate failure: stop all AutoInfo services
3. [ ] Provision clean VM (or use pre-warmed standby)
4. [ ] Restore from S3 backup (latest hourly)
5. [ ] Run `autoinfo validate-restore`
6. [ ] Verify: KB search returns expected results
7. [ ] Verify: MCP tools respond (sample: `health_check`, `list_domains`)
8. [ ] Verify: cron schedules are registered (`crontab -l`)
9. [ ] Verify: Prometheus metrics endpoint responds
10. [ ] Record RTO achieved, RPO gap (data age in backup), any issues
11. [ ] Post-mortem: document findings, update runbook if procedures changed

**DR test log** stored at `docs/operations/dr-test-log.md`:

```markdown
## DR Test Log

| Date | Type | RTO Target | RTO Achieved | RPO Gap | Pass/Fail | Notes |
|------|------|------------|-------------|---------|-----------|-------|
| 2026-10-01 | Quarterly | 4h | 3h 12m | 47 min | ✅ Pass | S3 download slower than expected; add edge location |
| 2026-07-01 | Quarterly | 4h | 2h 45m | 22 min | ✅ Pass | Clean restore, no issues |
```

---

## 3. Monitoring & Alerting

> **Cross-ref:** CD-004 (Cron Reliability & Backup), CD-007 (Delivery Channel Health Monitoring), CD-013 (Live Operations Dashboard).
> **Current gap:** Prometheus endpoint exists with 8 metrics. No alert rules defined. No PagerDuty/webhook integration. No runbook templates.

### 3.1 Prometheus Metrics Reference

See `operations.md` §4.3 for the canonical Prometheus metrics reference (endpoint: `http://localhost:8741/metrics`).

**Additional metrics needed** (spec'd, not implemented):

> **Status 2026-08-04:** Prometheus endpoint shipped at `http://localhost:8741/metrics` (see operations.md §4.3). The additional metrics below remain spec-only.

| Metric | Type | Purpose |
|--------|------|---------|
| `items_collected_total` | Counter | Collection throughput — missed-schedule detection (liveness check on this counter) |
| `items_processed_total` | Counter | Processing throughput — KB pipeline liveness |
| `extraction_tokens_total` | Counter | LLM token consumption — flat-line signals extraction failures (no direct LLM error metric) |
| `errors_total` | Counter | Pipeline/API error rate tracking |
| `storage_bytes` | Gauge | KB storage usage — closest exported proxy for disk-usage alerting |
| `delivery_failures_total` | Counter | Failed deliveries — proxy for per-channel health (CD-007) |
| `billing_stripe_sync_failures_total` | Counter | Billing sync failures (Stripe) |
| `active_users` | Gauge | Active end-user profile count |

**Not exported** (spec-only; alerts referencing them cannot fire today):

| Metric | Type | Purpose |
|--------|------|---------|
| `autoinfo_backup_last_success_timestamp` | Gauge | Backup failure detection (CD-004) — requires new metric |
| `autoinfo_channel_health{channel, status}` | Gauge | Per-channel delivery health (CD-007) — requires new metric |

### 3.2 Alert Rules Specification

#### Alert Severity Levels

| Level | Name | Notification | Escalation | Response Time |
|-------|------|-------------|------------|---------------|
| **P0** | Critical / Page | PagerDuty page + SMS + on-call rotation | Escalate to manager if no ack in 15 min | **< 15 min** |
| **P1** | Warning / Email | Email to ops team + Slack channel | Escalate to P0 if unresolved in 4 hours | **< 1 hour** |
| **P2** | Info / Log | Logged to monitoring dashboard + daily digest | Reviewed in weekly ops review | **< 1 business day** |

#### Prometheus Alert Rules

File: `monitoring/prometheus/alerts.yml`

```yaml
groups:
  - name: autoinfo_critical
    rules:
      # P0: Disk space critically low (DB can't grow)
      - alert: DiskSpaceCritical
        expr: (node_filesystem_avail_bytes{mountpoint="/var"} / node_filesystem_size_bytes{mountpoint="/var"}) < 0.10
        for: 5m
        labels:
          severity: P0
          component: infrastructure
        annotations:
          summary: "Disk usage above 90% on {{ $labels.instance }}"
          description: "Available disk: {{ $value | humanize }}%. Database writes will fail if disk fills. Immediate action required."
          runbook: "§3.5 Runbook: DB Full"

      # P0: Backup has not succeeded in 36 hours
      # Note: `autoinfo_backup_last_success_timestamp` is NOT exported yet
      # (spec-only, see §3.1). This alert is dormant until the metric ships.
      - alert: BackupNotSucceeded
        expr: (time() - autoinfo_backup_last_success_timestamp) > 129600
        for: 1h
        labels:
          severity: P0
          component: backup
        annotations:
          summary: "AutoInfo backup has not succeeded in 36 hours"
          description: "Last successful backup was {{ $value | humanizeDuration }} ago. Risk of data loss exceeds RPO."
          runbook: "§3.5 Runbook: DB Full"

      # P0: Delivery failure volume exceeds 10 in 15 minutes.
      # `delivery_failures_total` is a pure failure counter (no success/failure
      # label split), so the alert fires on absolute failure volume.
      - alert: DeliveryFailuresHigh
        expr: increase(delivery_failures_total[15m]) > 10
        for: 5m
        labels:
          severity: P0
          component: delivery
        annotations:
          summary: "More than 10 delivery failures in 15 minutes"
          description: "End users may not be receiving products. Check delivery channels and the outbox."
          runbook: "§3.5 Runbook: Channel Down"

  - name: autoinfo_warning
    rules:
      # P1: Cron collection missed (no items collected in 2x expected interval).
      # No cron timestamp metric is exported — `items_collected_total` liveness
      # (rate == 0) is the proxy.
      - alert: CronCollectionMissed
        expr: rate(items_collected_total[2h]) == 0
        for: 30m
        labels:
          severity: P1
          component: cron
        annotations:
          summary: "No items collected in the last 2 hours"
          description: "Scheduled collection may have failed silently — no items were collected in 2 hours."
          runbook: "§3.5 Runbook: Cron Missed"

      # P1: LLM extraction stalled (no tokens consumed in 15m).
      # No direct LLM error metric exists — a flat `extraction_tokens_total`
      # is the proxy for failing extraction calls.
      - alert: LLMExtractionStalled
        expr: rate(extraction_tokens_total[15m]) == 0
        for: 10m
        labels:
          severity: P1
          component: llm
        annotations:
          summary: "LLM extraction stalled (no tokens consumed in 15m)"
          description: "LLM extraction may be failing. Check API key validity and provider status."
          runbook: "§3.5 Runbook: LLM API Failure"

      # P1: Delivery failures detected (any in 10 minutes).
      # No per-channel health metric is exported — `delivery_failures_total`
      # is the proxy (CD-007).
      - alert: DeliveryFailuresDetected
        expr: rate(delivery_failures_total[10m]) > 0
        for: 10m
        labels:
          severity: P1
          component: delivery
        annotations:
          summary: "Delivery failures detected in the last 10 minutes"
          description: "Delivered products may be silently dropped. Check the delivery log and channels."
          runbook: "§3.5 Runbook: Channel Down"

      # P1: KB processing stalled (no items processed in 1 hour).
      # No staleness metric is exported — `items_processed_total` flat-line is
      # the KB-liveness proxy.
      - alert: KBProcessingStalled
        expr: rate(items_processed_total[1h]) == 0
        for: 1h
        labels:
          severity: P1
          component: knowledge_base
        annotations:
          summary: "No KB items processed in the last hour"
          description: "The KB pipeline may be stalled. Check processing jobs and LLM availability."
          runbook: "https://wiki.internal/autoinfo/stale-content"

  - name: autoinfo_info
    rules:
      # P2: Error rate spike (5x baseline)
      - alert: ErrorRateSpike
        expr: |
          rate(errors_total[1h])
          >
          rate(errors_total[24h]) * 5
        for: 15m
        labels:
          severity: P2
          component: quality
        annotations:
          summary: "Error rate spiking"
          description: "Hourly error rate is 5x the 24h baseline. May indicate source quality change or extraction regression."

      # P2: Collection stalled (no items collected in 30 minutes).
      # No collection duration histogram is exported, so sustained zero
      # throughput stands in for latency issues.
      - alert: CollectionStalled
        expr: rate(items_collected_total[30m]) == 0
        for: 30m
        labels:
          severity: P2
          component: collection
        annotations:
          summary: "No items collected in the last 30 minutes"
          description: "Sources may be slow or unresponsive. Consider timeout adjustment or source health check."
```

### 3.3 PagerDuty / Webhook Integration

#### PagerDuty Integration (P0 Alerts)

Configure AlertManager to route P0 alerts to PagerDuty:

```yaml
# monitoring/alertmanager/config.yml
route:
  receiver: "default"
  routes:
    - match:
        severity: P0
      receiver: "pagerduty-critical"
      continue: true
    - match:
        severity: P1
      receiver: "slack-ops"
    - match:
        severity: P2
      receiver: "ops-dashboard"

receivers:
  - name: "pagerduty-critical"
    pagerduty_configs:
      - routing_key: "${PAGERDUTY_ROUTING_KEY}"
        severity: critical
        description: "AutoInfo P0 alert: {{ .CommonAnnotations.summary }}"
        details:
          runbook: "{{ .CommonAnnotations.runbook }}"
          alert_name: "{{ .CommonLabels.alertname }}"

  - name: "slack-ops"
    slack_configs:
      - api_url: "${SLACK_WEBHOOK_URL}"
        channel: "#autoinfo-ops"
        title: "AutoInfo P1: {{ .CommonAnnotations.summary }}"
        text: "{{ .CommonAnnotations.description }}\nRunbook: {{ .CommonAnnotations.runbook }}"

  - name: "ops-dashboard"
    webhook_configs:
      - url: "http://autoinfo-dashboard:8080/api/alerts"
```

#### Webhook Fallback (No PagerDuty)

For deployments without PagerDuty, use AutoInfo's own webhook delivery to push P0 alerts to all configured channels:

```python
# P0 alerts delivered via AutoInfo's existing delivery channel adapters
# Telegram Bot, DingTalk, FeiShu, WeChat Work — whichever is configured
ALERT_ROUTING = {
    "P0": ["pagerduty", "telegram", "sms"],
    "P1": ["email", "slack"],
    "P2": ["dashboard", "weekly_digest"],
}
```

### 3.4 Monitoring Dashboard (Ops View)

> **Cross-ref:** CD-013 (Live Operations Dashboard). Not a full admin panel — a focused ops dashboard.

**Implement as a Prometheus + Grafana stack** (industry standard, minimal custom code):

| Dashboard Panel | Metrics | Refresh | Alert |
|-----------------|---------|---------|-------|
| **System Health** | `diagnose_system` health score, disk usage, DB size | 30s | Disk > 85% |
| **Collection Status** | Active collections, collection rate, errors | 30s | Flat line > 2h |
| **Delivery Health** | Delivery rate by channel, failure rate | 30s | Failure rate > 10% |
| **LLM Usage** | Token consumption, cost, model distribution | 5m | Daily cost > budget |
| **KB Freshness** | Staleness ratio per domain, entry count by tier | 1h | Staleness > 50% |
| **Backup Status** | Last backup timestamp, size trend | 1h | Last backup > 36h |
| **Cron Status** | Last run per domain, next scheduled | 1h | Missed run |
| **Error Rates** | Gate failures, API errors, LLM errors | 5m | Spike > 5x baseline |

**Grafana dashboard JSON** committed to repo as `monitoring/grafana/autoinfo-ops-dashboard.json`.

### 3.5 Runbook Templates for Common Failures

Each runbook follows a standard format: Detection → Triage → Resolution → Verification.

---

#### Runbook: Cron Missed (P1)

**Detection:** `CronCollectionMissed` alert fires — `rate(items_collected_total[2h]) == 0` (no items collected in 2h).

**Triage (5 min):**
1. Check if crond is running: `systemctl status crond`
2. Check crontab registered: `crontab -l | grep autoinfo`
3. Check cron logs: `journalctl -u crond --since "2 hours ago" | grep autoinfo`
4. Check if collection process is hung: `ps aux | grep "autoinfo collect"`

**Resolution (15 min):**
- **crond stopped:** `systemctl restart crond`
- **Crontab missing:** `python -m autoinfo.cli cron install`
- **Collection hung:** Kill hung process (`kill -9 <pid>`), then manually trigger collection
- **Collection failed (error in log):** Fix root cause (source down, API key expired, disk full), then re-run

**Verification (5 min):**
1. Manually trigger: `python -m autoinfo.cli cron run --name <schedule>`
2. Verify items collected: `python -m autoinfo.cli status --domain <domain>`
3. Verify `items_collected_total` counter is advancing
4. Resolve alert in PagerDuty / monitoring

**If unresolved after 30 min:** Escalate to P0. Page on-call engineer.

---

#### Runbook: DB Full (P0)

**Detection:** `DiskSpaceCritical` alert fires. Disk usage > 90%.

**Triage (5 min):**
1. Identify space consumers: `du -sh /var/backups/autoinfo/*`, `du -sh autoinfo.db*`
2. Check for WAL file bloat: `ls -lah autoinfo.db-wal`
3. Check for old collection cache: `du -sh collections/`
4. Check for large log files: `du -sh logs/`

**Resolution (15 min):**
- **Old backups exceeding retention:** Manual cleanup of expired backup files: `find /var/backups/autoinfo/hourly -mtime +1 -delete`
- **WAL bloat:** Run `sqlite3 autoinfo.db "PRAGMA wal_checkpoint(TRUNCATE);"` to checkpoint and truncate WAL
- **Collection cache:** Run `python -m autoinfo.cli clean` to clear old cache files
- **Log files:** Rotate logs: `logrotate -f /etc/logrotate.d/autoinfo`
- **DB grown unexpectedly:** Run `sqlite3 autoinfo.db "VACUUM;"` to reclaim space (may take minutes on large DB)

**If disk > 95%:** Immediate action — stop collection services to prevent DB corruption: `systemctl stop autoinfo-collector`

**Verification (5 min):**
1. Re-check disk usage: `df -h /var`
2. Verify DB integrity: `sqlite3 autoinfo.db "PRAGMA integrity_check;"`
3. Trigger test collection to confirm writes work
4. Resolve alert

---

#### Runbook: Channel Down (P0/P1)

**Detection:** `DeliveryFailuresHigh` or `DeliveryFailuresDetected` alert fires.

**Triage (5 min):**
1. Identify affected channel from alert labels
2. Check delivery log for recent failures: `query_delivery_log` MCP tool (channel=`<channel>`, `since=1h`)
3. Check channel API status: external status page (Telegram, WeChat, DingTalk, Discord)
4. Check if channel credentials expired: review config files, test API key

**Resolution (15 min):**
- **Channel API down (external):** No action possible. Delivery will retry with exponential backoff. After 3 retries, fall back to email. Alert auto-resolves when channel recovers.
- **Credentials expired:** Update API key/token in config, run `python -m autoinfo.cli sources test --url <source-url> --type <type>`
- **Rate limited:** Reduce delivery frequency or batch deliveries. Check channel rate limit documentation.
- **Message formatting error:** Check adapter implementation against channel API docs. Fix and redeploy.

**Fallback strategy:**
1st failure → retry with 1 min delay
2nd failure → retry with 5 min delay
3rd failure → fall back to email + log error
All subsequent deliveries for this channel → routed to email until channel recovers

**Verification (5 min):**
1. Send test delivery: `python -m autoinfo.cli output digest --domain <domain> --dry-run`
2. Verify test delivery reaches channel
3. Verify `delivery_failures_total` counter is not increasing
4. Resume normal delivery routing

---

#### Runbook: LLM API Failure (P1)

**Detection:** `LLMExtractionStalled` alert fires — `rate(extraction_tokens_total[15m]) == 0`. Extraction/processing failures increasing.

**Triage (5 min):**
1. Check LLM provider status page (OpenAI, OpenRouter, DeepSeek, etc.)
2. Check API key validity: `curl -H "Authorization: Bearer $KEY" https://api.openai.com/v1/models`
3. Check rate limits: review provider dashboard for usage/rate limit hits
4. Check if fallback model is configured: review the `llm` section of `.autoinfo/config.yaml` (or `python -m autoinfo.cli doctor --verbose`)

**Resolution (15 min):**
- **Provider outage:** Swap to fallback model. AutoInfo's LLM config supports fallback chains:
  ```yaml
  llm:
    model: deepseek/deepseek-chat
    fallback_chain:
      - model: openai/gpt-4o-mini
        provider: openai
      - model: anthropic/claude-3-haiku
        provider: anthropic
  ```
  Run: set `llm.model: openai/gpt-4o-mini` in `.autoinfo/config.yaml` (or via the `configure_llm` MCP tool) and restart the service
- **API key expired/invalid:** Rotate key, update `AUTOINFO_LLM_API_KEY` env var, restart service
- **Rate limited:** Wait for rate limit window to reset. Reduce batch size in `process_collection`.

**Verification (5 min):**
1. Run test extraction: `python -m autoinfo.cli process --domain <domain> --batch-size 1`
2. Verify extraction succeeds with fallback model
3. Monitor `extraction_tokens_total` metric for recovery
4. Switch back to primary model when provider recovers

---

## 4. Scaling Strategy

> **Cross-ref:** CD-015 (Horizontal Scaling Strategy).
> **Current reality:** Single-node SQLite. Single Python process. All state in one file. Works for pilot/small-scale deployments (up to ~10 domains, ~100 topics, ~10 end users).
> **Migration triggers:** > 50 domains OR > 500 topics OR > 100 concurrent end users OR DB size > 1 GB OR write contention observed.

### 4.1 Current Single-Node Limitations

| Constraint | Limit | Symptom When Exceeded |
|------------|-------|----------------------|
| **SQLite single-writer** | 1 concurrent writer at a time | `SQLITE_BUSY` errors during concurrent collections |
| **SQLite WAL size** | WAL file grows under high write load | Disk usage spike, checkpoint latency |
| **Single process** | All collection + processing + API in one process | CPU saturation, request queuing |
| **No connection pooling** | Every DB access opens/closes connection | Connection overhead, file descriptor exhaustion |
| **In-memory Python** | All cached state lost on restart | In-flight jobs abandoned, no persistence |
| **No load balancing** | Single point of failure | Any crash = total outage |

**Safe operating envelope** (before migration needed):

| Metric | Safe Limit | Warning Threshold |
|--------|-----------|-------------------|
| DB size | < 1 GB | > 500 MB — start migration planning |
| Domains | < 50 | > 30 — start migration planning |
| Concurrent collections | < 5 | > 3 — add collection workers |
| End users | < 100 | > 50 — evaluate read replicas |
| Write ops/second | < 100 | > 50 — evaluate PostgreSQL |

### 4.2 Migration Path: SQLite → PostgreSQL

#### Phase 1: Database Abstraction Layer (Week 1-2)

Introduce a repository pattern that abstracts SQLite-specific queries behind a common interface. No PostgreSQL yet — just the abstraction.

```python
from abc import ABC, abstractmethod

class KBRepository(ABC):
    @abstractmethod
    async def insert_entry(self, entry: KBEntry) -> str: ...
    @abstractmethod
    async def search(self, query: str, domain: str) -> list[KBEntry]: ...
    @abstractmethod
    async def get_entry(self, entry_id: str) -> KBEntry | None: ...

class SQLiteKBRepository(KBRepository):
    # Current implementation, migrated to async
    ...

class PostgresKBRepository(KBRepository):
    # Future implementation using asyncpg
    ...
```

**Why this matters:** Once the repository interface exists, swapping SQLite for PostgreSQL is a configuration change, not a rewrite. The rest of the codebase queries through the interface.

#### Phase 2: PostgreSQL Schema Migration (Week 3-4)

**Tools:** Alembic for migrations. `pgloader` for initial data migration from SQLite.

**Schema highlights:**

| SQLite Feature | PostgreSQL Equivalent |
|---------------|----------------------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL PRIMARY KEY` |
| FTS5 full-text search | `tsvector` + GIN index (PostgreSQL native) |
| sqlite-vec vector embeddings | `pgvector` extension |
| JSON fields (TEXT) | `JSONB` column type |
| No concurrent writes | MVCC (native concurrency) |

**Data migration command:**

```bash
# One-time: dump SQLite, load into PostgreSQL
pgloader autoinfo.db postgresql://user:pass@host:5432/autoinfo
```

**Feature parity checklist:**

- [ ] KB entries CRUD (all tiers)
- [ ] Hybrid search (FTS5 → `tsvector`, vector → `pgvector`)
- [ ] Audit log (append-only, queryable)
- [ ] Cost logs (time-series queries)
- [ ] Delivery logs (partitioned by month for performance)
- [ ] User profiles & subscriptions
- [ ] Alert rules (YAML → config table)
- [ ] Domain/source/topic config (YAML → config table)

**Rollback plan:** Keep SQLite repository implementation alive. Toggle between backends via config flag. If PostgreSQL migration fails in production, flip back to SQLite.

#### Phase 3: Cutover & Validation (Week 5)

1. **Shadow mode** (1 week): Write to both SQLite + PostgreSQL. Read from SQLite only. Compare results. Fix discrepancies.
2. **Read cutover**: Route read queries to PostgreSQL. Write to both. Validate read results match.
3. **Write cutover**: Route writes to PostgreSQL only. Keep SQLite as cold backup for 1 week.
4. **Decommission SQLite**: Remove SQLite repository. Archive old SQLite DB to S3.

### 4.3 Connection Pooling (PgBouncer)

PostgreSQL has a process-per-connection model. AutoInfo's collection/processing workers can open many short-lived connections. PgBouncer sits between the application and PostgreSQL, pooling connections.

```
AutoInfo Workers ──→ PgBouncer (pool of 20 connections) ──→ PostgreSQL
```

**Configuration:**

```ini
# pgbouncer.ini
[databases]
autoinfo = host=127.0.0.1 port=5432 dbname=autoinfo

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
pool_mode = transaction        # Release connection after each transaction
max_client_conn = 100          # Max concurrent application connections
default_pool_size = 20         # Maintain 20 PostgreSQL connections in pool
reserve_pool_size = 5          # Additional connections when pool is exhausted
```

**Application connection string** changes from `postgresql://host:5432/db` to `postgresql://host:6432/db` (PgBouncer port). No code changes — SQLAlchemy/databases library handles pooling transparently.

### 4.4 Read Replica Architecture

Once PostgreSQL is the primary, add read replicas for KB queries (search, summaries, Q&A). Write operations (collection, processing, delivery) go to primary. Read operations (search, browse, dashboard) go to replicas.

```
                    ┌─────────────┐
                    │  PostgreSQL  │  ← Primary (writes)
                    │   Primary    │
                    └──────┬──────┘
                           │ streaming replication
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Replica 1│ │ Replica 2│ │ Replica  │ ← Read replicas
        │ (search) │ │  (API)   │ │  (dash)  │
        └──────────┘ └──────────┘ └──────────┘
```

**Routing rules:**

| Operation | Target | Reason |
|-----------|--------|--------|
| Collection, processing, delivery | Primary | Write-heavy |
| KB search, Q&A, summaries | Replica | Read-heavy, latency-tolerant |
| Dashboard queries | Replica | Can be stale (≤ 1 second lag acceptable) |
| Audit log writes | Primary | Append-only, must be durable |
| Cost log writes | Primary | Must be accurate for billing |

**Replication lag monitoring:** Alert if replica lag exceeds 5 seconds. Dashboard shows current lag.

### 4.5 Cache Layer (Redis)

**Purpose:** Cache frequently accessed data to reduce PostgreSQL load and improve response times.

**What to cache:**

| Cache Key | TTL | Invalidation |
|-----------|-----|-------------|
| `search:{domain}:{query_hash}` | 5 min | On new collection for domain |
| `summary:{summary_id}` | 1 hour | On summary update |
| `digest:{domain}:{period}` | 15 min | On new digest generation |
| `domain_config:{domain}` | 10 min | On config change (MCP `set_config`) |
| `user_prefs:{user_id}` | 30 min | On `update_preferences` |
| `channel_health:{channel}` | 1 min | On delivery attempt |

**Cache strategy:** Cache-aside (lazy loading). Application checks Redis first; on miss, queries PostgreSQL and populates Redis.

```python
async def get_summary(summary_id: str) -> Summary | None:
    cached = await redis.get(f"summary:{summary_id}")
    if cached:
        return Summary.from_json(cached)
    
    summary = await db.fetch_summary(summary_id)
    if summary:
        await redis.setex(f"summary:{summary_id}", 3600, summary.to_json())
    return summary
```

**Redis deployment:** Single Redis instance for pilot. Redis Sentinel for HA in production. Consider Redis Cluster if cache size exceeds single-node memory (> 32 GB).

### 4.6 CDN for Delivered Product Assets

Products delivered as HTML (digests, reports, presentations) include static assets (CSS, JS, images). Generated audio (TTS MP3 files) can also be cached.

**CDN strategy:**

| Asset Type | CDN TTL | Origin |
|-----------|---------|--------|
| Presentation HTML (Reveal.js) | 1 hour | AutoInfo API `/products/{id}` |
| Generated audio (MP3) | 24 hours | AutoInfo API `/products/{id}/audio` |
| Static assets (CSS, fonts) | 7 days | S3 bucket |
| Digest/report HTML | 15 min | AutoInfo API |

**Implementation:** Place CloudFront (AWS) or Cloudflare in front of the AutoInfo API. Configure cache behaviors based on URL path. Signed URLs for private products (subscriber-only content).

### 4.7 Horizontal Scaling: Stateless Workers + Shared DB

Once PostgreSQL + Redis + CDN are in place, the AutoInfo application can be horizontally scaled:

```
                     ┌──────────────┐
                     │   CDN / LB   │  (CloudFront / Nginx)
                     └──────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  API-1   │ │  API-2   │ │  API-3   │  (FastAPI, stateless)
        └──────────┘ └──────────┘ └──────────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Worker-1 │ │ Worker-2 │ │ Worker-3 │  (Background jobs)
        └──────────┘ └──────────┘ └──────────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   ┌──────────┐      ┌──────────┐       ┌──────────┐
   │PostgreSQL│      │  Redis   │       │   S3     │
   │(Primary) │      │ (Cache)  │       │(Backups) │
   └──────────┘      └──────────┘       └──────────┘
```

**Key architectural decisions:**

| Component | Scaling Model | Stateless? | Notes |
|-----------|--------------|------------|-------|
| **API servers** | Horizontal (N instances) | ✅ Yes | Route via load balancer. Session in Redis. |
| **Collection workers** | Horizontal (N instances) | ✅ Yes | Jobs dispatched via Redis queue. Worker claims job, processes, reports result. |
| **Processing workers** | Horizontal (N instances) | ✅ Yes | Same pattern as collection. LLM calls are stateless. |
| **Cron scheduler** | Single instance (leader election) | ❌ Must be singleton | Use Redis Redlock for leader election. Only the leader installs crontab and triggers schedules. |
| **PostgreSQL** | Vertical + read replicas | N/A | Primary scales up (bigger instance). Replicas scale out (more read capacity). |
| **Redis** | Sentinel / Cluster | N/A | Sentinel for HA. Cluster for scale beyond single node. |

**Job queue** (for background collection/processing):

Use Redis-backed queue (RQ / Celery with Redis broker). Workers pull jobs from queue:

```
Cron Scheduler → Enqueue "collect:medical-research:IVF" → Worker picks up → Executes collection → Reports result
```

**Worker autoscaling:** Scale collection workers based on queue depth. If > 10 pending jobs, add a worker. If idle > 10 min, remove a worker. Implement via Kubernetes HPA or simple process manager.

### 4.8 Scaling Roadmap Summary

| Phase | When | What | Effort | Risk |
|-------|------|------|--------|------|
| **Phase 0 (Current)** | Now | Single-node SQLite, single process | — | Single point of failure |
| **Phase 1** | DB > 500 MB OR domains > 30 | Repository abstraction layer | 1-2 weeks | Low (no behavioral change) |
| **Phase 2** | DB > 1 GB OR concurrent writes > 50/s | PostgreSQL migration | 3-4 weeks | Medium (data migration, feature parity) |
| **Phase 3** | End users > 50 OR search load high | Read replicas + Redis cache | 1-2 weeks | Low (additive, no migration) |
| **Phase 4** | Users > 100 OR delivery load high | Horizontal workers + CDN | 2-3 weeks | Medium (distributed cron, job queue) |
| **Phase 5** | Users > 1000 OR revenue > $10K/mo | Full distributed architecture | 4-6 weeks | High (multi-region, HA) |

**Trigger thresholds are guidelines, not hard limits.** Monitor the metrics in §4.1. Start migration planning when any two warning thresholds are crossed.

---

## 5. References

| Document | Relevance |
|----------|-----------|
| `cross-dimensional-catalog.md` | CD-004 (Cron Reliability), CD-007 (Channel Health), CD-013 (Ops Dashboard), CD-014 (Backup & DR), CD-015 (Scaling) |
| `specs/operations.md` §4 | Observability — Prometheus metrics, traceability, diagnostics |
| `specs/pipeline.md` | Collection and KB pipeline architecture |
| `specs/delivery.md` | Delivery channels, retry logic, SLA tracking |
| `specs/expectations.md` | F28-F29 (Cost), F36-F39 (Lifecycle), F40-F44 (Observability) |
| `AGENTS.md` | MCP tool catalog — backup/DR tools to implement |

---

> **Implementation notes:**
> - This entire document is a **spec**, not implemented. All procedures are designed for future execution.
> - **Status 2026-08-04:** Partially implemented — SQLite backup (`scripts/backup-db.sh`), cron health (`autoinfo cron health`), and channel health (`get_channel_health`) are shipped; remaining items spec-only.
> - Single-person operations team is assumed. Procedures are designed for minimal manual intervention.
> - All bash scripts and config files should be committed to `scripts/operations/` and `monitoring/` respectively.
> - PagerDuty is recommended but optional. Webhook fallback uses AutoInfo's own delivery channels.
> - Scaling strategy is intentionally conservative. Prefer vertical scaling (bigger server) until PostgreSQL migration is necessary.
