# Round-6 Findings Register — main@cec108b

**Commit under test:** `cec108b` ("Merge pull request #164 from basiltt/fix/0.8.1-round5";
unreleased 0.8.1, `__version__` still reports `0.8.0` — key on the commit, not the version).
**Method:** every inbound finding's repro was re-run in a *fresh* process against a clean
venv (120 s cap per script), then the claimed root cause was read back in
`src/xstate_statemachine/` before the finding was allowed to keep its severity.
Findings with the same root-cause line were merged into one canonical `R6-nn`.

**Severity scale (OMS):** *Blocker* = can lose, duplicate or strand an order, or burn the
box, with no signal. *High* = safety property unenforceable or silently wrong; a wrapper
can cover it. *Medium* = correctness/observability gap with a workaround. *Low* = docs,
ergonomics, degenerate inputs. *Info* = confirmation, no action.

## §1 Headline

- **20 canonical library defects** survive triage: **4 Blocker**, **6 High**,
  **5 Medium**, **5 Low**. 33 inbound library-kind items collapsed into these 20.
- **The round-5 fixes are real but were applied to one engine at a time.** Three of the
  four Blockers are async-engine-only faults whose sync counterpart is correct:
  the `always`-chain macrostep never terminates (R6-01, #144 landed on
  `SyncInterpreter` only), `done.invoke.*` is exempt from the chain budget on async and
  charged on sync (R6-02), and `rollback` + `invoke.onDone` re-arms the invoke for ever
  at ~1400 invocations/sec with `status="running"` and `.error is None` (R6-03).
  Each burns a full core silently. **This is the single most important pattern of the
  round: "fixed" means "fixed on the engine the issue was filed against".**
- **`send_threadsafe(internal=…)` is a safety switch with no lock on it** (R6-04,
  Blocker). `internal=True` from any thread routes to the unbounded internal queue and
  skips `OverflowPolicy.RAISE` entirely (5000/5000 accepted against a bound of 2);
  `internal=False` from inside the interpreter's *own* action forces external accounting
  and dodges `maxIterations` (200 self-triggered macrosteps, budget 20, no error).
  Both directions fail open, both from user code, both with no diagnostic.
- **Persistence read-side validation is still porous** (R6-07, R6-08): a dropped
  `machine_hash` silently disables drift checking even under `verify_machine_hash=True`,
  and `configuration` — the second copy of the configuration fact — is never
  cross-validated against `state_ids`, so a snapshot that contradicts itself restores live.
- **The write-side snapshot guard uses the wrong predicate** (R6-06, High): #142
  correctly made legality *exactly one leaf per region*, but inside an **entry action** the
  configuration is perfectly legal while context is half-applied, so a torn snapshot is
  accepted on both engines with `last_transition_ok=True` and no error.
- **Confirmed fixed:** #152 (guard-raise no longer aborts the selection pass — the prior
  round's ship-blocker), #153 `Receipt.denied`, #125/#133/#134 sync parity, #145
  `fail`→stopped, #160 redaction. See §7.
- **Adoption verdict unchanged: DO NOT ADOPT bare.** R6-01/02/03 are silent unbounded
  CPU spins reachable from shapes our catalogue mandates (`rollback` is required by
  CV §1.3b and 4 of 5 machines in one group carry the triggering
  `invoke.onDone` → entry-actions shape). A wrapper cannot see a livelock that reports
  `running`/`error=None`/`last_transition_ok=True`.

## §2 Canonical library defects

All `Repro?` = yes: re-run this round, fresh process, on `cec108b`.

| ID | Sev | Area | Title | Merged from |
|---|---|---|---|---|
| R6-01 | Blocker | async run loop / macrostep termination | `await send(..., wait=True)` never resolves and the loop burns a core when an event re-enters a compound whose `always` descends into a child with a completed `invoke`; #144's chain-budget fix landed on `SyncInterpreter` only | D6-fuzz-1 |
| R6-02 | Blocker | chain budget / engine parity | The async budget check exempts system events (`interpreter.py:1427`), so a two-state invoke cycle is unbounded and silent on async; sync charges them and raises `RunawayChainError` | LD-03 |
| R6-03 | Blocker | `actionErrorPolicy: "rollback"` + `invoke.onDone` | Rollback returns the machine to the invoking state, re-arming the invoke — an unbounded hot re-invocation loop (~1400/s) with `status="running"`, `.error is None`; async only | LIB-R6-01 |
| R6-04 | Blocker | `send_threadsafe(internal=…)` trust boundary | The `internal` flag is caller-supplied and unverified, and fails open in **both** directions: `True` bypasses the bounded inbox and `OverflowPolicy.RAISE`; `False` from the interpreter's own action dodges `maxIterations` | K-1, K-2, D6-security-2 |
| R6-05 | High | `send_threadsafe` backpressure | Under `OverflowPolicy.RAISE` the bound is checked against a stale `qsize()`, so it is bypassed precisely while the loop is busy; excess events are accepted and silently never run | LIB-R6-02 |
| R6-06 | High | persistence / torn snapshot | A snapshot taken inside an **entry action** is accepted and persists a torn state (new leaf + half-applied context); legality was never the right predicate for that window. Both engines | D6-semantics-1 |
| R6-07 | High | persistence / corruption detection | `machine_hash: None` silently disables `from_snapshot()` drift verification even under `verify_machine_hash=True` | D6-security-1 |
| R6-08 | High | `onUnhandled: "error"` observability | An `onUnhandled="error"` kill is invisible to the sender: the `Receipt` is byte-identical to a benign no-op and `last_error` is `None` | LIB-01 |
| R6-09 | High | plain-`def` service responsiveness | A plain-`def` service blocks its own macrostep for the service's whole duration: the machine's inbox is frozen and events declared on the invoking state are evaluated against the post-completion configuration and lost. #149 freed the *loop*, not the *machine* | CV-CEC-01, K-3, W-05, CV-C32-RETEST |
| R6-10 | High | `Receipt.denied` semantics | `denied=True` is also set for a *crashed* guard under `guardErrorPolicy:"raise"`, re-merging the two cases #153 exists to separate; and `onUnhandled:"defer"` shadows the `guard_denied` disposition, so a guard-refused event is buffered and replayed against a later world | W-04 |
| R6-11 | Medium | `start()` contract / engine parity | `await Interpreter.start()` returns before the initial entry set's `invoke` children are registered (~13 ms) and before a plain-`def` service invoked by the initial state completes; `SyncInterpreter.start()` does both before returning | D6-concurrency-1, D6-fuzz-2, D6-semantics-2 |
| R6-12 | Medium | `send_threadsafe` counter leak | `_threadsafe_self_sends_in_flight` is incremented on the calling thread and decremented inside `_deliver`; if `_deliver` never runs the counter stays up for ever, and it gates the `_raise_depth` reset | K-5 |
| R6-13 | Medium | `service_executor` sizing | `max_workers=4` is hard-coded in `_get_service_executor()` and absent from the public surface; >4 concurrent plain services serialise in waves, each wave blocking a macrostep (R6-09) | K-4 |
| R6-14 | Medium | regression — `after` lateness | `AfterEvent` timestamps are populated (#118 fixed), but under a 100-iteration busy loop lateness is 88–92 ms against a 50 ms budget; the per-macrostep settle budget does not bound lateness under load | 35-r6-regression #2 |
| R6-15 | Medium | regression — `stop()` receipt resolution | `stop()` does not resolve *every* outstanding duplicate-`Event`-instance receipt with `InterpreterStoppedError`; some in-flight duplicates settle as ordinary success receipts | 35-r6-regression #3 (N-1 case D) |
| R6-16 | Low | snapshot read-side | Legality is validated via `state_ids` only; `configuration`, the second copy of the same fact, can be emptied independently and still restores live | LIB-R6-03 |
| R6-17 | Low | two legality predicates | `_configuration_is_legal()` calls a root with zero child states legal; the surviving `_active_leaf_present()` disagrees. Two definitions of one invariant in one file is the shape that reopened #142 | K-7 |
| R6-18 | Low | `stop()` contract | Owned-pool `shutdown(wait=False)` lets a service thread outlive the machine and commit its side effects after `stop()` returned; undocumented | K-6 |
| R6-19 | Low | build-time read-back | `spawnBlockingTimeout` is accepted by `create_machine` but sets no attribute on `MachineNode`, so a conformance lint cannot assert it post-build | OBS-01 |
| R6-20 | Low | docs | `PluginBase.on_action_error` docstring says `status == "error"` for `actionErrorPolicy="fail"`; every code path and the CHANGELOG say `"stopped"` | D6-observability-1, 35-r6-regression #1 (LC-01) |

## §3 Evidence

Every block below is this round's own re-run output, trimmed.

### R6-01 — async macrostep never terminates (Blocker)

`battle-cec108b/fuzz/m9_send_hang_min.py`, 8-line config:

```
async maxIterations=1     HANG (no receipt after 5.0s)  status=running
async maxIterations=1000  HANG (no receipt after 5.0s)  status=running
sync  baseline            returned in 0.06s  ok=False err=RunawayChainError
-- necessity ablations (async) --
always removed            resolved 0.00s
invoke removed            resolved 0.04s
external (non-internal) GO  HANG
no settle (invoke still running)  resolved 0.16s
HANGS: 3
```

Both `always` and a *completed* `invoke` are necessary; `maxIterations` and
internal-vs-external are irrelevant. Prior instrumentation during the pending send:
`t=9s events=36305 cpu=8.75s rss=32MB qsize=1` — a livelock, not a queue explosion.
**Root cause:** #144 ("a chain ends only when nothing self-generated remains queued")
was implemented in `SyncInterpreter` only; the async macrostep-termination condition in
`interpreter.py::_run_event_loop` never concludes the self-generated `always` chain once
the invoke has completed, so the receipt at `interpreter.py:1560` is never constructed.
**Classification:** LIBRARY-DEFECT.

### R6-02 — system events exempt from the async chain budget (Blocker)

`interpreter.py:1427`:

```python
if self._raise_depth > limit and not is_system_event(event):
```

with the comment *"The sync engine spares these by construction; mirror that here."*
That premise is false on `cec108b`: `sync_interpreter.py:747` charges completions.
Re-run of `contracts/repro/f9_sync_budget_signal.py` (sync, same machine):

```
"dropped": [["done.invoke.ver", "chain_budget"]], "critical_alerts": 500
```

versus `contracts/repro/f2_naked_verify_livelock.py` (async): unbounded, 523 laps/s,
`status=running`, `error=None`, `last_transition_ok=True`, `on_event_dropped=[]`.
#120's premise — "an engine completion cannot self-feed" — is untrue for a two-state
invoke cycle where each state's invoke completes into the other.
**Classification:** LIBRARY-DEFECT. Distinct root cause from R6-01 (budget *exemption*
vs. chain *termination*), so not merged, but they share a victim shape.

### R6-03 — `rollback` + `invoke.onDone` hot respawn (Blocker)

`contracts/repro/rollback_invoke_respawn_spin.py`, 40 lines, library only:

```
t=0.5s  service invocations=716    state=['spin.starting']  status=running
t=1.0s  service invocations=1434   state=['spin.starting']  status=running
t=2.0s  service invocations=2869   state=['spin.starting']  status=running
service was invoked 2869 times for ONE user-visible event; status never left 'running'.
```

Policy/engine matrix over 1 s: `rollback` async=1440 invocations vs sync=2;
`continue`=1; `fail`=1 then stopped. **Root cause:** rollback undoes the `onDone`
transition and restores the invoking state; re-entering re-arms the invoke, which runs
again, completes, raises in entry, rolls back — for ever. #144's budget does not apply
because every lap is a *separate macrostep* driven by a genuine `done.invoke.sub`, and no
budget is charged to a rolled-back transition. **Classification:** LIBRARY-DEFECT.
Highest practical priority for us: CV §1.3b mandates `rollback` on every contract machine.

### R6-04 — `internal=` fails open in both directions (Blocker)

`probes/main-cec108b/p4_forge_internal.py` (inbox bound 2, `RAISE`, loop stalled):

```
honest send_threadsafe : accepted=4    refused=46
internal=True          : accepted=5000 refused=0
```

`probes/main-cec108b/p3_threadsafe.py` case [1], `maxIterations: 20`:

```
[1] internal=False from action: hits=200 status=running err=None  -> dodged
[2] bounded inbox size=2 RAISE: honest refused=0, forged internal=True accepted=500
```

`p13_budget.py` shows the honest path is fine (`internal=True` from a plain thread trips
at 21 hits) — the defect is that the *unsafe* value is reachable and the *safe* default
(`internal=None` from a plain thread: 300 hits uncharged) is the unbounded one.
**Root cause, read back at `interpreter.py:1111-1126`:** `self_issued =
self._issued_from_own_action() if internal is None else internal` — the caller's claim
replaces the classifier unconditionally — and the overflow test is guarded by
`not self_issued`, while the internal queue is "never bounded" by design.
**Classification:** LIBRARY-DEFECT. Absorbs D6-security-2 (same line, same absence of a
cross-check) as a DUPLICATE.

### R6-05 — stale `qsize()` defeats the call-site bound (High)

`contracts/repro/threadsafe_bound_bypassed_when_loop_busy.py`:

```
accepted        : 500
QueueOverflow   : 0   <-- expected ~497
actually ran    : 3
on_event_dropped: 0   <-- silent loss
```

**Root cause:** `_inbox_is_full()` reads `self._event_queue.qsize()`, but the enqueue
happens later inside `_deliver()` via `run_coroutine_threadsafe`. While the loop thread
is busy no `_deliver` runs, so `qsize()` stays at its pre-burst value and every call-site
check passes regardless of in-flight depth. The pinned test
`test_raise_policy_raises_at_call_site_when_full` pre-fills the queue with awaited
loop-thread sends, so it only ever exercises the accurate-`qsize` idle case. The async
`send()` path enqueues synchronously and is correct. **Classification:** LIBRARY-DEFECT.

### R6-06 — entry-action window accepts a torn snapshot (High)

`semantics/repro/d6s1_entry_window_torn_snapshot.py`, **both engines identical**:

```
live after settle : ['oms.filled'] ctx= {'filled_qty': 100}
snapshot mid-entry: ACCEPTED
   persisted state : ['oms', 'oms.filled']  context: {'filled_qty': 0}
   restored        : ['oms.filled'] ctx= {'filled_qty': 0}
   >>> TORN: state says FILLED, context says 0 filled
```

`last_transition_ok=True`, `last_error=None` — no signal at all. **Root cause,**
`base_interpreter.py:1306`: the guard is a **conjunction**,
`if self._step_in_flight() and not self._configuration_is_legal():`. #142 correctly
replaced the any-leaf test with per-region legality (`_configuration_is_legal`,
`base_interpreter.py:1222`), which closes the parallel tear — but in the entry-action
window the configuration *is* legal (the new leaf is already active, exactly one per
region) while the macrostep is still open and context is half-applied. Legality was never
the right predicate here; `_step_in_flight()` alone already is. **Suggested fix:** for the
root call (`_seen is None`) refuse on `_step_in_flight()` alone, keeping the legality
conjunction for the recursive child case, where the deliberate
`_await_settled_for_snapshot()` race tolerance belongs. **Classification:**
LIBRARY-DEFECT. Carried over unfixed from D5-semantics-1: register item R5-01 is only
partly closed.

### R6-07 — `machine_hash: None` disables drift checking (High)

`security/probe_r6_gap_fields.py`:

```
machine_hash -> None ............ ACCEPTED (no error)
machine_hash -> 'wrong-hash-value' ... SnapshotDriftError  (correct)
taken_at -> None / 'garbage' ...... ACCEPTED (metadata only, acceptable)
__extra_junk__ ................... ACCEPTED (unknown key, acceptable)
```

`attack_snapshot_corrupt_fuzz.py`: 196/300 mutations silently accepted.
**Root cause,** `persistence.py:277`: `if verify_hash and snap_hash is not None:`. The
`None` branch exists for genuinely unversioned v0 payloads, but it is keyed on the
*field* rather than on the snapshot's declared `version`, so dropping one key downgrades
a v1 snapshot to unchecked. Fix: when `version >= 1` and `verify_hash`, a missing
`machine_hash` is `SnapshotCorruptError`. **Classification:** LIBRARY-DEFECT.

### R6-08 — `onUnhandled="error"` kill is invisible to the sender (High)

`contracts/r5_probes3.py::R5-unh-recv`, re-run:

```
receipt  : Receipt(state_ids={'ws_conn.live'}, changed=False, error=None,
                   deferred=False, denied=False)
status   : error
.error   : "Event 'CONNECT' is not handled ... onUnhandled policy is 'error'."
last_error: None
hooks    : [('CONNECT', 'errored')]
```

The receipt for the send that *killed the machine* is byte-identical to a benign no-op.
**Root cause:** the `_fail(UnhandledEventError)` path populates neither the `Receipt` nor
`last_error`. #153's `denied` is `False` here (correct by its own definition — nothing was
guard-denied) and #159's new hooks do not cover this path. Only `on_unhandled_event`
fires. Compounded: once `status="error"` every later send is dropped by the not-running
guard before `_check_strict`, with a WARNING log only. Note the prior round's companion
claim (strict-name rejection) was a **harness error** — see §4/H-2. **Classification:**
LIBRARY-DEFECT, still open from the prior round.

### R6-09 — plain-`def` service blocks its own machine (High)

`contracts/repro_cv_cec_01.py` — one machine, only `def` vs `async def` differs:

```
async def  PING latency=0.001s receipt.state_ids=['p.working'] mark_ping=True
plain def  PING latency=0.341s receipt.state_ids=['p.done']    mark_ping=False
```

The `PING` declared on the *invoking* state is evaluated against the post-completion
configuration and lost (deferred for ever under `onUnhandled:"defer"`).
`probes/main-cec108b/p6_service_blocking.py` shows the two halves cleanly: during a 0.5 s
plain service an unrelated asyncio task and the clock do keep running, but the machine's
own `PING`/`after` are only *processed* after the macrostep closes.
`c9_cvc32_executor.py`: latency 0.001 s (async) vs 0.441 s (plain, default pool) vs
0.437 s (plain, custom pool) — **a custom executor changes nothing, because the wait is in
the macrostep, not the pool.** **Root cause:** #149 moved plain-`def` services onto a
`ThreadPoolExecutor` so the loop keeps turning, but `_await_inline_services()` is awaited
*inside* the entering macrostep (`interpreter.py:1645, :1649`), deliberately, to preserve
#116's ordering. Ordering and `onError` routing do hold. **Classification:**
LIBRARY-DEFECT (High) **plus** DESIGN-CONSTRAINT — see §5/C-1: the ordering guarantee and
machine responsiveness are in genuine tension, so this may be answered by documentation
rather than code. Our contract rule CV-C32 ("all services `async def`") therefore
**stands**; `CV-C32-RELAX` is retracted.

### R6-10 — `Receipt.denied` conflates refusal with a crash (High)

`contracts/repro/f5_denied_conflation.py`: guard returns `False` → `denied=True,
error=None`; guard **raises** → `denied=True, error=RuntimeError`.
`f7_disposition_precedence.py`: `dispositions=[('TIGHTEN_SL','errored')]` with
`receipt.denied=True` — `defer`/`errored` shadows the `guard_denied` disposition.
`f6_denied_defer_buffer.py`: 3 denied `TIGHTEN_SL` → `deferred_count=3`; flipping the
guard true and forcing a configuration change replays all three
(`set_trading_stop` 0 → 3). **Root cause:** #153 sets
`denied = (not changed and _guard_denied_this_step)` regardless of whether the guard
returned `False` or raised under `guardErrorPolicy:"raise"`. The correct discriminator for
a caller is the *pair* `(denied, error is None)` — which works, but is undocumented and
re-merges what #153 exists to separate. Separately, `onUnhandled:"defer"` takes precedence
over the `guard_denied` disposition, so a guard-refused event enters the defer buffer and
is replayed against a world where the guard now answers differently. Same on both
engines. **Classification:** LIBRARY-DEFECT (the conflation) + DESIGN-CONSTRAINT (defer
precedence, §5/C-2). Wrapper obligation W-04 stands regardless.

### R6-11 — `start()` returns before the initial macrostep is settled (Medium)

Three inbound findings, one root cause. `concurrency/p1b_invoke_ordering.py`:

```
"async_completes_inside_start": false,
"sync_completes_inside_start" : true,
"engines_agree_on_start_completion": false,   "result": "FAIL"
```

`fuzz/m11_116_parity.py`:

```
#116 (GO,CANCEL)x10  sync=ok10 async=ok10  PARITY      <-- existing regression test
start()-settles-invoke  sync=(after_start=['m.b'], after_GO=['m.c'])
                        async divergent 10/10 sample=(['m.a'], ['m.b'])
```

`semantics/repro/d6s2_invoke_start_race.py`:

```
async: actors immediately after `await start()` : []
async: child actor became addressable 12.7 ms AFTER start() returned
async: first POKE -> drops: ['unresolved_target']
sync : actors immediately after start() : ['par:kid']   (0 lost in 10)
```

**Root cause,** `interpreter.py:487,496`: `start()` enters the initial configuration via
`_enter_states` + `_settle_transient_transitions` and **never calls
`_await_inline_services()`**, which is only reached from the run loop at `:1645`/`:1649`.
So the executor handoff future created at `:2417-2425` is first drained by the *first
event's* macrostep, and invoke-child registration likewise lands after `start()` returns.
The existing `(GO,CANCEL)x10` parity oracle passes, so the pinned regression test does not
catch this. Mitigating: the sendTo loss is **not silent** —
`on_event_dropped(reason='unresolved_target')` plus a soft step error fire, which is the
#133 contract working. Still a defect: `await start()` reads as "the machine is up and its
declared children exist", and the engines disagree on that for one config.
**Suggested fix:** await the initial macrostep's inline services and actor registration in
async `start()`, or expose an awaitable `children_ready()` and document that `start()`
does not imply it. **Classification:** LIBRARY-DEFECT. Subsumes D6-fuzz-2 and
D6-semantics-2 as DUPLICATEs, and reclassifies the prior suite's `N2-06` FAIL from
"budget mis-accounting" to this.

### R6-12 to R6-20 — condensed

- **R6-12** (Medium). `p3_threadsafe.py` case [3]: `in-flight counter after loop stop: 5
  (expected 0)`. Incremented at `interpreter.py:1132` on the calling thread, decremented
  at `:1136` inside `_deliver`; no compensating path if `_deliver` never runs. It gates
  the `_raise_depth` reset at `:1513`, so a permanently non-zero value means the chain
  budget can never reset and a long-lived machine eventually trips `RunawayChainError` on
  legitimate work. Consequence is **latent, not demonstrated** — `p10_counter_leak.py`
  could not drive a trip, because external events do not increment `_raise_depth`. The
  leak itself is deterministic. Fix: decrement in a done-callback on the returned future.
- **R6-13** (Medium). `interpreter.py:2360` `ThreadPoolExecutor(max_workers=4)`;
  `p7_sat.py` shows a clean step function at multiples of 4 (n≤4: 0.22 s, n=5–8: 0.41 s,
  n=12: 0.62 s), and this round's `p6_service_blocking.py` case [B]: 9 × 0.2 s services
  took **5.01 s** against an ideal 0.2 s and a serialised 1.8 s — worse than serial,
  because R6-09 compounds pool saturation. Workaround exists (`service_executor=`), hence
  Medium; wants a `service_pool_size=` argument and a documented limit.
- **R6-14** (Medium, regression vs `5e07ba8`). `after` lateness 88–92 ms against a 50 ms
  budget under a 100-iteration busy loop, 5/5 deterministic. Timestamp *fields* are fixed
  (#118); the per-macrostep settle budget does not bound *lateness* under load.
- **R6-15** (Medium, regression vs `5e07ba8`). `stop()` no longer resolves every
  outstanding duplicate-`Event`-instance receipt with `InterpreterStoppedError`; some
  events that raced the stop land as ordinary `Receipt(changed=True, …)`. Cases A/B/C of
  the original collision bug are genuinely fixed; case D regressed.
- **R6-16** (Low).
  `contracts/repro/snapshot_configuration_unchecked_when_state_ids_present.py`:
  both keys emptied → `SnapshotCorruptError`; both non-leaf → `SnapshotCorruptError`;
  **`configuration` emptied alone with `state_ids` intact → ACCEPTED, restores live in
  `m.b`**. The #142/#143 read-side check keys on `state_ids` and never cross-validates
  `set(state_ids) ⊆ set(configuration)`. A self-contradicting snapshot walks through the
  guard the library promises will catch an illegal configuration.
- **R6-17** (Low). `p1_legality.py`: `root_only_legal: True` for
  `create_machine({"id":"ro","states":{}})` — `_configuration_is_legal`'s recursion treats
  an empty-`states` node as atomic. The surviving `_active_leaf_present()`
  (`base_interpreter.py:1258`) excludes `self.machine` and answers `False`. Two
  disagreeing definitions of one invariant in one file is the shape that reopened #142.
- **R6-18** (Low). `p5_service_executor.py` case [3]: `stop()` returns in 0.00 s with a
  0.6 s service in flight, the `xsm-svc-*` thread survives, and the service **runs to
  completion** with its result discarded. Probably the right choice (user code is not
  interruptible) but undocumented: for an order-placement service, "`stop()` returned"
  must not be read as "nothing further will happen".
- **R6-19** (Low). `c1_build.py`: `spawnBlockingTimeout` reads back `<missing>` on all
  five machines while `actionErrorPolicy`/`onUnhandled`/`guardErrorPolicy`/`strictTargets`
  read back verbatim. Parsed without error, no attribute set on `MachineNode`, so a
  conformance lint cannot assert a contract's own spawn timeout post-build. No behavioural
  impact in the probed group (nothing spawns).
- **R6-20** (Low). `plugins.py:201-202` says `"fail"` → `status == "error"`; runtime and
  CHANGELOG both say `"stopped"`. Re-confirmed this round by
  `observability/new_attacks.py::B`: `status=stopped config=set() on_error x1
  on_transition_failed x1 receipt.error=ValueError('action-boom')`. **This also resolves
  regression LC-01**, which asserted the docstring's `"error"`: the *code* is correct and
  matches #145; the docstring and the LC-01 script are the stale artefacts. LC-01 is
  therefore **not** a true regression — reclassified here as a doc defect plus a harness
  refresh (§4/H-1).

## §4 Harness errors (not library defects)

| ID | Inbound | What was wrong | Action |
|---|---|---|---|
| H-1 | 35-r6-regression LC-01 ("TRUE REGRESSION") | Asserts `status == "error"` for `actionErrorPolicy="fail"`, copying the stale `plugins.py` docstring. #145 deliberately changed it to `"stopped"` and the CHANGELOG says so. The library is right. | Drop from the regression count; refresh the script to assert `"stopped"` + cleared configuration. Keep R6-20 for the docstring. |
| H-2 | `r5_probes3.py::R5-strict` | Reported strict-mode names ACCEPTED. The script's own note is correct: that run reused an interpreter already in `status="error"`, where sends are dropped *before* `_check_strict`. Fresh-machine behaviour is correct. | Already self-annotated; do not count. The *hazard* it stumbled on (post-`error` sends dropped with a WARNING only) is folded into R6-08. |
| H-3 | HD-01 (`c2 INV-B8-b`) | Asserts a call-site raise for a crashed guard; on `cec108b` the signal is `Receipt.error` + `last_error` and the transition is correctly not taken. Assertion predates `Receipt.error`/`denied`. | Refresh the assertion. The contract obligation is met on the `wait=True` path. Not a library defect — so the group's "53/55" is not a real 2-point deficit. |
| H-4 | `f_loader_dup`, `fv1_blockers_highs` (35-r6-regression §4) | Round-5 fix-confirmation scripts whose "the defect reproduces" assertion now fails *because* the new `InvalidConfigError` / `RootTargetError` guards fire. Expected FAILs. | Refresh; do not count as regressions. |
| H-5 | `contracts/repro/f5,f6,f7,f9` | Fail with `ModuleNotFoundError: cvlib` unless run with `PYTHONPATH=battle-cec108b/contracts`. All four pass and reproduce once the path is set. | Add a `sys.path` bootstrap so the repros are self-contained for a maintainer. |

Regression count after triage: **3** (R6-14, R6-15, and LC-26's secondary copy folded
into R6-14), not the 4 reported — LC-01 is H-1.

## §5 Design constraints (behaviour is defensible; document, don't "fix")

- **C-1 — ordering vs responsiveness for plain-`def` services.** #116's guarantee (a
  service's completion lands at the same point on both engines) and machine
  responsiveness during that service are in genuine tension; `_await_inline_services()`
  inside the macrostep buys the first at the price of the second. R6-09 is filed as a
  defect because the CHANGELOG claims *both*, but a documentation fix ("plain `def`
  services block this machine for their duration; use `async def` for anything slow") is
  an acceptable resolution. **Our rule CV-C32 stays mandatory**, restated per-engine:
  async engine → services must be `async def`; sync engine → services must be plain `def`
  (`SyncInterpreter` raises `NotSupportedError` on `async def`, confirmed in
  `k2::b18_sync`, `k3::b19_sync`, `c32_executor.py`). Sync parity for those machines is
  therefore *unavailable*, not merely untested.
- **C-2 — `onUnhandled:"defer"` precedence over `guard_denied`.** Defensible as written
  (the event was undelivered; defer is the configured undelivered policy) but hazardous:
  authorisation and risk events must never be deferrable. Library should let a transition
  or event opt out of the defer buffer; until then this is wrapper work (W-03, W-04).
- **C-3 — dict-event acceptance.** `{'type':'GO'}` acceptance is a documented, deliberate
  validation boundary as of #161 (`attack_invalid_event_hostile.py`), not a bypass.
  D5-security-3 / R5-20 is **resolved**.
- **C-4 — `internal=None` from a plain `threading.Thread` is uncharged.** Documented.
  Listed here so it is not re-filed: the *defect* is R6-04 (`True`/`False` unverified),
  not the default. But note the safe default is the unbounded one, which is a poor
  ergonomic for a safety limit.
- **C-5 — coverage gate (K-8).** `fail_under = 90` in `[tool.coverage.report]` is a
  genuine improvement (local and CI now agree) but an honour-system floor a contributor
  can lower in one line. Not a defect; INFO.

## §6 Our-contract defects and wrapper obligations

Library is correct in every row below; the fault is in our catalogue JSON or belongs in
a wrapper. Tracked here so they are not mistaken for library items.

| ID | Sev | Machine | Issue |
|---|---|---|---|
| CV-B4-01 | High | B4 OCO | `LEG_B_FILL` is declared only on `racing`; deferred correctly in `settling_b` but `completing`/`completed` do not declare it, so it re-defers for ever and `filled_b=0` in a terminal OCO. Patch confirmed: adding it gives `deferred_now=0, record_fill_b=1`. Identical on `3ed3099` — not a regression. |
| CD-03 | High | B8 | `naked ⇄ verifying` is an unbounded invoke-driven livelock (523 laps/s, 523 P1 alerts/s, every health signal clean). A successful-but-useless fallback attach can never reach `naked_unrecoverable`, which is only reachable via the attach *erroring*. Our shape — but R6-02 is why it is silent on async. |
| C-04 | Blocker | B16 | Elevation survives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` and can be acquired after `REVOKE`. The `elevation` region declares only `REVOKE`. Correct SCXML parallel-region semantics; our JSON is wrong. |
| C-07b | Blocker | B18 | `onUnhandled:"error"` makes a guard-denied `RELEASE` terminal — the kill switch is bricked by a wrong button press. `Receipt.denied` distinguishes it for the caller but the policy does not. |
| C-06 | High | B19 | `stale_lockout` declares only `RECONNECTED`; `OPERATOR_RESOLVED` defers for ever, and `page_owner` in the entry list re-pages on every retry of a flapping link. |
| C-07 | High | B16–B20 | CV-C31 withdrew `fail` in favour of `rollback` + explicit `halted` states; the `halted` states were never added, so a failed `locked` entry rolls B20 back to `clear` (tag `trading_allowed`) with no record and no sink to page from. |
| OUR-B11-01 | High | B11 | `degraded` declares no `STREAM_UNHEALTHY` handler; a second stream failing is parked and `streams_healthy` lags reality. One-line JSON fix: internal targetless `"STREAM_UNHEALTHY": {"actions": ["mark_stream_unhealthy"]}`. |
| OUR-B14-01 | High | B14 | INV-B14-d's "bounded" pending-delta buffer is prose-only: 1000 `DELTA`s → 1000 buffered, growth 1:1, nothing dropped. Needs a `maxBufferedDeltas` key and a re-snapshot (not a silent discard) on overflow, so the overflow path does not violate INV-B14-c. |
| W-01 / C-01 | High | all | `create_machine` is not a conformance gate: all five machines build with a bare `MachineLogic()`; a missing guard surfaces as a failed receipt at first use. Wrapper must validate the logic table against the JSON at construction. |
| W-03 | High | B17 | A deferred `ENABLE_REQUESTED` auto-fires the moment evidence lands, reaching `enabled` unattended. Authorisation events must be non-deferrable or stamped with the configuration they were issued against. |
| W-04 | High | all | Wrapper must read `(denied, error is None)` — not `denied` alone — to tell refusal from a crashed guard (R6-10), and must keep guard-denied events out of the defer buffer (C-2). |
| CV-B8-01 | Medium | B1/B8 | Native-SL-before-position is observable but not structurally enforced: no `stateIn`/`in` guard anywhere in the B1 JSON, so lifecycle can reach `filled` while protection is `sl_missing`. |
| CV-B3-01 | Medium | B3 | `place_tp_ladder_once` is edge-triggered on `open → partially_filled`; a re-entry of `open` after restore fires it again. Idempotency must live in the action implementation. |
| W-02 | Medium | B16 | Unbounded defer buffer in a terminal region: events declared by the machine but undeclared by the terminal state are held for ever (`deferred_count` growing after `auth.revoked`). |
| C-05 | Low | B16 | `STEP_UP_OK` while already elevated writes no audit record (INV-B16-c): the `elevated → elevated` re-enter runs `stamp_elevated_until` but omits `audit_step_up`. |

## §7 Counts

**Canonical library defects: 20.**

| Severity | Count | IDs |
|---|---|---|
| Blocker | 4 | R6-01, R6-02, R6-03, R6-04 |
| High | 6 | R6-05 … R6-10 |
| Medium | 5 | R6-11 … R6-15 |
| Low | 5 | R6-16 … R6-20 |

**Triage of the inbound set (36 items + K-1…K-8 + 4 regressions):**

| Classification | Count |
|---|---|
| LIBRARY-DEFECT (canonical) | 20 |
| DUPLICATE (merged into a canonical ID) | 13 |
| HARNESS-ERROR | 5 (H-1 … H-5) |
| DESIGN-CONSTRAINT | 5 (C-1 … C-5) |
| OUR-CONTRACT-DEFECT / NEEDS-WRAPPER | 15 |
| CONFIRMED-FIXED / INFO | 9 |

**Merges performed (13):** D6-fuzz-2 + D6-semantics-2 + D6-concurrency-1 → R6-11;
K-1 + K-2 + D6-security-2 → R6-04; CV-CEC-01 + K-3 + W-05 + CV-C32-RETEST → R6-09;
LC-26 repro → R6-14; D6-observability-1 + LC-01 → R6-20; CV-C32-RELAX → retracted
into R6-09/C-1.

**Confirmed FIXED on `cec108b` (9), re-verified this round, no action:**

- **LD-01 / #152** — a raising guard on `invoke.onDone` no longer aborts the whole
  selection pass; the unguarded fallback is taken (`f4_guard_raise_sinks.py`). The prior
  round's ship-blocker is **closed**. Fixing it is what turned CD-03 from a silent strand
  into a visible spin.
- **#153** — `Receipt.denied` + `on_unhandled_event(disposition="guard_denied")` exist
  and fire (`new_attacks.py::A`). Caveat R6-10.
- **#125 (sync parity)** — a deferred event's replay is its own macrostep on
  `SyncInterpreter`; the caller's `Receipt` is final before any replay runs.
- **#134 (sync parity)** — `on_resolve_error` now fires on `SyncInterpreter`
  (`rerun_prior.py::D5`, hooks include `on_resolve_error`).
- **#145** — `actionErrorPolicy:"fail"` → `status="stopped"`, configuration cleared,
  `TransitionFailedError` retained; `from_snapshot` refuses the blob with
  `InvalidConfigError` (`new_attacks.py::B`, `k6_failsnap.py`).
- **#147** — `RootTargetError` raised at build time on every `strict_targets` setting
  (`new_attacks.py::C`).
- **#143** — a torn-parallel restore is refused with `SnapshotCorruptError`
  (`new_attacks.py::E`). Caveat R6-16 (`configuration` key unchecked).
- **#160** — `get_snapshot()`'s DEBUG log is redacted and `DEFAULT_REDACT_KEYS` covers
  financial/PII keys (`repro_D_security_1_snapshot_log_leak.py`, `plugins.py:493-530`).
  D5-security-1 / R5-19 **closed, both halves**.
- **`on_event_dropped` for events abandoned at `stop()`** — fires 5/5
  (`rerun_prior.py::D8b`); the signal that did not exist in the prior round now does.
- **C-02 (contract)** — with the `"*"` defer scaffolding removed from the catalogue,
  `onUnhandled:"defer"` correctly holds and replays `UNKNOWN_ORDER` mid-sweep on B19.

## R7-08 (refutation attempt, main@221ce7c) — CONFIRMED (High)
`base_interpreter.py:1280-1289` `_await_settled_for_snapshot` uses `time.sleep(0.0005)`
in a deadline loop. On the async engine the caller is the loop thread, so the child it
waits for cannot progress: the wait burns its full 0.5 s and then snapshots the unsettled
child. Repro `probes/main-221ce7c/p10_snapshot_refusal_and_child_wait.py` (b): 501 ms.
Scales per mid-step child: 1 child 501 ms, 3 children 1502 ms of total loop block
(sequential recursion, each child charged its own 0.5 s). A child whose step is legal
mid-step returns in ~1 ms (wait only entered when config illegal), so the stall is
conditional but deterministic once entered. Not API misuse: parent was settled and the
docs' prescribed call sites (after `send(wait=True)`, `on_transition`, `stop(drain=True)`)
give no way to observe or avoid a child's in-flight step. Docs describe no blocking;
XState v5 `getPersistedSnapshot()` is non-blocking. Compounds R7-07.
