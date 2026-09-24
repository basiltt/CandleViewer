# Contract machines end-to-end on `f28719c` (B1–B5 + B18)

Library clone at `main` = `f28719c` (unreleased 0.8.1; `__version__` still
reports `0.8.0` — keyed on the commit). Round-8 fixes #192–#201 plus the
reopened #181/#186 are in.

Scope: B1 Order, B2 TradeGroup, B3 TradeGroupLeg, B4 OCO, B5 Iceberg, driven
end-to-end, plus B18 kill_switch for the priority-lane and `always`→invoked-child
obligations. Mandatory config on every machine: `actionErrorPolicy: rollback`,
`onUnhandled: defer` (order path) / `error` (control path), `guardErrorPolicy:
raise`, `strictTargets`, `strict`, bounded inbox with `OverflowPolicy.RAISE`,
`SimulatedClock`, plugin stub (`CvHooks`) on every interpreter.

**Pass 1 = every service an `async def`. Pass 2 = every service a plain `def`.**
Each pass re-runs the whole suite; the sync engine runs the `def` lane.

## Result

| Suite | checks (async) | checks (def) | fail |
|---|---|---|---|
| build (`create_machine`) | 5 | 5 | 0 |
| B1 Order | 34 | 34 | 0 |
| B2 TradeGroup | 23 | 23 | 0 |
| B3 TradeGroupLeg | 21 | 21 | 0 |
| B4 OCO + B5 Iceberg | 34 | 34 | 0 |
| B18 kill_switch | 5 | 5 | 0 |
| cross-engine parity | 16 | 16 | 0 |
| **total** | **138** | **138** | **0** |

No `InvalidConfigError` on any of the five contracts in either service style, so
no our-contract defect surfaced at build time. Every machine reached its expected
terminal or parked configuration, every invariant held, and snapshot/restore at
quiescence between every macrostep round-tripped without drift on both lanes.

## Artefacts

Everything lives under `battle-f28719c/contracts/zc/`:

- `cvz.py` — harness (stub logic, `CvHooks` plugin, `drive` / `drive_sync`,
  `snap_roundtrip`). `CV_SVC_STYLE=async|def` selects the service kind.
- `z0_build.py`, `z_b1.py`, `z_b2.py`, `z_b3.py`, `z_b45.py`, `z_b18.py`,
  `z_parity.py` — drivers. Outputs in `zc/results/`.
- `zc/repro/r1_rollback_onDone.py`, `r2_chain_trip.py`, `r3_stranded.py`,
  `r4_b18_priority.py`, `r5_lasterror_kind.py` — STANDALONE (stdlib +
  `xstate_statemachine` only, every helper inlined), each parametrised by
  `CV=async|def`, each exiting non-zero on the unsafe outcome.

## The three mandated explicit drives

### 1. rollback + `invoke.onDone` — **NEEDS-WRAPPER** (unchanged from round 7/8)

`repro/r1_rollback_onDone.py`. `submitting` invokes `place_order`; its `onDone`
targets `submitted`, whose entry action raises. Under `actionErrorPolicy:
rollback` the failed entry unwinds to `submitting`, which **re-arms the invoke**.
Each lap is a real exchange order.

```
style=async maxIterations=(default) place_order_calls=1003
style=def   maxIterations=(default) place_order_calls=1003
style=async maxIterations=25        place_order_calls=28
style=def   maxIterations=25        place_order_calls=28
```

Both service kinds trip at the **same lap count** — #201's parity claim holds
here. The cycle is bounded and the machine does not livelock: after the shed it
parks quietly in `submitting` (`r3_stranded.py`: `quiet_after=True`) and remains
responsive — a subsequent `ABORT` is accepted and drives it to `unknown` on both
lanes.

This is **not** a library defect: the engine's documented `rollback` contract is
to unwind the transition, and re-entering a state with an `invoke` re-arms it per
SCXML. It *is* a hazard for an OMS, because the unwound unit of work is a
side-effecting order placement. **Wrapper obligation:** an entry action on a
state reached by `invoke.onDone` must never raise; push any fallible adoption
work into a service or a guarded `always`, or make `place_order` idempotent on a
client order id. B1's corrected contract already routes adoption through
`adopt_ack`, so the wrapper must treat "entry action on an onDone target" as a
lint rule.

**Observability gap worth recording:** the trip is reported on `i.last_error`
(a `RunawayChainError` naming the limit and the discarded count) and via
`on_event_dropped(..., "chain_budget")`, but **`on_error` is never called** and
`i.error` stays `None` while `status` stays `running` (`r2_chain_trip.py`, both
kinds). A supervisor polling `interpreter.error` or subscribing to `on_error`
will not see a runaway. `CvErrorHooks` must poll `last_error` per step or
subscribe to `on_event_dropped`.

A second, sharper wrinkle (`r5_lasterror_kind.py`): `last_error` is observable on
the step the trip affects on both lanes, but once the machine settles it is
**cleared on the `async def` lane and retained on the `def` lane**:

```
style=async  last_error_after_step=RunawayChainError  last_error_settled=NoneType
style=def    last_error_after_step=RunawayChainError  last_error_settled=RunawayChainError
```

So a supervisor that samples `last_error` asynchronously rather than per-step
sees the runaway on `def` services and misses it on the `async def` services the
docs recommend. Classified **NEEDS-WRAPPER** (sample per step, off the send
receipt) rather than LIBRARY, since #196/#201 only promise the trip is reported
"on every step it affects" — which is met.

### 2. `always` → invoked child — **clean on both lanes**

`z_b18.py` against B18 `kill_switch`: `engaging` has no event handler, only
`entry` actions and an `always` fan-out that selects `cancelling` (an `invoke` of
`cancel_all_working_orders`) when `cancel_working_requested`; that invoke's
`onDone` chains through `always`/guards into `flattening` (a second invoke) and
on to `engaged`.

```
svc_calls = ['cancel_all_working_orders', 'flatten_all_positions']
states    = ['kill_switch.engaged']   error=None   snapshot_ok=True
```

Identical on `async def` and `def`. The eventless settle pass arms the invoked
child correctly, the completion is charged to the priority lane, and the chain of
two services plus three `always` hops terminates without a spurious chain trip.
This is the behaviour #196 promised (eventless transitions selected only in the
settle pass) and it holds end-to-end on a real control machine.

### 3. B18 `send_priority` under a self-generated chain — **clean, 0 dropped**

`repro/r4_b18_priority.py`. A parallel region spins a self-generated `SPIN` chain
that trips `maxIterations: 5`, while an external producer issues N
`send(..., priority=True)` `ENGAGE` events at the kill switch.

```
style=async N=40   ext_counted=40/40   ENGAGE_dropped=0  states=[..., engaged]
style=async N=200  ext_counted=200/200 ENGAGE_dropped=0  states=[..., engaged]
style=def   N=40   ext_counted=40/40   ENGAGE_dropped=0  states=[..., engaged]
style=def   N=200  ext_counted=200/200 ENGAGE_dropped=0  states=[..., engaged]
```

Exactly one drop in every run, and it is the runaway's own `SPIN` shed as
`chain_budget`. **Not one external priority send was destroyed**, at either
volume, in either service style — #192's provenance-based shedding is doing what
it claims. The kill switch preempts: it reaches `engaged` (through its invoked
child) while the noise region is still being shed. This closes the round-7 B18
hazard for our purposes.

## Snapshot / restore at quiescence

Every driver calls `snap_roundtrip` before the first event and after every
macrostep: `get_persisted_snapshot()` → fresh machine built from the same JSON
with a fresh stub → `Interpreter.from_snapshot` → start → quiesce → compare
`(current_state_ids, context, status, deferred_count)`. Across B1–B5 and B18,
both service styles, **every round-trip matched with no drift and no refusal** —
including mid-flight configurations with a deferred `EXEC` outstanding
(`B1.defer.exec_replayed`), a quarantined order, and the kill switch parked in
`engaged` after two chained invokes. #198's "both configuration fields non-empty
on a `version >= 1` running snapshot" did not reject any legitimate payload our
contracts produce.

## Cross-engine parity

`z_parity.py` runs B1, B3, B4 and B18 on the async engine and on
`SyncInterpreter` (plain `def` services, as the sync engine requires) and
compares `states`, `context`, `actions` and `svc_calls` element-for-element. All
16 comparisons match, in both passes. Note `SyncInterpreter` still accepts no
`max_queue_size` / `overflow_policy` — the bounded RAISE inbox is async-only, as
recorded in earlier rounds; that is a documented asymmetry, not a regression.

## Findings

| # | Class | Item |
|---|---|---|
| F1 | NEEDS-WRAPPER | `rollback` + `invoke.onDone` re-arms a side-effecting service once per lap until `maxIterations` sheds it. Lint rule: no fallible entry action on an `onDone` target; make placement idempotent on a client order id. |
| F2 | NEEDS-WRAPPER | A chain trip is **not** surfaced on `on_error` or `interpreter.error`; only `last_error` and `on_event_dropped(..., "chain_budget")`. `CvErrorHooks` must subscribe to `on_event_dropped` and read `last_error` off the send receipt. |
| F3 | NEEDS-WRAPPER | `last_error` is cleared once settled on the `async def` lane but retained on the `def` lane. Sample per step, never asynchronously. |
| F4 | OUR-HARNESS | `send(wait=True)` resolves at the end of the macrostep, **not** after an `async def` service chain settles. Our fixed 60 ms settle raced under CPU load (B3's three-retry unwind chain: median tail 7 ms idle, 25 ms / max 40 ms under 400 competing tasks) and produced three flaky FAILs. Fixed by widening the settle to 5×50 ms. Real wrapper code must not treat a `wait=True` receipt as "the service chain has finished". |

No **LIBRARY** finding. Every behaviour reproduced above is either the
documented contract of `rollback`/SCXML re-entry, or a fix from #192–#201
working as claimed.

## Verdict

B1–B5 and B18 are **green end-to-end on `f28719c` in both service styles**, with
the four wrapper obligations above written into the adoption gate. The two
round-7/8 hazards that mattered most to an OMS — external priority sends
destroyed by an unrelated runaway, and `always` failing to arm an invoked child —
are both closed and stay closed under `async def` and `def` alike.
