## Description

<!-- What this PR does and why. Keep it focused: one PR, one purpose. -->

## Related issue

<!-- `Fixes #N`. If no issue, write "N/A". -->

Fixes #

## Special review notes

<!-- Optional. Call out risky areas, behavior changes, or areas needing close review. -->

## release-note

<!-- MANDATORY. The maintainer uses this line for the CHANGELOG. "NONE" is valid. -->

```release-note
<NONE or short user-facing description>
```

## 回归场景 (regression scenario)

<!--
Required when this PR fixes a bug. Name the validation scenario in
`src/autoinfo/mcp/scenarios/regression/` that guards the fix — the test that
fails without this PR and passes with it (P1-1 regression flywheel).
If no bug is being fixed, write "N/A".
-->

回归场景: N/A

## Checklist

- [ ] Tests pass locally: `pytest -m "not real_api"`
- [ ] Lint passes: `make lint`
- [ ] Docs updated (`docs/`) if behavior changed
- [ ] ADR added in `docs/adr/` if this is a non-trivial architecture change
- [ ] AI assistance disclosed per the AI policy in CONTRIBUTING.md
- [ ] Read CODE_OF_CONDUCT.md and CONTRIBUTING.md
- [ ] No unrelated style changes (small-PR principle)
