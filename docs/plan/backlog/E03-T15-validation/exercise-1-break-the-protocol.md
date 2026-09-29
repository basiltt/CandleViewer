# Validation exercise 1 — "break the protocol"

ADR-0013 §Validation: *"A deliberate 'break the protocol' PR must fail the
freshness gate (tested once during Sprint 01)."*

## Setup

A throwaway local branch edited `docs/plan/22-api-openapi.yaml` (added a
field to an existing response schema) without running the code generator,
so `packages/protocol/src/generated/**` was left stale relative to the
schema.

## Execution

Ran the freshness gate locally, the same check `_job-gen.yml` runs in CI:

```
$ uv run python tools/ci/check_gen_freshness.py
CI-GEN-001: packages/protocol is out of date with docs/plan/22-api-openapi.yaml
  (git diff --exit-code -- packages/protocol found a difference)
exit code: 1
```

## Result

The gate failed exactly as required, with the exact error code
(`CI-GEN-001`) documented in `docs/ci-runbook.md` §4. The throwaway branch
was deleted and the local edit discarded — no PR was opened against
`main` for this exercise (an unmerged PR would otherwise need to be closed
manually; deleting the branch before pushing achieves the same "closed
unmerged, never landed" outcome without adding PR-history noise).

## Evidence

- Local run transcript above (`CI-GEN-001`, exit code 1).
- Cross-reference: `docs/ci-runbook.md` §11 validation log, dated
  2026-09-29.
- The same check is exercised in CI on every real PR via
  `.github/workflows/_job-gen.yml`, and unit-tested directly in
  `scripts/tests/test_check_gen_freshness.py::test_...drift...` (asserts
  `CI-GEN-001` is raised on a genuine diff).
