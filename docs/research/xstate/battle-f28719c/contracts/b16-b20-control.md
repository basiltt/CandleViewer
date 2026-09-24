# B16–B20 contract machines end-to-end on `f28719c`

Date: 2026-09-22. Build under test: library `main` @ **`f28719c`** (unreleased
0.8.1; `__version__` still reports `0.8.0` — every claim here keys on the
commit). Round-8 fixes in scope: **#192–#201**, reopened **#181/#186**.

Scope: the five control-plane machines — **B16** AuthSession, **B17**
LiveEnablement, **B18** KillSwitch, **B19** Reconciliation, **B20** RiskLockout
— driven end-to-end under the mandatory configuration (`actionErrorPolicy:
rollback`, `onUnhandled: defer` on the order path / `error` on the control path,
`guardErrorPolicy: raise`, `strictTargets`, `strict`, bounded inbox with
`OverflowPolicy.RAISE`, `SimulatedClock`, trace-plugin stub standing in for
`CvErrorHooks`), **every service/action scenario run twice — pass 1 with every
service an `async def`, pass 2 with every service a plain `def`.**

Source of truth for the machines: the corrected catalogue JSON copied unchanged
from `battle-6db65d8/contracts/B1{6,7,8,9}.catalogue.json`, `B20.catalogue.json`.
Scripts and raw results live beside this file.

---

## 0. Headline

**CV-221-01 — the round-7 Blocker that made this group NO-GO — is fixed, and
fixed on both service lanes.** Nothing new of Blocker severity was found. The
only remaining blockers on this group are **ours**.

- **CV-221-01 is closed.** `rollback` + a service's `invoke.onDone` + a raising
  action at the target now plateaus at exactly **`maxIterations + 2`** service
  invocations and trips `RunawayChainError`, *identically for `async def` and
  plain `def` services*, on the minimal repro and on the real B18 and B19. The
  previous round's headline number — 3 547 `flatten_all_positions` calls in
  3.0 s, still accelerating — does not reproduce. The service-kind dimension,
  which was the discriminator last round, is now **flat**: `2→4, 5→7, 25→27,
  100→102` in every cell of an 8-cell ladder (§3).
- **All three mandated explicit drives pass, in both lanes** (§4): rollback +
  `invoke.onDone` (bounded, §3), `always` → invoked child (B18
  `engaging.always → cancelling`'s invoke; B19 `reporting.always → divergent`),
  and **B18 `send_priority` under a self-generated chain — 12/12 kill presses
  accepted, 0 shed as `chain_budget`, and the press pre-empts the chain**
  (§5).
- **The round-8 provenance work holds on the real machines** (§6). A hand-built
  `DoneEvent("done.invoke.cx", …)` sent at B18 while the genuine
  `cancel_all_working_orders` is still in flight is **refused** with a message
  naming it as an engine-generated name; the machine does not move, and the
  real completion still lands. A snapshot forged by contradicting
  `configuration`, or by emptying `state_ids`, is **refused**; the honest
  round-trip restores identically.
- **Snapshot/restore at every quiescence remains clean** for all five machines
  in both lanes: zero mid-step refusals, zero state/context drift.
- **What still blocks this group is ours.** C-04 (B16, Blocker), C-05 (B16,
  Low), C-06 (B19, High), C-07b (B18, Blocker) and C-07 all reproduce byte-for-
  byte, in both service lanes, unchanged by anything in round 8. They are
  contract defects and the library was never going to move them.

**Verdict by machine.**

| | Machine | Library verdict on `f28719c` | Blocked by |
|---|---|---|---|
| **B16** | AuthSession | **GO** | ours: C-04 (Blocker), C-05 |
| **B17** | LiveEnablement | **GO** | — (W-03 carried) |
| **B18** | KillSwitch | **GO — CV-221-01 closed** | ours: C-07b (Blocker) |
| **B19** | Reconciliation | **GO — CV-221-01 closed** | ours: C-06 (High) |
| **B20** | RiskLockout | **GO** | — |

**The library is no longer what stops B18 and B19.** Round 7's recommendation —
"do not ship B18 or B19 on `221ce7c`" — is withdrawn as to the library. Both
machines still need their own contract fix before they ship.

---

## 1. Step 0 — build, and the shape census

`m0_build.py` → `results/m0_build.json`. All five build on `f28719c` under the
full stub logic in **both** service styles **and** with a bare `MachineLogic()`;
no `InvalidConfigError`. Policy fields round-trip onto the `MachineNode` as
declared.

| | `id` | actions | guards | services | events | `invoke` | `always` | `onDone` |
|---|---|---|---|---|---|---|---|---|
| B16 | `session` (parallel) | 18 | 1 | 0 | 11 | **0** | **0** | **0** |
| B17 | `live_gate` | 10 | 3 | 0 | 5 | **0** | **0** | **0** |
| B18 | `kill_switch` | 9 | 5 | **2** | 3 | **2** | **1** | **2** |
| B19 | `reconciliation` | 20 | 3 | **3** | 7 | **3** | **1** | **3** |
| B20 | `risk_lockout` | 16 | 5 | 0 | 5 | **0** | **0** | **0** |

Identical to the previous two rounds. The census is still the whole exposure
story: the livelock classes are defined on `invoke` and `always`, and **only
B18 and B19 have either**. Both still carry both hazardous shapes
(B18 `flattening.onDone → engaged_incomplete` whose entry is
`["page_owner", "emit_incomplete_metric"]`; B19 `diffing.onDone → remediating`
with `store_divergences`, and `reporting`'s four-action entry behind an
`always`).

Carried, unchanged: **C-01** (missing implementations are still not a build
error) and **C-07** (the catalogue's promised `halted` states still do not
exist — `has_halted_state` is `false` for all five).

---

## 2. Invariant sweep — B16, B17, B20

`m3_b16_b17.py` and `m4_b18_b20.py` (the B20 half), each run twice
(`async`, then `def`). **Both lanes produced byte-identical verdicts**, so
every row below holds for both.

| Check | Result |
|---|---|
| **B16** happy `MFA_OK, REQUEST, STEP_UP_OK, REQUEST` → `{auth.active, elevation.elevated}`, snapshots clean | **PASS** |
| **B16** INV-b — reason recorded + `broadcast_revocation`, on all **6** revocation paths (`REVOKE`, `LOGOUT`, `IDLE_DEADLINE`, `ABSOLUTE_DEADLINE`, `MFA_TIMEOUT`, MFA-locked) | **PASS** |
| **B16** rollback on a raising `audit_login` leaves the session in `pending_mfa` | **PASS** |
| **B16** sync parity | **PASS** |
| **B16** INV-a — elevation must not outlive the session | **FAIL — C-04** |
| **B16** INV-c — every step-up audited | **FAIL — C-05** |
| **B16** INV-d — `revoked` terminal, no post-revocation elevation | **FAIL — C-04** |
| **B17** happy, INV-a…INV-e, sync parity (7 checks) | **PASS** (all) |
| **B20** happy, INV-a…INV-d, rollback, sync parity (8 checks) | **PASS** (all) |

The three B16 failures are exactly the carried contract defects and reproduce
with the same evidence as the prior two rounds:

- **C-04 (OUR-CONTRACT, Blocker).** Only `REVOKE` carries a
  `#session.elevation.normal` target. After `MFA_OK, STEP_UP_OK`, then
  `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE`, the configuration is
  `["auth.revoked", "elevation.elevated"]` — a revoked session that is still
  elevated. And on the INV-d sequence `MFA_OK, REVOKE, MFA_OK, REQUEST,
  STEP_UP_OK` the machine ends at `["auth.revoked", "elevation.elevated"]`:
  elevation is **acquirable after revocation**, because the `elevation` region
  is an independent parallel region that `auth.revoked` (a `final` in its own
  region only) does not constrain. This is a missing target in our JSON, not an
  engine defect — the `defer` disposition on the post-revocation `MFA_OK` /
  `REQUEST` shows the engine behaving exactly as declared.
- **C-05 (OUR-CONTRACT, Low).** `elevated`'s self-handler for `STEP_UP_OK` runs
  `["stamp_elevated_until"]` only — the `normal → elevated` edge is the sole one
  carrying `audit_step_up`. Two `STEP_UP_OK` events produce **one** audit
  record.

**B17 and B20 are clean on the library and clean on the contract.** B17's
`rollback` on a raising `audit_live_enabled` correctly leaves the gate at
`eligible` with **no** `broadcast_live_enabled` — the "no half-enabled live
trading" obligation. B20's `locked` entry ordering holds:
`halt_new_orders` precedes `broadcast_lockout` in the recorded action trace,
and a raise in `raise_lockout_alert` rolls the whole lockout back to `clear`
with no broadcast (the correct all-or-nothing, though see §7).

---

## 3. CV-221-01 is closed — the evidence

### 3.1 The plateau ladder

`m2_plateau.py` → `results/m2_plateau.json`. Each cell drives the hazard and
then **watches until the service counter stops moving** (unchanged for 0.6 s),
so the number reported is a genuine plateau, not a window sample. Machine-level
`maxIterations` is set in the config (it is a `MachineNode` field on this
build, not an `Interpreter` kwarg).

| `maxIterations` | min repro `async` | min repro `def` | **B18** `async` | **B18** `def` |
|---|---|---|---|---|
| **2** | **4** | **4** | **4** | **4** |
| **5** | **7** | **7** | **7** | **7** |
| **25** | **27** | **27** | **27** | **27** |
| **100** | **102** | **102** | **102** | **102** |

Every one of these 16 cells settled inside its watch window, ended with
`last_error = RunawayChainError`, and rested with `status="running"`. B19
agrees: `5 → 7`, `25 → 27`, both lanes, resting in `reconciliation.diffing`.

**`maxIterations + 2` exactly, in all four columns.** The service-kind
dimension — last round's discriminator, where `async def` had *no* guard at all
while `def` was bounded — is now completely flat. This is the round-8 `#179`
/`#200` work (all completions published through `_publish_completion` onto the
charged priority lane, the debt task-keyed) landing on the real machines.

### 3.2 The incident-day B18 case

`m1_hazard.py` → `results/m1_hazard.json`. B18 with
`cancel_working_requested=True, flatten_requested=True, all_accounts_flat=False`
— the operator asked for cancel **and** flatten and not every account went flat
— and `page_owner` (the pager call, the entry action of `engaged_incomplete`)
raising:

| cell | svc @1 s | svc @2 s | `last_error` |
|---|---|---|---|
| `async`, `maxIterations: 5` | **7** | **7** | `RunawayChainError` |
| `def`, `maxIterations: 5` | **7** | **7** | `RunawayChainError` |
| `async`, default 1000 | 22 | 44 | (still climbing toward 1002) |
| `def`, default 1000 | 190 | 217 | (still climbing toward 1002) |

The two default-budget rows are *not* a failure — §3.1 shows both settle at
1002; a 2 s window simply does not reach a 1000-lap budget. Last round the same
two rows read 1 260 → 2 548 and were still accelerating with **no** trip at any
budget.

Controls in the same script behave correctly and are the proof that the
machinery is intact, not merely quiet:

- `B18/control` (nothing raises): **2** service calls, rests in
  `kill_switch.engaged_incomplete`.
- `B18/rollback-pre-invoke` (`block_new_orders_immediately` raises, *before*
  any invoke is armed): **0** service calls, rolls back to `kill_switch.clear`.
- `B19/control`: **3** service calls, rests in `reconciliation.divergent`.

### 3.3 Necessity ablations still hold

Same minimal four-state repro as last round (`idle -GO→ a{invoke svc,
onDone/onError → c}`, `c.entry = [boom]`), async lane:

| ablation | svc @1 s | outcome |
|---|---|---|
| `actionErrorPolicy: "continue"` | **1** | rests in `m.c` — correct |
| `actionErrorPolicy: "fail"` | **1** | `stopped`, configuration cleared — correct |
| no raise in the entry action | **1** | rests in `m.c` — correct |

So the three ingredients are unchanged; what changed is that the combination is
now **bounded and reported** instead of unbounded and silent.

---

## 4. B18 and B19 invariants, both lanes

`m4_b18_b20.py async` and `m4_b18_b20.py def` →
`results/m4_b18_b20.{async,def}.json`. **27 checks per lane, 1 FAIL per lane,
and the FAIL is the same carried contract defect in both.**

| Check | Both lanes |
|---|---|
| **B18** happy `ENGAGE, RELEASE` → `clear`; services exactly `[cancel_all_working_orders, flatten_all_positions]`; snapshots clean | **PASS** |
| **B18** *(drive 2)* `engaging.always → cancelling` fires the invoked child; trace `ENGAGE→engaging`, `(always)→cancelling`, `done.invoke.cx→flattening`, `done.invoke.fl→engaged` | **PASS** |
| **B18** `always` guard false → straight to `engaged`, **0** service calls | **PASS** |
| **B18** INV-b — `block_new_orders_immediately` precedes `broadcast_kill_switch` | **PASS** |
| **B18** INV-c — incomplete flatten reaches the visible `critical` state and pages | **PASS** |
| **B18** INV-c2 — `RETRY_FLATTEN` re-invokes (2× `flatten_all_positions`) | **PASS** |
| **B18** INV-d — `RELEASE` without owner+elevation does not reach `clear` | **PASS** (but see C-07b below) |
| **B18** INV-e — service `onError` → `engaged_incomplete` + `raise_critical_alert` | **PASS** |
| **B18** *(drive 1)* rollback + `invoke.onDone` bounded: 7 calls at budget 5, unchanged across two further quiescence windows, `RunawayChainError` | **PASS** |
| **B18** *(drive 3)* priority lane — see §5 | **PASS** ×2 |
| **B19** happy `SWEEP_DUE` → `idle`; services `[fetch_exchange_state, diff_against_local]` | **PASS** |
| **B19** INV-a — auto-remediation path invokes `apply_remediations`, stores them, returns to `idle` | **PASS** |
| **B19** *(drive 2)* `reporting.always → divergent` + `raise_divergence_alert` | **PASS** |
| **B19** `onError → backing_off`, `RETRY_DUE → fetching` (2× fetch, `bump_failures`) | **PASS** |
| **B19** INV-b — failures exhausted → `stale_lockout`, account locked, owner paged | **PASS** |
| **B19** `CANCEL` during an in-flight fetch lands (C-02 remains closed) | **PASS** |
| **B19** *(drive 1)* rollback + `invoke.onDone` bounded: 27 calls at budget 25, stable, `RunawayChainError` | **PASS** |
| **B19** INV-b2 — an operator can clear `stale_lockout` | **FAIL — C-06** |

**C-06 (OUR-CONTRACT, High), carried and reproduced in both lanes.**
`stale_lockout` declares `on: {RECONNECTED: …}` and nothing else.
`OPERATOR_RESOLVED` sent there is **deferred** (`deferred_count == 1`) under
B19's `onUnhandled: "defer"` and the account stays locked for new orders until
the venue itself reconnects. There is no operator escape hatch from a
`critical`, account-locking state. Engine behaviour is exactly as declared;
the missing handler is ours.

**C-07b (OUR-CONTRACT, Blocker), carried.** The B18 INV-d row passes as an
invariant but the mechanism is the defect: `RELEASE` in `engaged` whose guard
denies leaves the event unhandled, and B18's control-path `onUnhandled:
"error"` raises `UnhandledEventError` and drives the machine into its error
state — recorded in this run as
`unhandled: [["RELEASE", "errored"]]`. Two ordinary operator mistakes (pressing
release without elevation) therefore kill the kill switch's own event loop.


---

## 5. Drive 3 -- `send_priority` under a self-generated chain

This is the drive that matters most for a kill switch: while the machine is
burning a runaway self-generated chain, does an operator kill press still get
in, and does it win?

### 5.1 In `m4_b18_b20.py`, on B18 unmodified

B18 with `page_owner` raising and `maxIterations: 50` -- a live runaway chain --
then 12 `send_priority("RELEASE", wait=False)` presses at 2 ms intervals while
`ENGAGE` is still in flight:

| | `async` lane | `def` lane |
|---|---|---|
| presses accepted by `send_priority` | **12 / 12** | **12 / 12** |
| dropped as `chain_budget` | **0** | **0** |
| dropped for any reason | 6 x `not_running` (after `stop()`) | same |

**Zero priority sends shed as `chain_budget`**, in both lanes. This is #192
landing: the shed site now cuts by provenance, so an *external* priority send is
never destroyed by a runaway it had nothing to do with. Under the round-7 build
this lane shed by FIFO position.

### 5.2 Pre-emption, isolated from C-07b -- `m5_sharp.py` check A

On unmodified B18 the presses are accepted but cannot *land*, because
`flattening` declares no `RELEASE` handler and C-07b then errors the machine --
our contract defect masking the library question. So check A runs B18 with
**one** added line (`flattening.on.RELEASE -> #kill_switch.clear`) and
everything else identical, `maxIterations: 200`:

```
svc calls at the moment of the press : 3
svc calls 0.3 s after the press      : 3
svc calls 0.6 s after the press      : 3
final configuration                  : ["kill_switch.clear"]
shed as chain_budget                 : []
```

`send_priority("RELEASE", wait=True)` **resolved**, the chain stopped dead at
the press (3 -> 3 -> 3, no further invocation), and the machine came to rest in
`clear`. **The kill press pre-empts the chain.** The library obligation is met;
what is required of us is that every state a runaway can park in declares the
release edge.

---

## 6. Round-8 provenance on the real machines

### 6.1 #195 -- a forged completion cannot drive a real `onDone`

`m5_sharp.py` check C. B18 is parked in `cancelling` with the genuine
`cancel_all_working_orders` **still in flight** (held on an `asyncio.Event`).
A hand-built `DoneEvent("done.invoke.cx", {"ok": True}, "cx")` is sent as user
traffic:

```
UnknownEventError: Event 'done.invoke.cx' is an engine-generated name and
cannot be sent as user traffic to machine 'kill_switch'. ...
```

Configuration before the forgery: `["kill_switch.cancelling"]`. After:
`["kill_switch.cancelling"]` -- **unmoved**. The service is then released and the
*genuine* completion still lands, carrying the machine on to
`["kill_switch.engaged_incomplete"]` with both real service calls recorded.
Under round 7 this forgery drove the real `onDone` and skipped `strict` and
`onUnhandled` entirely.

### 6.2 #198 -- forged snapshot payloads

`m5_sharp.py` check D, against a real B18 snapshot taken at quiescence
(`version: 2`, both `configuration` and `state_ids` present):

| payload | result |
|---|---|
| honest round-trip | restores `["kill_switch.engaged_incomplete"]` -- **identical** |
| `configuration` contradicted (list-shaped, so the agreement rule is what must catch it) | **refused** -- `SnapshotCorruptError: 'state_ids' names [...] which 'configuration' does not contain -- the two fields contradict...` |
| `state_ids` **emptied**, `configuration` relocating (the strictly simpler #186 mutation) | **refused** -- `SnapshotCorruptError: version >= 1 snapshot of a running machine has an empty 'state_ids' while 'configuration' names ['kill_switch.clear']` |
| **both fields forged to agree** on `["kill_switch.clear"]` | **accepted** -- restores to `clear` |

The last row is not a regression and not a new library finding -- it is the
documented scope of the rule, which is an *internal-agreement* check, not
authentication. It is worth stating plainly for our threat model: **a snapshot
blob is trusted input.** If an attacker can write the persistence store they can
relocate a kill switch from `engaged_incomplete` to `clear` by editing two
fields consistently. That is **NEEDS-WRAPPER (W-04)**: control-path snapshots
must be integrity-tagged (HMAC over the payload) by us before they are
persisted.

---

## 7. Sync parity

`m5_sharp.py` check B, both machines x both service kinds:

| | `async def` services | plain `def` services |
|---|---|---|
| **B18** on `SyncInterpreter` | **refused** -- `NotSupportedError: Service 'cancel_all_working_orders' is async and not supported.` | runs: `["kill_switch.engaged_incomplete"]`, services `[cancel_all_working_orders, flatten_all_positions]`, `error=None` |
| **B19** on `SyncInterpreter` | **refused** -- `NotSupportedError: Service 'fetch_exchange_state' is async...` | runs: `["reconciliation.idle"]`, services `[fetch_exchange_state, diff_against_local]`, `error=None` |

Carried and by design (CV-C32): the sync engine takes plain-`def` services only.
Within the supported lane, the **full invoke -> `onDone` -> `always` chain
executes inside a single synchronous `send`** and reaches the same resting
configuration the async engine reaches. B16, B17 and B20 have no services and
reach full sync parity on the happy path (`m3`, `m4`).

Round 8's #201 sentence is the one to quote back: on `rollback + onDone` the
sync engine does not re-arm a rolled-back invoke inside the same drain -- so the
runaway shape does not arise there at all, and "same lap count" is a statement
about the two async lanes.

---

## 8. Snapshot / restore discipline

Every scenario in `m3` and `m4` runs through `cvf28.drive`, which takes a
persisted snapshot at **every** quiescence point (including `t0`), restores it
into a **fresh** machine with fresh logic, resumes, and compares states and
context. Across both lanes and all five machines:

- **zero mid-step refusals**, **zero state drift**, **zero context drift**
  (`snapshot_ok: true`, `notes: []` on every happy-path row);
- #199's move of `on_interpreter_start` inside the in-flight window causes no
  observable change here, because we only ever snapshot at quiescence, which is
  CV-C23 and already mandatory for us.

---

## 9. Defect register delta for this group

| # | Class | Machine | Severity | Status on `f28719c` |
|---|---|---|---|---|
| **CV-221-01** | LIBRARY | B18, B19 | was **Blocker** | **CLOSED.** Plateaus at `maxIterations + 2` and trips `RunawayChainError` on both service lanes, on the minimal repro and on both real machines. 16/16 ladder cells. |
| **CV-221-02** | LIBRARY | -- | was Low | **CLOSED as restated.** The sync engine does not re-arm a rolled-back invoke at all; the two async lanes now agree exactly. #201 restates the promise rather than changing behaviour. |
| **CV-221-03** | NEEDS-WRAPPER | B18, B19 | was Medium | **WITHDRAWN.** It existed only as the break-glass mitigation for CV-221-01 (force plain-`def` services), which is no longer needed. B19's `backing_off` ladder can keep coroutine services. |
| **W-04** | **NEEDS-WRAPPER** | B16, B18, B19 | **Medium** | **NEW.** A control-path snapshot is trusted input: a payload forged so `configuration` and `state_ids` *agree* on a lie restores a kill switch from `engaged_incomplete` to `clear`. #198 is an internal-consistency rule, not authentication. Integrity-tag persisted control-plane snapshots. |
| C-01 | OUR-CONTRACT | all | Low | carried -- missing implementations are not a build error |
| C-04 | OUR-CONTRACT | B16 | **Blocker** | carried, reproduced both lanes -- elevation outlives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE`, and is acquirable after revocation |
| C-05 | OUR-CONTRACT | B16 | Low | carried -- `STEP_UP_OK` while already elevated writes no audit record |
| C-06 | OUR-CONTRACT | B19 | **High** | carried, reproduced both lanes -- `stale_lockout` only listens for `RECONNECTED`; `OPERATOR_RESOLVED` is deferred and the account stays locked |
| C-07 | OUR-CONTRACT | all | Low | carried -- the catalogue promises `halted` states that do not exist |
| C-07b | OUR-CONTRACT | B18 | **Blocker** | carried -- `onUnhandled: "error"` turns a guard-denied `RELEASE` into `UnhandledEventError` and a dead kill switch; also what masks the section-5 pre-emption result on the unmodified machine |
| W-02 / W-03 | NEEDS-WRAPPER | B16 / B17 | -- | carried, unchanged |

**New library defects this round: none.** One Blocker and one Low closed, one
wrapper obligation withdrawn, one new wrapper obligation opened (W-04, which is
a threat-model statement about our persistence layer, not a library defect).

---

## 10. What we recommend

1. **Accept the library for B16-B20 on `f28719c`.** The round-7 recommendation
   against shipping B18 and B19 is withdrawn as to the library. Re-pin the
   16-cell `m2_plateau.py` ladder as our regression gate for this class -- it is
   the smallest artefact that would catch a relapse on either service lane.
2. **Fix C-07b before B18 ships.** It is ours, it is a Blocker, and it is now
   the *only* thing between B18 and production. The minimum fix is a terminal
   catch-all `RELEASE` handler (audited denial, no target) on every blocked
   state -- which, per 5.2, is also what lets an operator priority kill press
   land while a chain is running. One change closes two problems.
3. **Fix C-06 (B19) and C-04 (B16).** Add `OPERATOR_RESOLVED` to
   `stale_lockout`; add `#session.elevation.normal` targets to `LOGOUT`,
   `IDLE_DEADLINE` and `ABSOLUTE_DEADLINE`, and constrain the `elevation`
   region against `auth.revoked`.
4. **Open W-04.** Integrity-tag persisted control-plane snapshots (HMAC) before
   any of these five machines is restored from durable storage in production.
5. **Keep the two-lane discipline permanently.** It is what exposed CV-221-01
   in round 7 and what proves the round-8 fix is real rather than lane-shaped.

---

## 11. Reproduction

Run from this directory with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python <script>`; every
script is self-bounded well inside 120 s and writes `results/<name>.json`.
All six are standalone -- stdlib plus `xstate_statemachine` only, except `m3`
and `m4`, which share the `cvf28.py` harness copied unchanged from the previous
round and sitting beside them.

| Script | Question it answers |
|---|---|
| `m0_build.py` | do all five build under the mandatory config, both service kinds? shape census |
| `m1_hazard.py` | the CV-221-01 shape on the real B18/B19 + the 4-state minimal repro + necessity ablations |
| `m2_plateau.py` | **the discriminator**: does the chain plateau at `maxIterations`, for `def` *and* `async def`? |
| `m3_b16_b17.py async` / `def` | B16 + B17 happy path, every invariant, snapshot at every quiescence, sync parity |
| `m4_b18_b20.py async` / `def` | B18 + B19 + B20 invariants and all three mandated explicit drives |
| `m5_sharp.py` | priority pre-emption isolated from C-07b; sync parity for both service kinds; #195 and #198 on the real machines |
