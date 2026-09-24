# Contract machines end-to-end on `cec108b` (unreleased 0.8.1)

Scope: B1 Order, B2 TradeGroup, B3 TradeGroupLeg, B4 OCO, B5 Iceberg driven
end-to-end on the async engine with the corrected catalogue JSON, plus the
control machines B16/B17/B18/B19 and B11 re-run, plus a targeted re-test of
**CV-C32** now that #149 has landed a `service_executor`.

Library clone read-only at `cec108b`; all scripts live beside this file.

Mandatory config used throughout: `actionErrorPolicy: rollback`,
`onUnhandled: defer` (order path) / `error` (control), `guardErrorPolicy:
raise`, `strictTargets`, `MachineLogic(strict=True)`, bounded inbox with
`OverflowPolicy.RAISE` on the order path, `SimulatedClock`.

## Headline

| | |
|---|---|
| `create_machine` on B1–B5 | **5/5 clean**, no `InvalidConfigError` |
| B1 Order | **23/23 pass** |
| B2 / B3 / B5 | **14 / 14 / 16 pass** |
| B4 OCO | 9/11 — 2 failures, both **OUR-CONTRACT** (unchanged from `3ed3099`) |
| B11 RecordingSession | **7/7 pass** |
| B16/B17/B18/B19 | drive clean; no new library defects |
| Snapshot at quiescence | **zero `SnapshotMidStepError`** across every macrostep of all five machines |
| Snapshot resume parity | state, context and action-trace identical at every cut point |
| New library findings | **1** (`CV-CEC-01`, plain-`def` service blocks its macrostep) |

The round-5 fixes we depend on all hold under contract load: `Receipt.deferred`
is `True` at the call site for a held order event (B1 INV-5, B3, B5), the
deferred replay is its own macrostep, `guardErrorPolicy: raise` no longer
eats an `invoke.onDone` fallback, and the per-macrostep settle budget removed
the batch-sharing trip we saw in round 4.

## Verdicts

### LIBRARY — CV-CEC-01 (new, reproduced)

**A plain-`def` service blocks its own macrostep, so the invoking state's own
`on` handlers never run while it is in flight.** `#149` moved plain-`def`
services onto a `service_executor` so the *event loop* keeps turning — that
part is real and verified (≈31 loop turns during a 0.35 s service, same as
`async def`). But the *entering macrostep* still awaits the result, so the
machine itself is unresponsive for the service's whole duration.

`repro_cv_cec_01.py`, same machine, only the service's `def`/`async def`
differs:

```
async def  PING latency=0.001s receipt.state_ids=['p.working'] mark_ping=True  final=['p.working']
plain def  PING latency=0.343s receipt.state_ids=['p.done']    mark_ping=False final=['p.done']
```

`PING` is declared on `working` and nowhere else. Under `async def` it is
handled there. Under plain `def` the `send()` blocks for the service duration
and the event is then evaluated against `done` — with `onUnhandled: defer` it
is reported `('PING','deferred')` and parked forever, and with `strict` it
would raise. The caller's `Receipt` even reports `state_ids={'p.done'}` for an
event sent while the machine was demonstrably in `working`.

Severity for us: **high on the order path**. A plain-`def` `place_order` would
make every `EXEC` arriving during submission land against the post-ack
configuration — exactly the INV-5 hazard round 5 was fixed to close, reopened
through a different door.

### CV-C32 — KEEP THE RULE (all services `async def`)

The re-test (`c32_executor.py`) answers the question asked: **no, the
`service_executor` does not make CV-C32 unnecessary.** It fixes loop
starvation, not machine responsiveness. Measured:

| service | loop turns during 0.35 s | `PING` in `working` | `send()` latency |
|---|---|---|---|
| `async def` | 31 | handled | 0.000 s |
| plain `def` (default executor) | 31 | **lost** | 0.297 s |
| plain `def` (own `ThreadPoolExecutor`) | 32 | **lost** | — |

Ordering (`#116`) and error routing do hold for plain `def` — a raising plain
service reaches `onError` correctly, and the sync engine runs plain `def`
natively while still refusing `async def` (`NotSupportedError`). So the fix is
good as far as it goes; CV-C32 stays in force for us regardless.

### OUR-CONTRACT — B4 OCO loses `LEG_B_FILL` during settlement

`B4/INV-B4-d` and `B4/INV-B4-a` fail identically to `3ed3099` — not a
regression, our JSON's defect. `LEG_B_FILL` is declared only on `racing`.
Sent while the machine is in `settling_b` it is correctly deferred by the
runtime (`Receipt.deferred=True`, `deferred_count=1`), but the replay target
`completing` does not declare it either, so it is re-deferred and the fill is
never recorded — `filled_b=0` in a terminal OCO.

`b4_probe.py` isolates it: adding `LEG_B_FILL` to `completing` and `completed`
makes the same run record the fill and drain the deferral.

```
as-written ids=['oco.completing'] deferred_now=1 record_fill_b=0 unhandled=[(LEG_B_FILL,deferred) x2]
patched    ids=['oco.completing'] deferred_now=0 record_fill_b=1 unhandled=[(LEG_B_FILL,deferred) x1]
```

Fix belongs in `28-statechart-catalogue.md`: every terminal-ward state on the
order path must declare the fill events its predecessors declared, otherwise
`onUnhandled: defer` converts a lost event into a permanently parked one.

### NEEDS-WRAPPER (carried forward, re-confirmed)

- **B8 native-SL-before-position is not structurally enforced.** B1's
  `protection` region observes `sl_missing` correctly (`B1/B8-*` pass), but no
  `stateIn`/`in` guard anywhere gates `lifecycle` on it, so `filled` is
  reachable while protection is `sl_missing`. Either add the cross-region
  guard to the contract or enforce it in the adapter.
- **B3 ladder idempotency.** `place_tp_ladder_once` fires on the
  `open -> partially_filled` edge only; a re-entry of `open` after restore
  fires it again. Idempotency must live in the action, the machine does not
  provide it.
- **Sync parity on the control machines** is informational only: B17/B18/B19
  are unrunnable on `SyncInterpreter` because their services are `async def`
  (`NotSupportedError`). This is CV-C32's cost and is expected.

## Invariant scenarios covered

B1: happy path, terminal stickiness, fill-during-submit (INV-5, receipt
`deferred` then applied), reject + action rollback with no half-commit,
protection region / B8, amend-rejected keeps the order live, fill-beats-cancel,
late cancel-ack cannot revive, B13 transport fault to `unknown`, `unknown`
never resubmits, B19 recon divergence, B18 `send_priority` preemption on a
full inbox. B2: all-or-none unwind, partial-open abort, quiesce deadline,
status purity. B3: sized-once, ladder-once, bounded close attempts,
authoritative read, resolve-by-lookup, exec-during-resolving. B4: as above.
B5: single live child, remaining never negative, bounded slices, cooldown is
quiescent and not a busy-loop, WS disconnect freeze + reconcile on resume.
B11 concurrent `STREAM_UNHEALTHY`, B16 elevation cleared on logout, B17 2FA +
pen-test gate, B18 kill-switch, B19 stale-lockout all drive clean.

## Files

`b1_order.py`, `b2345.py` (drivers, `CV_VARIANT=fixed`), `b4_probe.py`,
`c32_executor.py`, `repro_cv_cec_01.py`, `c1_b16.py`..`c4_b19.py` (+ `.out`),
`g3_b11.py`, harnesses `charness.py` / `cvlib.py` / `cdrv.py` / `g3_harness.py`.
