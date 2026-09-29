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
| `actions/checkout` | `11bd71901bbe5b1630ceea73d27597364c9af683` | `v4.2.2` | `pr.yml`, `governance.yml`, `governance-drift.yml`, `ci-metrics-report.yml` |
| `actions/setup-python` | `0b93645e9fea7318ecaed2b359559ac225c90a2b` | `v5.3.0` | `pr.yml`, `governance.yml`, `governance-drift.yml`, `ci-metrics-report.yml` |
| `actions/setup-node` | `0a44ba7841725637a19e28fa30b79a866c81b0a6` | `v4.0.4` | `pr.yml` |
| `actions/github-script` | `f28e40c7f34bde8b3046d885e986cb6290c5673b` | `v7.0.1` | `governance-drift.yml`, `ci-metrics-report.yml` |
| `actions/download-artifact` | `fa0a91b85d4f404e444e00e005971372dc801d16` | `v4.1.8` | `ci-metrics-report.yml` |
| `dorny/paths-filter` | `de90cc6fb38fc0963ad72b210f1f284cd68cea36` | `v3.0.2` | `pr.yml` |
| `astral-sh/setup-uv` | `c18668ad3cf93ea998bef934396af7bb5c839dc7` | `v10.2.0` | `_job-py.yml` |
| `actions/upload-artifact` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | `v7.0.1` | `_job-py.yml` |

Verification: `tools/ci/check_action_pins.py .github/workflows` fails the
build if any `uses:` line drifts back to a tag, and independently rejects any
workflow declaring the `pull_request_target` trigger (SR-132).
