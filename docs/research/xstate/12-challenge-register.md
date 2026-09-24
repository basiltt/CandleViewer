# 12 — Consolidated Challenge Register: `xstate-statemachine` 0.7.0 → 0.8.0 → `main` @ `5327ba6` → `3c527b0` → `5e07ba8` → `3ed3099` → `cec108b` → `221ce7c` → `6db65d8` → `f28719c` → `19cb1f1` → `c78ce99` → `de2da4e` → `de2da4e` → **tag `v0.9.0`**

> **Round 13 — tag `v0.9.0` = `91bd979`, 2026-09-23 (tree `main` @ `e3a1f22`). Current position.**
> The original 62-finding register remains **fully discharged**; rounds 4–13 have been
> about defects found *by* the battle-tests. **First round keyed on a TAG rather than a
> commit, and the first with a real published pin** — `__version__` finally reads
> `0.9.0`, thirteen rounds after it first went stale.
>
> **DECISION: ADOPT WITH CONSTRAINTS — decision-table ROW 6, and row 9 is ONE ISSUE
> away.** Not a demotion from round 12's row 8: both are "ADOPT with constraints", but
> this one arrives by a different door and with a materially *smaller* constraint set.
> Rows 8 and 9 both require an **empty High row**, and `R13-01` is a CONFIRMED High —
> that single row is the entire distance to unconstrained adoption, because every
> benchmark threshold is now met, every library Blocker is closed and every Medium is
> triaged. **11 of 11 issues fixed (#225–#235), 0 partial, 0 one-axis** — fourth
> consecutive round on that record and the **first in thirteen with zero "fixed, but…"
> rows**; #231 and #235 landed **stricter than asked**. Suite **3577 passed, 13 skipped,
> coverage 92.86 %**; **0 library regressions**, 0 timeouts across 534 sweep scripts.
>
> **CONSTRAINTS — three retirements in one round, the most this study has ever returned
> to the library's credit, and the largest of them came from finding OUR instrument was
> wrong.** **`CV-C12` RETIRES to `CV-C12′`.** Its sole ground was BENCH-6, and BENCH-6
> was never being measured with the right tool: `bench_c_timers.py` does not reproduce
> upstream's "N busy machines" loaded-timer scenario, so **five rounds of "174.4 ms,
> still missed" answered a question nobody asked** while the largest architectural
> constraint in this study stood on the number. Re-run on **THEIR**
> `benchmarks/production_characteristics.py --quick` §2, ten runs: **min 52.1 / p50 53.4
> / p99 55.8 ms against a 100 ms bar — every run under, ~44 ms headroom, spread 3.7 ms.**
> `after` and `raise(delay=)` are now permitted for **coarse timeouts and deadlines with
> ≥250 ms tolerance**; **hard sub-100 ms deadlines and all algo timing — TWAP intervals,
> chase repricing, iceberg release — stay on the external `MonotonicScheduler` with
> absolute `*_us` deadlines**, and the relaxation is conditional on re-measuring on
> target hardware (P3-G6). **`CV-C64` RETIRES to a lint (`CV-C64′`)** — #225 replaced the
> inheritable `ContextVar` with task identity (`_action_tasks`), so a worker outliving
> its action and the `ensure_future` hand-out are ordinary external traffic
> (`worker_send='ok'`, `chain_trips == 0`) while the genuine in-step await is still
> refused by the **library** with `ReentrantWaitError`; the ban's ground is closed, but
> the lint stays, because the hand-out being legal again means the old ban no longer
> incidentally catches a hand-written reentrant await. **`CV-V08` RETIRES** — 0.9.0 is on
> PyPI and the wheel matches the tag across **42/42 modules** (sha256 `018505a1…6c7c0c`),
> so the vendoring caveat carried since 0.8.0 is gone. **`CV-C63` NARROWS** — #226 makes
> the chain latch a real v3 snapshot field, so the wrapper no longer carries it; what
> survives is the **type** rule (`R13-07`: `RestoredError` is not a `RunawayChainError`
> — read `chain_trips > 0`, never `isinstance`). **NEW: `CV-C65`** (persist via
> `get_persisted_snapshot()`, never `drain_pending()` — the mechanically enforced
> mitigation row 6 requires for `R13-01`), **`CV-C66`** (no per-process bring-up hangs
> off `on_interpreter_start`; it has **no working route** on a restored actor, and
> `on_interpreter_stop` still fires, so the pair is *unbalanced*), **`CV-C67`** (register
> coroutine functions **directly**, never behind a sync `def` wrapper — `R13-21`, our own
> harness bug, which silently dropped coroutines and had been **masking the #225
> probes** until `-W error::RuntimeWarning` surfaced it).
> **Net: 3 retired, 3 new, 1 narrowed — the count is flat and the character changed
> again, this time toward rules that guard observability rather than correctness.**
>
> **THE BOARD HAS INVERTED, and that is the round's real finding.** The **library**
> carries **0 Blocker · 1 High · 3 Medium · 6 Low**; **we** carry **3 Blockers and
> 1 High** — `R13-13`/`R13-18` (B16 parallel-region revocation and its missing re-enter
> audit), `R13-14` (B18: our opt-in root `onUnhandled:'error'` turns a guard-denied
> RELEASE into a permanently bricked kill switch), `R13-15`/`R13-16` (B11: a guard ranked
> ahead of its own action reads pre-action context, and gap telemetry goes dark precisely
> while degraded). **Every one is config-only, every one has a fix proven green 11/11 in
> both spellings on this exact build, and in every case the engine is spec-correct per
> XState v5 and SCXML — the defect is our chart.** Thirteen rounds in, the remaining risk
> in this adoption is **ours to discharge, and all of it is mechanical.**
>
> **RELEASE READINESS: v0.9.0 IS the pin, and it is a real one.**
> `xstate-statemachine == 0.9.0`, `==` never `~=` or `>=` (#231 shows this project will
> tighten validation inside a minor release, and a floating pin would take that
> unreviewed), hash-checked in the lock file against sha256
> `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`. No vendoring, no
> git ref; `git tag v0.9.0` = `91bd979` is the provenance anchor if source is ever
> needed. Full reasoning and the FINAL mandatory configuration:
> `74-r13-final-readiness-verdict.md`.

> **Round 12 — `main` @ `de2da4e`, 2026-09-23 (merge of PR #223, `fix/0.8.1-round11`). Superseded by round 13.**
> The original 62-finding register remains **fully discharged**; rounds 4–12 have been
> about defects found *by* the battle-tests. Keyed on the commit — `__version__` still
> reports `0.8.0`, **twelve rounds running**.
>
> **DECISION RECOVERS TWO ROWS: ADOPT WITH CONSTRAINTS — decision-table ROW 8**,
> up from row 6 at `c78ce99` and level with round 10. Row 8 is *"all Blocker and High
> closed; all Medium triaged; benchmark thresholds not all met."* The difference from
> row 6 is the one that matters: last round **one of our constraints was containment
> for an open library defect**; this round **every remaining constraint is an
> architectural consequence of our own benchmarks** again.
>
> **5 issues verified: all five FIXED (#218–#222) — 0 partial, 0 not-fixed, 0
> regressed-on-one-axis.** Third consecutive round in which every fix landed on every
> axis it claimed, both engines and both service spellings — and the **first in which
> a majority (3 of 5) carries no scope residual at all**.
>
> **Post-refutation the LIBRARY board is 0 Blocker · 0 High · 3 Medium · 6 Low.**
> Trajectory across the series: **4 Blocker · 8 High at round 5 → 0 · 2 at round 9 →
> 0 · 0 at round 10 → 0 · 1 at round 11 → 0 · 0 now.**
>
> **Seventh consecutive round in which our own claims were the thing that did not
> survive contact.** Refutation moved **every** Blocker/High candidate *down* and
> **none up**, for the fifth round running. Of three library candidates — all filed
> Blocker — **two were refuted outright** and **one was downgraded to Low**:
>
> - **R12-02** (forged `"version": 2` blob gets `engine: true` from `upcast`) —
>   **REFUTED.** Reproduced exactly, then killed by its own control: a plain v3 blob
>   writing `configuration`/`context` verbatim reaches the **identical** observable
>   outcome. The proposed `minimum_version=3` mitigation refuses the forgery while
>   leaving the trivial path untouched, which **proves the trust boundary — not
>   `upcast` — is load-bearing.** Merged sources **D11-fuzz-1, D11-semantics-1 and
>   R11-01 fall with it.**
> - **R12-03** (engine-event provenance is forgeable) — **REFUTED (Info).** No vector
>   uses only the public API; each requires a private import, a private-slot poke,
>   already holding an engine event, arbitrary code execution, or the documented
>   snapshot trust boundary. `is_system_event(DoneEvent(...))` is correctly `False`.
> - **R12-01** (forged `scheduled_sends` mints engine events) — **DOWNGRADED to Low.**
>   The `engine` flag **is** consulted on that path; without it the record restores as
>   a public `Event` with `e.data == {}` and the payload never arrives. Only a narrow
>   `_admit_restored`-bypass strict-parity gap survives.
>
> **Fourth consecutive round in which a provenance Blocker died on the same control
> probe.** Standing amendment 18 — *test every blob-write finding against the
> `state_ids`-only control before triage* — has now paid for itself four times, and
> R12-02 is its cleanest kill: the control and the exploit were run side by side and
> reached the same state.
>
> **Round 11's regression is reversed AT THE MECHANISM.** R11-04 — `_timer_handles`
> retaining 1.00 handle per `raise(delay=)` beat for ever, **+455 MB / 24 s at 200
> machines** — is closed by **#218**: a 200-beat heartbeat holds **peak 1 handle** on
> every engine/kind cell, a 500× arm/cancel storm peaks at **0** with no
> double-release, `stop()` releases, and the soak that read **+753 MB** last round
> reads **RSS Δ 0.00 MB over 93,168 beats** at `handles_max_per_machine = 1`.
> **R11-06** (#215's silent permanent `start()` deadlock) is closed by **#219**, which
> converts it into a loud immediate error.
>
> **The one item that could have held the High row open is argued in the open and
> resolved at Medium.** **DE-L1** — #219's guard rides an **inheritable `ContextVar`**,
> so the **documented `ensure_future` escape hatch** is refused whenever the spawning
> action yields again, and a background worker born in an action is refused even
> 300 ms after the machine goes idle. Filed High; **Medium** on four grounds: every
> refused shape has a deterministic documented alternative we already mandate
> (**CV-C25**, since round 5), the failure is **loud and immediate** where every High
> in this study has been *silent*, it is **strictly safer than the silent deadlock it
> replaced** (scoring an improvement above its worse predecessor would be incoherent),
> and our corpus contains **zero** instances across 573 scripts and 20 charts. The
> falsifier is recorded: produce a shape with no fresh-context or gateway alternative
> and it returns to High.
>
> **The measurement debt split — one paid, one not.** **PAID:** the full suite
> completed for the first time in four rounds — **3545 passed, 13 skipped, 0 failed,
> 92.87 % coverage** — so decision-table **row 2, which fires before any adoption
> row, now rests on a number taken at the commit under test** rather than a stale
> carry-over. The diff **weakens no test** (`+794/−1`, no `xfail`, no `skip`; the one
> test edit *strengthens* a #219 pin). **NOT PAID: BENCH-6 is unmeasured for a FIFTH
> consecutive round**, and `bench_h` took **BENCH-1 and BENCH-2** down with it by
> sharing a timeout. **Row 9 is refused explicitly: *unmeasured* is not *met*, and a
> row requiring all thresholds met cannot be reached by absence of evidence.**
>
> **ZERO true regressions** across **168 gate checks** (128 P / 40 F; six new checks,
> all PASS) and a **573-script sweep** (476 P / 94 F / 3 T) — the **sixth consecutive
> round**. All 11 PASS→not-PASS deltas re-run **×5 serially**: nine are
> harness/contention false FAILs, two are superseded oracles. **SUPERSEDED-BY-#219:
> ZERO scripts — and the absence is the finding**, established by scan and by targeted
> audit rather than assumption.
>
> **Both round questions answered NO, and both positively.** *Did #219 require any
> change to our catalogue actions?* **Zero** — 0 of 573 scripts and 0 of 20 charts
> contain the refused shape. That is **CV-C25 doing its job since round 5 —
> anticipation, not luck.** *Did #220's recursion reject any of our catalogue JSON?*
> **There is no rejection to adjudicate** — 20/20 build clean, 0 warnings, both lanes,
> with **both controls positive**. The load-bearing consequence is **retroactive:
> nothing in B1–B20 was ever silently dropping an entry action or a transition**,
> which validates the contract results of rounds 4–11.
>
> **CONSTRAINTS — the first retirement in this study driven by a defect being FIXED AT
> THE MECHANISM rather than by a rule being superseded. CV-C47 RETIRES** (both grounds
> closed — R10-03 by #212, **R11-04 by #218**) **and CV-C61 retires with it**; the
> handle-count gauge **survives as telemetry**. **CV-C12 STANDS UNCHANGED** — its
> ground is BENCH-6, and #218 fixed a handle-**retention** defect while saying nothing
> about **drift under load**; retiring it on #218's strength would answer a timing
> question with a memory measurement. **CV-C52 RE-LABELLED: `minimum_version=3` is
> hygiene, not a security control.** **CV-C51 and CV-C59 become agreements with the
> runtime rather than substitutes for it** — #219 and #222 now enforce what they
> assert. **NEW: CV-C63** (chain-trip durability is the wrapper's job — the latch is
> process-local) and **CV-C64** (no action may await *or hand out an `ensure_future`
> receipt for* a `send(wait=True)` on its own interpreter; **lint before upgrading**).
> **Net: 2 retired, 2 new, 62 standing — the count is flat and the character changed.**
>
> **RELEASE READINESS: we would pin a tag cut at `de2da4e` with NOTHING required to
> land first. Recommendation: cut and tag 0.8.1 at this commit**, bumping
> `__version__` in the same commit — a wrong version string is harmless on an
> unreleased tree because we key on the commit, but on a *released* build it becomes a
> **distributed** problem that cannot be re-cut quietly.
>
> **What still blocks the order path is OURS, for the second round running.**
> **R12-13** (B16 — elevation outlives the session, 12/12 lanes fail; **fix CORRECTED
> this round: the root hoist alone fixes only 9/12 because the deeper
> `elevated.on.REVOKE` handler outranks the root arm, so the region-level handler must
> ALSO be deleted**) and **R12-14** (B18 — one guard-denied `RELEASE` under
> `onUnhandled:"error"` **bricks the kill switch**; the next *authorised* release is
> accepted by `send()` and silently dropped) are **Blocker, config-only, open SEVEN
> rounds**; **R12-15** (B19 — operator cannot clear a stale lockout) is **High**, fix
> proven in both lanes. **Six items remain open and NOT ONE IS UPSTREAM** — three
> chart defects, the unshipped linter and `tests/xstate_contract/` (**G-P3-3, still
> the single gating condition**), and three unmeasured benchmarks.
>
> Verdict: `69-r12-final-readiness-verdict.md`; regression: `65-r12-regression.md`;
> suite+bench: `66-r12-suite-bench.md`; diff review: `67-r12-diff-review.md`;
> refutations: `65-r12-01-refutation.md`, `68-r12-14-refutation.md`; refuted records:
> `issues/post-de2da4e/refuted/`; drafts: `issues/post-de2da4e/` (**not posted**).


> **Round 11 — `main` @ `c78ce99`, 2026-09-22 (merge of PR #217, `fix/0.8.1-round10`). SUPERSEDED by round 12 above.**
> The original 62-finding register remains **fully discharged**; rounds 4–11 have been
> about defects found *by* the battle-tests. Keyed on the commit — `__version__` still
> reports `0.8.0`, **eleven rounds running**.
>
> **DECISION REGRESSES BY ONE ROW: ADOPT WITH CONSTRAINTS — decision-table ROW 6**,
> down from row 8 at `19cb1f1`. Row 6 is *"all Blockers closed, 1–5 High open, each with
> a mechanically enforced mitigation."* The difference from row 8 is not cosmetic: last
> round every remaining constraint was an **architectural consequence of our own
> benchmarks**; this round **one of them is containment for an open library defect**.
>
> **5 issues verified: all five FIXED (#212–#216) — 0 partial, 0 not-fixed, 0
> regressed-on-one-axis.** This is the **second consecutive round where every fix landed
> on every axis it claimed**, both engines and both service spellings. Four of the five
> carry residuals, and **every residual is a scope or composition gap rather than a
> failure of the mechanism that shipped**: #214 and #216 each fixed one level and left
> the adjacent one; #213 fixed the hop and left the second hop; #215 fixed the parity
> and added a gate.
>
> **Post-refutation: 0 Blocker · 1 High · 4 Medium · 5 Low.** Trajectory across the
> series: **4 Blocker · 8 High at round 5 → 0 · 2 at round 9 → 0 · 0 at round 10 →
> 0 · 1 now.**
>
> **Sixth consecutive round in which our own claims were the thing that did not survive
> contact.** Refutation moved **every** Blocker/High candidate *down* and **none up**,
> for the fourth round running. Of five candidates — one Blocker and four Highs —
> **three were refuted outright**, **one was downgraded**, and **one survived**:
>
> | filed as | id | final | why |
> |---|---|---|---|
> | **Blocker** | R11-01 | **Low** (doc nit) | The `"version": 2` downgrade really does mint `engine: true` onto forged `done`/`error`/`after` records, firing a 60,000 ms `after` in ~1 ms with `last_error=None`. **But the control killed it:** an attacker who can edit `version` can equally edit `state_ids` and land in the target state **with no event forgery at all**. `from_snapshot` is a **documented trusted-input boundary** (#205 applies `state_ids`/`configuration`/`context` verbatim; `machine_hash` is explicitly *not a MAC*), and `from_snapshot(minimum_version=3)` raises `SnapshotVersionError` on the forged blob. **Residual: the snapshot guide still names `minimum_version=1` as the anti-downgrade floor and should say 3.** |
| **High** | R11-02 | **Low** (contract inconsistency) | `scheduled_sends` really does bypass `_admit_restored`. But forging `configuration` alone reaches the same state with no event, and `events.py:421` states that boundary explicitly. **What survives is observability-grade:** #214 promises restored user events get a *reported* strict refusal, and the field added in the same release does not — so a chart upgrade that undeclares an event yields **silent delivery**. One-line fix. |
| **High** | R11-03 | **REFUTED outright (None)** | Four `after`-forgery vectors, all reproducing. **Control V1 — the only vector reachable from the documented public API — is correctly refused with `UnknownEventError`**, which is exactly the claim #195/#203 make. V2 needs a non-exported module; V3/V4 need an already-held genuine engine event (original and pickle clone behave identically — zero escalation); V5 needs blob-write, which reaches the target with no event at all. **"Type identity is not a capability" attacks a capability claim the library never makes.** |
| **High** | R11-04 | **CONFIRMED — High, the round's only survivor** | Every refutation avenue failed: no correct usage bounds it (id reuse, explicit `cancel(sendId)`, 250 ms period, never-exiting self-loop all 1.00/beat), not documented, XState v5 and SCXML both disagree with the retention, not a duplicate (round 10 was flat only because #206's trip capped the cycle at ~12 beats), not a measurement artefact (measured on the container, polled to convergence, strictly linear), no trust boundary involved. |
| **High** | R11-05 | **REFUTED outright (none)** | The `raise(delay=0.0001)` spin is real — and **plain `after:` at the same delays behaves identically on the same charts**, having been exempt from `maxIterations` since long before #212. The reversal opened **no escape**; it achieved **parity** with a path the budget never bounded by design. Documented in `production-characteristics.md` §2, conformant with SCXML §6.2 and XState v5, and not a liveness failure (external `send` served in 16.5/15.3 ms — the Windows timer floor). `delay` is milliseconds, so `0.0001` is 100 ns: API misuse. |
>
> **The two candidates the round's framing pointed at hardest — the security ones — are
> the two that did not survive contact with a control probe.** This is now the **third
> consecutive round** in which a Blocker filed against engine-event provenance has been
> refuted by our own control, and it has been promoted from a refutation step to a
> **triage precondition** (standing amendment 18): *any finding whose threat model
> requires blob-write must first be tested against "what does the same writer achieve
> with `state_ids`/`context` alone?"*
>
> **Both round questions answered NO.** **(1) #212 re-opened no bounded-cycle class** —
> a purpose-built collateral-unboundedness probe found no previously-bounded shape that
> became unbounded (both lanes, watchdogs), R11-05 is refuted on its `after:` control,
> and the 163-check gate plus 527-script sweep produce **exactly one** stable PASS→FAIL
> delta, which is **our own test encoding the #206 rule #212 deliberately reverses**.
> **(2) Snapshot v3 and the v2-upcast rule re-opened no forgery boundary** — both
> candidates died on controls, and the boundary #195/#203 target holds in every probe.
>
> **The one thing that costs a row.** #212 opened no *semantic* hole but made a latent
> *resource* defect unbounded. **R11-04:** `_timer_handles` retains **1.00 handle per
> `raise(delay=)` beat, for ever**, on both engines and both action kinds —
> `_schedule_send` keys the handle under the **machine** id while the only pruner pops
> by **state** id on state exit, and the machine id never exits. The `after:` path uses
> `owner_id=state.id` and is **flat**. **+455 MB / 24 s at 200 machines, strictly
> linear, no plateau.** Before #212 it was capped at ~12 entries because #206's trip
> killed the cycle first. **One line per engine to fix**, and the correct pattern
> already exists four hundred lines away.
>
> **The interaction is what makes it bite:** #212 explicitly *endorses* the shape that
> leaks, and #213 makes `raise(delay=)` the **only restart-safe in-chart deadline
> primitive** (since `after` deadlines are deliberately not persisted, #128). So the
> documented path to snapshot-safe deadlines is currently also the leaking one. It is
> contained by **CV-C47** — a lint written last round against a *different* finding —
> which is the entire difference between **row 6 (ADOPT)** and **row 7 (DEFER)**.
>
> **Contracts: 20/20 LIBRARY-GO, ZERO library defects across all four groups, on both
> spellings — second consecutive round.** B1–B5 **356 checks / 0 FAIL**.
> `strictConfig: true` is now mandatory on all 20 machines and found 0 unknown root
> keys — but per R11-07 its value is ~95 % unrealised until the recursion lands, since
> our typo surface is ~200 state nodes, not ~10 root keys. **What blocks B16/B18 is
> still OURS: C-04 and C-07b, open SIX rounds, both refuted as library defects, both
> fixable in config alone.**
>
> **Measurement debt is now the largest open risk on the board.** The full suite did
> **not** complete for the **third consecutive round** (~4 % reached, 0 failures), so
> decision-table row 2 — which fires *before* any adoption row — rests on round 10's
> one-commit-stale **92.78 %**. **BENCH-6 has been unmeasured for four rounds** while
> **LC-26/CV-C12 stand entirely on it**; a constraint whose ground has not been
> re-measured cannot be retired.
>
> **Constraint movement: CV-C48 RETIRES** (#214's upcast closed its R10-05b ground and
> the security objection to that upcast was refuted), **CV-C45's stripping clause
> RETIRES**, **CV-C49 is REWRITTEN** (#213 closed its R10-04 ground; R11-08 supplies the
> mirror-image hop), and **CV-C47 STANDS, WIDENED and is now LOAD-BEARING** — its
> R10-03 ground is gone and R11-04 replaced it. **New: CV-C51…CV-C62.** Three
> constraints, three different outcomes from the same release — which is why standing
> amendment 20 now requires an explicit per-constraint re-grounding pass every round.
>
> **Net effect of #212 on our timer rules: zero relaxation, one tightening.** The
> reversal that made `raise(delay=)` legal is the same reversal that made it leak.
>
> Full reasoning: `64-r11-final-readiness-verdict.md`. Register:
> `63-r11-findings-register.md`. Refutation: `64-r11-04-refutation.md`. Refuted
> records: `issues/post-c78ce99/refuted/`.


> **Round 10 — `main` @ `19cb1f1`, 2026-09-22 (merge of PR #211, commit `4dbf86e`). Superseded by round 11.**
> The original 62-finding register remains **fully discharged**; rounds 4–10 have been
> about defects found *by* the battle-tests. Keyed on the commit — `__version__` still
> reports `0.8.0`, ten rounds running.
>
> **DECISION ADVANCES: ADOPT WITH CONSTRAINTS — decision-table ROW 8**, up from row 6
> at `f28719c`. Row 8 is "all Blocker **and High** closed, all Medium triaged,
> benchmark thresholds not all met": the constraints that remain are
> **benchmark-derived architectural consequences**, not containment for open library
> defects. Round 9's own §9 named row 8 as *"the honest ceiling for this library in our
> system."* **We have reached it.**
>
> **8 issues verified: all eight FIXED, clean — 0 partial, 0 not-fixed, 0
> documentation-only.** This is the **first round in ten where every fix landed on
> every axis it claimed**. Rounds 6, 7, 8 and 9 each found at least one fix that held
> on one engine or one service spelling and not the other; round 10 finds none. The
> service-kind axis is flat across the entire corpus, save the one documented, intended
> divergence (`def` services are non-preemptable).
>
> **THE OWED MEASUREMENT IS DISCHARGED.** Round 9 could not finish the coverage run
> inside its bound and recorded it as an open measurement rather than a pass, because
> decision-table row 2 fires *before* any adoption row. The suite finished this round:
> **3505 passed, 13 skipped, 0 failed, 566.57 s, coverage 92.78 %** — above the
> library's own 90 % floor and our 86 % bar, and up from 92.70 %. Row 2 is now
> not-triggered **on measured evidence rather than inference**, which retires round 9's
> single largest open risk.
>
> **Post-refutation: 0 Blocker · 0 High · 5 Medium · 7 Low** — **the High row is empty
> for the first time in ten rounds.** Trajectory across the series: **4 Blocker · 8
> High at round 5 → 0 · 2 at round 9 → 0 · 0 now.**
>
> **Fifth consecutive round in which our own claims were the thing that did not
> survive contact — and this round it was total.** Refutation moved **all three**
> Blocker/High library candidates *down* and **none up**, and on the contract side took
> two Blockers and two Highs off the library's ledger entirely:
>
> | filed as | id | final | why |
> |---|---|---|---|
> | **Blocker** | R10-01 | **Low** (hardening) | Seven engine-event forgery vectors, all reproducing — but they partition into **Class A** (in-process Python: *strictly weaker than the premise*, since a plain registered action writes context arbitrarily and a live `Interpreter` exposes `_enter_states`/`_exit_states`) and **Class B** (blob-write: we tested rather than accepted `events.py:414`'s claim, and **a hand-edited snapshot with no event forgery at all** restores to `{'z.late'}` with context `{'n': 999}`). The boundary #195/#203 actually target holds in every probe. |
> | **High** | R10-02 | **REFUTED outright** | A self-targeting `onDone` is an **internal** transition by contract — XState v5 makes internal the default with `reenter: true` the opt-in, documented three times including a troubleshooting entry naming this exact shape. With `"reenter": true`, polled to convergence on both engines and both kinds: `entries == submits == 22 == maxIterations + 2`, `RunawayChainError`, hook fired. Zero violations. |
> | **High** | R10-03 | **Medium** | Reproduces robustly, but is implied by the #206 changelog and `json-config.md:110`; the **documented** `after` idiom measures 93/92 beats in 3 s with zero drops against 9 for the `raise(delay=)` spelling, and no doc presents self-`raise(delay=)` as a heartbeat. |
> | **Blocker** | R10-C1 | **REFUTED as a library defect; ours (C-04)** | Our chart omits the revocation events from the elevation region, while `REVOKE` — listed in *both* regions — clears correctly, proving dispatch is sound. The corrected chart passes on both engines and both spellings. |
> | **Blocker** | R10-C2 | **REFUTED as a library defect; ours (C-07b)** | `onUnhandled:"error"` is documented opt-in policy and a guard-denied event *is* an unhandled event (#170). SCXML §3.13 and XState v5 agree; neither spec even defines an error-on-unhandled disposition. Fixable in our config alone. |
> | High | R10-C3 | **Medium** | The stated cause is refuted: `stale_lockout` **is** escapable by the operator via `RECONNECTED`, identically on both lanes, so the High premise ("clearable only by an event the operator cannot produce") fails. |
> | High | R10-C4 | **REFUTED (Low)** | Contract-modelling error: the kill event is declared only on *sibling* states. Sibling-only 1.458 s; ancestor handler **0.001 s**. XState v5/SCXML would drop the event outright; `defer` loses less. |
>
> **Both round-9 Highs are closed, at the right sites.** **#203** gates `after`
> selection on `is_system_event` (`base_interpreter.py:4624`) — the same test the
> `done`/`error` branch already used, which is precisely what our R9-02 asked for.
> **#204** moves invoke arming into the eventless settle pass per SCXML §6.1
> `statesToInvoke`, closing the roll-forward half on **both engines and both service
> kinds**: `LD-01` **3 leaks → 0/6**, B6–B10 `def` lane 51/52 → **52/52**, drives
> 13/14 → **14/14**, and `167 rollback_reinvoke_spin` — which we had recorded as a
> *permanent* expected-failure and built a standing architectural constraint around —
> now passes 5/5.
>
> **Contracts: 20/20 build clean on both service spellings, and ZERO library defects
> across all four groups.** A first in the study.
>
> **Constraints retired: CV-C46** (order path never on `SyncInterpreter` — its entire
> ground was R9-04's sync-engine leaks) and **CV-C45's send-side clause** (its ground
> was R9-02, now closed in the engine). **CV-C32 retires as a *safety* rule** while the
> rule itself stands, re-grounded on R10-D2. **New: CV-C47…CV-C50 and CV-C4x.**
>
> **Phase-3 order-path shim retirement MAY BEGIN.** Both gating Highs are closed and
> Phase 3's one measurement precondition is met at 92.78 %. The three remaining
> acceptance conditions are **entirely ours**: five green nightlies, lint+tests, and a
> two-week low-notional canary.
>
> **What blocks B16/B18 is still OURS**, and this round removed the last ambiguity
> about it: **C-04 and C-07b are open five rounds**, and we refuted both as library
> defects by building the corrected charts and watching them pass on every engine and
> every spelling. **Ten rounds of library verification have converged on a state where
> the binding constraint on our order path is our own catalogue, and nothing else.**
> That is the right problem to have, and it is the next thing to work.
>
> Verdict: `59-r10-final-readiness-verdict.md` · register: `58-r10-findings-register.md`
> · refutations: `59-r10-01-refutation.md`, `59-r10-c3-refutation.md`,
> `59-r10-c4-refutation.md`, `55-r10-c2-refutation.md`,
> `issues/post-19cb1f1/refuted/` · drafts: `issues/post-19cb1f1/` (**not posted**).

---

> **Round 9 — `main` @ `f28719c`, 2026-09-22 (merge of PR #202, `fix/0.8.1-round8`). Superseded by round 10 above; retained as history.**
> The original 62-finding register remains **fully discharged**; rounds 4–9 have been
> about defects found *by* the battle-tests. Keyed on the commit — `__version__` still
> reports `0.8.0`, nine rounds running.
>
> **VERDICT CHANGE: ADOPT WITH CONSTRAINTS — on all four lifecycle families, order
> path included.** This supersedes eight consecutive rounds of DEFER on the order
> path. Decision-table **row 6**.
>
> **12 issues verified: 11 fixed in code (9 clean, 2 narrower than claimed), 1 partial
> (#197), 0 not-fixed, 0 documentation-only.** Zero true PASS→FAIL gate regressions —
> the single flip (`LC-42`) is a flaky sub-millisecond latency threshold, 4/5 PASS.
> **Coverage was NOT measured** (the `--cov` run did not finish inside the wall-clock
> bound; ~51 % of tests observed green, 92.70 % at `6db65d8`). Row 2 keys on coverage,
> so that is recorded as an **open measurement, not a pass**.
>
> **Post-refutation: 0 Blocker · 2 High · 5 Medium · 8 Low** — the best position in
> nine rounds, and the trajectory across the series is **4 Blocker · 8 High at round 5
> → 0 · 2 now**. Refutation moved **3 of 5** Blocker/High candidates *down*
> (**R9-01 Blocker→Low**, **R9-03 High→REFUTED outright**, **R9-05 High→Medium**) and
> **none up**. **Fourth consecutive round in which our own claims were the thing that
> did not survive contact**, and this round it went further than usual: R9-03 was
> withdrawn entirely (its "permanent starvation of external priority traffic" was an
> artefact of reading a counter after a fixed `sleep(1.0)`; polling to drain gives
> **500/500 applied with both queues at zero** on both spellings, and its "silent, no
> error" claim was backwards — both lanes now trip `RunawayChainError`, which *is* the
> #179/#201 fix working). We also corrected ourselves in the library's favour on
> **#195**: the send-side gate *does* refuse a hand-built `AfterEvent` under `strict`,
> which our own register had overstated. **Re-run vectors; do not inherit them.**
>
> **The round-8 Blocker is closed, and that is the whole verdict change.** #192 taught
> the priority lane's *drop* site the provenance rule its *charge* site already knew —
> self-issued sends charged, external ones shielded, by issuer rather than FIFO
> position. Verified on both engines, both service kinds, and the real B18 kill switch:
> **12/12 presses accepted, 0 shed as `chain_budget`, press pre-empts the chain.** That
> was the single item round 8 named as the exit condition, and nothing else had to move.
>
> **The two open Highs are each one branch of one function, and both are mechanically
> contained** — which is what makes this row 6 rather than row 7, since a documented
> convention is explicitly not a mitigation.
> **R9-02** — `base_interpreter.py:4523` selects `after` transitions on the **public
> exported** `AfterEvent`, never on #195's `_EngineAfter`, unlike the
> `DoneEvent`/`ErrorEvent` branch eight lines below. The decisive vector needs no API
> call: a forged `pending_events` record with **no `"engine"` flag** is handed straight
> to the inbox by `_enqueue_restored`, so **a 60-second timer fires instantly from
> untrusted snapshot data even at `strict=True`**. Contained by **CV-C45 (widened to
> match the serialised record, not only the class)**. Fix upstream is one line.
> **R9-04** — a `def` service armed by a transition an `always` rolls **forward** is
> still submitted: **3 of 6 lanes leak**, contradicting
> `docs/_guide/production-characteristics.md:97` verbatim and SCXML 6.4. Contained by
> **CV-C32 + new CV-C46**, which together make all three leaking lanes unreachable.
>
> **The round's pattern is a new one.** Rounds 6–8 were "fixed on the axis the test was
> written against" (engine, then service kind, then issuer provenance). **Round 8
> followed that instruction and it worked** — the service-kind axis is now flat across
> every battle track, and the only surviving `def`/`async` divergence in the entire
> corpus is R9-04's. Round 9's two Highs are a different shape: **a good mechanism
> applied to a proper subset of its call sites.** #195 minted three private engine
> event classes and wired two of three into transition selection; #193 cancelled the
> `def`-service handoff on the rollback epilogue but not the roll-forward one. Both are
> *second* incomplete landings of the same fix. Now standing amendment 14: **when a fix
> introduces a trust mechanism, enumerate every call site it governs and assert the
> list is exhausted.**
>
> **Two upstream tests are actively misleading, and both shaped our triage** (standing
> amendment 15). `test_round8_findings.py::test_always_rollforward_matches_sync`
> **pins the leaking behaviour** its own docs say cannot happen, so the green suite
> certifies the inverse of the published claim and R9-04 shipped uncovered. And
> `test_round6_findings.py::TestAsyncRollbackRearmCycleBounded` fails ~80 % of runs on
> **correct** behaviour by reading a counter at 0.6 s when the `def` lane converges at
> ~1.0 s — we carried it as a possible regression and **reclassified it after polling
> to convergence** (both lanes plateau at exactly **1003 = `maxIterations` + 2**).
> Those are the two ways a green suite stops meaning anything: a test that cannot fail
> on the defect it names, and a test that fails on behaviour that is correct.
>
> **Contracts: 20/20 build clean on both service spellings**, zero `InvalidConfigError`.
> B1–B5+B18 **138/138 async and 138/138 def**; B6–B10 async 52/52, def 51/52 (the one
> FAIL is R9-04, down from 3 at `6db65d8`); **B16–B20 all LIBRARY-GO**. Sync parity
> 15/15 on configuration, action trace *and* service-call trace.
>
> **Constraints: CV-C43 and CV-C31″ RETIRE** (both had R8-01/R8-02 as their entire
> ground; `status` and `last_error` are liveness signals again). **CV-C45 WIDENED.**
> **NEW CV-C46** — the order path never runs on `SyncInterpreter`. CV-C27′, CV-C40 and
> CV-C44 become defence in depth rather than the only check; CV-C42 stands on the
> narrower ground of R9-06; CV-C35 stands, re-grounded, even though R9-03 was refuted.
>
> **For the first time in this study, the binding constraint on our order path is OURS,
> not the library's.** **C-04** (B16 elevation survives `LOGOUT`/`REVOKE`) and
> **C-07b** (B18 kill switch bricked by a guard-denied `RELEASE`) are the only
> Blockers of any kind still open. Both are catalogue defects on **any** runtime, on
> machines the library has already cleared. That is the right problem to have, and it
> is the next thing to work.
>
> Verdict: `54-r9-final-readiness-verdict.md` · register: `53-r9-findings-register.md`
> · refutation: `54-r9-03-refutation.md` · drafts: `issues/post-f28719c/` (**not
> posted**).

> **Round 8 — `main` @ `6db65d8`, 2026-09-21 (merge of PR #191, `fix/0.8.1-round7`). Superseded by round 9.**
> The original 62-finding register remains **fully discharged**; rounds 4–8 have been
> about defects found *by* the battle-tests. Keyed on the commit — `__version__` still
> reports `0.8.0`.
>
> **16 issues verified: 15 fixed in code (10 clean, 5 narrower than claimed), 1
> documentation-only (#174), 0 not-fixed** — the first round with no not-fixed row.
> Suite **3 457 passed** plus one load-sensitive flake, coverage **92.70 %**. **Zero
> true PASS→FAIL gate regressions**; the two deltas are *our* stale `machine_hash`
> fixtures, correctly superseded by #185 and reproduced and attributed directly.
>
> **Post-refutation: 1 Blocker · 3 High · 7 Medium · 4 Low** — the best position in
> eight rounds. Refutation moved **3 of 6** Blocker/High candidates *down*
> (R8-02 Blocker→High, R8-04 High→Medium, R8-06 High→Low) and **none up**. Two of
> those three moves killed claims we ourselves had rated Blocker or High: R8-02's
> "the service runs inline and blocks the process" is false (#149 moved it to
> `run_in_executor`; the stall starves only that machine's inbox and is documented at
> `docs/_guide/production-characteristics.md:93`), and R8-06's security framing is
> false (`structure_hash` is a public unkeyed checksum, not a MAC, so an attacker who
> can edit the blob needs no downgrade at all). **Third consecutive round in which our
> own claims were the thing that did not survive contact** — which is the argument for
> keeping the refutation step.
>
> **What landed, and it is the largest single improvement in the series.** Round 7's
> one ask — parametrise every service-invoking test over `def` / `async def` — shipped
> as `KINDS = ("def", "async def")` in `tests/test_round7_findings.py` (37 tests, both
> engines). The async livelock config fuzz went **58/120 RUNAWAY → 0/120**; a
> 500-config × 2 spellings × 2 engines sweep found **0 hangs, 0 silent runaways,
> 0 lap mismatches**; `maxIterations` is a real bound again and **lane-independent**
> (2 / 5 / 100 → 4 / 7 / 102 service calls, `max + 2` exactly, identical cell for
> cell); and the kill-switch machine that produced **3 547 service calls in 3.0 s**,
> still accelerating, now **plateaus at 1 002** with `last_error = RunawayChainError`.
> **Both round-7 Blockers are closed.** All five control machines (B16–B20) are
> **LIBRARY-GO**, and what still blocks two of them is **ours**.
>
> **The pattern of the round — the entry this register exists to record:**
> *"fixed" has meant "fixed on the issuer the test happened to use."* Round 6 was the
> engine, round 7 the service kind, round 8 the **issuer provenance and chain state**.
> The same lesson three times, one level down each round. The general form, now
> recorded as standing amendment 13 to the gate: **when a fix distinguishes two cases,
> the test must exercise both sides of the distinction — and the arm expected to fail
> must be given work that can actually fail.** The corollary has its own finding this
> round: `tests/test_round7_findings.py:557` parametrises over `KINDS` but gives the
> `def` arm `time.sleep(0.05)` against the async arm's `asyncio.sleep(3.0)`, so the
> parametrisation is decorative and the defect it names (R8-03) shipped green. **A
> parametrised test whose arms are not equally capable of failing is not
> parametrised.**
>
> **The mechanism, in one sentence: the provenance rule #180 introduced was
> implemented on one side of the ledger.** `_deliver_priority` consults *who issued* an
> event when deciding whether to **charge** it (`interpreter.py:2342-2389`) and does
> not consult it when deciding whether to **shed** it (`:1598`), over a single FIFO
> carrying external sends and engine completions together. So a priority event issued
> from an action is never charged and livelocks unbounded and unobservably
> (`status="running"`, `last_error is None`, no drop hook, `start()` never returns —
> against a plain-lane control bounded at 27 laps), while an external priority event
> arriving at an already-tripped chain is silently destroyed as `chain_budget` (8–9 of
> 2 000, `send()` accepted; the `priority=False` control loses 0). **R8-01**, the
> round's only Blocker, the regression surface of #180 itself, and **one function's
> worth of work**. It is not wrappable: we can ban `priority=True` in our own code,
> but the library routes its own completions onto that queue regardless, and the
> livelock starves the very loop thread any in-process watchdog would run on.
>
> **Verdict: DEFER (order path) / GO (non-order paths under constraints)** —
> decision-table row 4. **Row 6 (ADOPT WITH CONSTRAINTS) is otherwise satisfied**:
> open-High is **3** (R8-02, R8-03, R8-05) against a bar of 5, each with a
> mechanically enforced mitigation. Closing R8-01 flips the verdict. Constraints:
> **retired CV-C38, CV-C31′ and the `maxIterations`-is-inert annotation**; **widened
> CV-C42** (`priority=True` forbidden everywhere, any origin); **new CV-C43**
> (out-of-process progress supervisor), **CV-C44** (per-child bring-up bound),
> **CV-C45** (completion events never accepted from a wire). Verdict:
> `49-r8-final-readiness-verdict.md`; register: `48-r8-findings-register.md`; drafts:
> `issues/post-6db65d8/` (**not posted**).


> **Round 7 — `main` @ `221ce7c`, 2026-09-20 (PRs #177/#178 on top of #165/#176). Superseded by round 8 below; retained as the previous position.**
> The original 62-finding register remains **fully discharged**; rounds 4–7 have been
> about defects found *by* the battle-tests. Keyed on the commit — `__version__` still
> reports `0.8.0`.
>
> **12 issues verified: 7 fixed, 2 partial (#167/#168 — one defect), 2
> documentation-only, 1 not-fixed (#175 Case D).** Suite **3 418/0** plus one
> non-reproducible flake, coverage **92.64 %**; `interpreter.py` 89 % → **91 %**.
> **Zero true PASS→FAIL regressions in the gate**, confirmed by direct
> check-by-check JSON diff — and **three regressions introduced by this round's own
> fix work that the gate cannot see**, because no check existed for any of them.
>
> **Post-refutation: 2 Blocker · 4 High · 6 Medium · 8 Low.** Refutation moved **3 of
> 8** Blocker/High candidates *down*, none up, and **refuted one outright** —
> R7-04's budget-renewal cause was killed by our own follow-up evidence (a budget
> sweep flat at ~3.3 laps/event from `maxIterations` 1→1000; our own control burning
> 4.5× the laps with zero starvation; a cause isolation showing the discriminating
> variable is `def` vs `async def`). Recording that plainly, because it is the second
> consecutive round in which our own claims were the thing that did not survive
> contact.
>
> **The pattern of the round — the entry this register exists to record:**
> *"fixed" has meant "fixed on the service kind the test was written against."* It is
> last round's lesson one level down. All three pinned regression tests for the
> invoke-cycle family declare `def svc`, so the suite is structurally blind to the
> `async def` lane the documentation recommends — and **six independently filed
> findings collapse into one defect (R7-01) that a single
> `@pytest.mark.parametrize("kind", ["def", "async def"])` would have caught.**
>
> **The mechanism, in one sentence: WHO issued an event has been replaced by WHEN it
> arrived.** Self-generated work escapes the budget on the coroutine completion lane
> (R7-01 — 28 108 service calls vs **23** for the identical chart with `def`, with one
> variant settling into an **empty configuration** reporting `ok=True`); external work
> is charged on the priority lane (R7-02 — 751 of 1 500 external sends dropped as
> `chain_budget`, control drops zero). Two lines in `interpreter.py`, opposite halves
> of one mistake. Neither is wrappable, and **DC-4 records why**: the only mitigation
> for R7-01 is plain-`def` services, which #174 documents as blocking the machine's
> own `after` timers — and the refutation of R7-04 shows plain `def` has its own
> inbox-starvation failure on the same shape. **There is no service kind that is safe
> on both axes.**
>
> **What closed, and it is real:** the `send(wait=True)` livelock is dead (6/6 hangs →
> 0 on every ablation; 500 fuzzed cyclic configs across both engines, zero livelocks,
> trip observable at the same lap count); the root-level snapshot refusal holds across
> 320 generated parallel machines and 7 622 attempts from 8 windows with zero raw
> exceptions; the receipt matrix `(denied, error, deferred, changed)` is **injective**,
> which **retires W-04a**; and #171 fixed the children-ready race, which **retires
> CV-C37** — replaced by its inverse, CV-C39, because the same fix introduced an
> unbounded `await start()`.
>
> **Register verdict on `221ce7c`: DEFER (order path) · GO (non-order paths) under
> CV-C01…CV-C42.** Decision-table row 4. Absent the two Blockers this is row 6 —
> 4 High, each mechanically mitigated. Full reasoning, the decision-table walk, the
> constraint ledger and the recomputed mandatory configuration block:
> `44-r7-final-readiness-verdict.md`.

> **Round 6 — `main` @ `cec108b`, 2026-09-20 (PR #164 merged). Current position.**
> The original 62-finding register is **fully discharged**: every Blocker and High
> from the 0.7.0 review is closed or superseded, and rounds 4–6 have been about
> defects *found by* the battle-tests, not the original list. Keyed on the commit —
> `__version__` still reports `0.8.0`.
>
> **26 issues verified: 24 closed, 1 partial (#122 — a doc fix where the repro
> criterion asked for a drain-loop fix), 1 not-fixed (#157 — reopened on **narrower**
> grounds after our own claim was refuted).** Suite **3 399/0**, coverage **92.77 %**
> against the new 90 % floor. **3 Medium regressions** (`after` lateness 88–92 ms vs a
> 50 ms budget; `stop()` leaves some duplicate-instance receipts unresolved). A fourth
> reported regression, LC-01, was **our harness asserting a pre-#145 contract** — the
> library is right.
>
> **Post-refutation: 2 Blocker · 2 High · 7 Medium · 9 Low.** Refutation moved **6 of
> 10** Blocker/High candidates *down* and none up; three of those downgrades were
> corrections to claims of ours that did not survive contact (`send_threadsafe` does
> **not** bypass the inbox bound; `internal=True` grants nothing extra; a plain-`def`
> service does **not** block the loop, and the defect does not survive documented
> `async def` usage).
>
> **The pattern of the round — and the entry this register exists to record:**
> *"fixed" has meant "fixed on the engine the issue was filed against."* Three of the
> four candidate Blockers are async-only faults whose sync counterpart is provably
> correct: the `always`-into-completed-`invoke` hang (R6-01, #144's rule never ported
> out of `sync_interpreter.py`), the unconditional system-event exemption at
> `interpreter.py:1427` (R6-02), and `rollback` + `invoke.onDone` re-invoking ~1400×/s
> with `status="running"` (R6-03). **One upstream change closes all three**, and an
> `Interpreter`/`SyncInterpreter` parity test class would have caught all three at
> authoring time.
>
> **The register's oldest structural complaint is, however, now closed.** #142/#143
> landed **one** configuration-legality predicate — exactly one leaf per region —
> enforced on **both** the snapshot write side and the read side, with the read side
> provably reusing the write-side function. Torn parallel snapshots go **27.4 % → 0 %**;
> 2 000 quiescent snapshot/restore cycles give 2000/2000; a 350-machine random-parallel
> property yields 1 217 snapshots with zero illegal configurations. That was the single
> design change rounds 4 and 5 both asked for, and it arrived done properly.
>
> **Constraint movement:** **CV-C30 retired** (parallel regions safe again),
> **CV-C27 retired** to a one-line residual (CV-C27′), **CV-C31 retired and inverted** —
> `"fail"` is safe per #145 while `"rollback"` is now the dangerous policy on the order
> path (CV-C31′), **CV-C34 retired (done)**. CV-C32 **does not** retire: R6-09's
> downgrade depends on it. New: **CV-C35** (no `always` into an invoked child),
> **CV-C36** (every `send_threadsafe` future is read), **CV-C37** (`children_ready()`
> barrier).
>
> **Gate: DEFER (order path) / GO (non-order paths)** on row 1. Absent the two Blockers
> the open-High count is **2**, inside the bar of 5, both mechanically mitigated — i.e.
> row 6, *adopt with constraints*. The entire distance to adoption is one upstream
> change. See `39-r6-final-readiness-verdict.md`; register `38-r6-findings-register.md`.

> **`main` @ `3c527b0` verification, 2026-09-18 (PR #83 merged).** Every row now
> carries a **`main@3c527b0` status** column. **Identify that build by commit —
> `__version__` still reports `0.8.0` on it**, two reviews running. The
> `5327ba6` and 0.8.0 columns are preserved as written.
>
> **Headline: three good fixes, one regression, and the gate moves to DEFER.**
> **#43** (task-collapse), **#79** (provenance-based system events) and **#80**
> (`ErrorEvent`) all verify 7/7, 10/10 and 8/8 against their own criteria; the
> gate's LC-28 check flips FAIL→PASS at 1.0 tasks/child; the suite grows to
> 3 242/13/0 at 90% coverage.
>
> **But #79 and #80 each met the snapshot boundary (#47) without being taught
> about it.** **G-2** — provenance is not persisted, so a restored `escalate`
> event becomes user traffic and fails a machine configured
> `onUnhandled: "error"`, where the old name rule gave the same answer either
> side of a restore. **This is the one regression in the window.** **G-3** — a
> pending `ErrorEvent` is silently dropped by `get_persisted_snapshot()`
> (`isinstance(e, Event)` filter; `ErrorEvent` is a `NamedTuple`), so a machine
> restores believing the invoke never failed. **G-1** — `Event.system` is a
> public, user-settable field that bypasses `strict`, `onUnhandled` and `"*"`.
>
> The register now stands at **28 FIXED-DEFAULT · 5 FIXED-OPT-IN · 1 PARTIAL ·
> 0 NOT-FIXED** across the 34 filed issues: **13 confirm closed · 3 REOPEN**
> (#31 engine parity, #77 raise-on-overflow, #79 provenance). Twenty-four
> canonical findings (6 High, 11 Medium, 7 Low) → 16 new issues, 8 ride-along
> comments.
>
> **Gate: DEFER**, on decision-table row 5 — 7 High open against a bar of 5.
> Arithmetic, not a re-weighting: all four Blockers stay closed and the three
> new Highs all come from PR #83. This is a **pre-release** build; fixing G-2
> and G-3 before 0.8.1 tags returns the count to 5 and restores row 6.
>
> **M-1 still gates the order path and is now harder**: the `deferred_count`
> mitigation specified at `5327ba6` reads `0` at the caller's `await` point for
> the deferred case *and* the true negative. CV-C06's clause is **withdrawn as
> unsound**. CV-C15 is **narrowed** (case-insensitivity retires; the rule
> becomes the six `ENGINE_EVENT_SHAPES` prefixes); **CV-C19…CV-C22 are new**.
> See `26-verify-3c527b0-verdict.md`.

> **`main` @ `5327ba6` verification, 2026-09-18.** Every row now carries a
> **`main@5327ba6` status** column recording its classification against the
> unreleased pre-0.8.1 build. **Identify that build by commit — `__version__`
> still reports `0.8.0` on it.** The 0.8.0 column is preserved as written.
>
> **Headline for this pass: no regressions.** Of the 34 individually filed
> issues the register now stands at **25 FIXED-DEFAULT · 5 FIXED-OPT-IN ·
> 3 PARTIAL · 1 NOT-FIXED**. Nine issues are closable (#27, #37, #39/#75, #44,
> #50/#76, #51/#78, #52) and six stay open, all narrowed (#31, #43, #60, #77,
> #79, #80). Thirteen new defects were found (3 High, 6 Medium, 3 Low, 0
> Blocker); the one that governs the order path is **M-1** — a deferred event's
> `send(wait=True)` receipt resolves `changed=False, error=None`, which is the
> composition of the two settings CV-C01 and CV-C06 *mandate*.
>
> Two CandleViewer constraints **retire** into the library (CV-C06's
> fresh-`Event` clause, CV-C14's gateway validation) and three are **added**
> (CV-C16, CV-C17, CV-C18). See `22-verify-main-verdict.md` for the verdict,
> the dispositions and the constraint table.

> **0.8.0 re-evaluation, 2026-09-17.** Every row also carries a **0.8.0 status**
> column recording its classification against `xstate-statemachine` 0.8.0
> (commit `9bf6065`). Classifications are **FIXED-DEFAULT** (correct with no
> configuration), **FIXED-OPT-IN** (fix verified, but the 0.7.x behaviour is
> still the default — closed only while the mandated config is lint-enforced),
> **PARTIAL**, and **NOT-FIXED**.
>
> The severity and "Blocks?" columns are the **0.7.0** assessment and are
> preserved as written — this register is a historical record as well as a live
> one. Read the 0.8.0 status column for the current position, and
> `17-reeval-0.8.0-verdict.md` for the gate decision, the mandatory machine
> configuration (§4) and the 17 new defects (N-1…N-17) found by the adversarial
> and diff reviews.
>
> **Headline:** of the 34 individually filed issues, **23 are FIXED-DEFAULT,
> 6 FIXED-OPT-IN, 5 PARTIAL, 0 NOT-FIXED.** All four filed Blockers are closed —
> but two of them (LC-01, LC-03) only by opt-in policy.

**One deduplicated register.** Supersedes the `LC-01…LC-24` list in `10-fit-analysis.md` Part D and the `CR-1…CR-10` list in `11-adversarial-review.md`. IDs are renumbered `LC-01…LC-48`; the **Old ID** column preserves traceability to the source documents and probe ids.

**Sources merged:** `01-library-core.md` (source study), `02-quality-and-tests.md`, `03-docs-examples-gaps.md`, `04-performance-concurrency.md` (benches `bench_a`–`bench_i`, `g1`–`g11`), `05-semantics-probes.md` (probes `A1`–`A20`, `B1`–`B14`, `C1`–`C17`), `06-alternatives-ecosystem.md`, `10-fit-analysis.md` (`LC-01…LC-24`, B1–B20), `11-adversarial-review.md` (`CR-1…CR-10`, `adv01`–`adv08`, MUST/MUST-NOT).

**De-duplication against upstream:** every row was checked against `_ref/xstate-statemachine/docs/FEATURE_GAP_ANALYSIS.md` (73 gaps, all closed in 0.6.0 — historical record only) and `CHANGELOG.md` `[0.6.0]`/`[0.7.0]`. Rows that restate an already-fixed gap were dropped. `gh issue list -R basiltt/xstate-statemachine --state all --limit 50` returns **exactly one issue ever** (#17, closed, camelCase→snake_case `logic_providers` mapping) — so there are **no duplicate upstream issues** to collide with; every `Upstream-issue = Y` row below is a genuinely new filing.

### Severity scale (relative to a trading OMS, not to the library in general)

| Severity | Meaning |
|---|---|
| **Blocker** | Can cause financial loss or silent data corruption on the order path. Must be closed (fixed or mitigated with an enforced mechanism) before live use. |
| **High** | Silent wrongness, or a hard architectural constraint that forces a design workaround. |
| **Medium** | Surprising or costly; worked around at moderate expense. |
| **Low** | Ergonomics, waste, or maintainability. |

All `file:line` references are relative to `_ref/xstate-statemachine/src/xstate_statemachine/`. All probe result files are under `CandleViewer/docs/research/xstate/{probes,bench,adversarial}/`.

---

## A. Correctness / semantics bugs

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-01** | LC-01, CR-1, g2 | An action that raises still commits the transition, with no programmatic error channel | Bug | **Blocker** | `base_interpreter.py` action handler catches `Exception`, logs `"🔥 Action '%s' raised…; skipping remaining actions"`, continues; `interpreter.py:667-689`. Probe `bench_g2_error_channel.py`: `actions:["first","explode","third"]→b`, `third` skipped but `entry_b` ran, ended in `b`, `status=="running"`, no exception, `on_transition` fired as success. Reproduced on **both** engines | B1, B2, B3, B4, B5, B6, B7, B8, B19, B20 | **Y** | Add per-machine `action_error_policy: continue \| rollback \| fail`. The rollback path already exists for *transition* failures (0.6.0 "Transition atomicity") — reuse it. Minimum viable: pass `failed_actions: list[str]` into `on_transition` and fire a dedicated `on_transition_failed` hook | **Y**  **FIXED-OPT-IN** — `actionErrorPolicy:"rollback"/"fail"` (#27). Default `"continue"` still commits, now observable via `last_transition_ok`. Rollback is not an effect transaction (N-5) | **FIXED-OPT-IN** — unchanged. Rollback now also **withdraws self-`raise`d events** (#27), verified in 8 hostile shapes; idle no-action checkpoint skip reproduced at 0.998–1.056x. Still not an effect transaction (`sendTo` survives). **close #27** | FIXED-OPT-IN — unchanged. F-7 rides along (checkpoint-skip predicate ignores `always`/`on` on the target). **confirm #27 closed** |
| **LC-02** | LC-04, A10, A19 | `always` with a self-target deadlocks silently | Bug | **Blocker** | `base_interpreter.py:1769` — `if target_state == transition.source and not transition.reenter` classifies *any* self-target as internal, so `entry` never re-runs and the guard is never re-evaluated. Probe A10: `loop` with `entry:["inc"]`, `always:[{target:"done",guard:"n>=5"},{target:"loop"}]` parked at `loop` with `n==1`, `is_running==True`, no error. A19: identical loop via a distinct intermediate state converges to `n==5` | B5 (iceberg slicing), B9 (rule counting), B3 (retry loops) | **Y** | Treat an **explicit** self-target as external by default (XState v5), with `internal:true` / omitted target as the opt-out; read `internal` as well as `reenter`. Failing that, raise/warn loudly at `create_machine()` on any `always` self-target — it can never make progress | **Y**  **FIXED-DEFAULT** — build-time rejection of dead `always` self-targets (#29) | FIXED-DEFAULT — unchanged, no regression | unchanged |
| **LC-03** | LC-03, C17, §2.6 | Events with no handler in the current state are silently discarded | Semantic divergence from XState v5 | **Blocker** | Probe C17, deterministic across 10 runs: `send("NEW")` → `pending` (invoke ack ~5 ms); three subsequent `PARTIAL`/`FILL` all vanished. Expected `oms.filled, filled==30`; observed `oms.live, filled==0`. Same "no transition found" path as an unknown event (`_process_event`) | B1, B2, B3, B4, B5, B6, B7, B12, B13, B19 | **Y** | Implement XState `defer`/deferred semantics, or at minimum a machine-level `on_unhandled: "ignore" \| "defer" \| "error"`. Today "ignore" is the only behaviour and it is the silent one | **Y**  **FIXED-OPT-IN** — `onUnhandled:"defer"/"error"` (#28). 9/9 adversarial; closes LC-17/LC-18 | **FIXED-OPT-IN** — unchanged. **New: M-1** — a deferred event's `wait=True` receipt reports `changed=False, error=None`. See CV-C06's new `deferred_count` clause | FIXED-OPT-IN — unchanged. **M-1 STILL-PRESENT and its mitigation is now unsound**: `deferred_count` reads 0 at the caller's `await` point for the deferred case *and* the true negative. CV-C06's clause WITHDRAWN |
| **LC-04** | A3/A17, §2.3 | A self-transition with an explicit target does not re-enter (XState treats it as external) | Semantic divergence from XState v5 | High | Probe A3: `{"target":"A","actions":["tAct"]}` from `A` logs only `["tAct"]` — no `xA`, no `eA`. A17: `reenter:True` correctly yields `["xA","tAct","eA"]`. `"internal": False` is **not read**. Same root cause as LC-02 (`base_interpreter.py:1769`) | B1, B3, B5, B13 | N (house rule A4 + linter) | Same fix as LC-02; additionally accept `internal` as a recognised key | Y (grouped with LC-02)  **FIXED-DEFAULT** — `internal:false` honoured as `reenter:true` (#29) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-05** | LC-06, C10, §2.7 | `raise` is queued behind pending external events — no macrostep semantics | Semantic divergence from XState v5 | High | Probe C10: expected `["entry","RAISED","EXTERNAL"]`, observed `["entry","EXTERNAL","RAISED"]`. `raise` goes through `_deliver` onto the same FIFO `asyncio.Queue` as external sends | B2 (`EVALUATE` self-raise), B3, B9 | N (binding rule: aggregate decisions are pure functions of context) | A separate internal queue drained to exhaustion before the next external event is dequeued — this is the SCXML macrostep algorithm the library otherwise implements faithfully | **Y**  **FIXED-DEFAULT** — SCXML internal event queue (#36); probe C10 now PASS | FIXED-DEFAULT — unchanged | unchanged |
| **LC-06** | LC-07, 01 §4.8/§14.4 | Over-forgiving target resolution can silently bind the wrong state | Bug | High | 4-stage fallback in `base_interpreter.py:1164-1261` ending in an exhaustive tree walk matching on the **last id segment** (`:1238-1250`). `target:"filled"` can resolve to an unrelated `…other.branch.filled`. `filled`/`cancelled`/`failed` appear in Order, Leg and every algo | B1, B2, B3, B4, B5, B6, B7 | N (house rule A5: absolute targets + build-time validator) | Make the last-segment tree walk opt-in; `strict_targets=True` as the default. Warn on every fallback stage beyond exact resolution | **Y**  **FIXED-DEFAULT** — `strict_targets=True` by default (#34). Type is `InvalidConfigError`, not `StateNotFoundError` | FIXED-DEFAULT — unchanged | unchanged |
| **LC-07** | LC-16, A5/A18, §2.4 | Relative `.child` targets resolve to nothing, silently | Bug | High | Probe A5: `target:".A2"` → actions `[]`, state unchanged at `m.A.A1`, nothing raised; `"A2"` and `"#m.A.A2"` both work. A18: `.zzz` is also a silent no-op. `_resolve_target_state_node` returns `None`; the caller treats `None` as "no transition" | B9/B12 (rule IR), all config-authored machines | N (house rule A5) | Implement leading-dot relative syntax (it is standard XState and all over the Stately docs), or reject it explicitly at `create_machine()`. A `None` resolution must never be silently swallowed | **Y** (grouped with LC-08)  **PARTIAL** — `.child` resolves into source descendants (#31), but the sibling fallback is still reachable **and silent** unless `strictTargets:true` | **PARTIAL** — child-first resolution, deprecation-warned fallback, warning throttling and build-time rejection all confirmed. Engine parity under `strict_targets=False` still unmet. **keep #31 open**, re-scoped (+F-10 registry leak) | **PARTIAL — unchanged.** Engine parity under `strict_targets=False` still unmet by code. **REOPEN #31** (+F-10 ride-along) |
| **LC-08** | LC-16, C15, §2.5 | An unknown target state is never validated and is a silent runtime no-op | Missing feature | High | Probe C15: `{"on":{"GO":"nowhere_at_all"}}` passes `create_machine()` and does nothing on `send("GO")` — state unchanged, `running==True`, nothing raised. Contrast C14: an unknown **action** name correctly raises `ImplementationMissingError` at `create_machine()` time | B9 (compiled rule IR — deploys clean, fails open), all | N (build-time target validator, deploy-time for compiled rules) | Validate targets in `create_machine()` exactly as actions are validated | **Y**  **FIXED-DEFAULT** — build-time target validation, all failures in one message (#30) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-09** | LC-08, A20, g2 | A guard that raises is swallowed as `False` | Improvement | High | `base_interpreter.py:2911-2925`. Probe A20 + bench `g2`. Documented behaviour, but a *crashing* risk check and a *failing* risk check are indistinguishable, and both fall through to a permissive branch in an `or` composition | B8 (native-SL invariant), B17 (live gate), B18, B20 | N (house rule A6: deny-polarity, own try/except) | `guard_error_policy: false \| true \| raise`, defaulting to today's behaviour. At minimum fire `on_guard_error` on plugins — today the failure is invisible to every observer | **Y** (grouped with LC-10)  **FIXED-DEFAULT** (observability: `on_guard_error` fires under defaults) / **FIXED-OPT-IN** (outcome: `guardErrorPolicy:"raise"`) (#35) | FIXED-DEFAULT / FIXED-OPT-IN — unchanged | unchanged |
| **LC-10** | LC-19, A6, §2.8 | Guards continue to be evaluated after a branch has been selected | Bug | Medium | Probe A6: guard array `[g1 false, g2 true, g3 true]` selects `m.second` correctly but calls all three | B1, B8, B9 | N | Short-circuit guard evaluation at the first match | Y (grouped with LC-09)  **FIXED-DEFAULT** — grouped under #35 | FIXED-DEFAULT — unchanged | unchanged |
| **LC-11** | g3, 04 §7 | An entry action raising during `start()` does not fail the start | Bug | High | Bench `g3`: `start()` **succeeds**, `status=="running"`, the state is entered anyway, entry logic never completed. Same silent-failure family as LC-01 | B1, B11, B13, B19 | N (covered by the `@cv_action` wrapper) | Same `action_error_policy` as LC-01, applied to the initial-entry path | Y (grouped with LC-01)  **FIXED-OPT-IN** — `actionErrorPolicy` covers `start()`'s initial entry (#27) | FIXED-OPT-IN — unchanged | unchanged |
| **LC-12** | 01 §14.14 | `spawn_blocking_<key>` is honoured only by the sync engine; the async engine spawns non-blocking | Semantic divergence from XState v5 | Medium | `interpreter.py:615` tests `startswith("spawn_")`, so `spawn_blocking_x` resolves to service key `x` and spawns non-blocking. Sync-only handling in `sync_interpreter.py`. Not covered by `test_engine_conformance.py` | B2, B3 (leg actors) | N (we never use `spawn_blocking_`) | Either implement blocking spawn on the async engine or raise `NotSupportedError` there. A silently different meaning for the same action name across engines is exactly the class `test_engine_conformance.py` exists to prevent | **Y**  **FIXED-DEFAULT** — `spawnBlockingTimeout` bounds the wait (#41); async `spawn_` still blocks for a sync-bodied child | FIXED-DEFAULT — unchanged | unchanged |
| **LC-13** | 01 §13.13 | Duplicate `systemId` registration silently replaces the previous actor | Bug | Medium | `base_interpreter.py:1429-1437` — warns and overwrites | B2, B3 (N legs registered under per-leg system ids) | N (application-owned registry, see LC-16) | Enforce `systemId` uniqueness — raise `ActorSpawningError` on a duplicate | Y (grouped with LC-16)  **FIXED-DEFAULT** — duplicate live `systemId` raises `ActorSpawningError` (#40) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-14** | 01 §14.11 | `_prepare_event` forwards arbitrary duck-typed objects unchecked | Code quality | Low | `base_interpreter.py:1148-1153` — any object with `.type`/`.payload` is forwarded with no validation | all | N | Validate the duck-typed branch, or drop it in favour of an explicit protocol | N (group H nit)  Not re-tested — Low, group H nit | Not re-tested — Low, group H nit | Not re-tested — unchanged |

---

## B. Persistence & recovery

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-15** | CR-1 | A state produced by a failed action is **durably persisted** as truth | Bug | **Blocker** | Probe `adv01` t5: `trace=['persist','explode','entry_b']`, `states=['x.b']`, `status=running`, `SNAPSHOT PERSISTS THE BROKEN STATE: ['x.b'] ctx={'persisted':True,'in_b':True}`. The snapshot path has no visibility into whether the transition that produced the state was clean; `from_snapshot` restores it without complaint | B1, B2, B3, B19 | **Y** | Consequence of LC-01; closing LC-01 closes this. Independently: expose a per-transition cleanliness flag (e.g. `snapshot["last_transition_ok"]`) so a persistence layer can gate on it. **Our side (MUST-01):** the snapshot writer refuses any context carrying `_fault`, writes a `quarantined` marker row and alerts P1 | Y (grouped with LC-01)  **CLOSED via LC-01** — `last_transition_ok` + rollback; our snapshot fault gate (MUST-01) retained as defence in depth | FIXED-OPT-IN — unchanged (rides on LC-01/#27) | unchanged |
| **LC-16** | LC-02, C16, §2.2 | `sendTo` cannot address an actor by its `invoke` `id` or `systemId`; ambiguity drops the event | Bug | **Blocker** | Probe C16: `by_service_key("child")→"PONG"` ✅; `by_invoke_id("kid")→None` ❌; `by_system_id("kid")→None` ❌ with `invoke:{"id":"kid","src":"child","systemId":"kid"}`. `interpreter.py:958-964` mints ids as `parent:<serviceKey>:<uuid>` — the declared `id` never enters the string. `_resolve_actor_target` (`base_interpreter.py:1329-1391`) matches on `actor_id.split(":")[1:]`; ambiguity → `logger.warning` + **dropped event** | B2, B3 (ADR-0008 fan-out is exactly "N children from one `src`, addressed individually") | **Y** | Include the declared `id` in the minted actor id (`parent:<id>` when `id` is given) and make `systemId` an exact-match first-class key in `_resolve_actor_target`. An **ambiguous** target must raise, never drop | **Y**  **FIXED-DEFAULT** — `sendTo` by `id` and `systemId` (#40); probe C16 now PASS. Unresolved `sendTo` target may still log-and-drop | FIXED-DEFAULT — unchanged | unchanged |
| **LC-17** | CR-2 | A persisted deferral buffer is never drained after a crash — the universal LC-03 workaround strands fills | Missing feature | **Blocker** | Probe `adv06` `defer_crash`: `snapshot state=['o.submitting'] _deferred=[e0,e1,e2]` → after restore+start: `state=['o.submitting'] filled=0 _deferred_still=3`. The drain lives in `submitted`'s `entry`; `submitted` is reachable only via `done.invoke.place`; the invoke is not restarted on restore (LC-19); so `entry` never runs. Happy path works (`t_ok: filled=3`) — which is why this passes every test that does not kill the process mid-invoke | B1, B2, B3, B4, B5, B6, B7 | **Y** | Library-side: native `defer` (LC-03) with a documented boot-time drain. **Our side (MUST-03/MUST-04):** drain `_deferred` unconditionally at boot *before* re-driving invokes; alert on any `_deferred` non-empty > 5 s via `cv_machine_deferred_depth` | Y (grouped with LC-03)  **CLOSED via LC-03** — library-owned defer buffer survives snapshots; alert on `deferred_count` | FIXED-OPT-IN — unchanged (rides on LC-03/#28) | unchanged |
| **LC-18** | CR-3 | The deferral workaround destroys exchange event ordering | Semantic divergence from XState v5 | High | Probe `adv06` `t_reorder`: `delivery order = ['old0','old1','old2','LIVE']` — held in this run, but guaranteed by nothing; `drain_deferred` re-`send`s behind live traffic and `create_task(send)` gives no ordering guarantee. The library's strict-FIFO guarantee (bench `g7`, 500/500, per-producer order preserved) **does not extend across a defer/drain boundary** | B1, B2, B3 | N (MUSTNOT-04) | Native `defer` that re-injects at the *head* of the queue in original order. **Our side:** `apply_fill` and all aggregation actions must be order-independent and sort by `(ts_exec, seq)`. `10` C2.3's "ordering is exactly what an OMS needs" is **incorrect as written** once A3 is applied | Y (grouped with LC-03)  **CLOSED via LC-03** — replay is at the **head** of the queue in original order (verified 9/9) | FIXED-OPT-IN — unchanged (rides on LC-03/#28) | unchanged |
| **LC-19** | LC-10, C7, §2.10 | Restore does not restart invokes or re-run entry actions — parked machines look healthy | Missing feature | High | Probe C7: a snapshot taken mid-`invoke` restored with `calls==0`. `base_interpreter.py:814-958`; docstring `:827-831` documents it. An order restored in `submitting` has no request in flight, a reconciliation in `fetching` has no sweep, a TWAP in `armed` has no deadlines — all report `running` | B1, B2, B3, B5, B6, B7, B13, B19 | N (C3.3 boot procedure) | Opt-in `restart_services=True` on `from_snapshot`, or at minimum an API reporting "these restored states have invokes that are not running" so the application can drive them without walking the tree itself | **Y** (grouped with LC-20)  **FIXED-OPT-IN** — `from_snapshot(restart_services=True)`; `pending_invocations()` is unconditional (#44). `status` still lies about dormancy | **FIXED** — `has_dormant_invocations` now on **both** engines with confirmed parity (#44). `status` still not a liveness signal, by design. **close #44** | FIXED — unchanged. Now *more* load-bearing: **G-3** means a snapshot can lose the `ErrorEvent` entirely, so `pending_invocations()` reconciliation is the only signal left (CV-C20) |
| **LC-20** | LC-05b, C6 | Restore does not resume pending `after` timers | Missing feature | High | Probe C6: `fired==False` 400 ms after restoring a 150 ms timer; bench `bench_d_snapshot.py` — a machine snapshotted with 700 ms left on an 800 ms timer never fired, even 1.5 s later. Documented, so a limitation rather than a bug | B5, B6, B7, B8, B13, B19, B20 | N (A2: deadlines are absolute timestamps in context, re-armed by an external scheduler) | Opt-in `resume_timers=True` on `from_snapshot` using persisted remaining durations | Y (grouped with LC-19)  **NOT-FIXED** — `after` timers are still not resumed on restore; probe C6 still FAILs. Out of #44 scope | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-21** | LC-11, 01 §9/§13.12 | No snapshot schema version | Missing feature | High | `get_persisted_snapshot()` (`base_interpreter.py:690-745`) emits `{status, context, state_ids, configuration, output, error, history, actors, system}` — confirmed field-by-field by `adv07`. No `version`, no machine identity | all persisted machines (B1–B8, B11, B12, B13, B16, B19, B20) | N (our own `cv_schema_version` + `machine_hash` envelope + upcaster registry) | Write a `version` field into `get_persisted_snapshot()` and validate it on restore; optionally a machine-structure hash so semantic drift (LC-23) is detectable | **Y**  **FIXED-DEFAULT** — snapshot envelope v1 (#45). `machine_hash` ignores action params (N-9) | FIXED-DEFAULT — unchanged; snapshot format not changed on this commit | FIXED-DEFAULT — serialised format unchanged on this commit. **Flagged:** fixing G-2/G-3 will likely change the shape and re-open the schema-version question |
| **LC-22** | CR-7 row 2, 01 §14.9 | `from_snapshot` assigns the restored context wholesale — new machine-default keys are missing, and the caller's dict is aliased | Bug | High | `base_interpreter.py:872` sets `interpreter.context = snapshot["context"]` — no merge of machine defaults and **no deep copy**. `adv01` context-drift case: restores, but new keys `cum_qty`/`venue` **MISSING** → v2 actions hit `KeyError` or silently use `.get()` defaults | B1, B2, B3, B9 (any machine whose context schema evolves) | N (MUST-06 restore wrapper merges `{**machine_defaults, **snapshot_context}`) | Merge machine-default context keys under the restored context, and deep-copy on assignment so the caller's parsed dict does not alias live machine state | **Y**  **FIXED-DEFAULT** — deep-copy + merge over machine defaults (#46). **Retires MUST-06** | FIXED-DEFAULT — unchanged | unchanged |
| **LC-23** | CR-7 row 3 | Semantic drift at a stable state id restores silently into a different machine | Missing feature | Medium | `adv01` drift matrix: state **renamed** → `StateNotFoundError` ✅ fails loud (the strongest failure signal the library gives anywhere — worth locking in with a regression test); **same id, different semantics** (guard added to `FILL`) → restores silently, order enters `submitted`, `FILL` now guarded false, **order stuck forever**. OMS evolution is far more often "add a guard" than "rename a state" | B1, B2, B3, B5, B6, B7 | N (machine_hash in CI, MUST-12; no-op upcasters banned by MUSTNOT-09) | Ship a machine-structure hash alongside the snapshot version (LC-21) so the library itself can detect drift | Y (grouped with LC-21)  **FIXED-DEFAULT** — `machine_hash` + `SnapshotDriftError` (#45), modulo N-9 | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-24** | CR-8 | Events in the interpreter queue are lost on crash and are invisible in the snapshot | Missing feature | High | `adv01` t4: 50 events sent; snapshot taken immediately shows `n=0`; context after stop `n=0`; **50 events LOST on stop**. `adv07` field inventory confirms no pending-queue field. `send()` is 2.26 µs, a transition is 33 µs — the queue is where events *live* under any burst (Budget 1's 165 ms p95 is 165 ms of events sitting in exactly this volatile place) | B1, B2, B3, B9, B13 | N (MUSTNOT-07: never ack a bus message before the transition is observed) | Include pending queue contents in `get_persisted_snapshot()`, or expose a `drain_pending()` so a shutdown path can flush them durably | **Y**  **FIXED-DEFAULT** — `pending_events`, `drain_pending()`, `stop(drain=True)` (#47). Bare `stop()` still drops, now loudly | FIXED-DEFAULT — unchanged; `stop(drain=True)` still mandated (CV-C08 family) | FIXED-DEFAULT — unchanged for `Event`s. **G-3 NEW:** pending `ErrorEvent`/`DoneEvent` are silently dropped by `get_persisted_snapshot()` (`isinstance(e, Event)` filter). **G-2 NEW:** provenance lost across a restore — **the one regression in this window**. Drives CV-C20 |
| **LC-25** | LC-21 | `get_snapshot()` hardcodes `indent=2` | Improvement | Low | Bench `bench_d_snapshot.py`: 3,976 B as produced vs 2,249 B compact — **1.77× inflation**; `get_persisted_snapshot()` is also 30 % faster (203.3 µs vs 289.7 µs) | B11, B12 (recorder writing per-entity snapshots) | N | Accept `**json_kwargs`, or default to compact | Y (grouped, group F/H)  Not re-tested — Low | Not re-tested — unchanged | Not re-tested — unchanged |

---

## C. Actors / invoke / timers

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-26** | LC-05, 04 §3 | `after` timers degrade catastrophically under event-loop load | Performance | High | `bench_c_timers.py`: idle error +6 to +16 ms (Windows' ~15.6 ms granularity is a floor); 100 busy interpreters → ~+500 ms; **500 busy interpreters → +2,250 ms for a 10 ms timer**, roughly the same absolute error at 100 ms and 1 s — the signature of event-loop starvation. `adv02` independently: 5 ms sleeps drift ~10.9 ms p50 with an **idle** loop | B5 (250 ms refills), B6 (TWAP), B7 (200 ms chase), B8 (2–3 s SL deadline), B13 (10 s pong), B19 (5 s watchdog), B20 | N (A2: external `MonotonicScheduler` owns every deadline) | Run timers on a dedicated task/thread not starved by the event queue — or, at minimum, **document the starvation characteristic**; it is not mentioned anywhere in the docs | **Y**  **FIXED-DEFAULT** — priority timer lane (#48). **14.5x better but BENCH-6 still missed**: 2530 ms → 174.4 ms vs ≤100 ms. CV-C12 stands | FIXED-DEFAULT — unchanged; BENCH-6 still missed, CV-C12 stands | unchanged |
| **LC-27** | 01 §13.5 | No clock injection / virtual time — `after` cannot be made deterministic in tests | Missing feature | High | No `Clock` abstraction anywhere in the source; both engines call `asyncio.sleep` / `threading.Event.wait` directly (`interpreter.py:999-1040`, `sync_interpreter.py:1257-1327`). `helpers.wait_for` polls real time at 5 ms | B5, B6, B7, B12 (replay determinism) | N (A2 externalises timing) | Add a `SimulatedClock`/injectable clock as XState v5 has. This is the single change that would let the algo families (B5–B7) keep their timing in-machine | **Y**  **FIXED-DEFAULT** — `Clock`/`RealClock`/`SimulatedClock` (#49). `increment()` is **ms** and returns a `_MustAwait` that must be awaited | FIXED-DEFAULT — unchanged. **New: F-2** — the `sync=` shim treats a `**kwargs` clock as consent | FIXED-DEFAULT — unchanged. **F-2 still present** (`**kwargs` shim) |
| **LC-28** | CR-6, 01 §12 | Every invoked child actor costs **two** asyncio tasks, one polling at 5 ms | Performance | Medium | `_ACTOR_POLL_INTERVAL = 0.005` (`interpreter.py:81`), poll loop `:1214-1215` — `while child.status=="running": await sleep(0.005)`. Probe `adv04`: `children=0→2 tasks; 10→22; 50→102; 200→402` — exactly linear, 2 per child. At `10` C1.2's worst case (500 legs + 600 slices) that is ~2,200 tasks, ~1,100 waking 200×/s ⇒ ~220,000 wakeups/s. Mitigating: `adv02` measured no detectable loop degradation at 200 children | B2, B3, B5, B6 | N (MUSTNOT-08: ≤200 concurrent children without re-measuring) | Await a completion future/event instead of polling. The child already has a terminal-status transition to signal from | **Y**  **PARTIAL** — poll→future done, `wait_done()` added (#43); task count per idle child is still **2**, not ≤1 | **NOT-FIXED** (task-count criterion) — still a flat **2.0** asyncio tasks per child at n=2/10/50. Poll→`wait_done()` half holds (0.58 ms `onDone`, zero idle wakeups). **keep #43 open**, re-scope criteria | **FIXED** — #43's task-collapse half landed. 1.0 tasks/child at n=2/10/50 (was 2.0), `onDone` 0.96 ms median, zero idle wakeups, clean teardown. Gate LC-28 FAIL→PASS. **confirm #43 closed** (+G-9 ride-along) |
| **LC-29** | LC-12, 01 §13.3 | `invoke.input` is static and is ignored entirely for child-machine actors | Missing feature | Medium | `InvokeDefinition.input` is a static dict (`models.py:469`); `_spawn_and_manage_actor` never reads `invocation.input` (`interpreter.py:1173-1252`). XState's callable `input: ({context,event}) => …` has no equivalent | B2, B3 (passing a leg's frozen `profile_snapshot` into the child) | N (spawn explicitly and seed the child's context ourselves) | Support callable `input` and actually apply it to spawned child machines' context | **Y**  **FIXED-DEFAULT** — callable `invoke.input`, forwarded to child machines (#42) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-30** | LC-17 | No per-transition or per-invoke timeout | Missing feature | Medium | Absent from the API surface (01 §2). 24 §11.5 E8 mandates `evaluation_timeout_ms` | B9, B19, B13 | N (`asyncio.wait_for` inside the service so the timeout surfaces as `onError`) | `invoke: {..., "timeout_ms": N, "onTimeout": {...}}` | Y (grouped with LC-29)  **NOT-FIXED** — no per-invoke timeout; `spawnBlockingTimeout` covers only blocking spawn | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-31** | 01 §13.4 | No actor-logic constructors (`fromPromise`/`fromCallback`/`fromObservable`/`fromTransition`) and no `onSnapshot` | Missing feature | Medium | Services are plain callables; a callback-style long-running service that emits multiple events has no first-class form — you must capture `interpreter` and call `send` | B13 (WS stream as an actor), B12, B19 | N | Add the v5 actor-logic constructors, or document the "capture the interpreter" pattern as the supported idiom | Y (grouped with LC-29)  **NOT-FIXED** — no `fromPromise`/`fromCallback` actor-logic constructors | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-32** | CR-10 | Terminal machines are not reaped — `done` interpreters retain context, queue and registry entry | Improvement | Medium | Probe `adv04`: on reaching a final state `status='done'`, `is_running=False`, but the object and its registry entry persist until *we* call `stop()` and evict. `adv03`: **8.8 MB retained after full teardown + gc of a 2,854-interpreter fleet** (~3.1 KB each) — allocator arena retention, not a reference leak (confirmed by `bench_i_retention.py`: 0 live `Interpreter` objects, empty `gc.garbage`) | B1, B2, B3, B4, B5, B6, B7, B10 (high-churn families) | N (MUST-11: supervisor reaper + `cv_machine_live_count` alert on monotonic growth) | Auto-release actor/system registry entries and clear the queue when a machine reaches a final state | **Y**  **FIXED-DEFAULT** — terminal machines reap children, tasks and registry entries (#57) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-33** | 04 §5 | Parent→child `sendTo` forwarding costs 75.7 µs/msg — 2.3× a direct transition | Performance | Low | `bench_e_actors.py`: spawn ~100–130 µs, teardown ~30 µs (both flat in child count, 0.11 KB/actor over 3,000 cycles — the best-behaved subsystem measured); forwarding 75.7 µs vs a 33 µs direct transition | B2, B3 | N (fan out to children directly) | Short-circuit the system-registry lookup when the target actor object is already known | N (perf nit, group E)  Not re-tested — Low perf nit | Not re-tested — unchanged | Not re-tested — unchanged |

---

## D. Validation & strictness

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-34** | LC-13, C12, §2.11 | No strict mode: event names and payloads are unvalidated; a typo'd event is a silent no-op | Missing feature | High | Probe C12: `send("E", qty="not-a-number")` accepted silently. No `strict` option anywhere in the source. Probe A14: unknown events are ignored, not errors. `adv07`: sending `EE` instead of `E` left the machine unchanged with 2 log lines indistinguishable from a normal unhandled-event log | all (B1–B20) | N (`MachineGateway` + closed `StrEnum` per family + pydantic validation, lint-enforced) | A `strict=True` machine option that raises on an event type absent from the machine's descriptor set, and on unknown targets (LC-08) | **Y**  **FIXED-OPT-IN** — `strict` + `event_schemas` (#51). `send_threadsafe()` bypasses both (N-4); internal `raise` typos invisible under `"continue"` (N-11) | **FIXED** — `send_threadsafe()` now runs `_check_strict` on the calling thread; static `raise` targets validated at build time with a Did-you-mean. `strict` itself remains FIXED-OPT-IN by design. **close #51** (+M-6, F-8 ride along) | FIXED — unchanged, and **improved**: `done.review`/`DONE.review`/`error.validation` now rejected by `strict` (#79). **G-7 residual:** `strict` still exempts by name via `ENGINE_EVENT_SHAPES` (`after.party`, `xstate.whatever`, `done.invoke.NEVER_INVOKED`). **confirm #51 closed**, G-7 filed separately |
| **LC-35** | LC-13, 01 §13.1 | No typed context or events — `TContext` is bound to `Dict[str, Any]` | Missing feature | Medium | 01 §5, §13.1. No `setup({types})` equivalent, no typestate, no TypedDict/dataclass/pydantic support. 24 §1.1 mandates pydantic models on every boundary | all | N | A `setup({types})` analogue accepting TypedDict/pydantic models | Y (grouped with LC-34)  **PARTIAL** — `event_schemas` gives payload validation; no typed context. `TEvent` removal is a runtime break (N-7) | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-36** | 05 §method note | Built-in action params must be nested under `"params"`; the wrong spelling parses fine and does nothing | Docs / Validation | High | `{"type":"raise","event":"X"}` (the obvious spelling) parses without error and is a **no-op**; the correct form is `{"type":"raise","params":{"event":"X"}}`. Cost this study a false negative before correction. Same silent-failure class as LC-07/LC-08 | B2 (`EVALUATE` raise), B1, B9 | N (linter check) | Validate built-in action params at `create_machine()` — a built-in action creator with no recognised params is a config error, not a no-op | **Y**  **FIXED-DEFAULT** — built-in action param validation at build time, with a hint (#32) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-37** | 01 §14.7 | `MachineLogic` subclass auto-registration classifies callables **by arity** and silently misclassifies | Bug | Medium | `machine_logic.py:186-255` — 2 params → guard, 3 → service, 4 → action. An action helper taking 3 args silently becomes a "service"; `*args` or default params shift arity | all (any machine using `MachineLogic` subclassing rather than explicit dicts) | N (use explicit `MachineLogic(actions=…, guards=…)` dicts only; lint the subclass form out) | Require explicit `@action`/`@guard`/`@service` decorators for subclass registration; make bare-arity inference an opt-in fallback that warns | **Y**  **FIXED-DEFAULT** (decorated) / **PARTIAL** (undecorated arity fallback retained, now `UserWarning`) (#52) | **FIXED** — `MachineLogic(strict=True)` refuses undecorated public methods; decorated methods bind by decorator not arity; unclassifiable arity now warns. 10/10. **close #52** | unchanged |
| **LC-38** | LC-14, 04 §6, 01 §11 | `SyncInterpreter` is not single-threaded: `after` timers run on background threads and mutate context with no locks | Bug | High | Bench `bench_f_sync_vs_async.py` feature probe: a machine advanced `t.w → t.f` purely from a 200 ms `time.sleep()` on the main thread with no event pump ⇒ a background timer thread. `sync_interpreter.py:1323` — one daemon OS thread per timer; `grep` for `asyncio.Lock`/`threading.Lock` across the codebase → **none**. `_is_processing` is a plain check-then-set bool (`:337-340`) | none (MUSTNOT-06 bans `SyncInterpreter` outright) | N | Document the threading model explicitly, and either lock context/queue access or refuse `after` in sync machines. (Positive note: async services are rejected loudly and early with `NotSupportedError` — good design) | **Y**  **FIXED-DEFAULT** — no thread per timer (25 machines → +0 threads) (#50). **New defect N-2** — sync timers unreachable by `tick()` inside a running loop | **FIXED** — `Clock.set_timeout(sync=)`; the lane follows the owning engine, not ambient loop state. **close #50**. **New: F-2** on the legacy-clock shim | FIXED — unchanged. **confirm #50 closed**; F-2 filed separately |

---

## E. Concurrency & performance

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-39** | LC-15, 04 §2 | Throughput is a **fixed global budget**, not per machine | Performance | High | `bench_b2_scaling.py`: N=1 → 21,231 ev/s; N=10 → 20,305; N=100 → 20,063; N=500 → 19,323; N=1,000 → **18,152 aggregate (18.2 each)**. One asyncio loop, one thread — concurrency is interleaving, not parallelism | B9, B14, B15 (hard no), and a shared ceiling over B1–B8 | N (R1/R2/R3 hosting rules; process split pre-designed in ADR-0004) | No realistic library fix — this is asyncio. But the **docs must state it plainly**; a reader could reasonably assume N interpreters scale | **Y** (docs)  **FIXED-DEFAULT** (docs) — production-characteristics page ships (#53). Budget is still per-process by design | FIXED-DEFAULT — unchanged; BENCH-2 still missed, MUST-05 stands | unchanged |
| **LC-40** | CR-4 | Realistic machine throughput is 8.8k ev/s, not ~20k — the rule pre-filter must reach ≥99 %, not 90 % | Performance | High | Probe `adv05`, 1,000 rule machines / 30,000 events: **8,813 ev/s aggregate**. Required machine-ev/s at pre-filter hit-rates 100 %/10 %/5 %/1 % → 200,000 FAIL / 20,000 FAIL / 10,000 FAIL / 2,000 OK. Plain Python does the *entire unfiltered* 200,000 evals in **30 ms = 6.5 M eval/s, ~744×** | B9 (dispatch), and the shared budget over B1–B8 | N (MUST-05: ≥99 % rejection asserted as a test; below that, disable dispatch and alert) | None library-side — this reprices `10`'s margin, not the design. `10` B9's "Not suitable for per-tick evaluation" verdict stands; its "pre-filtering makes the budget comfortable" claim does not | N  **IMPROVED, still binding** — 30,662 → 34,467 ev/s; BENCH-2 still missed (380.9 vs ≥2000). MUST-05 pre-filter stands | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-41** | LC-20, 01 §11 | Unbounded interpreter queue with no backpressure signal and no queue-depth API | Missing feature | High | Single unbounded `asyncio.Queue`, single consumer (`interpreter.py:406-529`). Budget 1: 65 ms p50 / 95 ms p95 queueing with 500 busy machines; ~2.2 s under saturation. Depth is not observable through any public API | B1, B2, B9, B13 | N (bounded queue in front of the gateway + our own `cv_machine_queue_depth`) | Expose `qsize()`/a `queue_depth` property, and support an optional bounded queue with an overflow policy | **Y** (grouped with LC-42)  **FIXED-DEFAULT** (`queue_depth`) / **FIXED-OPT-IN** (`max_queue_size` + `OverflowPolicy`) (#38). 13/13 adversarial | FIXED-DEFAULT — unchanged | unchanged |
| **LC-42** | LC-09, CR-5 | `send()` is fire-and-forget with unbounded queueing latency — a statechart cannot answer synchronously | Missing feature | High | `send()` is `await queue.put(...)`; the caller cannot await the resulting transition (01 §11). `adv02`: kill-switch decision at a 2,854-interpreter fleet — **33.5 ms p50 / 50.8 ms max**. `adv04` governor: statechart RESERVE `p50=35.20ms p95=44.03ms max=53.18ms` vs a plain token bucket at **0.148 µs — ~238,264× slower** | B18 (kill switch), B20 (risk lockout), B17, and the *absent* fan-out rate governor | N (MUSTNOT-02/05: statecharts record and orchestrate; a synchronous flag enforces) | An awaitable `send()` returning a future resolved after the event is processed (XState's `actor.send` is sync-and-immediate; this one is neither), and/or a priority send that jumps the queue | **Y**  **FIXED-DEFAULT** — `send(wait=)`/`send(priority=)`/`Receipt` (#39). **New defect N-1** — hangs forever on a reused `Event` instance | **FIXED** — receipts no longer keyed on `id()`; held at 500-way concurrency under three policies. **close #39/#75**. **CV-C06's fresh-`Event` clause RETIRES** | FIXED — unchanged; re-confirmed at 500-way concurrency, **undisturbed by #43's redesign**. **confirm #39/#75 closed** |
| **LC-43** | LC-18, g6 | Cross-thread `send()` silently loses events | Bug | High | Bench `g6`: a bare `interp.send(...)` from a foreign thread returns a coroutine that is **never awaited** — no exception, event lost. `run_coroutine_threadsafe` works (500/500 delivered) at 336 µs/event — 10× the 33 µs in-loop cost. 20 §4.1 permits `run_in_executor` for DuckDB/Parquet/Argon2/crypto | B11, B12, B16, B13 | N (`SafeInterpreter.send_threadsafe()`; lint bans bare `.send(`) | Detect the foreign-thread case and either raise or dispatch via `call_soon_threadsafe`. Returning an un-awaited coroutine with no warning is the worst of the three options | **Y**  **PARTIAL** — bare cross-thread `send()` now raises `WrongThreadError` (#37), but `run_coroutine_threadsafe(send(...))` regressed (N-6) and `send_threadsafe()` lacks the guardrail (N-4) | **FIXED** — `WrongThreadError` message corrected and the 0.8.0 break documented. **close #37**. Repro script is stale (measures delivery from a worker that now correctly crashes) | FIXED — unchanged. **confirm #37 closed** |
| **LC-44** | LC-23, 04 §1 | The "pure" API is 2.4× slower than the interpreter **and does not run imperative actions** | Bug | Medium | `bench_a`: 77.2 µs vs 33 µs. After `SUBMIT` the state advanced while `context["qty"]` stayed `0.0` — verified directly. It is advertised as the no-overhead path and is a pessimisation; worse, unit tests written against it silently test transitions **without effects** | C5.1 (the unit-test strategy for all of B1–B20) | N (use it only for transition-table tests; say so in the test module docstring) | Document that it executes only declarative `assign`, and investigate the 2.4× overhead — it should be the fast path | **Y**  **FIXED-DEFAULT** — pure API ~3x faster, 39,036 ev/s (#54). "Skips imperative actions" was never in scope — documented design | FIXED-DEFAULT — unchanged | unchanged |
| **LC-45** | 01 §12, §10 | Hot-path allocation and INFO-level logging on every transition, guard and state entry | Performance | Medium | `_select_transitions` builds a fresh `leaves` list + per-leaf `eligible` list + `guard_cache` dict **per event**, nothing precomputed (`base_interpreter.py:2562-2599`); `_matching_descriptors` iterates all `on` keys on every ancestor walk with no descriptor index (`:2408-2418`); `_is_descendant` does string-prefix comparison on ids in a loop (`:2751-2771`). Guard evaluation logs at INFO per guard (`:2927-2931`); sync engine logs INFO per event (`sync_interpreter.py:365`) and per entry/exit (`:643`, `:747`) | B1–B9 (the shared ~20k ev/s budget) | N (disable the `xstate_statemachine` logger explicitly in production) | Precompile a descriptor index per state; demote transition/guard/entry logging to DEBUG; use the cached int `depth` instead of string prefixing in `_is_descendant` | **Y**  **FIXED-DEFAULT** — INFO→DEBUG on the hot path, precompiled descriptor index (#55) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-46** | RF-5, adv08 | Querying an interpreter from a hot path is 12× a plain bool read | Performance | Low | `adv08`: `interp.matches('live')` = 0.746 µs → 3.58 % of one core at 48k deltas/s; plain bool flag = 0.060 µs. Affordable, but a pointless tax for a value that changes a few times an hour | B14 (book health), B17 (live gate) | N (MUSTNOT-03: the machine writes a plain bool on entry; hot paths read the bool) | None needed library-side — this is a usage rule, recorded so no one reaches for `matches()` in a loop | N  Not re-tested — Low; MUSTNOT-03 stands | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-47** | 01 §12/§14.8, RF-4 | Target resolution mutates `transition.target_str` on definition objects shared across interpreters | Code quality | Low | `base_interpreter.py:1195`, `sync_interpreter.py:1478` — an accidental memoisation cache on a `MachineNode` shared by every interpreter of that machine. **Refuted as a live risk** by `adv07`: 200 interpreters over one `MachineNode`, `E` sent to exactly 100 → 100/100 moved, 100/100 untouched, no cross-talk (the mutation is idempotent and the async engine serialises onto one loop). Would **not** hold for `SyncInterpreter` with threaded timers | none in practice (A8's 19×-cheaper shared-node mandate is safe) | N | Move the memoisation into a per-interpreter cache so the definition object stays immutable | **Y** (grouped, group H)  **FIXED-DEFAULT** — resolution no longer writes back to the shared `TransitionDefinition` (#59) | FIXED-DEFAULT — unchanged | unchanged |

---

## F. Observability & ergonomics

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-48** | CR-9, LC-01, LC-08 | No error-observability hooks: no `on_transition_failed`, no `on_guard_error`, no unhandled-event signal | Missing feature | High | `plugins.py:70-256` — `PluginBase` has `on_action_error` (added 0.6.0) but **no** `on_transition_failed`, **no** `on_guard_error`, and no unhandled-event hook. `on_transition` fires as a success even when actions raised (bench `g2`). `adv07`: a typo'd event name is indistinguishable from a legitimately unhandled one. Duck-typed `on_error`/`on_done` are looked up dynamically (`base_interpreter.py:2329-2332`, `:2356-2359`) but are **not declared on `PluginBase`** | all (B1–B20) | N (MUST-10: `cv_machine_unhandled_events_total{kind,event}` + CI failure on any gateway event absent from the machine's descriptor set) | Declare `on_transition_failed(failed_actions)`, `on_guard_error`, and `on_unhandled_event` on `PluginBase`; declare the duck-typed `on_error`/`on_done` too | **Y**  **FIXED-DEFAULT** — 5 error hooks, firing **under the 0.7.x defaults** (#33). `on_transition_failed` fires twice under `"continue"` (N-15) | FIXED-DEFAULT — unchanged | FIXED-DEFAULT — unchanged. **G-12 ride-along:** the provenance API (`is_system_event`, `system_event`, `Event.system`) is unexported and undocumented, so a plugin author has no supported way to ask 'did the engine mint this?' |
| **LC-49** | LC-22, 01 §13.7 | No hierarchical `state.value` — active states are a flat `Set[str]` of ids | Missing feature | Medium | `current_state_ids` is a flat set (`['o.life.b','o.prot.p']`, confirmed by `adv07`). XState consumers and the Stately visualiser expect `{parent:'child'}` | B1–B20 via the WS projection (ADR-0005, 24 §19.3) and any `@xstate/react` live overlay | N (a projector rebuilds `value` from the flat id set + the machine tree, §C4.2) | Add a `value` property producing the hierarchical form — it is a pure function of data the library already has, and it is what makes visualiser interop actually work | **Y**  **FIXED-DEFAULT** — `interpreter.value` in XState hierarchical form (#58) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-50** | CR-9 | The snapshot cannot answer "how did this order get here?" — no timestamp, event history, machine hash or pending queue | Improvement | Medium | `adv07` field inventory: keys are exactly `actors, configuration, context, error, history, output, state_ids, status, system`. A snapshot answers "where is it", never "how did it get here". At 3 a.m. an operator has a flat id set and log lines | B1, B2, B3, B19 (incident forensics) | N (our `machine_events` write-ahead log is the book of record, MUST-02) | Add `taken_at` and an optional bounded `recent_transitions` ring to the persisted snapshot | Y (grouped with LC-21)  **FIXED-DEFAULT** — envelope `taken_at`/`machine_id` plus the error hooks give the forensic trail (#45, #33) | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-51** | 01 §10 | `RestoredError` is not exported in `__init__.__all__` | Code quality | Low | `exceptions.py` defines it; `__init__.py:176-232` `__all__` omits it — and the publish workflow smoke-tests `len(x.__all__) == 48`, pinning the omission | B1–B8 (restore error handling) | N | Export it | Y (grouped, group H)  **FIXED-DEFAULT** — `RestoredError` and 9 new exceptions exported in `__all__` | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-52** | 01 §14.16 | `error.platform.*` events carry an exception instance inside a `DoneEvent` | Improvement | Low | `interpreter.py:1121-1125`. Naming a failure a `DoneEvent` is misleading and forces consumers to branch on `type`. (Probe B2 confirms the payload itself is correct: `type(e.data).__name__ == "RuntimeError"`) | B1, B2, B13, B19 | N | Introduce an `ErrorEvent` type, or rename the field | Y (grouped, group H)  **NOT-FIXED** — `error.platform.*` is still delivered as a `DoneEvent`; dropped from #60 grouped scope | **NOT-FIXED** — no `ErrorEvent`; `error.platform.*` still a `DoneEvent`. Visibly deferred (absent from the itemised `[Unreleased]` list). **keep #80 open**, criteria apply verbatim | **FIXED** — `ErrorEvent(type, error, src)` landed (#80); 8/8 criteria incl. sync parity. **confirm #80 closed.** Four defects around the new type filed separately: G-3, G-4, G-5, G-6 |

---

## G. Docs

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-53** | LC-05, LC-14, LC-15 | Three production-critical characteristics are undocumented: timer starvation, the `SyncInterpreter` threading model, and the global throughput budget | Docs | High | None of the three appears in `docs/_guide/` (`delayed-transitions.md`, `interpreters.md`, `services.md` checked). Measured: +2,250 ms timer error at 500 machines (`bench_c`); a `SyncInterpreter` advancing with no event pump (`bench_f`); 18,152 ev/s aggregate at N=1,000 (`bench_b2`) | all | N | Add a "production characteristics" page covering all three with the measured numbers | **Y**  **FIXED-DEFAULT** — Production Characteristics guide page + reproducible benchmark (#56) | FIXED-DEFAULT — unchanged; docs grew further this window | unchanged |
| **LC-54** | LC-23 | The pure API's "does not execute imperative actions" limitation is undocumented | Docs | Medium | `docs/_guide/testing-and-pure-api.md` documents `PureSnapshot` and the API surface but never states that only declarative `assign` runs. Bench `bench_a`: `context["qty"]` stayed `0.0` while the state advanced | C5.1 test strategy for all families | N | State it in `testing-and-pure-api.md`, prominently — a test suite written against it can look thorough and verify nothing | Y (grouped with LC-44)  **FIXED-DEFAULT** — the pure API's action limitation is now documented (#54) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-55** | 03 §3.1 | Docs disagree on whether a live interpreter's `status` can be `'error'` | Docs | Low | `snapshots.md` says `status` is `"running"`/`"stopped"` etc.; `testing-and-pure-api.md` documents `PureSnapshot.status` as `'running'`/`'done'`/`'error'`; the FAQ says action failures are "logged and contained". Probe B3 confirms the **live** interpreter does reach `status == "error"` on an unhandled invoke error — so `snapshots.md`/`interpreters.md` are simply incomplete | B1, B13, B19 | N | List `'error'` as a possible `status` in `snapshots.md` and `interpreters.md` | Y (grouped with LC-53)  **FIXED-DEFAULT** — grouped under #56 | FIXED-DEFAULT — unchanged | unchanged |
| **LC-56** | 03 §2, 06 §5 | The docs-site comparison table is stale, and the Jekyll docs build is untested in CI | Docs | Low | The site's "How It Compares" table marks `python-statemachine` ❌ for hierarchical/parallel; that library **does** support compound states and parallel regions (06 §2). `ci.yml` has lint/test/coverage/build jobs only — no docs-build job; `tests/test_docs_site.py` regex-extracts `<pre><code>` from the **committed** `index.html` rather than rendering Jekyll from source, so a broken build is not caught | — | N | Correct the comparison table; add a Jekyll build job to CI | Y (grouped with LC-53)  **FIXED-DEFAULT** (docs) — but 3 version-badge tests were deleted with no successor (N-13) | FIXED-DEFAULT — unchanged | unchanged |

---

## H. Code quality

| ID | Old ID | Title | Type | Sev | Evidence | Affected machines | Blocks? | Proposed fix | Upstream  0.8.0 status | main@5327ba6 status | main@3c527b0 status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LC-57** | 01 §14.2, §14.3 | The two engines duplicate rather than share the core algorithm | Code quality | Medium | `Interpreter` and `SyncInterpreter` each reimplement target resolution (`base_interpreter.py:1164` vs `sync_interpreter.py:1431`), transition execution (`:1732` vs `:456`), entry/exit (`:1896`/`:2108` vs `:614`/`:724`) and built-in action dispatch (`:695` vs `:901`). The "mode-agnostic" base's `_process_event`/`_execute_transition` are `async def` and are **unused** by the sync engine, which overrides them with differently-named sync versions — the Template Method pattern is broken in practice. `test_engine_conformance.py` exists precisely because the two silently diverged in six release-blocking ways | — (root cause of LC-12, and of future divergences) | N | Extract the algorithm into a sans-io core parameterised over an execution strategy, so a fix lands once | **Y** (umbrella issue for group H)  **FIXED-DEFAULT** for the checkable criterion — one core algorithm on `BaseInterpreter` (#60). Delivered by a different design than the sketch; LC-52 did not ship | **PARTIAL** — the shared-algorithm half holds; the LC-52 `ErrorEvent` sub-claim did not ship. **keep #60 open**, or close and let #80 carry it | **FIXED behaviourally** — the shared-algorithm half held and the LC-52 `ErrorEvent` sub-claim landed here. The gate's residual is the *architectural framing* (`core/algorithm.py` + `ExecutionStrategy`), never the implementation path taken — not a criterion. **confirm #60 closed**; G-8 (sync child-machine failure parity) filed separately |
| **LC-58** | 01 §14.13 | `SyncInterpreter._is_async_callable` checks `__code__.co_flags & 0x80` | Code quality | Low | `sync_interpreter.py:1532-1548` — misses `functools.partial`, objects with an async `__call__`, and async generators, so `NotSupportedError` is not raised where it should be | — (sync engine banned) | N | Use `inspect.iscoroutinefunction` plus an `unwrap`/`partial` walk | Y (grouped with LC-57)  **FIXED-DEFAULT** — sync engine raises `NotSupportedError` for `partial`-wrapped async actions (#60) | FIXED-DEFAULT — unchanged | unchanged |
| **LC-59** | 01 §14.1 | Unreachable code after `return`, and a misindented comment block inside a method body | Code quality | Low | `models.py:414-423` (`logger.debug` after `return`); same pattern at `models.py:1032-1034` | — | N | Delete | Y (grouped with LC-57)  **FIXED-DEFAULT** — grouped under #60 | FIXED-DEFAULT — unchanged | unchanged |
| **LC-60** | 01 §14.12 | Polling instead of futures throughout: actor completion 5 ms, `wait_for` 5 ms, sync actor runner 10 ms | Code quality | Low | `interpreter.py:81`/`:1214-1215`, `helpers.py`, `sync_interpreter.py`. No condition variables or futures anywhere | B2, B3 (see LC-28 for the measured cost) | N | Replace with `asyncio.Event`/futures | Y (grouped with LC-28)  **PARTIAL** — actor completion is future-based (#43); still 2 tasks per child | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-61** | 02 | No mypy gate despite the `Typed` classifier; flake8 complexity limit 35; coverage gaps concentrated in rollback/cancellation | Code quality | Low | `ci.yml` lint job is `black --check` + `flake8` on py3.13 only — no mypy. `--cov-fail-under=86`; `base_interpreter.py` at **86 %** with misses concentrated in error/rollback/cancellation branches — exactly the paths CandleViewer leans on hardest. Full suite takes ~9.5 min locally (2805 passed, 2 skipped) | — | N | Add a mypy job; ratchet `base_interpreter.py` coverage on the rollback/cancellation branches specifically | Y (grouped with LC-57)  **PARTIAL** — changelog claims mypy at zero errors; **unverified** (mypy absent from the gate venv). No `fail_under` coverage floor (N-13) | Not re-tested — unchanged | Not re-tested — unchanged |
| **LC-62** | LC-24, 06 §3/§4 | Project maturity: single maintainer, no independent production adoption, rapid API churn | Improvement (ecosystem) | Medium | 14 stars, 1 fork, **exactly one issue ever filed** (#17, closed, camelCase↔snake_case mapping — the very seam CandleViewer would use), ~11 releases in under a year (0.2.1 → 0.7.x). 2,805 tests at 87 % coverage, but both 0.6.0 and 0.7.0 disclose CRITICAL silent-wrongness defects that survived thousands of passing tests. **Downgraded from `10` LC-24's framing** (per RF-6): 12,104 LOC, zero runtime deps, MIT, and the owner *is* the maintainer ⇒ vendorable; the risk is a *testing* obligation, not an availability risk | all | N (MUST-07 exact pin `== 0.7.0` + sha256; MUST-08 vendor into `third_party/`; `tests/xstate_contract/` as the bump gate) | Not a code fix. File every row of this register upstream; keep the contract suite under 60 s so it actually gates bumps | N  **IMPROVED, unchanged in kind** — 2805 → 3170 tests, +13,115 lines of test code; still a single maintainer, still no independent production adoption. MUST-08 (vendoring) stands | Not re-tested — unchanged | Not re-tested — unchanged |

---

## Adoption gate summary

These are the **Blocker** and **High** items that must be closed — by an upstream fix, or by a *mechanically enforced* CandleViewer mitigation with a regression test in `tests/xstate_contract/` — before CandleViewer adopts `xstate-statemachine` on any live-trading path.

### Blockers (7) — no live use until closed

| ID | Title | Closing mechanism |
|---|---|---|
| **LC-01** | Action raises → transition commits, no error channel | Upstream `action_error_policy`, **or** `@cv_action` wrapper + `FAULT`→`quarantined` + ERROR-log→P1 + independent reconciliation (4 layers, none sufficient alone). Test: `test_failed_action_is_not_persisted` | **FIXED-OPT-IN** — unchanged. Rollback now also **withdraws self-`raise`d events** (#27), verified in 8 hostile shapes; idle no-action checkpoint skip reproduced at 0.998–1.056x. Still not an effect transaction (`sendTo` survives). **close #27** |
| **LC-02** | `always` self-target deadlocks silently | Upstream external-self-target semantics, **or** linter rule banning self-targets + `reenter:true` mandate. Test: `test_reenter_semantics` | FIXED-DEFAULT — unchanged, no regression |
| **LC-03** | Unhandled events silently discarded | Upstream `on_unhandled:"defer"`, **or** `"*": defer` on every transient state + `drain_deferred` in every `entry`, linter-enforced. Test: INV-5 per family | **FIXED-OPT-IN** — unchanged. **New: M-1** — a deferred event's `wait=True` receipt reports `changed=False, error=None`. See CV-C06's new `deferred_count` clause |
| **LC-15** | A failed action's state is durably persisted as truth | MUST-01: snapshot writer refuses any `_fault` context, writes `quarantined`, alerts P1. Test: `test_failed_action_is_not_persisted` | FIXED-OPT-IN — unchanged (rides on LC-01/#27) |
| **LC-16** | `sendTo` cannot address actors by `id`/`systemId`; ambiguity drops events | Upstream id-in-actor-id fix, **or** application-owned `dict[leg_id → Interpreter]` with restore-time rehydration (verified working) | FIXED-DEFAULT — unchanged |
| **LC-17** | Persisted deferral buffer never drained after a crash | MUST-03 boot step 3b (drain before re-driving invokes) + MUST-04 alert on `_deferred` > 5 s. Test: `test_deferred_survives_crash_and_drains_at_boot` | FIXED-OPT-IN — unchanged (rides on LC-03/#28) |
| — | **Prerequisite for all of the above:** the machine-definition linter (E29-T10) and `tests/xstate_contract/` must **ship before the first statechart** (MUST-09). Every Blocker mitigation fails silently if a developer forgets it; an unenforced rule is not a rule | E29-T10 + C5.4 |

### High (19) — must have a documented, tested mitigation before adoption

`LC-04` self-transition non-reentry · `LC-05` `raise` outside the macrostep · `LC-06` over-forgiving target resolution · `LC-07` `.child` targets silent no-op · `LC-08` unknown targets unvalidated · `LC-09` raising guard swallowed as `False` · `LC-11` entry action raising at `start()` · `LC-18` ordering destroyed across defer/drain · `LC-19` restore does not restart invokes · `LC-20` restore does not resume timers · `LC-21` no snapshot schema version · `LC-22` context assigned wholesale, defaults not merged · `LC-24` queued events lost on crash · `LC-26` timer starvation under load · `LC-27` no clock injection / virtual time · `LC-34` no strict mode / no payload validation · `LC-36` built-in action params silently ignored when misspelled · `LC-38` `SyncInterpreter` unlocked cross-thread context mutation · `LC-39` throughput is a fixed global budget · `LC-40` realistic throughput 8.8k ev/s ⇒ pre-filter ≥99 % · `LC-41` unbounded queue, no backpressure · `LC-42` `send()` cannot answer synchronously · `LC-43` cross-thread `send()` loses events · `LC-48` no error-observability hooks · `LC-53` three undocumented production characteristics.

### Standing verdict

The library is **correct where correctness is hardest** — invoke cancellation (probe B4/B5), parallel/nested snapshot fidelity (C4), FIFO ordering (`g7`), history semantics (B12–B14), determinism across 15 runs (C8/C9/C17), actor teardown (0.11 KB/actor over 3,000 cycles) — and **wrong where wrongness is quietest**. Every Blocker above is an instance of one design philosophy: *resolution and execution failures degrade to silent no-ops rather than errors.* `LC-01`, `LC-02`, `LC-03`, `LC-07`, `LC-08` and `LC-36` are all the same bug wearing different clothes.

If upstream closes **LC-01, LC-03 and LC-02** (issues 1–3 in `10` D2), three of the four highest-severity mitigations disappear and this becomes a straightforward Good-to-Excellent fit across B1–B13 and B16–B20.

---

## 0.8.0 status roll-up (2026-09-17)

The prediction in the paragraph above was tested and largely held: upstream
closed LC-01, LC-02 **and** LC-03, plus 31 more rows. Recording what that
actually bought, honestly.

### Counts against the 34 individually-filed issues

| Class | Count |
|---|---:|
| FIXED-DEFAULT | **23** |
| FIXED-OPT-IN | **6** (LC-01, LC-03, LC-09, LC-19, LC-34, LC-41) |
| PARTIAL | **5** (LC-07, LC-28, LC-37, LC-38, LC-43) |
| NOT-FIXED | **0** |

Across the full 62-row register, the rows still genuinely open are **LC-20**
(`after` timers not resumed on restore), **LC-30** (no per-invoke timeout),
**LC-31** (no actor-logic constructors) and **LC-52** (`error.platform.*` is
still a `DoneEvent`).

### Blockers (7) — all closed, two conditionally

| ID | 0.8.0 | Condition |
|---|---|---|
| LC-01 | FIXED-OPT-IN | **Only closed while `actionErrorPolicy: "rollback"/"fail"` is set on every machine and enforced by CV-LINT-XS1.** |
| LC-02 | FIXED-DEFAULT | — |
| LC-03 | FIXED-OPT-IN | **Only closed while `onUnhandled: "defer"/"error"` is set on every machine and enforced by CV-LINT-XS2.** |
| LC-15 | closed via LC-01 | MUST-01 retained as defence in depth |
| LC-16 | FIXED-DEFAULT | — |
| LC-17 | closed via LC-03 | MUST-03/04 re-expressed against `deferred_count` |
| Linter prerequisite (MUST-09) | **NOT MET** | `E29-T10` and `tests/xstate_contract/` have not shipped. This is now the single gating condition. |

### The honest read

Two of the four filed Blockers are closed **by a policy whose default is still
the 0.7.x behaviour**. That is a real fix — both were verified end to end, and
`defer` survived 9/9 hostile probes — but it means the Blocker is closed *for a
caller who sets the option* and open for one who does not. Since every Blocker in
this register is a **silent** failure, and an unenforced rule is not a rule
(MUST-09), the register's own standard requires the mandate to be mechanical
before these count as closed.

The 0.8.0 review also found **17 new defects** (N-1…N-17: 2 High, 9 Medium,
6 Low, 0 Blocker), five of which are drafted as new upstream issues with runnable
repros in `issues/new-0.8.0/`. The two High ones both sit inside features this
release added: `send(wait=True)` hangs forever on a reused `Event` instance
(N-1), and `SyncInterpreter` `after` deadlines become unreachable by `tick()`
inside a running loop (N-2).

> **Register verdict on 0.8.0: ADOPT WITH CONSTRAINTS (CV-C01…CV-C15),
> conditional on the `E29-T10` linter and `tests/xstate_contract/` being green;
> DEFER on the order path until then. Non-order paths may proceed now.**
> Full reasoning, the decision-table walk and the mandatory machine
> configuration: `17-reeval-0.8.0-verdict.md`.

## Round 14 — v0.9.1 (`45bb7f3`), 2026-09-24

| ID | Class | Severity | Status |
|---|---|---|---|
| R14-01 | LIBRARY-DEFECT | Medium (downgraded from High on refutation) | OPEN upstream (draft filed). Mitigated by `CV-C68`. |
| R14-02 | DESIGN-CONSTRAINT | Low | The drained receipt error is `InterpreterStoppedError`. Wrapper handles it (`CV-C65′`). |
| R14-03 | OUR-CONTRACT-DEFECT | Blocker (ours) | Fixes for B16/B18/B11 proven on 0.9.1; merge pending in 28. |
| B610-OC-CD03 | OUR-CONTRACT-DEFECT | High (ours) | B8 needs a bounded attempt counter. |
| R14-04 | NEEDS-WRAPPER | Info | Alert on `chain_trips > 0`. |
| R13-01..R13-08 (library) | — | — | **CLOSED** by #239–#248. |

> **Register verdict on 0.9.1: ADOPT WITH CONSTRAINTS (row 8).** See `79-r14-final-readiness-verdict.md`.
