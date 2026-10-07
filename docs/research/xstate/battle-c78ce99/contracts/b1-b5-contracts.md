# B1–B5 contract machines end-to-end on `c78ce99`

**Library:** `xstate-statemachine` @ `c78ce99` (merge of #217, round-10 fixes
#212–#216; unreleased 0.8.1 — `__version__` still reads `0.8.0`, so key on the
commit).
**Contracts:** `B1` Order, `B2` TradeGroup, `B3` TradeGroupLeg, `B4` OCO,
`B5` Iceberg, plus `B16`–`B20` for the control-plane re-checks. The JSON is
byte-identical across the `19cb1f1`, `f28719c` and `3ed3099` contracts
directories (md5-verified); this pass copied the `19cb1f1` set forward
unmodified.
**Mandated config, every run:** `actionErrorPolicy: rollback`,
`onUnhandled: defer` (order path) / `error` (control plane),
`guardErrorPolicy: raise`, `strictTargets`, `strict`, **`strict_config=True`**,
bounded `RAISE` inbox (`max_queue_size=64`, `OverflowPolicy.RAISE`),
`SimulatedClock`, and a `CvErrorHooks`-shaped plugin stub carrying
`on_invocation_stranded` and `on_invalid_event`.

## Headline

**356 checks, 0 FAIL** — 178 per service-spelling lane, every driver run twice
(pass 1 all services `async def`, pass 2 all plain `def`), async engine primary
with sync-engine parity on configuration, action trace and service-call trace.

| Driver | Covers | async | def |
|---|---|---|---|
| `w0_build.py` | #216 `strictConfig` conformance of the catalogue | 25/25 | 25/25 |
| `w_b1.py` | B1 Order, happy + every invariant + R6-03 + parity | 34/34 | 34/34 |
| `w_b2.py` | B2 TradeGroup | 23/23 | 23/23 |
| `w_b3.py` | B3 Leg | 21/21 | 21/21 |
| `w_b45.py` | B4 OCO + B5 Iceberg | 34/34 | 34/34 |
| `w5_timers.py` | #212 delayed-send rule, #213 v3 armed sends, `after` | 15/15 | 15/15 |
| `w6_sharp.py` | #207 plateau, #204 no-arm, C-07b, B16–B20 parity | 13/13 | 13/13 |
| `w7_edges.py` | C-04, B18 priority under a chain, #214 restore-strict | 9/9 | 9/9 |
| `w8_214_hook.py` | #214 `on_invalid_event` reachability | 4/4 | 4/4 |

Every script is standalone (stdlib + `xstate_statemachine` only, inline
helpers in `cv78.py`), `chdir`s to the neutral `<home>` before doing
any work, and writes its own `res_*.json`.

**Verdict unchanged from the row-8 ADOPT.** The library side of B1–B5 is clean
on `c78ce99`: nothing in the round-10 semantic reversals disturbs any contract,
and #213's layout v3 is a strict gain for the OMS. The two open blockers remain
**ours**, in the catalogue JSON, exactly as `58-r10-findings-register.md`
recorded them — neither has been fixed in any contracts pass.

## The structural finding that shapes this whole pass

**Our catalogue declares no `after` transitions and no `raise(delay=)` actions
— anywhere.** A scan of all twenty machines returns empty for both:

```
B1..B20  after= []   delayed_sends= []
```

Every deadline in the OMS is a *host-side* timer that a plain action stamps:
`arm_sl_deadline`, `arm_recon_deadline`, `arm_quiesce_deadline`,
`arm_submit_timeout`, `schedule_refill_deadline`, `next_refill_at_us`. The
chart declares only the *event* the timer will deliver (`SL_DEADLINE`,
`REFILL_DUE`, `SUBMIT_TIMEOUT`, `COOLDOWN_DUE`).

Two consequences, both load-bearing:

1. **#212 and #213 are unreachable from the catalogue as written.** The
   round-10 reversal that matters most — a delayed self-send is a timer, not a
   chain debt — cannot fire on a chart with no delayed self-sends. Neither can
   #213's `scheduled_sends`: our snapshots carry `"scheduled_sends": []` at
   every quiescence point in every driver (visible in every
   `snapshot` note as `v=3:sched=0`).
2. **The risk therefore lives in the wrapper, not the chart.** Whether a
   deadline survives a process restart is currently a property of *our* timer
   store, which the library's snapshot cannot see. `w5_timers.py` grafts the
   timers the wrapper would own onto the real contract shapes and proves the
   library would handle them correctly — which is the argument for moving them
   into the chart. See §5.

## 1 · #216 `strictConfig` — the catalogue is clean

The brief flagged any `strictConfig` hit as an our-contract defect. **There are
none.** `w0_build.py` checks each of B1–B5 four ways and adds a negative
control so a vacuous pass is impossible:

| Check | Result |
|---|---|
| No top-level key outside `KNOWN_MACHINE_KEYS` (and no `x-` needed) | ✅ B1–B5 |
| `create_machine(..., strict_config=True)` builds | ✅ B1–B5 |
| Config-level `"strictConfig": true` builds | ✅ B1–B5 |
| No WARNING emitted at default `strict_config=False` | ✅ B1–B5 |
| **Negative control** — injected `actionErrorPolicyy` is refused | ✅ B1–B5 |

Every contract's top-level key set is a subset of the known list:
`actionErrorPolicy, context, guardErrorPolicy, id, initial, onUnhandled,
spawnBlockingTimeout, states, strict, strictTargets, type`. The did-you-mean
hint fires correctly on the control:

```
InvalidConfigError("Machine 'order' has unknown top-level key(s)
 'actionErrorPolicyy' (did you mean 'actionErrorPolicy'?). ...")
```

**Recommendation (LIBRARY-adjacent, ours to act on):** set
`"strictConfig": true` in all twenty catalogue files and pass
`strict_config=True` at every `create_machine` call site. The whole class of
"a misspelled safety policy silently reverts to permissive" — which for us
would mean `actionErrorPolicy` degrading from `rollback` to `continue` on the
order path — becomes a build-time error for free. `cv78.build()` already
defaults it to `True`, so every check in this pass ran under it.

## 2 · B1 Order — 34/34 per lane

Parallel chart (`lifecycle` ∥ `protection`). Snapshot/restore round-trip at
**every** quiescence point, with `minimum_version=3` on the restore side, and a
full observable comparison (configuration + context + status + deferred count).

- **Happy path** `VALIDATE → SEND → EXEC → FIRST_FILL → EXEC → SL_LOST`: two
  parallel leaves throughout; lands `lifecycle.partially_filled` ∥
  `protection.sl_missing`; `raise_naked_position_alert` fires. All seven
  snapshots `v=3`, zero drift.
- **Invariants held:** local reject on failed gates; transport fault →
  `unknown` + `raise_unknown_alert` + `record_transport_fault`; `RECON_MISS`
  re-enters once then rejects on the second (`recon_misses == 1`); duplicate
  link id → `submitted` + `mark_needs_lookup`; `FAULT` → quarantine and
  `RECON_FOUND_LIVE` recovers with `raise_critical_alert`; `attach_native_sl`
  `onError` → `sl_missing` + `request_fallback_sl`; cancel path adopts the ack.
- **`onUnhandled: defer` works as designed:** an `EXEC` arriving *before*
  `SEND` is deferred and replayed, landing `partially_filled`. Disposition
  `deferred` is reported on every hop.
- **`guardErrorPolicy: raise`** is observable: a raising `ret_code_ok` surfaces
  on `on_guard_error` without killing the interpreter.
- **R6-03 explicitly driven** (`adopt_ack` raises → rollback to `submitting` →
  `place_order` re-armed): terminates, no timeout, `status=running`,
  `error=None`, 127/91 action errors reported. **`place_order` was called 128
  times (async) / 91 (def).** This is the mandated rollback+onDone storm and it
  behaves exactly as pinned — but see the standing constraint below.
- **Sync parity:** identical configuration, identical 11-action trace,
  identical service-call trace `['place_order', 'attach_native_sl']`.

> ⚠️ **Standing our-contract constraint (unchanged, not new).** The R6-03 storm
> places 128 real orders before the chain cut. On a live venue that is 128
> duplicate submissions. The library is behaving correctly — `rollback` means
> re-enter, re-enter means re-invoke — and #207 makes the strand observable, but
> **an idempotency key on `place_order` is mandatory in the wrapper.** This is
> the single most dangerous interaction in the catalogue and it is ours.

## 3 · B2 / B3 / B4 / B5 — 78/78 per lane

**B2 TradeGroup (23):** happy path to `closed`; partial-open quiesce
(`legs_open=1, legs_failed=1, quiesced=True`); all-fail → `failed`; the
`always`-resolved abort arms correctly; unwind `onDone` → terminal with
`mark_unwound`, `onError` → `failed` + `raise_critical_alert`; deferred
`ALL_LEGS_FLAT`/`EVALUATE` flush to `closed`; R6-03 bounded at 90/96
`unwind_machine` invocations, observable, `error=None`.

**B3 Leg (21):** `always` cascade in `pending` resolves skip-first; preflight
failure → `error`; `resolving` invoke → `open`, service called exactly once;
the unwind sub-chart runs its chain in order `cancel_children_svc →
reduce_only_close → poll_until_flat`; retry ladder bounded at 3 then terminal;
the naked-position alert path fires; R6-03 bounded at 25/22.

**B4 OCO (17):** arm-then-settle; the overshoot path raises the warning alert
*and* journals the double fill *and* calls `reduce_only_market_excess`; arm
failure maps the error; settle retry bounded at 3 → `failed` + alert;
R6-01 ping-pong terminates and settles at `racing` with one settle call.

**B5 Iceberg (34):** refill loop progresses two slices; completion, preflight
failure with **no** child submitted, reprice ping-pong bounded at 2, failure
ladder terminal at 4, pause/resume with reconcile, WS-disconnect freeze,
flat-cancel. R6-03 observed at 208/126 `submit_child` — same idempotency
warning as B1.

All snapshot round-trips `v=3`, `sched=0`, zero drift, both lanes, both
engines.

## 4 · #204 `always` → invoked child, and the #207 plateau

**#204 — no arm on a same-macrostep exit.** `B18.cancelling` carries an
`invoke`; giving it an `always` that leaves the state in the macrostep it is
entered must mean the service is never called. It is not: `svc_calls == []`,
configuration `['kill_switch.engaged']` — **on both engines and both service
spellings**. This is the roll-forward half of #193/#204 and it holds.

**#207 — the strand is named, and the plateau is exact.** Driving
rollback+onDone to the cut on B18 (`maxIterations=5`) and B19 (`=25`):

| Chart | limit | plateau | stranded hook | `has_dormant_invocations` | `pending_invocations()` |
|---|---|---|---|---|---|
| B18 | 5 | **7** | ✅ `('kill_switch.flattening','fl',RunawayChainError)` | `True` | `PendingInvocation(... src='flatten_all_positions')` |
| B19 | 25 | **27** | ✅ `('reconciliation.diffing','diff',...)` | `True` | `PendingInvocation(... src='diff_against_local')` |

Plateau is exactly `maxIterations + 2` service calls on **both** lanes, found by
polling to convergence (two identical laps) rather than sampling — the round-9
correction holds. For the OMS this is the difference between "the kill switch
is waiting on a slow venue" and "the kill switch is dead and nothing is
running"; `CvErrorHooks.on_invocation_stranded` must page.

## 5 · #212 and #213 — grafted onto the real contract shapes

Because the catalogue declares no timers (see above), `w5_timers.py` grafts
them onto the genuine B1/B3/B5 shapes — the timers the wrapper owns today —
and runs the result under the new rules.

**`after` on B1's SL deadline.** `protection.sl_pending` (which invokes
`attach_native_sl`) gets `after: {2000: '#order.protection.sl_missing'}`, i.e.
the deadline `arm_sl_deadline` stamps. With the service hanging: the machine
parks in `sl_pending`; the snapshot taken while the deadline is armed is `v=3`;
`clock.increment(2100)` fires it; the configuration becomes
`['order.lifecycle.submitted', 'order.protection.sl_missing']` and
`raise_naked_position_alert` runs. ✅ both lanes.

**#212 — a self-paced cycle is a process, not a runaway.** Grafted onto B5's
*real* refill cycle: `working —CHILD_CANCELLED→ waiting_refill —REFILL_DUE→
submitting_slice —onDone→ working`, each hop armed by a 1 ms `raise(delay=1)`.
Over 40 clock ticks:

```
beats=40 laps=21 status=running err=None states=['iceberg.working']
no RunawayChainError
```

Twenty-one complete laps of a three-state cycle with real `submit_child`
invocations on every lap, and the interpreter is still healthy. **Under the
superseded #206 rule this died at `maxIterations` beats regardless of period.**
The reversal is correct and it is the one that matters to us: an iceberg
refill poller, a reconciliation sweep and a heartbeat are all exactly this
shape. ✅ both lanes.

**#213 — an armed, unfired delayed send survives the snapshot.** B3's
`submitting` already declares `arm_submit_timeout` as an entry action and
already handles `SUBMIT_TIMEOUT → #leg.resolving`; the graft realises that arm
as `raise(event='SUBMIT_TIMEOUT', delay=5000, id='submit_timeout')`, making the
timer the *only* exit from the state — the exact shape #213 was filed against.

```
armed at t=0, 1000 ms elapsed, snapshot:
  "scheduled_sends": [{"kind":"event","type":"SUBMIT_TIMEOUT","payload":{},
                       "remaining_ms": 4000.0, "send_id": "submit_timeout"}]
restore (minimum_version=3) → parked in leg.submitting
  +3000 ms → still leg.submitting   (not early)
  +1200 ms → fires; lookup_by_link_id invoked; leaves submitting
```

The *remaining* delay is what is persisted and re-armed, the `send_id`
survives, and the restored timer is neither early nor lost. ✅ both lanes.
Before #213 this state restored permanently parked — a leg stuck in
`submitting` forever, invisible to reconciliation.

## 6 · #214 — the restore path applies `strict`

Our B1 snapshot is `v=3`. Forging a `pending_events` entry the chart never
declares (`NOT_IN_CHART`) and restoring at `minimum_version=3`:

- the event is **refused, not enqueued** — `last_error` carries
  `UnknownEventError("Event 'NOT_IN_CHART' is not declared by machine 'order'...")`;
- the machine is **still usable** — `status=running`, configuration
  `['order.lifecycle.validated','order.protection.not_required']`;
- a `v2` payload is refused by the floor:
  `SnapshotVersionError("Snapshot version 2 is below the caller's minimum_version=3...")`.

✅ both lanes. Under `strict: true` a snapshot is no longer a way to smuggle
undeclared traffic past the `send()` gate.

### 6.1 · NEW, NEEDS-WRAPPER · `on_invalid_event` is unreachable on the restore path

`w8_214_hook.py`. The #214 note says a restore refusal "is reported
(`on_invalid_event`, `last_error`)". `last_error` is reported. **The hook is
not, and structurally cannot be.** `from_snapshot()` performs the strict check
inside the constructor, and `_report_invalid_event` iterates `self._plugins` —
which is necessarily empty, because the only way to register a plugin is
`interpreter.use(p)` on the object `from_snapshot` has not yet returned. At the
earliest possible registration point the refusal has already happened:

```
on_invalid_event never reaches a plugin        hook.invalid == []
refusal IS visible on last_error (not silent)  UnknownEventError(...NOT_IN_CHART...)
n_plugins_after_use = 1                        (registered, but too late)
```

**Classification: NEEDS-WRAPPER, Low.** Not a correctness defect — the refusal
is not silent, and the library's behaviour (drop and record) is right. But
`CvErrorHooks` cannot learn about traffic dropped on restore through the hook
it subscribes to, so the OMS restore routine **must read `last_error`
immediately after `from_snapshot()` and before `start()`**, and journal it as a
dropped-traffic event. Worth reporting upstream as a docs/API note: either
accept plugins as a `from_snapshot` kwarg, or soften the changelog sentence.

## 7 · C-04 and C-07b — both STILL PRESENT, both ours

Re-checked directly against the corrected JSON on `c78ce99`, both lanes.

### C-07b — B18 kill switch bricked by a guard-denied `RELEASE` · **PRESENT** · Blocker

`B18` still carries `onUnhandled: "error"`. A `RELEASE` pressed by an
unauthorised operator matches no handler in `kill_switch.engaged`, so:

```
denied RELEASE → status=error
  UnhandledEventError("Event 'RELEASE' is not handled in any active state
   ['kill_switch.engaged'] and the machine's onUnhandled policy is 'error'.")
subsequent AUTHORISED RELEASE → send returns ok=True, but
  final=['kill_switch.engaged'], status=error   ← the switch is bricked
```

A mistyped press permanently disables the ability to lift the kill switch.
**OUR-CONTRACT, Blocker, unchanged** — the round-6 fix never landed in the JSON.

The control shows the machine is otherwise sound: with an authorised operator
throughout (`w7_edges.py`), `ENGAGE` runs both kill services in order and
`RELEASE` returns cleanly to `kill_switch.clear`, `status=running`.

### C-04 — B16 elevation survives `LOGOUT` · **PRESENT** · Blocker

```
before LOGOUT: ['session.auth.active',  'session.elevation.elevated']
after  LOGOUT: ['session.auth.revoked', 'session.elevation.elevated']
elevation.elevated handles: ['ELEVATION_DEADLINE', 'REVOKE', 'STEP_UP_OK']
```

`elevation.elevated` declares **no `LOGOUT` handler at all**, so a privilege
elevation outlives the session that granted it: the `auth` region is `revoked`
while the `elevation` region is still `elevated`. Because no handler exists, no
clearing action can run either — `elevated_until_us` cannot be cleared by the
chart. **OUR-CONTRACT, Blocker, unchanged.**

*(Harness note, stated so the evidence is not overread: the stub's actions do
not write context, so `elevated_until_us` reads `null` in this run for harness
reasons, not because the chart cleared it. The structural fact — the missing
handler — is what is asserted.)*

## 8 · B18 `send_priority` under a self-generated chain

With `maxIterations: 12`, an authorised `ENGAGE` drives
`engaging —always→ cancelling(invoke) —onDone→ flattening(invoke) —onDone→
engaged` while the bounded `RAISE` inbox is live:

- chain completes, `error=None`, **nothing dropped** (`p.dropped == []`);
- both kill services ran, in order:
  `['cancel_all_working_orders', 'flatten_all_positions']`;
- the following authorised `RELEASE` lands on `kill_switch.clear`,
  `status=running`.

✅ both lanes. The `always` → invoked-child obligation holds under a live
chain: no arm on a same-macrostep exit (§4), correct arm when the state
persists.

## 9 · Findings register for this pass

| # | Class | Sev | Finding | Status |
|---|---|---|---|---|
| K1 | **LIBRARY** | — | #216 `strictConfig`: B1–B5 (and B16–B20) carry **zero** unknown top-level keys; build clean under `strict_config=True` and `"strictConfig": true`; the typo control is refused with a did-you-mean hint. | ✅ clean, no defect |
| K2 | **LIBRARY** | — | #212 reversal verified on a real contract shape: B5's three-state refill cycle, self-paced by `raise(delay=1)`, runs 40 beats / 21 laps with live invokes, `status=running`. The #206 rule would have killed it. | ✅ correct |
| K3 | **LIBRARY** | — | #213 v3 `scheduled_sends`: remaining delay + `send_id` persist and re-arm; restored timer neither early nor lost. B3's timer-only exit now survives a restart. | ✅ correct |
| K4 | **LIBRARY** | — | #214: restore applies `strict`; undeclared event dropped with `UnknownEventError` on `last_error`, machine stays usable; `v2` refused at `minimum_version=3`. | ✅ correct |
| K5 | **LIBRARY** | — | #207 plateau exactly `maxIterations + 2` on B18/B19, both lanes, polled to convergence; `on_invocation_stranded` + `has_dormant_invocations` + `pending_invocations()` all answer. | ✅ correct |
| K6 | **LIBRARY** | — | #204: an `invoke` on a state exited within its entry macrostep never arms, both engines, both spellings. | ✅ correct |
| K7 | **NEEDS-WRAPPER** | Low | **NEW.** `on_invalid_event` cannot fire for a restore-path refusal — `from_snapshot` reports it before any plugin can be registered. Refusal is still visible on `last_error`. Wrapper must poll `last_error` after `from_snapshot`, before `start()`. | 🟡 open, ours to handle |
| K8 | **OUR-CONTRACT** | **Blocker** | **C-07b PRESENT.** `B18` still carries `onUnhandled: "error"`; a guard-denied `RELEASE` faults the interpreter and the kill switch can never be released. | 🔴 unchanged |
| K9 | **OUR-CONTRACT** | **Blocker** | **C-04 PRESENT.** `B16.elevation.elevated` declares no `LOGOUT` handler; elevation outlives a revoked session. | 🔴 unchanged |
| K10 | **OUR-CONTRACT** | High | **Idempotency.** R6-03 on B1 places `place_order` **128×** (async) / 91× (def) before the chain cut; B5 `submit_child` 208× / 126×. Library-correct, venue-catastrophic. An idempotency key is mandatory. | 🔴 standing constraint |
| K11 | **OUR-CONTRACT** | Medium | **No timers in the chart.** Every deadline is a host-side `arm_*` action, so no deadline is covered by the library's snapshot. #213 exists precisely to make these restart-safe — and we cannot use it. | 🟡 new recommendation |

## 10 · Recommendations

1. **Move host-side deadlines into the charts** (K11, and the reason K2/K3
   had to be grafted). `arm_sl_deadline`, `arm_submit_timeout`,
   `arm_recon_deadline`, `arm_quiesce_deadline` and `schedule_refill_deadline`
   should become `after:` transitions or `raise(delay=, id=)` self-sends. The
   grafts in `w5_timers.py` are working templates against the real shapes.
   The payoff is direct: a deadline in the chart is persisted and re-armed by
   `get_persisted_snapshot()` / `from_snapshot()`, with its *remaining* delay
   and its id; a deadline in our timer store is not. #212 removes the reason
   to avoid the self-paced form.
2. **Turn on `strictConfig` everywhere** (K1). Add `"strictConfig": true` to
   all twenty files and pass `strict_config=True` at every `create_machine`
   call site. Zero migration cost — the catalogue already conforms.
3. **Fix C-07b** (K8): drop `onUnhandled: "error"` on B18, or give
   `kill_switch.engaged` an explicit guard-denied `RELEASE` arm that journals
   the denial and stays engaged. A safety control must not be bricked by an
   unauthorised press.
4. **Fix C-04** (K9): add a `LOGOUT` (and `REVOKE`) handler on
   `elevation.elevated` targeting `elevation.none` with an action that clears
   `elevated_until_us`.
5. **Idempotency key on every order-placing service** (K10) — `place_order`,
   `submit_child`, `submit_entry_order`. Non-negotiable before Phase 3 touches
   a live venue.
6. **Restore routine reads `last_error`** (K7) immediately after
   `from_snapshot()` and before `start()`, and journals any dropped restored
   traffic.
7. **Adopt `minimum_version=3`** at every `from_snapshot` call site (this pass
   ran that way throughout) so a stale v2 payload can never be silently
   accepted.

## 11 · Reproducing

```
PY=<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python
set PYTHONIOENCODING=utf-8  PYTHONUTF8=1
for STYLE in async def:
  CV_SVC_STYLE=$STYLE  $PY w0_build.py
  CV_SVC_STYLE=$STYLE  $PY w_b1.py
  CV_SVC_STYLE=$STYLE  $PY w_b2.py
  CV_SVC_STYLE=$STYLE  $PY w_b3.py
  CV_SVC_STYLE=$STYLE  $PY w_b45.py
  CV_SVC_STYLE=$STYLE  $PY w5_timers.py
  CV_SVC_STYLE=$STYLE  $PY w8_214_hook.py
  $PY w6_sharp.py $STYLE
  $PY w7_edges.py $STYLE
```

Each script `chdir`s to `<home>` before touching anything, imports only
the stdlib and `xstate_statemachine`, and never modifies library source. Shared
helpers live in `cv78.py` (stub logic, `CvErrorHooks` stand-in, `drive` /
`drive_sync`, and the v3 snapshot round-trip comparator).
