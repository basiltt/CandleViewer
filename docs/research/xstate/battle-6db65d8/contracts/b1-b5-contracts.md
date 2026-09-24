# Contract machines B1–B5 end-to-end on `6db65d8`

Library clone at `main` = `6db65d8` (unreleased 0.8.1; `__version__` still
reads 0.8.0 — keyed on the commit). Library source was never modified.

**Headline: 264 / 264 contract checks PASS, on BOTH service styles.**
Round 7's R7-01 (`async def` services escaping the chain budget) is gone on
every shape our contracts exercise. One genuine engine-parity gap remains
(CV-6DB-01) and one API ergonomics gap (CV-6DB-02); neither is a blocker for
B1–B5.

| Pass | Driver | async def svc | plain def svc |
|---|---|---|---|
| B1 Order | `z_b1.py` | 34 / 34 | 34 / 34 |
| B2 TradeGroup | `z_b2.py` | 23 / 23 | 23 / 23 |
| B3 TradeGroupLeg | `z_b3.py` | 21 / 21 | 21 / 21 |
| B4 OCO + B5 Iceberg | `z_b45.py` | 34 / 34 | 34 / 34 |
| Persistence / drift | `y5_snapshot.py` | 15 / 15 | 15 / 15 |
| `create_machine` | `z0_build.py` | 5 / 5 | 5 / 5 |
| **Total** | | **132** | **132** (+10 build) |

## Method

Harness `cv6db.py` (ported from `battle-221ce7c/contracts/cv221.py`). The one
structural change is the point of this round: a `Stub.svc_style` axis
independent of the engine, driven by `CV_SVC_STYLE` (default `async`). Every
driver was run twice — `CV_SVC_STYLE=async` then `CV_SVC_STYLE=def` — and
every result key is prefixed `[async]` / `[def]`. The round-7 harness was
`def`-only for services on the async engine and was structurally blind to the
coroutine lane; that blindness is what this pass removes.

Mandatory config, taken from the corrected JSON in
`battle-221ce7c/contracts/<B>.machine.json` and carried unchanged:
`actionErrorPolicy: rollback`, `onUnhandled: defer` (order path),
`guardErrorPolicy: raise`, `strictTargets: true`, `strict: true`,
bounded inbox `max_queue_size=64` + `OverflowPolicy.RAISE`, `SimulatedClock`,
and a `CvHooks` plugin stub recording every observability hook the OMS would
route to alerting.

Every send carries a hard 5 s watchdog and every driver a 40 s `wait_for`
around the cycle shapes; a timeout *is* the observed result, never a retry.
Snapshot/restore round-trips run at `t0` and after every macrostep, comparing
`(state_ids, context, status, deferred)` against a freshly restored
interpreter.

One harness bug of ours was fixed en route: the sync-parity legs set
`stub.sync = True` but left `svc_style` at `async`, so the `SyncInterpreter`
was handed coroutine services and raised
`NotSupportedError: Service 'attach_native_sl' is async and not supported`.
That is correct library behaviour (the sync engine does not run coroutines);
the parity legs now set `svc_style = "def"` alongside `sync = True`. This was
**OUR-CONTRACT**, not a library defect.

## Result 1 — every contract builds and every invariant holds, both styles

`z0_build.py`: `create_machine` accepts all five contracts under
`strict_targets`, on both service styles — no `InvalidConfigError`, so no
our-contract defect survives from earlier rounds. Name surface:
B1 25 actions / 7 guards / 4 services, B2 14/7/1, B3 11/7/5, B4 8/6/5,
B5 9/8/3.

The four drivers reproduce every catalogue invariant and every round-5/6 OC
fix with byte-identical verdicts on `async def` and `def` services:

- **B1** parallel lifecycle+protection, local reject, transport-fault
  `unknown` + alert, RECON_MISS re-enter-once-then-reject, duplicate link id
  → `submitted` + `mark_needs_lookup`, quarantine→recon recovery,
  `attach_native_sl` `onError` → naked-position alert, cancel/amend paths,
  `onUnhandled: defer` replaying `EXEC` sent before `SEND`,
  `guardErrorPolicy: raise` surfacing on `on_guard_error`, and sync parity on
  states/context/actions/service calls.
- **B2** raise-driven `EVALUATE` chain terminating under a bounded inbox,
  quiesce→`partially_open` / `failed`, `abort_on_first`, and the
  `unwinding` invoke resolving exactly once.
- **B3** the `pending` `always` ladder evaluated at `start()`, `always` into
  the invoked `resolving` child, the three-invoke unwind chain in order
  (`cancel_children_svc` → `reduce_only_close` → `poll_until_flat`), and the
  bounded close-retry ladder.
- **B4** OCO arm→race→settle, overshoot flatten, arming failure, bounded
  settle-retry ladder. **B5** refill loop, preflight short-circuit,
  post-only reprice cycle reaching `cooling_down`, bounded submit-failure
  ladder, pause/resume/reconcile, `POSITION_FLAT` cancel.

Full per-check JSON: `res_b1.{async,def}.json`, `res_b2.*`, `res_b3.*`,
`res_b45.*`, `res_y5.*`, `res_z0.json`.

## Result 2 — R7-01 is fixed: the coroutine lane is now charged

This was round 7's reopened blocker: an `async def` service's `done.invoke`
was published on the public inbox, never charged to the chain budget, and
reset the settle budget every lap — so `maxIterations` was inert for exactly
the service style the docs recommend, while the identical `def` service
tripped. Round 7 measured ~10–21k unbounded calls in 1–2 s for the coroutine
lane against ~1 000 (a clean trip) for `def`.

`y2_observe.py` drives the R6-03 shape directly — `actionErrorPolicy:
rollback` where the `invoke.onDone` action raises, so the rollback returns to
the invoking state and re-arms the invoke — at three budgets, both styles:

| `maxIterations` | `async def` calls | `def` calls | bounded | `last_error` |
|---|---|---|---|---|
| 20 | 22 | 22 | yes | `RunawayChainError` |
| 100 | 102 | 102 | yes | `RunawayChainError` |
| default 1000 | 1002 | 1002 | yes | `RunawayChainError` |

The two lanes are now **exactly equal** at `limit + 2` and the trip is
observable on `interpreter.last_error` as
`RunawayChainError("... exceeded N chained self-generated events in one
macrostep and discarded 1 of them ...")`, with `on_transition_failed` and
`on_action_error` firing `limit + 1` times. Boundedness was confirmed by
sampling the call count twice 4 s apart after `send()` returned: identical,
so the chain is cut, not merely slow.

Caveat on method, worth recording because it nearly produced a false
positive: an early probe sampled only 1 s after `send()` and saw the counter
still climbing at the default budget, which looks like "unbounded". At
`maxIterations: 1000` the cycle legitimately needs ~2 s of wall clock to burn
its budget. **Any boundedness claim needs a settle window longer than the
budget takes to spend, or it measures the sampler.** `y1_rollback.json`
preserves the misleading short-window run beside the corrected one.

The `always`-into-an-invoked-child shape (`y6_always.py`, the B5 repricing
ladder in miniature) is equally clean: the terminating case runs exactly 5
service calls on async-engine/`async def`, async-engine/`def` and
sync-engine/`def` alike and lands in the final state; the deliberately
unbounded case trips at 15 calls on both async-engine styles (16 on sync,
see CV-6DB-01) with `RunawayChainError` on `last_error`.

## Result 3 — external priority sends are never charged (#180 holds)

`y4_priority.py` is the B18 kill-switch shape: 40 concurrent external
`send(..., priority=True)` calls landing while an invoke/`onDone` chain is
open on a `max_queue_size=8`, `OverflowPolicy.RAISE` interpreter.

| style | sent | applied | dropped | send exceptions |
|---|---|---|---|---|
| `async def` | 40 | 40 | 0 external (1 engine `done.invoke`, `chain_budget`) | 0 |
| `def` | 40 | 40 | 0 external (1 engine `done.invoke`, `chain_budget`) | 0 |

Provenance is by *who issued it*, as #180 claims: every externally-issued
priority event was applied, and the only `on_event_dropped` was the engine's
own `done.invoke` hitting the chain budget. The kill switch cannot be
silently shed. This is the requirement the catalogue places on B18, met on
both lanes.

## Result 4 — persistence: round-trip clean, drift and corruption refused

`y5_snapshot.py`, both styles, all five contracts (15 checks each pass):

- Snapshot at `t0` and after every macrostep of a representative script
  restores into a fresh machine with identical `state_ids` and `context`.
  Blobs are `version: 2` and carry a `machine_hash`.
- **#185** — a versioned blob whose `machine_hash` is `null`, and one where
  the field is absent entirely, are both refused with `SnapshotDriftError`.
  The v0 presence-keyed bypass is gone.
- **#186** — a blob whose `configuration` is emptied, and one whose
  `state_ids` contradicts the `configuration`, are both refused with
  `SnapshotCorruptError`. Neither silently wins.

## Findings

### CV-6DB-01 — LIBRARY (low) — the two engines cut the rollback re-arm cycle at different lap counts

`y3_parity.py`, one machine, `maxIterations: 20`, rollback + `invoke.onDone`
whose action raises:

| engine / style | service calls | final state | `last_error` |
|---|---|---|---|
| async / `async def` | **22** | `m.arm`, running | `RunawayChainError` |
| async / `def` | **22** | `m.arm`, running | `RunawayChainError` |
| sync / `def` | **2** | `m.arm`, running | `RuntimeError('boom')` |

The async engine spends the whole declared budget; the sync engine stops
after two laps and never reports a `RunawayChainError` at all — its
`last_error` is the action's own `RuntimeError`.

`y7_syncquiesce.py` establishes that the sync engine's stop is genuinely
terminal and not merely deferred: after the two laps, six further unrelated
`NUDGE` sends leave the service-call count at 2, the state at `m.arm`, and
`last_error` at `None`. So the sync engine is *safer* here, not broken — it
declines to re-arm the invoke after a rollback, where the async engine
re-arms it `maxIterations` times.

The defect is **parity and observability**, not runaway: the same chart on
the two engines issues a different number of real side effects for the same
budget (for B1 that is `place_order` — 22 live order submissions versus 2),
and only one of the two surfaces the budget trip. The round-7 `always` shape
shows the milder version of the same skew (15 async vs 16 sync).

*Impact for the OMS:* wherever a contract can roll back onto a re-armed
invoke, treat `maxIterations` as the **number of duplicate exchange calls you
are authorising**, and set it per machine accordingly — the default 1000 is
1000 duplicate `place_order`s. Do not rely on cross-engine equality of lap
counts in tests.

### CV-6DB-02 — LIBRARY (informational) — the chain-budget trip is on `last_error`, never on the caller's receipt

In every trip above, `await interpreter.send("GO")` returns `None`, not a
receipt: the caller whose event opened the runaway chain gets no signal.
`on_error` never fires either (`n_on_error: 0`); the trip is visible only on
`interpreter.last_error` and, indirectly, through `on_transition_failed` /
`on_action_error` / `on_event_dropped(reason="chain_budget")`.

*Impact:* an OMS that awaits `send()` and branches on the receipt will
conclude the order step succeeded. **NEEDS-WRAPPER:** the send wrapper must
read `interpreter.last_error` after every await and treat a
`RunawayChainError` as a hard alert, or register a plugin on
`on_event_dropped` with `reason == "chain_budget"`.

### OUR-CONTRACT — sync parity legs must pin `svc_style = "def"`

Not a library defect. The `SyncInterpreter` correctly refuses coroutine
services with `NotSupportedError`; any parity harness must build plain-`def`
logic for the sync leg. Recorded because it produced three spurious FAILs
before it was diagnosed.

### Not reproduced

R7-01 (coroutine services escaping the chain budget) — **fixed**, verified at
three budgets on the exact filed shape. #180 (external priority sends
charged), #185 (null hash accepted), #186 (configuration/`state_ids`
disagreement accepted) — all refuted on both service styles.

## Verdict

B1–B5 are **fit to build on at `6db65d8`**, on `async def` services. Two
wrapper obligations before the OMS ships:

1. Set `maxIterations` explicitly per contract machine, read as a duplicate-
   side-effect budget, not a safety net (CV-6DB-01).
2. Check `interpreter.last_error` after every `send()`, or subscribe to
   `on_event_dropped(reason="chain_budget")` (CV-6DB-02).

## Files

Harness `cv6db.py`; contracts `B{1..5}.machine.json`; drivers `z0_build.py`,
`z_b1.py`, `z_b2.py`, `z_b3.py`, `z_b45.py`; probes `y1_rollback.py`,
`y2_observe.py`, `y3_parity.py`, `y4_priority.py`, `y5_snapshot.py`,
`y6_always.py`, `y7_syncquiesce.py`; results `res_*.json`, `y*.json`,
`{async,def}_out_*.json`.
