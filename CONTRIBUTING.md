# Contributing to CandleViewer

CandleViewer is a private, self-hosted trading terminal (React + custom WebGL chart engine + Electron
shell, Python FastAPI monolith, Bybit v5 USDT linear perpetuals). It places real orders with real capital,
so the bar for changes is high and the rules are explicit.

## Read these first

| Document                                 | What it is                                                                                                                                                                                                                                                                                         |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **[`CONSTITUTION.md`](CONSTITUTION.md)** | **The binding rules.** Scope guardrails, architecture invariants, branching, quality gates, review rules, DoR/DoD, security, testing, a11y/performance budgets, release and amendment process. It outranks every other document in this repo.                                                      |
| **[`AGENTS.md`](AGENTS.md)**             | The practical operating manual — repo map, how to pick up a ticket, ticket anatomy (§3a), board protocol (§3b), commands per package, coding standards, test-writing rules, PR checklist, prohibitions. Written for AI coding agents (tool-agnostic: Copilot, Codex, Cursor, Claude Code, humans). |
| **[`CLAUDE.md`](CLAUDE.md)**             | Claude Code's entry point specifically — a thin pointer into `CONSTITUTION.md` and `AGENTS.md`, not a second rulebook. If you use a different agent, read `AGENTS.md` directly instead.                                                                                                            |
| **[`SECURITY.md`](SECURITY.md)**         | Vulnerability reporting, supported versions, secrets policy, incident process.                                                                                                                                                                                                                     |
| `docs/plan/`                             | Planning source of truth: SDLC, DoR/DoD, testing, security, a11y, performance, release/PRR, UX, architecture, API/WS contract, schema, roadmap, backlog.                                                                                                                                           |
| `docs/adr/`                              | Accepted architecture decisions (MADR). Do not relitigate them silently.                                                                                                                                                                                                                           |
| `.github/PULL_REQUEST_TEMPLATE.md`       | The checklist your PR must satisfy.                                                                                                                                                                                                                                                                |
| `.github/CODEOWNERS`                     | Who must review what.                                                                                                                                                                                                                                                                              |

If anything below appears to conflict with the Constitution, **the Constitution wins** and the conflict is
a bug to report.

## The short version

1. **Start from a Ready issue.** Check it against the Definition of Ready (Constitution §11.1). If
   acceptance criteria, design sign-off, dependencies or estimate are missing, comment on the issue and
   stop — do not guess.
2. **One ticket = one branch = one PR.** Branch as `<type>/<epic-key>-<short-slug>` using `feat/`, `fix/`,
   `chore/`, `design/`, `spike/` or `docs/` (Constitution §4.2).
3. **Contract first.** If the REST/WS surface changes, edit `docs/plan/22-api-openapi.yaml` or
   `docs/plan/23-ws-protocol.md` and regenerate `packages/protocol` before writing implementation code
   (§6).
4. **Tests first, at the right level.** Unit for pure logic, integration for boundaries (with recorded
   Bybit fixtures — no live-exchange calls in CI), E2E only for user-visible critical paths (§13).
5. **[Conventional Commits](https://www.conventionalcommits.org/)** with an allowed scope; `commitlint`
   enforces it (§4.4).
6. **Rebase, never merge** (`git pull --rebase origin main`). PRs land on `main` as a squash. `main` is
   protected: no direct pushes, no force-pushes (§4.5).
7. **Keep it small.** ≤400 changed LOC preferred; >800 needs a `large-pr-approved` label with a written
   justification (C-4.8).
8. **Open a PR with `Closes #N`** and the template fully completed, with evidence attached (test output,
   screenshots for UI, benchmark deltas for engine work, migration up/down output for schema work).
9. **Get 2 approvals including 1 CODEOWNER.** Security-sensitive paths need `@CandleViewer/security`; UI
   changes need `design-approved` and a Done design ticket (§10).
10. **Merging means In Test, not Done.** Only QA or the owner moves a ticket to Done (§10, §11.2).

## Quality gates

Every PR must pass **all** required CI checks. **The single source of truth for the list of check names,
and for what each one enforces, is [`CONSTITUTION.md` §9 (Quality gates)](CONSTITUTION.md#9-quality-gates-required-ci-checks).**
It is deliberately **not** duplicated here, in `AGENTS.md`, or in the PR template — a renamed check must
require exactly one edit, in one file. If you find a check list copied into any other document, delete it
and link to §9 instead.

Rules that always hold, wherever the list lives:

- A red required check is never merged. There is no admin merge and no "re-run until green".
- Checks are never disabled, skipped, marked `continue-on-error`, or removed from branch protection in a
  feature PR. Changing the required-check set is an amendment (Constitution §16).
- Coverage floors are floors and may never be lowered in the PR that fails them (C-9.4).
- Run the same gates locally before pushing — see [`AGENTS.md` §4 (Commands)](AGENTS.md#4-commands), which
  is the single source of truth for task/script names.

## Hard boundaries

Out of scope, and rejected on sight (Constitution §1.3): Android/iOS or any mobile client; a separate admin
application (admin lives as RBAC-gated screens inside the web app); any exchange other than Bybit or any
category other than USDT linear perpetuals; options/GEX; withdrawal, transfer or funding code; public
internet exposure (Tailscale only); multi-tenant/SaaS productisation; a third-party chart library as the
production renderer.

Safety invariants that no flag, environment or "advanced mode" may weaken: every position-opening order
carries a **native exchange-side stop-loss**; API keys **never leave** the secrets module; **withdrawal
permission is never enabled**; **every order action is audited** append-only; **RBAC and risk caps are
enforced server-side**.

## Local commands

**Single source of truth: [`AGENTS.md` §4 (Commands)](AGENTS.md#4-commands).** Task names are not
duplicated here. Note that until ticket `INFRA-001` (monorepo scaffolding) is Done, those names are a
**specification** — the repo currently contains planning documents only and no
`package.json`/`pyproject.toml`. After INFRA-001, the generated-code required check fails the build if
`AGENTS.md` §4 and the real scripts disagree.

See `AGENTS.md` §4 for the root install/verify command and the backend lint/format/typecheck/test loop.

After `pnpm install --frozen-lockfile`, run `pnpm prepare` once to install the local git hooks
(`.husky/`: `commit-msg` commitlint, `pre-commit` lint-staged, `pre-push` branch-name + affected-project
typecheck). This is a deliberate, code-owned exception to the repo's `ignore-scripts=true` posture — see
the comment in `.npmrc` — so it is not run implicitly by `pnpm install`. Hooks are a convenience; the same
rules are enforced server-side by CI and cannot be weakened by `--no-verify`.

## Design and architecture decisions

Sprints are **1 week** (Fri→Thu; Sprint 01 = 2026-09-25; calendar in `docs/plan/backlog/_tools/calendar_cv.py`). Design runs at least two sprints ahead of engineering; no frontend screen work starts before its design
ticket is Done. Architectural decisions are recorded as MADR ADRs in `docs/adr/` and must be proposed
before implementation (Constitution §15.1).

## Governance map — which document owns what

Every list in this repo has exactly one owner (`CONSTITUTION.md` C-16.5); everything else links to it
instead of restating it. See the [C-16.5 single-source-of-truth registry](CONSTITUTION.md#16-amendment-process)
for the authoritative table (rules, CI check names, budgets, commands, repo layout, ownership, security
policy, ticket schema, statechart contracts). If you find the same list copied into a second file, that
copy is a bug — delete it and link to the owner instead.

## Branch protection break-glass runbook

`main` protection (`.github/branch-protection.json`, applied by
`scripts/apply_branch_protection.py`, `enforce_admins: true`) has no built-in
bypass — that is the point (C-9.1). If protection must be lifted in a genuine
emergency (e.g. to land a hotfix while CI infrastructure itself is down):

1. Only `@basiltt` or a person they explicitly delegate in writing on the
   tracking issue may perform the bypass.
2. Before changing anything, open (or comment on) the dedicated break-glass
   tracking issue, stating: what is broken, why waiting for a normal PR is not
   possible, and the exact setting(s) about to change.
3. Use the repository-administration-scoped credential only via the GitHub UI
   or `gh api`, never the automated apply script (which never runs from a
   PR-triggered workflow, by design).
4. Restore `.github/branch-protection.json` settings immediately after the
   emergency merge — do not leave protection weakened.
5. The weekly `governance-drift` workflow (GOV-005, `.github/workflows/governance-drift.yml`)
   will detect any settings left un-restored and open a `priority/p1-high`
   `security`-labelled issue regardless of step 4 — this is deliberate, not a
   bug: break-glass usage is always independently recorded.
6. The tracking issue is reviewed at the R4 live-enablement gate
   (`docs/plan/28-statechart-catalogue.md` B-series live gate; see
   `docs/plan/30-release-roadmap.md`).

Break-glass is for repository infrastructure emergencies only — it is never a
substitute for getting a second review on a normal change.

## Reporting security issues

Never open a public issue for a vulnerability. Follow [`SECURITY.md`](SECURITY.md).

## Changing the rules

The Constitution changes only through its [amendment process](CONSTITUTION.md#16-amendment-process):
a `constitution`-labelled issue, an amendment PR updating every affected artefact, a 3-working-day
discussion period, and approval from the architect, the security engineer, affected CODEOWNERS and
`@basiltt`. Local exceptions, temporary bypasses and undocumented practices are not permitted.

## Code of Conduct

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
