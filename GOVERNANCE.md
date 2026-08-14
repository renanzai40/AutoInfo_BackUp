# AutoInfo Governance

This document describes how the AutoInfo open-source project is run. It is a
lightweight governance model for a small maintainer team, written in the
spirit of Minimum Viable Governance (MVG): process is added only when a
concrete pain point appears, and every rule here exists because a real problem
motivated it. When in doubt, prefer the lighter option.

## Project model

AutoInfo is an agent-first, domain-agnostic information tracking and knowledge
base platform. Users configure sources and topics; AutoInfo handles the rest:
automated collection, LLM-based structured extraction, summarization, and a
queryable knowledge base. It is MIT licensed and developed openly on GitHub.

### Roles

There are three roles, deliberately flat:

- **Maintainer**: a person (or small group of 1-3 people) with write access to
  the repository. Maintainers triage issues, review and merge pull requests,
  manage releases, and make final decisions. The maintainer team owns the
  project's direction.
- **Contributor**: anyone who opens an issue, comments, or submits a pull
  request. Contributions are welcome regardless of experience level. See
  `CONTRIBUTING.md` for how to contribute, and `CODE_OF_CONDUCT.md` for the
  standards every interaction must meet.
- **User**: anyone who runs AutoInfo or consumes its output. Users are not
  required to participate in development, but their feedback is the project's
  main compass.

## Decision-making

Maintainers make decisions by **lazy consensus**: a proposal is accepted once
it has been discussed and no maintainer has objected within a reasonable
period (usually 72 hours for non-trivial changes). Any maintainer may call a
vote. Objections must be specific and actionable rather than general
disagreement.

Non-trivial architecture decisions must be recorded as an Architecture
Decision Record (ADR) in `docs/adr/`, following `docs/adr/TEMPLATE.md`. The
ADR rules:

- **ADR numbers are never reused.** If a decision changes, write a new ADR.
- **Accepted ADRs are never rewritten in place.** If a decision is
  superseded, write a new ADR and mark the old one `Superseded by NNNN`.
- An ADR is required when a change alters an architecture rule (the KB
  pipeline, collection pipeline, quality gates, delivery), introduces a
  non-obvious trade-off, or has a wide blast radius (MCP surface, REST
  envelope, storage schema, LLM call paths).

## Issue triage

AutoInfo follows the mature-project label taxonomy. Every new issue starts
with `needs-triage`; a maintainer applies labels and removes that status once
the issue is understood. Labels fall into four independent groups, and an
issue may carry one label from each:

| Group | Labels | Meaning |
|-------|--------|---------|
| **Status** | `needs-triage` | New issue, not yet reviewed |
| | `triage/accepted` | Issue is real, agreed, ready for work |
| | `in-progress` | Someone is actively working on it |
| **Kind** | `bug` | Definite defect, unexpected behavior |
| | `feature` | New capability that does not exist |
| | `enhancement` | Improvement to an existing capability |
| | `docs` | Documentation defect or gap |
| | `regression` | Behavior that broke after a release |
| **Priority** | `critical-urgent` | Blocks use; data loss or security impact |
| | `important-soon` | Significant; should land in the next release window |
| | `important-longterm` | Valuable but not time-bound |
| | `backlog` | Tracked, not scheduled |
| **Meta** | `duplicate` | Already tracked in another issue |
| | `wontfix` | Accepted decision not to address |
| | `needs-info` | Awaiting details from the reporter |
| | `help-wanted` | Good for outside contributors |
| | `good-first-issue` | Welcoming for first-time contributors |

A `bug` that is also a regression carries both labels. `help-wanted` and
`good-first-issue` are set by maintainers, not by reporters. Security reports
follow `SECURITY.md` instead of the normal triage flow.

## Response SLA

Maintainers commit to the open-source-guide baseline: every issue or pull
request receives a **human first response within 7 days** of being opened.
Beyond that baseline, first response is prioritized by the Priority label:

| Priority | First human response |
|----------|----------------------|
| `critical-urgent` | within 24 hours |
| `important-soon` | within 3 days |
| `important-longterm` | within 7 days |
| `backlog` | within 14 days |

A response means a maintainer has acknowledged the report and said what
happens next, not necessarily that it is resolved. `SECURITY.md` overrides
these windows with faster commitments for vulnerability reports.

## Stale policy

AutoInfo does **not** use an aggressive stale bot, and this is a deliberate,
documented decision. Community research is clear that auto-closing bots
backfire: Gradle retired its stale bot after community backlash, when issues
were closed automatically without a human ever weighing in. The cost of a few
quiet issues is lower than the cost of alienating reporters.

- **Initial state**: no stale bot. Issues and pull requests stay open until a
  human acts.
- **Revisit trigger**: adopt one only if abandoned pull requests pile up and
  the backlog becomes unmanageable.
- **If ever added**, the configuration must be conservative: mark after 360
  days, close only 30 days after marking, and always exempt `bug` and
  `good-first-issue` labels from both marking and closing.

## Pull request review policy

CI is the gatekeeper. Every pull request must pass the required status checks
in `.github/workflows/ci.yml`: `lint` (ruff), `mypy-changed-files`, and
`test` (pytest). Reviewers focus on substance, not on style trivia that CI
already covers.

- **One required reviewer** is the sweet spot for a team of this size. More
  reviewers slow the loop without adding safety; zero reviewers ships bugs.
- **Draft pull requests are assumed not ready.** Do not review a draft unless
  explicitly asked; a draft means the author wants feedback later.
- **Small pull requests are strongly preferred.** A request that takes more
  than a few hundred lines to review will likely be asked to split.
- **First-time contributors get extra warmth.** GitHub auto-classifies
  first-time contributors; the maintainer posts a welcome comment, points at
  `good-first-issue`, and walks through the process step by step. Reviewing a
  first PR is a teaching act, not just a gate.
- **Cross-cultural review guidance**: be explicit about what blocks the merge
  and what does not. Label blocking feedback separately from optional polish,
  for example `Blocking:` versus `Nit:`. Short, direct English can read as
  rude to non-native speakers; one sentence of context costs little and
  prevents friction.

## Merge strategy and branch protection

- **Default to squash-and-merge.** Every merged pull request becomes one
  clean commit on `main`, keeping history linear and blame useful. Other
  merge strategies are disabled, matching GitHub's own recommendation for
  default-branch hygiene.
- **Branch protection on `main`** requires:
  - A pull request before merging (no direct pushes)
  - At least 1 approval
  - Passing status checks: `lint`, `mypy-changed-files`, `test`
  - Dismissing stale approvals when new commits are pushed
  - Branches up to date before merging

## Developer Certificate of Origin (DCO)

All contributions require a sign-off: `git commit -s`, affirming the Developer
Certificate of Origin (<https://developercertificate.org/>). The DCO app
(<https://github.com/apps/dco>) enforces this check once installed; a pull
request whose commits lack sign-off fails the check until the author amends
them.

Sign-off exists for legal provenance. AutoInfo is MIT licensed, and
maintainers need a clear chain of who contributed what and under what
authority. A DCO is lighter than a Contributor License Agreement and is the
standard practice for MIT projects.

## CODEOWNERS

`.github/CODEOWNERS` maps paths to owning maintainers. It auto-requests review
from the matching owners when a pull request touches their paths, and with the
"Require review from Code Owners" branch-protection setting it makes that
review mandatory. Pitfalls to remember:

- **Last match wins**: CODEOWNERS is processed in file order, and the most
  specific matching pattern determines the owner. Put broad patterns first.
- **Owners need write access**: entries must resolve to users or teams with
  write permission to the repository, or the auto-review request fails.

## Release management

Releases use **release-please** with **Conventional Commits**, producing
semantic versioning (semver) from commit messages:

- `feat:` bumps the minor version; `fix:` bumps the patch version; breaking
  changes (a `BREAKING CHANGE` footer or a `feat!:` prefix) bump the major
  version.
- release-please opens a **release PR** that batches the accumulated changes
  into a single release with a generated changelog. Maintainers review and
  merge it; merging tags the release and publishes the package.
- Feature work lands on `main` continuously. Only maintainers merge release
  PRs.

## Change control

Documentation changes that affect the acceptance framework or its evidence
catalog require director approval per AC7; they are not self-approvable. See
`docs/dev/acceptance-framework.md` for the acceptance mechanism (AC1-AC9)
and its change-control rules.
