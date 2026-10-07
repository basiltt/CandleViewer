# Contract machines end-to-end on `19cb1f1` (B1–B5 + B18, plus B16)

Library clone at `main` = `19cb1f1` (unreleased 0.8.1; `__version__` still
reports `0.8.0` — keyed on the commit). Round-9 fixes **#203–#210** are in on
top of round-8's #192–#201.

Scope: B1 Order, B2 TradeGroup, B3 TradeGroupLeg, B4 OCO, B5 Iceberg driven
end-to-end, plus B18 `kill_switch` for the priority-lane and
`always`→invoked-child obligations, plus B16 `session` for the C-04 question.
Mandatory config on every machine: `actionErrorPolicy: rollback`, `onUnhandled:
defer` (order path) / `error` (control path), `guardErrorPolicy: raise`,
`strictTargets`, `strict`, bounded inbox with `OverflowPolicy.RAISE`,
`SimulatedClock`, plugin stub (`CvHooks`, now including
`on_invocation_stranded`) on every interpreter.

**Pass 1 = every service an `async def`. Pass 2 = every service a plain `def`.**
Each pass re-runs the whole suite; the sync engine runs the `def` lane.

The corrected JSON for B1–B5 is **byte-identical across `battle-3ed3099`,
`battle-6db65d8` and `battle-f28719c`** (verified by `diff`), so the contracts
under test are unchanged and every delta below is the library's.

## Result

| Suite | checks (async) | checks (def) | fail |
|---|---|---|---|
| build (`create_machine`) | 5 | 5 | 0 |
| B1 Order | 34 | 34 | 0 |
| B2 TradeGroup | 23 | 23 | 0 |
| B3 TradeGroupLeg | 21 | 21 | 0 |
| B4 OCO + B5 Iceberg | 34 | 34 | 0 |
| B18 kill_switch | 5 | 5 | 0 |
| cross-engine parity | 39 | 39 | 0 |
| **total** | **161** | **161** | **0** |

No `InvalidConfigError` on any of the five contracts in either service style, so
no our-contract defect surfaced at build time. Every machine reached its expected
terminal or parked configuration, every invariant held, and snapshot/restore at
quiescence between every macrostep round-tripped without drift on both lanes.
This is the round-8 result reproduced with **zero regressions** on `19cb1f1`.

## Artefacts

Everything lives under `battle-19cb1f1/contracts/`:

- `cvz.py` — harness (stub logic, `CvHooks` plugin now recording
  `on_invocation_stranded`, `drive` / `drive_sync`, `snap_roundtrip`;
  `drive` now also reports `stranded`, `last_error` and
  `has_dormant_invocations`). `CV_SVC_STYLE=async|def` selects the service kind.
- `z0_build.py`, `z_b1.py`, `z_b2.py`, `z_b3.py`, `z_b45.py`, `z_b18.py`,
  `z_parity.py` — drivers. Outputs in `results/`.
- `repro/` — STANDALONE (stdlib + `xstate_statemachine` only, every helper
  inlined, run from neutral cwd `<home>`), each parametrised by
  `CV=async|def`, each exiting non-zero on the unsafe outcome:
  `r1_rollback_onDone.py`, `r2_chain_trip.py`, `r3_stranded.py`,
  `r4_b18_priority.py`, `r5_lasterror_kind.py`, `ld01_always_rollforward.py`,
  and new for round 9: **`r6_stranded_hook.py`** (#207 surface),
  **`r7_c07b_b18_release.py`** (C-07b), **`r8_c04_b16_elevation.py`** (C-04),
  **`r9_after_provenance.py`** (#203).

## The three mandated explicit drives

### 1. rollback + `invoke.onDone` — **NEEDS-WRAPPER**, now observable (#207)

`repro/r1_rollback_onDone.py`. `submitting` invokes `place_order`; its `onDone`
targets `submitted`, whose entry action raises. Under `actionErrorPolicy:
rollback` the failed entry unwinds to `submitting`, which **re-arms the invoke**.
Each lap is a real exchange order.

```
style=async maxIterations=(default 1000) place_order_calls=1003
style=def   maxIterations=(default 1000) place_order_calls=1003
style=async maxIterations=25             place_order_calls=28
style=def   maxIterations=25             place_order_calls=28
```

**The plateau is exactly `maxIterations + 3` and identical on both lanes** —
25→28, 1000→1003. `repro/r6_stranded_hook.py` at `maxIterations=10` gives 13 on
both. This is #209/#210 landing: the round-8 report could only say "same lap
count"; round 9 pins the constant and the lane parity, and our runs confirm it
at three separate limits in both service styles.

The mechanics are unchanged and still **not a library defect** — the documented
`rollback` contract unwinds the transition, and re-entering a state with an
`invoke` re-arms it per SCXML. It remains a hazard for an OMS because the
unwound unit of work is a side-effecting order placement.

**What is new and materially better: the strand is now named.**
`repro/r6_stranded_hook.py`, both lanes, identical:

```
style=async maxIterations=10 arms=13 states=['order.submitting']
  last_error=RunawayChainError stranded=('po',)
  hook_fired=[('order.submitting', 'po', 'RunawayChainError')]
  dormant=True pending=[('order.submitting', 'po')]
  on_error=[] dropped_reasons=['chain_budget'] i.error=None status=running
  after_ABORT=['order.unknown']
  VERDICT=OK
```

All four surfaces #207 promised work on a real order-path shape:
`RunawayChainError.stranded == ('po',)`, `on_invocation_stranded` fires once with
`(state_id, invoke_id, error)`, `has_dormant_invocations` is `True`,
`pending_invocations()` names the pair — and an ERROR log says it in prose:

```
🧷 Machine 'order' rests in state 'order.submitting' whose invocation 'po' was
cut by the chain budget and will never complete (#207).
```

The `RunawayChainError` message itself now carries the strand
(`r2_chain_trip.py`): *"The cut stranded invocation(s) ['po']: their state is
still active with no service running, and no onDone/onError will arrive."* This
**closes round-8 finding F2's sharpest edge** — a supervisor no longer has to
poll the configuration against the chart to tell "stranded" from "slow service".

The machine also stays responsive after the cut: `ABORT` is accepted and drives
it to `unknown` on both lanes (`r3_stranded.py`, `r6_stranded_hook.py`).

**Wrapper obligation (unchanged):** an entry action on a state reached by
`invoke.onDone` must never raise; push fallible adoption work into a service or a
guarded `always`, or make `place_order` idempotent on a client order id. B1's
corrected contract already routes adoption through `adopt_ack`, so the wrapper
must treat "entry action on an onDone target" as a lint rule.

### 2. `always` → invoked child — **clean on both lanes, both directions**

`z_b18.py` against B18 `kill_switch`: `engaging` has no event handler, only
`entry` actions and an `always` fan-out selecting `cancelling` (an `invoke` of
`cancel_all_working_orders`), whose `onDone` chains through `always`/guards into
`flattening` (a second invoke) and on to `engaged`.

```
svc_calls = ['cancel_all_working_orders', 'flatten_all_positions']
states    = ['kill_switch.engaged']   error=None   snapshot_ok=True
```

Identical on `async def` and `def`. The *other* half — #204's roll-forward — is
now also green: `repro/ld01_always_rollforward.py` covers a state entered and
exited inside one macrostep (case A rolled forward by an `always`, case B rolled
back by `actionErrorPolicy`) across **6 lanes** (async/def service × async/sync
engine):

```
0/6 lanes leaked the service call
```

A state that never survives its macrostep **never submits its service**, on
either engine and for either service kind. On `f28719c` this held on one engine
only; #204 closes it everywhere. For an OMS this is the difference between a
rolled-back leg and a real order on the wire.

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

Exactly one drop per run, and it is the runaway's own `SPIN` shed as
`chain_budget`. **Not one external priority send was destroyed**, at either
volume, in either service style. The kill switch preempts: it reaches `engaged`
(through its invoked child) while the noise region is still being shed. #192's
provenance-based shedding holds unchanged on `19cb1f1`.

## `after` timers under `SimulatedClock` (#203)

**The corrected B1–B5 JSON contains no `after` block at all** (`grep -c '"after"'`
= 0 on all five): every deadline on the order path is modelled as an external
event (`IDLE_DEADLINE`, `SL_DEADLINE`, `QUIESCE_DEADLINE`) minted by the
wrapper's timer service. So there is nothing on the contracts themselves for
#203 to change — but the wrapper's timeout supervisor is exactly the code
tempted to hand-build one, so `repro/r9_after_provenance.py` pins the new rule
on a minimal 60-second timer:

```
style=async|def  start=['sub.waiting']
  forged AfterEvent -> ['sub.waiting'] (fired=send-raised:UnknownEventError)
  clock +61s        -> ['sub.timed_out']
  VERDICT=OK
```

A hand-built `AfterEvent` with the right `type` string is now **refused at the
inbox** (`UnknownEventError` — it never even reaches selection), while the
genuine `SimulatedClock` advance fires the timer normally. On `f28719c` the
forged event fired the 60 s timer instantly. **Wrapper consequence:** the
supervisor must cancel/re-arm through the clock or an ordinary domain event; it
can no longer synthesise `AfterEvent` to force a timeout, and if any of our shim
code does so it will now raise rather than silently succeed.

## Snapshot / restore at quiescence

Every driver calls `snap_roundtrip` before the first event and after every
macrostep: `get_persisted_snapshot()` → fresh machine built from the same JSON
with a fresh stub → `Interpreter.from_snapshot` → start → quiesce → compare
`(current_state_ids, context, status, deferred_count)`. Across B1–B5 and B18,
both service styles, **every round-trip matched with no drift and no refusal** —
including mid-flight configurations with a deferred `EXEC` outstanding
(`B1.defer.exec_replayed`), a quarantined order, and the kill switch parked in
`engaged` after two chained invokes. #205's new `from_snapshot(minimum_version=,
expected_machine_hash=)` parameters are opt-in and default to the round-8
behaviour, so no legitimate payload our contracts produce was rejected; #208's
"never success-shaped over an empty configuration" likewise changed nothing we
can observe, because no round-trip produced an illegal configuration.

## Cross-engine parity

`z_parity.py` runs B1, B3, B4, B5 and B18 on the async engine and on
`SyncInterpreter` (plain `def` services, as the sync engine requires) and
compares `states`, `context`, `actions` and `svc_calls` element-for-element.
**All 39 comparisons match, in both passes** (up from 16 on `f28719c`, which
covered fewer machines). `SyncInterpreter` still accepts no `max_queue_size` /
`overflow_policy` — the bounded RAISE inbox is async-only, a documented
asymmetry, not a regression.

## Are C-04 (B16) and C-07b (B18) still Blockers in the corrected JSON?

**Both are still present. Neither was fixed in a later contracts pass.** The
`onUnhandled` / `actionErrorPolicy` header of every stored B16 and B18 across
`battle-3ed3099`, `battle-6db65d8` and `battle-f28719c` was read directly, and
both defects were then reproduced end-to-end on `19cb1f1` in both service styles.
These are **OUR-CONTRACT** findings; the library behaves exactly as documented in
each case.

### C-07b — B18 kill switch bricked by a guard-denied `RELEASE` — **PRESENT**

Header check: `B18` carries `onUnhandled: "error"` in **all three** contract
passes (`3ed3099`, `6db65d8`, `f28719c`) — the round-6 correction that was
supposed to remove it never reached the JSON. `repro/r7_c07b_b18_release.py`
engages the switch, presses `RELEASE` while the operator is *not* elevated (the
`owner_and_elevated` guard denies), then elevates and presses again:

```
style=async|def  onUnhandled=error   engaged=['kill_switch.engaged']
  denied_RELEASE  -> status=error
      error=UnhandledEventError("Event 'RELEASE' is not handled in any active
      state ['kill_switch.engaged'] and the machine's onUnhandled policy is
      'error'.")   unhandled=[('RELEASE','errored')]
  elevated_RELEASE -> states=['kill_switch.engaged'] status=error
  C-07b PRESENT=True (kill switch CANNOT be released after a guard-denied press)
```

A guard-denied transition leaves the event unhandled by the active
configuration, and `onUnhandled: "error"` faults the interpreter. **One wrong
button press puts the kill switch into `status=error` permanently** — the
subsequent legitimate, elevated `RELEASE` is refused and the firm stays blocked
from trading with no in-chart way out. Identical on both lanes.

The same script with `UNH=defer` is the fix and is green on both lanes:

```
  denied_RELEASE  -> status=running  unhandled=[('RELEASE','deferred'), ...]
  elevated_RELEASE -> states=['kill_switch.clear']
  C-07b PRESENT=False
```

Note the deferred press replays on the next legal configuration, which is
benign here (it re-attempts the release the operator wanted) but must be
considered: `defer` means the *old* button press can take effect later. If that
is unacceptable, `onUnhandled: "ignore"` plus an explicit self-transition
logging the denial is the alternative. **Action: remove `onUnhandled: "error"`
from `B18.machine.json` / `B18.catalogue.json` in every contracts directory, and
add a rule that no machine with a guarded transition out of a safety-critical
parked state may use `onUnhandled: "error"`.**

### C-04 — B16 elevation survives `LOGOUT` — **PRESENT**

Structural read of `B16.machine.json`: `session` is a parallel chart;
`elevation.elevated` handles `ELEVATION_DEADLINE`, `STEP_UP_OK` and `REVOKE` —
but **not `LOGOUT`**, while `auth.active` handles both `REVOKE` and `LOGOUT`.
`repro/r8_c04_b16_elevation.py` drives `MFA_OK` → `STEP_UP_OK` → kill event:

```
style=async|def  kill=LOGOUT
   after=['session.auth.revoked', 'session.elevation.elevated']
   elevated_until_us=9999999  revoke_reason='logout'  deferred=0
   STILL_ELEVATED_AFTER_LOGOUT=True
style=async|def  kill=REVOKE
   after=['session.auth.revoked', 'session.elevation.normal']
   elevated_until_us=None     revoke_reason='admin'
   STILL_ELEVATED_AFTER_REVOKE=False
C-04 PRESENT=True  elevation survives LOGOUT
```

After a logout the `auth` region is in its `final` `revoked` state while the
`elevation` region is still `elevated` **and `context.elevated_until_us` is still
in the future**. Any authorisation predicate written as "the `elevated` tag is
present" or "`elevated_until_us > now`" — which is precisely what B18's
`owner_and_elevated` guard is — grants privileged operations on a dead session
until the elevation deadline expires. `REVOKE` is handled correctly, which makes
the gap easy to miss in review: the *admin* path is safe and the *user* path is
not. Identical on both lanes; `deferred=0`, so nothing is queued to rescue it.

**Action: add `LOGOUT` (and any other `auth`-terminating event —
`IDLE_DEADLINE`, `ABSOLUTE_DEADLINE`, `MFA_TIMEOUT`) to `elevation.elevated`
with `target: #session.elevation.normal, actions: [clear_elevated]`. Better, as
CV-C37 already hints: make the elevation region's exit a single
`SESSION_TERMINATED` event raised by `auth.revoked`'s entry, so the two regions
cannot drift again.** Until then, no authorisation check may read the elevation
region or `elevated_until_us` without also asserting `auth` is not `revoked`.

## Findings

| # | Class | Item | Change vs `f28719c` |
|---|---|---|---|
| F1 | NEEDS-WRAPPER | `rollback` + `invoke.onDone` re-arms a side-effecting service once per lap until `maxIterations` sheds it, plateauing at exactly **`maxIterations + 3`** on both lanes. Lint rule: no fallible entry action on an `onDone` target; make placement idempotent on a client order id. | Unchanged in mechanism; the constant and lane parity are now pinned (#209/#210). |
| F2 | NEEDS-WRAPPER | A chain trip is still **not** surfaced on `on_error` or `interpreter.error`; `status` stays `running`. But a *stranded* trip is now fully observable: `RunawayChainError.stranded`, `on_invocation_stranded`, `has_dormant_invocations`, `pending_invocations()`, and an ERROR log. `CvErrorHooks` must implement `on_invocation_stranded` and subscribe to `on_event_dropped`. | **Materially improved** (#207). The "is it stranded or just slow?" ambiguity is gone. |
| F3 | NEEDS-WRAPPER | `last_error` is cleared once settled on the `async def` lane but retained on the `def` lane (`r5_lasterror_kind.py`, still reproduces). Sample per step, never asynchronously. | Unchanged — not addressed by #203–#210. |
| F4 | OUR-HARNESS | `send(wait=True)` resolves at the end of the macrostep, **not** after an `async def` service chain settles. Harness settle widened to 5×50 ms. Real wrapper code must not treat a `wait=True` receipt as "the service chain has finished". | Unchanged. |
| F5 | NEEDS-WRAPPER | A hand-built `AfterEvent` is now refused at the inbox with `UnknownEventError` (#203). Any shim that synthesises `AfterEvent` to force a timeout will start raising; drive timers through the clock or a domain event. | **New on `19cb1f1`** — a behaviour change our wrapper must absorb. |
| F6 | OUR-CONTRACT | **C-07b still present**: `B18` carries `onUnhandled: "error"` in all three contracts directories; a guard-denied `RELEASE` faults the interpreter and the kill switch can never be released. Blocker. | Unchanged — never fixed in any contracts pass. |
| F7 | OUR-CONTRACT | **C-04 still present**: `B16.elevation.elevated` has no `LOGOUT` handler, so elevation (state *and* `elevated_until_us`) survives a logout while `auth` is `revoked`. Blocker. | Unchanged — never fixed in any contracts pass. |

**No LIBRARY finding.** Every behaviour reproduced above is either the
documented contract of `rollback` / SCXML re-entry / `onUnhandled`, or a
round-9 fix (#203, #204, #207, #209, #210) working as claimed. F6 and F7 are
ours.

## Verdict

B1–B5 and B18 are **green end-to-end on `19cb1f1` in both service styles** —
161 checks per lane, 0 failures, no build refusal, no snapshot drift, 39/39
cross-engine parity comparisons matching. Round 9 is a **net improvement with no
regression** on the order path: the roll-forward half of the invoke-arming rule
now holds on both engines (#204 — a rolled-back leg never reaches the wire), the
stranded-invocation strand is named rather than inferred (#207), and the
rollback plateau is a pinned constant on all lanes (#209/#210). The one
behaviour change we must absorb is F5 (`AfterEvent` provenance).

**The binding constraints remain ours, not the library's.** C-04 and C-07b are
both **still Blockers in the corrected JSON**, reproduced here on both lanes,
and neither is waiting on upstream — each is a handful of lines of chart. They
should be fixed in the contracts directory and re-run against this same suite
before the phased shim retirement in `54-r9-final-readiness-verdict.md`
proceeds past its first phase.
