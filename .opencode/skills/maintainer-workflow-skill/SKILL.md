---
name: maintainer-workflow-skill
description: "AutoInfo maintainer SOP — issue triage, PR review, and merge decision tree for the OSS repo. Load when acting as a maintainer: triaging issues, reviewing PRs, deciding merge/close, applying labels, or preparing releases."
author: AutoInfo
version: 1.0.0
---

# AutoInfo Maintainer Workflow Skill

## Purpose

This skill encodes the maintainer triage → review → merge decision tree so
agent-maintainers and human maintainers act consistently on the same repo.
Canonical policy lives in `GOVERNANCE.md` (created alongside this skill); the
contribution rules live in `CONTRIBUTING.md`. This skill is the loadable
procedure: when policy and this skill disagree, `GOVERNANCE.md` wins and this
skill gets updated.

Every rule here is grounded in real repo artifacts: the issue template
(`.github/ISSUE_TEMPLATE/bug_report.md`), the CI gates
(`.github/workflows/ci.yml`), the PR title gate (`pr-title-check.yml`), the
release automation (`release-please.yml`), the ADR process
(`docs/adr/README.md`), and the agent constraints in `AGENTS.md`.

## When to load

- **Triaging issues** → apply Kind/Priority/Meta labels, decide close vs. wait.
- **Reviewing a PR** → check CI, title, scope, docs, then approve or request changes.
- **Merging** → verify merge preconditions, squash-merge, dismiss stale approvals.
- **Applying labels** → first-triage and re-triage sweeps.
- **First-contributor welcome** → gentle guidance, no blocking nit-picking.
- **Release preparation** → review the release PR that release-please opens.

## Issue triage

Flow: every issue starts as `needs-triage`. One pass, then it leaves that label.

1. **Verify template compliance.** Bug reports MUST fill the 回归场景 (regression
   scenario) field naming a scenario under `src/autoinfo/mcp/scenarios/regression/`
   or "none (will add in PR)". Missing → `needs-info`, ping the reporter. Not
   using the template → restructure or close with a link to it.
2. **Classify Kind.** One of `kind/bug`, `kind/feature`, `kind/enhancement`,
   `kind/docs`, `kind/regression`. A regression report should reference the
   issue that introduced the behavior.
3. **Set Priority.** `priority/critical-urgent` (blocks a release or corrupts
   the KB), `priority/important-soon`, `priority/important-longterm`,
   `priority/backlog`.
4. **Apply Meta labels.** `meta/duplicate`, `meta/wontfix`, `meta/needs-info`,
   `meta/help-wanted`, `meta/good-first-issue`.

SLA for the first human response:

| Priority | First response |
|----------|----------------|
| critical-urgent | within 24 hours |
| everything else | within 7 days |

Close rules:

- **Missing info** → `meta/needs-info`, ping, close after one unanswered round.
- **Duplicate** → close, link the original issue, thank the reporter.
- **Wontfix** → close with explicit rationale in this order: thank → explain
  the scope mismatch → suggest a concrete improvement → link relevant docs.
  If the same request recurs, update the documentation so the answer is findable.

## PR review

CI is the gatekeeper. Never manually re-review what CI already catches. The
required jobs in `ci.yml` are ruff on changed Python files, mypy on changed
Python files, and the fast pytest subset (`pytest -m "not real_api"`, TERM=dumb).
Before treating red CI as a regression, read `tests/TRIAGE.md`: 12 documented
M1-deferred envelope failures (#73, #74-83, #84) are known and cleared by
M1T11-12.

1. **Title conforms.** `pr-title-check.yml` enforces Conventional Commits
   (`type(scope): subject`, breaking `!` allowed). Exempt: dependabot, Merge,
   and Release titles. The title becomes the squash-merge commit, so it must be
   right at PR time, not patched after merge.
2. **Issue linked.** `Fixes #N` in the body.
3. **Release-note block filled.** "NONE" is valid for small/CI/docs changes;
   otherwise summarize the user-visible impact.
4. **回归场景 provided** for bug fixes, matching the issue field or added in the PR.
5. **Docs updated** if behavior changed (see `doc-manager-skill` §2 dependency map).
6. **ADR added** if the change alters an architecture rule, picks between viable
   alternatives, or has a wide blast radius (`docs/adr/README.md`).
7. **AI-assistance disclosed** if the author used an agent to write code.

Review posture:

- **Solo-maintainer mode: no required human approval.** The `main-protection`
  ruleset runs `required_approving_review_count: 0` (GitHub structurally blocks
  self-approval, so a non-zero count would deadlock every merge). The CI gate
  is the review: ruff, mypy, pytest subset, title check, coverage gate, DCO.
  If a second trusted maintainer joins, raise the count to 1 — no other change.
- Draft PRs are not ready for review; say so and wait for "ready for review".
- Label every comment `blocking` or `nit` explicitly. This keeps feedback
  unambiguous across cultures and language barriers.
- First-contributor PRs get a welcome comment and gentle guidance. Hold the
  hard standards, apply them kindly.
- Small-PR principle: reject large style refactors. Code readability is
  subjective; large-scale stylistic changes add noise. If the diff is mostly
  reformatting, ask for it to be split or dropped.

## Merge decision

Only merge when ALL of these hold (the ruleset enforces 1-3):

1. CI green (ruff, mypy, fast pytest subset, coverage gate, DCO).
2. PR title conforms (the title IS the commit).
3. PR is a pull request into `main` (no direct pushes) and up to date
   (strict status checks).
4. Release-note block filled.
5. No unresolved blocking comments (review threads must be resolved).

- **Squash-merge is the default.** Individual commits need not be perfect; the
  squashed message is the history. Squash keeps `main` linear and makes
  release-please's changelog grouping work.
- **The author merges their own PR once CI is green** (solo-maintainer mode).
  No `--admin` needed: the ruleset has no bypass actors and approval count is
  zero, so a clean PR merges normally.
- **Never merge a PR with unresolved blocking comments**, even if CI is green.

## Agent-specific maintainer constraints

Translated from the `AGENTS.md` MUST NOT table and scoped to maintainer
actions. These are hard constraints; violating them produces incorrect behavior.

| Constraint | Reason |
|-----------|--------|
| Never demote or delete 03-Wiki entries | 03-Wiki is append-only. Tag `status: deprecated` only on explicit human command. |
| Never create a Draft from outside 01-Raw | 01-Raw is the sole entry point; Draft must come from Raw. |
| Agent promotion Draft→Wiki has no human gate | Promotion is a production step executed by the agent (ADR-0002). |
| Never modify `.autoinfo/config.yaml` directly | Use MCP tools (`add_source`, `add_topic`, `configure_llm`). |
| Never run `autoinfo doctor` | Use `diagnose_system()` MCP tool; it returns structured health data. |
| Never manage raw API keys | `configure_llm()` stores an env var reference (`${AUTOINFO_LLM_API_KEY}`), never the key. |
| Never delete source or domain config | Humans decide what sources and domains to remove. |

## Release process

release-please (`release-please.yml`) watches `main`. Squash-merges plus
Conventional Commit titles are its input contract:

- `fix:` → patch bump
- `feat:` → minor bump
- `BREAKING CHANGE` (title `!` or footer) → major bump
- A release PR batches the accumulated changes. Merging it bumps
  `src/autoinfo/_version.py`, updates `CHANGELOG.md`, tags the commit, and cuts
  the GitHub release. Nothing in that workflow is ever edited by hand.

Maintainer duty at release time: review the release PR like any other, confirm
the changelog sections match the merged conventional commits, and never
hand-edit `CHANGELOG.md` outside a release PR.

## Decision rules for adding heavy process

From the governance philosophy in `GOVERNANCE.md`: do not add process until
pain appears. Each symptom gets a specific, minimal cure:

| Symptom | Cure |
|---------|------|
| Duplicate issue flood | Stricter issue templates + `meta/duplicate` labeling discipline |
| Wrong reviewers on security-sensitive files | `CODEOWNERS` entries for those paths |
| Merges keep breaking `main` | Strict status checks + up-to-date requirement (already enforced by the ruleset) |
| Abandoned PR pile | Conservative stale bot: mark stale at 360 days, close at 30 days, exempt `kind/bug` and `meta/good-first-issue` |
| Recurring wontfix requests | Update the docs, do not re-litigate the issue |

**Never** run an aggressive stale bot (short mark/close windows). Abandoned
work is recoverable; closed PRs are not. Process exists to serve contributors,
not the other way around.

## Verification checklist

Before declaring a maintainer action complete:

1. Issue: has labels (Kind + Priority + Meta where applicable), an SLA-compliant
   first response, and a close reason if closed.
2. PR: CI green, title conforms, issue linked, release-note filled, 回归场景 for
   bugs, docs/ADR updated where required, every comment labeled blocking/nit,
   no unresolved blocking comments.
3. Merge: squash-merge used, stale approvals dismissed, no manual history edits.
4. No MUST NOT constraint from the table above was violated.
5. First-contributor interaction ended with a welcome and clear next steps.
