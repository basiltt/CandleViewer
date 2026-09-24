# Battle test — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`5e07ba8`** (merge of PR #101, `fix/round3-ride-alongs`).
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`;** this build is identified **by commit, never by version string**.

**Date:** 2026-09-18. **OS:** Windows 11 Pro 10.0.26200.
**Primary interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
— CPython **3.13.7** (GIL build), env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
**Secondary (track item h):** `battle-5e07ba8/.venv-ft/Scripts/python` —
CPython **3.13.7 experimental free-threading build**, `Py_GIL_DISABLED=1`,
`sys._is_gil_enabled() is False`.

No library source was modified (`git status --porcelain` in the library clone
is empty after the whole run). No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout.

**Scripts:** `docs/research/xstate/battle-5e07ba8/concurrency/*.py`.
**Raw results:** the `*.json` beside them, written by `common.emit()`.

---

## 0. Bottom line

**Six defects, two of them Blockers, both on the async engine's async path.**

The engine's *accounting* is exact and its *task hygiene* is flawless. Under a
1,000,000-event fan-in across 2,000 interpreters, on every one of the three
overflow policies, not a single event was both accepted and lost
(§2). Across 7,000 stop/teardown cycles racing sends, invokes, `after` timers
and child actors — under `-W error -X dev` — the `asyncio.all_tasks()` delta
was **0** every time, with zero `RuntimeWarning`s, zero
"Task was destroyed but it is pending", and zero unhandled loop exceptions
(§4). Cancelling the awaiter of `send(wait=True)` at nine rotating loop phases
across 200 trials left **0 invariant violations** and leaked **0** receipts out
of 2,000 (§5). Plugin failures are contained by construction, at the
registration boundary, for all ten hooks tested (§6). Memory is flat (§7).
The `_next_event` yield-per-event design does what it was built to do: a
50,000-event backlog drains with the 100 ms tick's p95 lateness at **2.8 ms**
(§8). That is a lot of genuinely good engineering and it should be said first.

The two Blockers are both cases where *an `await` inside the engine makes an
intermediate state observable*, and both are silent:

- **D-concurrency-3 (Blocker).** For exactly as long as any transition action
  `await`s, the machine reports **no active state at all** while
  `status == "running"` — `current_state_ids == set()`, `matches(x) == False`
  for every `x`, and `get_persisted_snapshot()["state_ids"] == []`. A snapshot
  taken in that window restores to a machine that is `running`, has no
  configuration, and ignores every event forever. `_execute_transition` has an
  explicit `ATOMICITY` comment (base_interpreter.py:2340) describing this exact
  state as "permanently dead and reporting itself healthy" — it defends
  against the *failure* case and not against the *observation* case.
  Window measured at **0.252 s for a 0.25 s await, 17/17 samples empty**.
- **D-concurrency-1 (Blocker).** Under `OverflowPolicy.BLOCK` — the policy the
  library's own production-config example recommends
  (`docs/_guide/reliability.md:348`) — a fire-and-forget `interp.send("X")`
  is **silently discarded, even with an empty inbox**. The published changelog
  states the opposite in so many words. 10/10 events lost, no hook, no log.

Three more are High, one Medium. §9 has the register; §10 has the constraints
we would need.

---

## 1. Method

### 1.1 Exact commands

Every command below was run from
`docs/research/xstate/battle-5e07ba8/concurrency/`, with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1` set and
`PY="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"`.

```bash
# (a) bounded inbox, 2,000 interpreters x 500 events x 16 producers, cap 64
$PY a1_bounded_fanin.py raise       2000 500 16 64
$PY a1_bounded_fanin.py block       2000 500 16 64
$PY a1_bounded_fanin.py drop_newest 2000 500 16 64
$PY a2_block_edges.py
$PY d1_block_fire_and_forget.py        # minimal repro, D-concurrency-1
$PY d2_block_stop_silent_drop.py       # minimal repro, D-concurrency-2

# (b) send_threadsafe from 32 OS threads
$PY b1_threadsafe.py 32 2500 20000     # paced at the 20k ev/s target
$PY b1_threadsafe.py 32 2500 0         # unpaced (max rate)
$PY b1_threadsafe.py  4 20000 0
$PY b2_threadsafe_cost.py              # ingest-cost attribution
$PY b3_threadsafe_backpressure.py      # D-concurrency-6

# (c) stop()/stop(drain=True) races -- 7 variants x 1,000 cycles
$PY -W error -X dev c1_stop_leaks.py 1000

# (d) cancellation
$PY probe_d_cancel.py
$PY probe_d_empty_window.py
$PY d3_snapshot_in_window.py           # minimal repro, D-concurrency-3

# (e) exceptions in plugin hooks
$PY e1_plugin_hook_raises.py
$PY e2_plugin_containment_edges.py
$PY e3_baseexception_case.py KeyboardInterrupt   # one case per process
$PY e3_baseexception_case.py SystemExit
$PY e3_baseexception_case.py MemoryError
$PY e3_baseexception_case.py CancelledError
$PY d4_plugin_cancellederror.py        # minimal repro, D-concurrency-4

# (f) memory: 1,000,000 events x 100 machines x 3 machine shapes
$PY f1_memory.py 1000000 100 20 --depth=4

# (g) loop blocking, 3 s window per scenario
for s in s0 s1 s2 s3 s4 s5 s6; do $PY g1_loop_blocking.py 3.0 $s; done
for s in s1 s2 s3;             do $PY g1_loop_blocking.py 3.0 $s --batch=1; done

# (h) free-threading, NOTE ONLY
FT="../.venv-ft/Scripts/python"
$FT h1_free_threading.py
$PY  h2_reader_race_gil.py             # the same probe on the GIL build
```

### 1.2 Instruments and what they can and cannot show

- **Event accounting (a, b).** Every script balances
  `attempted == accepted + refused_at_call_site` and
  `accepted == processed + dropped_via_hook + still_queued`, where `processed`
  is counted by a `PluginBase.on_event_received` hook *and* independently by a
  context counter incremented in an action. Both must agree. A discrepancy is
  by definition an event that was accepted and lost.
- **Task-leak accounting (c).** `len(asyncio.all_tasks())` before and after
  each 1,000-cycle batch, with `gc.collect()` and a settle on both sides;
  a custom `loop.set_exception_handler` to catch anything the loop would have
  merely logged; a `logging.Handler` on the `asyncio` logger matching
  "Task was destroyed but it is pending"; and `warnings.catch_warnings` inside
  the batch. The whole run additionally under `-W error -X dev`.
- **Tick lateness (g).** A `loop.call_at` chain rescheduling itself every
  100 ms and recording `actual - expected` — literally the criterion the
  heatmap cares about. This is the instrument the §8 verdict rests on.
- **Callback duration (g).** `asyncio` debug mode with
  `slow_callback_duration = 0.005`. **Read qualitatively only**, because
  debug mode is a heavy instrument: under it the *idle control* already put
  8/30 ticks over the 5 ms budget and saturated throughput fell from ~240k to
  ~390 ev/s. The headline numbers in §8 are from debug-OFF runs; the
  debug-ON runs are kept in `g1_loop_blocking_*_debug.json` for attribution.
- **Producer-batch control (g).** A saturating producer that issues 200 sends
  between yields is *itself* one long callback. Every saturation scenario was
  therefore re-run with `--batch=1` (yield after every send) to separate
  engine-caused lateness from producer-caused lateness. This changed the
  verdict — see §8.
- **Memory (f).** `tracemalloc` with a 15-frame limit, sampled after each of
  20 batches so the *shape* of the curve is visible rather than just the
  endpoints, plus RSS (psutil), `len(gc.get_objects())`,
  `len(asyncio.all_tasks())` and aggregate `queue_depth` per sample; and a
  `compare_to(..., "lineno")` top-8 allocation diff so a leak could be
  attributed to a line rather than merely observed.

### 1.3 Honest limits of this track

- **One box, one run each.** Timing numbers (§8, §3) are single-sample on a
  Windows 11 laptop with a `ProactorEventLoop`. They establish orders of
  magnitude and the *shape* of the curves, not portable constants. The
  correctness results (§2, §4, §5, §6) are not timing-dependent in the same
  way and are repeated many times internally.
- **Windows only.** `ProactorEventLoop` behaviour (notably the ~15 ms timer
  granularity visible in the `s0` idle control's 42 ms max loop-turn gap) is
  not representative of `epoll` on Linux. The defects in §9 are all logic
  defects, reproduced deterministically, and are not Windows-specific — but
  the §8 latency table would need re-running on the deployment platform.
- **`SyncInterpreter` was not covered.** This track is about the async
  engine's concurrency surface; every finding below is against `Interpreter`.
  Whether the `SyncInterpreter` shares D-concurrency-3's window (it plausibly
  cannot, having no loop to yield to) is **not tested here**.
- **`spawn_blocking_`, history states, parallel states and deep actor trees**
  were exercised only incidentally (c V5 spawns one child per cycle). A
  parallel-state machine's configuration has several leaves, and
  D-concurrency-3's "empty configuration" window was characterised only on
  simple compound machines.
- **20k ev/s was targeted but not reached** for `send_threadsafe` (§3); the
  ceiling is ~11k ev/s on this box. That is a measurement, not a defect, but
  it means the 20k figure in the track brief is **unverified at 20k** — the
  accounting invariants were verified at the rate the engine could actually
  sustain.

---

## 2. (a) Bounded inbox under fan-in — **no event both accepted and lost**

2,000 interpreters sharing one `MachineNode`, 500 events each (1,000,000
total), pushed by 16 concurrent producer tasks, inbox bound `max_queue_size=64`.

| Policy | attempted | accepted | refused at call site | processed | dropped via hook | **accepted-but-lost** | balance ok | deadlock |
|---|---:|---:|---:|---:|---:|---:|:--:|:--:|
| `RAISE` | 1,000,000 | 128,000 | 872,000 (`QueueOverflowError`) | 128,000 | 0 | **0** | ✅ | no |
| `BLOCK` | 1,000,000 | 1,000,000 | 0 | 1,000,000 | 0 | **0** | ✅ | no |
| `DROP_NEWEST` | 1,000,000 | 1,000,000 | 0 | 128,000 | 872,000 (`queue_full`) | **0** | ✅ | no |

`processed` is corroborated independently: `context["n"]` summed over all
2,000 interpreters equals the hook count exactly in all three rows.

**Every claim in the track brief's item (a) holds:**

- *No event is both accepted and lost.* The residual is **0** on all three
  policies at 1,000,000 events. `RAISE` refuses at the call site and processes
  every event it accepted. `DROP_NEWEST` accepts everything and attributes
  every one of the 872,000 losses to a `on_event_dropped(reason="queue_full")`
  hook. `BLOCK` loses nothing at all.
- *`QueueOverflowError` attribution is correct.* 872,000 refusals under
  `RAISE`, and `accepted + refused == attempted` exactly. The exception
  carries `interpreter_id`, `depth` and `maxsize`
  (`exceptions.py:303`).
- *`BLOCK` cannot deadlock with the loop.* No deadlock at 1M events; the run
  completes in 29.3 s (34.1k ev/s aggregate). The self-send case — a `BLOCK`
  send issued *from an action*, which would suspend the only task that drains
  the inbox — is handled by routing it to the internal queue when
  `self._processing` (interpreter.py:611-623). `a2_block_edges.py` V3 confirms
  a self-feeding `BLOCK` machine at `max_queue_size=1` does not wedge
  (`wedged: false`).

**Two BLOCK-specific defects were found** on paths this table does not reach —
see D-concurrency-1 and D-concurrency-2 in §9.

Throughput note: the `RAISE` row completes its producer phase in 4.18 s
(239k send-attempts/s) because most attempts are cheap refusals; `BLOCK` and
`DROP_NEWEST` run at 34.1k and 43.6k ev/s of real work.

---

## 3. (b) `send_threadsafe` from 32 OS threads

Target: 20,000 ev/s into one interpreter. **Not reached — the ceiling is
~11k ev/s on this box.** All correctness invariants hold at the achievable rate.

| Run | threads | attempted | accepted | raised on calling thread | processed | per-thread order violations | lost | achieved ev/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| paced @20k target | 32 | 80,000 | 80,000 | 0 | 80,000 | **0** | **0** | 9,391 |
| unpaced (max) | 32 | 80,000 | 80,000 | 0 | 80,000 | **0** | **0** | 9,243 |
| unpaced | 4 | 80,000 | 80,000 | 0 | 80,000 | **0** | **0** | 5,148 |

- **Per-producer FIFO is preserved.** Each event carries `(tid, seq)`; a
  receiving action asserts `seq` is strictly increasing per `tid`.
  **0 violations in 240,000 events** across the three runs. Global interleaving
  between threads is arbitrary, as expected.
- **`strict` is enforced on the calling thread (#78).** One deliberately
  typo'd event per thread: **32/32 raised `UnknownEventError` on the producing
  thread**, before anything was queued, in every run.
- Loop responsiveness while 32 threads hammer it: turn-gap p50 0.055 ms,
  p99.9 12.3 ms, max 34.8 ms.

### 3.1 Why 20k is not reached — ingest cost attribution

`b2_threadsafe_cost.py`, 40,000 events, 32 threads:

| Path | µs/event | ev/s |
|---|---:|---:|
| `interp.send_threadsafe(...)` | **86.9** | 11,503 |
| floor: `run_coroutine_threadsafe(noop())` | 60.5 | 16,542 |
| floor: `loop.call_soon_threadsafe(noop)` | 20.0 | 49,939 |
| reference: in-loop `interp.send(...)` enqueue | 6.1 | 164,620 |
| reference: in-loop `send()` end-to-end (enqueue + process) | — | 20,181 |

`send_threadsafe` (interpreter.py:871-914) allocates a fresh `_deliver()`
coroutine per event and hands it to `run_coroutine_threadsafe`, which wraps it
in a `Task` and does one `call_soon_threadsafe` — **one full task schedule and
one loop wake-up per event**. 60.5 of the 86.9 µs is that design's own floor;
a `call_soon_threadsafe` of a plain callback would cost 20 µs. This is a
**design cost, not a bug**, and it is honestly documented in spirit by the
`Production Characteristics` page — but the specific consequence (the
cross-thread path is ~14× more expensive per event than the in-loop path, and
caps a single interpreter around 11k ev/s) is worth knowing before sizing.

### 3.2 `send_threadsafe` has no working backpressure — D-concurrency-6

`b3_threadsafe_backpressure.py`. 32 free-running threads, one interpreter:

- **Unbounded:** `queue_depth` grows strictly monotonically —
  `2096, 2936, 3732, … 14825` sampled every 100 ms over a 2 s window. The
  producers get no signal whatsoever; `send_threadsafe` returns a future that
  resolves as soon as the event is queued.
- **`max_queue_size=100` + `RAISE`:** 6,400 calls returned on the producing
  threads **without raising**; **6,082 of them later failed with
  `QueueOverflowError` on the returned future**, which the documented usage
  (`interp.send_threadsafe("X")`, result discarded) never inspects. Only 318
  events were processed. `on_event_dropped` fired **0 times**.
- **`max_queue_size=100` + `DROP_NEWEST`:** correct and observable — 5,736
  `on_event_dropped` hooks for 5,736 drops.

See §9, D-concurrency-6.

---

## 4. (c) `stop()` / `stop(drain=True)` racing in-flight work — **fully clean**

`c1_stop_leaks.py`, **7 variants × 1,000 cycles = 7,000 teardowns**, the whole
run under `python -W error -X dev`.

| Variant | what races the stop | cycles | task delta | `RuntimeWarning`s | "Task destroyed but pending" | loop exceptions |
|---|---|---:|---:|---:|---:|---:|
| V1 | 5 in-flight sends, `stop()` | 1,000 | **0** | 0 | 0 | 0 |
| V2 | 5 in-flight sends, `stop(drain=True)` | 1,000 | **0** | 0 | 0 | 0 |
| V3 | an invoked service mid-`await` (`asyncio.sleep(3600)`) | 1,000 | **0** | 0 | 0 | 0 |
| V4 | an armed-but-not-due `after: {50000}` timer | 1,000 | **0** | 0 | 0 | 0 |
| V5 | a running spawned child actor | 1,000 | **0** | 0 | 0 | 0 |
| V6 | two concurrent `stop()` calls | 1,000 | **0** | 0 | 0 | 0 |
| V7 | producers + `stop()` interleaved at a rotating loop phase (0–6 turns), alternating `drain` | 1,000 | **0** | 0 | 0 | 0 |

**The track brief's acceptance criterion for (c) — `asyncio.all_tasks` delta
== 0 after 1,000 cycles, no 'Task was destroyed but it is pending', no
un-awaited coroutine warnings under `-W error` — is met, seven times over.**

The variants are non-vacuous: `c1_selfcheck.py` confirms that at the moment
`stop()` is called V3 has a live invoke task (3 tasks alive vs 1 baseline),
V4 has one live timer handle registered under `aft.waiting`, and V5 has a
registered child actor. V7 additionally rotates the stop's loop phase so
teardown lands in a different place each cycle.

This is the strongest result in the track. `_teardown` (interpreter.py:979) is
a single shared path reached by both `stop()` and terminal-status reaping, it
acks the inbox before cancelling the run loop so a concurrent
`_event_queue.join()` cannot hang, and `TaskManager.cancel_all()` plus the
per-state timer map leave nothing behind.

---

## 5. (d) Cancelling the awaiter of `send(wait=True)` mid-transition

Note on shape: `send(..., wait=True)` returns the receipt **`Future`**, not a
coroutine, so `asyncio.create_task(i.send(...))` is a `TypeError`. The
realistic application shape — and the one used here — is a task running
`async def _run(): return await i.send(ev, wait=True)`; cancelling *that* task
propagates into the receipt future.

| Variant | result |
|---|---|
| V1 — cancel while the action list is mid-`await` | machine intact; the action **completes** (`n` reaches its final value); `states_after == ['cx.b']`; `status running`; receipts map back to **0**; next event's receipt `changed=True, error=None` |
| V2 — 200 trials, cancelling at 9 rotating loop phases | **0 invariant violations** (exactly one active leaf, `status running`, receipts == 0, `context` self-consistent, follow-up event succeeds) |
| V3 — cancel all 50 awaiters of a 50-event batch | all 51 events processed, receipts left **0**, follow-up OK |
| V4 — 2,000 cancelled awaiters (leak check) | `_receipts` map size after: **0**; all 2,000 events still processed |
| V5 — cancel 5 awaiters queued behind a slow transition | slow event's own receipt resolves `changed=True, error=None`; receipts left **0**; 6/6 processed |

**Verdict: cancellation of the awaiter does not corrupt the machine, does not
abort the in-flight transition, and does not leak receipts.** This is the
correct semantics: the awaiter does not own the machine, and a committed
transition is not the awaiter's to roll back.

**But V1 exposed something else.** At the instant the cancellation was
observed, `sorted(i.current_state_ids)` was `[]` — the machine reported *no
active state*. That is not caused by the cancellation; it is the transition
window itself, and it is the track's most serious finding. It is characterised
in §5.1 and filed as D-concurrency-3.

### 5.1 The empty-configuration window (`probe_d_empty_window.py`)

| Surface, read from an ordinary concurrent task while a transition action awaits | value |
|---|---|
| `current_state_ids` | `[]` |
| `active_state_ids` (documented alias) | `[]` |
| `matches("a")` / `matches("b")` (source / target) | `False` / `False` |
| `status` | `"running"` |
| `get_persisted_snapshot()["state_ids"]` | `[]` |
| `get_persisted_snapshot()["status"]` | `"running"` |
| `get_snapshot()` → `"state_ids": []`, `"value": {}` | (serialises the same) |
| `PluginBase.on_transition` fired yet? | **no** (fires after entry) |
| an event sent *during* the window | queued, processed correctly *after* |

Duration scales with the action's own await, exactly:

| action awaits | window observed | samples with empty configuration |
|---:|---:|---|
| 10 ms | 14.8 ms | **2 / 2** |
| 250 ms | 252.1 ms | **17 / 17** |

Control: a purely **synchronous** action list produces **0 empty-configuration
observations in 200 transitions**. The window is specific to actions that
`await` — which is to say, to any action that makes an HTTP call, writes to a
database, or does `asyncio.sleep`.

---

## 6. (e) Exceptions inside plugin hooks — **contained by construction**

`use()` (base_interpreter.py:917) wraps **every** plugin in `_SafePlugin`
(base_interpreter.py:184-252), whose `__getattr__` returns a `_guarded`
closure that catches `Exception`, logs with `exc_info=True`, and returns
`None`. Containment is at the *registration boundary*, so no dispatch site can
forget it — and none of the eleven dispatch sites has its own `try`.

`e1_plugin_hook_raises.py` raises from one plugin in each of ten hooks, with a
second innocent plugin registered *after* the exploder:

| Hook raised from | transition committed | exactly one leaf | status | next event OK | second plugin still called |
|---|:--:|:--:|---|:--:|:--:|
| `on_interpreter_start` | ✅ | ✅ | running | ✅ | ✅ |
| `on_event_received` | ✅ | ✅ | running | ✅ | ✅ |
| `on_transition` | ✅ | ✅ | running | ✅ | ✅ |
| `on_action_execute` | ✅ | ✅ | running | ✅ | ✅ |
| `on_guard_evaluated` | ✅ | ✅ | running | ✅ | ✅ |
| `on_guard_error` | n/a (guard failed) | ✅ | running | ✅ | ✅ |
| `on_unhandled_event` | n/a | ✅ | running | ✅ | ✅ |
| `on_event_dropped` | ✅ | ✅ | running | ✅ | ✅ (4 drops still hooked) |
| `on_done` | ✅ | ✅ | done | n/a | ✅ |
| `on_interpreter_stop` | ✅ | ✅ | running | ✅ | ✅ |

**Nothing escaped to the caller in any of the ten. An observer cannot break
the machine it observes, and cannot blind another observer.** This is a
direct, verified answer to the track brief's item (e).

### 6.1 The edges the wrapper does not cover (`e2`, `e3`)

- **`BaseException` is not caught — deliberately**, and the four cases differ:

  | raised from a hook | outcome |
  |---|---|
  | `MemoryError` | **contained anyway**: receipt `changed=True`, machine keeps running, `stop()` OK. (It reaches the run loop's `except BaseException` at interpreter.py:1290, which logs `CRITICAL` and re-raises — but the transition had already committed.) |
  | `KeyboardInterrupt` | escapes `asyncio.run()` and terminates the process |
  | `SystemExit` | escapes `asyncio.run()` and terminates the process |
  | `asyncio.CancelledError` | **silently kills the run loop while `status` stays `"running"`** → D-concurrency-4 (High) |

  `KeyboardInterrupt` / `SystemExit` terminating the process is defensible
  (that is what they mean). `CancelledError` is not — see §9.
- **An `async def` hook never runs.** `_guarded` calls it and discards the
  returned coroutine: `async_hook_body_executed: 0`, plus a
  `coroutine ... was never awaited` RuntimeWarning — which under
  `-W error` becomes a crash at an arbitrary later GC point. Filed as
  D-concurrency-5 (Medium).
- **A contained failure has no programmatic surface.** With a hook raising on
  every transition: receipt `changed=True, error=None`,
  `last_transition_ok=True`, `last_error=None`. An **ERROR log line is the
  only trace.** There is no counter, no hook-of-last-resort, and nothing an
  alerting path can assert on. (Noted under D-concurrency-5.)
- **A mutating hook is allowed.** A hook that writes `context` and calls
  `i.send()` drives the machine to `n=1001, tampered=1001` — the observer
  became a participant, bounded only by the runaway-chain budget. Not filed:
  arguably the user's fault, but worth knowing an "observer" has full write
  access.
- **A blocking hook is charged to the run loop**, as expected: a
  `time.sleep(0.05)` hook produced a **50.8 ms** max loop stall.

---

## 7. (f) GC / memory — **flat**

`f1_memory.py 1000000 100 20 --depth=4`. 100 interpreters sharing one machine
node, **1,000,000 events per shape**, 20 tracemalloc samples, three machine
shapes, after a warm-up excluded from the measurement.

| Shape | events | traced first → last | traced growth | bytes/event | RSS growth | gc objects growth | asyncio task growth |
|---|---:|---|---:|---:|---:|---:|---:|
| `m1_plain` (self-transition) | 1,000,000 | 535.0 → 542.7 KiB | **+7.7 KiB** | **0.0083** | +2,192 KiB | **0** | **0** |
| `m2_entry_exit` (ping-pong + entry/exit actions) | 1,000,000 | 535.0 → 542.7 KiB | **+7.7 KiB** | **0.0083** | +7,336 KiB | **0** | **0** |
| `m3_internal_raise` (`raise` an internal event per external one) | 1,000,000 | 534.9 → 542.7 KiB | **+7.8 KiB** | **0.0084** | **−9,248 KiB** | **0** | **0** |

**Growth is flat — the track brief's criterion for (f) is met.**

- **0.008 bytes per event.** Over 1,000,000 events the traced heap moved by
  7.7 KiB; that is ~180,000× smaller than one `Event` object per event would
  be. The curve is linear-flat across all 20 samples, not a sawtooth hiding a
  trend: `m1` reads 535.0 / 536.7 / 538.7 / 540.7 / 542.7 KiB at batches
  1 / 5 / 10 / 15 / 20.
- **`len(gc.get_objects())` is constant to the object** across all 20 samples
  in all three shapes (24,635 / 24,665 / 24,657). Nothing accumulates on the
  Python heap at all.
- **`len(asyncio.all_tasks())` is constant at 101** — 100 run loops plus the
  driver — for the entire 3,000,000 events. This independently corroborates §4.
- **`queue_depth` returns to 0 after every batch**, so the flatness is not an
  artefact of work being deferred.
- **RSS is noise, in both directions**: `m3` *fell* 9.2 MiB over its run while
  `m2` rose 7.3 MiB, on a 32–44 MiB process. That is allocator behaviour, not
  a signal; the `tracemalloc` and `gc` figures are the ones that carry weight.
- **The top allocation-diff sites are all steady-state, not growth.** The
  largest is `asyncio/queues.py:67` (`self._queue.append(item)`) at +412.5 KiB
  / +800 objects — that is 8 in-flight events per interpreter across 100
  interpreters at sampling time, i.e. the queues' working set, and it does not
  grow between samples. The two library lines that appear
  (`interpreter.py:1699` `await self._wakeup.wait()` and `interpreter.py:1231`
  `config_before = frozenset(...)`) are +21.1 KiB / +100 objects each —
  exactly one per interpreter, the parked wait and the current frozenset.
  **No library line shows per-event accumulation.**

Instrument note: the first attempt ran `tracemalloc.start(15)` and the
*probe* grew past 4 GiB of bookkeeping at this event count and had to be
killed. Frame depth 4 still attributes an allocation to a library line, which
is all the diff table is read for. The engine was never the thing consuming
that memory.

---

## 8. (g) Event-loop blocking — **the 5 ms budget is met by the engine**

Acceptance criterion: no single loop callback may exceed 5 ms, so a 100 ms
heatmap tick is not starved. The instrument that answers this literally is the
`call_at` tick chain's own lateness. `--batch` is the *producer's* sends per
loop turn: `batch=200` measures a deliberately antisocial producer,
`batch=1` a well-behaved one. **The distinction is the whole result.**

| Scenario | batch | throughput ev/s | tick late p50 | p95 | max | ticks over 5 ms | loop-turn gap p99.9 / max |
|---|---:|---:|---:|---:|---:|---:|---|
| s0 idle control (no interpreters) | — | 0 | 0.34 ms | 2.35 ms | 6.37 ms | 1/30 | 2.57 / 42.78 ms |
| s1 1 machine saturated | 200 | 2,508 | 1.60 | 21.73 | 53.82 | 94/368 | 22.70 / 105.22 |
| s1 1 machine saturated | **1** | 5,631 | **0.21** | 13.28 | 27.22 | 8/30 | 14.13 / 30.39 |
| s2 100 machines saturated | 200 | 6,271 | 25.31 | 62.30 | 85.24 | 42/43 | 90.58 / 90.58 |
| s2 100 machines saturated | **1** | 4,655 | **0.23** | 5.97 | 9.37 | 3/30 | 9.58 / 37.44 |
| s3 1,000 machines saturated | 200 | 14,984 | 20.16 | 31.93 | 68.05 | 30/30 | 55.42 / 55.42 |
| s3 1,000 machines saturated | **1** | 6,786 | **0.19** | **2.00** | **2.18** | **0/30** | 4.18 / 28.39 |
| s4 100 machines + 32 threads (paced 6.4k ev/s) | 200 | 3,724 | 1.59 | 5.18 | 5.52 | 2/30 | 6.30 / 8.38 |
| **s5 50,000-event backlog drain** | 200 | 5,156 | **0.45** | **2.85** | 248.72 | **3/96** | 3.12 / 10.28 |
| s6 20 ms synchronous action (control) | 200 | 47 | 32.75 | 41.05 | 42.62 | **30/30** | 29.63 / 29.63 |

**Reading this table:**

- **The engine meets the budget; the caller can break it.** At `batch=1` —
  a producer that yields after each send — tick lateness p50 is
  **0.19–0.23 ms** at every scale from 1 to 1,000 machines, and at 1,000
  machines **0/30 ticks exceed 5 ms with a p95 of 2.0 ms**. At `batch=200`
  the same scenarios blow the budget, but the long callback is *the
  producer's own 200-send loop*, not the interpreter's.
- **s5 is the important one and it passes.** A 50,000-event backlog built up
  *before* the measurement window drains with tick p50 **0.45 ms** and p95
  **2.85 ms**, only **3/96 ticks** over budget. This is exactly what the
  `_next_event` design (interpreter.py:1654-1699) was built for — it yields
  once per inbox event so a deep backlog cannot be drained in one loop turn
  and starve a due timer. The **248.7 ms max** is a single outlier at the
  start of the drain, not a sustained stall (p99.9 of the loop-turn gap is
  3.1 ms).
- **s6 proves the instrument works.** A 20 ms synchronous action puts
  **30/30 ticks** over budget with p50 lateness 32.7 ms. User code that
  blocks does show up, so the clean rows above are not a broken instrument.
- **s0 sets the floor.** Even idle, one tick in 30 exceeded 5 ms and the max
  loop-turn gap was 42.8 ms — Windows `ProactorEventLoop` timer granularity.
  **No conclusion about sub-5 ms behaviour on this platform can be stronger
  than that floor**, which is another reason to re-run this table on the
  deployment OS.

**Verdict on (g): the engine does not itself block the loop for >5 ms at any
tested scale, including a 50k backlog. Two things do: a synchronous action
(s6, by construction) and a caller that batches many sends between yields
(batch=200).** Both are under the adopting application's control.

---

## 9. Defects

### D-concurrency-1 — `OverflowPolicy.BLOCK` silently discards every fire-and-forget `send()` — **Blocker**

**Repro:** `d1_block_fire_and_forget.py` (exit 1 = fail).

```
sent (fire-and-forget) : 10
processed              : 0
context['n']           : 0
queue_depth            : 0
on_event_dropped hook  : []
RuntimeWarnings        : 10   ("coroutine 'Interpreter._enqueue_blocking' was never awaited")
RESULT: FAIL (all 10 lost silently)
```

The inbox is `max_queue_size=1000` and **empty**; this is not an overflow
path. Ten events vanish. No hook, no log line, no counter — the only trace is
a GC-time `RuntimeWarning`, which under `-W error` becomes a crash at an
unrelated point in the program.

**Root cause.** `interpreter.py:625`:

```python
# ⏸️ BLOCK is the one policy that must genuinely await.
return self._enqueue_blocking(event_obj, receipt)
```

This returns an **un-started coroutine object**. The `RAISE` /
`DROP_NEWEST` branch 12 lines below (`interpreter.py:637`) instead calls
`self._enqueue(event_obj)` **eagerly** before returning. So under BLOCK
nothing happens at all unless the caller awaits.

**Why this is a Blocker rather than a documentation nit.** The library
documents the opposite, twice, unconditionally:

- `Interpreter.send()`'s own docstring (interpreter.py:556-566): *"ALL of the
  work — thread check, normalisation, status guard and the queue put —
  therefore happens eagerly, before anything is awaited… a fire-and-forget
  `interp.send("GO")` from inside the loop is delivered rather than silently
  dropped."*
- The published changelog (`docs/_guide/changelog.md:482-487`): *"…returns an
  already-resolved awaitable… A fire-and-forget `interp.send("GO")` from
  inside the loop is therefore delivered rather than silently dropped, and no
  'coroutine was never awaited' warning is ever emitted by the library."*

And `BLOCK` is the policy the library's **own recommended production config**
selects (`docs/_guide/reliability.md:344-349`):

```python
interp = Interpreter(machine, strict=True,
                     max_queue_size=10_000,
                     overflow_policy=OverflowPolicy.BLOCK)
```

So the documented production configuration and the documented fire-and-forget
idiom combine into silent, unattributed event loss on an order path.

**Suggested fix.** Make the BLOCK branch eager when the inbox has room —
enqueue synchronously and return `_completed()` — and only return the
coroutine when it genuinely must suspend. Failing that, the docstring and
changelog claims must be narrowed to exclude BLOCK, and BLOCK must at minimum
log and fire `on_event_dropped`.

---

### D-concurrency-3 — an `await`ing action makes the configuration observably EMPTY; a snapshot taken there restores a permanently dead machine — **Blocker**

**Repro:** `d3_snapshot_in_window.py`; characterisation in
`probe_d_empty_window.py`.

```
before          : ['order.submitted'] running
during window   : []                  running
  matches('submitted'): False
  matches('working')  : False
  snapshot state_ids  : []
  snapshot status     : running
after           : ['order.working']   running

restored        : [] running
  FILL receipt changed: False error: None
  context             : {'fills': 0}
  states              : []
  status              : running
RESULT: FAIL - restored machine has no configuration, status 'running', and ignores every event
```

**Root cause.** `_execute_transition` (base_interpreter.py:2278-2345) runs
exit → actions → enter as one transaction, and its own `ATOMICITY` comment at
**base_interpreter.py:2340** states the stakes precisely:

> ⚛️ ATOMICITY: exit → actions → enter is ONE transaction. If a user action
> raises in the middle, the source has been left and the target never reached,
> so the configuration would be EMPTY while `status` still read "running" —
> **permanently dead and reporting itself healthy.**

The rollback at base_interpreter.py:2413-2418 defends against the **failure**
case. It does not — and structurally cannot, as written — defend against the
**observation** case: the transaction is not atomic *with respect to the event
loop*. The moment a transition action `await`s, the run-loop task suspends
with `_active_state_nodes` already emptied by `_exit_states` and not yet
repopulated by `_enter_states`. Every other task on that loop sees exactly the
state the comment describes.

**Blast radius (measured, §5.1):** `current_state_ids`, the documented
`active_state_ids` alias, `matches()` for every argument, `get_snapshot()` and
`get_persisted_snapshot()` all report the empty configuration, while `status`
reports `"running"`. The window lasts exactly as long as the action's await
(252 ms measured for a 250 ms await, 17/17 samples empty) — not a scheduling
hairline. Any action that does I/O opens it.

**Why this is a Blocker for an order-management system.** Three ordinary
concurrent readers hit it:

1. **A health endpoint** on the same loop reports "no state" and a supervisor
   restarts a healthy process.
2. **A periodic snapshotter** (our CV-C08 path is snapshot/restore-based)
   persists `state_ids: []` and the restore is inert — `status running`,
   responds to nothing, forever. The receipt for the ignored event reads
   `changed=False, error=None`, which is the *same* signature as a legitimate
   no-op, so even a `wait=True` caller cannot tell.
3. **Any `matches()`-based routing** silently takes the else-branch.

**Suggested fix.** The reader-visible configuration must not be the
mid-transition one. Either publish the configuration atomically (compute the
new `_active_state_nodes` and swap it in one non-awaiting step, keeping
`snapshot_before` visible until then), or expose a `transition_in_progress`
flag and make `get_persisted_snapshot()` refuse (or block) while it is set.
The second is strictly weaker — it fixes the snapshot but leaves the health
endpoint lying.

---

### D-concurrency-4 — a plugin hook raising `asyncio.CancelledError` kills the run loop while `status` stays `"running"`; awaiters hang forever — **High**

**Repro:** `d4_plugin_cancellederror.py`.

```
status            : running          <-- WRONG
is_running        : False            <-- correct
current_state_ids : ['px.b']
run loop done     : True
run loop exception: CancelledError: metrics push was cancelled

now ask the 'running' machine a question:
  send(BACK, wait=True) HUNG: no receipt, no error, no timeout
  queue_depth after: 1
```

**Root cause chain.**

1. `_SafePlugin._guarded` (base_interpreter.py:239-251) catches `Exception`.
   `CancelledError` is a `BaseException`, so it is not caught — correct in
   itself, since swallowing real cancellation would be a bug.
2. It propagates out of the `on_transition` dispatch
   (base_interpreter.py:2464) into `_run_event_loop`.
3. `_run_event_loop` (interpreter.py:1274-1275) does
   `except asyncio.CancelledError: raise`, with an explicit architecture note
   that it must **not** set `status = "stopped"` because cancellation normally
   arrives from an enclosing TaskGroup and `stop()` owns the status
   transition. **That reasoning is sound for cancellation from outside and
   wrong here: nobody cancelled anything.** The `CancelledError` was
   manufactured by user code running *inside* the loop, and the loop cannot
   tell the two apart.

**Consequences.** `status` — the attribute `stop()`,
`_refuse_if_not_running()` (interpreter.py:790) and every documented example
switch on — still reads `"running"`, so later events are **queued rather than
refused**: no `on_event_dropped`, no warning, `queue_depth` grows unbounded.
And `_fail_all_receipts()` runs only from `_teardown`, which only `stop()`
reaches, so a `wait=True` awaiter hangs with **no error and no timeout**.

**Mitigation that already exists and works.** `is_running`
(interpreter.py:296-299) additionally requires `_event_loop_task` to exist and
not be done, and correctly returns `False` here. That property was added for
exactly this class of problem (#44, restored-but-not-pumping machines). It is
the right check — it is just not the one the rest of the library, or the docs,
tell you to use.

**Realism.** A plugin need not be malicious. `raise asyncio.CancelledError`
is what comes out of any hook wrapping `await`-based work with `task.cancel()`
semantics, out of `concurrent.futures.CancelledError` (which *is*
`asyncio.CancelledError` since 3.8), and out of any library re-raising
cancellation through a synchronous shim.

**Suggested fix.** In `_run_event_loop`'s `CancelledError` handler,
distinguish "our own task was cancelled" (`asyncio.current_task().cancelling()
> 0`, or a flag set by `stop()`) from a `CancelledError` that merely
propagated out of user code. In the latter case treat it like any other fatal
loop error: set `status`, fail the receipts, fire `on_error`.

---

### D-concurrency-2 — an event parked on a full `BLOCK` inbox is dropped with no `on_event_dropped` hook — **High**

**Repro:** `d2_block_stop_silent_drop.py` (exit 1 = fail).

```
inbox cap               : 4
producers parked        : 5
processed (hook)        : 0
on_event_dropped events : []
producer outcomes       : 0..4: send() returned normally   (x5)

blocked events lost with NO on_event_dropped hook: 5/5
RESULT: FAIL (silent loss)
```

Five producers doing the ordinary `await interp.send("PING")` are parked on a
full inbox when `stop()` runs. All five `await`s **return normally** — the
documented "accepted" signal — and all five events are discarded.

**Root cause.** `_enqueue_blocking` (interpreter.py:819-833) leaves its wait
loop when `status != "running"` and calls only `self._fail_receipt(...)`.
With `wait=True` the caller does learn, via an `InterpreterStoppedError`
receipt (verified: `a2_block_edges.py` V2 resolves all three such awaiters
correctly). Without a receipt, `_fail_receipt` is a **no-op** — there is no
future to fail — so the coroutine returns `None`, indistinguishable from
success.

**Why it matters.** Every *other* loss path in the engine is attributable:
`queue_full` (interpreter.py:853-863), `not_running`
(interpreter.py:790-811), `chain_budget` (interpreter.py:1211-1240). BLOCK's
stop-release path is the one hole. A load-shedding dashboard built on
`on_event_dropped` reports zero drops while events are being dropped.

**Suggested fix.** Call `plugin.on_event_dropped(self, event_obj,
"stopped_while_blocked")` and log at WARNING in that branch, exactly as the
other three paths do.

---

### D-concurrency-6 — `send_threadsafe` has no backpressure, and `max_queue_size` does not protect it in a way the caller can act on — **High**

**Repro:** `b3_threadsafe_backpressure.py`. Data in §3.2.

Two distinct problems:

1. **Unbounded, there is no signal at all.** 32 threads drive `queue_depth`
   monotonically from 2,096 to 14,825 over a 2 s window. `send_threadsafe`
   returns a `concurrent.futures.Future` that resolves when the event is
   *queued*, which under overload is immediate. The producer cannot tell it is
   overrunning the consumer. Combined with the ~87 µs/event loop-side ingest
   cost (§3.1), a single interpreter saturates near 11k ev/s — below the 20k
   this track targets — and then simply accumulates.

2. **Bounded + `RAISE`, the refusal is unreachable.** `send_threadsafe`
   schedules `_enqueue()` onto the loop (interpreter.py:911-914), so the bound
   is evaluated **after the calling thread has already returned**. The
   `QueueOverflowError` is raised inside the scheduled coroutine and lands on
   the returned future. Measured: **6,400 calls returned without raising;
   6,082 later failed on a future the documented usage never reads; 318
   events processed; `on_event_dropped` fired 0 times.**

   This is a notable asymmetry with `send()`, where the same policy raises at
   the call site — and with `send_threadsafe`'s own `strict` check, which #78
   deliberately moved *onto the calling thread* (interpreter.py:903-909) with
   the explicit reasoning that "raising here — not inside the returned future
   — is what a foreign-thread caller can actually act on". **The overflow
   policy did not get the same treatment.**

`DROP_NEWEST` is correct and observable (5,736 hooks for 5,736 drops), so a
cross-thread producer that must not silently lose events has exactly one
working option today.

**Suggested fix.** Evaluate `_inbox_is_full()` on the calling thread before
scheduling (the depth read is a cheap `qsize()`), and raise
`QueueOverflowError` there under `RAISE` — mirroring what #78 did for
`strict`. At minimum, document that under `RAISE` the error surfaces only on
the returned future.

---

### D-concurrency-5 — an `async def` plugin hook is never awaited, and a contained hook failure has no programmatic surface — **Medium**

**Repro:** `e2_plugin_containment_edges.py` V2, V3.

- `async def on_transition(...)` → `async_hook_body_executed: 0`, plus
  `coroutine ... was never awaited`. `_guarded` (base_interpreter.py:239-251)
  calls the hook and discards the return value; a coroutine function
  "succeeds" and does nothing. Under `-W error` the warning becomes a crash at
  an arbitrary later GC point, far from the plugin. `PluginBase`'s hooks are
  all `def`, so this is arguably user error — but nothing rejects it, and the
  failure is invisible and delayed.
- A hook raising on every transition leaves receipt `changed=True,
  error=None`, `last_transition_ok=True`, `last_error=None`. Two ERROR log
  lines are the *only* trace. There is no counter and no
  hook-of-last-resort, so an alerting path cannot assert "no plugin failed" —
  and the whole point of the audit/metrics plugins that would raise is that
  someone is watching them.

**Suggested fix.** In `_guarded`, detect a returned coroutine
(`inspect.iscoroutine`) and either schedule it on the owning loop or close it
and log an explicit error naming the plugin and hook. Separately, expose a
`plugin_errors` counter (or an `on_plugin_error` hook-of-last-resort) so
containment is observable.

---

### Not defects, recorded

- **A plugin hook can mutate the machine** (`context` writes, `send()`) and
  drove `n` to 1001 in one transition. Bounded only by the runaway-chain
  budget. An "observer" has full write access by construction.
- **A synchronous plugin hook is charged to the run loop**: a 50 ms
  `time.sleep` hook produced a 50.8 ms loop stall. Expected; noted because
  §8's budget is 5 ms.
- **`send(..., wait=True)` returns a `Future`, not a coroutine**, so
  `asyncio.create_task(i.send(..., wait=True))` raises
  `TypeError: a coroutine was expected`. Correct and arguably desirable, but
  it is a surprising shape and appears in no example.
- **`from_snapshot()` takes a JSON *string***, while `get_persisted_snapshot()`
  returns a `dict`; passing the dict straight back raises a bare `TypeError`
  from `json.loads` (base_interpreter.py:1167), not a wrapped
  `InvalidConfigError` — despite the adjacent comment explaining why decode
  errors *are* wrapped. Cosmetic.

---

## 10. (h) Free-threading (3.13t) — note only

Run on CPython 3.13.7 free-threading (`Py_GIL_DISABLED=1`,
`sys._is_gil_enabled() is False`) with the library installed into a separate
venv. **The library does not claim 3.13t support and we are not gating on it.**

| Check | Result |
|---|---|
| import, build, start, 100 sends, `wait=True` receipt, stop | ✅ works |
| 32 threads × 1,000 `send_threadsafe` | 32,000 accepted, **32,000 processed, 0 lost, 0 per-thread order violations**, 32/32 `strict` typos rejected on the calling thread |
| ingest rate | 3,926 ev/s (vs 9,243 ev/s on the GIL build — ~2.4× slower) |
| **8 threads reading `current_state_ids` / `context` / `queue_depth` while the loop transitions** | ❌ **58 exceptions in 144 reads**: `RuntimeError: Set changed size during iteration`, `RuntimeError: deque mutated during iteration` |

The reader race is **specific to free-threading**. The identical probe on the
GIL build (`h2_reader_race_gil.py`) did **332,638 reads with 0 exceptions**.

The cause is structural: `current_state_ids` comprehends over the live
`_active_state_nodes` set (base_interpreter.py:556) and `queue_depth` does
`list(getattr(q, "_queue", ()))` over the live deque (interpreter.py:1026);
under the GIL those iterations are effectively atomic, without it they are not.

**Note, not a defect against this build.** It does mean the engine's public
read properties are not safe to call from a non-owning thread on a
free-threaded interpreter, and that anyone planning a 3.13t migration should
treat cross-thread reads — not just writes — as needing `send_threadsafe`-like
mediation.

---

## 11. Constraints we would need

If the adopting project proceeds on this commit, these are additions to the
existing CV-C* set. They are written as they would appear in the
`cv/statechart/` config block.

```python
# cv/statechart/actions.py
# CV-C23 (D-concurrency-3, Blocker): NO transition action may `await`.
#   Any action attached to a transition, entry or exit must be a plain `def`.
#   Work that needs I/O is modelled as an `invoke`, whose completion arrives
#   as a done.invoke/error.platform event -- outside the exit->enter
#   transaction. Rationale: for as long as a transition action awaits, the
#   machine reports current_state_ids == set() with status == "running", and
#   a snapshot taken there restores a permanently inert machine.
#   Enforced by CV-LINT-XS10: reject `async def` in any actions= registry.

# cv/statechart/persistence.py
# CV-C24 (D-concurrency-3): a snapshot is INADMISSIBLE unless
#   `interp.current_state_ids` is non-empty AND `interp.is_running`.
#   Assert both immediately before and after get_persisted_snapshot(), and
#   discard the snapshot if either fails. This is defence in depth behind
#   CV-C23, not a substitute for it -- it cannot protect a health endpoint.
#   Extends the existing CV-C20 pre-snapshot assertions.

# cv/statechart/health.py
# CV-C25 (D-concurrency-3, D-concurrency-4): liveness is
#   `interp.is_running`, NEVER `interp.status == "running"`.
#   `status` reads "running" both mid-transition (empty configuration) and
#   after a CancelledError has killed the run loop. `is_running` additionally
#   requires a live loop task and is correct in both cases.
#   A health check must also assert `current_state_ids` is non-empty.

# cv/statechart/gateway.py
# CV-C26 (D-concurrency-1, Blocker): OverflowPolicy.BLOCK is BANNED.
#   Use DROP_NEWEST for telemetry lanes and RAISE for order lanes. Under
#   BLOCK a fire-and-forget `send()` is silently discarded even with an
#   empty inbox, and an event parked on a full inbox at stop() is dropped
#   with no on_event_dropped hook (D-concurrency-2).
#   Enforced by CV-LINT-XS11.
# CV-C27 (D-concurrency-1): every `send()` must be awaited. A bare
#   `interp.send(...)` statement is a lint error, notwithstanding the
#   library docstring and changelog blessing the fire-and-forget form.
# CV-C28 (D-concurrency-6): cross-thread producers use send_threadsafe ONLY
#   with overflow_policy=DROP_NEWEST, and must read the returned future's
#   exception (or use an explicit in-process queue + a single loop-side
#   pump). Under RAISE the QueueOverflowError lands on a future the ordinary
#   call site never inspects -- measured 6,082 refusals with zero producer
#   signal and zero on_event_dropped hooks.
# CV-C29 (§3.1): size cross-thread ingest at <= 8,000 ev/s per interpreter
#   (measured ceiling ~11,500 ev/s at ~87 us/event, loop-side). Above that,
#   shard across interpreters or batch on the producing thread.

# cv/statechart/plugins.py
# CV-C30 (D-concurrency-4, High): no plugin hook may raise BaseException.
#   Every hook body is wrapped in `try/except BaseException` by our own
#   PluginBase subclass, which converts to a counter + log. `_SafePlugin`
#   contains Exception only; a CancelledError from a hook kills the run loop
#   while status still reads "running" and hangs every wait=True awaiter.
# CV-C31 (D-concurrency-5, Medium): no `async def` plugin hook -- the body
#   never runs. Enforced by CV-LINT-XS12.
# CV-C32 (D-concurrency-5): plugin containment is unobservable upstream, so
#   our PluginBase subclass owns the counter; alerting reads it, not the log.

# cv/statechart/README
# CV-C33 (g): the 5 ms budget is met by the ENGINE, not by every caller.
#   A producer must not issue more than ~16 sends between `await`s (measured:
#   200 sends/turn puts 30/30 heatmap ticks over budget at 1,000 machines;
#   1 send/turn puts 0/30 over, p95 2.0 ms). Re-run g1_loop_blocking.py on
#   the deployment OS before relying on the table: these numbers are Windows
#   ProactorEventLoop, whose idle floor alone is a 42 ms max loop-turn gap.
# CV-C34 (h): 3.13t is not supported. Public read properties
#   (current_state_ids, queue_depth, pending_events) iterate live containers
#   and raise "changed size during iteration" from a non-owning thread when
#   the GIL is off. Not a defect on supported builds; a migration blocker.
```

**What would have to change upstream before these could be relaxed:**
CV-C23/C24/C25 collapse to nothing once D-concurrency-3 is fixed;
CV-C26/C27 once D-concurrency-1 and -2 are fixed; CV-C28/C29 are partly
structural (the task-per-event cross-thread design) and partly fixable
(D-concurrency-6's call-site check); CV-C30 once D-concurrency-4 is fixed.

---

## 12. Coverage — what this track did and did not establish

**Established, with evidence:**

- (a) Bounded-inbox accounting is exact at 1,000,000 events × 2,000
  interpreters × 16 producers on all three policies; `QueueOverflowError`
  attribution correct; `BLOCK` does not deadlock with the loop, including the
  self-send-from-an-action case. **Plus two BLOCK defects on paths the
  headline table does not reach.**
- (b) `send_threadsafe` from 32 OS threads preserves per-producer FIFO
  (0 violations in 240,000 events), loses nothing, and enforces `strict` on
  the calling thread. **The 20k ev/s target was not reached**; the ceiling is
  ~11k ev/s and the cost is attributed to a line.
- (c) 7,000 stop/teardown cycles across 7 race shapes: task delta 0,
  no warnings, no destroyed-pending tasks, no loop exceptions, under
  `-W error -X dev`. **Clean.**
- (d) Cancelling a `send(wait=True)` awaiter at rotating loop phases leaves
  the machine consistent and leaks no receipts (0 violations / 200 trials,
  0 leaked / 2,000). **Clean — but the probe surfaced D-concurrency-3.**
- (e) All ten plugin hooks tested can raise without harming the machine or
  blinding a second plugin. **Clean by construction** — plus four
  edge findings, one of them High.
- (f) Memory flat over 1,000,000 events × 100 machines × 3 machine shapes,
  with per-batch samples and per-line allocation attribution.
- (g) The engine does not block the loop beyond 5 ms at 1 / 100 / 1,000
  machines or while draining a 50,000-event backlog, once the producer's own
  batching is controlled for. Instrument validated by a positive control.
- (h) 3.13t runs the engine correctly single-threaded and for
  `send_threadsafe` fan-in, but concurrent readers of public properties tear.

**Not established — do not read this report as covering:**

- `SyncInterpreter` in any variant. Every result is against `Interpreter`.
- Parallel states, history states, deep actor hierarchies, `spawn_blocking_`,
  and `after`-heavy machines under concurrent load. In particular,
  D-concurrency-3's window was characterised only on simple compound machines;
  its shape on a parallel machine (where some regions may still be populated)
  is unknown.
- Any platform other than Windows 11 / CPython 3.13.7 / `ProactorEventLoop`.
  The §8 latency table in particular is not portable.
- Sustained multi-hour soak. The memory result is 1M events in a single
  process over minutes, not days.
- Multi-process, multi-loop, or `uvloop` deployments.
- Whether any of the six defects is a regression against `3c527b0` or
  `5327ba6`. None of the probes here existed before this track, so all six are
  reported as *present on `5e07ba8`*, not as new.
