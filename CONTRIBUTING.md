# Contributing to AutoInfo

Welcome. AutoInfo is a universal information tracking and knowledge base
platform: you configure sources and topics, and AutoInfo handles collection,
LLM-based structured extraction, summarization, and a queryable knowledge
base. It is domain-agnostic (13 demo domains are configurations, not
hardcoded features), agent-native (145 MCP tools across 35 categories), and
BYOK (bring your own LLM keys).

AutoInfo is operated agent-first, but it is built and reviewed by humans. The
repo's internal agent rules live in `AGENTS.md`; this guide translates those
rules into human-actionable steps, so you never need to read the agent guide
to contribute. Where a rule matters for your contribution, this document
tells you exactly what to do.

## Code of Conduct

Please read and follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) in all
interactions. Be kind, be specific, and assume good faith.

## Getting started

Prerequisites:

- Python >= 3.11
- git
- a GitHub account

Setup:

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<you>/autoinfo.git
cd autoinfo

# 2. Point at the upstream repo
git remote add upstream https://github.com/1StepMore/AutoInfo.git

# 3. Create a virtualenv and install in editable mode with dev extras
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. Verify the project works
make test
make lint
```

- `make test` runs the full suite (`pytest -v`). The suite is roughly 3728
  tests; every test is bounded by pytest-timeout at 180 seconds so a hang
  fails fast instead of stalling the run.
- `make lint` runs `ruff check src/ tests/` followed by `mypy src/`.
- `make dev-install` is the Makefile equivalent of `pip install -e ".[dev]"`.
- `make lint-fix` autofixes style issues with ruff.

For a faster loop during development, run the fast subset with
`pytest -m "not real_api"` (the `real_api` tests hit live external services
and need API keys), or `pytest -m "not slow"` to skip the slow nested
subprocess re-runs. See the README [Quick Start](README.md#quick-start) for
a walkthrough of the first commands (`autoinfo init`, `autoinfo collect`,
`autoinfo process`), and smoke-test a running instance over REST:

```bash
autoinfo init --demo medical-research
curl http://localhost:8741/health
```

## Finding work

- Issues labeled `good first issue` are curated for newcomers.
- Issues labeled `help wanted` are open for anyone.
- Browse the open issues and pick one you can reproduce.
- For questions and ideas that are not issues yet, start a
  [Discussion](https://github.com/1StepMore/AutoInfo/discussions).

Before you start, comment on the issue so maintainers and other contributors
know you are working on it and nobody duplicates the work.

## Development workflow

Branches:

- `fix/<slug>` for bug fixes
- `feat/<slug>` for new features
- `docs/<slug>` for documentation changes

Small PRs principle:

- Keep PRs small and focused. One PR does one thing.
- Break large changes into a series of smaller patches that each merge
  cleanly.
- Do not mix refactors into bug fixes.
- Do not submit large-scale stylistic refactors. Code readability is
  subjective, and broad style churn pollutes git history and makes reviews
  noisy.

## Commit conventions

AutoInfo uses [Conventional Commits](https://www.conventionalcommits.org/),
with an important nuance: the project merges via **squash-merge**. Individual
commits inside your PR branch do not need to follow the spec, because they
collapse into a single squashed commit on merge. What matters is the **PR
title**, which becomes that squashed commit. CI enforces this with a
`pr-title-check` workflow.

Required prefix:

| Prefix | Use for |
|--------|---------|
| `fix:` | a bug fix |
| `feat:` | a new feature |
| `docs:` | documentation |
| `refactor:` | a code change that neither fixes a bug nor adds a feature |
| `perf:` | a performance improvement |
| `test:` | adding or fixing tests |
| `chore:` | tooling, dependencies, housekeeping |
| `BREAKING CHANGE:` | a breaking change (or `!` after the prefix, e.g. `feat!: ...`) |

Examples of good PR titles:

```text
fix: guard _cache_items against int item ids
feat: add bundle export to the output CLI
docs: clarify 01-Raw sole entry rule in AGENTS.md
```

A good title reads like a sentence describing the change. If a title is
unclear, a maintainer will ask you to reword it.

## Coding standards

- Python >= 3.11.
- ruff with `select = ["E", "F", "I", "N", "W"]` and `line-length = 100`.
- mypy in **strict** mode (`python_version = "3.11"`, `strict = true`).
- Type annotations on public functions and non-trivial internals.
- Prefer small modules that do one thing well, following the existing layout
  under `src/autoinfo/`. New CLI groups mirror MCP tools (the CLI has 28
  command groups).
- Avoid `# type: ignore`; if you must add one, explain why in a comment.

A short example that satisfies ruff and strict mypy:

```python
def truncate(text: str, limit: int = 100) -> str:
    """Truncate text to `limit` characters, adding an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
```

A pre-commit config is provided; if you use pre-commit, run
`pre-commit install` once so hooks run on every commit.

## Testing

All changes need tests:

- New features need tests that exercise the new behavior.
- Bug fixes need a regression scenario (below).
- Run targeted tests while developing, e.g. `pytest tests/test_cli_commands.py`.
- Run the full suite (`make test`) and the linter (`make lint`) before
  pushing. CI runs the same checks.

### The 回归场景 (regression scenario): what makes AutoInfo different

AutoInfo has a practice that is rare in open source, and we are proud of it:
**every bug fix must ship a validation scenario that guards against the bug
returning.**

The project maintains 112 validation scenarios (64 functional + 48 regression)
under `src/autoinfo/mcp/scenarios/`. Regression scenarios live in
`src/autoinfo/mcp/scenarios/regression/` and are marked `category: regression`
plus `regression: true`. They auto-load via recursive glob and run through
real MCP, CLI, or REST calls, asserting on the `{success, data}` envelope.

The bug report template has a mandatory 回归场景 (regression scenario) field:
when you open a bug report, you name the scenario that will guard the fix.
When you submit the fix, you add that scenario in the same PR. The existing
suite shows the naming convention: `regression-collect-int-id` (#104),
`regression-llm-key-resolution` (#119), `regression-period-enum` (#126),
`regression-report-structure` (#121), `regression-source-301` (#135), and
`regression-product-routing`.

A regression scenario is not extra paperwork. It is the insurance that your
fix stays fixed, and it keeps every future contributor safe to touch the code
you changed. `scripts/coverage_audit.py` tracks the count ("Regression
scenarios: N").

A minimal valid skeleton, matching the real schema:

```yaml
name: regression-my-fix
description: "Regression #NNN: short description of the fixed behavior"
category: regression
regression: true
regression_issue: "#NNN"
steps:
  - name: "exercise the fixed behavior through the CLI"
    kind: cli
    command: |-
      python3 -c '
      from autoinfo.something import the_fixed_function
      assert the_fixed_function(input_value) == expected
      print("REGRESSION_OK")
      '
    expect:
      success: true
      exit_code: 0
      stdout_has: ["REGRESSION_OK"]
```

Authoring rules live in
[`docs/dev/validation-scenario-contract.md`](docs/dev/validation-scenario-contract.md).
Run your scenario with the `list_validation_scenarios` /
`run_validation_scenario` tools or the validation-runner workflow, and prove
it fails before your fix and passes after.

## Documentation requirements

Code changes and documentation go together. When you change behavior, update
the docs that describe it; the dependency map in the doc-manager conventions
tells you which docs own which code. Highlights:

- `README.md`: feature list, Status table, CLI table, tool counts.
- `AGENTS.md`: only when you change architecture rules, the MCP surface, CLI
  groups, or quantitative facts (MCP tool count, test count, scenario count).
- `CHANGELOG.md`: via your PR's release-note block; do not hand-edit version
  entries.
- `docs/dev/specs/`: the spec that owns the changed topic.
- Non-trivial architecture changes must be recorded as an Architecture
  Decision Record (ADR) in `docs/adr/` (copy
  [`docs/adr/TEMPLATE.md`](docs/adr/TEMPLATE.md); see
  [`docs/adr/README.md`](docs/adr/README.md) for when one is needed and how
  to write one).

After editing any doc, regenerate the inventory and check consistency:

```bash
python3 scripts/doc_inventory.py
python3 scripts/doc_inventory.py --check
```

## AI contribution policy

AutoInfo is operated agent-first: internally, AI agents do much of the
day-to-day work under human direction. Externally, we welcome AI-assisted
contributions, held to the same standard we apply to ourselves: **disclosure
and human review**.

If your PR was created with significant AI assistance (generated or
substantially drafted by an AI tool):

1. **Disclose it.** State in the PR description which parts were AI-assisted
   and which tool was used.
2. **Review and modify every line before submitting.** You are responsible
   for the code: read it, understand it, and adjust it so it fits the
   project's standards and your own judgment.
3. **Take full responsibility** for correctness, licensing, and security of
   the contribution, exactly as with hand-written code.

We trust contributors. But the disclosure and review standard is enforced:
repeated violations (two strikes of undisclosed or unreviewed AI-generated
code) lead to a contribution ban. If you are unsure whether disclosure is
needed, disclose anyway; it costs one line in the PR description. This policy
follows the model used by major projects such as pandas and scikit-learn.

## Review process

- **CI is the gatekeeper.** ruff, mypy, pytest, the Conventional-Commits title
  check, the coverage gate, and DCO are required checks; a PR that fails them
  does not merge. Run `make lint` and `make test` locally before pushing.
- AutoInfo is currently a solo-maintained project, so the author can merge
  their own PR once all checks pass (GitHub blocks self-approval, so requiring
  human approvals would deadlock the repo). Reviews and comments from
  contributors are still very welcome; see `GOVERNANCE.md`.
- Open a **draft PR** early to get feedback while you iterate, and mark it
  ready when checks pass.
- When a reviewer comments, respond to each thread: agree and fix, or explain
  why you disagree. Follow-up commits are fine; history is squashed on merge.
- First-time contributors: we are glad you are here. Maintainers aim to
  respond to your PR within 7 days. If nobody has replied after a week, ping
  the thread; a gentle mention is fine.

## Issue triage SLA

Maintainers commit to a **first human response within 7 days** on every
issue. The response may be a clarifying question, a triage decision, or a
fix; it will not be silence. Issues that are duplicates, out of scope, or
already fixed are closed with an explanation. If an issue has had no human
response after 7 days, ping the thread to surface it again.

## Close discipline: verify on real products before closing

A fix is **not** done when its regression scenario turns green. Regression
scenarios run on mock/synthetic or local data and cannot catch problems that
only surface in real generated products (stale config, live source quirks,
residual placeholders). Before closing an issue whose fix touches output or
collection behavior:

1. After the fix merges, run `validate --matrix` (or `run_validation_scenario`
   against the real generation path) on a freshly generated product for the
   affected domain/product.
2. Confirm the assertion or behavior the issue tracked is **cleared on the real
   product**, not merely on the synthetic scenario.
3. If the real-product run still shows the problem, keep the issue **open** and
   add the `needs-real-verification` label; do not close it. The label marks
   issues that passed regression but have not been proven clear on real output.
4. Only close once real-product evidence is attached (a comment linking the
   `validate --matrix` / `--only-assert` result).

This rule exists because several issues were historically closed on regression
pass alone while the real product still reproduced the defect. It is tracked in
issue #356. The `needs-real-verification` label is the marker; treat it as a
hard block on closing, not a soft note.

## Release process

Releases follow semantic versioning, driven by the same Conventional Commits
prefixes used on PR titles:

- `fix:` bumps the patch version (0.0.x)
- `feat:` bumps the minor version (0.x.0)
- `BREAKING CHANGE:` bumps the major version (x.0.0)

Versioning is automated with release-please. It reads the squashed commit
titles since the last release, opens a release PR that bumps the version and
maintains `CHANGELOG.md`, and publishes when that PR merges. You never
hand-edit version entries; your contribution to the changelog is your PR's
release-note block.

## License & DCO

AutoInfo is MIT licensed (see [`LICENSE`](LICENSE)). By contributing, you
agree that your contribution is licensed under the same terms.

Every commit must carry a Developer Certificate of Origin (DCO) sign-off,
certifying that you have the right to submit the code. Add it with:

```bash
git commit -s
```

This appends a `Signed-off-by: Your Name <you@example.com>` trailer. If you
forgot it, sign your last commit with `git commit --amend -s`. See
[`GOVERNANCE.md`](GOVERNANCE.md) for details.

## References

- [`AGENTS.md`](AGENTS.md): internal agent rules and architecture constraints
  (this guide is their human translation)
- [`GOVERNANCE.md`](GOVERNANCE.md): project governance and decision-making
- [`SECURITY.md`](SECURITY.md): reporting vulnerabilities (use the private
  reporting path, not public issues)
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md): expected behavior
- [`CHANGELOG.md`](CHANGELOG.md): release history
- [`docs/adr/README.md`](docs/adr/README.md): Architecture Decision Records
- [`docs/dev/validation-scenario-contract.md`](docs/dev/validation-scenario-contract.md):
  scenario authoring contract
- [`README.md`](README.md): overview and Quick Start

Thank you for contributing.
