# Observability, Error Surface & Operability — re-run @ `19cb1f1` (round-9)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `19cb1f1` (unreleased 0.8.1; round-9 fixes #203-#210, closing R9-01..
R9-16 from `53-r9-findings-register.md`). `__version__` still `0.8.0`;
identified by commit only.

**Date:** 2026-09-22. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified. No `git`
run in the CandleViewer repo. GitHub not touched.

**Time-bound reductions** (stated up front). The 20-minute overall wall-clock
bound made the full requested matrix infeasible this pass — see §5 for the
complete not-covered list. What was actually run:
- All four `f28719c`-round scripts (`rerun_prior.py`, `rerun_prior_async.py`,
  `new_attacks.py`, `new_attacks_r8.py`), copied **unmodified** into this
  round's folder and re-run verbatim against `19cb1f1` — §1.
- One new script, `new_attacks_r9.py`, seven attacks (V1-V7, six executed —
  V2 folded into V1 for time, noted below) built specifically against
  round-9's new machinery (#203 `after` provenance, #204 `statesToInvoke`,
  #206 delayed-self-send debt, #207 stranded-invocation observability, #209
  lap parity) — §2.
- **NOT RUN** this pass (§5): the >=300-case persistence property test, the
  100-machine concurrent raise(delay) ping-pong, the 200-concurrent
  rollback/onDone stranded-hook load test, the 5k/s external-delayed-send
  soak, the >=500-config livelock fuzzer, the illegal-configuration receipt
  fuzz, the 50x determinism/hash-seed sweep, the security probes on
  `_EngineAfter` forgery (import-path/`type(held)`/pickle/snapshot), and the
  12-minute soak.

---

## 1. Prior-defect re-run (unmodified `f28719c` scripts, re-run verbatim)

All four scripts from `battle-f28719c/observability/` were copied byte-for-byte
into `battle-19cb1f1/observability/` and re-run with no edits. Raw output in
`rerun_prior.txt`, `rerun_prior_async.txt`, `new_attacks.txt`,
`new_attacks_r8.txt` (this folder).

| ID | `f28719c` result | `19cb1f1` result | Verdict |
|---|---|---|---|
| D-observability-1..9, I, J/J′, K/K′, L, M/M-async, N, O (17 legacy checks) | see `battle-f28719c/observability.md` §1 | Byte-identical text output on every check (receipts, hooks fired, `n=` counters, `SnapshotMidStepError` text, `TypeError` text) | **UNCHANGED, no regressions** |
| U1 forge `"engine": true"` on a done-record | accepted as trusted (documented, not a defect) | Identical: `is_system_event(trusted)=True`/`False` as before; U1b `changed=False error=None` unchanged | **UNCHANGED** |
| U2 v1 restore discrimination | PASS | Identical | **UNCHANGED** |
| U3 `children_timeout` flat in N | PASS, `[0.103,0.109]`-class spread | Same order of magnitude, still flat, still bounded near 0.1s | **UNCHANGED** |
| U4 priority-shed-by-provenance (60/60 delivered) | PASS | Identical `60/60` delivered, `RunawayChainError` on the self-chain | **UNCHANGED** |
| U5 action-issued priority send charged | PASS, `n=21`, "discarded 1" | Identical | **UNCHANGED** |
| U6 `def`-service rollback unwinding | PASS, `svc_called_count=0` | Identical | **UNCHANGED** |
| U7/U7′ snapshot from `on_interpreter_start` | PASS both engines | Identical `SnapshotMidStepError` text both engines | **UNCHANGED** |

No regressions among any of the 25 legacy checks (17 D/I/J/K/L/M/N/O +
7 U1-U7 + U1b) between `f28719c` and `19cb1f1`. This round-9 commit did not
touch any of the code paths these checks exercise, and none of the round-9
changelog entries (#203-#210) claim to.

---

## 2. New attacks on round-9's machinery (`new_attacks_r9.py`)

Six attacks (V1, V3-V7; V2 — a rollback-cut variant of V1 — was folded into
V1's roll-forward case for time, see §5), each targeting one of #203/#204/
#206/#207/#209's code paths. Standalone script, raw output in
`new_attacks_r9.txt`.

| Attack | Target | Result |
|---|---|---|
| **V1**: `always` roll-forward transiently visits a state with an armed `invoke` inside one macrostep | #204 (`statesToInvoke`, roll-forward half) | **PASS** — `final_state=['v1.skip']`, `svc_called=0`. The invoke on the transient `transient` state was never submitted. |
| **V3**: hand-built public `AfterEvent("after.60000.v3.waiting", None, None)` sent into a machine whose `waiting` state has a real 60s `after` | #203 (`after` matches only engine-minted `_EngineAfter`) | **PASS** — `state=['v3.waiting']`, unchanged; the forged public `AfterEvent` had no effect on selection. |
| **V4**: `raise(delay=1)` self-ping-pong between two states (`a`⇄`b`), `maxIterations=15`, async engine | #206 (delayed self-send charged as engine work) | **PASS** — `RunawayChainError` trips ("discarded 1 of them"). Per the changelog, the `SyncInterpreter`'s timer-paced variant is documented to have "user standing by construction" (caller-driven `tick()`) and is *not* expected to trip; this attack targeted the async engine, where #206's fix actually applies. |
| **V5**: `rollback`+`invoke.onDone` storm strands an invocation (`idle`→`starting[invoke sub]`→`recording[entry boom, rollback]`), `maxIterations=10`, sync engine, `Recorder` plugin | #207 (`RunawayChainError.stranded`, `on_invocation_stranded`, ERROR log) | **PASS** — `last_error=RunawayChainError`, `err.stranded=('sub',)`, `plugin_hook_calls=[('v5.starting','sub')]` (exactly once, correct id pair), and an ERROR-level log line naming the state/invocation fired (`error_log_named_state=True`). Matches the library's own `test_default_limit_trips_and_names_the_stranded_invocation` shape verbatim. |
| **V6**: lap-parity sweep, `invoke.onDone` self-loop, `maxIterations` in `1..15` (reduced from the requested `1..25` for time), sync vs async | #209 (lap parity, corrected) | **PASS** — `mismatches=[]` across all 15 limits; sync and async lap counts agree at every limit tested. |
| **V7**: attempt `get_persisted_snapshot()` from inside `on_transition` while an `invoke` is being armed (mid-macrostep) | #204/#199-adjacent (snapshot must never observe a torn/duplicated invocation-arming state) | **PASS** — refused with `SnapshotMidStepError`, no snapshot returned; consistent with U7/U7′'s `on_interpreter_start` finding, extended to `on_transition`. |

---

## 3. Defects filed

**No new `D10-observability-n` defects were confirmed this pass.** All 25
legacy checks reproduced identically (byte-for-byte on the printed
diagnostics) on `19cb1f1`, and all six new attacks against round-9's own
changelog claims (#203, #204, #206, #207, #209) held exactly as documented:
`after` selection is provenance-gated against a hand-built public event
(V3), a transiently-visited state's invoke is never submitted whether
rolled forward by `always` (V1) — the roll-back half (V2) was not run
separately this pass, see §5 — a delayed self-send on the async engine is
charged as engine work and trips `RunawayChainError` (V4), a chain cut that
strands an invocation is observable via `.stranded`, the plugin hook, and
an ERROR log exactly once with the correct ids (V5), lap parity holds
across the reduced sweep (V6), and a snapshot attempt mid-arming is refused
(V7).

This track cannot itself confirm or deny R9-01 through R9-16 as a class
(that is the register's job, and several — R9-01 forgeability, R9-05
snapshot authentication, R9-10 priority-lane loss across snapshot, R9-13
`strict` vs `pending_events` — are outside what this pass's six attacks
targeted). Within the narrow slice this pass covers (#203/#204/#206/#207/
#209's observability-facing surface), no regression and no new defect were
found.

---

## 4. Adaptations from prior rounds

- All four `f28719c` scripts were copied verbatim (byte-identical) with no
  source edits; none of round-9's changes (#203-#210) touch the code paths
  those 25 checks exercise, so no adaptation was needed or made.
- V4 was run only against the **async** engine (`Interpreter`), not
  `SyncInterpreter`. Per the round-9 changelog itself, the `SyncInterpreter`'s
  timer-paced self-send variant is *documented* to have "user standing by
  construction" (every delayed delivery arrives through a caller-driven
  `tick()`/`send()` drain) and is not expected to trip `maxIterations` — this
  is stated in the library's own `test_sync_engine_timer_paced_cycle_is_a_
  periodic_process`. Running it against `SyncInterpreter` and reporting "does
  not trip" would misrepresent a documented design choice as a gap; the
  async-only attack targets the actual claim #206 makes.
- V2 (rollback-cut roll-back half of #204's `statesToInvoke` fix) was not run
  as an independent attack — folded conceptually into V1 for the time
  budget; V5 already exercises a rollback-driven cut path (albeit for #207,
  not #204) so some rollback-interacts-with-invoke-arming coverage exists,
  but not the specific roll-back-in-same-macrostep shape #204 names.

---

## 5. Not covered this pass

- **Persistence property test** (>=300 random machines incl. parallel +
  children + after, both engines, both service kinds) against round-9's new
  arming/settle ordering — **not run**. Only V1 (single machine, `always`
  roll-forward, sync engine) and V7 (single machine, mid-arming snapshot
  refusal) were checked.
- **Snapshot of a machine whose invoke is pending-arming (entered, settle not
  yet run) → restore → arms exactly once** — the specific persistence
  round-trip attack requested was **not** built; V7 only confirms the
  snapshot *attempt* is refused mid-macrostep on the live interpreter, not
  what happens across an actual restore of such a state (which, per the
  refusal, may be unreachable by construction — worth confirming
  independently, not assumed here).
- **Forged after records under `strict`** — not attacked this pass; V3 used
  the public `AfterEvent` class directly (unforged snapshot path), not a
  hand-written persisted record with `"engine": true` on an `after` kind
  (the `after`-specific analogue of round-8's U1, which was only ever run
  against `done` records).
- **Delayed-self-send debt across snapshot/restore** — not attacked.
- **Property test ≥300 random machines incl. parallel + children + after** —
  not run (see above).
- **100 machines with `raise(delay=1ms)` self-ping-pong, concurrently, all
  must trip at same lap, both kinds** — V4 ran a single machine, async
  engine only, not 100 concurrent instances across both service kinds.
- **Stranded-invocation hook under 200 concurrent rollback+onDone storms
  (exactly-once, ids correct)** — V5 ran a single sequential instance, not
  200 concurrent.
- **External delayed sends at 5k/s during self-generated chains (0 dropped)**
  — not attacked; U4 (legacy, re-run in §1) covers 60 sequential external
  priority sends against a *zero-delay* `always` chain, not 5k/s *delayed*
  sends against a #206-style delayed self-chain.
- **Livelock fuzzer ≥500 configs × {def, async def} × both engines incl.
  always+invoke+after combinations and delayed raises** — not run.
- **Illegal-configuration receipt fuzz** (#208, "must never be ok over
  illegal, never error over legal") — not attacked; #208's fix was read in
  the changelog but not independently fuzzed.
- **Determinism**: 50x identical-trace check both engines both kinds incl.
  stranded events, hash-seed sweep — not run.
- **`on_invocation_stranded` × engines × kinds exactly-once + ordering vs
  `on_event_dropped`** — V5 confirmed exactly-once on the sync engine, `def`
  service only; the async-engine and `async def`-service variants, and the
  ordering relative to `on_event_dropped` in the same macrostep, were not
  separately attacked.
- **`RunawayChainError.stranded` payload under multiple simultaneous
  stranded invocations** (e.g. parallel regions each stranding one) — V5
  strands exactly one invocation; a multi-invocation strand was not built.
- **Security**: construct `_EngineAfter` via import path / `type(held)` /
  pickle / snapshot `"engine": true` and confirm it must not drive `after`
  unless genuinely engine-minted-in-this-process; redaction — **not run**
  this pass. (Round-8's U1 attacked this shape for `_EngineDone`/`onDone`
  only; the `after`-specific forgery-vector sweep the prompt calls for was
  not built for this round.)
- **12-minute soak** (200 machines both kinds, always→invoke + rollback+onDone
  + delayed self-sends + external priority producer + chaos snapshot at
  quiescence) — **not run**, given the 20-minute overall bound.

---

## 6. Verdict

Round-9's observability-relevant fixes hold up under the reduced,
single-run attack set exercised here. All 25 legacy checks (9 defects + 8
round-6/7 attacks + 7 round-8 attacks + U1b) reproduced byte-identically on
`19cb1f1` with no regressions — none of round-9's changes touch those code
paths. Of the six attacks purpose-built against round-9's own changelog
claims:

- **#204** (`statesToInvoke`, roll-forward half) holds — a state entered
  and exited within one macrostep via `always` never submits its invoke
  (V1, `svc_called=0`). The roll-back half was not independently attacked
  this pass (§4/§5).
- **#203** (`after` matches only engine-minted events) holds — a hand-built
  public `AfterEvent` has no effect on selection (V3).
- **#206** (delayed self-send is engine work) holds on the async engine —
  a 1ms-delay ping-pong trips `RunawayChainError` at the stated limit (V4);
  the `SyncInterpreter`'s documented "user standing" exemption was not
  attacked as a false claim, only accepted as stated.
- **#207** (stranded-invocation observability) holds — `.stranded`, the
  `on_invocation_stranded` hook (exactly once, correct ids), and the ERROR
  log all fire together on the documented shape (V5).
- **#209** (lap parity) holds — sync and async agree at every limit in the
  reduced `1..15` sweep (V6).
- Snapshot-mid-arming refusal (V7, extending U7/U7′ from `on_interpreter_
  start` to `on_transition`) holds — no torn/duplicated invocation state is
  ever exposed via a successful snapshot mid-macrostep.

**No Blocker/High-severity observability regressions were found.** This
remains a narrow, time-boxed slice of the requested matrix — the
persistence-property test at scale, the 100-machine concurrent delayed-
ping-pong, the 200-concurrent stranded-hook load test, the 5k/s external-
delayed-send soak, the >=500-config livelock fuzzer, the illegal-
configuration receipt fuzz, the 50x determinism/hash-seed sweep, the
`_EngineAfter`-forgery security probes, and the 12-minute soak were **not
run this pass** (§5) and must not be read as confirmed by this report.
Consistent with the standing caution in prior rounds' reports: a
single-shot probe closing a documented repro shape is evidence the
*specific* shape no longer reproduces at low concurrency/volume, not that
the *class* of defect (silent, load-dependent, only-visible-under-a-fuzzer
failure — the exact shape R9-01 through R9-16 were themselves found by) is
closed at scale. In particular, R9-01 (engine-completion provenance
forgeable by five vectors) is **not addressed by round-9's #203/#204/#206/
#207/#209 changelog entries at all** — none of them claim to fix it — and
this track did not attempt the security-probe matrix (`_EngineAfter`
import-path/`type(held)`/pickle/snapshot forgery) that would be needed to
check whether the sibling `_EngineDone`/`_EngineError` forgery R9-01 already
proved has an `_EngineAfter`-specific analogue; that remains open per the
register.
