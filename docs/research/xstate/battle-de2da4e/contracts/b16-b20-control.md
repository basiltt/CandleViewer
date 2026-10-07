# B16–B20 control machines end-to-end on `de2da4e`

Commit `de2da4e` (unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed
on the commit). Round-11 fixes **#218–#222** in scope. Suite on this commit:
**3545 passed, 13 skipped, 92.87 % coverage** (`suite-de2da4e.log`, complete).

Corrected JSON carried from `battle-c78ce99/contracts/` with **one edit**:
`"strictConfig": true` added to all five files, adopting **CV-C49** from last
round. Mandatory config otherwise unchanged — `actionErrorPolicy: rollback`,
`guardErrorPolicy: raise`, `strictTargets: true`, `strict: true`,
`onUnhandled: defer` (B16/B17/B19/B20) and `error` (B18). Every run uses
`SimulatedClock`, a bounded `OverflowPolicy.RAISE` inbox (`max_queue_size=64`)
on the async engine, and a `PluginBase` stub — now also implementing the new
**`on_chain_budget_exceeded`** hook (#222).

**Pass 1 = every service `async def`; pass 2 = every service plain `def`.**
The service-kind axis is flat on 83 of 84 checks per lane; the **one** cell
that differs is the new library finding below, and it is a genuine difference,
not a harness artefact.

## Headline

| | result |
|---|---|
| `create_machine` B16–B20 under **#220 recursive `strictConfig`** (`d0`) | **20/20 clean** per lane |
| B16/B17 invariants (`d1`) | 11/14 PASS — **3 FAIL = C-04/C-04b/C-04c**, unchanged |
| B18/B19/B20 invariants + 3 mandated drives (`d2`) | 26/27 PASS — **1 FAIL = C-06**, unchanged |
| Sharp edges (`d3`: C-07b, #207, #204, sync parity) | **13/13 PASS** per lane |
| Timer/restore axis (`d4`: #212, #213, #128, #214, #205) | **10/10 PASS** per lane |
| Round-11 axis (`d5`: #218, #219, #221, #222) | 13/13 async · **12/13 `def`** |
| `chain_trips == 0` on every happy path, B16–B20 | **yes, all five, both lanes** |
| **LIBRARY findings** | **1 new** (DE-L1, Medium) |

## #220 — the recursive gate does **not** fire on our catalogue

This was the round's biggest exposure: #220 turned unknown-key checking from a
root-dict scan into a full recursion, so a machine that built clean last round
could be refused this round. The instruction was to decide, for any rejection,
between an our-contract defect and a #220 false positive. **There is no
rejection to adjudicate.** Four builds per machine per lane (`d0_build.py`):

1. **as-carried JSON + `strictConfig`** — all five build clean, **0 warnings**.
   So the recursion finds no misspelled key anywhere in B16–B20: not in a
   nested `states`, not in a parallel region, not in an `on` / `always` /
   `onDone` transition body, not in an `invoke`.
2. **root typo** (`actionErrorPolicyy`) — refused on all five, as in round 10.
3. **NEW nested typo** — `entyr` + `onn` planted in the first child state.
   Refused on all five, and the message **names the path**, e.g.
   `session.auth: 'entyr' (did you mean 'entry'?), 'onn' (did you mean 'on'?)`,
   with both findings in one `InvalidConfigError`.
4. **`x-` / `meta` / `description` / `tags` at nested level** — accepted on all
   five, so our per-state annotation style survives the new gate.

Check (3) is the one that matters. Under `c78ce99` that exact JSON built a
machine with **no entry action and no transition, silently**. B18's
`engaging.entry` is `block_new_orders_immediately` — a one-character typo there
was, until this commit, a kill switch that builds clean and blocks nothing.
**CV-C49 is upgraded from a recommendation to a hard requirement** and is now
applied in-tree: `strictConfig: true` is in all five catalogue files.

## Our action stubs vs #219 — nothing to change, but a rule to add

#219 is a **behaviour change**, so the mandated audit was: does any catalogue
action await `send(..., wait=True)` on its own interpreter? A scan of B16–B20
for send-shaped action names returns `broadcast_revocation`,
`broadcast_live_enabled`, `broadcast_kill_switch`, `broadcast_lockout`,
`broadcast_recon_complete`, `page_owner`, `raise_critical_alert`,
`raise_divergence_alert`, `raise_lockout_alert`. **Every one is an outbound
fan-out to a non-chart subsystem** (alerting, journal, socket broadcast) — none
is catalogued as feeding an event back into its own machine, and none of our
stubs does so. **No our-contract change is required by #219.**

That is luck, not design, so it is worth pinning. The refusal was confirmed on
the real shape (`d5_r11.py`): `broadcast_kill_switch` rewritten as an
`async def` that awaits `interp.send("RELEASE", wait=True)` raises
`ReentrantWaitError` in **0.003 s** rather than hanging, on both lanes, and the
`SyncInterpreter` refuses the identical shape while still accepting the
fire-and-forget `send()`. The old failure mode was a permanent hang of the run
loop — on a kill switch.

### DE-L1 · the documented #219 escape hatch is timing-dependent · **LIBRARY** · Medium

This is the round's one new library finding and the one cell where the
`async def` / `def` lanes disagree.

The changelog states the contract plainly: *"The receipt can still be handed
out (`asyncio.ensure_future(i.send(..., wait=True))`) and awaited later; only
the in-step await is refused."* That is the escape hatch an OMS action needs
when it must both emit an event and later confirm it landed.

`asyncio.ensure_future` copies the **current** context, so the spawned task
inherits `_ACTIVE_ACTION_OWNER = <this interpreter>` from the action that
created it. The guard in `Interpreter.send`'s `_Awaitable.__await__` is

```python
if _ACTIVE_ACTION_OWNER.get() is self and not receipt.done():
    raise ReentrantWaitError(self.id, event_type)
```

so the handed-out receipt is refused unless it is **already done** at the
moment the task first awaits. Whether that holds is a scheduling race decided
by what the action does *after* the hand-out:

| action body after `ensure_future(...)` | result |
|---|---|
| returns immediately | task awaits after the step — `resolved` |
| `await asyncio.sleep(0.05)` — one extra awaited step | **`ReentrantWaitError`** |

5/5 deterministic each way. In the B18 harness the `def` lane hit the refusing
side and the `async def` lane the resolving side — same code, same commit; the
lane difference is just which side of the race each spelling lands on.

The event itself is **not** lost in either case: the standalone machine reaches
`hatch.c` in both runs. What fails is only the caller's receipt, so the damage
is an unexpected exception in a task the action spawned — for us, in a
`broadcast_*` wrapper — not a missed transition.

Repro: `repro/cvde_219_hatch_flaky.py`, standalone (stdlib +
`xstate_statemachine` only), run from `<home>`, carrying both shapes as
each other's control → `REPRODUCED (timing-dependent)`.

This is **not** an R10-01/R11-01-style trust-boundary case: the docs do not
draw a boundary here, they describe the hatch as working. Either the guard
should exempt a task that is no longer the running action (the natural fix is
to reset `_ACTIVE_ACTION_OWNER` in the spawned context, e.g. hand out a future
created under `contextvars.copy_context()` with the owner cleared), or the
changelog should say the hatch requires the hand-out to be the action's last
act. **NEEDS-WRAPPER for us until then** — see CV-C62.

## #218 — the heartbeat we would actually ship holds at one handle

B20 is the natural home for a self-paced poller (CV-C50 made it a permitted
design last round), so `d5_r11.py` builds exactly that: `locked.entry` gains
`{"type": "xstate.raise", "params": {"event": "HEARTBEAT", "delay": 1,
"id": "beat"}}` with a self-targeting `reenter: true` arm, `maxIterations: 5`.

Driven 200 beats on the `SimulatedClock`, sampling
`sum(len(v) for v in i._timer_handles.values())` after every beat:

| | `async def` | `def` |
|---|---|---|
| peak handles over 200 beats | **1** | **1** |
| beats delivered | 200 | 200 |
| `status` / `error` | `running` / `None` | `running` / `None` |
| `chain_trips` | **0** | **0** |

Under `c78ce99` this list grew by one dead handle per beat — for a 1 ms
heartbeat that is ~3.6 M handles per hour of wall clock, on a machine intended
to run for the life of the session. #218 is live and the leak is closed.
`chain_trips == 0` also re-confirms #212 from the new instrument: the heartbeat
is billed as a clock event, not as chain debt.

*Note for the catalogue:* built-in action params must be nested under
`"params"`. Writing `{"type": "xstate.raise", "event": ..., "delay": ...}`
flat is refused at build time with a precise message. Our JSON has no
`raise(delay=)` yet; when it acquires one, this is the spelling.

## #221 — the journal-compaction path is safe

The shape that #221 fixes is one we have an actual job for: load a blob,
rewrite it, never start the machine. Driven on B20 with an armed 4000 ms
`raise(delay=)` expiry deadline (`d5_r11.py`), both lanes:

1. arm, advance 1000 ms, snapshot → `scheduled_sends` has **1** record,
   `{"kind": "event", "type": "EXPIRY_DUE", "remaining_ms": 3000.0,
   "send_id": "expiry"}`.
2. `from_snapshot(..., minimum_version=3)`, **no `start()`**, re-persist →
   still **1** record, byte-identical.
3. restore the twice-written blob and start it: still in `locked` at +2999 ms,
   in `clear` at +3001 ms.

So the deadline survives a compaction round-trip *and* keeps its remainder
rather than restarting from zero. On `c78ce99` step 2 emitted `[]` and the
lockout would have been permanent.

The #128 asymmetry from last round is unchanged and still governs: `after`
deadlines are **not** in `scheduled_sends`, so CV-C51 (`minimum_version=3` plus
a `has_dormant_timers` check on every restore) still stands, and CV-C50's
preference for `raise(delay=)` over `after` for anything that must survive a
restart is now doubly earned.

## #222 — the sticky chain trip, on the mandated rollback drive

Exercised on the drive the brief already mandates: B18 with `page_owner`
raising and `maxIterations: 5`, reached via `all_accounts_flat: false` so the
machine lands in `engaged_incomplete` and the rollback+`onDone` chain opens.
Both lanes, identical:

| | value |
|---|---|
| `chain_trips` after the runaway | **1** |
| `last_chain_error` | `RunawayChainError("… exceeded 5 chained self-generated events …")` |
| `on_chain_budget_exceeded` fires | **once**, matching `chain_trips` |
| after one benign `RELEASE` — `last_chain_error` | **still latched** |
| after one benign `RELEASE` — `i.error` (per-step) | `UnhandledEventError('RELEASE' …)` |
| `clear_chain_error()` | latch → `None`, `chain_trips` stays **1** |

The second row is the whole point. `i.error` is a per-step read and the benign
event overwrote it exactly as documented — under `c78ce99` that was the *only*
record, so a supervisor polling `last_error` would have seen a routine
unhandled-event and concluded the machine was healthy, when it had in fact
discarded work on the kill switch. The latch plus the counter survive it.

**`chain_trips == 0` on every happy path** was asserted for all five machines
in both lanes and holds: B16 `auth.active`+`elevation.elevated`, B17
`eligible`, B18 `clear`, B19 `idle`, B20 `clear` — all with `chain_trips: 0`
and a null latch. Nothing in our catalogue feeds itself work within a step.

**CV-C61 follow-on:** our supervisor must read `chain_trips` /
`last_chain_error` (or take `on_chain_budget_exceeded`), **not** `last_error`,
to decide whether a machine has silently dropped work.

## The carried-forward catalogue defects — all still present, all still ours

Re-tested against the corrected JSON on this commit. Nothing in #218–#222
touches any of them; results are cell-for-cell identical to `c78ce99`.

- **C-04** (B16, **Blocker**) — elevation outlives the session. `LOGOUT`,
  `IDLE_DEADLINE` and `ABSOLUTE_DEADLINE` revoke `auth` while leaving
  `elevation.elevated` live; only `REVOKE` reaches both regions. A revoked
  session keeps the tag that B17 `ENABLE_REQUESTED` and B18 `RELEASE` gate on.
  **Fix (ours):** hoist the four revocation events to the root.
- **C-04b** (Medium) — the second `STEP_UP_OK` takes the
  `elevated → elevated, reenter: true` arm, whose `actions` omit
  `audit_step_up`: a re-elevation is unaudited.
- **C-04c** (Medium) — post-`REVOKE`, `STEP_UP_OK` still re-elevates a dead
  session; the `elevation` region has no terminal state to match
  `auth.revoked`.
- **C-07b** (B18, **Blocker**) — re-checked as mandated, **still present**.
  `engaged.on.RELEASE` has one guarded arm; when `owner_and_elevated` denies,
  no transition is selected, the event is *unhandled*, and B18 is the machine
  carrying `onUnhandled: "error"` — so it is fatal. `send()` returns
  success-shaped, the machine goes `status = "error"`, and a subsequent
  *correct* `RELEASE` is dropped. One wrong button press leaves trading blocked
  with no in-process recovery. **Fix (ours):** drop `onUnhandled: "error"` on
  B18 and give `RELEASE` an unguarded fall-through arm that audits the denial
  and stays in `engaged` — the B17 `ENABLE_REQUESTED` / B20
  `OVERRIDE_REQUESTED` shape, both of which pass this test today.
- **C-06** (B19, High) — `stale_lockout` handles `RECONNECTED` only;
  `OPERATOR_RESOLVED` is deferred and the account stays locked. **Fix (ours):**
  add an `OPERATOR_RESOLVED` arm.

## The mandated drives

All driven on both spellings; every result identical to `c78ce99`.

**(1) rollback + `invoke.onDone`.** B18 (`page_owner` raises, limit 5) and B19
(`store_divergences` raises, limit 25) both trip, plateau **exact** at
limit + 2 service calls (7 and 27), resting in `kill_switch.flattening` /
`reconciliation.diffing`, polled to two successive identical plateaus. #207
stays live: `on_invocation_stranded` fires with the real pair,
`RunawayChainError.stranded` carries the invoke ids,
`has_dormant_invocations` is `True`.

**(2) `always` → invoked child.** Positive: B18 `engaging.always` rolls into
`cancelling` and its `cx` invoke **does** arm; B19 `reporting.always →
divergent` fires with its alert. Negative (#204 `statesToInvoke`): an
unconditional `always` out of `cancelling` means the state is entered and left
inside one macrostep and the service is **never submitted** — `svc_calls == []`
on async and `SyncInterpreter`, both spellings.

**(3) B18 `send_priority` under a self-generated chain.** 12 presses against a
live runaway (limit 50): **12/12 accepted, 0 shed as `chain_budget`**, both
spellings. The only drops are `("RELEASE", "not_running")` after stop — a
different and correct reason.

**Snapshot / restore.** Every drive snapshots at `t0` and after every
macrostep, asserts `version == 3` with `scheduled_sends` present, restores into
a fresh machine under `minimum_version=3`, and compares configuration +
context + status + deferred count. Zero drift, zero `SnapshotMidStepError`,
zero version violations, both lanes. A v2 payload is refused with
`SnapshotVersionError`; a forged event planted in a restored `pending_events`
does not drive the machine.

**Sync parity** — configuration + full action trace + full service-call trace,
**5/5** on all five machines.

## Findings

| id | class | sev | machine | status |
|---|---|---|---|---|
| **DE-L1** | **LIBRARY** | **Medium** | any | **NEW** — the documented #219 `ensure_future` escape hatch raises `ReentrantWaitError` whenever the action does any further awaiting after handing the receipt out. Reproduced standalone, both shapes. |
| C-04 | OUR-CONTRACT | **Blocker** | B16 | still present, both lanes |
| C-04b | OUR-CONTRACT | Medium | B16 | still present |
| C-04c | OUR-CONTRACT | Medium | B16 | still present |
| C-07b | OUR-CONTRACT | **Blocker** | B18 | **re-checked as mandated — still present**, both lanes |
| C-06 | OUR-CONTRACT | High | B19 | still present |
| CV78-T1 | NEEDS-WRAPPER | High | any chart with `after` | unchanged — `after` deadlines are not persisted; check `has_dormant_timers` on every restore |
| — | OUR-CONTRACT | — | B16–B20 | **#220 finds nothing**: no nested unknown key in any catalogue file; `strictConfig: true` now shipped in all five |
| — | OUR-CONTRACT | — | B16–B20 | **#219 needs no catalogue change**: no action awaits `send(wait=True)` on its own interpreter |

### Constraints

- **CV-C49** (upgraded to *required*, and applied) — every catalogue machine
  ships `"strictConfig": true`. #220 makes this catch typos at every nesting
  level, including the one-character `entyr` on `engaging` that would have
  built a kill switch which blocks nothing.
- **CV-C50 / CV-C51** unchanged and re-confirmed (self-paced `raise(delay=)`
  permitted and preferred for restart-surviving deadlines; every restore passes
  `minimum_version=3` and checks `has_dormant_timers` /
  `has_dormant_invocations`).
- **CV-C61** (new) — supervision reads `interpreter.chain_trips` /
  `last_chain_error` or takes `on_chain_budget_exceeded`. `last_error` is a
  per-step read and must never be used to decide whether work was dropped.
- **CV-C62** (new, from DE-L1) — a chart action must never await
  `send(..., wait=True)` on its own interpreter, and must not rely on the
  `ensure_future` hand-out either. If an action needs to emit and later
  confirm, it hands the work to the supervisor outside the step (queue the
  intent in context, act on it from an `invoke` or from the caller), or it
  makes the hand-out its final statement and documents why.

## Verdict for this group

**No change to the row-6 ADOPT.** All five control machines build, run, persist
and restore correctly on `de2da4e` in both service spellings and on both
engines; #218 closes a leak that would otherwise have ruled out the heartbeat
design we want on B20; #220 closes the silent-typo hole on exactly the kind of
JSON our catalogue is; #221 makes the compaction job safe; #222 gives
supervision the signal it was missing. The remaining failures are the same five
**our-contract** defects, two of them Blockers (C-04, C-07b) that must be fixed
in our JSON before these charts go anywhere near a live account. DE-L1 is the
only new library item and is Medium with a clean workaround (CV-C62).

## Scripts

Run from `battle-de2da4e/contracts/`; each driver takes `async` or `def` as
`argv[1]` and was run both ways. Result JSON: `d0_build.<lane>.json` and
`d5_r11.<lane>.json` in this directory; `results/p1_b16_b17.<lane>.json`,
`results/p2_b18_b20.<lane>.json`, `results/p3_sharp.<lane>.json`,
`results/p4_timers.<lane>.json` (the `p*` result names are carried from the
`c78ce99` drivers these are ports of, and are kept so the two rounds diff
cell-for-cell; `results/d*` in this directory belong to other groups).

| script | what |
|---|---|
| `cvde.py` | harness — SimulatedClock, bounded RAISE inbox, plugin stub incl. `on_chain_budget_exceeded`, v3 snapshot audit on every roundtrip, `chain_trips` in every result |
| `d0_build.py` | #220 recursive `strictConfig` pass: as-carried, root typo, **nested `entyr`/`onn` typo**, nested `x-`/`meta` |
| `d1_b16_b17.py` | B16/B17 happy path + invariants |
| `d2_b18_b20.py` | B18/B19/B20 invariants + the three mandated drives |
| `d3_sharp.py` | C-07b, #207 stranding, #204 no-arm, sync parity |
| `d4_timers.py` | #212 / #213 / #128 / #214 / #205 timer + restore axis |
| `d5_r11.py` | **round-11 axis** — #218 heartbeat handles, #219 refusal + hatch + sync parity, #221 compaction, #222 latch, `chain_trips == 0` on all five happy paths |
| `repro/cvde_219_hatch_flaky.py` | **DE-L1**, standalone, both shapes as mutual controls |
