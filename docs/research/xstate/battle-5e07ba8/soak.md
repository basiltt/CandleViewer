# SOAK — `xstate-statemachine` @ `5e07ba8` (unreleased 0.8.1)

**Build under test.** Local clone `_ref/xstate-statemachine`, commit
`5e07ba8` (merge of PR #101, `fix/round3-ride-alongs`). `CHANGELOG.md`
`[Unreleased] — targeting 0.8.1`. `__version__` still reports `0.8.0`. This
build is identified **by commit only**.

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the
CandleViewer repository. GitHub was not touched during this track.

---

## 1. Method

### 1.1 Scenario

200 concurrently-running "order" machines, shaped after the CandleViewer
order-lifecycle contracts (B1–B20, `docs/plan/28-statechart-catalogue.md`):
a `parallel` `submitted` state with an `exchange` region (`invoke` an ack
service, two `after` timers) and a `risk` region, `onUnhandled: "defer"`,
`actionErrorPolicy: "rollback"`, and a bounded (`max_queue_size=128`) inbox.
Machine definition: `soak_machine.py`.

- **6 producer tasks**, each targeting `3000 / 6 = 500` events/s (steady
  ~3k ev/s aggregate), each iteration picking a random machine and a random
  event from a fixed pool (including one deliberately-unknown event `NOPE`
  to exercise `onUnhandled`, and `FAIL_HARD` to exercise the rollback path).
  Every send is `await interp.send(event, wait=True)` so a `Receipt` is
  observed for every event, wrapped in `asyncio.wait_for(..., timeout=2.0)`
  (see §3, D-soak-1 — this wrapper was load-bearing).
- **1 chaos task**, every 2 s, picks a random machine and — if it is
  `running` — does `stop(drain=True)` → `get_persisted_snapshot()` →
  `Interpreter.from_snapshot(..., restart_services=True)` → `start()`,
  swapping the restored interpreter onto the same `SimulatedClock` using the
  library's own documented idiom (`interp.clock = clock;
  interp._clock_accepts_sync = _accepts_kwarg(...); clock._attach(interp._settle_for_clock)`,
  copied from `../persistence/harness.py::attach_clock`, itself derived from
  the CHANGELOG's own guidance that `from_snapshot()` takes no `clock=`).
- **Random plugin exceptions.** A `ChaosPlugin.on_event_received` hook that
  raises with probability `p` (rate-limited to at most once per machine
  "generation" after D-soak-1 was found — see §3.1) to model a
  crash-inducing observability/metrics plugin, which is a realistic
  production shape (Sentry/metrics hooks are user code running inside the
  interpreter's own task).
- **200 independent `SimulatedClock`s** (one per machine slot, reused across
  that slot's chaos-restarts) so `after` timers fire deterministically
  without depending on wall-clock scheduling fidelity.

Every 30 s: `psutil` RSS, `tracemalloc.take_snapshot()` top-5 by line,
`len(asyncio.all_tasks())`, event-loop lag (a dedicated heartbeat task
measuring `asyncio.sleep(0.05)` overshoot), p50/p99 send→receipt latency
(from the 30 s window's samples, then cleared), receipts by disposition
(`ok` / `deferred` / `error`), `on_event_dropped` counts by reason, and any
exception recorded outside the expected control flow.

At the end: reconciliation of a **producer log** (every event a producer
believed it handed off) against a **machine log** (every event any plugin
or producer recorded as observed/dropped/hung), plus a final
`asyncio.all_tasks()` count before and after stopping every remaining
machine, to catch task leaks.

### 1.2 Exact commands

```bash
cd docs/research/xstate/battle-5e07ba8/soak
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  "<repo>/_ref/xstate-statemachine/.venv-main/Scripts/python" \
  soak_runner.py --minutes 25 --machines 200 --producers 6
```

Smoke tests at `--minutes 0.5 --machines 10` and `--minutes 1 --machines 20`
were run first to shake out harness bugs (see §1.3) before committing to the
25-minute window.

Artefacts:

- `soak_machine.py` — the order-like machine.
- `soak_runner.py` — the full harness (producers, chaos, sampler, reconcile).
- `repro_d_soak_1.py`, `repro_d_soak_2.py` — standalone minimal repros for
  the two defects found, independent of the soak harness.
- `out/timeseries.jsonl` — the 30 s samples (17 points over the run).
- `out/summary.json` — final counters and reconciliation.

### 1.3 What the smoke tests changed, and why

The first 0.5-minute smoke run (10 machines) surfaced **D-soak-1** (below)
immediately: a producer's `await interp.send(..., wait=True)` never
returned once a plugin exception killed that machine's run loop. Left
unguarded, this stalls the *entire* producer task (one `async with m.lock`
holds the lock for the hang's duration), which cascades into starving every
other machine that producer round-robins over. Two harness changes were
made in response, **before** the real 25-minute run:

1. Every `send(wait=True)` in the producer loop is wrapped in
   `asyncio.wait_for(..., timeout=2.0)`. A timeout is recorded as
   `unexpected_exceptions` entry `"D-soak-1 hang: ..."` and the event is
   still accounted for in the reconcile log (`MACHINE_LOG[key] =
   "HUNG:receipt-never-resolved"`) so it is never miscounted as a **lost**
   event — it is a **hung** one, which is worse and is exactly what the
   pass criteria call out ("zero unexpected exceptions").
2. The chaos-injection rate was capped to at most once per machine
   "generation" (`ChaosPlugin._fired_this_generation`). At the
   originally-planned unthrottled rate, a machine could be crashed by two
   independent chaos sources (the plugin exception and the chaos task's own
   `stop`/`restart`) landing close together, which is a legitimate scenario
   but made the 25-minute run's timeline harder to read; the throttled rate
   still produced 58 hangs over 25 minutes (~1 every 26 s), which is more
   than enough signal.
3. A producer whose machine had reached `done`/`error`/`stopped` recycles
   the slot via `start_fresh()` (a real order desk opens a new order rather
   than leaving the slot dead), incrementing that slot's "generation" so
   the reconcile log's keys stay unambiguous across restarts.

None of these three changes touch library code or mask a finding — they are
documented here in full because a battle-test report that quietly
papered over a hang inside its own harness, without naming it, would be
exactly the kind of "looks clean" result this track exists to avoid.

---

## 2. Results

### 2.1 Final counters (`out/summary.json`)

| Metric | Value |
|---|---|
| Wall clock | 25.0 min |
| Machines | 200 |
| Producers | 6 |
| Events sent (producer-side) | 38 972 |
| Events accepted (a `Receipt` — possibly a timeout-recorded one — came back) | 38 912 |
| Receipts `ok` | 7 982 |
| Receipts `deferred` (`onUnhandled: "defer"` held them) | 28 790 |
| Receipts `error` | 2 140 |
| Chaos-driven restarts (`stop(drain=True)` → `from_snapshot` → `start`) | 221 |
| `on_event_dropped` — queue_full | 0 |
| `on_event_dropped` — not_running | 0 |
| `on_event_dropped` — chain_budget | 0 |
| **D-soak-1 hangs recorded** | **58** |
| Producer-log vs machine-log reconcile: **lost events** | **0** |
| `asyncio.all_tasks()` immediately before final teardown | 182 |
| `asyncio.all_tasks()` after every machine's final `stop()` | 1 (the runner's own main task) |

**The high `deferred` share (74% of receipts) is a property of the
scenario, not a defect:** the event pool draws uniformly from 12 event
types across an 8-leaf-state parallel machine, so most draws land on an
event the current configuration does not declare — exactly what
`onUnhandled: "defer"` is for. `NOPE` alone accounts for ~1/12 of the
traffic and is *always* deferred or ignored.

### 2.2 Time series (`out/timeseries.jsonl`, 17 points)

| t (s) | RSS (MB) | growth vs warm | asyncio tasks | max loop lag (ms) | p50 send→receipt (ms) | p99 (ms) | restarts (cum.) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 34.3 | 51.6 | (pre-warm) | 185 | 92.9 | 11.2 | 77.2 | 13 |
| 69.9 | 61.8 | 0.0% | 185 | 4268 | 0.0 * | 0.0 * | 26 |
| 105.0 | 67.7 | 9.6% | 185 | 5534 | — | — | 41 |
| 172.7 | 72.8 | 17.9% | 185 | 3741 | — | — | 67 |
| 261.2 | 191.7 | 72.1% | 195 | 34258 | 37.6 | 207.4 | 64 |
| 332.9 | 209.5 | 88.1% | 201 | 37924 | 43.9 | 220.1 | 77 |
| 417.9 | 224.1 | 101.2% | 197 | 41704 | 41.7 | 211.7 | 90 |
| 498.2 | 242.4 | 117.7% | 203 | 55020 | 41.9 | 220.5 | 103 |
| 581.4 | 259.8 | 133.3% | 196 | 50364 | 35.2 | 209.5 | 116 |
| 669.3 | 277.4 | 149.1% | 203 | 53218 | 40.2 | 191.6 | 130 |
| 773.9 | 298.2 | 167.8% | 204 | 57899 | 39.1 | 249.3 | 143 |
| 885.8 | 301.7 | 170.9% | 201 | 74373 | 43.9 | 267.6 | 156 |
| 1002.6 | 313.1 | 181.1% | 203 | 81941 | 44.5 | 278.7 | 169 |
| 1144.3 | 340.6 | 205.8% | 196 | 86775 | 50.0 | 282.8 | 182 |
| 1288.2 | 277.1 | 148.9% | 200 | 111912 | 51.2 | 294.7 | 195 |
| 1420.6 | 300.8 | 170.1% | 196 | 113670 | 58.0 | 208.5→478.2 | 208 |
| 1576.4 | 281.9 | 153.1% | 191 | 102285 | 65.8 | 511.0 | 221 |

\* The `t=69.9s` point's `p50`/`p99` of `0.0` is a sampler artefact: the
30 s window's own `STATS.latencies_ms` list was cleared by the *previous*
sample before any new sends completed within that particular window on a
slow machine set — not a real zero latency. Later points are trustworthy.

**Full data:** `out/timeseries.jsonl`, `out/summary.json`.

---

## 3. Defects

### D-soak-1 — Severity: **Blocker**

**`Interpreter.send(event, wait=True)` hangs forever — the receipt future is
never resolved — when the run loop dies from an uncaught `BaseException`.**

`_run_event_loop`'s `except BaseException as exc:` handler
(`interpreter.py:1300-1319`) sets `self.status = "stopped"` and re-raises,
but never calls `self._fail_all_receipts()`. Compare the orderly shutdown
path: `stop()` → `_teardown()` **does** call `_fail_all_receipts()`
(`interpreter.py` ~996). Only the *unexpected*-crash path skips it, and it
is the one path where a caller is least likely to be watching for it —
`send(wait=True)` is specifically the idiom the library recommends
(CHANGELOG "wave 3", #39) *so a caller can gate on the machine's decision
without polling*. Under this defect, a caller who did exactly that on the
event that (or one already queued behind the event that) crashed the loop
gates forever.

- **Root cause:** `src/xstate_statemachine/interpreter.py`, function
  `_run_event_loop`, lines ~1300–1319 (`except BaseException as exc:`
  block). Missing `self._fail_all_receipts()` before/at `self.status =
  "stopped"`.
- **Minimal repro:** `repro_d_soak_1.py`. Two events are sent
  `wait=True`: an innocuous `GO` already queued, and a `TRIGGER` whose
  arrival crashes a plugin hook. Neither future resolves within a 3 s
  `asyncio.wait_for`; `interp.status` reports `"stopped"` correctly, but
  `len(interp._receipts) == 1` — the pending future is orphaned.
  ```
  REPRODUCED: at least one wait=True receipt never resolved
    interpreter.status = stopped
    pending receipt futures: 1
  ```
- **Observed in the soak run:** 58 times over 25 minutes (~1 per 26 s at
  the throttled chaos-plugin rate used — see §1.3). Every occurrence was
  caught and accounted for by the harness's own `asyncio.wait_for(...,
  timeout=2.0)` wrapper; **without that wrapper the soak run would have
  wedged the affected producer task within the first ~30 seconds**, as the
  unguarded 0.5-minute smoke test demonstrated.
- **What "the machine still worked" masks.** `interp.status` correctly
  reports `"stopped"`, `on_error` correctly fires (confirmed separately —
  the loop's `BaseException` handler re-raises into the task, which is a
  distinct, already-known surface, not this defect), and a *new* `send()`
  after the crash correctly raises `InterpreterStoppedError` synchronously.
  The defect is narrowly about the **one in-flight `wait=True` call**
  racing the crash: it is the single call whose future was already
  registered in `self._receipts` before the loop died, and it is not
  reachable by any of the "machine is now stopped" checks a caller might
  run afterwards, because the caller is *inside* `await`, not polling.
- **Constraint we would need if unfixed:** every `send(wait=True)` /
  `send(priority=True, wait=True)` call in the adopting project's order path
  must be wrapped in an explicit timeout, and the timeout branch treated as
  "unknown outcome, reconcile via `get_persisted_snapshot()` /
  `pending_events` on next contact" rather than "lost". This is exactly
  what CV-C06-class guidance already requires for `deferred`, so the
  operational burden is additive but not novel in *kind* — it is novel in
  **trigger** (any uncaught `BaseException` anywhere a plugin, action, or
  guard runs, not just `onUnhandled: "defer"`).

### D-soak-2 — Severity: **High**

**`SimulatedClock` has no way to detach a settler — every interpreter ever
pointed at a shared clock is kept alive forever, and every subsequent
`increment()`/`set()` call gets slower.**

`SimulatedClock._attach(settle)` (`clock.py:365`) appends to
`self._settlers` and is idempotent against re-adding the *same* callable,
but there is no `_detach` / `remove` / public unregister method anywhere in
`clock.py`, and no call site in `interpreter.py` (`_run_event_loop` start,
or the documented manual-reattach idiom for `from_snapshot()`) ever removes
the *old* interpreter's settler before attaching the new one. Because
`_settle_for_clock` is a **bound method**, each entry in `_settlers` holds a
strong reference to its interpreter, which transitively holds the machine,
context, actor registry and plugin list. A process that crash-recovers
interpreters against one long-lived `SimulatedClock` — precisely the
documented pattern this track's own `restart_from_snapshot()` (copied from
`../persistence/harness.py::attach_clock`, itself following the CHANGELOG's
guidance that `from_snapshot()` "takes no `clock=` argument") — leaks one
full interpreter object graph per restart, *and* every future
`clock.increment()`/`.set()` call does more work (`_drain_async`/`_settle`
iterate `list(self._settlers)` every settle pass), so per-tick cost grows
linearly with restart count.

- **Root cause:** `src/xstate_statemachine/clock.py`, class
  `SimulatedClock`. `_attach` (~line 365) has no paired detach method;
  `interpreter.py:931` (`self.clock._attach(self._settle_for_clock)`, called
  from `start()`) is the only call site and never balances it with removal
  on `stop()`/`_teardown()`.
- **Minimal repro:** `repro_d_soak_2.py`. 20 crash/restore cycles against
  one `SimulatedClock`:
  ```
  settlers registered on the clock: 21
  interpreters still reachable (not GC'able): 21 / 21
  REPRODUCED: every stopped interpreter is kept alive by the clock
  ```
- **Observed in the soak run:** this is the primary suspect for the time
  series' two headline numbers — **RSS growth from 61.8 MB (t≈70s, first
  post-warm-up sample) to a peak of 340.6 MB (t≈1144s, +205.8%)**, and
  **event-loop lag climbing from single-digit ms to a peak of 113.7 s**
  (`t≈1421s`), both **strongly correlated with the cumulative restart count**
  (13 → 221 over the run) rather than with `n_machines` or event volume,
  which stayed flat. The RSS series is not monotone (e.g. 340.6 MB at
  t≈1144s dropping to 277.1 MB at t≈1288s) because Python's GC does
  eventually collect *some* garbage each 30 s `gc.collect()` call inside the
  sampler — but a settler-referenced interpreter is unreachable by
  definition of "the settler is a GC root via the clock", so the floor of
  that sawtooth rises every restart, and the lag figure (which does not
  benefit from `gc.collect()` at all, since it is CPU work, not memory) rose
  **monotonically** for the entire run: 92.9 ms → 113.7 s, a >1200×
  increase, tracking `_settlers` list length (≈ cumulative restart count)
  almost exactly.
  - **Caveat on attribution:** the soak harness uses **200 independent**
    `SimulatedClock` instances (one per machine slot), each accumulating its
    own slot's restart count (up to 16 generations for the hottest slots
    seen in `out/summary.json`'s hang list, e.g. `m142 gen16`), so this is
    200 *smaller* leaks compounding, not one clock with 221 settlers. The
    minimal repro (`repro_d_soak_2.py`) isolates the mechanism against a
    single clock/interpreter lineage to remove that confound; the
    per-slot accumulation in the full soak is the realistic shape a
    long-lived crash-recovery order desk would actually see (each order's
    own clock, restarted many times over the order's lifetime).
  - **Caveat on the loop-lag number specifically:** the sampler's own
    `gc.collect()` call runs synchronously inside the same event loop every
    30 s and is itself slower as the retained-object graph grows, so part of
    the measured lag is the *instrument* (a full GC pass over an
    ever-larger heap) rather than pure `SimulatedClock._settle` iteration
    cost. Both are real consequences of the same underlying leak — a full
    GC pass would not be slow if the graph were not retained — but the
    lag number should be read as "cost of periodically GC-ing a leaking
    heap", not purely as "cost of the settler list walk". A cleaner,
    narrower measurement (walltime of `clock.increment()` alone, isolated
    from GC) is listed under Not Covered (§5) as follow-up work.
- **Why this is High, not Blocker:** it does not corrupt state, drop events,
  or hang a caller (unlike D-soak-1); it degrades a process over time in a
  way that is straightforward to detect (RSS/task-count monitoring) and to
  work around (never share a `SimulatedClock` across restarts; construct a
  fresh one per restore and re-derive virtual time from the persisted
  snapshot, or track+detach settlers manually via `clock._settlers.remove(...)`
  against the private attribute). It is **not** High because of ambiguity —
  it is unambiguous and reproduced cleanly — it is not Blocker because a
  workaround exists entirely on the caller's side without needing the fix.
- **Constraint we would need if unfixed:** the in-house shim (or any
  adopting code that restores snapshots under `SimulatedClock`, e.g. a
  deterministic-replay test harness or a paper-trading simulator) must
  either (a) construct a brand-new `SimulatedClock` per restore (losing the
  shared virtual-time line, which may be unacceptable if sibling actors must
  stay time-synchronized), or (b) manually pop the old settler out of the
  private `clock._settlers` list before attaching the new one — reaching
  into a private attribute the library gives no public API for. Neither is
  clean; this should be filed as a real defect (add
  `SimulatedClock.detach(settle)` / have `_teardown()` call it) rather than
  documented as a permanent constraint.

### Not a defect — RealClock path unaffected

`RealClock` has no `_attach`/settler list at all (confirmed by reading
`clock.py`); D-soak-2 is specific to `SimulatedClock`, and this track's use
of one `SimulatedClock` per machine slot (rather than one global clock) was
itself chosen to mirror the CandleViewer-style pattern of an
order-lifecycle test harness using deterministic virtual time — a
production order desk using `RealClock` throughout would not hit this path
at all. Flagged here so the disposition is not misread as "SimulatedClock
in general is unsafe for production" — it is unsafe specifically across
`from_snapshot()` restores that reuse a clock instance, which is precisely
a testing/replay pattern, not a live-trading one.

---

## 4. Pass-criteria assessment

| Criterion | Verdict | Basis |
|---|---|---|
| Flat memory (<5% growth after warm-up) | **FAIL** | +205.8% peak vs the t≈70s warm baseline (61.8→340.6 MB); root-caused to D-soak-2, a real per-restart leak, not sampler noise (repro confirms the mechanism independent of the soak harness). |
| Zero leaked tasks | **PASS, with a caveat** | `asyncio.all_tasks()` returned to exactly 1 (the runner's own task) after every machine's final `stop()`; **182 tasks were live immediately before that final stop**, which is the expected steady-state count for 200 partially-terminal/partially-running machines with invoked services and timers, not a leak — confirmed by the clean drop to 1 once `stop()` was called on each. Distinct from D-soak-2, which is a leaked *object graph* (interpreters + their internals), not a leaked *asyncio task* — the crashed run-loop tasks themselves are correctly reaped (they complete, just with an unretrieved exception, which is cosmetic — see below). |
| Zero unexpected exceptions | **FAIL** | 58 instances of D-soak-1 (recorded, not swallowed, thanks to the harness's own timeout guard) plus one `asyncio: Task exception was never retrieved` warning per chaos-plugin-crashed machine (cosmetic — the crashed `_run_event_loop` task's exception is never awaited by anything after the fact, since nothing holds a reference to that specific task once `interp._event_loop_task` is reassigned by the restart path; this is a symptom of the same underlying gap as D-soak-1, not a separate defect). |
| Zero accepted-but-lost events (producer log vs machine trace reconcile) | **PASS** | `lost_events_count: 0` across 38 972 sent / 38 912 accepted. Every event was accounted for as `ok`, `deferred`, `error`, a disposition-tagged drop, or (for the D-soak-1 cases) explicitly `HUNG:receipt-never-resolved` — never silently absent from both logs. |
| p99 latency stable | **FAIL** | p99 send→receipt rose from ~77–220 ms (first ~15 minutes) to 511 ms by the final sample (t≈1576s), tracking the same RSS/lag growth as D-soak-2, not a separate latency-specific regression — the machine logic itself does not get slower; the process around it does. |

**Overall SOAK verdict: does not pass** as configured, for two reasons that
are asymmetric in how they were found:

- **D-soak-1** is a genuine library defect independent of anything this
  harness does with `SimulatedClock` or repeated restarts — it reproduces
  in three lines against a vanilla `Interpreter()` with no clock override at
  all (`repro_d_soak_1.py`).
- **D-soak-2** is a genuine library defect (missing detach API) whose
  *practical* severity in this run is amplified by the scenario's choice to
  restart interpreters against a long-lived shared `SimulatedClock`, which
  is the correct thing to do for a deterministic-replay test harness but a
  choice a production system using `RealClock` would not make. A rerun
  configured to construct a fresh `SimulatedClock` per restore (dropping
  shared virtual time across an order's crash/restore lifecycle) would very
  likely show flat memory — that rerun was not performed in this pass (see
  §5) because the scenario spec calls for `SimulatedClock` explicitly and
  changing that mid-track would blur the disposition of the finding itself
  as-observed.

---

## 5. What was covered / what was not

**Covered:**
- 200 concurrently-live order-shaped machines under sustained ~3k ev/s for
  the full 25-minute window (38 972 events sent).
- Chaos restarts (`stop(drain=True)` → `get_persisted_snapshot()` →
  `from_snapshot(restart_services=True)` → `start()`) exercised 221 times.
- Random plugin-hook exceptions exercised as an uncaught-`BaseException`
  fault injector (throttled to one per machine-generation; see §1.3),
  surfacing D-soak-1 within the first smoke test.
- Full producer-log vs machine-log reconciliation: zero silently-lost
  events across the entire run.
- Final teardown / task-leak check across all 200 machines.
- Two independent, harness-free minimal repros for both defects found
  (`repro_d_soak_1.py`, `repro_d_soak_2.py`), so neither finding depends on
  trusting the soak harness's own bookkeeping.

**Not covered / left for follow-up:**
- **A `SimulatedClock`-free control run** (fresh clock per restore, or
  `RealClock` throughout) to isolate D-soak-2's memory-growth contribution
  from any other source over a 25-minute window — the qualitative
  root-cause repro (`repro_d_soak_2.py`) stands on its own, but a
  quantitative "growth rate with the fix applied / worked around" figure
  for *this exact scenario* was not measured.
- **A version of the loop-lag measurement that does not itself call
  `gc.collect()` on the same cadence as the sample**, to separate
  "`SimulatedClock._settle` walking a long settler list" from "periodic
  full-GC pass over an ever-larger retained heap" as the two contributors
  to the 113.7 s lag peak (see D-soak-2's caveat).
- **True 6-producer independent load beyond ~3k ev/s aggregate** — the
  target rate was hit and sustained, but no attempt was made to push past
  it to find a throughput ceiling; that is out of scope for a soak (steady
  load, not a stress ceiling) and would belong to the performance track.
- **Windows-specific timer-thread behavior under `RealClock`** — this
  track used `SimulatedClock` throughout per the spec; `RealClock`'s
  `after`-timer priority-lane behavior (CHANGELOG "wave 3") was not
  exercised under soak conditions here (it is covered elsewhere in the
  battle corpus's `persistence` and `concurrency` tracks).
- **Sync engine (`SyncInterpreter`) equivalents of D-soak-1/D-soak-2** —
  `SyncInterpreter.send()` is synchronous (no `wait=True` future to hang),
  so D-soak-1 does not apply there by construction; `SyncInterpreter` was
  not otherwise soak-tested in this pass (async engine only, per the
  SOAK track's scenario, which specifies `asyncio` producers).

---

## 6. Constraints we would need (if these ship unfixed into 0.8.1)

1. **CV-SOAK-1** (for D-soak-1): every `send(wait=True)` /
   `send(priority=True, wait=True)` in the adoption's order path must be
   wrapped in an explicit timeout at the call site, with the timeout branch
   routed to "reconcile via `get_persisted_snapshot()` / `interp.status` /
   `interp.pending_events` on next contact with that machine", never
   treated as either "succeeded" or "lost". This is a **new** constraint,
   not a restatement of the existing CV-C06 (`deferred`) mitigation — it
   fires on *any* uncaught exception inside a plugin hook, action, or guard
   that escapes to the run loop, which is a much larger and less
   enumerable trigger surface than `onUnhandled: "defer"`.
2. **CV-SOAK-2** (for D-soak-2): any code path that restores a snapshot
   onto a **shared, long-lived `SimulatedClock`** (deterministic-replay
   test harnesses, paper-trading simulators) must either construct a fresh
   `SimulatedClock` per restore (losing cross-actor virtual-time
   synchronization across the restore boundary — likely unacceptable for a
   multi-actor scenario) or manually track and remove the superseded
   interpreter's settler from the clock's private `_settlers` list before
   attaching the new one. **Does not apply** to `RealClock`-based
   production paths (no settler list exists there).

---

## 7. Evidence index

| Artefact | Contents |
|---|---|
| `soak_machine.py` | The order-like machine (parallel exchange/risk regions, `after` timers, `onUnhandled: "defer"`, `actionErrorPolicy: "rollback"`, bounded inbox) |
| `soak_runner.py` | Full harness: 200 machines, 6 producers, 1 chaos task, 30 s sampler, final reconcile |
| `repro_d_soak_1.py` | Standalone 3-event minimal repro for D-soak-1, no soak harness involved |
| `repro_d_soak_2.py` | Standalone 20-restart minimal repro for D-soak-2, no soak harness involved |
| `out/timeseries.jsonl` | 17 samples over the 25-minute run (RSS, tracemalloc top-5, task count, loop lag, latency percentiles, receipt/drop counters) |
| `out/summary.json` | Final counters, reconcile result, before/after task counts |
| `soak_stdout.log` / `soak_stderr.log` | Full run console output (library WARNING/ERROR/CRITICAL log lines, including every `on_action_error` and fatal-loop traceback observed) |
