# Contract machines B1–B5, end-to-end on `221ce7c`

**Track:** CONTRACT MACHINES END-TO-END · **Commit:** `221ce7c` (unreleased
0.8.1; `__version__` still reports 0.8.0) · **Engines:** async primary, sync
parity · Fresh venv.

## Scope

Five contract machines from the corrected catalogue JSON
(`battle-cec108b/contracts/<B>.machine.json`), driven under the mandatory
configuration for this track:

| Knob | Value |
|---|---|
| `actionErrorPolicy` | `rollback` |
| `onUnhandled` | `defer` (order path) |
| `guardErrorPolicy` | `raise` |
| `strictTargets` / `strict` | `true` / `true` |
| inbox | `max_queue_size=64`, `OverflowPolicy.RAISE` |
| clock | `SimulatedClock` |
| plugins | `CvHooks` (CvErrorHooks-equivalent stub, every hook recorded) |

Each machine: `create_machine` build, happy path, every catalogue invariant,
the round-5/6 OC fixes, an explicit exercise of the **R6-03 class**
(`rollback` + `invoke.onDone`) and the **R6-01 class** (`always` into an
invoked child), snapshot/restore at quiescence between **every** macrostep with
trace comparison, and sync parity.

| Machine | Checks | Fail |
|---|---|---|
| B1 Order (parallel: lifecycle ∥ protection) | 34 | 0 |
| B2 TradeGroup | 23 | 0 |
| B3 TradeGroupLeg | 21 | 0 |
| B4 OCO + B5 Iceberg | 34 | 0 |
| **Total** | **112** | **0** |

All five build clean — **no `InvalidConfigError`**, so no our-contract defect
on the build axis. Results: `res_b1.json`, `res_b2.json`, `res_b3.json`,
`res_b45.json`.

> The 112 assertions are the *contract* assertions. Two of them were written
> as observation-only recorders (`B1.R6-03.duplicate_orders_placed`,
> `B5.R6-03.observed`) precisely because the behaviour they record is the
> finding below — they pass by construction and must not be read as green.

## Findings

| # | Class | Severity | Summary |
|---|---|---|---|
| **C221-01** | **LIBRARY** | **Blocker** | The round-6 chain budget (#166/#167/#168) charges only when the invoked service is a plain `def`. An `async def` service escapes the budget entirely: no `RunawayChainError`, no `chain_budget` drop, unbounded spin. |
| C221-02 | NEEDS-WRAPPER | Medium | `SyncInterpreter` accepts neither `max_queue_size` nor `overflow_policy` — the bounded RAISE inbox mandated for the order path is async-only. |
| C221-03 | NEEDS-WRAPPER | Low | `get_persisted_snapshot()` returns a `dict`, but `from_snapshot()` refuses a dict (`SnapshotCorruptError: must be a JSON string`). The persist/restore pair does not compose without an explicit `json.dumps`. |

Everything else on the contract surface behaved to specification — see
*Passing invariants* below.

---

## C221-01 — chain budget is not charged for `async def` services (LIBRARY, Blocker)

### What the CHANGELOG claims

> Every self-generated cycle is bounded on `Interpreter`. … A completion the
> machine produced *while processing* (a rollback that re-armed an invoke,
> #167; an invoke ping-pong `ver -> arm -> ver`, #168) is charged to the chain
> budget … The invoke cycle now trips at the same lap count on both engines.

### What reproduces

Every round-6 test that pins this (`tests/test_round6_findings.py`
`TestAsyncRollbackRearmCycleBounded`, `TestAsyncInvokeCycleTrips`, and the
#166 case) defines its service as a **plain `def`**. Switching that one
declaration to `async def` — changing nothing else — removes the bound.

`repro_166_168_axes.py`, the library's own two pinned configurations, run
under the track's mandatory interpreter config, `maxIterations: 50`:

```
{"case": "#168 invoke ping-pong", "service": "plain def",
 "laps@1s": 52,    "laps@3s": 52,    "still_growing": false,
 "last_error": "RunawayChainError", "drops": ["chain_budget"]}

{"case": "#168 invoke ping-pong", "service": "async def",
 "laps@1s": 10880, "laps@3s": 32046, "still_growing": true,
 "last_error": "NoneType",          "drops": []}

{"case": "#166 always-into-invoked-child", "service": "plain def",
 "laps@1s": 51,    "laps@3s": 51,    "still_growing": false,
 "last_error": "RunawayChainError", "drops": []}

{"case": "#166 always-into-invoked-child", "service": "async def",
 "laps@1s": 285,   "laps@3s": 877,   "still_growing": true,
 "last_error": "NoneType",          "drops": []}
```

`maxIterations: 50` is honoured to the lap for `def` and ignored entirely for
`async def`. In the `async def` runs `status` stays `"running"`, `last_error`
is `None`, and **no** `on_event_dropped` fires — the loop is silent.

### The #167 rollback shape, minimally

`repro_r603_min.py` — a 12-line machine, no catalogue involved:

```
idle --GO--> work          work invokes `svc`
work.invoke.onDone --> done, actions: ["bad"]   # `bad` raises
actionErrorPolicy: rollback  ->  back to `work` -> invoke re-arms -> ...
```

```
{"engine":"async","send":"returned in 0.000s","states":["m.work"],
 "status":"running","error":null,"last_error":"RuntimeError('boom')",
 "svc_after_1s":1292,"rate_per_s":1292.0}
{"engine":"async", ... "svc_after_3s":3996,"rate_per_s":1332.0}
{"engine":"sync",  "send":"returned in 0.002s","states":["m.work"],
 "status":"running","last_error":"RuntimeError('boom')","svc":2}
```

`send()` returns a receipt immediately — this is not the R6-01 hang — and the
machine then spins at ~1330 invocations/s for as long as the loop lives. The
sync engine stops at 2. `last_error` carries the *action's* `RuntimeError`,
never a `RunawayChainError`, so the documented
"`(denied, error is None)` discriminates" signal cannot distinguish a
one-shot rollback from a runaway.

### Axis isolation

`repro_167_axes.py` varies entry-path and service-kind independently:

```
initial state  / plain def : svc@1s 1003  svc@3s 1003  RunawayChainError  chain_budget
initial state  / async def : svc@1s 1402  svc@3s 4275  RuntimeError       (no drops)
external send  / plain def : svc@1s 1002  svc@3s 1002  RunawayChainError  chain_budget
external send  / async def : svc@1s 1441  svc@3s 4317  RuntimeError       (no drops)
```

The entry path is irrelevant. `repro_167_delta.py` additionally rules out the
raise *site* (target-state `entry` vs `onDone` transition `actions`) — both
bound identically at ~1003 with a `def` service. `repro_167_knobs.py` rules
out `SimulatedClock`, `max_queue_size` and `OverflowPolicy.RAISE` — all four
knob combinations bound at 1003 with a `def` service.

**The service declaration is the only variable that matters.**

### Why this is a blocker for an OMS

The contracts reach this shape on their own, with their real service kind
(every exchange call is `async def`):

| Machine | Trigger | Observed |
|---|---|---|
| B1 Order | `adopt_ack` raises on `place_order.onDone` → rollback to `submitting` | **74 `place_order` calls** in the drive window, `status=running`, `error=None` |
| B2 TradeGroup | `mark_unwound` raises on `unwind_machine.onDone` | 3220 `unwind_machine` invocations over 3 s and still climbing (`p_r603.py`) |
| B3 Leg | `note_cancel_failure` raises on `cancel_children_svc.onError` | 19 calls, parked in `unwinding.cancel_children`, `running` |
| B5 Iceberg | `record_child` raises on `submit_child.onDone` | **117 `submit_child` calls** — 117 child orders — `slices_done` left at 1 |

B1 and B5 are the ones that matter: `place_order` and `submit_child` are order
placements. A single raising post-ack action turns one intended order into a
duplicate-submission storm, at ~1300/s, with the machine reporting
`status="running"` and `error=None` throughout. `p_r603.py` confirms linear
growth with no ceiling (`growth` at 0.25 s intervals: 293 → 3220 over 3 s).

**Classification: LIBRARY.** The behaviour contradicts the CHANGELOG's
"every self-generated cycle is bounded on `Interpreter`" and the #168 claim of
equal lap counts on both engines. The contract JSON is unchanged from the
corrected catalogue and the shape is the library's own pinned configuration.

**Coverage note:** the gap is invisible to `tests/test_round6_findings.py`
because all three tests declare `def svc(...)`. The library's own docs
(#174, Production Characteristics) tell users to *prefer* `async def` for any
service that must not block timers — i.e. the documented-correct choice is the
one the budget does not cover.

### Repro files

`repro_r603_min.py`, `repro_167_axes.py`, `repro_166_168_axes.py`,
`repro_167_delta.py`, `repro_167_knobs.py`, `p_r603.py`
(outputs `out_r603_min.json`, `out_167_axes.json`, `out_166_168_axes.json`,
`out_167_delta.json`, `out_167_knobs.json`, `out_r603_probe.json`).

---

## C221-02 — bounded RAISE inbox is async-only (NEEDS-WRAPPER, Medium)

`SyncInterpreter.__init__(machine, input=None, clock=None, strict=None)` on
`221ce7c` accepts neither `max_queue_size` nor `overflow_policy`:

```
TypeError: SyncInterpreter.__init__() got an unexpected keyword argument
'max_queue_size'
```

The mandatory order-path configuration — bounded inbox with `OverflowPolicy.RAISE`
— therefore cannot be expressed on the sync engine. Every sync-parity run in
this track is consequently an *unbounded-inbox* comparison; the parity results
below are valid for ordering and effects, not for backpressure.

**Classification: NEEDS-WRAPPER.** Not a defect — the sync engine drains
inline and has no inbox to bound in the same sense — but any component that
claims "the same config runs on both engines" is wrong, and a wrapper must
either refuse a bounded-inbox config on the sync path or enforce the bound
itself at the call site.

## C221-03 — `get_persisted_snapshot()` output is not `from_snapshot()` input (NEEDS-WRAPPER, Low)

`get_persisted_snapshot() -> Dict[str, Any]`, but `from_snapshot(snapshot_str, ...)`
rejects a dict:

```
SnapshotCorruptError('Snapshot payload must be a JSON string, got dict.')
```

The harness threads `json.dumps` between them (`cv221.snap_roundtrip`). Worth
noting only because the natural persist→restore call pair does not compose,
and the failure is a corruption-flavoured exception rather than a type error.

**Classification: NEEDS-WRAPPER.**

---

## Passing invariants

### Snapshot / restore at every macrostep

A round-trip was taken at `t0` and after **every** scripted step on the
snapshot-enabled runs: snapshot → fresh `create_machine` with fresh stub →
`from_snapshot(clock=SimulatedClock())` → `start()` → quiesce → compare
`(state ids, context)`. Zero drift and zero refusals across B1 happy/filled/
recon, B2 happy/partial, B3 happy/unwind, B4 happy, B5 refill — including
parallel-region configurations (B1) and nested compound configurations
(B3 `unwinding.*`). The #142/#143 legality rules and the #169 mid-step refusal
did not produce a single false refusal at a genuine quiescence point.

### R6-01 class — `always` into an invoked child

Exercised where the contracts actually contain the shape, and every instance
terminated, bounded and observable:

- **B3 `pending.always`** ladder runs at `start()` and descends into
  `submitting`, which invokes. Entry order `size_from_profile →
  submit_entry_order → arm_submit_timeout`; first matching guard wins
  (`should_skip` → `skipped`, `passes_preflight` false → `error`).
- **B5 `pending.always` → `submitting_slice`** (invokes `submit_child`) and
  **`repricing.always` → `submitting_slice`**: the post-only reject loop
  `submitting_slice → repricing → submitting_slice` reached `cooling_down` in
  2 invocations, exactly as the `two_consecutive_post_only_rejects` guard
  specifies.
- **B2 `aborting.always`** resolved to `failed` / `partially_open` on
  `some_open` with `stop_submitting_remaining_legs` run.
- **B4 settle→racing reenter ping-pong** settled in 1 invocation.

The R6-01 hang (`send(wait=True)` never resolving) did **not** reproduce on any
contract shape — every `send` returned a receipt in well under a millisecond.

### Bounded retry ladders

Every guard-bounded retry ladder respected its bound: B3 `close_attempts_left`
(3 `reduce_only_close`, → `leg.error` with `mark_incomplete`), B4
`settle_retries_left` (3 `settle_other_leg`, → `oco.failed` with
`raise_critical_alert`), B5 `failures_exhausted` (4 `submit_child` →
`iceberg.failed`), B1 `second_consecutive_miss` (one `unknown` reenter with
`bump_recon_misses`, second miss → `rejected`).

### `onUnhandled: "defer"`

An early event is buffered and replayed after the target state is reachable,
with `on_unhandled_event(disposition="deferred")` observed each time:
B1 `EXEC` before `SEND` → replays into `partially_filled`; B2 `ALL_LEGS_FLAT`
before `CONFIRM` → group reaches `closed`; B3 `FLAT` before `CLOSE` → `closed`.
Raised events produced by `raise` actions (B2 `EVALUATE`) also route through
the defer buffer, matching the #170 documentation note.

### `guardErrorPolicy: "raise"`

A crashed guard fires `on_guard_error` with the original exception on both B1
(`ret_code_ok`) and B2 (`all_non_skipped_open`). Note the send still returns
`ok` — the crash surfaces on the plugin hook, not the receipt — which matches
the #170 rule that `error` and not `denied` carries a crashed guard.

### Safety-critical alert paths

All fired where the catalogue requires: B1 `raise_unknown_alert` +
`record_transport_fault` on transport fault, `raise_critical_alert` +
`request_reconciliation` on quarantine, `raise_naked_position_alert` +
`request_fallback_sl` on `protection.sl_missing` (reached both via `SL_LOST`
and via `attach_native_sl` failing); B3 `raise_naked_position_alert` on the
`verify_sl` onError leaf; B4 `raise_warning_alert` + `journal_double_fill` on
overshoot; B2 `raise_critical_alert` on incomplete unwind.

### Parallel-region integrity (B1)

The `lifecycle ∥ protection` machine held exactly one leaf per region across
every scenario, including after a region reached a `final` state
(`['order.lifecycle.filled', 'order.protection.sl_present']`), and the
protection region's own `invoke` (`attach_native_sl`) resolved independently
of lifecycle progress.

### Sync parity

Async and sync agreed on final state ids, context, action order and service
call order for B1 (`VALIDATE/SEND/FIRST_FILL/EXEC` — including the interleaving
of `apply_fill` and `notify_protection_region` across regions), B2, B3
(`unwinding` three-invoke chain), B4 and B5. The only structural parity break
found is C221-01 (chain budget) and the C221-02 config-surface asymmetry.

---

## Files

| File | Purpose |
|---|---|
| `cv221.py` | Harness: name collection, stub logic, `CvHooks`, snapshot comparator, async/sync drivers |
| `d_b1.py` / `d_b2.py` / `d_b3.py` / `d_b45.py` | Contract drivers |
| `d_b2_lib.py` | B2 guard/action tables shared with the probe |
| `repro_r603_min.py` | Minimal R6-03 rollback re-arm spin |
| `repro_167_axes.py` | Entry-path × service-kind isolation |
| `repro_166_168_axes.py` | #166/#168 pinned shapes, `def` vs `async def` |
| `repro_167_delta.py` | Entry-action vs transition-action raise site |
| `repro_167_knobs.py` | Clock / inbox-bound / overflow-policy isolation |
| `p_r603.py` | B2 growth-over-time measurement |
| `res_*.json`, `out_*.json` | Raw results |

## Verdict for the contract track

B1–B5 are **structurally sound against `221ce7c`**: they build, their
invariants hold, their bounded ladders stay bounded, they snapshot and restore
faithfully at every quiescence point, and they behave identically on both
engines. No our-contract defect was found.

Adoption is blocked by **C221-01** alone. It is not a contract-shaping problem
— no rearrangement of the catalogue avoids it, because the trigger is
"a transition action raises while `actionErrorPolicy: rollback` is in force and
the state being rolled back into invokes an `async def` service", and both of
those are mandatory for this domain. Until the chain budget charges async
services, an OMS on this engine needs either an external invocation-rate
circuit breaker per invoke id, or a hard ban on raising actions anywhere
downstream of an `invoke` — the latter being unenforceable in review.
