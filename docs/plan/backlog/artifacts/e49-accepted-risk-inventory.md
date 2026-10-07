# E49-T03 — Accepted-risk inventory and re-review

Date: 2026-10-06 · Ticket: #1342 · Status: **provisional** — recommendations by the delivering agent.
The named decider for anything beyond re-stating an existing owner-approved expiry is the **Owner**
(RACI **OWN**); those rows are marked `escalate: owner` and collected in §6 for #1778.
No approver or expiry on an owner-approved entry was changed by this PR.

Enforcement: `python tools/ci/check_accepted_risk_expiry.py` (governance job + weekly workflow) covers
sources 1–4 below: **56 items checked, 0 expired, 0 inside 30 days** at 2026-10-06; soonest expiry
2026-12-31 (86 days).

## 1. Register `Accepted` rows (32-risk-register.md)

| ID                           | Score             | Owner (RACI) | Expiry     | Review record        | Outcome                                                                           | Re-activation trigger                                               |
| ---------------------------- | ----------------- | ------------ | ---------- | -------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| RSK-053 runbook integrity    | 10 → **15 prov.** | SEC          | 2027-03-25 | 2026-10-06 (this PR) | **escalate: owner** (re-score reaches 15)                                         | runbook merge with <2 approvals; first non-owner approver onboarded |
| RSK-054 allow-list redaction | 6                 | OWN          | 2027-06-30 | 2026-10-06           | re-accept, unchanged                                                              | two support cases blocked by a missing field in a quarter           |
| RSK-055 Manager diagnostics  | 9                 | SEC          | 2027-03-25 | 2026-10-06           | re-accept; re-score at E44 go-live (`escalate: owner`: confirm as GA-gate review) | first Manager trading real funds                                    |

## 2. `security/accepted-risks.yaml` entries (8)

Approver for all: `basiltt` (OWN; security reviewer CODEOWNER merge per C-12.3). Owner role SEC unless noted.

| ID                                                      | Tool/sev      | Expiry     | Ticket     | Outcome                                                                                    | Re-activation trigger                                                                          |
| ------------------------------------------------------- | ------------- | ---------- | ---------- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `license:psycopg@3.3.6`                                 | licence / LOW | 2027-03-25 | #108       | re-accept as is                                                                            | any redistribution of the backend to a third party, or code derived from psycopg               |
| `license:psycopg-binary@3.3.6`                          | licence / LOW | 2027-03-25 | #108       | re-accept as is                                                                            | same as above; version bump re-opens SR-136                                                    |
| codeql `py/clear-text-logging…0002_rbac_seed.py:146`    | HIGH          | 2027-03-25 | #1551      | re-accept; **recommend mitigate-by-GA** (structured bootstrap channel) — `escalate: owner` | bootstrap print becomes reachable without the two env vars; non-owner operators run migrations |
| codeql `py/weak-sensitive-data-hashing…signer.py:49`    | HIGH          | 2027-03-25 | #290       | re-accept (HMAC-SHA256 mandated by Bybit v5)                                               | signer used for anything but request signing; Bybit changes the scheme                         |
| npm-audit `GHSA-vfj7-8cjw-p6xm` (EX-06 braces)          | HIGH          | 2026-12-31 | #1737      | re-accept at expiry only if still unpatched; **check upstream at each freeze**             | patched release published; braces reaches a runtime path                                       |
| semgrep `cv-adapter-isolation` `0004_instruments.py:45` | HIGH          | 2026-12-31 | #1778 B5-b | re-accept (migration immutable, C-5.4)                                                     | any new finding in the file; migration squash ADR                                              |
| same, `:46`                                             | HIGH          | 2026-12-31 | #1778 B5-b | as above                                                                                   | as above                                                                                       |
| same, `:52`                                             | HIGH          | 2026-12-31 | #1778 B5-b | as above                                                                                   | as above                                                                                       |

The three 0004 entries cannot be removed by code (immutable migration). **Recommend** the Owner accept
them once, to the GA cut (2027-03-25), so one decision replaces three year-end re-reviews — Owner call.

## 3. §16.2 exceptions (04-security-program.md)

| ID                                          | Owner | Expiry     | Status                                              | Outcome                                                                                                                      |
| ------------------------------------------- | ----- | ---------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| EX-01 `--allow-no-mfa` seeder, testnet-only | SEC   | 2026-12-31 | **approval Pending** (#1658)                        | `escalate: owner` — an unapproved exception is not a valid acceptance; approve, or retire when ZAP gains a TOTP step (#1639) |
| EX-06 braces                                | SEC   | 2026-12-31 | approved on merge of #1745                          | see §2                                                                                                                       |
| EX-05 http-cache-semantics                  | —     | —          | **retired**: cleared by pnpm override 4.3.0 (#1857) | retired, evidence #1857                                                                                                      |

EX-02…EX-04 were withdrawn (`35-dependency-freeze-policy.md` §8); nothing to review.

## 4. In-source `nosemgrep` suppressions (40, all within the ≤180-day window)

Grammar: `tools/ci/suppressions.py`; enforced at gate time by CI-SEC-006; now also by the expiry check.
Three further legacy markers in `0004_instruments.py` carry no fields and are covered by the §2 yaml rows.

| Group (`reason=`)                                                        | Count | Owner                        | Review/expiry | Basis                                                              | Outcome                                                                                      |
| ------------------------------------------------------------------------ | ----- | ---------------------------- | ------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `B5-b` (app.py, domain/events, primitives, lint script, electron checks) | 6     | @CandleViewer/security (SEC) | 2026-12-31    | code outside `exchange/bybit/` must name the exchange (#1778 B5-b) | re-accept; **mitigate-later**: renaming `CV_BYBIT_*` is a breaking config change, own ticket |
| `B5-b-harness` (test harnesses/corpora)                                  | 15    | SEC                          | 2026-12-31    | recorded-corpus vocabulary in tests                                | re-accept                                                                                    |
| `X02` (ingestion security tests)                                         | 14    | SEC                          | 2026-12-31    | hostile-payload suites name the vendor                             | re-accept                                                                                    |
| `X02-fix` (ingest-boundary unit tests)                                   | 3     | SEC                          | 2026-12-31    | same                                                               | re-accept                                                                                    |
| `schema-enum-0004` (db/models.py)                                        | 2     | @basiltt (OWN)               | 2027-03-25    | mirrors the immutable migration enum                               | re-accept, same expiry as §2                                                                 |

Re-activation trigger for the whole class: a suppression whose rule id broadens, or a count above 40
without a ticket. Recommendation: 38 of the 40 expire on one day (2026-12-31); schedule one
Owner/SEC re-review session in the week of 2026-12-14 rather than 40 piecemeal ones.

## 5. Ticket-level acceptances (owner ruling on #1778, 2026-10-05)

Hunted via `gh issue list --search "accepted risk"`, `"waiver"`, and the #1778 thread/triage comments.
Owner: OWN (decider); delivering owner role in brackets. **None carries an expiry on the issue** — the
mechanical enforcement cannot see them. Each gets a proposed expiry below (recommendation only; Owner
approves in #1778). All are acceptances of _missing evidence_, not of vulnerabilities.

| Issue                   | Ticket       | Acceptance                                                                | Group | Proposed expiry / trigger                        |
| ----------------------- | ------------ | ------------------------------------------------------------------------- | ----- | ------------------------------------------------ |
| #210                    | E04-Q01      | drill matrix, dashboards-under-load, Prometheus outage not run on staging | A     | PRR; staging exists                              |
| #258                    | E04-X02      | abuse cases ran in-process, not against staging                           | A     | PRR; staging exists                              |
| #273 (follow-ups #1830) | E07-Q02      | 4×90-min human exploratory sessions                                       | A     | before R1 exit                                   |
| #274                    | E07-Q03      | bytes/day/symbol without a capture                                        | A     | E16 recorder tooling lands                       |
| #286                    | E08-S05      | invariants on synthetic, not recorded, corpus                             | A/E   | recorded capture exists                          |
| #664 (#1828)            | E24-K01      | no recorded symbol-days incl. cascade                                     | A/E   | recorded capture exists                          |
| #295                    | E09-Q04      | audit scoped to 4 of 8 missing screens                                    | A     | screens built (E09-S03)                          |
| #1313 (#1827)           | E47-K01      | NVDA + Electron + real-route cost not measured                            | A/D   | before E47 exit                                  |
| #219 (#1829)            | E06-Q02      | NVIDIA / Intel Iris Xe probe runs                                         | A/D   | before R2 exit; owner hardware                   |
| #1320                   | E47-S06      | themes re-scoped to foundation + legend                                   | A     | per-view AC lines on view tickets                |
| #1321                   | E47-S07      | a11y prefs re-scoped to plumbing                                          | A     | per-consumer AC lines                            |
| #884                    | E40-K01      | analysis on synthetic load; Q1/Q3 pending capture + E25                   | A     | E25 detector + capture                           |
| #877 (#1803)            | E37-K01      | headless result; hardware run deferred to E37-Q04                         | A     | E37-Q04                                          |
| #1340                   | E49-T01      | `regression-guard` non-required, reporting only                           | B     | C-16 amendment ticket                            |
| #1051                   | E35-X02      | 3 abuse cases xfail until OMS exists                                      | B4    | OMS lands (#863) — **real control gap, RSK-056** |
| #1406 / #1407 (#1831)   | E50-C01/C02  | upstream xstate PRs not opened; bundles ready                             | D     | Owner opens PRs                                  |
| #158, #1639             | E04, E09-X03 | alert drill receipt; ZAP staging secrets                                  | D     | Owner                                            |

A GA decision is needed on #1051: its three xfail cases are the controls behind RSK-056
(rule-execution drift), not documentation gaps. Recommendation: **mitigate now** — block GA on those
cases passing once E29 OMS lands. `escalate: owner`.

## 6. Sampling check of ticket-level completeness

Ten tickets sampled from the thread above (#210, #258, #273, #274, #286, #664, #295, #1313, #219,
#1051) each appear in §5. Ticket-level acceptances in the register itself: none existed before this PR;
they are referenced here and from the PRR statement rather than copied into the register as RSK rows
(none is a risk of the kind §1.2 defines — they are evidence deferrals). E43/E46/E47 acceptance lists
have not been published yet (those epics are unstarted or in progress), so the sweep must re-run when
they land; the `escalate: owner` row for that is in the statement.

## 7. Re-scoring against the current system (provisional — Security engineer / Architect to confirm)

| Risk    | Now        | Proposed            | Evidence / reasoning                                                                                                                    |
| ------- | ---------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| RSK-053 | L2 I5 = 10 | **L3 I5 = 15**      | see §1; escalated, heat map updated                                                                                                     |
| RSK-011 | L3 I4 = 12 | unchanged (watch)   | E08-T06 in-process burst: 0 trades lost, 19.9 s recovery. Synthetic only; the 24 h soak is owed (#1778 A), so no downgrade              |
| RSK-013 | L4 I4 = 16 | unchanged           | rate-limit label leak fixed (`uid`→`scope`); the governor under 5-account fan-out is unbuilt (OMS), so likelihood is not evidenced down |
| RSK-047 | L3 I4 = 12 | unchanged           | register text already holds the score at 12 until the first PRR drill passes                                                            |
| RSK-057 | L3 I3 = 9  | unchanged, **Open** | new in E22-X01; no acceptance yet — mitigations not built                                                                               |
| RSK-056 | L3 I4 = 12 | unchanged, **Open** | its controls are the xfail abuse cases of #1051 (§5)                                                                                    |

Only one score moves. A claim that other scores "improved" would rest on synthetic or in-process data
that the owner has already ruled as non-final evidence (#1778 A), so none is made.

## 8. Register hygiene outcome

No `Mitigating` risk is eligible for `Retired`: the root fixes that shipped (IlpWriter contract #1875,
composition guard #1860, image digests #1877) close _defect clusters_ from
`e49-root-cause-clusters.md`, not the register entries RSK-026/027/011, whose triggers still need
real-load evidence. RSK-012 stays "largely retired" pending E07-S07. §10.0.1 records that nothing was
retired here. The §10 band counts were stale (47 vs 52 entries) and are corrected in the register.
