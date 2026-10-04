# GitHub Actions pin ledger

SR-132 (`docs/plan/04-security-program.md` §6.13): every third-party action
referenced from `.github/workflows/**` must be pinned to a full 40-hex commit
SHA, never a floating tag/branch. `tools/ci/check_action_pins.py` enforces
this mechanically (CI-GATE-003); this file is the human-readable ledger of
*which* upstream tag each pinned SHA corresponds to, so a reviewer can see at
a glance what a pin bump changes.

Bumping a pin: update the `uses:` line(s), update the row below in the same
commit, and let Dependabot (`.github/dependabot.yml`, `github-actions`
ecosystem) open the PR when it can — a manually-authored bump is only for
cases Dependabot hasn't caught up with yet.

| Action | Pinned SHA | Upstream tag | Used in |
|---|---|---|---|
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | `v7.0.1` | `_job-a11y.yml`, `_job-contract.yml`, `_job-coverage.yml`, `_job-e2e.yml`, `_job-engine-bench.yml`, `_job-event-coverage.yml`, `_job-gen.yml`, `_job-integration.yml`, `_job-js.yml`, `_job-machine-hash-lock.yml`, `_job-migrations.yml`, `_job-py.yml`, `_job-rule-roundtrip.yml`, `_job-security.yml`, `_job-statechart-lint.yml`, `_job-xstate-contract.yml`, `a11y-nightly.yml`, `board-automation.yml`, `changelog.yml`, `ci-gates.yml`, `ci-metrics-report.yml`, `coverage-ratchet.yml`, `dast-storage-nightly.yml`, `deploy-dev.yml`, `deploy-staging.yml`, `docs-spike.yml`, `governance-drift.yml`, `governance.yml`, `main.yml`, `pr.yml`, `release.yml`, `xstate-nightly.yml` |
| `actions/setup-python` | `0b93645e9fea7318ecaed2b359559ac225c90a2b` | `v5.3.0` | `pr.yml`, `governance.yml`, `governance-drift.yml`, `ci-metrics-report.yml` |
| `actions/setup-node` | `0a44ba7841725637a19e28fa30b79a866c81b0a6` | `v4.0.4` | `pr.yml` |
| `actions/github-script` | `3a2844b7e9c422d3c10d287c895573f7108da1b3` | `v9.0.0` | `_job-coverage.yml`, `ci-gates.yml`, `ci-metrics-report.yml`, `governance-drift.yml`, `release.yml` |
| `actions/download-artifact` | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` | `v8.0.1` | `_job-coverage.yml`, `ci-metrics-report.yml`, `coverage-ratchet.yml` |
| `dorny/paths-filter` | `ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d` | `v4.0.3` | `pr.yml` |
| `astral-sh/setup-uv` | `c18668ad3cf93ea998bef934396af7bb5c839dc7` | `v10.2.0` | `_job-py.yml` |
| `actions/upload-artifact` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | `v7.0.1` | `_job-a11y.yml`, `_job-e2e.yml`, `_job-integration.yml`, `_job-js.yml`, `_job-py.yml`, `_job-security.yml`, `a11y-nightly.yml`, `docs-spike.yml`, `governance.yml`, `main.yml`, `xstate-nightly.yml` |
| `anchore/sbom-action` | `3ad7283483fc7af8ff2b4ea19663c2d5ca935e26` | `v0.24.2` | `main.yml` |
| `sigstore/cosign-installer` | `6f9f17788090df1f26f669e9d70d6ae9567deba6` | `v4.1.2` | `deploy-dev.yml`, `deploy-staging.yml`, `main.yml`, `release.yml` |
| `actions/cache` | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` | `v6.1.0` | `_job-js.yml`, `_job-rule-roundtrip.yml` |
| `docker/build-push-action` | `c3c9e263c25d99ce0380d002d59b67737d91b0dc` | `v7.4.0` | `main.yml` |
| `docker/login-action` | `dbcb813823bdd20940b903addbd779551569679f` | `v4.6.0` | `main.yml` |
| `docker/setup-buildx-action` | `f87e5991a6d7451dcb8d9637bfbc97413f497069` | `v4.4.1` | `main.yml` |
| `hadolint/hadolint-action` | `06be81baf89a55ffd0e24b8f04a4185738dd3387` | `v3.5.0` | `main.yml` |
| `peter-evans/create-pull-request` | `5f6978faf089d4d20b00c7766989d076bb2fc7f1` | `v8.1.1` | `coverage-ratchet.yml` |

Verification: `tools/ci/check_action_pins.py .github/workflows` fails the
build if any `uses:` line drifts back to a tag, and independently rejects any
workflow declaring the `pull_request_target` trigger (SR-132).
