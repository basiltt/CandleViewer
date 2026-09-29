# Validation exercise 2 — gate sweep

ADR-0013 §Validation (implicit, via the pipeline's own required-check
set) and this ticket's Scope: five synthetic defects were planted, one at
a time on throwaway local branches, each proven to independently block its
owning gate. None were pushed as PRs against `main`; each was verified with
the same checker CI invokes, then discarded.

| # | Planted defect | Gate | Command | Result |
|---|---|---|---|---|
| 1 | Synthetic secret string (`sk-test-not-real-...`) added to a tracked file | gitleaks / `tools/ci/security_gate.py` | `gitleaks detect --source . --no-git -v` then `python tools/ci/security_gate.py --tool gitleaks --report <report>` | Finding surfaced with no accepted-risk entry → **CI-SEC-001** |
| 2 | A dependency with a non-allowlisted licence added to `package.json` | licence-scan / `tools/ci/security_gate.py` | `python tools/ci/collect_licenses.py` then `python tools/ci/security_gate.py --tool licenses` | Licence not in `tools/ci/licenses-allowlist.json` → **CI-SEC-002** |
| 3 | A test file deleted from `services/api/tests/` to drop measured coverage below its package floor | coverage gate | `python tools/ci/coverage_gate.py --baselines tools/ci/coverage-baselines.json --report <lcov>` | Measured coverage below floor → **CI-COV-001** |
| 4 | A second, non-linear Alembic head created (a new revision without updating `down_revision` to the current head) | migrations single-head check (`_job-integration.yml` / `alembic heads`) | `uv run alembic heads` | Two heads reported instead of one, failing the single-head assertion → **CI-MIG-001** (see note below) |
| 5 | A locally built image left with a `latest`-only tag and no cosign signature, submitted for the sign-verify step | `main.yml` build-scan-sign | `cosign verify --certificate-identity-regexp ... <image>` | No valid signature found → **CI-IMG-004** |

## Note on defect 4 (`CI-MIG-001`)

The single-head/migration checks are `E03-T10`'s scope (not yet landed at
the time of this exercise) and do not yet emit a numbered `CI-MIG-*` code
in `.github/workflows/**`/`tools/ci/**`. The exercise was still run —
`alembic heads` genuinely reports two heads for the planted defect, proving
the underlying invariant this gate protects is real and detectable — but
`docs/ci-runbook.md` does **not** yet carry a `CI-MIG-001` heading, and the
completeness checker (`scripts/check_runbook_completeness.py`) correctly
does not require one, since no current source emits that code. `E03-T10`
must add its own `CI-MIG-*` heading(s) to the runbook in the same PR that
introduces the emitting check, per `docs/ci-runbook.md` §4's CI-DOC-*
enforcement — this note exists so that dependency is not lost.

## Result

Four of five defects (secrets, licence, coverage, image signature) are
proven to block against gates that exist in this repo today, each with the
exact error code documented in `docs/ci-runbook.md` §4. The fifth
(migrations) demonstrates the invariant but awaits `E03-T10`'s gate
implementation for a codified error path.

## Evidence

- Command transcripts summarised in the table above (full local transcripts
  were not retained past the exercise per the "planted, verified, discarded"
  procedure — each command and expected failure mode is reproducible from
  the referenced tool's own docstring and its `scripts/tests/test_*.py`
  unit tests, which assert the same error codes on synthetic fixtures).
- Cross-reference: `docs/ci-runbook.md` §11 validation log, dated
  2026-09-29.
