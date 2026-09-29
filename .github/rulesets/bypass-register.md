# Branch-protection bypass register (E03-T13, CI-PROT-004)

Every actor permitted to bypass `main` branch protection (`.github/branch-protection.json`,
`enforce_admins: true`) must be named here with a justification and a review date
(CONSTITUTION.md C-9.1, C-10.1; `docs/plan/01-sdlc-and-branching.md` §7–§8). An actor that can
bypass protection but is **not** listed here is a `CI-PROT-004` finding — treat it as an incident,
not a config nit.

There is deliberately **no standing bypass** for ordinary merges: `enforce_admins: true` means even
repository admins go through the same 2-review + required-checks gate. The only registered bypass
is the release-automation identity below, scoped to a single, narrowly-typed commit class — and it
is **not** a bypass of `main`'s protection at all, since it never pushes to `main` (see Scope).

| Actor                                                                                                                     | Scope of bypass                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Justification                                                                                                                                                                                                                                                                                                                                                  | Review date                                    |
| ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `github-actions[bot]` (release workflow, `.github/workflows/release.yml` "Commit finalised changelog + version.txt" step) | Push a single `chore(release): vX.Y.Z changelog` commit to `HEAD:${REF_NAME}` — the triggering `release/*` branch or `vX.Y.Z` tag ref (`release.yml` lines ~146-156), **never `main`** — containing only `CHANGELOG.md` and `version.txt`, no source/build changes. This is not a `main`-protection bypass (`main` is untouched); it is listed here for completeness because it is the repo's one non-human commit identity with any standing push grant, and any future change that retargeted it at `main` would need to update this row first | The changelog-finalize step must land the release commit on the release ref before the next tag can be cut; routing it through a normal PR would race the next merge-queue entry and needs no human review since it is a mechanical diff of `CHANGELOG.md`/`version.txt` produced deterministically from merged PR metadata (`tools/ci/finalize_changelog.py`) | 2026-12-25 (quarterly review, next: Sprint 13) |
| `@basiltt` (break-glass only)                                                                                             | Manually disable/relax protection settings via the GitHub UI or `gh api` in a genuine repository-infrastructure emergency (CI itself down)                                                                                                                                                                                                                                                                                                                                                                                                       | `CONTRIBUTING.md` § "Branch protection break-glass runbook" — no automated tooling ever performs this; `governance-drift` (GOV-005) independently detects and flags any settings left un-restored                                                                                                                                                              | 2026-12-25 (quarterly review, next: Sprint 13) |

## Rules for this table

1. Adding a row requires a PR touching this file, reviewed like any other change to `.github/`
   (CODEOWNERS: `@CandleViewer/devsecops @CandleViewer/security`).
2. Every row must have a review date no more than one quarter (13 sprints) out. Staleness is
   enforced two ways so a passed date is never caught only by luck of a PR being open:
   `scripts/check_bypass_register.py` runs both in `governance.yml` (every PR touching this file
   or the checked paths) **and** in the scheduled `governance-drift.yml` (weekly, independent of any
   open PR) — see the "Register staleness (CI-PROT-004)" step there.
3. Removing a bypass (e.g. the release-automation identity is retired) removes its row in the same PR
   that removes the capability — an orphaned row for a bypass that no longer exists is also a finding.
4. This table is the single source of truth for "who can bypass `main`'s protection" (C-16.5); do not
   duplicate it elsewhere — link here instead.
5. `scripts/check_bypass_register.py` only validates internal consistency of this file (rows parse,
   dates unexpired); it does **not** reconcile the table against the live actors that
   `.github/branch-protection.json` / the repo's actual GitHub settings currently permit to bypass
   `main`. That reconciliation is `scripts/check_branch_protection_drift.py`, run in
   `governance-drift.yml` — it diffs the live GitHub branch-protection API response (including
   admin/bypass allowances) against the desired-state JSON and opens a `GOV-005` issue on drift.
   A row here for an actor no longer permitted live, or a live bypass actor with no row here, is
   caught by that job, not by `check_bypass_register.py` alone.
