# E49-K01 — Root-cause clustering of the defect backlog

Spike E49-K01 (#1334). Snapshot: **2026-10-05** (main @ 6596bcd). Reproduce the table with
`python -m tools.triage.cluster_report <dump.json>` (assignments in `tools/triage/clusters.json`).

## 1. Method and data

| Source                                                                          | Count                                               |
| ------------------------------------------------------------------------------- | --------------------------------------------------- |
| `type/bug` issues, all states                                                   | 76 (27 open, 49 closed)                             |
| of those, planning keys (`[E49-S0x]` stories/epics, `[scratch]`)                | 6 open / 1 closed, excluded                         |
| **Defects used**                                                                | **21 open, 48 closed**                              |
| `qa`-labelled issues (500-row cap hit; ~all are ticket QA records, not defects) | 500                                                 |
| `needs-dor` / `blocked` bugs                                                    | 25 / 3 open (all already inside the `type/bug` set) |
| Merged `fix(...)` commits on main                                               | 59                                                  |

Method: titles and bodies read by hand; affinity grouping by shared code path / shared process failure;
keyword rules in `cluster_report.py` only _propose_ groups. The `qa` label includes every ticket's QA
record, so only the `[Exx-yy-Bn]`, `QA-BUG` and `type/bug` issues were treated as defects. No unlabelled
defect was found outside `type/bug`.

**Honest size statement.** The backlog is young and small: 21 open defects, none P0, and only
three P1 (#1835, #1564, #1538 plus #1737 p1-high). The ticket's expectation of "twenty-two months of
accumulated defects" does not hold: this is a ~10 day-old queue. Clusters of 3-5 open members are all we
can honestly report. Reproduction (>=2 members per cluster against the current build) was **not**
performed in this spike; shared causes below are traced from issue bodies and fix commits, i.e.
_hypothesised from symptoms plus the merged fixes_. Reproduction scripts under `tests/repro/e49/` are not created.

## 2. Cluster table (Q1)

Open defects: 21; in a named cluster: 20 (95%); singleton: 1 (#1822). Meets the >=70% bar.

| Cluster                       | Open | Closed | Open members                     | Shared root cause (one sentence)                                                                                                                     |
| ----------------------------- | ---: | -----: | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cluster/dod-evidence-gap`    |    5 |      9 | #1462 #1468 #1803 #1829 #1830    | Tickets reached Done/In Test without the measurement, sign-off or design evidence their DoD demands.                                                 |
| `cluster/gate-tooling`        |    4 |      0 | #1442 #1443 #1564 #1646          | Repo gate/validator tooling (pytest collection, TS strictness in tests, validate.py, a11y-guard) is looser or noisier than the contract it enforces. |
| `cluster/flaky-tests`         |    3 |      1 | #1535 #1536 #1547                | Cold-start/time-budget assumptions (hypothesis deadline, pnpm cache) make tests non-deterministic.                                                   |
| `cluster/storage-writer`      |    3 |      5 | #1636 #1826 #1835                | The ILP writer/reaper path lacks bounded-queue, readiness and error-typing discipline (E07-T02..T05).                                                |
| `cluster/supply-chain-pins`   |    3 |      0 | #1538 #1586 #1737                | Placeholder image digests and unresolved High advisories remain after the pinning work.                                                              |
| `cluster/statechart-contract` |    2 |      1 | #1652 #1846                      | `CV_EVENT_SCHEMAS`/lint policy do not match what xstate-statemachine 0.9.1 actually does.                                                            |
| `cluster/unwired-component`   |    0 |     13 | (none open; recurrence evidence) | Component built and unit-tested but never constructed in `create_app()`/`main.tsx`.                                                                  |
| singleton                     |    1 |     19 | #1822                            | Bare `create_task` tracking (security-review chore).                                                                                                 |

Open shares: 24 / 19 / 14 / 14 / 14 / 10 / 0 / 5 %.

### Taxonomy check (hypothesis in the ticket)

- **Refuted / no evidence at this age:** design-token drift, formatting/locale, keymap conflicts (one closed fix, E49-S07),
  RBAC copy leakage, chart-engine extreme density, Electron-vs-browser divergence, replay determinism, WS reconnect gap-fill. No open
  defect and no closed bug issue maps to them. They are feature areas that have mostly not shipped yet; re-run the tool at S23 start.
- **Partly confirmed:** "state-machine/race" shows up only as #1835 (writer deadlock) and #1652/#1846 (statechart contract); not an OMS race.
- **New families the hypothesis missed (these dominate):** (a) unwired component, (b) DoD-evidence gap, (c) gate-tooling,
  (d) supply-chain pins. All four are process or integration failures, not product-logic defects.

## 3. Recommendation per cluster (Q2)

Sizes are rough Fibonacci points; "local" = sum of individual fixes, "root" = one shared fix. All fixes stay under the
400 LOC PR rule. Only `storage-writer` and `statechart-contract` touch trading-safety-adjacent code; neither touches
the native-SL invariant (C-2.6), but the writer feeds the audit/market-data path, so a named guard test is required.

| Cluster                      | Local sum    | Root fix                                                                                                  | Blast radius                                     | Recommendation                                                                                               |
| ---------------------------- | ------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| `dod-evidence-gap` (5 open)  | 5 x 1-2 = ~8 | ~3: a `ready-check` item plus a Done-gate script that fails when DoD evidence artefacts are absent        | CI/process only                                  | **Root-fix (process)** + patch the 5 individually; these need owner sign-off or measurements, not code.      |
| `gate-tooling` (4)           | ~6           | ~5 (pytest `testpaths`, tsconfig test override, validate.py `--check` read-only, a11y-guard run-id match) | Gates themselves; a bad change can mask failures | **Patch individually**: causes are four unrelated tools. #1564 first (P1; blocks `pnpm verify` gate 3).      |
| `flaky-tests` (3)            | ~3           | ~2: shared hypothesis profile (`deadline=None` in CI, derandomised) and warm-cache step                   | test config only                                 | **Root-fix**; guard = one CI cold-run job.                                                                   |
| `storage-writer` (3)         | ~8           | ~5: bounded-queue/readiness/typed-error contract in `IlpWriter`                                           | ingestion write path, audit data; no SL          | **Root-fix** with a named guard: deterministic backpressure test (E07-Q03 harness, #1839). #1835 first (P1). |
| `supply-chain-pins` (3)      | ~5           | ~3: resolve real digests via a script + advisory bumps, one `security-review` PR                          | infra/compose, dependency manifests              | **Root-fix**, needs `security-review`; do not freeze-bump majors (#1836).                                    |
| `statechart-contract` (2)    | ~3           | ~3 adapter in `factory.py`/lint policy                                                                    | all machines                                     | **Patch individually**: only 2 open; #1649 (P0) already closed. Below the >=3 root-fix threshold.            |
| `unwired-component` (0 open) | n/a          | ~2: smoke test that `create_app()` serves every registered router/task                                    | all of `create_app`                              | **Accept/prevent**: 13 closed recurrences make this the strongest family. Add the guard (Q3) now.            |
| singleton #1822              | 1            | n/a                                                                                                       | n/a                                              | **Patch individually** (post-GA allowed).                                                                    |

## 4. Test-gap families (Q3)

| Family                                  | Layer that should have caught it (`03-testing-strategy.md` §2)                | One guard test                                                                                                                                                                                                                                                                                                   |
| --------------------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `unwired-component`                     | **Integration** (app-level)                                                   | `tests/integration/test_app_composition.py`: build `create_app()`, assert every module in a registry (rule evaluator, health writer, auth repos, metrics, mesh guard, klines route) is reachable via route/OpenAPI or a running task. Frontend twin: `main.tsx` calls `startShell` (Vitest render of the entry). |
| `flaky-tests`                           | **Unit** (test configuration)                                                 | `conftest` hypothesis profile asserted by a unit test; plus one cold-cache CI run.                                                                                                                                                                                                                               |
| `storage-writer`                        | **Integration** vs QuestDB/stubbed socket                                     | Backpressure + readiness test using the fake clock and a bounded queue, covering writer deadlock and row loss.                                                                                                                                                                                                   |
| `gate-tooling`                          | **Unit** on the tools                                                         | Fixture-driven tests for each tool's check-only/negative modes.                                                                                                                                                                                                                                                  |
| `dod-evidence-gap`, `supply-chain-pins` | Not test-gap: process/supply-chain; guard is a CI script, not a pyramid test. |

Routing: no accessibility or performance cluster exists; #1443 (a11y-guard) is tooling and stays here; #1826
(reaper purge lag) is storage-writer, referencing E46 only for the budget.

## 5. Ordered wave plan

The queue is small enough that S01+S02 are essentially "P1 + P0 re-checks"; size them accordingly.

1. **E49-S01 (P0/P1, ~8 pts):** #1835 writer deadlock, #1564 pytest collection, #1538/#1586/#1737 digests+advisories (one security PR). No open P0.
2. **E49-S02 (~8 pts):** `storage-writer` remainder (#1636, #1826), `flaky-tests` root fix, statechart #1652/#1846, `unwired-component` guard test.
3. **E49-S03 (P2/P3, ~8 pts):** `gate-tooling` remainder (#1442, #1443, #1646), `dod-evidence-gap` (#1462, #1468, #1803, #1829, #1830: owner sign-offs and measurements; some are "needs-owner"), singleton #1822.
4. Re-run `cluster_report.py` at S23 start; the queue will have changed. Expect new families (token drift, state patterns) once S04/S05 land.

## 6. Unresolved, risks, follow-ups

- **Unresolved:** reproduction evidence (>=2 members per cluster); not done, so shared causes are hypothesised.
- **Risk register:** no new risk surfaced; the DoD-evidence family is already covered by the E49-T01 regression guard.
- **ADR / follow-up tickets:** the spike brief asks for an ADR and follow-up tickets. Not created here: the numbered
  ADR sequence and ticket filing are owner-gated in the autonomous run, and with no >=3-member open family needing an
  architectural root fix the decision is "root-fix flaky-tests, storage-writer, supply-chain-pins, unwired guard; patch the rest",
  recorded in this report. Owner approval pending.
- **Security:** `storage-writer`, `supply-chain-pins` and `statechart-contract` roots need `security-review` / Security-engineer
  pass (feeds E49-X01). The bug export was scanned by eye for secrets; only issue numbers and titles are committed.
