# Branch-protection bypass register (E03-T13, CI-PROT-004)

Every actor permitted to bypass `main` branch protection (`.github/branch-protection.json`,
`enforce_admins: true`) must be named here with a justification and a review date
(CONSTITUTION.md C-9.1, C-10.1; `docs/plan/01-sdlc-and-branching.md` §7–§8). An actor that can
bypass protection but is **not** listed here is a `CI-PROT-004` finding — treat it as an incident,
not a config nit.

There is deliberately **no standing bypass** for ordinary merges: `enforce_admins: true` means even
repository admins go through the same 2-review + required-checks gate. The only registered bypass
is the release-automation identity below, scoped to a single, narrowly-typed commit class.

| Actor | Scope of bypass | Justification | Review date |
|---|---|---|---|
| `github-actions[bot]` (release workflow, `.github/workflows/release.yml`, `CHANGELOG.md` finalize step) | Push a single `chore(release): vX.Y.Z changelog` commit directly to `main` after tagging — **changelog file only**, no source/build changes | The changelog-finalize step must land the release commit before the next tag can be cut; routing it through a normal PR would race the next merge-queue entry and needs no human review since it is a mechanical diff of `CHANGELOG.md` produced deterministically from merged PR metadata (`tools/ci/finalize_changelog.py`) | 2026-12-25 (quarterly review, next: Sprint 13) |
| `@basiltt` (break-glass only) | Manually disable/relax protection settings via the GitHub UI or `gh api` in a genuine repository-infrastructure emergency (CI itself down) | `CONTRIBUTING.md` § "Branch protection break-glass runbook" — no automated tooling ever performs this; `governance-drift` (GOV-005) independently detects and flags any settings left un-restored | 2026-12-25 (quarterly review, next: Sprint 13) |

## Rules for this table

1. Adding a row requires a PR touching this file, reviewed like any other change to `.github/`
   (CODEOWNERS: `@CandleViewer/devsecops @CandleViewer/security`).
2. Every row must have a review date no more than one quarter (13 sprints) out; `governance-drift`
   (GOV-005) fails and opens an issue when a row's review date has passed (CI-PROT-004).
3. Removing a bypass (e.g. the release-automation identity is retired) removes its row in the same PR
   that removes the capability — an orphaned row for a bypass that no longer exists is also a finding.
4. This table is the single source of truth for "who can bypass `main`'s protection" (C-16.5); do not
   duplicate it elsewhere — link here instead.
