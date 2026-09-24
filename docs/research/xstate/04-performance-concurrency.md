# Study 4 — Performance & Concurrency Bench: `xstate-statemachine`

**Library:** `basiltt/xstate-statemachine` v0.7.0 (local clone, installed `-e`)
**Date run:** 2026-09-15
**Scripts:** `docs/research/xstate/bench/` (all runnable; `common.py` holds the shared OMS machine)

> **Scope note.** Everything below measures the *state-machine engine only* — no
> network, no exchange, no database. Where a CandleViewer budget includes I/O,
> the engine cost measured here is the portion of that budget the library
> consumes before any real work happens.

---

## 0. Machine specs

| Item | Value |
|---|---|
| CPU | Intel64 Family 6 Model 142 Stepping 10 (Kaby Lake-R class, mobile) |
| Cores | 4 physical / 8 logical |
| Base freq | 1992 MHz |
| RAM | 15.9 GB |
| OS | Windows 11 (10.0.26200) |
| Python | CPython 3.13.7 |
| Library | xstate-statemachine 0.7.0, zero deps |

⚠️ **This is a low-clock mobile CPU.** A production server (3.5–4.5 GHz, better
memory bandwidth) should be expected to run **2–3× faster** on every CPU-bound
number here. Absolute throughput figures should be read as a *floor*, but the
*ratios* and all correctness findings are platform-independent.

⚠️ **Logging was disabled** (`logging.disable(logging.INFO)`) in every
benchmark. The library logs at INFO on every transition, guard evaluation and
action. Left enabled, logging dominated the profile. **Any CandleViewer
deployment must disable this logger explicitly** or pay a large multiple.

⚠️ **`tracemalloc` distorts timing by ~5–6×** on this workload (measured — see
§2). Timing rows come from `notrace` runs, memory rows from `trace` runs. This
is the single most common way to get this benchmark wrong.

---

## 1. (a) Single async interpreter throughput

5-state OMS machine (`pending → submitted → open → filled|cancelled`), guards
and actions on every transition. Script: `bench_a_throughput.py`.

| Mode | Events | Throughput (ev/s) | µs/event | Notes |
|---|---:|---:|---:|---|
| Burst (enqueue all, then drain) | 10,000 | **28,699** | 34.8 | upper bound |
| Burst | 50,000 | **30,662** | 32.6 | stable with size |
| Lockstep (send→await processed) | 5,000 | 17,386 | 57.5 | realistic request/response shape |
| `send()` enqueue only | 50,000 | 441,993 | 2.26 | producer-side cost only |
| Pure API (`get_next_snapshot`) | 50,000 | 12,958 | 77.2 | **slower than the interpreter** |

**Lockstep latency (µs), single interpreter, no load:**

| p50 | p95 | p99 | max |
|---:|---:|---:|---:|
| 48.1 | 101.4 | 157.0 | 3,051.7 |

### Findings

- **~30k ev/s single-interpreter ceiling** on this CPU; ~33 µs per transition
  including guard evaluation and 2 actions. Expect 60–90k ev/s on server silicon.
- **`send()` is ~15× cheaper than processing** (2.3 µs vs 33 µs). Producers are
  never the bottleneck; the single event-loop consumer is.
- **The "pure" API is 2.4× SLOWER than the full interpreter** (77 µs vs 33 µs).
  This is counter-intuitive — it is advertised as the no-overhead path. It also
  **does not execute imperative actions**: after `SUBMIT`, `context` was
  unchanged (`qty` stayed `0.0`) while the state advanced. Verified directly.
  Two consequences: (1) do not reach for it as an optimisation, it is a
  pessimisation; (2) it is only meaningful for machines using the declarative
  `assign` form. Worth reporting upstream.
- The 3 ms max in lockstep is a GC/scheduler artefact, not a systematic tail.

---

## 2. (b) 1,000 and 10,000 concurrent interpreters

One interpreter per order, 100 events each. Fresh process per configuration.
Script: `bench_b_many_interpreters.py`.

### Timing (from `notrace` runs — authoritative)

| N | create_machine (µs ea) | ctor (µs ea) | start (µs ea) | drain (s) | aggregate ev/s | stop (µs ea) |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 121.7 | — | 31.2 | 3.55 | **28,208** | 22.7 |
| 10,000 | 255.3 | — | 77.6 | 48.62 | **20,568** | 35.4 |

### Memory (from `trace` runs — authoritative)

| N | RSS/idle interp | tracemalloc/interp | RSS peak | RSS retained after teardown+gc |
|---:|---:|---:|---:|---:|
| 1,000 | 42.4 KB | 20.1 KB | 135.7 MB | 16.1 MB |
| 10,000 | 44.7 KB | 19.5 KB | 1,055 MB | 80.3 MB |

### The tracemalloc distortion, quantified

| N | Mode | aggregate ev/s | create_machine µs ea |
|---:|---|---:|---:|
| 1,000 | notrace | 28,208 | 121.7 |
| 1,000 | **trace** | **4,970** (−82%) | **1,119.7** (9.2×) |
| 10,000 | notrace | 20,568 | 255.3 |
| 10,000 | **trace** | **4,289** (−79%) | **1,619.6** (6.3×) |

An initial run of this benchmark with tracemalloc always on reported "5,429
ev/s" for 1,000 interpreters — a number that is ~5.4× too pessimistic and would
have produced a wrong verdict. Recorded because it is an easy trap.

### Findings

- **Aggregate throughput is flat in N, not per-interpreter.** ~20–28k ev/s
  *total* whether that is 1 machine or 1,000. Confirmed by `bench_b2_scaling.py`:

  | N | aggregate ev/s | per-interpreter ev/s |
  |---:|---:|---:|
  | 1 | 21,231 | 21,231 |
  | 10 | 20,305 | 2,031 |
  | 100 | 20,063 | 201 |
  | 500 | 19,323 | 38.6 |
  | 1,000 | 18,152 | **18.2** |

  **This is the single most important architectural fact in this study.** Every
  interpreter shares one asyncio event loop and one thread. Concurrency here is
  *interleaving, not parallelism*. Adding machines does not add capacity; it
  divides a fixed ~20k ev/s budget. Scaling is by **process**, not by machine count.
- **~21 KB Python heap / ~42 KB RSS per idle interpreter.** 10,000 interpreters
  cost ~450 MB resident. For CandleViewer's 500-order target this is trivial
  (~21 MB); it only becomes a constraint at 10k+.
- **`create_machine()` is expensive (~120–255 µs)** and was ~1.1 ms under
  tracemalloc. Building 10,000 machines took 2.5 s of pure startup.
  **Mitigation found:** the `MachineNode` **can be shared** across interpreters —
  `build_us_each` drops from ~325 µs to **17.3 µs (19× cheaper)** and context is
  **not** aliased between interpreters (verified explicitly:
  `interps[0].context is interps[1].context` → `False`, and all 1,000 machines
  independently reached exactly 101 processed events). Sharing the machine
  definition is safe and should be the default pattern.
- **`send_events()` batching gives nothing** (19,966 vs 18,152 ev/s at N=1,000).
  The bottleneck is transition processing, not enqueue.
- **~8 KB/interpreter RSS is retained after full teardown.** Investigated in
  `bench_i_retention.py`: **not a reference leak** — 0 live `Interpreter`
  objects after gc, empty `gc.garbage`. Growth decelerates across 5 cycles
  (10.5 → 3.5 → 2.0 → 3.5 → 3.0 MB), consistent with allocator arena retention.
  But it does **not fully flatten** — ~3 MB per 1,000-interpreter cycle persists.
  For a process churning thousands of order machines per day, budget headroom or
  plan periodic recycling. Not a blocker; worth watching.

---

## 3. (c) Timer precision — `after` at 10 ms / 100 ms / 1 s

Error = actual fire time − requested delay. Script: `bench_c_timers.py`.

| Scenario | 10 ms err (p50 / p95) | 100 ms err (p50 / p95) | 1 s err (p50 / p95) |
|---|---:|---:|---:|
| Idle | +5.7 / +7.0 ms | +11.1 / +15.1 ms | +10.5 / +14.2 ms |
| 100 busy interpreters | +511 / +612 ms | +474 / +530 ms | +456 / ~+500 ms |
| 500 busy interpreters | ~+2,250 / +2,530 ms | +2,285 / +2,530 ms | +2,157 / +2,521 ms |
| 500 busy + 2 CPU hogs | +1,962 / +2,745 ms | +1,858 / +2,363 ms | +1,791 / +2,157 ms |

### Findings

- **Idle accuracy is acceptable but not precise: +6 to +16 ms, always late.**
  Never early. On Windows the default event loop timer granularity is ~15.6 ms,
  so a 10 ms `after` **cannot** be honoured accurately — this is a platform
  floor, not purely the library's fault. **Do not build a 10 ms control loop on
  `after`.**
- **Under load, timers degrade catastrophically — and this is the headline
  risk.** With 500 busy interpreters, a 10 ms timer fires **~2.25 seconds
  late (225× the requested delay)**. Critically, *the absolute error is roughly
  constant regardless of the requested delay* (~2.2 s at 10 ms, 100 ms **and**
  1 s). That is the signature of **event-loop starvation**: the timer callback
  is queued on time but cannot be serviced because the loop is saturated
  processing the event backlog.
- **Timers and event throughput compete for the same single-threaded resource.**
  A TWAP slice scheduled with `after: 5000` will drift by seconds during a
  volatility burst — exactly when it matters most. For CandleViewer's emulated
  algos (TWAP intervals, chase repricing, iceberg clip release), **`after` is
  not safe as a timing source under load**. Use an external monotonic scheduler
  that computes deadlines from wall-clock and injects events, and keep `after`
  only for coarse, non-critical timeouts where seconds of lateness is tolerable.
- Note the CPU-hog row is *not worse* than the plain 500-interpreter row —
  the loop is already saturated; additional CPU pressure adds nothing.

---

## 4. (d) Snapshot + restore — nested/parallel machine, 2 KB context

3-region parallel machine (`execution`/`risk`/`reporting`) with a nested
compound substate, realistic ~2.1 KB order context. Script: `bench_d_snapshot.py`.

| Metric | Value |
|---|---:|
| Context JSON | 2,119 B |
| Snapshot JSON (as produced, `indent=2`) | 3,976 B |
| Snapshot JSON (compact, `separators=(',',':')`) | **2,249 B** |
| Structural overhead vs context | 130 B compact |
| `get_snapshot()` (JSON str) | 289.7 µs |
| `get_persisted_snapshot()` (dict) | 203.3 µs |
| `from_snapshot()` | 321.2 µs |
| restore + `start()` (resume) | 17.5 µs |
| **Restore 500 orders (projected)** | **169 ms** |

| Correctness check | Result |
|---|---|
| Active states round-trip (3 parallel regions + nested leaf) | ✅ exact |
| Context round-trip | ✅ exact |
| Transitions work after restore | ✅ |
| **Pending `after` timer survives restore** | ❌ **No** |

### Findings

- **Correctness is excellent.** A 3-region parallel configuration with a nested
  compound leaf round-tripped exactly. This is the hard case and it works.
- **Cost is acceptable for failover** — 500 order machines restore in ~170 ms.
  For *periodic* snapshotting it is less comfortable: at 290 µs each, snapshotting
  500 orders costs ~145 ms of loop time, which at ~20k ev/s is ~2,900 events of
  stalled throughput. Snapshot on state *change* rather than on a timer sweep,
  or snapshot in slices.
- **`get_snapshot()` hardcodes `indent=2`, inflating payloads 1.77×.** For a
  recorder writing per-order snapshots this is pure waste in disk and bandwidth.
  Use `get_persisted_snapshot()` + your own compact `json.dumps` — also 30% faster.
- **Pending `after` timers do not survive a restore** — verified: a machine
  snapshotted with 700 ms left on an 800 ms timer never fired after restore,
  even 1.5 s later. This *is* documented in the README, and it is the right
  default, but it means **CandleViewer must persist algo deadlines in context
  and re-arm them explicitly on recovery.** Combined with §3, this reinforces
  that timing must live outside the statechart.

---

## 5. (e) Actor spawn / teardown

Parent supervisor spawning child machines (the OCO-leg / TWAP-slice shape).
Script: `bench_e_actors.py`.

| Metric | 4 children | 50 children |
|---|---:|---:|
| Spawn µs/child (p50) | 102.6 | 133.0 |
| Spawn µs/child (p95) | 282.3 | 229.0 |
| Teardown µs/child (p50) | 31.6 | 29.2 |
| Teardown µs/child (p95) | 69.0 | 62.0 |
| All children registered in `system` | ✅ | ✅ |

| Parent→child forwarding (`sendTo`) | Value |
|---|---:|
| Messages | 10,000 |
| Delivered | 10,000 (100%) |
| Throughput | 13,207 msg/s |
| µs per forwarded message | 75.7 |

| Leak check (300 cycles × 10 actors) | Value |
|---|---:|
| RSS growth | 0.32 MB |
| Per actor | **0.11 KB** |

### Findings

- **Spawn ~100–130 µs, teardown ~30 µs, both flat in child count.** Cheap
  enough for per-leg actors. A 12-slice TWAP costs ~1.5 ms to stand up.
- **Actor teardown is clean — 0.11 KB/actor over 3,000 spawn/stop cycles.** No
  leak in the supervision path. This is the best-behaved subsystem measured.
- **Parent→child forwarding costs 75.7 µs/msg — 2.3× a direct transition
  (33 µs).** Routing through `sendTo` + the system registry is not free. A
  hierarchy that forwards every market tick through a parent would burn most of
  the throughput budget on routing. Fan out to children directly where possible.

---

## 6. (f) SyncInterpreter vs async Interpreter

Identical machine and event stream. Script: `bench_f_sync_vs_async.py`.

| Benchmark | Engine | ev/s | µs/event |
|---|---|---:|---:|
| Single, 50k events | **Sync** | **24,253** | 41.2 |
| Single, 50k events | Async | 19,399 | 51.5 |
| 1,000 machines × 100 events | Sync | 24,092 | 41.5 |
| 1,000 machines × 100 events | Async (from §2) | ~18,152 | 55.1 |

**Speedup of sync over async: 1.25×**

**Sync per-`send()` latency (µs)** — in the sync engine `send()` runs the full
transition inline:

| p50 | p95 | p99 | max |
|---:|---:|---:|---:|
| 35.2 | 78.9 | 110.4 | 436.3 |

### Feature probe

| Feature under `SyncInterpreter` | Result |
|---|---|
| `async def` service via `invoke` | ❌ `NotSupportedError: Service 'fetch' is async and not supported.` |
| `after` timer | ✅ **Fires without an event pump** (threaded timer) |

### Findings

- **Sync is only 1.25× faster than async — much less than expected.** The
  asyncio queue machinery is not the dominant cost; transition resolution is.
  This means **choosing sync for speed alone is not worth it**; choose it for
  *semantics* (inline, deterministic, no loop) where async services aren't needed.
- **`SyncInterpreter` rejects async services loudly and early** — a clean,
  correct failure with a clear message. Good design.
- **Surprise: `after` timers DO fire under `SyncInterpreter` with no event
  pump.** The machine advanced from `t.w` to `t.f` purely from a 200 ms
  `time.sleep()` on the main thread. That implies a background thread driving
  timers, which means **the "sync" engine is not actually single-threaded and
  its context can be mutated concurrently with the caller's code**. For
  CandleViewer's rule engine this is a real hazard: reading `interp.context`
  while a timer thread mutates it is unsynchronised. **Either avoid `after` in
  sync machines entirely, or treat sync context access as needing a lock.**
  This deserves an upstream question — it is not called out in the docs.

---

## 7. (g) Failure, cancellation, thread-safety, re-entrancy

Scripts: `bench_g_semantics.py`, `bench_g2_error_channel.py`.

| # | Probe | Result |
|---|---|---|
| g1 | Action raises | Machine survives, stays `running`, keeps accepting events. Remaining actions in that list skipped. |
| g2 | Guard raises | Treated as `False`; transition not taken; machine healthy. Documented behaviour. |
| g3 | Entry action raises at `start()` | `start()` **succeeds**, status `running`, state entered anyway. |
| g4 | Invoked service raises | ✅ `onError` reached, error payload propagated correctly. |
| g5 | Service cancelled by `stop()` | ✅ `CancelledError` delivered, `finally` ran, `stop()` returned in 0.15 ms (did not block on the 10 s sleep). |
| g6 | `send()` from another OS thread | Naive call silently does nothing (coroutine never awaited). `run_coroutine_threadsafe` works: 500/500 delivered, 336 µs/event. |
| g7 | Concurrent producers | ✅ Strict FIFO single-producer; 500/500 no loss; per-producer order preserved across 10 concurrent producers. |
| g8 | Re-entrancy — async `send()` inside an action | ✅ No deadlock. Order: `outer` → `inner`. Must use `create_task`. |
| g8b | Re-entrancy — sync `send()` inside an action | ✅ **Queued, not recursive**: `outer_start` → `outer_end` → `inner`. No `RecursionError`. |
| g10 | `send()` after `stop()` | Silently dropped (warns in log). Restart raises `InvalidConfigError` — correct, explicit. |
| g10 | Unknown event | ✅ Ignored, machine unaffected. |
| g11 | Sync engine, action raises | ❌ **Swallowed** — does not propagate to the `send()` caller. |

### 🔴 Critical finding — action failures are silent AND the transition still commits

`bench_g2_error_channel.py` isolates this. A transition with
`actions: ["first", "explode", "third"]` targeting state `b`, where `explode` raises:

| Observation | async engine | sync engine |
|---|---|---|
| Actions that ran | `first`, `explode_entered`, **`entry_b`** | same |
| Remaining actions in the list skipped | ✅ yes (`third` skipped) | ✅ yes |
| **Target entry action still ran** | ❌ **yes** | ❌ **yes** |
| **Transition rolled back** | ❌ **no** — ended in `err.b` | ❌ **no** |
| Status after | `running` | `running` |
| Exception propagated to caller | ❌ no | ❌ no |
| Plugin hook signalled an error | ❌ no — `on_transition` fired normally, as if successful |
| Only evidence | one `ERROR` **log line** | one log line |

The source confirms it (`base_interpreter.py`): the action handler catches
`Exception`, logs `"🔥 Action '%s' raised while handling event '%s'; skipping
remaining actions"`, and continues. There is a rollback path for *transition*
failures, but an action raising does not trigger it.

**Why this matters for CandleViewer specifically.** If `apply_fill` raises
partway — a bad decimal, a `None` price from a malformed exchange message —
the machine **still transitions to `filled`** while `context["filled"]` holds a
stale quantity. The order is marked complete with wrong position accounting,
`status` still reads `running`, `on_transition` reports a clean transition, and
the **only** signal is a log line. This is a silent position-corruption path on
the order-state machine.

**There is no programmatic error channel.** Confirmed: no exception, no error
event, no status change, no plugin hook, no subscriber notification. Verified
that a plugin's `on_transition` fires as if nothing went wrong.

**Mandatory mitigation if this library goes on the order path:**
1. Wrap **every** action body in try/except that, on failure, records the fault
   in `context` and sends an explicit `FAULT` event the machine handles by
   transitioning to a quarantine state. Never let an action raise.
2. Install a logging handler on `xstate_statemachine` at `ERROR` that raises an
   alert — treat any such log as a P1 reconciliation trigger.
3. Reconcile fills against the exchange independently. Do not treat the
   statechart as the book of record.

### Other findings

- **g3 is a related gap:** an entry action raising during `start()` does not
  fail the start. The interpreter reports `running` in a state whose entry
  logic never completed. Same silent-failure family as the above.
- **g5 cancellation is genuinely well-implemented** — clean cancellation
  delivery, `finally` honoured, `stop()` does not block. Notably `onError` does
  *not* fire on cancellation, which is correct (cancellation is not failure).
- **g6: cross-thread `send()` is a footgun.** `interp.send(...)` from a foreign
  thread returns a coroutine that is never awaited — **no exception, event
  silently lost**. CandleViewer's ingestion may have non-asyncio threads;
  every such call site must use `run_coroutine_threadsafe`. Wrap the
  interpreter in a helper that refuses bare cross-thread `send`.
- **g6 cost: 336 µs/event cross-thread** vs 33 µs in-loop — **10×**. Keep the
  hot path in-loop.
- **g7 ordering is solid** — strict FIFO, no loss, per-producer order preserved.
  This is the property an OMS most depends on, and it holds.

---

## 8. Direct test against CandleViewer budgets

Script: `bench_h_candleviewer_budgets.py`. These are shaped like the real
budgets rather than synthetic throughput.

### Budget 1 — order submit → ack p95 < 300 ms ✅ **PASS (with caveat)**

500 background order machines live and churning; 200 samples.

| Stage | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|
| `SUBMIT` → `submitted` | 65.3 ms | 94.6 ms | 110.5 ms | 141.9 ms |
| `ACK` → `open` | 63.6 ms | 94.2 ms | 107.5 ms | 184.0 ms |
| **Total submit → open** | **132.6 ms** | **165.6 ms** | 201.6 ms | 292.5 ms |

**Verdict: within the 300 ms budget, but only 1.81× headroom — and that is
before any network I/O.** The real budget includes a round trip to Bybit
(typically 50–150 ms). The engine consuming 165 ms of p95 on its own leaves
very little room. Note the max already touches 292 ms.

Critically, **this latency is not transition cost** (a transition is ~33 µs —
5,000× smaller). It is **queueing delay behind 500 other machines' events on
the shared event loop**. Compare §9 below where the same machines are idle:
fill latency drops to **0.06 ms p50 / 0.13 ms p95**. The budget is met or
missed entirely as a function of *event-loop contention*, not machine design.
Under a heavier burst than modelled here, this budget will break.

### Budget 2 — ~100 rules × ~10 symbols at up to 2,000 events/s ❌ **FAIL**

1,000 rule machines, each tick fanned out to the 100 rules watching that symbol.

| Engine | Rule evals/s | **Market events/s** | Budget | Meets? |
|---|---:|---:|---:|---|
| async Interpreter | 28,823 | **288** | 2,000 | ❌ |
| SyncInterpreter | 31,649 | **316** | 2,000 | ❌ |

**Verdict: misses the 2,000 ev/s budget by ~6.3–6.9×.**

The arithmetic is unavoidable: 2,000 market events/s × 100 rules per symbol =
**200,000 rule evaluations/s** required. Both engines deliver ~30,000/s. Even
allowing 3× for server-grade silicon, ~90,000/s still falls ~2.2× short.

**One machine per rule per symbol is not a viable architecture for this path.**
Options, in order of preference:
1. **Don't use a statechart for per-tick rule evaluation.** Use the statechart
   for rule *lifecycle* (armed → triggered → cooling-down → disarmed) and a
   plain predicate pass for the per-tick test. Statecharts earn their keep on
   lifecycle correctness, not on inner-loop arithmetic.
2. **Pre-filter before fan-out.** Most rules don't care about most ticks.
   Index rules by threshold band; evaluate only candidates. This can cut
   evaluations by 10–100× and makes the budget comfortable.
3. **Shard across processes.** Throughput is per-event-loop (§2), so N
   processes give ~N× — but this adds coordination the rule engine may not want.

Note sync and async are within 10% of each other here — switching engines does
not rescue this.

### Budget 3 — ~500 open order machines ✅ **PASS comfortably**

| Metric | Value |
|---|---:|
| All 500 reached `open` | ✅ |
| RSS cost of 500 open orders | **0.53 MB** |
| Per open order | **1.08 KB** |
| Fill latency p50 | **0.057 ms** |
| Fill latency p95 | **0.127 ms** |
| Fill latency p99 | 0.177 ms |
| Retained after teardown | 0.53 MB |

**Verdict: comfortable.** 500 resident order machines are essentially free in
memory, and fill-processing latency is microseconds when the loop is not
saturated. The per-order memory here (1.08 KB) is lower than §2's 42 KB because
these machines are quiescent rather than mid-burst with queued events.

> The contrast between Budget 1 (165 ms p95, loop busy) and Budget 3 (0.13 ms
> p95, loop idle) on the *same population* is the clearest statement of this
> library's performance model: **cost is dominated entirely by event-loop
> contention, not by the state machine.**

---

## 9. Overall verdict for CandleViewer

### Where it fits ✅

- **OMS per-order state machines (500 open orders).** Memory is negligible,
  latency is microseconds when the loop is healthy, ordering is strictly FIFO,
  snapshot/restore round-trips nested+parallel states exactly. This is the
  library's strongest use case and it maps directly to CandleViewer's OMS.
- **Trade-group / algo supervision via actors.** Spawn ~100 µs, teardown ~30 µs,
  zero leak over 3,000 cycles. Good fit for OCO legs and TWAP slices.
- **Failover/recovery.** 500 machines restore in ~170 ms with exact state and
  context fidelity.
- **Rule *lifecycle*** (armed/triggered/cooldown) — as distinct from per-tick
  evaluation.

### Where it does not fit ❌

- **Per-tick rule evaluation at 2k events/s × 100 rules.** Short by ~6.5×.
  Architectural change required (§ Budget 2), not a tuning problem.
- **Any timing-critical scheduling via `after`.** Under load, timers fire
  seconds late regardless of requested delay. TWAP intervals, chase repricing
  and iceberg clip release must use an external monotonic scheduler.
- **Sub-50 ms control loops.** Windows timer granularity alone (~15.6 ms) plus
  loop contention rules this out.

### Blocking issues to resolve before production

1. 🔴 **Silent action failure with committed transition** (§7). This is a
   position-corruption path. Requires the discipline in §7 *and* an upstream
   fix or explicit `onActionError` escalation hook. **Highest priority finding
   in this study.**
2. 🟠 **Single-event-loop ceiling ~20–30k ev/s** shared across *all* machines
   (§2). Capacity planning must be per-process, not per-machine. Decide the
   sharding model before building on this.
3. 🟠 **Timer starvation under load** (§3). Design timing out of the statechart.
4. 🟡 **Cross-thread `send()` silently loses events** (§7 g6). Wrap the API.
5. 🟡 **`SyncInterpreter` runs `after` timers on a background thread** (§6),
   making "sync" context access concurrent. Clarify upstream.
6. 🟡 **Disable the library logger explicitly** — INFO-level logging on every
   transition is a large multiple in production.

### Honest summary

The library is **correct where correctness is hardest** — parallel/nested
snapshot fidelity, FIFO ordering, service cancellation, re-entrancy, actor
teardown all passed cleanly, several of them more cleanly than expected. The
error-handling philosophy is the problem: it consistently prefers *staying
alive* over *failing loudly*, which is a defensible default for UI workflows
and the wrong default for an order path where a silently committed wrong
transition costs money. That single design choice, not performance, is the
real barrier to adoption.

On performance: it is fast enough per-transition (~33 µs) but the single
event-loop model means throughput is a **fixed global budget**, not something
that scales with machine count. Two of three CandleViewer budgets pass; the
rule-evaluation budget fails by a margin that no tuning will close and that
requires rethinking whether per-tick evaluation belongs in a statechart at all.

---

## Appendix — running the benchmarks

```bash
cd docs/research/xstate/bench
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e <path-to>/xstate-statemachine psutil

.venv/Scripts/python.exe bench_a_throughput.py           # (a)
.venv/Scripts/python.exe bench_b_many_interpreters.py    # (b) spawns subprocesses
.venv/Scripts/python.exe bench_b2_scaling.py             # (b) scaling probe
.venv/Scripts/python.exe bench_c_timers.py               # (c) ~10 min
.venv/Scripts/python.exe bench_d_snapshot.py             # (d)
.venv/Scripts/python.exe bench_e_actors.py               # (e)
.venv/Scripts/python.exe bench_f_sync_vs_async.py        # (f)
.venv/Scripts/python.exe bench_g_semantics.py            # (g)
.venv/Scripts/python.exe bench_g2_error_channel.py       # (g) error observability
.venv/Scripts/python.exe bench_h_candleviewer_budgets.py # budgets
.venv/Scripts/python.exe bench_i_retention.py            # memory retention
```
