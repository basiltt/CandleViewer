# Battle-test track re-run: SEMANTICS — round 6, commit `cec108b`

**Build under test.** `_ref/xstate-statemachine` @ `main` = `cec108b`
("Merge pull request #164 from basiltt/fix/0.8.1-round5"), unreleased 0.8.1.
`__version__` still reports **`0.8.0`** — this build is identified **by
commit, never by version string**. `CHANGELOG.md` `[Unreleased] — targeting
0.8.1` (round-5 fixes #142–#162, reopened #118/#122/#125/#133/#134) was read
in full before any case was written.

**Date:** 2026-09-19. **Python:** CPython 3.13.x. **OS:** Windows 11 Pro
10.0.26200. **Interpreter for every run below:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was not consulted.

**Predecessor.** `battle-3ed3099/semantics.md` (prior attack suite N1–N6,
defects D5-semantics-1…4) and `33-r5-findings-register.md` (R5-01…R5-03).

**Standard applied.** Candidate to run an order-management system handling
real money. Every silent failure, nondeterminism or ordering ambiguity is a
defect, reproduced with a standalone script before it is counted.

---

## 0. Bottom line

**Prior suite re-run: 32/34 → 32/34, but the composition changed. New attack
suite: 32/33 PASS across 6 groups. 3 of 4 prior defects FIXED. 1 prior High
STILL-PRESENT. 1 new Medium.**

**Round 5 is the strongest round this track has measured.** Every headline
fix passes its own attack, including the three that were most likely to
regress something else: the `service_executor` move (#149) keeps #116's
ordering *and* the loop's liveness; the chain-budget rework (#150) is
charged and observable; the legality rule (#142/#143) accepts 300 random
parallel machines at 3,600 quiescent points without a single false refusal.

- **Prior defects.** **3 of 4 FIXED**, 1 **STILL-PRESENT**:
  - D5-semantics-3 (truncated `configuration` restores inert) — **FIXED**,
    now `SnapshotCorruptError`.
  - D5-semantics-4 (untyped `TypeError`/`AttributeError` from
    `from_snapshot`) — **FIXED**: 0/9 targeted poisons and **0/5000** fuzz
    mutations escape `XStateMachineError` (was 432/5000).
  - D5-semantics-2 (`SimulatedClock` ambient-loop dispatch) — **CHANGED /
    accepted**: still true, already reclassified as constraint DC-02 in the
    register, not re-counted here.
  - **D5-semantics-1 (High) — STILL-PRESENT.** See **D6-semantics-1**.
- **D6-semantics-1 (High, carried over).** `get_persisted_snapshot()` taken
  from inside an **entry action** is still **accepted** and persists a
  **torn** state — the new leaf with a half-applied context. #142 replaced
  the any-leaf test with per-region legality, which closes the *parallel*
  tear but not this one: in the entry-action window the configuration is
  perfectly legal (the new leaf is already active) while the macrostep is
  still open. Both engines. `repro/d6s1_entry_window_torn_snapshot.py`.
- **D6-semantics-2 (Medium, NEW).** On the **async engine only**,
  `await Interpreter.start()` returns **before** the initial state's
  `invoke` children are registered (~15 ms early on this box), so a `sendTo`
  addressed to a child in the first macrostep finds no live actor. The
  failure *is* reported (`on_event_dropped(reason="unresolved_target")` plus
  a soft step error) — so this is an **engine-parity and API-contract**
  defect, not a silent-loss one: `SyncInterpreter.start()` has the child
  addressable the instant it returns. `repro/d6s2_invoke_start_race.py`.
- **Everything else this round passes.** 7/7 concurrency (200 concurrent
  executor services with the loop staying lively; `stop()` mid-service;
  `internal=True` forgery charged *and* observable; `QueueOverflowError` at
  the `send_threadsafe()` call site under 16 threads; double-cancel `_die`;
  500 churn cycles leak nothing; an injected executor survives `stop()`).
  7/7 semantics (#152 fallback, #153 Receipt matrix, #147, #145 both
  engines, #156 anonymous `escalate`, #155 `spawn_*` namespace, #151
  per-macrostep budget). 5/5 determinism. 7/7 fuzz/observability/security.
- **The soak is clean** (see §5).

**Verdict: the semantics track does not block adoption.** One adoption
constraint carries forward unchanged (**CV-S07 — never snapshot from inside
an action**), and one new narrow constraint is added (**CV-S09 — on the
async engine, await child registration before addressing a child actor**).

---

## 1. Method and reductions

### 1.1 What was run

1. **Prior-suite re-run.** Every script under `battle-3ed3099/semantics/`
   (N1–N5, 34 attacks) re-run **unmodified** on `cec108b`, plus all four
   `repro/*.py` scripts. No script needed adapting for documented-superseded
   behaviour.
2. **New attack suite** under `battle-cec108b/semantics/`, six groups
   (N1–N6, 33 attacks + soak), aimed at this round's fixes.

### 1.2 Reductions against the brief (stated explicitly)

| Brief asked | Run as | Why |
|---|---|---|
| soak **12 min**, 200 machines | **5 min** (`SOAK_SECONDS=300`), 200 machines | Whole-task budget is 20 min wall clock and the prior re-run plus six new groups consumed most of it. Parameterised: `SOAK_SECONDS=720 python n6_soak.py` restores the brief's figure unchanged. |
| config livelock fuzzer, 30 s watchdog | 120 machines, **8 s per-machine** watchdog | A per-machine bound is strictly tighter than one 30 s bound on the group and keeps the script inside the 120 s cap. |
| ≥300 parallel machines, hypothesis property | **300 machines × 12 quiescent snapshots = 3,600 snapshot round-trips**, seeded `random` rather than `hypothesis` | Same coverage shape, deterministic and re-runnable from the recorded seed (`random.Random(20260919)`). |
| *(all other items)* | **as specified, no reduction** | 5,000 fuzz mutations, 50× traces on both engines, 5 hash seeds, 200 concurrent services, 16 RAISE threads, 500 churn cycles all ran at full size. |

Every script completes inside the 120 s bound except the soak, which is
bounded by its own `SOAK_SECONDS`.

### 1.3 Honesty note — ten of my own harness bugs

Round 6 cost me more harness bugs than any prior round, because this round's
API is *stricter*. I record them because in almost every case the library's
own diagnostics or docstrings are what caught me, and because three of them
initially looked like library defects:

1. `from_snapshot(machine, blob, logic=...)` — the real signature is
   `from_snapshot(snapshot_str, machine, *, ...)`. My call raised `TypeError`
   before reaching any library logic.
2. **Snapshot round-trip "drift"** that was just the wall-clock `taken_at`
   stamp differing between two snapshots — and, once fixed at the top level,
   *again* in the nested child-actor blob. Canonicalising now strips
   `taken_at` recursively. **Not a defect.**
3. `{"LATER": {"defer": True}}` is not the defer API; it is
   `onUnhandled: "defer"` at machine level.
4. **`SyncInterpreter.send()` returns a `Receipt` only with `wait=True`** —
   documented on the method. My N3-02 matrix read `None` for every field and
   looked like a missing `Receipt.denied`. **Not a defect.**
5. **`current_state_ids` is a `set`.** Comparing it to a list never matched,
   so every async settle loop silently burned its full timeout — N4 went from
   12 s to 300 s+ and hit the script cap. The traces were correct all along.
6. Inspector hook signatures are **positional** (`on_event_dropped(self,
   interpreter, event, reason)`, `on_unhandled_event(self, interpreter,
   event, active_state_ids, disposition)`). My `**kwargs` versions captured
   nothing, which made a correctly-reported `chain_budget` drop look
   **silent** — I nearly filed it as a High. See §3.2.
7. `on_resolve_error` is for an **unresolvable target** under
   `strict_targets=False`, not for an unimplemented action (that is a typed
   `ImplementationMissingError` at the call site).
8. My `OverflowPolicy.RAISE` attack used a **blocking sync** action, which
   stops the loop from ever running the `call_soon_threadsafe` callbacks, so
   the inbox never filled and the test proved nothing. An `async` action
   makes it real: 255 `QueueOverflowError`s at the call site.
9. My loop-liveness metric used an absolute `asyncio.sleep(0.005)` beat
   count, which is meaningless on Windows (~15 ms timer granularity). It now
   calibrates against a measured **idle** beat rate and asserts the loaded
   rate stays ≥60% of it.

10. My first liveness metric measured only ~4 heartbeats over a 0.1 s window
    (the services were too short), so the rate was pure quantisation noise
    and N2-01 flaked. With 0.25 s services and a ≥20-beat floor it is stable
    3/3 — and the measured answer is emphatic: **74 Hz loaded vs 64 Hz idle**,
    i.e. the loop is not merely alive under 200 blocking services, it is
    scheduling *faster* than idle.

Bugs 2, 6 and 8 each produced a false FAIL that would have been a filed
defect if I had counted before reproducing.

---

## 2. Prior-defect table

### 2.1 Prior suite, re-run unmodified on `cec108b`

| Group | 3ed3099 | cec108b | Delta |
|---|---|---|---|
| `n1_persistence.py` | 6/7 | **6/7** | N1-02 still FAIL (D6-semantics-1) |
| `n2_concurrency.py` | 5/6 | **5/6** | N2-06 FAIL — reclassified, see below |
| `n3_semantics.py` | 9/9 | **9/9** | — |
| `n4_determinism.py` | 5/5 | **5/5** | — |
| `n5_fuzz_obs_sec.py` | 7/7 | **7/7** | — |
| **Total** | **32/34** | **32/34** | composition changed |

**N2-06 is not a budget regression.** The prior script sends 60 `POKE`s
immediately after `await start()` and asserts all 60 reach the child. On
`cec108b` it observes 45. Reproducing it (`repro/d6s2_invoke_start_race.py`)
shows the losses are all inside the first ~15 ms, before the invoke child is
registered, and that each one is correctly reported as
`on_event_dropped(reason="unresolved_target")` — this is **D6-semantics-2**,
a start-contract / engine-parity defect, not mis-accounting. Waiting for the
child to register makes it 60/60.

### 2.2 Prior defects, individually

| Prior defect | Sev | Status on `cec108b` | Evidence |
|---|---|---|---|
| **D5-semantics-1** — snapshot inside an entry action accepted, persists a torn state | High | 🔴 **STILL-PRESENT** → re-filed as **D6-semantics-1** | `repro/d6s1_entry_window_torn_snapshot.py`; new N1-02; prior N1-02 |
| **D5-semantics-2** — `SimulatedClock.increment()` dispatches on the ambient loop | Low | 🟡 **CHANGED / accepted** — behaviour unchanged, already reclassified as constraint **DC-02** in the register (needs a gate check, not a fix) | prior `repro/d5s2_simclock_loop_context.py` |
| **D5-semantics-3** — leaf-deleted `configuration` restores as `running` with zero leaves | Med | ✅ **FIXED** — now `SnapshotCorruptError: status is 'running' but the configuration has no active leaf` | prior `repro/d5s3_truncated_config_inert.py`; new N1-04 |
| **D5-semantics-4** — untyped `TypeError`/`AttributeError` from `from_snapshot` (432/5000) | Med | ✅ **FIXED** — **0/9** targeted poisons and **0/5000** fuzz mutations escape `XStateMachineError` | prior `repro/d5s4_untyped_snapshot_errors.py`; new N5-02 |

Register items **R5-01 / R5-02 / R5-03**: R5-02 and R5-03 are **closed** by
this track's evidence. **R5-01 is only partly closed** — the parallel-tear
half is fixed and verified over 3,600 snapshots; the entry-window half is not.

---

## 3. New attacks

All scripts under `battle-cec108b/semantics/`; machine-readable results in
`semantics/results/*.json`.

### 3.1 Results

| Group | Result |
|---|---|
| `n1_persistence.py` — persistence | **5/6** (N1-02 = D6-semantics-1) |
| `n2_concurrency.py` — concurrency | **7/7** |
| `n3_semantics.py` — semantics | **7/7** |
| `n4_determinism.py` — determinism | **5/5** |
| `n5_fuzz_obs_sec.py` — fuzz / observability / security | **7/7** |
| `n6_soak.py` — soak | **clean** (§5) |
| **Total** | **32/33** |

### 3.2 What each group establishes

**N1 — persistence (5/6).**

- **N1-01 ✅** 300 random parallel machines (2–3 regions, compound regions,
  seed `random.Random(20260919)`), snapshotted at **every** quiescent point:
  **3,600 snapshots, zero refusals**, every one byte-identical on round-trip
  and configuration-identical. #142's stricter rule has **no false positives**.
- **N1-02 ❌** entry-action window → **D6-semantics-1**.
- **N1-03 ✅** deep history inside a parallel region survives snapshot and
  restore: the remembered leaf (`hp.a.busy.b2`) is in the restored history.
- **N1-04 ✅** a torn v2 configuration (region `b` dropped) and a legacy v1
  blob with a torn configuration are **both refused**, not upcast.
- **N1-05 ✅** an `actionErrorPolicy:"fail"` machine is `status="stopped"`
  with a cleared configuration and `TransitionFailedError` retained; the
  snapshot is coherent and does not restore as a live zombie.
- **N1-06 ✅** a snapshot with a live child actor *and* a deferred-event
  buffer round-trips byte-identical (child blob included); a deferred record
  with a non-`str` `type` is `SnapshotCorruptError` (#146/#158).

**N2 — concurrency (7/7).**

- **N2-01 ✅** 200 machines each running a blocking plain-`def` service: all
  200 complete, all ran **off** the loop thread, and the loop's measured
  heartbeat rate under load (**74 Hz**) is not merely ≥60% of its calibrated
  idle rate (**64 Hz**) — it exceeds it. #149 buys liveness without losing
  #116's ordering (see N4-03). Stable 3/3 re-runs.
- **N2-02 ✅** `stop()` with a service blocked in `gate.wait(3.0)` returns in
  well under a second and leaks no thread.
- **N2-03 ✅** `send_threadsafe(..., internal=True)` **forgery** from four
  plain `threading.Thread`s (800 sends, `maxIterations=30`) is charged to the
  chain budget; the excess is dropped but **observably** —
  `on_event_dropped(reason="chain_budget")` fires and the machine stays
  `running`. *(The attack my `**kwargs` inspector made look silent; §1.3/6.)*
- **N2-04 ✅** `OverflowPolicy.RAISE` + `max_queue_size=4` + 16 threads:
  **255 `QueueOverflowError`s raised at the `send_threadsafe()` call site**,
  and nothing else. The fire-and-forget caller learns on its own stack.
- **N2-05 ✅** double `task.cancel()` both before the loop's first turn and
  after: identical terminal outcome on both, `is_running=False`, and
  `send(wait=True)` returns rather than hanging. `_die` is idempotent.
- **N2-06 ✅** 500 start/stop cycles with an executor service: no thread and
  no asyncio-task growth.
- **N2-07 ✅** a caller-injected `service_executor` is used (services run on
  its named threads) and is **still usable after `stop()`** — the interpreter
  shuts down only a pool it owns.

**N3 — semantics (7/7).**

- **N3-01 ✅** `guardErrorPolicy:"raise"`: a throwing guard on the first
  `invoke.onDone` candidate cancels **only that candidate**; the unguarded
  fallback is taken on both engines. The completion is not swallowed (#152).
- **N3-02 ✅** the **Receipt matrix** (#153): guard-denied is
  `denied=True, changed=False`; undeclared is `denied=False`; handled is
  `changed=True, denied=False`. All three distinguishable.
- **N3-03 ✅** a root target is `RootTargetError` under `strict_targets`
  True, False **and** default — the #108 hole stays shut (#147).
- **N3-04 ✅** a child bricked by `actionErrorPolicy:"fail"` drives its
  parent's `invoke.onError` on **both** engines (#145).
- **N3-05 ✅** `escalate` from an **anonymous** invoke (no `id`) reaches the
  parent's `onError` on both engines (#156).
- **N3-06 ✅** a user action named `spawn_order` runs as the user's action;
  no actor spawned, no error (#155).
- **N3-07 ✅** `send_events(["A","B"])` gives exactly the same hops, final
  configuration and error state as `send("A"); send("B")` over a 5-deep
  `always` ladder — the settle budget is per macrostep (#151).

**N4 — determinism (5/5).** 50× byte-identical traces on the sync engine and
50× on the async engine with the service on the executor; the async trace is
**identical** to the sync trace (#116 parity survives #149); stable across 5
`PYTHONHASHSEED` values in fresh subprocesses; and a 3-region parallel
machine's entry/action order is identical 50× on both engines, with the two
engines agreeing.

**N5 — fuzz / observability / security (7/7).**

- **N5-01 ✅** 120 fuzzed machines across three livelock shapes (nested
  `invoke.onDone` re-entering the common ancestor — the #144 shape; `always`
  cycles across parallel regions; self-raising action chains), each under an
  8 s watchdog: **120/120 settled, zero hangs.**
- **N5-02 ✅** 5,000 snapshot mutations: `SnapshotCorruptError` 2,964,
  faithful restore 1,107, `SnapshotDriftError` 880, `SnapshotVersionError` 41,
  `StateNotFoundError` 8 — **0 untyped**. `except XStateMachineError:` is now
  sufficient (was 432 escapes).
- **N5-03 ✅** 20 hostile event shapes: 19 typed rejections; the one
  acceptance is the documented-legal `{"type":"OK","payload":<object>}`
  (payload *values* are the caller's). Nothing untyped escapes (#161).
- **N5-04 ✅** hook matrix — `guard_denied`, `unresolved_target`,
  `chain_budget`, `on_plugin_error`, `on_resolve_error` each fire **exactly
  once**: no double-fire, no miss.
- **N5-05 ✅** redaction (#160): with DEBUG logging captured off the real
  `xstate_statemachine` logger, `get_snapshot()` + `get_persisted_snapshot()`
  leak **none** of `iban` / `pan` / `cvc` / `otp` / `email`, while `qty=500`
  is still logged — targeted, not blanket suppression.
- **N5-06 ✅** executor thread context leakage: 8 machines sharing the service
  pool each saw **only its own** context (`owners == [0..7]`).
- **N5-07 ✅** API surface: all 18 required round-5 exports present; **every**
  exported error class derives from `XStateMachineError`; `Receipt` carries
  `changed / deferred / denied / error / state_ids`.

---

## 4. Defects

Two, both reproduced with a standalone script before being counted. No
Blockers.

### D6-semantics-1 — (High) a snapshot taken inside an ENTRY action is accepted and persists a TORN state

**Carried over from D5-semantics-1, unfixed.** Both engines.

- **Repro:** `battle-cec108b/semantics/repro/d6s1_entry_window_torn_snapshot.py`
  (also new attack **N1-02**, and prior attack N1-02).
- **Site:** `src/xstate_statemachine/base_interpreter.py:1306` —
  `if self._step_in_flight() and not self._configuration_is_legal():`
  (legality rule at `base_interpreter.py:1222`).

**What happens.** An order machine records a fill in the `filled` state's
entry action, in the realistic two-phase form (`ctx["filled_qty"] = 0`, work,
then `ctx["filled_qty"] = 100`). A `get_persisted_snapshot()` called from
inside that window is **accepted**:

```
live after settle : ['oms.filled']  ctx={'filled_qty': 100}
snapshot mid-entry: ACCEPTED
   persisted state : ['oms', 'oms.filled']  context: {'filled_qty': 0}
   restored        : ['oms.filled']  ctx={'filled_qty': 0}
   >>> TORN: state says FILLED, context says 0 filled
```

Restores are static, so the restored OMS sits in `filled` with the fill never
recorded. `last_transition_ok` stays `True` and `last_error` stays `None` —
there is no signal at all.

**Why round 5 did not close it.** #142 correctly replaced the any-leaf test
with per-region legality, which closes the *parallel* tear (and N1-01 shows
it does so without false positives over 3,600 snapshots). But the guard is a
conjunction: it refuses only a configuration that is *both* mid-step *and*
illegal. In the entry-action window the configuration is **perfectly legal** —
the new leaf is already active, exactly one per region — while the macrostep
is still open and the context is half-applied. Legality was never the right
predicate for this window; `_step_in_flight()` alone already is.

**Impact for an OMS.** Any code path that snapshots from inside an action
(an audit hook, a persistence action, a "checkpoint on fill" action — all
natural designs) can persist an order as filled with a zero fill quantity.
The failure is silent and survives restore.

**Suggested fix.** For the **root** of the call (`_seen is None`), refuse on
`_step_in_flight()` alone; keep the legality test for the recursive child
case, where it is exactly right. That is a one-line change at
`base_interpreter.py:1306` and does not weaken #142.

**Constraint if not fixed:** **CV-S07 (carried forward) — never call
`get_persisted_snapshot()` / `get_snapshot()` from inside an action.**
Snapshot only from outside the engine, at quiescence.

### D6-semantics-2 — (Medium, NEW) `await Interpreter.start()` returns before invoke children are addressable; the sync engine's does not

**Async engine only.** Engine-parity / start-contract defect.

- **Repro:** `battle-cec108b/semantics/repro/d6s2_invoke_start_race.py`
  (also the reclassified prior attack N2-06).

**What happens.**

```
async: actors immediately after `await start()` : []
async: first POKE -> drops: ['unresolved_target']
       last_error: sendTo target 'kid' did not resolve to a live actor; 'PING' was not delivered.
async: child actor became addressable 15.1 ms AFTER start() returned
sync : actors immediately after start()        : ['par:kid']
sync : sent 10 POKE -> parent saw 10 TICK
```

A supervisor whose initial state declares `invoke: {id: "kid", ...}` and
which pokes that child right after `await start()` loses every poke issued in
the first ~15 ms — 15 of 60 in the prior N2-06 shape. The **sync** engine
loses none: `SyncInterpreter.start()` has the child registered before it
returns.

**Mitigating — why Medium, not High.** The loss is **not silent**. Each
undelivered `sendTo` fires `on_event_dropped(reason="unresolved_target")`
and lands a soft step error, which is exactly the #133 reporting contract
working as designed. A caller who inspects receipts or hooks will see it.

**Why it is still a defect.** `await start()` reads — and is used — as "the
machine is up and its declared children exist". The two engines disagree on
that contract for the same config, which breaks the engine-parity property
the rest of round 5 (#116, #125, #133, #134, #145) works hard to establish.
It also makes a correct-looking supervision tree lose work with no code
change between engines.

**Suggested fix.** Have the async `start()` await the initial macrostep's
actor registration before returning (or expose an awaitable
`children_ready()` and document that `start()` does not imply it).

**Constraint if not fixed:** **CV-S09 (new) — on the async engine, do not
address an `invoke` child immediately after `await start()`.** Await the
child's registration (poll `interpreter._actors`, or drive the first message
through the parent's own state), or route first-message work through an event
the parent handles itself.

### Not a defect — three findings I withdrew after reproducing

| Looked like | Actually |
|---|---|
| `send_threadsafe(internal=True)` silently drops events | The drop **is** reported: `on_event_dropped(reason="chain_budget")`. My inspector used `**kwargs`; the hook is positional. Charging a forged `internal=True` to the budget is #150 working correctly. |
| `Receipt.denied` always `None` on the sync engine | `SyncInterpreter.send()` returns a `Receipt` only with `wait=True` — documented on the method. With `wait=True` the full #153 matrix is correct. |
| `OverflowPolicy.RAISE` never raises under 16 threads | My blocking **sync** action stopped the loop from running the `call_soon_threadsafe` callbacks, so the inbox never filled. With an `async` action: 255 `QueueOverflowError`s at the call site. |

---

## 5. Soak

`n6_soak.py`, **5 minutes** (reduced from the brief's 12 — §1.2), **200
order-like machines**, each a **parallel** machine with a `life` region
(`new → working → live → done`, `working` driven by a plain-`def` service on
the **executor**) and an independent `risk` region (`ok ⇄ halted`). Random
events from `{SUBMIT, FILL, CANCEL, BREACH, CLEAR, NOPE}`. Chaos every ~2 s:
10% of the fleet is snapshotted **at quiescence**, restored into a fresh
interpreter, compared, and swapped in.

| Metric | Result |
|---|---|
| Events processed | **4,271,000** |
| Snapshots (all at quiescence) | **2,980** |
| Restores | **2,980** |
| Order machines live over the run | 3,180 |
| `SnapshotMidStepError` at quiescence | **0** |
| Restore configuration drift | **0** |
| Restored `running` with an empty configuration | **0** |
| Lost fills across restore | **0** |
| Untyped exceptions | **0** |
| RSS delta | +27.2 MB over 5 min / 4.27M events |

**Zero faults of every kind measured.** The RSS delta is the only number
worth a note: +27 MB across 3,180 interpreter lifetimes and 2,980
restore-and-swap cycles is modest and flat-looking, but this run is too short
to distinguish "steady state reached" from "slow growth". It is recorded as a
**watch item**, not a defect — a longer run (`SOAK_SECONDS=3600`) is the
cheap way to settle it and is listed in §6.

Raw: `semantics/results/n6_soak.json`, `semantics/results/soak_stdout.txt`.

---

## 6. Not covered

Stated plainly, so the gate does not mistake absence of evidence for
evidence of absence.

1. **The brief's full 12-minute soak.** Run at 5 min. Re-run with
   `SOAK_SECONDS=720`. Related: the **RSS watch item** above needs a ≥1 h run
   to call.
2. **`hypothesis` proper.** The N1-01 property was run as a seeded
   `random`-driven property (300 machines × 12 quiescent points). A real
   `hypothesis` run with shrinking would produce smaller counterexamples if
   any exist; none did here.
3. **`SimulatedClock` / timer semantics.** Deliberately not re-attacked this
   round: D5-semantics-2 is already reclassified as constraint DC-02, and the
   timer surface is the determinism track's. The interaction of
   `restart_timers=True` with a **parallel** history restore is untested by
   anyone so far.
4. **Multi-level actor trees.** All actor attacks here are parent→child, one
   level. Grandchild `escalate`, and a snapshot taken while a *grandchild* is
   mid-step (the `_await_settled_for_snapshot` bound at
   `base_interpreter.py:1198`), are untested.
5. **Cross-process / real persistence.** Snapshots round-trip through
   `json.dumps` in-process. No test writes to a real store, and no test
   restores a blob produced by a *different* library version (only the
   synthetic v1 shape in N1-04).
6. **`OverflowPolicy` other than RAISE** under the new call-site classification
   (BLOCK/DROP were covered in the prior round, not re-run against #157).
7. **PR #141 (hot-path perf) and #163 (coverage gate)** — not this track's
   remit; no performance claim is made here. N2-01 measures loop *liveness*,
   not throughput.
8. **Windows only.** Every number above is from Windows 11 / CPython 3.13.
   The executor-hop ordering (#149 vs #116) is exactly the kind of thing that
   can differ on Linux epoll; N4-03 should be re-run there before adoption.

---

## 7. Verdict

**The semantics track does not block adoption of `cec108b`.**

Round 5 is the strongest round this track has measured. Of the four prior
defects, three are fixed and one is reclassified as an accepted constraint;
the two register items this track owns end-to-end (R5-02, R5-03) are
**closed** with hard evidence — 0/5000 untyped snapshot errors, down from
432/5000. Every headline fix passes its own attack, including the three most
likely to have regressed something else: the executor move (#149) keeps
#116's ordering *and* the loop's liveness; the chain budget (#150) is charged
*and* observable; the legality rule (#142) refuses torn configurations with
**zero** false positives over 3,600 quiescent snapshots. Determinism is
intact on both engines and across hash seeds. A 4.27M-event chaos soak with
2,980 restores is spotless.

**One High carries forward unfixed** — D6-semantics-1, the entry-action
snapshot window. It is narrow, it has a one-line candidate fix, and it is
fully contained by an adoption constraint that is easy to hold and easy to
lint for. **One new Medium** — D6-semantics-2, the async `start()` /
invoke-child race — is an engine-parity wart whose failure is *reported*,
not silent.

**Adoption constraints from this track:**

| ID | Constraint | Status |
|---|---|---|
| **CV-S07** | **Never call `get_persisted_snapshot()` / `get_snapshot()` from inside an action.** Snapshot only from outside the engine, at quiescence. | **carried forward** (D6-semantics-1) |
| **CV-S09** | **On the async engine, do not address an `invoke` child immediately after `await start()`.** Await the child's registration first. | **new** (D6-semantics-2) |
| DC-02 | `SimulatedClock.increment()` dispatches on the ambient loop — never drive a `SyncInterpreter` on a `SimulatedClock` from inside a running loop. | unchanged, register-owned |

CV-S07 is worth a lint rule (`get_persisted_snapshot` must not appear in any
module that defines machine actions); CV-S09 is worth a single shared
`await_children_ready(interp)` helper in the adopting project's bootstrap.

**Recommended before the gate closes:** re-run N4-03 and the soak on Linux
(§6.8), and run the soak for ≥1 h to settle the RSS watch item.
