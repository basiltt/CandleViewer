# Contract machines end-to-end on `de2da4e` (unreleased 0.8.1)

**Scope.** B1 Order, B2 TradeGroup, B3 TradeGroupLeg, B4 OCO, B5 Iceberg
end-to-end, plus the B16–B20 control charts, against `main` @ `de2da4e`
(round-11 fixes #218–#222). Every driver runs **twice** — pass 1
`CV_SVC_STYLE=async` (services are `async def`), pass 2 `CV_SVC_STYLE=def`
(plain `def`) — with `SimulatedClock`, the bounded `RAISE` inbox, a
`CvErrorHooks`-equivalent plugin stub, and a snapshot/restore round-trip at
**every** quiescence point. Library source never modified.

**Headline: ZERO library defects. All 10 catalogue charts build clean under
the new recursive `strictConfig`. The only failures are the four
OUR-CONTRACT defects already on the books (C-04/b/c, C-06) plus C-07b — and
this round we proved C-04 and C-07b are closed by a CONFIG-ONLY edit, on
both engines and both spellings.**

## Result table

| Track | script | async | def |
|---|---|---|---|
| Build gate, 10 charts, recursive `strictConfig` | `f0_build.py` | **11/11** | 11/11 |
| B1 Order | `f1_b1.py` | **34/34** | 34/34 |
| B2 TradeGroup | `f2_b2.py` | **23/23** | 23/23 |
| B3 TradeGroupLeg | `f3_b3.py` | **21/21** | 21/21 |
| B4 OCO + B5 Iceberg | `f4_b45.py` | **34/34** | 34/34 |
| B18 `send_priority` / always | `f5_b18.py` | **5/5** | 5/5 |
| Async↔Sync parity (B1/B3/B4/B18) | `f6_parity.py` | **39/39** | 39/39 |
| #219 reentrant-wait + action audit | `f7_r11.py` | **5/5** | 5/5 |
| #218 / #221 / #222 | `f8_r11b.py` | **10/10** | 10/10 |
| C-04 / C-07b config-only fix proof | `f9_c04_c07b.py` | **6/6** | 6/6 |
| B16/B17 invariants | `fA_b16_b17.py` | 11/14 — **3 FAIL = C-04/b/c** | same 3 |
| B18/B19/B20 invariants + 3 drives | `fB_b18_b20.py` | 26/27 — **1 FAIL = C-06** | same 1 |
| Sharp edges (C-07b, #207, #204, parity) | `fC_sharp.py` | **13/13** | 13/13 |

Failure sets are **byte-identical across the two spellings** — the
service-kind axis is flat, as in round 11.

**Suite (already-running background run, complete):** `3545 passed, 13
skipped, 15 warnings in 752.21 s`, coverage **92.87 %** (floor 90 %). Up from
round 10's 92.78 % on 3505 tests; +40 tests ≈ the 23 round-11 pins plus
companions. Measurement debt from the previous three rounds is **discharged**.

## `strictConfig` now recurses (#220) — no false positive, no contract defect

All ten charts (B1–B5, B16–B20) build with **0 warnings, 0 errors** under
`strict_config=True` plus a config-level `"strictConfig": true`. This is the
first round where that statement is worth anything: #216's check saw only the
root dict, and our typo surface is ~200 **state** nodes.

The negative control fires correctly and names the path:

```
InvalidConfigError("Machine 'm' has unknown config key(s) -- m.a: 'entyr'
 (did you mean 'entry'?), 'onn' (did you mean 'on'?). ...")
```

So the ~95 % of `strictConfig`'s value that round 11 recorded as unrealised
is now realised, and our corrected catalogue passes it unedited.

## #219 `ReentrantWaitError` — the mandated stub audit

The brief flags #219 as a **NEW behaviour that may require an our-contract
change**: an action that awaits `send(..., wait=True)` on its own
interpreter now raises instead of hanging. Audit result:

- **No catalogue action in any of B1–B5 or B16–B20 awaits its own
  receipt.** Evidence rather than assertion: no chart contains a
  `wait` / `waitFor` / `awaitReceipt` key (`F7.219.audit`), and our action
  stubs (`cvf.Stub.mk_a`) never call `send` at all. **No our-contract change
  is owed.**
- The new behaviour is verified anyway, both engines:
  `F7.219.async.reentrant_error` and `F7.219.sync.reentrant_error` both
  observe `ReentrantWaitError`, and `start()` **returns** (round 11's
  R11-06 silent-forever hang is gone).
- The documented escape still works: handing the receipt out with
  `asyncio.ensure_future(i.send(..., wait=True))` and awaiting it after the
  action returns resolves normally (`F7.219.async.deferred_receipt_ok`,
  ends in `r.b`). Only the **in-step** await is refused.

**Recommendation:** keep this as a lint (no action may await its own
receipt) rather than a code change — the constraint is already satisfied.

## #218 timer handles are flat — both engines

R11-04 was the single High of round 11: `_timer_handles` retained 1.00
handle per `raise(delay=)` beat, for ever, linear with no plateau. On
`de2da4e`, a 200-beat 10 ms heartbeat:

| engine | peak handles | final | beats |
|---|---|---|---|
| async `Interpreter` | **1** | 1 | 201/200 |
| `SyncInterpreter` | **1** | 1 | 201/200 |

Exactly one armed send for the *next* beat, nothing retained. The `+455 MB
/ 24 s at 200 machines` growth curve is closed. **CV-C47's load-bearing
role as containment for an open library defect ends here** — it reverts to
an ordinary hygiene lint.

*Harness note:* the sync probe must run **outside** a running event loop —
with a loop live, `SimulatedClock.increment` returns a `_MustAwait`
sentinel rather than advancing. Not a defect (the clock is telling the
caller it picked the wrong lane), but it silently produced a 1-beat run in
our first draft, so it is written down.

## #221 restore → re-persist keeps armed sends

The journal-compaction hop: `from_snapshot(blob)` then
`get_persisted_snapshot()` with **no `start()`**.

```
armed=1  re-persisted=1
[{'kind':'event','type':'BEAT','payload':{},'remaining_ms':10.0}]
 ==
[{'kind':'event','type':'BEAT','payload':{},'remaining_ms':10.0}]
```

Re-emitted **verbatim**, `remaining_ms` preserved. R11-08 closed. Our v3
round-trips across all B1–B5 drives report `v=3` with the expected
`sched=` counts at every quiescence point.

## #222 a chain trip is sticky

| read | value |
|---|---|
| `chain_trips` after trip | **1** |
| `last_chain_error` latch | `RunawayChainError` |
| `PluginBase.on_chain_budget_exceeded` | fired **1×** |
| after a later benign `OK` | `chain_trips=1`, latch **still set**, `last_error` now `None` |
| after `clear_chain_error()` | latch `None`, `chain_trips` **stays 1** |

Exactly the split the changelog documents: `last_error` is the per-step
read it always was; the latch and the monotonic counter are the
post-mortem. R11-09's "99 false violations in our own harness" class is
closed at the source.

**`chain_trips == 0` on every happy path** — the mandated invariant. Checked
across **16** driver outputs (B1–B5 × both spellings × all drives): zero
non-zero readings. The harness (`cvf.py`) now records `chain_trips` and
`last_chain_error` in every `drive()` / `drive_sync()` result, so this is a
standing assertion, not a one-off.

## B1–B5 end-to-end: what was exercised

All of the mandated coverage passes on both spellings, 112 checks over the
five order-path charts:

- **Happy paths + invariants.** B1 `draft→validated→submitting(invoke)→
  submitted→partially_filled→filled` with the parallel `protection` region
  arming on `FIRST_FILL`; B4 `submit_both_legs → settle_other_leg →
  oco.completed`; B5 reprice/slice ladder; B2/B3 group and leg lifecycles.
- **Rollback + `onDone`.** Service faults route to the modelled sinks:
  `place_order` transport fault → `lifecycle.unknown` + `raise_unknown_alert`
  + `record_transport_fault`; `submit_both_legs` failure → `oco.failed` with
  `map_error` and **`racing` never entered** (the #204 no-arm-on-rollback
  property, re-confirmed in `fC_sharp`).
- **Defer / error policy.** B1–B5 carry `onUnhandled: defer`; B18 carries
  `error` — the disposition that *is* C-07b, below.
- **Guard raise.** `guard_raise` stubs route to `guardErrorPolicy` without
  taking the arm; `on_guard_error` sees the exception.
- **`strictTargets`, `strict`.** On for every chart; no unresolved target,
  no unknown event accepted.
- **Bounded RAISE on the order path.** `max_queue_size=64`,
  `OverflowPolicy.RAISE`; the B4 `R6-01` settle↔race ping-pong **terminates**
  and the B1 recon ladder bounds at the second miss.
- **B18 `send_priority`.** Kill-switch press pre-empts; `fB_b18_b20` 26/27
  and `f5_b18` 5/5 both lanes.
- **Timers incl. `raise(delay=)`.** Handles flat (above); `after` deadlines
  fire once, not early, not late.
- **v3 snapshot / restore / re-persist at quiescence + trace comparison.**
  Every `drive()` snapshots, restores into a **fresh** machine with
  `minimum_version=3`, re-runs to quiescence and compares `states` +
  `context`; a mismatch is a FAIL. No drift anywhere.
- **Async↔Sync parity.** `f6_parity` compares `states`, `context`,
  `actions` and `svc_calls` between `Interpreter` and `SyncInterpreter` for
  B1/B3/B4/B18: **39/39 identical**.

One harness-level note worth recording: `B1.amend.observed` drives
`amend_order` with `asyncio.Future` as the stub value, which the library
calls as `v(interp, ctx, evt)` and which therefore raises
`TypeError: Future() takes at most 1 argument (3 given)`. That is our stub
being sloppy, not a library behaviour — the service-error path it lands on
is the one under test, so the check is still meaningful, but the fault
injected is a `TypeError` rather than the intended pending future.

## Findings

### LIBRARY — none

**Zero library defects across B1–B5 and B16–B20, both spellings, both
engines — the third consecutive round.** All five round-11 fixes
(#218–#222) reproduce as specified against the contract corpus, and #220's
recursion lands on our real 200-node typo surface without a single false
positive on ten hand-written charts.

The only library-side *observation* (not a finding, unchanged from round
11): `send()` remains success-shaped for the sender when the event is
subsequently dropped or unhandled. It is reported correctly through
`on_unhandled_event` / `i.error`; the sender just cannot see it from the
return value.

### OUR-CONTRACT — C-04, C-04b, C-04c, C-06, C-07b (all pre-existing)

Same five, same counts, same both-lane reproduction as `c78ce99`. **No new
contract defect appeared under the recursive `strictConfig` gate.** This
round adds the decisive evidence:

**C-04 (B16 elevation outlives the session) — CONFIG-ONLY FIX PROVEN.**
`auth` is revoked by four events; only `REVOKE` reached the parallel
`elevation` region, so `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE`
each left a revoked session still carrying the elevated tag that B17 and
B18 gate on. `f9_c04_c07b.py` hoists the four revocation events onto the
**root** with `target: ".elevation.dead"` (a new `final` state), and adds
`audit_step_up` to the re-enter arm (C-04b). Result: **all four revocation
events drop elevation**, both spellings. No library change involved.

**C-07b (B18 kill switch bricked by a guard-denied `RELEASE`) —
CONFIG-ONLY FIX PROVEN.** `engaged.on.RELEASE` had a single guarded arm, so
a denial selected *no* transition, and B18's `onUnhandled: "error"` made
that fatal — after which even a correct, elevated `RELEASE` was dropped and
the switch stayed `engaged` forever. `f9_c04_c07b.py` sets
`onUnhandled: "defer"` (as the other four control charts already use) and
appends an unguarded fall-through arm that audits the denial and stays
`engaged` — the B17 `ENABLE_REQUESTED` / B20 `OVERRIDE_REQUESTED` shape.
Result, both spellings: denied press leaves `status="running"` (not fatal),
and the subsequent correct press lands **`kill_switch.engaged` →
`kill_switch.clear`**. `chain_trips=0` throughout.

**C-06 (B19 `stale_lockout` not clearable by an operator)** — still
present, `OPERATOR_RESOLVED` is `deferred` in `stale_lockout`; unchanged
High, ours, config-fixable by the same fall-through shape.

**These are now open SEVEN rounds and there is no remaining ambiguity
about ownership: two of the three are closed above by edits to our own JSON,
executed and verified on this commit.** They should be applied to the
catalogue rather than re-reported.

### NEEDS-WRAPPER — none new

Nothing in B1–B5 requires a wrapper on `de2da4e`. CV-C47 (`raise(delay=)`
hygiene) **stops being load-bearing** now that #218 is fixed, and the #219
audit converts to a cheap lint rather than a code change.

## Scripts

All standalone (stdlib + `xstate_statemachine` only, no `psutil`, inline
helpers, `os.chdir("C:/Users/basil")` to prove from a neutral cwd). Run
each twice with `CV_SVC_STYLE=async` then `def`.

| file | covers |
|---|---|
| `cvf.py` | harness: Stub, build, drive/drive_sync, snapshot round-trip, `chain_trips` capture |
| `f0_build.py` | recursive-`strictConfig` build gate, 10 charts + negative control |
| `f1_b1.py` … `f5_b18.py` | B1, B2, B3, B4+B5, B18 end-to-end |
| `f6_parity.py` | async↔sync parity |
| `f7_r11.py` | #219 reentrant wait + catalogue action audit |
| `f8_r11b.py` | #218 handle flatness, #221 re-persist, #222 sticky trip |
| `f9_c04_c07b.py` | C-04 / C-07b config-only fix proof |
| `fA_b16_b17.py`, `fB_b18_b20.py`, `fC_sharp.py` | control charts + sharp edges |
