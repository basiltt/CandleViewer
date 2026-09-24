# B16–B20 control machines end-to-end on `19cb1f1`

Commit `19cb1f1` (unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed
on the commit). Round-9 fixes #203–#210 in scope.

Corrected JSON carried byte-identical from `battle-f28719c/contracts/`
(`B16`–`B20.machine.json`). Mandatory config already present in every file:
`actionErrorPolicy: rollback`, `guardErrorPolicy: raise`, `strictTargets: true`,
`strict: true`, `onUnhandled: defer` (B16/B17/B19/B20) and `error` (B18, the
control machine). Every run uses `SimulatedClock`, a bounded inbox
(`max_queue_size=64`, `OverflowPolicy.RAISE`) on the async engine, and a
`PluginBase` stub standing in for the project error hooks — now including
**`on_invocation_stranded`** (#207).

**Pass 1 = every service `async def`; pass 2 = every service plain `def`.**
Both passes were run for every driver. The service-kind axis is **flat**: no
check changes verdict between the two spellings.

## Headline

| | result |
|---|---|
| `create_machine` B16–B20 | **10/10 clean** (5 machines × 2 spellings), zero `InvalidConfigError` |
| B16/B17 invariants (`n1`) | 11/14 PASS per lane; **3 FAIL = C-04, both lanes** |
| B18/B19/B20 invariants + 3 mandated drives (`n2`) | 26/27 PASS per lane; **1 FAIL = C-06, both lanes** |
| Sharp edges (`n3`: C-07b, #207, #204, parity) | **13/13 PASS per lane** |
| Snapshot/restore at every quiescence | **clean on every drive**, zero drift, zero mid-step refusal |
| Sync parity (configuration + action trace + **service-call trace**) | **5/5** |
| LIBRARY findings | **0 new** |

**Every B16–B20 failure on this commit is OURS.** The library cleared all five
machines on both engines and both service spellings.

## The two catalogue Blockers: still present

Both were re-tested against the **corrected** `battle-f28719c` JSON — they were
**not** fixed by a later contracts pass. Both are defects on *any* runtime.

### C-04 — B16 elevation outlives the session · **STILL PRESENT** · OUR-CONTRACT · Blocker

`states.elevation.elevated.on` lists `ELEVATION_DEADLINE`, `STEP_UP_OK` and
`REVOKE` — and nothing else. The `auth` region is revoked by **four** distinct
events. Three of them never reach the parallel `elevation` region:

| kill event | final configuration | still elevated |
|---|---|---|
| `REVOKE` | `auth.revoked`, `elevation.normal` | no |
| `LOGOUT` | `auth.revoked`, **`elevation.elevated`** | **yes** |
| `IDLE_DEADLINE` | `auth.revoked`, **`elevation.elevated`** | **yes** |
| `ABSOLUTE_DEADLINE` | `auth.revoked`, **`elevation.elevated`** | **yes** |

A revoked session still carries the elevated-privilege tag that B17
`ENABLE_REQUESTED` and B18 `RELEASE` both gate on. Identical on both spellings
and on the sync engine.

Repro: `repro/cv19_c04_elevation_survives.py` → `REPRODUCED ... ['LOGOUT',
'IDLE_DEADLINE', 'ABSOLUTE_DEADLINE']`.

Two further B16 checks fail from the **same** root cause, and are the same
defect seen from a different angle, not separate ones:

- `INV-c every step-up audited` — the second `STEP_UP_OK` takes the
  `elevated → elevated, reenter: true` arm whose `actions` list omits
  `audit_step_up` (only `stamp_elevated_until`). A re-elevation is unaudited.
  **OUR-CONTRACT, Medium** (call it C-04b).
- `INV-d revoked terminal, no post-revoke elevation` — after `REVOKE` the
  machine is `auth.revoked` + `elevation.normal`, but a later `STEP_UP_OK` is
  still live in the `elevation` region and re-elevates a dead session. The
  post-revoke `MFA_OK`/`REQUEST` are correctly `deferred` (the `auth` region is
  final); the elevation region has no corresponding terminal state. Same fix.

**Fix (ours, one edit):** give `elevation` a `revoked`/`normal`-terminal arm
driven by every revocation event — or, better, hoist the four revocation events
onto the **root** so both regions see them, and add `audit_step_up` to the
re-enter arm.

### C-07b — B18 kill switch bricked by a guard-denied `RELEASE` · **STILL PRESENT** · OUR-CONTRACT · Blocker

`engaged.on.RELEASE` has exactly one arm, guarded by `owner_and_elevated`. When
the guard denies, **no transition is selected at all**, so the event is
*unhandled* — and B18 is the machine carrying `onUnhandled: "error"`. The
policy makes it fatal.

Observed, both spellings:

1. `ENGAGE` → … → `kill_switch.engaged` (trading blocked). Correct.
2. Operator presses `RELEASE` without elevation — an ordinary mistake.
   `send()` **returns normally, success-shaped, raising nothing**; the machine
   goes `status = "error"` with
   `UnhandledEventError("Event 'RELEASE' is not handled in any active state
   ['kill_switch.engaged'] and the machine's onUnhandled policy is 'error'.")`.
3. The operator elevates and presses `RELEASE` **correctly**. `send()` again
   returns normally; the library logs `⚠️ Interpreter 'kill_switch' is error;
   dropping event 'RELEASE'`. Final configuration: **`kill_switch.engaged`**.

The kill switch is stuck in the trading-blocked state and cannot be released
in-process. One wrong button press is unrecoverable.

Repro: `repro/cv19_c07b_killswitch_bricked.py` → `REPRODUCED ... ['async def',
'def']`.

Note the library behaves exactly as documented at each step — the **policy
choice is the defect**, and it is ours. The two library-side ergonomics
complaints that used to ride along with C-07b are now *closed*: the fatal kill
is logged loudly with a named exception on `i.error`, and the unhandled
disposition is reported to the hook as `("RELEASE", "errored")`. What remains
is that `send()` is still success-shaped for the sender — carried as a Low
library observation, not a new finding.

**Fix (ours):** drop `onUnhandled: "error"` on B18 (use `defer`, as B16/B17/B19/
B20 already do), **and** give `RELEASE` an unguarded fall-through arm that
audits the denial and stays in `engaged` — the B17 `ENABLE_REQUESTED` /
B20 `OVERRIDE_REQUESTED` shape, which both pass this exact test. Either change
alone closes it; do both.

## Third catalogue defect confirmed

### C-06 — B19 `stale_lockout` cannot be cleared by an operator · OUR-CONTRACT · High

`stale_lockout` (`tags: [account_locked, critical]`, entry locks the account and
pages) handles **`RECONNECTED` only**. `OPERATOR_RESOLVED` is `deferred` and the
account stays locked with `deferred_count = 1`. On a venue that never
reconnects cleanly the only exit is a process restart. Both lanes, both
engines. Fix is ours: add an `OPERATOR_RESOLVED` arm.

## The three mandated drives

All three were driven explicitly, on both spellings.

**(1) rollback + `invoke.onDone`.** Driven on B18 (`page_owner` raises,
`maxIterations: 5`) and B19 (`store_divergences` raises, `maxIterations: 25`).
Both trip, both lanes, and the plateau is **exact**:

| machine | limit | service calls at plateau | resting state | `last_error` |
|---|---|---|---|---|
| B18 | 5 | **7** = limit + 2 | `kill_switch.flattening` | `RunawayChainError` |
| B19 | 25 | **27** = limit + 2 | `reconciliation.diffing` | `RunawayChainError` |

Polled to convergence (not sampled at a fixed instant); the count is identical
at two successive plateaus, and identical cell-for-cell between `async def` and
`def`. **#207 is live and correct**: `on_invocation_stranded` fires with the
real pair — `("kill_switch.flattening", "fl", RunawayChainError(...))` and
`("reconciliation.diffing", "diff", …)` — `RunawayChainError.stranded` carries
the invoke ids, `has_dormant_invocations` is `True`, `pending_invocations()`
returns `PendingInvocation(state_id=…, invoke_id='fl',
src='flatten_all_positions')`, and an ERROR log names the state
(`🧷 Machine 'kill_switch' rests in state … whose invocation 'fl' was cut by
the chain budget and will never complete (#207)`). This is the round-7
CV-221-01 Blocker's successor surface and it is now fully observable: the "is
it stranded or just slow?" ambiguity that motivated the finding is gone.

**(2) `always` → invoked child.** Two directions, both correct.
*Positive:* B18 `engaging.always` (guard true) rolls into `cancelling`, whose
`cx` invoke **does** arm — `cancel_all_working_orders` then
`flatten_all_positions` are called and `kill_switch.engaging` is absent from
the final configuration. B19's `reporting.always → divergent` likewise fires
with its alert.
*Negative — the #204 `statesToInvoke` rule:* adding an unconditional
`always: [{target: "#kill_switch.engaged"}]` to `cancelling` means the state is
entered and exited inside one macrostep. **The service is never submitted**:
`svc_calls == []`, final state `kill_switch.engaged` — on the async engine and
on `SyncInterpreter`, for `async def` and for plain `def`. Four lanes, four
clean results. Also confirmed negatively from the guard side: with
`cancel_working_requested` false, `engaging` goes straight to `engaged` and no
service is called.

**(3) B18 `send_priority` under a self-generated chain.** With a runaway
`rollback + onDone` chain open (`maxIterations: 50`, `page_owner` raising), 12
`send_priority("RELEASE")` presses were issued against the live chain:
**12/12 accepted, 0 shed as `chain_budget`**, zero exceptions, both spellings.
The only drops recorded are `("RELEASE", "not_running")` **after** the
interpreter had already stopped — an entirely different and correct reason.
Round 8's Blocker R8-01 stays closed on the real kill switch.

## Snapshot / restore and sync parity

Every `drive()` call snapshots at `t0` and after **every** macrostep, restores
into a **fresh** machine built from the same JSON with a fresh stub, and
compares configuration + context + status + deferred count. Zero drift and
zero `SnapshotMidStepError` across all B16–B20 drives on both spellings.

Sync parity was tightened this round from configuration-only to
**configuration + full action trace + full service-call trace**, and is 5/5 on
all five machines.

One harness correction worth recording: a first parity pass showed B18/B19
diverging on the async lane. That was **our harness** handing `async def`
services to `SyncInterpreter`, not a library defect — the library refuses
loudly and correctly (`NotSupportedError: Service 'cancel_all' is async and not
supported.` plus an ERROR log), and the machine does **not** silently park.
Pinned as a negative result in `repro/cv19_sync_async_svc.py`
(`NOT REPRODUCED`). The parity drivers now build sync stubs with `def`
services, which is the only supported combination, and pass. This reinforces
**CV-C46** (the order path never runs on `SyncInterpreter`) from the other
direction: the sync engine is honest about what it cannot do.

## Findings

| id | class | sev | machine | status |
|---|---|---|---|---|
| C-04 | **OUR-CONTRACT** | Blocker | B16 | **still present** in the corrected JSON; reproduced standalone, both lanes |
| C-04b | OUR-CONTRACT | Medium | B16 | re-elevation via the `reenter` arm is unaudited; same root cause |
| C-04c | OUR-CONTRACT | Medium | B16 | `STEP_UP_OK` still live after revocation; same root cause |
| C-07b | **OUR-CONTRACT** | Blocker | B18 | **still present**; `onUnhandled:"error"` + single guarded `RELEASE` arm bricks the switch, both lanes |
| C-06 | OUR-CONTRACT | High | B19 | `stale_lockout` clearable only by `RECONNECTED` |
| — | LIBRARY | — | — | **none.** 0 new library findings on B16–B20 at `19cb1f1` |
| — | NEEDS-WRAPPER | Low | B18 | `send()` remains success-shaped after the machine has gone `status="error"`; the drop is logged and `i.error` is set, so a wrapper that reads `status`/`error` after each send closes it. Not a new finding — carried. |

## Verdict for these five

**B16, B17, B19, B20: LIBRARY-GO.** **B18: LIBRARY-GO.** All five build clean,
satisfy every library-side expectation on both engines and both service
spellings, snapshot and restore losslessly at every quiescence, and show exact
lap parity on the bounded-chain drives.

What blocks B16 and B18 is **ours** — C-04 and C-07b, unchanged from round 9,
present in the corrected contracts JSON, and fixable with edits to our own
catalogue that touch no library code. That is still the right problem to have.

## Artefacts

| file | what |
|---|---|
| `cv19.py` | harness (f28719c harness + `on_invocation_stranded` capture) |
| `n0_build.py` | `create_machine` B16–B20, both spellings |
| `n1_b16_b17.py` | B16/B17 happy path + invariants + rollback + sync parity |
| `n2_b18_b20.py` | B18/B19/B20 invariants + the three mandated drives |
| `n3_sharp.py` | C-07b, #207 stranded, #204 no-arm, full-trace parity |
| `results/n*.{async,def}.json` | every check, both spellings |
| `repro/cv19_c04_elevation_survives.py` | C-04, STANDALONE, REPRODUCED |
| `repro/cv19_c07b_killswitch_bricked.py` | C-07b, STANDALONE, REPRODUCED, both spellings |
| `repro/cv19_sync_async_svc.py` | sync + `async def` service, STANDALONE, NOT REPRODUCED (loud refusal) |

All three repro scripts are stdlib + `xstate_statemachine` only, inline
helpers, no harness import, and were run from the neutral cwd `C:/Users/basil`.
