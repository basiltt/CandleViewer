# Meta-issue #26 — round-9 update: `main` @ `f28719c` (unreleased 0.8.1)

**Round 9. Verified build:** `main` @ **`f28719c`** (merge of PR #202, `fix/0.8.1-round8`).
`__version__` still reports `0.8.0` on this tree — **identify this build by commit, never by version string.** CPython 3.13.7, Windows 11, fresh venv.

**GATE DECISION: ADOPT WITH CONSTRAINTS — order path included.** Decision-table
row 6. Both remaining Highs (R9-02, R9-04) are contained by mechanisms we
already enforce in lint and CI: **CV-C45** (a restore/gateway strip of
`Done`/`After`/`Error` records before they reach the interpreter), **CV-C32**
(async-only services on the order path), and **CV-C46** (no `SyncInterpreter`
on the order path) — together these make all three of R9-04's leaking lanes,
and R9-02's snapshot-restore vector, unreachable for us. Our 20-machine
contract suite (`tests/xstate_contract/`) becomes a standing blocking gate in
CI, on both service spellings.

**Method:** 12 issue verifications re-run live; full regression sweep; diff review `6db65d8..f28719c`; 8 battle tracks; 20 contract machines driven end-to-end **on both service spellings**; triage → dedupe → **independent adversarial refutation of every Blocker and High**. Nothing counted without a standalone repro on a clean interpreter.

---

## Headline

**Round 8's Blocker is closed, and with it the last Blocker of any kind in this study that belongs to the library.**

#192 taught the priority lane's *drop* site the provenance rule its *charge* site already knew. That was the single item our round-8 report named as the thing standing between this library and our order path, and it is fixed at the root — verified on both engines, both service kinds, and on our real kill-switch machine (**12/12 presses accepted, 0 shed, press pre-empts the chain**).

**Post-refutation the round leaves 0 Blocker · 2 High · 5 Medium · 8 Low.** Refutation moved three of five Blocker/High candidates *down* and none up. That is the best position in nine rounds.

## Disposition of the 12 issues

| Disposition | Issues |
|---|---|
| **FIXED — closing** (9) | #181, #186, #192, #194, #196, #198, #199, #200, #201 |
| **FIXED IN PART — please keep open** (2) | #193 (roll-forward half), #195 (`after` family) |
| **PARTIAL — please keep open** (1) | #197 (receipt over empty configuration) |

No issue regressed. Every round-8 residual we named as our own exit condition — the priority-lane Blocker, the `children_timeout` no-op, the one-sided agreement check, the torn start hook, the `_chain_owed` leak, the lap parity — is closed.

## What we are filing new

| ID | Sev | Title |
|---|---|---|
| **R9-02** | High | `after` transitions matched on the **public** `AfterEvent` class; a forged snapshot record fires a 60 s timer instantly even under `strict` |
| **R9-04** | High | A `def` service armed by a transition an `always` rolls **forward** is still submitted, contradicting #193 and `production-characteristics.md:97` |
| R9-05 | Medium | Snapshots are unauthenticated — filed as a **docs/affordance ask, not a defect** |
| R9-06 | Medium | A delayed self-`send` cycle is charged to nothing and can never be shed |
| R9-07 | Medium | `rollback` + `onDone` storm self-terminates early, silently, wedged in a transient state |
| R9-08 | Medium | `send(wait=True)` reports success over an empty configuration (#197 residual) |
| R9-09 | Medium (doc) | #201's universal lap-parity claim is not quite true at odd limits |

Each Medium-and-above ships with a **standalone** repro (stdlib + `xstate_statemachine` only, every helper inlined).

Eight Low items are recorded but **not filed individually** to avoid noise; we are happy to file any of them on request: priority lane not persisted, call-site queue refusals fire no hook, `done.state.*` unreserved, `strict` not gating restored `pending_events`, #198's v1 compat narrowing, `child=False` misreported, unknown config keys accepted silently, and the `_replace` completion-retyping footgun.

## Two corrections to our own earlier reporting

We re-ran vectors rather than inheriting them, and two of our characterisations were wrong in the library's favour:

1. **#195's send-side gate is better than we said.** With `strict=True`, a hand-built `AfterEvent` passed to `send()` **is** correctly refused. Our register had claimed otherwise. What survives is only the snapshot-restore vector, which never reaches that gate.
2. **R9-03 is refuted outright** and we are not filing it. Its "permanent starvation of external priority traffic" was a measurement artefact of reading a counter after a fixed `sleep(1.0)`; polling to drain gives **500/500 applied, both queues at zero**, on both spellings. Its "silent, no error" claim was backwards — both lanes now trip `RunawayChainError`, which *is* the #179/#201 fix working. And its chart is an unguarded `always` targeting its own region, which the docs already name as invalid.

We would rather withdraw a finding loudly than leave a bad one on the record.

## The one process note worth making

**#195 and #193 are each the second incomplete landing of the same fix** — a good mechanism applied to two of three event families, and a good cancellation applied to one of two epilogues. Rounds 6–8's lesson was "parametrise over the axis the defect lives on", and round 8 did that well; the service-kind axis is now flat across every battle track we run.

Round 9's lesson is different: **when you build a trust mechanism, enumerate every call site it is meant to govern and assert the list is exhausted.** A small test asserting that every `isinstance(event, <public engine class>)` in `base_interpreter.py` is paired with a provenance check would have caught R9-02 at authoring time, and R9-12 with it.

Related: `tests/test_round8_findings.py::test_always_rollforward_matches_sync` currently **pins the leaking behaviour** that `production-characteristics.md:97` says cannot happen, so the green suite certifies the inverse of the published claim. And `TestAsyncRollbackRearmCycleBounded` fails ~80 % of runs on correct behaviour because it reads a counter at 0.6 s when the `def` lane converges at ~1.0 s. Both are small fixes; together they are the difference between a suite people trust and one they learn to ignore.

## Suite, coverage, scorecard

**Suite: 3486 passed / 2 = the too-tight test (filed as `R9-T1`, Low) / coverage
93 %** — `tests/test_round8_findings.py` pins 29/29, and the only visible
suite failure this round is not a library defect: `test_service_calls_bounded_by_max_iterations`
(kind=`def`) compares a call count at `0.6 s` against a later sample; the `def`
lane is still climbing at `0.6 s` and converges around `1.0 s`, so it fails
roughly 80 % of runs on a normal host while the bound it is checking is
correct — both lanes plateau at exactly `maxIterations + 2` when polled to
convergence (`battle-f28719c/r9triage/t_r6_plateau.py`). Coverage was last
fully measured at 92.70 % (`6db65d8`); this round's full `--cov` run did not
finish inside the wall-clock bound, but nothing in the `6db65d8..f28719c` diff
removes tests, so 93 % is recorded as the carried, not-regressed figure — see
`54-r9-final-readiness-verdict.md` §2 for the exact caveat.

**Trend, round 5 → round 9:**

| Round | Commit | Blocker | High | Medium | Low |
|---|---|---|---|---|---|
| 5 | `3ed3099` | 4 | 8 | 8 | 1 |
| 6 | `cec108b` | 2 | 2 | 7 | 9 |
| 7 | `221ce7c` | 2 | 4 | 6 | 8 |
| 8 | `6db65d8` | 1 | 3 | 7 | 4 |
| **9** | **`f28719c`** | **0** | **2** | **5** | **8** |

**4 Blocker · 8 High at round 5 → 0 Blocker · 2 High at round 9.** Every
Blocker of any kind belonging to the library is now closed.

## Full checklist, #27–#201, by status

Every issue we have ever filed against this library, round 1 through round 9.
`closed` means confirmed fixed and holding on this round's re-verification (or,
for issues predating round 6, never regressed on any later round's regression
sweep). Issues carrying a residual are cross-linked to the `R{n}-nn` finding
that narrows or continues them.

| Status | Issues |
|---|---|
| **closed** (round 1–3, #27–#98) | #27 #28 #29 #30 #31 #32 #33 #34 #35 #36 #37 #38 #39 #40 #41 #42 #43 #44 #45 #46 #47 #48 #49 #50 #51 #52 #53 #54 #55 #56 #57 #58 #59 #60 #75 #76 #77 #78 #79 #80 #84 #85 #86 #87 #88 #89 #90 #91 #92 #93 #94 #95 #96 #97 #98 |
| **closed** (round 4–5, #99–#145) | #99 #102 #103 #104 #105 #106 #107 #108 #109 #110 #111 #112 #113 #114 #115 #116 #117 #118 #119 #120 #121 #123 #124 #125 #126 #127 #128 #129 #130 #131 #132 #133 #134 #135 #136 #137 #138 #142 #143 #144 #145 |
| **closed** (round 6–7, #146–#178) | #146 #147 #148 #149 #150 #151 #152 #153 #154 #155 #156 #157 #158 #159 #160 #161 #162 #163 #164 #165 #166 #169 #170 #171 #172 #173 #176 #177 #178 |
| **closed** (round 8, #179–#191) | #179 #180 #182 #183 #184 #185 #187 #188 #189 #190 #191 |
| **closed** (round 9, #181 #186 #192 #194 #196 #198 #199 #200 #201) | #181 #186 #192 #194 #196 #198 (residual `R9-14`, Low) #199 (residual `R9-15`, Low) #200 #201 (residual `R9-09`, Medium/doc) |
| **FIXED IN PART — kept open (round 9)** | #193 (rollback half fixed; roll-forward half is `R9-04`, High) · #195 (`done`/`error` fixed; `after` family is `R9-02`, High) |
| **PARTIAL — kept open (round 9)** | #197 (persistence door shut; receipt path is `R9-08`, Medium) |
| **superseded/withdrawn/tracking** | #26 (this meta-issue) · #61–#74, #100–#101 (not part of our verified set) · #167, #168, #174, #175 (folded into round-8/9 dispositions above, see `48-r8-findings-register.md` / `53-r9-findings-register.md`) |

**We never close or reopen upstream issues ourselves — every "kept open" row
above is exactly what it says: still open, with the residual filed as a new
`R9-nn` issue rather than a reopen.**

## Round 9 — new findings

| ID | Sev | Title |
|---|---|---|
| `<R9-02>` | High | `after` transitions matched on the public `AfterEvent` class; forged snapshot record fires a 60 s timer instantly, even under `strict` |
| `<R9-04>` | High | A `def` service armed by a transition an `always` rolls forward is still submitted, contradicting #193 and `production-characteristics.md:97` |
| `<R9-05>` | Medium | Snapshots are unauthenticated — filed as a docs/affordance ask, not a defect |
| `<R9-06>` | Medium | A delayed self-`send` cycle is charged to no budget and can never be shed |
| `<R9-07>` | Medium | `rollback` + `onDone` storm self-terminates early, silently, wedged in a transient state |
| `<R9-08>` | Medium | `send(wait=True)` reports success over an empty configuration (#197 residual) |
| `<R9-09>` | Medium (doc) | #201's universal lap-parity claim is not quite true at odd limits |
| `<R9-T1>` | Low | The library's own `TestAsyncRollbackRearmCycleBounded` test sleeps too briefly (0.6 s) to see the `def` lane converge; both lanes plateau at `maxIterations + 2` when polled |

## Our refuted / withdrawn claims

We would rather withdraw a finding loudly than leave a bad one on the record:

- **R9-01 downgraded, Blocker → Low.** Every successful provenance-forgery
  vector requires a capability that already dominates the engine (a genuine
  engine-minted event, an unexported private class, or authoring arbitrary
  snapshot records) — all documented as the intended trust boundary. The only
  vector reachable without privileged capability, a hand-built public
  `DoneEvent`, is still correctly refused.
- **R9-03 refuted outright, not filed.** "Permanent starvation of external
  priority traffic" was a measurement artefact of reading a counter after a
  fixed `sleep(1.0)`; polling to drain gives 500/500 applied, both queues at
  zero, on both spellings. The "silent, no error" claim was backwards — both
  lanes now trip `RunawayChainError`, which is the #179/#201 fix working.
- **#195's send-side half was overstated by us.** With `strict=True`, a
  hand-built `AfterEvent` passed to `send()` **is** correctly refused. Our own
  findings register had claimed otherwise; re-running rather than inheriting
  the claim is what caught it. Only the snapshot-restore vector (`R9-02`)
  survives.

## Release-readiness list, before you tag 0.8.1

1. **Bump `__version__` in the same commit that tags.** Nine rounds have now keyed on commits because it reports `0.8.0` on a 0.8.1 tree. If the tag ships with the string still wrong, the escape hatch survives into a *released* artefact.
2. **Fix `R9-02` and `R9-04` before tagging.** A known snapshot→strict bypass (`R9-02`, forged `after.*` record fires a timer instantly even under `strict`) and a known roll-forward invoke leak (`R9-04`) should not ship in a release, even though both are contained on our side by lint-enforced constraints. `R9-02` is one line — gate the `after` branch on the minted subclass the way the `done`/`error` branch already is. `R9-04` needs the same exit-set check `#193`'s rollback half already added, applied to the `always` roll-forward path too.
3. **Fix the sleep in the def-lane test.** `tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` samples the call counter at `0.6 s`, before the `def` lane has converged (~`1.0 s`); poll to a stable plateau instead of comparing two fixed, short-elapsed timestamps (`R9-T1`).

## Pin policy

**`== 0.8.1` once tagged.** Until then: commit `f28719c` + its source sha256,
vendored in-tree per MUST-08. Never a bare version-string pin while
`__version__` still reads `0.8.0` on an unreleased 0.8.1 tree — nine rounds of
this audit have kept a correct baseline only by keying on the commit.

## Our decision

**ADOPT WITH CONSTRAINTS**, on all four lifecycle families including the order path. Pin `== 0.8.1` once tagged; until then the commit plus its source sha256, with a vendored copy in-tree.

Both open Highs are contained by mechanisms we already enforce in lint and CI — a restore-path filter that strips `done`/`error`/`after` records, and a rule that keeps `def` services and `SyncInterpreter` off the order path, which together make all three of R9-04's leaking lanes unreachable for us. Our 20-machine contract suite becomes a standing blocking gate on both service spellings.

Thank you for nine rounds of fast, substantive fixes. The trajectory here is unusual and worth saying plainly: **4 Blocker · 8 High at round 5 → 0 Blocker · 2 High now**, with the remaining two being one branch of one function each.
