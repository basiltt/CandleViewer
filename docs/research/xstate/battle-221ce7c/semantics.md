# Battle track: SEMANTICS @ 221ce7c

**Library:** `_ref/xstate-statemachine` @ `221ce7c` (merge of #178; unreleased
0.8.1, `__version__` still reports 0.8.0 — keyed on commit).
**Scope:** round-7 re-verification of the round-6 semantics defects, plus new
attacks aimed squarely at this round's fixes (#166–#175, #157, #122).
**Scripts:** `battle-221ce7c/semantics/{n1..n6,s1..s5}*.py`, repros under
`repro/`, machine-readable results under `results/`.

Financial-OMS standard applied throughout: nothing is counted as a defect
without a standalone repro that reproduces on a clean interpreter.

---

## 1. Prior-defect table (round 6 → round 7)

Re-ran every script in `battle-cec108b/semantics/` unmodified against 221ce7c.
Only one adaptation was needed and it is recorded in §5.

| Prior | Title | R6 status | **R7 status** | Evidence |
|---|---|---|---|---|
| **R6-06** / D6-semantics-1 | Snapshot inside an **entry/exit action** accepted, persists a torn (state, context) pair; both engines | FAIL (High) | **FIXED** | `n1_persistence.py::N1-02` PASS. `_step_in_flight()` alone now refuses at the root (`base_interpreter.py:1389`). **But see D7-semantics-1/3 — the fix has two holes.** |
| **R6-11** / D6-semantics-2 | `await start()` returns before the initial config's invoke children are registered; engines disagree on `start(); send(CANCEL)` | FAIL (Medium) | **FIXED** | `s4_semantics_det_sec.py::S4-02` PASS — 20× identical trace on both engines, `_actors` = `['o:kid']` the instant `start()` returns. |
| **R6-10** | `Receipt.denied` conflates guard-refused with guard-**crashed** | FAIL (High) | **FIXED** | `S4-01` PASS. 4-way matrix `(denied, error is None, deferred, changed)` is injective on both engines: DENY `(T,T,F,F)`, CRASH `(F,F,F,F)`, unhandled `(F,T,F,F)`, OK `(F,T,F,T)`. |
| **R6-01..05, R6-07..09, R6-12..20** (non-semantics-track items reachable from this suite) | — | mixed | **no regressions** | `n2` 7/7, `n3` 7/7, `n4` 5/5, `n5` 7/7 PASS. |
| Prior suite whole-run | `n1..n6` | 32/33 PASS (N1-02 FAIL) | **33/33 PASS** | `results/n*.json` |

**Prior-suite verdict: every previously-open semantics defect is closed.** The
single round-6 FAIL (`N1-02`) now passes, and nothing that passed in round 6
regressed.

---

## 2. New attacks

11 new attacks in 5 scripts. Reductions from the brief are listed in §5.

| ID | Target | Result |
|---|---|---|
| `S1-01` | Snapshot from **every** plugin hook (`on_transition`, `on_action_execute`, `on_guard_evaluated`, `on_event_received`) on a nested+parallel machine, both engines — refused-or-legal, never torn | **PASS** |
| `S1-02` | Property: **300 random** nested/parallel machines × both engines, 19,945 hook snapshots, paired-write invariant `px == qty` | **FAIL → D7-semantics-1** |
| `S2-01` | #166: 16 concurrent external `send_threadsafe` senders during a self-generated chain must **not** refill the per-macrostep budget | **PASS** (trips at lap 1001; see D7-semantics-2 on the reporting channel) |
| `S2-02` | #173: `service_pool_size=1`, 50 machines × plain services, plus `stop()` mid-service | **PASS** — 50/50 completed, `stop()` in 0.0 s, 0 leaked threads |
| `S2-03` | #173: knob validated (`0` → `ValueError`), `pool8` beats `pool1` (0.154 s vs 1.208 s), `DEFAULT_SERVICE_POOL_SIZE` exported | **FAIL → D7-semantics-4** (export only) |
| `S2-04` | #157: loop-side `RAISE` refusal fires `on_event_dropped("queue_full")` **exactly once** per refusal under 16 flooding threads | **PASS** — hook count == future-observed refusals |
| `S2-05` | #172: threadsafe in-flight counter returns to 0 after delivered / refused / cancelled / loop-stopped-before-run | **PASS** — all three cases 0 |
| `S3-01` | **520** generated cycle configs × async engine, 25 s watchdog | **PASS** — 520/520 settled, 0 hangs, 0 silent trips |
| `S3-02` | Same 520 configs × sync engine + shape-level trip parity | **PASS** — 520/520 settled, 0 hangs |
| `S4-03` | Trip-point determinism: 50× per engine, lap count at the budget | **PASS** — `{1001}` on both engines, single value |
| `S4-04` | Perf-PR (#165/#176) shared init/exit sentinel **aliasing**: two machines from one config dict | **PASS** — no context/list/history aliasing, config dict unmutated |
| `S4-05` | `__slots__` attribute surface | **PASS** (with a by-design note, §4) |
| `S4-06` | #169 at the **child** boundary: root snapshot while a child actor is mid-entry | **FAIL → D7-semantics-3** |
| `S5` | 12-min soak, 200 machines, 3 shapes (parallel ORDER, rollback+onDone, always→invoke), executor services, chaos snapshot/restore at quiescence | see §6 |

---

## 3. Defects

### D7-semantics-1 — async `start()` does not set the in-flight flag, so the #169 entry-window refusal is inert during initial entry (**High**)

**Engines:** async only (`SyncInterpreter` refuses correctly).
**Repro:** `battle-221ce7c/semantics/repro/d7s1_start_entry_window_torn.py`
**Property:** `s1_persistence_hooks.py::S1-02` — 300 random machines, every torn
sample is `engine=async, where=on_action_execute`.

```
--- sync
  live after start : ['oms.filled'] ctx={'filled_qty': 100, 'avg_px': 101.5}
  snapshot in entry: REFUSED
  snapshot in entry: REFUSED
--- async
  live after start : ['oms.filled'] ctx={'filled_qty': 100, 'avg_px': 101.5}
  snapshot in entry: ACCEPTED ctx={'filled_qty': 0, 'avg_px': 0}
  snapshot in entry: ACCEPTED ctx={'filled_qty': 100, 'avg_px': 0}
     >>> TORN: filled_qty set, avg_px not written yet
     restored: ['oms.filled'] ctx={'filled_qty': 100, 'avg_px': 0} last_error=None
```

**Root cause.** `base_interpreter.py:1389` refuses when `_step_in_flight()`,
which reads `_processing` (async) / `_is_processing` (sync)
(`base_interpreter.py:1290-1295`). The sync engine deliberately sets
`_is_processing = True` around the initial descent
(`sync_interpreter.py:370-374`, with an explicit architecture comment). The
async `start()` (`interpreter.py:536-556`) calls `_enter_states` and
`_settle_transient_transitions` **without ever setting `self._processing`** —
that flag is only set inside the run loop at `interpreter.py:1654`. So for the
whole initial-entry window the async engine reports "not in flight" and #169's
guard never engages.

**Impact.** This is exactly the financially-wrong blob #169 exists to prevent —
`filled` paired with `filled_qty=0` — restoring clean with `last_error=None`,
`last_transition_ok=True`. It is reachable from any `on_action_execute` plugin
(audit/reconciliation plugins are the documented use for that hook), and #171
*widened* the window by moving invoke-child registration and initial settling
into `start()`. It is also a **new engine-parity break** in the same area #169
was filed to unify.

**Suggested fix:** set `self._processing = True` for the duration of the
initial-entry + settle block in `Interpreter.start()`, mirroring
`sync_interpreter.py:370-374`.

### D7-semantics-3 — a root snapshot harvests a child actor's half-applied context (**High**)

**Engines:** both (probed on async).
**Repro:** `battle-221ce7c/semantics/repro/d7s3_child_midentry_torn_actor_blob.py`
**Attack:** `s4_semantics_det_sec.py::S4-06`

```
root in flight during child entry : False
live child after settle           : ['kid.y'] ctx={'q': 100, 'p': 101}
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q': 0, 'p': 0}
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q': 100, 'p': 0}   >>> TORN
```

**Root cause.** `base_interpreter.py:1389-1394`. At the root the guard refuses
on `_step_in_flight()` alone — but the check is on **`self`**. When the root is
quiescent and only a *child actor* is mid-entry, the root passes its own check
and then recurses into the child. The child is reached with `_seen is not None`,
so it takes the lenient branch: it only waits when
`not self._configuration_is_legal()`. Inside an entry action the child's
configuration **is** legal (`kid.y` active, one leaf) while its context is
half-applied — precisely the conjunction #169 removed at the root and left in
place at the child. The persisted hierarchy therefore embeds
`actors["par:kid"].snapshot = {state_ids: ["kid.y"], context: {q:100, p:0}}`.

**Impact.** In a parent/child OMS decomposition (the documented actor pattern)
the parent's snapshot is the unit of persistence. A torn child blob is
indistinguishable from a legitimate one and restores silently. Severity matches
R6-06 (High) — same failure mode, one level down.

**Suggested fix:** in the child branch, wait on `_step_in_flight()` too (not
only on illegality), and escalate to `SnapshotMidStepError` if the child has
not settled within the bounded wait rather than harvesting it mid-step.

### D7-semantics-2 — `last_error` is a latch cleared by the next successful transition, so a `RunawayChainError` trip is unobservable via that field under concurrent traffic (**Medium**)

**Repro:** `s2_concurrency_obs.py::S2-01`, run with and without the 16-thread flood:

```
flood=False drops=1 at_first_drop=('chain_budget', None) last_error_now=RunawayChainError ticks=1001
flood=True  drops=1 at_first_drop=('chain_budget', None) last_error_now=None            ticks=1001
```

The budget itself is **correct**: the chain trips at lap 1001 in both runs, and
external senders do not refill it — #166's headline claim holds under 16
concurrent senders. The defect is in the *reporting channel*. Two facts
compound:

1. At the instant `on_event_dropped("chain_budget")` fires, `last_error` is
   still `None` — it is assigned *after* the hook loop
   (`interpreter.py:1565-1576`), so a plugin reading `interpreter.last_error`
   from its own drop hook sees nothing.
2. `last_error` is then cleared by the next successful transition, so under any
   concurrent external traffic it reads `None` milliseconds later.

Callers told to reconcile from `last_error` (the CHANGELOG's stated signal:
"a trip is observable (`last_error` is `RunawayChainError`)") will miss trips on
a busy machine. The `on_event_dropped` hook is the only reliable channel and is
the one our wrapper obligation must key on.

**Suggested fix:** set `_last_action_error` before firing the drop hooks, and
document `last_error` as a latch-until-next-success (or add a monotonic
`chain_trips` counter).

### D7-semantics-4 — `DEFAULT_SERVICE_POOL_SIZE` is not exported from the package root (**Low**)

**Attack:** `s2_concurrency_obs.py::S2-03`.

```
from xstate_statemachine import DEFAULT_SERVICE_POOL_SIZE
  -> ImportError: cannot import name 'DEFAULT_SERVICE_POOL_SIZE'
'DEFAULT_SERVICE_POOL_SIZE' in xstate_statemachine.__all__  -> False
from xstate_statemachine.interpreter import DEFAULT_SERVICE_POOL_SIZE  -> 4  (works)
```

CHANGELOG line 73 announces "**`Interpreter(service_pool_size=N)`** and
`DEFAULT_SERVICE_POOL_SIZE`" as Added, and `docs/api/index.md:695` cites the
name in the public parameter table, but `__init__.py.__all__` (line 205) omits
it. The value is reachable only via the private submodule path. Everything else
about #173 is correct: `0` → `ValueError`, and `pool_size=8` is 7.8× faster
than `pool_size=1` on 8 concurrent plain services (0.154 s vs 1.208 s).

**Suggested fix:** one line in `__init__.py.__all__`.

---

## 4. Non-defects — probed, refuted, recorded

These are things the attacks flagged that we **deliberately did not** count:

- **`__slots__` still allows ad-hoc attributes** (`S4-05`). `BaseInterpreter.__slots__`
  retains `"__dict__"` (`base_interpreter.py:510`) with an explicit comment
  (`:464`) that this is kept so subclasses and test spies keep working. Every
  *declared* slot is a real slot (verified: `status` never appears in the
  instance `__dict__`), and every documented public attribute still reads on
  both engines. **By design, not a defect.**
- **Async invoke ping-pong looks like an engine-parity break in `S3-01/02`**
  (async tripped 130, sync 390). It is a *timing* artefact of the oracle:
  `send(wait=True)` returns before the async completion cycle has burned its
  budget. `repro/d7_lap_parity.py` settles it — **both engines trip at the same
  lap, 1002**, with the same `chain_budget` drop and the same
  `RunawayChainError`; async just lands ~3 s later. S3-02 is annotated
  accordingly. **#166's parity claim holds.**
- **Rollback+onDone (shape 2) does not trip the chain budget on either engine**
  — it terminates via the action's own `RuntimeError` under
  `actionErrorPolicy: "rollback"` (`last_error=RuntimeError`, machine parked in
  `work`). Bounded and observable; different mechanism, same outcome. Not a
  defect.
- **`last_error` being `None` inside `on_event_dropped`** is folded into
  D7-semantics-2 rather than filed separately (same root cause, one fix).
- **Prior `N1-02` adaptation**: none needed. The script ran unmodified and
  flipped FAIL→PASS on its own.

## 5. Reductions and deviations from the brief

Recorded per the hard-bounds rule; each is a reduction in *volume*, never in
the property being asserted.

| Brief | Run | Why |
|---|---|---|
| Fuzz ≥500 configs, 30 s watchdog | **520 configs, 25 s watchdog** | 30 s × any hang would blow the 120 s/script bound; 25 s is still >100× the observed settle time (max <0.3 s). Zero hangs, so the watchdog never bound. |
| Property ≥300 random machines | **300 machines** (19,945 snapshots, both engines) | at size. |
| Soak 12 min | **12 min / 720 s, 200 machines** | at size (see §6). A 100 s re-run of the *prior* soak (`n6`) was also clean. |
| Restore+resume trace parity | folded into `S4-02` + the soak's 1,000+ chaos restore/compare cycles | the dedicated parity oracle would duplicate `n4_determinism.py`, which passes 5/5. |
| Hash-seed sweep | **reused `n4_determinism.py::N4-04`** (5 seeds, fresh subprocess each) — PASS | unchanged code path; re-deriving it would spend budget for no new coverage. |
| `internal=True` forgery post-fix | **reused `n2_concurrency.py::N2-03`** — PASS (charged to budget, drop observable) | unchanged; re-verified in the prior-suite re-run. |
| Redaction | **reused `n5_fuzz_obs_sec.py::N5-05`** — PASS | unchanged. |

## 6. Soak (12 min, 200 machines, 3 shapes)

`s5_soak.py`, `SOAK_SECONDS=720`, `SOAK_MACHINES=200`. Shapes rotate across
machines: parallel ORDER (life + risk regions, executor `price` service),
ROLLBACK+onDone (`actionErrorPolicy: "rollback"`, action raises every 5th
fill), ALWAYS→invoke (`always` into an invoking state — the #166 shape). Chaos
every ~2 s: snapshot 10% of machines **at quiescence**, restore into a
same-shape machine, compare configuration and `filled`.

```
soak_seconds  720.0      machines 200      events 186,000
snapshots     5,512      restores 5,512    orders  5,712
restore_drift       0    inert_running   0    lost_fills      0
typed_errors        0    untyped_errors  0
midstep_at_quiescence  68      <-- see note
rss_delta_mb     8.09    cpu_percent_avg 117.0
shapes: ORDER(parallel) | ROLLBACK+onDone | ALWAYS->invoke
```

**CPU bounded, no livelock, no memory growth.** 117% average CPU across the
whole 12 minutes on a machine mix that includes both round-6 livelock shapes —
i.e. roughly one saturated core plus the executor pool, flat, with no runaway.
8 MB RSS drift over 186k events and 5,512 restore cycles. Zero restore drift,
zero inert-running restores, zero lost fills, zero untyped errors — the
persistence contract held across 5,512 real snapshot→restore→compare cycles on
live machines.

**The 68 `midstep_at_quiescence` (1.2% of snapshots)** are `SnapshotMidStepError`
raised where the harness believed the machine was idle. They concentrate on the
`ALWAYS→invoke` and `ROLLBACK+onDone` shapes, where a plain-`def` service's
`done.invoke` can still be in flight after `send(..., wait=True)` returns — the
same latency D7-semantics-2 and §4's lap-parity note describe. This is the
**fail-closed** direction (refuse rather than persist a maybe-torn blob) and is
therefore *not* filed as a defect; it is recorded because it is a real
operational consequence: **a caller cannot assume a snapshot at apparent
quiescence will succeed, and must retry.** That is a wrapper obligation, not a
library bug.

## 7. Not covered

- **`after`-timer callback snapshots** and **deferred-replay snapshots** — the
  brief lists both as hook sites. The `PluginBase` surface has no hook that
  fires *inside* a timer callback or *inside* the deferred-replay loop, so
  there is no supported call site to attack from without reaching into private
  internals. Given D7-semantics-1's root cause (a missing `_processing` set
  during a non-loop-driven entry path) these are the **most likely places for a
  third instance of the same bug**, and should be probed with an
  internals-level harness next round.
- **`sendTo` self-loop fuzz shape** — generated but every instance was rejected
  at build time by the target resolver, so it contributed no coverage. Shape 3
  was replaced with a `raise_` self-loop, which does exercise the chain budget.
- **Multi-level (grandchild) actor hierarchies** for D7-semantics-3. Probed one
  level; the recursion at `base_interpreter.py:1394` is depth-independent, so a
  grandchild is expected to tear identically, but that is inference, not a
  reproduced result.
- **Cross-process / `ProcessPoolExecutor` services** under `service_pool_size`.
- **`SimulatedClock`** interaction with the per-macrostep budget (#122 was
  closed as-designed; we did not re-litigate it).

## 8. Verdict

**Round-6 semantics defects: all closed.** R6-06, R6-10 and R6-11 each
reproduce as FIXED with the prior suite's own unmodified oracles, and the prior
suite went 32/33 → 33/33 with no regressions. The round-6 fixes are real, and
the two headline claims we could test hardest — bounded self-generated cycles
on both engines (520 configs, 0 hangs) and a deterministic trip point (lap 1001,
50× per engine, identical across engines) — **hold**.

**But #169 was fixed at one call site, not as an invariant.** Both new High
defects are the *same* bug as R6-06 reached by a different door:

- **D7-semantics-1** — async `start()` never sets `_processing`, so the entry
  window during initial entry is still wide open, and now the engines disagree
  again in exactly the area #169 unified. #171 widened this window.
- **D7-semantics-3** — the root refuses on its own in-flight flag but harvests
  child actors through the *old* legality conjunction, so the torn blob simply
  moved one level down the hierarchy.

Both persist a financially wrong (filled / zero-quantity) blob that restores
clean with `last_error=None`. Both are one-line-ish fixes in the same function.

**Adoption position for this track: NOT READY, narrowly.** The engine is
semantically sound under load — the soak is clean, the fuzz is clean, the
determinism is exact. The blocker is that the persistence *refusal invariant*
is still enforced per-call-site rather than as a property, and an OMS whose
reconciliation reads persisted snapshots cannot accept a silent torn blob. With
D7-semantics-1 and D7-semantics-3 fixed and re-verified against `S1-02` and
`S4-06`, this track clears.

**Wrapper obligations to carry forward regardless of the fixes:**
- **W-S1**: never call `get_persisted_snapshot()` from a plugin hook or an
  action; snapshot only from application code at a known-quiescent point, and
  **retry on `SnapshotMidStepError`** (the soak shows a 1.2% refusal rate at
  apparent quiescence).
- **W-S2**: reconcile chain-budget trips from `on_event_dropped(reason=
  "chain_budget")`, **not** from `interpreter.last_error` (D7-semantics-2).
- **W-S3**: import `DEFAULT_SERVICE_POOL_SIZE` from
  `xstate_statemachine.interpreter`, or pin the literal, until
  D7-semantics-4 is fixed.
