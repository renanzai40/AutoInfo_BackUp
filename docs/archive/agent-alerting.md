# Agent Proactive Alerting

> **Note**: As of v1.6, AutoInfo also supports **config-based alert rules** via `alerts.py`
> (`add_alert_rule`/`get_alert_rule`/`remove_alert_rule` MCP tools) with threshold-based triggers
> and auto-remediation actions. The polling pattern below remains valid for source health checks;
> for cost/budget/knowledge-lifecycle alerts, prefer the config-based rule system.
> See `docs/dev/specs/operations.md` for cost alert rules.

## Pattern

Agents should proactively monitor source health by polling `get_source_health()`
before each collection run or on a regular timer. AutoInfo does not push
notifications -- agents are expected to poll state on their own schedule.

## Detection Rule

If `error_count >= 3` (3 consecutive failures), flag to the user:

> Source "PubMed API" has failed 3 consecutive times with timeout errors.
> Would you like me to investigate or remove this source?

## Workflow

1. Agent calls `list_sources(domain)` to enumerate active sources for a domain
2. For each source, agent calls `get_source_health(source_id)` using the
   `domain:name` identifier format (e.g. `medical-research:pubmed`)
3. Agent inspects `error_count` and `status` in the response
4. If `error_count >= 3` or `status == "error"`, agent proactively notifies the
   user with specific details (error count, last error, source name)
5. User can then investigate (via `test_source`) or remove the failing source

## MCP Tool Reference

### `get_source_health`

**Description**: Return health status for a single source.

**Input**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_id` | string | Source identifier in `domain:name` format (e.g. `medical-research:pubmed`). Returned by `add_source` in the response. |

**Return value**: A dictionary with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | string | Echoes the input source identifier |
| `status` | string | One of: `healthy`, `degraded`, `error`, `paused`, `unknown` |
| `last_success` | string (ISO datetime) or null | Timestamp of the last successful collection run |
| `error_count` | integer | Number of consecutive failures |
| `avg_response_time_ms` | number or null | Average response time in milliseconds |

**Status meanings**:

| Status | Condition |
|--------|-----------|
| `healthy` | Last run succeeded, < 3 consecutive failures |
| `degraded` | Last run failed (< 3 consecutively) or slow response |
| `error` | 3+ consecutive failures -- needs attention |
| `paused` | `_paused` marker file exists (user-disabled) |
| `unknown` | No runs recorded yet |

### `list_sources`

Returns all configured sources for a domain. Use this to discover source IDs
before polling health for each one.

## No Server-Push

AutoInfo does **not** implement server-push alerting. This is a deliberate
design decision:

- **Simplicity**: No websocket long-poll, no webhook delivery for alerts
- **Agent responsibility**: Agents decide when and how to check health
- **Flexibility**: Different agents can use different polling strategies
  (time-based, pre-collection, post-failure)

The pattern is always: **agent polls, agent decides, agent reports**.

## Example Agent-User Dialogue

### Scenario: 3 consecutive failures detected

> **Agent**: Source "PubMed API" (`medical-research:pubmed`) has failed 3
> consecutive times. Status: `error`. The last successful run was 2026-07-20
> and all runs since then have timed out.
>
> Would you like me to investigate by testing the source, or should I remove
> it from the domain configuration?

> **User**: Investigate -- test the source and report back.

> **Agent**: (calls `test_source(url="...", type="api")`) ... The source is
> reachable (200ms response) but returning HTTP 503. This looks like a
> temporary server-side issue. I'd recommend waiting 24 hours and retrying.
> Would you like to pause the source for now?

> **User**: Yes, pause it.

> **Agent**: Marking `medical-research:pubmed` as paused. I'll check again
> in 24 hours and unpause if the source recovers.

### Scenario: Pre-collection health check

> **Agent**: Running pre-collection health check for domain
> `ai-commercial`... All 4 sources healthy. Proceeding with collection.

> **Agent**: (calls `collect_sources(domain="ai-commercial")`) ...
> Collection complete. 12 new items from 4 sources.

## Implementation Notes for Agents

1. **Poll before collect**: Call `get_source_health` for each active source
   before `collect_sources`. This avoids wasting resources on broken sources.

2. **Batch polling**: For domains with many sources, call `list_sources` once
   then iterate. There is no batch health endpoint -- poll individually.

3. **Status transitions**: A source can transition from `error` back to
   `healthy` after a successful run. Agents should re-check after each
   collection cycle and unpause or announce recovery.

4. **Graceful degradation**: If a source is `degraded` (1-2 failures), agents
   may still collect from it but should note the degraded state in reporting.

5. **Human notification**: Only alert the user on `error` (3+ failures).
   `degraded` and `paused` are informational and can be included in periodic
   status summaries without interrupting the user.
