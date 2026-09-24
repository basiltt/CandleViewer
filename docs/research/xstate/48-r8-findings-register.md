# 48 — Round-8 findings register: `xstate-statemachine` `main` @ `6db65d8`

Date: 2026-09-21. Library: `_ref/xstate-statemachine` @ `6db65d8` (merge of #191, "0.8.1
round-7"; `__version__` still reports `0.8.0` — key on the commit). Venv `.venv-main`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Method.** Every round-8 candidate (battle tracks + `47-r8-diff-review.md` M-* +
`45-r8-regression.md`) was re-run fresh under a 120 s cap in this session, the cited source
lines were read, and each was classified `LIBRARY-DEFECT` / `HARNESS-ERROR` /
`DESIGN-CONSTRAINT` / `OUR-CONTRACT-DEFECT` / `DUPLICATE`. Same-root-cause candidates are
merged into a single `R8-nn`. Service-related findings are stated for **both** `def` and
`async def` service kinds, per the financial-OMS standard.

## 0. Answer

**15 canonical findings. 2 blockers, both LIBRARY-DEFECTs, both regressions introduced by
the round-7 fix set.** Nothing in round 7's fix set is reverted by these, but two of its
headline claims are false as written: #180's "provenance by WHO" is implemented on one side
of the ledger only (R8-01), and #179's "both service kinds now trip at the same lap count as
the sync engine" does not hold (R8-11). The largest single risk to an OMS is **R8-02**: a
plain `def` service is not a service at all on the async engine — it runs on the loop
thread, cannot be cancelled, and is not unwound by rollback.

**Adoption impact.** The existing wrapper obligation "never write a non-coroutine service"
(W-01) is upgraded from *medium/style* to **hard prerequisite**: R8-02 alone removes the
kill switch, the cancel path, and event responsiveness for any `def` service. With that
rule enforced, R8-01 remains a blocker on its own (it is service-kind independent).

### Canonical table

| ID | Sev (OMS) | Class | Title | Merges |
|----|-----------|-------|-------|--------|
| **R8-01** | **Blocker** | LIBRARY-DEFECT | Priority lane honours provenance when charging, ignores it when shedding — self-sent priority events livelock unbounded, external priority events are destroyed | D8-concurrency-1, D8-fuzz-2, D8-semantics-1, M-1 |
| **R8-02** | **Blocker** | LIBRARY-DEFECT | A plain `def` service runs inline on the loop thread: blocks all event processing, is never cancelled on state exit, and is not unwound by rollback | D8-concurrency-2, LD-01, CV-6DB-01(blocker), W-01 |
| **R8-03** | High | LIBRARY-DEFECT | `start(children_timeout=)` (#181) is a no-op against non-yielding child entry actions; the WARNING is suppressed too; and the bound is aggregate, not per child | D8-concurrency-3, D8-persistence-3, M-4 |
| **R8-04** | High | LIBRARY-DEFECT | `always` → invoking child → `onDone` re-entry starves the inbox permanently with every health signal green | D8-fuzz-3 |
| **R8-05** | High | LIBRARY-DEFECT | `DoneEvent` / `AfterEvent` carry no provenance marker and are exempt from `strict` / `onUnhandled`: a forged completion drives a real `onDone` | D8-persistence-1 |
| **R8-06** | High | LIBRARY-DEFECT | #185's drift check is bypassable by version downgrade (`version: 0` + no `machine_hash`) | D8-persistence-2 |
| **R8-07** | Medium | LIBRARY-DEFECT | `await send(EV, wait=True)` can resolve at an instant when `current_state_ids == []`, success-shaped | D8-fuzz-1 |
| **R8-08** | Medium | LIBRARY-DEFECT | #186's `configuration`/`state_ids` agreement rule is one-sided: empty/absent either field short-circuits the check | D8-persistence-5, D8-fuzz-4, OBS-state-ids-empty |
| **R8-09** | Medium | LIBRARY-DEFECT | `get_persisted_snapshot()` from `on_interpreter_start` returns a torn blob (`status:"running"`, empty configuration), both engines | D8-concurrency-4 |
| **R8-10** | Medium | LIBRARY-DEFECT | `_chain_owed` leaks permanently on a `BaseException` service exit and is settled by a bare counter, not matched to the debt | M-2, M-3 |
| **R8-11** | Medium | LIBRARY-DEFECT | #179's service-kind parity claim is false for `invoke` ping-pong and rollback+`onDone`; sync/async cut the same chart at different lap counts | D8-persistence-4, CV-6DB-01(low) |
| **R8-12** | Medium | DESIGN-CONSTRAINT → NEEDS-WRAPPER | A chain-budget trip never reaches the originating caller's receipt or the `on_error` hook | CV-6DB-02, LIB-R6-01, W-02 |
| **R8-13** | Low | LIBRARY-DEFECT | Call-site `QueueOverflowError` refusals fire no `on_event_dropped`; hook coverage of the shed rate collapsed to 0.3% | D8-concurrency-5 |
| **R8-14** | Low | LIBRARY-DEFECT | `SnapshotMidStepError` from an invoked child's entry action reports `child=False` | D8-fuzz-5 |
| **R8-15** | Low | LIBRARY-DEFECT | The validator accepts unknown top-level config keys silently; `spawnBlockingTimeout` is parsed and dropped | WRAP-unknown-keys, WRAP-spawnBlockingTimeout |

Non-findings (verified clean / ours / stale) are in §3–§5.

---

## 1. Blockers

### R8-01 (BLOCKER, LIBRARY-DEFECT) — the priority lane charges by provenance and sheds by position

**Merges** D8-concurrency-1, D8-fuzz-2, D8-semantics-1, M-1. One root cause, two opposite
symptoms; filing them apart would have hidden that fixing either half alone makes the other
worse.

**Root cause (source read, `interpreter.py` @ `6db65d8`).**
`_deliver_priority` (:2342–2389) charges the chain budget **only** when
`engine_completion=True`:

```python
if engine_completion:
    if self._chain_owed:
        self._chain_owed -= 1
    self._raise_depth += 1
self._priority_queue.append(event)
```

The shed test in the run loop (:1598) is a property of the *chain*, applied to whatever
`_next_event()` pulled off the single `_priority_queue` FIFO:

```python
over = self._raise_depth > limit
```

`_priority_queue` carries engine completions and public `send(..., priority=True)` events
side by side, and there is no provenance test at the drop site. Meanwhile the **non**-priority
`send()` path *does* make the distinction correctly (:898–908) via `_issued_from_own_action()`,
routing a self-issued send to the internal queue and incrementing `_raise_depth`;
`priority=True` never reaches that branch.

So the ledger is inverted on both sides:

- **False negative** — a `send(priority=True)` issued *from the machine's own action* is
  self-raised by #180's own definition and is **never charged**. `maxIterations` is inert on
  that lane.
- **False positive** — a genuinely external `send(priority=True)` sitting at the head of
  the FIFO when an unrelated self-generated chain trips is **destroyed** with
  `reason="chain_budget"`.

**Reproduced this session (fresh).**

- `battle-6db65d8/concurrency/r8b_priority_self_send_livelock.py` → `result: FAIL`.
  2/2 defect cells (`def` and `async def`) `LIVELOCK` under a 20 s **process** watchdog,
  `trip_observable: false`. The spin starves the loop so hard that an in-process
  `asyncio.wait_for` never fires and `stop()` never returns — a process-level watchdog is the
  only way to observe it. The control cells (non-priority self-send) trip normally.
- `battle-6db65d8/semantics/repro/d8_s1_priority_shed.py` → exit 0, verdict line
  `REPRODUCED`. 2000 external priority sends during a self-generated invoke cycle,
  `maxIterations=50`:
  - `{'kind': 'plain', 'external_sent': 2000, 'send_accepted_no_raise': 2000,
    'external_applied': 1992, 'external_LOST': 8,
    'chain_budget_drops_by_type': {'EXT': 8, 'done.invoke.pp.a': 1}, 'last_error': None}`
  - `{'kind': 'async', ... 'external_LOST': 0, 'last_error': 'RunawayChainError'}`

  Note the lanes disagree: the `def` lane loses external events with `last_error` **None**
  (silent), the `async def` lane loses none but trips. Both halves of R8-01 are present in
  one run.
- `battle-6db65d8/fuzz/r8_ext_shed_loss.py` (prior artefact, end-to-end action watermark):
  `def` fire-and-forget sent=600 sender_ok=600 APPLIED=592 **LOST=8**; `wait=True` LOST=1;
  `async def` cells 0 lost.

**Classification.** LIBRARY-DEFECT, and a **regression** vs `221ce7c`: before #180 the charge
was by timing, which over-charged external traffic (~50% loss, the filed defect) but did
charge self-sent priority events. #180 fixed the false positive at the charge site and
introduced the false negative, while leaving the false positive alive at the shed site.

**OMS severity: Blocker.** Two independent disqualifiers. (a) The livelock is unbounded and
**silent** — `last_error` stays `None`, no hook fires, `stop()` never returns, and the event
loop is starved, so an OMS process hosting other machines or an HTTP server on the same loop
dies with it; there is no in-process detection short of an external watchdog. (b) An external
`send(priority=True)` is precisely the kill-switch / cancel lane, and it can be destroyed
with a success-shaped fire-and-forget send and `last_error: None`. Magnitude on (b) is now
small (~0.4–1.6%, confined to `maxIterations <= 10`… `<= 50`) and *is* visible via
`on_event_dropped` and via `Receipt.error` under `wait=True` — but a kill switch that is
silently dropped 1 time in 250 is not a kill switch.

**Fix direction (upstream).** Provenance must be carried on the *event*, not inferred at
either site: tag the queued item at enqueue time (engine-completion vs self-raised vs
external), charge self-raised **and** engine completions, and make the shed test refuse to
drop anything tagged external — or give external priority sends their own FIFO that the
chain-budget axe cannot reach. Route `send(priority=True)` through `_issued_from_own_action()`
as the inbox lane already does.

**Wrapper mitigation (insufficient alone).** Never issue `send(priority=True)` from inside an
action; always `wait=True` on control-path priority sends and treat `Receipt.error` /
`on_event_dropped(reason="chain_budget")` as a send failure and retry. This does not address
the livelock half if any dependency issues a priority send from an action.

---

### R8-02 (BLOCKER, LIBRARY-DEFECT) — a plain `def` service is not a service: it runs on the loop thread, cannot be cancelled, and is not unwound by rollback

**Merges** D8-concurrency-2, LD-01, CV-6DB-01(blocker), W-01. Four symptoms, one decision:
#116 made a non-coroutine service run **inline**, inside the macrostep that enters the
invoking state, so its `done.invoke` orders like the sync engine's. Every consequence below
follows from that single choice, so they are one finding.

**Root cause (source read).** The run loop at `interpreter.py:1577` gates the inbox behind
inline services:

```python
while self.status == "running":
    if self._inline_service_futures:
        await self._await_inline_services()      # :2713-2735, gathers to completion
    event, from_inbox = await self._next_event() # the ONLY inbox drain
```

The comment at :1569–1576 asserts *"The loop stays live: this is an await, not a block"* —
true of the OS thread, false of the machine: the loop cannot reach `_next_event()`, which is
the only thing that drains the inbox. The `async def` path has no equivalent gate; its
completion arrives via `_publish_completion` on a later turn. Round 7 mis-attributed this to
the per-external-event budget reset at :1646–1652, which is shared by both lanes and
therefore cannot explain the split.

Because the call happens during *entry*, before the `always` chain is evaluated and before
the rollback epilogue runs, a `def` service is **already called** when the step is undone —
and a call cannot be unwound. A coroutine service is armed as a task, and arming *is* unwound.

**Four reproduced symptoms (all fresh this session, both service kinds).**

1. **Total unresponsiveness while the service runs.**
   `concurrency/r2c_def_service_blocks_loop.py` → `result: FAIL`. A 2 s service is armed on
   entry; a `PING` targeting a *different* state is sent 0.2 s later and awaited 1.0 s.
   `async def`: answered in 0.001 s, machine leaves `hold`. `def`: probe times out at
   **1.007 s / 1.003 s**, machine still in `hold`, at `service_pool_size` **1 and 4** — which
   rules out executor starvation. Scale: `r1_d7_1_both_service_kinds.py` — 10/10 `def`
   machines unresponsive with a **16 398-event backlog**, `async def` draining to 0.
2. **No cancellation on state exit; the completion lands in an exited configuration.**
   `contracts/repro/cv_6db_01_def_invoke_not_cancelled.py` → exit 0 with an explicit `BUG:`
   line. `async` cell `PASS` (`after_cancel=['m.cancelled']`, `cursor=0`); `def` cell `FAIL`
   (`after_cancel=['m.done']`, `cursor=4242`). The exiting transition is silently discarded
   and the receipt is success-shaped. Also `h5_cancel.py` CANCEL-def, `h7_conc.py`
   CONC-def-task/seq on real B12, `h6_block.py` BLOCK-def.
3. **Not unwound by rollback / transient abandonment.**
   `contracts/kc_inline_svc.py` — run `async` → case B `PASS` (`service_calls: []`); run
   `def` → case B `FAIL` (`service_calls: ["submit_child"]`) with the identical
   `RuntimeError: entry action failed` and `rolling back to the pre-transition configuration`
   log in both. Configuration and context *are* correctly rolled back, so every state-based
   assertion still passes — **only the side effect leaks**, which is exactly the class of
   defect a state-machine test suite cannot see. Also on `SyncInterpreter`
   (`ke_syncinline.py`, both cases FAIL) and as 3 FAILs in `k7_invariants.py` `def`
   (B6 INV-c, B6 rollback, B7 rollback).
4. **No cancel window for a sequential caller.** `send(wait=True)` on the `def` lane does not
   return until `onDone` is applied (0.607 s for a 0.6 s service).

**Classification.** LIBRARY-DEFECT. Not a regression — #116 predates this window and #179's
completion-lane work unified *charging*, not cancellation — but it is materially worse than
round 7 recorded, because round 7 attributed symptom 1 to the wrong mechanism.

**OMS severity: Blocker.** For an order-management system this means: while `place_order`
runs, `USER_CANCEL` and `KILL_SWITCH` are not processed at all (symptom 1); if the state is
exited anyway the order is not cancelled and its fill lands in a dead configuration
(symptom 2); and a failing telemetry action in the same entry set submits a **real order**
that the rollback then pretends never happened (symptom 3 — 22 live `place_order` submissions
vs 2 in the B1 measurements). The invariant suite reports `async` 52/52 vs `def` 49/52.

**Fix direction (upstream).** Either run non-coroutine services off the loop thread with a
real cancellation token and gate their completion on the invoking state still being active
(losing #116's ordering guarantee), or refuse non-coroutine services on `Interpreter`
outright, as `SyncInterpreter` already refuses coroutines. The current middle position gives
sync-engine ordering with none of the async engine's safety.

**Wrapper obligation (W-01, upgraded to HARD PREREQUISITE).** The wrapper must **reject at
build time** any service implementation that is not a coroutine function, with an assertion
over every registered service in `MachineLogic` before `create_machine`. This is no longer a
style rule; without it the async engine has no kill switch, no cancel path, and no rollback
integrity. With it enforced, all four symptoms are unreachable.

---

## 2. High

### R8-03 (High, LIBRARY-DEFECT) — `start(children_timeout=)` is a no-op against a non-yielding child entry action, and it is an aggregate bound

**Merges** D8-concurrency-3, D8-persistence-3, M-4.

**Root cause.** #181 implements the bound as `asyncio.wait_for(self._await_actor_bringups(...), timeout)` (`interpreter.py:601`), and inside it `await asyncio.wait(pending, timeout=...)` (:2753–2757). `wait_for`/`wait` can only pre-empt a task **at an await point**. A bring-up awaits `child_interpreter.start()` (:2973), which runs the child's entry actions; a plain `def` entry action executes on the loop thread and yields nothing, so the timeout callback is never scheduled until the work is already done. Children are brought up **serially**, hence exact N × duration scaling. Same family as R8-02: an `await` on user code that never yields.

**Reproduced fresh.** `concurrency/r6b_children_timeout_def_noop.py` → `result: FAIL`. `children_timeout=0.2`, 3 s entry action:

| entry kind | children | start_seconds | bounded | overrun | WARNING |
|---|---|---|---|---|---|
| `async def` | 1 / 5 | 0.21 / 0.20 | yes | — | logged |
| `def` | 1 | **3.00** | no | **15×** | **not logged** |
| `def` | 5 | **15.01** | no | **75×** | **not logged** |

At scale (`r6_children_timeout_50_slow.py`): 50 children × 1 s, `children_timeout=0.2` → `async def` start 0.213 s with WARNING and 50 registered; `def` start **50.034 s**, no warning, identical to `children_timeout=None`. Confirmed independently by `persistence/r5_children_timeout_def.py` (20 children × 100 ms → 2.02 s at bounds 0.05, 0.2 **and** 1.0, elapsed independent of the bound, 0 warnings).

**Three distinct defects, one fix site.** (a) The bound does not bind on the `def` lane. (b) **The WARNING is emitted on the same timeout path**, so a `def` entry action suppresses the *observability* as well — the operator sees a clean, silent 50 s start. (c) Separately (M-4, `probes/main-6db65d8/m5_children_timeout_aggregate.py`), even on the `async def` lane the bound is an **aggregate deadline across all children**, not a per-child bound as the docstring implies: with N slow children the last ones get no budget at all.

**OMS severity: High.** Startup is where an OMS attaches to venues. A `def` entry action anywhere in the child tree converts a declared 2 s bounded start into an unbounded one with no diagnostic, and the aggregate semantics mean a documented per-child guarantee silently does not exist. Not a blocker only because it is confined to the `start()` window and is fully mitigated by the R8-02 wrapper rule plus a `def`-free entry-action rule.

**Wrapper obligation.** Extend the R8-02 build-time check to child entry actions, and measure `start()` wall time against the declared `children_timeout` independently rather than trusting the WARNING.

---

### R8-04 (High, LIBRARY-DEFECT) — `always` → invoking child → `onDone` re-entry starves the inbox permanently, all health signals green

**Merges** D8-fuzz-3.

**Root cause.** `_next_event()` (:1573–1583) drains the priority lane and the transient/`always` chain ahead of the inbox with **no fairness bound**, combined with the chain-end reset at :1725–1735, which clears `_raise_depth` on every lap because by the time the test runs each completion-driven `always` re-entry "raised nothing, armed nothing, owes nothing". The budget therefore never trips and no drop hook ever fires.

**Reproduced fresh.** `fuzz/r18_ext_starvation_repro.py` (14-line config, with both necessity ablations):

```
SYNC engine, plain def:  EXT sent=500 APPLIED=500 (100.0%)
plain def                EXT sent=500 received=500 APPLIED=490 (98.0%)  inbox=450 priority=1
async def                EXT sent=500 received=135 APPLIED=1  (0.2%)   inbox=499 priority=365
ablation A (no `always`): both kinds 500/500, queues drained to 0
ablation B (no `invoke`): both kinds 1/500, last_error=RunawayChainError
```

Both ablations are necessary: without the `always` the shape is clean; without the `invoke` the same starvation occurs but **is** reported (`RunawayChainError`). Only the combination starves *silently*. Permanence confirmed by `fuzz/r19_starvation_drain.py`: producer stopped, after 10 s idle `applied=1/500`, `inbox=499`, `priority=372`, `cpu=7.0 s` (70% of one core) — STUCK, not slow.

Throughout: `status=running`, `last_error=None`, `drops={}`. Every programmatic health signal is green while 499 of 500 external events sit unprocessed for ever.

**OMS severity: High.** A permanently wedged machine that reports healthy, burning a core. The sync engine is clean (500/500), so this is async-engine specific. Below blocker only because the shape is statically detectable in our own charts.

**Wrapper obligation.** Forbid the shape in the catalogue: an `always` whose target descends into an invoking child whose `onDone` re-enters the ancestor. Add a liveness watchdog on inbox depth — depth must not be monotonically non-decreasing across a window while `status == "running"`; `last_error` and `on_event_dropped` cannot be relied on here.

---

### R8-05 (High, LIBRARY-DEFECT) — `DoneEvent` / `AfterEvent` are freely constructible and exempt from `strict` / `onUnhandled`

**Merges** D8-persistence-1.

**Root cause (source read, `events.py`).** #85/#180 put the provenance marker on the `Event` dataclass only — `_provenance: Any = field(default=None, init=False, ...)` plus a read-only `system` property (:125–135). `DoneEvent` (:145) and `AfterEvent` (:453) are plain `NamedTuple`s. The hardening was applied to the class users were *expected* to construct and omitted from the two classes that **assert engine authorship**.

**Reproduced fresh.** `persistence/r10_doneevent_forgery.py` → `VERDICT: FAIL`, 6 failures, both service kinds. Surface check:

```
DoneEvent   has .system=False has ._provenance=False type=tuple
AfterEvent  has .system=False has ._provenance=False type=tuple
Event       has .system=True  has ._provenance=True  type=object
```

Behaviour (the service hangs, so the `onDone` target is unreachable by any other route):

```
[async] control: Event('done.invoke.k')    ['sec.a'] -> ['sec.a']       status=error    <- correctly killed
[async] FORGED DoneEvent('done.invoke.k')  ['sec.a'] -> ['sec.done_']   status=running  <- DROVE the onDone
[async] FORGED AfterEvent                  ['sec.a'] -> ['sec.a']       status=running  <- swallowed by strict
[async] FORGED DoneEvent(no such actor)    ['sec.a'] -> ['sec.a']       status=running  <- swallowed by strict
```

The identical type name sent as a plain `Event` errors the machine; sent as a `DoneEvent` it transitions the machine as if the still-running service had returned.

**OMS severity: High.** Any code path that can hand the interpreter an event — a plugin, a transport adapter, a replay tool, a test double left in a build — can declare an order filled while the real submission is still in flight, and `strict` / `onUnhandled: "error"`, the two mechanisms specifically relied on to catch forged control traffic, are both blind to it. Not a blocker because it is not reachable from outside the process and our wrapper owns every send site; it is a defence-in-depth failure, not an open door.

**Fix direction.** Give `DoneEvent`/`AfterEvent` the same `_provenance` field and `system` property (or make them `Event` subclasses), and make `is_known_event()` / the `strict` and `onUnhandled` paths test `system` rather than special-casing by type name.

**Wrapper obligation.** The wrapper's send surface must accept only `Event` and only whitelisted type names; never re-export `DoneEvent` / `AfterEvent`.

---

### R8-06 (High, LIBRARY-DEFECT) — #185's drift check is bypassable by version downgrade

**Merges** D8-persistence-2.

**Root cause (source read, `persistence.py:312–336`).**

```python
snap_hash = snapshot.get("machine_hash")
versioned = bool(version)
if snap_hash is None:
    if not versioned:
        return  # v0: nothing to check against, by design
    raise SnapshotDriftError(...)
```

#185 moved the bypass discriminator from the `machine_hash` field's *presence* to the *declared version*. Both fields live in the same JSON object and are edited by the same hand, so the bypass survives verbatim as a **downgrade**.

**Reproduced fresh.** `persistence/r3_version_downgrade.py`:

```
snapshot version=2 hash='510abea7b8ae24b2'
machine A hash=510abea7b8ae24b2   machine B hash=bf69643ef9e9a900
CONTROL intact                       -> SnapshotDriftError (correct)
version=0 + hash removed             ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']
version key removed + hash removed   ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']
version=0 + hash=None                ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']
```

`JUMP` is an event the snapshotting machine never declared; after restore it moves the machine to `m.c`. All under the **default** `verify_machine_hash=True`. Matrix context in `persistence/r2_readside_matrix.py` part 1 (32 version × hash × target cells).

**OMS severity: High.** Restoring OMS state from a blob a deployed-code change has drifted away from is a position-corruption event, and the check advertised to prevent it is defeated by a two-key edit. Below blocker because it requires the snapshot store itself to be attacker- or bug-reachable, which is inside our trust boundary.

**Fix direction.** Refuse an unversioned/`version: 0` payload that carries no `machine_hash` whenever the *machine* is versioned or a hash is computable — the v0 bypass should be keyed on the machine's own capability, not on a field the blob supplies. At minimum, make the bypass require the explicit `verify_machine_hash=False` opt-out, which already exists.

**Wrapper obligation.** Verify `version` and `machine_hash` in our own envelope, outside the blob (MAC or side-channel), before calling restore; refuse any blob whose declared version is lower than the writer's.

---

## 3. Medium

### R8-07 (Medium, LIBRARY-DEFECT) — `send(wait=True)` can resolve over a torn read (`current_state_ids == []`), success-shaped

**Merges** D8-fuzz-1. Residue of D7-fuzz-2.

**Root cause.** The step's chain-end test (`interpreter.py:1725–1735`) asks "raised nothing, armed nothing, owes nothing, queues empty" and **does not include** "the configuration has at least one leaf". The completion published by `_publish_completion` (:2683) can land between the exit set and the entry set of an `always` chain, so the caller's receipt resolves at an instant when the machine has no active leaf.

**Reproduced fresh.** `fuzz/r3_empty_repro.py` (284-byte config, shrunk by `r2_torn_shrink.py` from this run's own f2 capture):

```
sync engine, plain def:              [['m.a.a.a'] x5]           — never empty
async engine, async def svc: EMPTY 14/15   ok=True err=None status=running
                                     snapshot=REFUSED:SnapshotMidStepError   +500ms ids=['m.a.c']
async engine, plain def svc: EMPTY 0/15
```

(The prior recorded rate was 7/15; this run shows 14/15 — the window is wider than filed, not narrower.) The read heals in ~500 ms, and the snapshot API *correctly* refuses at the same instant — so the library knows it is mid-step; only the public `current_state_ids` read and the receipt do not.

**OMS severity: Medium.** `await send(...)` returning `ok=True, err=None, status=running` is the OMS's "the order step completed" signal; reading `current_state_ids` immediately after is the natural next line and yields `[]`, which a router would read as "no machine / terminated". No state is corrupted and it heals, so this is a transient false read on the observation surface, not a state defect. `async def` only — the service kind we mandate — which is why it is not lower.

**Wrapper obligation.** Never derive control flow from `current_state_ids` immediately after a receipt resolves; treat `[]` on a `status == "running"` machine as "unknown, re-read", never as terminal.

---

### R8-08 (Medium, LIBRARY-DEFECT) — #186's `configuration`/`state_ids` agreement rule is one-sided

**Merges** D8-persistence-5, D8-fuzz-4, OBS-state-ids-empty.

**Root cause (source read, `persistence.py:214–228`).**

```python
configuration = snapshot.get("configuration")
if configuration is not None:
    leaves = set(snapshot["state_ids"]); full = set(configuration)
    if leaves and not full: fail(...)
    missing = leaves - full
    if missing: fail(...)
```

The whole check is guarded by `configuration is not None`, and the predicate asks only "is every leaf of `state_ids` present in `configuration`?" — **vacuously true when `state_ids` is empty**. `full - leaves` is never examined, and an empty `state_ids` on a *running* blob is not itself refused. So whichever field survives decides alone.

**Reproduced fresh.** `fuzz/r10_186_asymmetry.py` — 3 of 9 mutations accepted despite disagreement:

```
state_ids=[]  (config says m.b.c)        -> loaded:['m.b.c']            <== ACCEPTED
configuration=None (state_ids m.b.c)     -> loaded:['m.b.c']            <== ACCEPTED
configuration missing (state_ids m.b.c)  -> loaded:['m.b.c']            <== ACCEPTED
state_ids missing                        -> refused:SnapshotCorruptError
CROSS: config@d + state_ids@c            -> refused:SnapshotCorruptError
CROSS: config@c + state_ids@d            -> refused:SnapshotCorruptError
BOTH emptied                             -> refused:SnapshotCorruptError
state_ids=[] AND configuration=None      -> refused:SnapshotCorruptError
```

And with a *forged* configuration beside an emptied `state_ids` (`persistence/r3_version_downgrade.py` final block, `r2_readside_matrix.py` part 2): `ACCEPTED -> leaves=['m.b']` where the snapshot said `m.a` — i.e. the one-sidedness does relocate the machine, which the symmetric case correctly refuses.

**OMS severity: Medium.** The cross-disagreement cases — the realistic corruption shapes — are all correctly refused, and no torn state results; this is an integrity-check weakness that requires a deliberate single-field edit. It is promoted above the "observation only" filing in `OBS-state-ids-empty` because the forged-configuration variant **does** reach a state the snapshot never named.

**Wrapper obligation.** Assert both fields are present and non-empty on a `running` blob, and that the restored `current_state_ids` equals what we wrote, before trusting the restore.

---

### R8-09 (Medium, LIBRARY-DEFECT) — `get_persisted_snapshot()` from `on_interpreter_start` returns a torn blob, both engines

**Merges** D8-concurrency-4.

**Root cause.** #182 sets `_processing` for the whole `start()` descent, so a snapshot from an *initial entry action* is now correctly refused. `on_interpreter_start` fires **outside** that window: `status` has already been flipped to `"running"` but `_active_state_nodes` is still empty, so the write-side #102 leafless check does not apply and a blob is produced. Write side and read side now disagree: `base_interpreter.py:1391` (refusal site / in-flight test) and :1443–1456 (blob builder, no "configuration is empty" guard) vs :1747–1756 (read-side guard that rejects exactly this blob).

**Reproduced fresh.** `concurrency/r3b_on_start_torn_minimal.py` → `result: FAIL`, 3/3 cells torn (`status=running`, `state_ids=[]`, `configuration=[]`, while the healthy live snapshot reads `['r3b.a']`/`['r3b.b']`). Property evidence (`r3_hook_snapshot_property_both_kinds.py --n=300`): **600 of 600** `on_interpreter_start` returns torn; **0 of 1 356** returns from `on_transition` / `on_event_received` / `on_action_execute` are torn, with 2 323 action-hook refusals — i.e. #187 is working and D7-concurrency-2 is genuinely fixed.

**Blast radius bounded.** Restoring the torn blob is refused (`SnapshotCorruptError`: "status is 'running' but the configuration is empty"; the sync cell shows `refused:AttributeError`). So the damage is a persisted artefact that is *guaranteed unusable*, not a silent restore into a wrong state.

**OMS severity: Medium.** A checkpointing plugin that snapshots on start writes a garbage checkpoint 100% of the time and only discovers it at recovery — precisely when it is needed. Unlike D7-concurrency-2 this is **both engines**, so the sync engine cannot serve as a cross-engine reference.

**Fix direction.** Either fire `on_interpreter_start` inside the `_processing` window (making the refusal consistent), or add the read side's "running with empty configuration" guard to the blob builder so the write side refuses what the read side will.

**Wrapper obligation.** Never snapshot from `on_interpreter_start`; validate every produced blob with the read-side guard before persisting it.

---

### R8-10 (Medium, LIBRARY-DEFECT) — `_chain_owed` leaks on a `BaseException` service exit and is settled by a bare counter

**Merges** M-2, M-3.

**Root cause (source read).** `_owe_completion` (:~2658) claims every coroutine service task ends in either a completion published through `_publish_completion` (which settles as it charges) or cancellation (settled by `_settle_if_cancelled`). `_invoke_service_task` (:~2470) catches `asyncio.CancelledError` (re-raised) and `Exception`. A `BaseException` that is neither — `SystemExit`, `KeyboardInterrupt`, `GeneratorExit`, a `BaseException`-derived timeout from a third-party library — propagates out. The task then finishes **not cancelled** and **without publishing**, so both of the only two decrement sites are skipped.

Separately (M-3), `_deliver_priority` (:2384) decrements `_chain_owed` on *every* `engine_completion=True` delivery if it is non-zero, including completions that never registered a debt — a bare counter, not matched to the debt that armed it.

**Reproduced fresh.** `probes/main-6db65d8/m2_chain_owed_leak_baseexception.py` — arm/disarm a state whose `async def` service raises a bare `BaseException`, five laps:

```
lap 0: owed=1 depth=0 state={'p.off'}
...
lap 4: owed=5 depth=0 state={'p.off'}
```

Monotonic, one per lap, machine idle in `off` between laps. The neighbouring **benign** case is genuinely handled (`m3_chain_owed_never_completing.py`: `after ARM owed=1`, `after 10 PING owed=1`, `after stop owed=0`) — the leak is specific to the `BaseException` exit.

**Consequence and why it is Medium, not High.** `_chain_owed` is never read as a *magnitude* — the loop compares `self._chain_owed == owed_before` (:~1730) — so the leak does not by itself trip the budget. The damage is the opposite: a permanently non-zero counter is still decremented by every later engine completion (M-3), converting the leak into **mis-accounting on unrelated chains**, i.e. a chain that should have ended is held open or vice versa. It is an `int`, so this is accounting corruption, not memory exhaustion, and there is no bound and no reset (`_raise_depth = 0` paths do not clear `_chain_owed`).

**Fix direction.** Settle from the task's done-callback on *any* terminal outcome that did not publish (a per-task `published` flag), and key the settle to the specific debt rather than decrementing a shared counter.

---

### R8-11 (Medium, LIBRARY-DEFECT) — #179's service-kind parity claim is false for `invoke` ping-pong and rollback+`onDone`

**Merges** D8-persistence-4, CV-6DB-01(low).

**The claim (CHANGELOG [Unreleased], #179):** *"Both service kinds now trip at the same lap count as the sync engine."*

**Reproduced fresh.** `persistence/r13_chain_parity_min.py` → `VERDICT: FAIL`, three explicit failures — one character differs between the two async-engine rows:

```
- invoke_pingpong: `def` trips, `async def` does not (#179)
- invoke_pingpong: sync=28 vs async-engine def=27 laps
- rollback_ondone: `def` trips, `async def` does not (#179)
```

Systematic view, `persistence/r12_livelock_fuzz.py 500 5` (500 fuzzed configs): `invoke_pingpong` `def` → TRIP 50/50, `async` → running 50/50; `rollback_ondone` `def` → TRIP 50/50, `async` → running 50/50; `always_cycle` and `sendto_selfloop` have **full parity**. 50 lap-count mismatches, all `invoke_pingpong` (async=27 vs sync=28). **0 HANGS, 0 SILENT trips.**

The two diverging shapes are exactly the two the CHANGELOG lists as *reopened* (#167, #168). Related: `CV-6DB-01`(low) — one machine, `maxIterations=20`, `actionErrorPolicy=rollback`, `invoke.onDone` action raises: async engine = 22 service calls + `RunawayChainError`; sync engine = **2** calls, `last_error=RuntimeError('boom')` only, and `y7_syncquiesce.py` shows the sync stop is terminal, not deferred (6 NUDGEs leave the call count at 2).

**Demoted from the fuzzer's implied High to Medium** because `r13` establishes the async lane **is bounded** (it reaches the same 27 laps then stops — `still_turning=False` measured across a further second of wall clock) and the trip **is** eventually observable via `on_event_dropped` (`drops=1`). The defect is the **timing and reporting of the signal**, not an unbounded livelock: #179's *bound* is real on both service kinds; its *parity* claim is not.

**OMS severity: Medium.** Same chart, same declared budget, different number of **real side effects** — for B1 that is 22 live `place_order` submissions versus 2 — and different observability (`RunawayChainError` on one engine, the raw action error on the other). A budget you cannot use to reason about side-effect count is a budget you cannot size.

**Wrapper obligation.** Do not treat `maxIterations` as a side-effect bound; bound side effects at the action level (idempotency key + counter), and never assume sync/async parity when validating a chart on the sync engine.

---

### R8-12 (Medium, DESIGN-CONSTRAINT → NEEDS-WRAPPER) — a chain-budget trip never reaches the caller's receipt or the `on_error` hook

**Merges** CV-6DB-02, LIB-R6-01, W-02. Classified **DESIGN-CONSTRAINT**, not LIBRARY-DEFECT: the runaway-chain cut is a machine-level safety action, and the library does surface it — on `interpreter.last_error`, `on_event_dropped(reason="chain_budget")`, `on_transition_failed` and `on_action_error`. It is filed because the *caller-facing* surface is silently successful, which is a trap, not because the engine is wrong.

**Reproduced.** `contracts/y2_observe.py` / `y3_parity.py`: `await interpreter.send("GO")` returns `None` (not a receipt) on every chain-budget trip at `maxIterations` 20/100/1000, **both** service styles; plugin `on_error` fires **0** times.

A worse variant is `LIB-R6-01` (`contracts/h1_r601.py`, `h2_obs.py`): the rollback/re-invoke storm is now genuinely bounded (~119–167 invocations in 0.186 s on both lanes, tracking `maxIterations`; it was 131 313 subscribe_streams in 20 s forever at `221ce7c` — a real round-7 improvement), but the bound is reached by a path that reports **nothing structured**: `receipt.changed=True`, `receipt.error=None`, `receipt.denied=False`, `status='running'`, `on_event_dropped` **0 drops**, and `last_error` is the action's `RuntimeError` rewritten each lap rather than `RunawayChainError`. Only the WARNING/ERROR log shows it (304 async / 238 def records). This is asymmetric with the #166 `always` settle bound, which *does* set `last_error=RunawayChainError` and fire `on_event_dropped` for the same user-visible symptom — so the reporting contract is inconsistent across two bounds of the same kind.

**OMS severity: Medium.** An OMS that awaits `send()` and branches on the receipt concludes the order step succeeded when the engine has just cut the chain. Not higher because every trip *is* observable on at least one channel, and the wrapper rule below closes it completely.

**Wrapper obligation (W-02, hard).** No fire-and-forget `send()` on control/order paths — `wait=False` discards the `Receipt` carrying guard-raise errors, `onUnhandled` kills, `deferred` and `denied` (`contracts/k9_wait.py`). After every `await`, read `interpreter.last_error` and subscribe to `on_event_dropped(reason="chain_budget")`; for rollback-storm shapes, also watch the log channel, since neither of the two programmatic channels fires there.

---

## 4. Low

### R8-13 (Low, LIBRARY-DEFECT) — call-site `QueueOverflowError` refusals fire no `on_event_dropped`; hook coverage collapsed to 0.3%

**Merges** D8-concurrency-5. Re-filed from D7-concurrency-3 — unchanged in mechanism, ~334× worse in measurement.

**Root cause.** #157 added the hook to the **loop-side** refusal path only (`interpreter.py:1136–1137`). The optimistic call-site `qsize()` check in `send_threadsafe` raises *before* anything is queued and never reaches that path, so it fires no hook.

**Reproduced fresh.** `concurrency/r9_observability_matrix.py --only=qf` (6 threads, 1 s, depth-4 inbox, `OverflowPolicy.RAISE`) → `result: FAIL`, `["queue_full", "call-site refusals fire NO hook"]`, `callsite_hooked: false`. Round 7 measured 6 021 call-site / 6 066 loop-side = **50.2%** hook coverage; round 8 measures ~85 k call-site refusals against a few hundred loop-side ones — coverage **0.3%**. What changed is not the mechanism but the ratio: the call-site check now wins the race far more often on this build (the loop turns less frequently between refusals).

**OMS severity: Low.** The call site **does** raise, so no caller loses an event silently — backpressure is correct and the caller is told. The defect is purely that the *aggregate* shed-rate metric, which an operator would use to size the inbox, now sees 0.3% of the truth. Exactly-once on the loop-side path is confirmed (255 refusals → 255 hooks).

**Wrapper obligation.** Count `QueueOverflowError` at our own send wrapper; do not use `on_event_dropped(reason="queue_full")` as the shed-rate metric.

---

### R8-14 (Low, LIBRARY-DEFECT) — `SnapshotMidStepError` from an invoked child's entry action reports `child=False`

**Merges** D8-fuzz-5.

**Root cause.** #183 specifies `SnapshotMidStepError(child=True)` for a child caught mid-step, and the site that sets it is `base_interpreter.py:1423`. The path this probe takes refuses **earlier**, at the root in-flight check added by #182/#187, which does not set the discriminator.

**Reproduced fresh.** `fuzz/r14_observability.py` section C: both service kinds report `REFUSED child=False` when snapshotting the parent from inside an invoked child machine's entry action.

**OMS severity: Low.** The refusal itself is **correct** — no torn blob is produced — only the discriminator is wrong, so this is diagnostic fidelity, not safety. Filed with the caveat that no case where `child=True` *is* observed could be constructed, so a probe artefact is not fully excluded.

---

### R8-15 (Low, LIBRARY-DEFECT) — the validator accepts unknown top-level config keys silently

**Merges** WRAP-unknown-keys, WRAP-spawnBlockingTimeout. Re-classified from NEEDS-WRAPPER to **LIBRARY-DEFECT** (with a wrapper mitigation): silently accepting a key it does not implement is a library contract failure, not merely something our wrapper forgot to check.

**Reproduced.** `contracts/g3_build.py`:

- `P2_typo_keys`: a typo'd `onUnhandledd` leaves the default `onUnhandled` policy in place with **no diagnostic**. By contrast a bad *value* for a *known* key raises `InvalidConfigError` cleanly — so the validator is strict on values and silent on names.
- All five machines declare `spawnBlockingTimeout: 5000`; `policy_honoured` reports **ABSENT**. The key is parsed and dropped — no corresponding attribute is set on the machine.

**OMS severity: Low** in isolation, but it is the **amplifier** for everything else in this register: every wrapper mitigation named above is expressed as a config key, and a typo in any of them downgrades silently to the default. A misspelled `onUnhandled` or `maxIterations` is exactly how R8-01's and R8-12's mitigations would fail in production.

**Wrapper obligation.** Whitelist-check top-level config keys before `create_machine`, and **assert the attribute exists on the built machine** for every policy we believe we set, rather than trusting the JSON.

---

## 5. Non-findings: verified clean this round

| Candidate | Disposition |
|---|---|
| D8-security-1 | **Confirmed status change, not a finding.** `security/attack_livelock_config_fuzz.py 120` → sync 120/120 settled, async 120/120 settled, 0 RUNAWAY (was 58/120 RUNAWAY at `221ce7c`). The async-engine invoke-cycle livelock D7-fuzz-1 is **fixed**, most likely by #179's `_publish_completion` routing. Recorded as a round-7 win. |
| `prior-defects` | 8 prior soak-track defects/checks (D-soak-1/2, D5-soak-1, #145, #166–#168, #172/#157, #173-def, #173-async-new) all remain FIXED/PASS at `6db65d8`. |
| `chain-owed` | `_chain_owed` does **not** hang `stop()` with 100 concurrent permanently in-flight `async def` services. Passed. (Note this is the *benign* neighbour of R8-10, which is `BaseException`-specific.) |
| `priority-no-drop` / `PRIO-180` | External priority sends on **real contract machines** (B11/B13/B14/B15 × both lanes, 60 sends each, issued to land mid-macrostep): 240/240 clean, zero `chain_budget` drops. **This does not contradict R8-01** — the shed half of R8-01 requires a *self-generated chain already over budget* at the moment the external event is at the FIFO head, which these machines' `maxIterations` and shapes do not produce. The B18 kill-switch lane is safe *for these charts*; it is not safe in general. |
| LIB-01 | `onUnhandled='error'` kill now lands on the sender's receipt — **fixed by #189**. Confirmed. The two scenarios still reporting FAIL (`B13-unh-2`, `B14-unh`) are **stale assertions** written against the broken behaviour: they assert the interpreter survives, but dying is the documented contract. Ours to update. |
| LIB-R6-strict | A `"*"` handler no longer defeats config-level `strict` — **fixed by #190**. `g3_wildcard.py` 3/3 PASS; B13 went 10/12 → 12/12. |
| M-5 … M-9 | Clean per `47-r8-diff-review.md`: late `sendTo` to a not-yet-registered child does not drop (M-5); in-flight flag vs plugin hooks has parity on both engines and refuses no legitimate snapshot (M-6); the child mid-step wait is bounded at 0.5 s and cannot hang on a livelocked child (M-7); #185/#186 behave as specified *within the scope they check* (M-8 — R8-06/R8-08 are about the scope itself); #190's declaration-vs-dispatch split leaves dispatch unchanged (M-9). |

## 6. Non-findings: HARNESS-ERROR

| Candidate | Disposition |
|---|---|
| `OUR-CONTRACT-01` | **HARNESS-ERROR.** Sync-parity legs set `stub.sync = True` but left `svc_style='async'`, handing `SyncInterpreter` coroutine services → `NotSupportedError`, producing 3 spurious FAILs. The sync engine refusing coroutines is **correct**. Fixed by setting `svc_style='def'` on sync legs. Rule: every sync-parity leg must pin `svc_style='def'`. |
| `45-r8-regression.md` deltas `154`, `158` | **HARNESS-ERROR (stale fixture), not a regression.** Both scripts hand-build a `version: N` blob with no `machine_hash` — valid at `221ce7c`, correctly refused at `6db65d8` by #185. Re-reproduced directly: `SnapshotDriftError` in both. `158`'s sub-case `[B]` (direct `restore_event()` type validation) still PASSes, confirming the underlying #158 fix is intact. **Action (ours):** add `machine_hash` to both scripts' blobs. Note this is the same #185 machinery that R8-06 shows is bypassable — it is strict against honest stale fixtures and permissive against a downgrade edit. |
| `167:verifyM4` FAIL ×5/5 | Deterministic, not flaky; matches the recorded round-7 PARTIAL. Superseded in substance by **R8-11**, which is the same `#167/#168` shape re-measured with both service kinds. |

**Regression sweep summary.** Zero true PASS→FAIL regressions at the gate level; 17 blocking-check FAILs all pre-existing and already triaged; `PROBE-01` 16/20 and `PROBE-03` 13/17 with identical failing cells ×5 runs (deterministic). **However**, the gate's clean bill is not the whole picture: R8-01 and R8-10 are genuine *behavioural* regressions introduced by this diff (#180 and #179 respectively) that no gate check and none of the 37 new `test_round7_findings.py` tests detect. The gate does not cover the priority lane's self-send path or `BaseException` service exits.

## 7. Non-findings: OUR-CONTRACT-DEFECT (catalogue fixes, not library)

These are real defects, but in `docs/plan/28-statechart-catalogue.md` and our corrected machine JSON — the library behaves correctly in every case. Listed for completeness; they belong on the contract backlog, not the upstream issue tracker.

| ID | Sev | Summary |
|---|---|---|
| C-04 | Blocker (ours) | B16 elevation outlives the session on 3 of 4 end events (`LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` exit the auth region only), and elevation can be acquired *after* revocation. Fix: declare the elevation-region exit on all four, and refuse step-up in `revoked`. |
| C-07b | Blocker (ours) | B18's `onUnhandled: "error"` turns an ordinary guard-denied `RELEASE` into a dead kill switch (`denied=True` **and** `UnhandledEventError`, `status='error'`). #189 makes the kill land correctly — the **policy choice is the defect**. Fix: do not use `onUnhandled:"error"` on the control path. |
| C-06 | High (ours) | B19 `stale_lockout` declares only `RECONNECTED`; `OPERATOR_RESOLVED` and `SWEEP_DUE` are deferred, so operator resolution queues behind the lockout. |
| W-03 (defer) | High (ours) | B17: `onUnhandled:defer` replays `ENABLE_REQUESTED` verbatim against evidence that post-dates the decision. Library correct; the contract needs an authorisation-freshness stamp re-validated at replay time. |
| CD-01 | High (ours) | The kill switch is deferrable as catalogued: B6 `submitting_slice` and B9 `evaluating` declare no `USER_CANCEL`/`KILL_SWITCH` handler, so under `onUnhandled:defer` the kill is held for the full in-flight service (~1.46 s vs ~1 ms with the handler) and `priority=True` does not help — `priority` orders the **inbox**, `defer` is decided by the **configuration**. Nothing is lost. Fix: declare the kill/cancel handler on **every** invoking state. |
| OUR-B11-01 | High (ours) | `recording.degraded` has no `STREAM_UNHEALTHY` handler: a second failing stream is deferred indefinitely and the next `STREAM_HEALTHY` flaps `degraded→recording→degraded`. |
| OUR-B14-01 | High (ours) | INV-B14-d's "bounded buffer" is prose only — 1000 DELTAs buffer 1:1, no `maxBuffer` anywhere in the JSON. |
| OUR-B14-02 / OUR-B15-01 | High (ours) | Fallible telemetry sharing an atomic entry set with a safety transition under `actionErrorPolicy=rollback` cancels the desync / cancels the liquidation, **durably** (it survives a snapshot). Fix: move telemetry to a post-settle observer. |
| C-05 | Low (ours) | B16 re-elevation while already elevated writes no step-up audit record (self-transition within `elevated` not declared) — INV-B16-c partially unmet. |
| C-01 | Low (ours) | Missing action/guard/service implementations are not a build error: `create_machine` succeeds with a bare `MachineLogic()`. The contract needs its own completeness check. (Adjacent to R8-15 — both are "the library validates less than we assumed".) |
| C-07 | Low (ours) | Catalogue-promised `halted` states absent from all five B16–B20 JSON files. Doc/JSON drift, carried unchanged. |

---

## 8. Canonical LIBRARY-DEFECT list (upstream-reportable)

13 of the 15 canonical findings are LIBRARY-DEFECTs. R8-12 is a DESIGN-CONSTRAINT; every entry in §7 is ours.

| ID | Sev | One line |
|---|---|---|
| R8-01 | Blocker | Priority lane charges by provenance, sheds by position — self-sent priority events livelock silently and unboundedly; external priority events are destroyed as `chain_budget`. Regression (#180). |
| R8-02 | Blocker | A plain `def` service runs inline on the loop thread: blocks all event processing, is never cancelled on state exit, is not unwound by rollback. |
| R8-03 | High | `start(children_timeout=)` does not bound a non-yielding child entry action and suppresses its own WARNING; the bound is aggregate, not per child. |
| R8-04 | High | `always` → invoking child → `onDone` re-entry starves the inbox permanently with every health signal green. |
| R8-05 | High | `DoneEvent`/`AfterEvent` carry no provenance marker and are exempt from `strict`/`onUnhandled`; a forged completion drives a real `onDone`. |
| R8-06 | High | #185's drift check is bypassable by version downgrade under the default `verify_machine_hash=True`. |
| R8-07 | Medium | `send(wait=True)` can resolve success-shaped at an instant when `current_state_ids == []`. |
| R8-08 | Medium | #186's `configuration`/`state_ids` agreement rule is one-sided; an emptied `state_ids` lets a forged `configuration` relocate the machine. |
| R8-09 | Medium | `get_persisted_snapshot()` from `on_interpreter_start` returns a torn blob, 600/600, both engines. |
| R8-10 | Medium | `_chain_owed` leaks permanently on a `BaseException` service exit and is settled by a bare counter. Regression (#179). |
| R8-11 | Medium | #179's service-kind parity claim is false for `invoke` ping-pong and rollback+`onDone`. |
| R8-13 | Low | Call-site `QueueOverflowError` refusals fire no `on_event_dropped`; shed-rate hook coverage 0.3%. |
| R8-14 | Low | `SnapshotMidStepError` from an invoked child's entry action reports `child=False`. |
| R8-15 | Low | Unknown top-level config keys accepted silently; `spawnBlockingTimeout` parsed and dropped. |

**Recommended upstream filing order:** R8-01 and R8-02 first (both blockers, and R8-01 is a regression in the round-7 fix set that its own 37 tests do not catch). R8-03/R8-04 next, as they share R8-02's root shape — *the engine awaits user code that never yields* — and a single upstream decision about non-coroutine user code on the loop thread resolves all three. R8-10 should be filed alongside R8-01 as the second regression in the same fix set.
