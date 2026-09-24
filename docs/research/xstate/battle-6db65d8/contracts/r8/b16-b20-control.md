# B16–B20 contract machines end-to-end on `6db65d8`

Date: 2026-09-21. Build under test: library `main` @ **`6db65d8`** (merge of
`fix/0.8.1-round7`, #191; unreleased 0.8.1 — `__version__` still reports
`0.8.0`, so every claim here keys on the commit). Round-7 fixes in scope:
**#179–#190** plus reopened **#167 / #168 / #175**, and **#157** (reopened).

Scope: the five control-plane machines — **B16** AuthSession, **B17**
LiveEnablement, **B18** KillSwitch, **B19** Reconciliation, **B20** RiskLockout
— driven end-to-end under the mandatory configuration (`actionErrorPolicy:
rollback`, `onUnhandled: defer` on the order path / `error` on the control
path, `guardErrorPolicy: raise`, `strictTargets`, `strict`, bounded inbox with
`OverflowPolicy.RAISE`, `SimulatedClock`, trace-plugin stub standing in for
`CvErrorHooks`).

Machines: the corrected catalogue JSON, copied unchanged from
`battle-3ed3099/contracts/B1{6,7,8,9}.catalogue.json` + `B20.catalogue.json`.

**Method change that matters this round.** The round-6/7 harness
(`charness.py`) stubbed *every* service as `async def` only. Because #179
established that service *definition kind* was the axis that decided whether a
livelock guard existed at all, the harness here (`r8/h.py`) takes `kind` as a
first-class parameter and **every cell below is run twice — once with all
services `async def`, once with all services plain `def`** — with the two
runs' state, context, action trace and lap counts compared cell by cell. The
async lane is primary; the sync lane is the control.

Scripts: `r8/{h,d}.py` (harness + driver), `r8/s0…s7_*.py`. Raw results:
`r8/results/*.json`. Every number below is read back out of those files.

---

## 0. Headline

**CV-221-01 — the round-7 Blocker carried into this group — is fixed, and it
is fixed on both service kinds at the same lap count. No new LIBRARY defect
was found in this group at `6db65d8`. All five machines are LIBRARY-GO.**

- **The livelock is bounded and observable.** B18 `ENGAGE` with the
  incident-day configuration (`cancel` + `flatten` requested, not all accounts
  flat) and `page_owner` raising — the exact cell that produced 3 547
  `flatten_all_positions` calls in 3.0 s at `221ce7c` and was still
  accelerating — now **plateaus at 1 002 service calls and stops**, with
  `last_error = RunawayChainError`. The trail is flat from t=0.5 s to t=4.1 s
  on both lanes (`results/s2_plateau.json`).
- **`maxIterations` is live again, and lane-independent.** `maxIterations` of
  2 / 5 / 100 give **4 / 7 / 102** service calls — `max+2` exactly — and the
  `async def` and plain `def` numbers are **identical, cell for cell**
  (`results/s1_livelock.json`). At `221ce7c` the same table was flat noise
  (193/183/181) with `last_error = RuntimeError`. The service-kind asymmetry
  that was the whole of CV-221-01 is gone.
- **External priority sends are never charged (#180).** 50 concurrent external
  `send(priority=True)` into B18 while a macrostep was open: **0 dropped, 0
  `chain_budget` refusals**, on both lanes (`results/s5_prio.json`).
- **Snapshot/restore at quiescence between every macrostep is clean** across
  all five machines and both lanes: **zero mid-step refusals, zero state /
  context / status diffs against the unsnapshotted run, identical transition
  traces** in all 20 snapshot cells (`results/s3_inv.json`).
- **Both hazardous shapes terminate, bounded, observable, same lap count on
  both lanes** when driven explicitly (§4).
- **Every carried OUR-CONTRACT defect reproduces unchanged** — C-04, C-05,
  C-06, C-07b, W-03. They are ours, not the library's, and none of them moved.

**Verdict by machine.**

| | Machine | Library verdict on `6db65d8` | Contract verdict |
|---|---|---|---|
| **B16** | AuthSession | **GO** | blocked by **C-04** (Blocker, ours) + C-05 (Low) |
| **B17** | LiveEnablement | **GO** | GO with **W-03** wrapper |
| **B18** | KillSwitch | **GO** — CV-221-01 closed | blocked by **C-07b** (Blocker, ours) |
| **B19** | Reconciliation | **GO** — CV-221-01 closed | blocked by **C-06** (High, ours) |
| **B20** | RiskLockout | **GO** | GO |

The remaining blockers in this group are **all OUR-CONTRACT**. That is a
different posture from every prior round, where a library defect sat on the
kill-switch path.

---

## 1. Step 0 — build, and the shape census

All five machines build at `6db65d8` with the full stub logic in **both**
service kinds, and with a bare `MachineLogic()`; no `InvalidConfigError`, so
no our-contract build defect. Policy fields round-trip onto the `MachineNode`
as declared (`results/s0.json`).

| | `id` | actions | guards | services | events | `invoke` | `always` |
|---|---|---|---|---|---|---|---|
| B16 | `session` | 18 | 1 | 0 | 11 | 0 | 0 |
| B17 | `live_gate` | 10 | 3 | 0 | 5 | 0 | 0 |
| B18 | `kill_switch` | 9 | 5 | **2** | 3 | **2** | **1** |
| B19 | `reconciliation` | 20 | 3 | **3** | 7 | **3** | **1** |
| B20 | `risk_lockout` | 16 | 5 | 0 | 5 | 0 | 0 |

`build_async`, `build_sync` and `build_bare` are `OK` for all five. Two carried
OUR-CONTRACT observations stand: missing implementations are still not a build
error (**C-01**), and the catalogue's promised `halted` states still do not
exist in the JSON (**C-07**).

B16, B17 and B20 carry no `invoke` and no `always`, so the whole
budget/completion-lane story of round 7 reaches **B18 and B19 only**. For those
two the service-kind axis is load-bearing; for the other three it is a control,
and it came back clean (identical results both kinds, as expected).

---

## 2. CV-221-01 is closed

### 2.1 The contract cell that was unbounded

`s1_livelock.py` / `s2_plateau.py`. B18, `guard_vals = {cancel_working_requested:
True, flatten_requested: True, all_accounts_flat: False}` — operator asked for
cancel **and** flatten, not every account went flat. `page_owner`, the entry
action of `engaged_incomplete`, raises: a pager call, the most plausible thing
in the machine to fail. One `send("ENGAGE", wait=True)`.

Service-call trail after the send, sampled every 0.5 s to t=4.1 s
(`results/s2_plateau.json`):

| lane | 0.5 s | 1.0 s | 1.5 s | 2.0 s | 3.0 s | 4.1 s |
|---|---|---|---|---|---|---|
| `async def` | **1 002** | 1 002 | 1 002 | 1 002 | 1 002 | **1 002** |
| plain `def` | 906 | **1 002** | 1 002 | 1 002 | 1 002 | **1 002** |

Flat. At `221ce7c` the same cell read `(0.50, 541) (1.00, 1136) (1.50, 1731)
(2.00, 2330) (2.50, 2940) (3.00, 3547)` — dead linear at ~1 190/s with no
plateau. The count is now a function of the **budget**, not of how long you
watch; both lanes converge on the identical 1 002 (= default `maxIterations`
1000 + 2).

### 2.2 `maxIterations` bounds it, identically on both lanes

`s1_livelock.py`, `declared_max_iterations` asserted on the `MachineNode` in
each cell (`results/s1_livelock.json`, 1.0 s observation window):

| `maxIterations` | `async def` svc calls | plain `def` svc calls | `last_error` |
|---|---|---|---|
| **2** | **4** | **4** | `RunawayChainError` |
| **5** | **7** | **7** | `RunawayChainError` |
| **100** | **102** | **102** | `RunawayChainError` |
| unset (1000) | 1 002 | 1 002 | `RunawayChainError` |

`max + 2` in every cell, and **zero divergence between the two service kinds** —
the core #179 claim, confirmed on a real contract machine rather than a unit
fixture. At `221ce7c` this table was 193 / 183 / 181 / 134 with no trend and
`last_error = RuntimeError`.

B19 reproduces the fix on both of its hazardous shapes. At default budget,
1.0 s window: `store_divergences` raising on `diffing.onDone` → 806 (async) /
618 (sync) calls *still climbing inside the window*, converging on the same
1 002 plateau; `persist_report` raising on `reporting`'s entry (the `always`-side
variant) → 645 / 374. With an explicit budget these become exact and equal, as
in the B18 table. Controls terminate correctly and cheaply on both lanes:
`b18_control` 2 service calls → `kill_switch.engaged`; `b19_control` 2 →
`reconciliation.idle`.

### 2.3 It is now observable, and the machine stops doing work

The round-7 note's own acceptance criterion was that a supervisor can tell
"one action raised once" from "this machine is calling `flatten_all_positions`
1 200 times a second". At `6db65d8`, after the trip (`results/s2_plateau.json`):

| signal | `221ce7c` | `6db65d8` |
|---|---|---|
| `last_error` | `RuntimeError` (indistinguishable) | **`RunawayChainError`** |
| service calls after the plateau | unbounded, ~1 190/s | **0** |
| `svc_after_external` (one more external send) | +633 in 0.5 s | **0** |
| `get_persisted_snapshot()` | — | `ok`, `status: "error"` |

The trip is a poll-able, distinct error class, the chain is genuinely dead, and
the machine can still be snapshotted for post-mortem. This is the signal a
wrapper needs.

One consequence worth stating plainly for the control path: after the trip the
next operator event is refused with `UnhandledEventError` and the interpreter
goes to `status="error"` while the configuration stays pinned at
`kill_switch.flattening`. That is `onUnhandled: "error"` behaving as this group
mandates it — it is **C-07b**, our contract's choice, not a library defect.

---

## 3. Invariants, both service kinds (`s3_inv.py`)

36 cells × 2 service kinds. **`kind_parity` is empty and `acts_eq` is `True`
in every single cell** — identical resting configuration, context, status and
action trace between the `async def` and plain `def` lanes. That is the
strongest statement this group can make about #179: on five real machines,
service definition kind is now semantically inert.

| Machine | Invariant | Result |
|---|---|---|
| B16 | INV-b — revocation reason + broadcast on all six paths | **PASS** |
| B16 | INV-a / INV-d — elevation must not outlive the session | **FAIL — C-04** |
| B16 | INV-c — every step-up audited | **PARTIAL — C-05** |
| B17 | INV-a…INV-e, `rollback` on `audit_live_enabled` | **PASS** |
| B17 | stale-authorisation replay | **W-03** |
| B18 | INV-b/c/e — block precedes outward effects, incomplete paging, retry | **PASS** |
| B18 | INV-d — release requires owner + elevation | **FAIL — C-07b** |
| B19 | INV-a, C-02 deferral of the trigger | **PASS** |
| B19 | INV-b — operator resolution clears lockout | **FAIL — C-06** |
| B20 | all invariants incl. rollback | **PASS** |

Nothing in #179–#190 moved any of these, which is expected: they are contract
defects on unrelated paths. The point is that **no round-7 fix regressed any
of them either**.

Carried defects, reconfirmed from the raw receipts:

- **C-04 (Blocker, OUR-CONTRACT).** `b16_inv_a_*`: `REVOKE` lands in
  `['session.auth.revoked', 'session.elevation.normal']` — correct — but
  `LOGOUT`, `IDLE_DEADLINE` and `ABSOLUTE_DEADLINE` all land in
  `['session.auth.revoked', 'session.elevation.elevated']`. Three of the four
  session-ending events leave the elevation region standing. `b16_inv_d` shows
  the other half: after `REVOKE`, the re-auth events are `deferred` (correct
  under `onUnhandled: defer`) but a later `STEP_UP_OK` still elevates
  (`changed=True`) inside a revoked session.
- **C-05 (Low).** `b16_inv_c`: the second `STEP_UP_OK` while already elevated
  returns `changed=False` and writes no audit record.
- **C-06 (High).** `b19_stale_RECONNECTED / _OPERATOR_RESOLVED / _SWEEP_DUE`:
  all three land `deferred=True`, `deferred_count=1`, resting in
  `reconciliation.backing_off`. Operator resolution does not clear the lockout;
  it queues behind it.
- **C-07b (Blocker).** `b18_release_denied`: the guard-denied `RELEASE` comes
  back `denied=True` **and** `error=UnhandledEventError`, and the interpreter
  goes `status="error"`. Two ordinary operator mistakes — asking to release
  without elevation, or retrying in the wrong state — leave a dead kill switch.
  Note this is now *correctly reported*: #189's fix means the kill lands on the
  **sender's** receipt rather than a success-shaped one, so the operator who
  did it gets told. The remedy remains ours: drop `onUnhandled: "error"` on
  B18, or gate the control path behind a wrapper that pre-validates.
- **W-03 (needs-wrapper).** `b17_stale_replay`: `ENABLE_REQUESTED` sent in
  `locked` is deferred (`deferred=True`), then replays the instant
  `EVIDENCE_RECORDED` lands, taking the machine to `live_gate.enabled` — with
  an authorisation decision made against evidence that did not yet exist. The
  library is doing what `defer` says; the wrapper must stamp and re-validate
  authorisation freshness at replay.

**B20 rollback** (`b20_rollback`): `broadcast_lockout` raising on
`MANUAL_LOCK` gives `changed=False, error=RuntimeError`, resting in
`risk_lockout.clear`, `last_error=RuntimeError`, `status="running"` — a clean
bounded rollback with no chain, both lanes.

---

## 4. The two hazardous shapes, driven explicitly (`s4_prio_shapes.py`)

Both shapes were driven on B18 with `maxIterations = 8`, on both lanes:

| Shape | lane | svc laps | actions | resting state | `last_error` | terminated |
|---|---|---|---|---|---|---|
| `rollback` + `invoke.onDone` → raising entry | `async def` | **10** | 13 | `kill_switch.flattening` | `RunawayChainError` | yes |
| `rollback` + `invoke.onDone` → raising entry | plain `def` | **10** | 13 | `kill_switch.flattening` | `RunawayChainError` | yes |
| `always` → invoked sibling (`engaged_incomplete.always → flattening`) | `async def` | **5** | 13 | `kill_switch.engaged_incomplete` | `RunawayChainError` | yes |
| `always` → invoked sibling | plain `def` | **5** | 13 | `kill_switch.engaged_incomplete` | `RunawayChainError` | yes |

All four cells: **terminated** (no watchdog timeout), **bounded** (lap count a
function of the declared budget), **observable** (`RunawayChainError`), and
**same lap count on both lanes** — 10 vs 10, 5 vs 5, with identical action
counts. That is the full acceptance condition for this task's "must terminate,
bounded, observable, same lap count both engines" clause, met on the kill
switch itself.

---

## 5. External priority sends (#180) — `s5_prio.py`

B18 driven to `engaged_incomplete`, where `RETRY_FLATTEN` **is** declared, then
50 concurrent external sends fired while the step is open:

| lane | `priority=True` | `priority=False` |
|---|---|---|
| `async def` | 50 accepted, **0 dropped**, 0 `chain_budget` | 50 accepted, 0 dropped |
| plain `def` | 50 accepted, **0 dropped**, 0 `chain_budget` | 50 accepted, 0 dropped |

`on_event_dropped` never fired, and `dropped_reasons` is empty in all four
cells. The ~50 % `chain_budget` loss rate that #180 describes does not
reproduce at `6db65d8`: external provenance is respected regardless of when the
send lands. For the kill switch specifically — the machine that actually uses
the priority lane in production — **zero operator commands were lost**.

(The `async` lanes end in `status="error"` at the tail of the burst because the
re-armed `flattening` invoke moves the machine out from under later
`RETRY_FLATTEN`s, which are then undeclared in `flattening` — C-07b again, not
a dropped-event defect. The `n_dropped=0` measurement is taken over the whole
burst and is unaffected.)

---

## 6. Snapshot / restore at quiescence between every macrostep (`s3_inv.py`)

Ten sequences (B16 ×2, B17 ×2, B18 ×2, B19 ×2, B20 ×2) × two service kinds =
**20 snapshot cells**. Each takes a full persisted snapshot at quiescence
before *every* macrostep, stops the interpreter, restores with
`restart_services=True, restart_timers=True`, restarts, and then applies the
step — carrying the same stub across restores so the action trace accumulates
exactly as in the unsnapshotted run.

| measure | result across all 20 cells |
|---|---|
| mid-step snapshot refusals | **0** |
| exceptions raised during the snapshotted run | **0** |
| `ids` / `ctx` / `status` diffs vs the plain run | **0** |
| transition-trace equality | **True, 20/20** |

Zero diffs on every axis, on both service kinds. The round-7 persistence work
(#182–#186) did not disturb quiescent snapshotting on any of these machines.

### 6.1 Persistence edges (`s6_persist.py`, `s7_edges.py`)

Blob shape at `6db65d8` is `version: 2` with `machine_hash`, `configuration`
and `state_ids` all present.

| Edge | Result (identical on both lanes) | Fix |
|---|---|---|
| snapshot from inside an entry action | **`SnapshotMidStepError`**, `child=False` | #187 |
| snapshot from an action on `start()`'s initial descent | **`SnapshotMidStepError`**, `child=False` | **#182 — confirmed** |
| `machine_hash: null` on a `version: 2` blob | **`SnapshotDriftError`** | **#185 — confirmed** |
| `machine_hash` absent on a `version: 2` blob | **`SnapshotDriftError`** | #185 |
| `machine_hash` wrong | `SnapshotDriftError` | — |
| `configuration: []` with a populated `state_ids` | **`SnapshotCorruptError`** | **#186 — confirmed** |
| `configuration` rewritten to disagree with `state_ids` | **`SnapshotCorruptError`** | #186 |
| `state_ids` absent | `SnapshotCorruptError` (missing required key) | — |
| `state_ids` rewritten to disagree | `SnapshotCorruptError` | #186 |
| `state_ids: []` with a populated `configuration` | **ACCEPTED** | see below |

Nine of ten edges refuse. The tenth — an **emptied** (not absent, not
rewritten) `state_ids` alongside a valid `configuration` — is accepted. We
chased it (`s7_edges.py`): the snapshot was taken in the non-initial state
`kill_switch.engaged_incomplete`, and the restore with `state_ids: []`
**recovers the correct configuration** (`restored_ids ==
['kill_switch.engaged_incomplete']`, `matches_original: True`, `status:
running`) on both lanes. `configuration` is the authority and the empty list is
treated as "nothing asserted", so no drift is possible through this door. It is
an asymmetry with the emptied-`configuration` case rather than a defect — we
file it as an **observation, not a finding**: no incorrect state is reachable
through it. A wrapper that wants strict symmetry can assert
`blob["state_ids"]` non-empty before restoring.

---

## 7. Sync-engine parity

`SyncInterpreter` was run alongside for all five machines (`s3_inv.py`,
`sync_engine`). B16/B17/B20 (no services) and B18/B19 (plain `def` services)
reach the same resting configurations and the same action traces as the async
engine on the corresponding sequences. The `maxIterations` trip tables in §2.2
are the sharper parity statement: the async engine now trips at exactly the lap
count the sync engine has always tripped at.

---

## 8. Findings

**LIBRARY: none new at `6db65d8` in this group.**

| ID | Class | Sev | Status at `6db65d8` |
|---|---|---|---|
| **CV-221-01** | LIBRARY | Blocker | **FIXED** — bounded at `max+2`, both lanes equal, `RunawayChainError`, zero work after the trip (§2) |
| C-01 | OUR-CONTRACT | Low | open — missing impls are not a build error |
| C-04 | OUR-CONTRACT | **Blocker** | open — elevation outlives the session on 3 of 4 end events; elevation obtainable after revocation |
| C-05 | OUR-CONTRACT | Low | open — re-elevation writes no audit |
| C-06 | OUR-CONTRACT | High | open — `stale_lockout` ignores `OPERATOR_RESOLVED` |
| C-07 | OUR-CONTRACT | Low | open — promised `halted` states absent from the JSON |
| C-07b | OUR-CONTRACT | **Blocker** | open — `onUnhandled: "error"` kills B18 on ordinary operator mistakes |
| W-03 | NEEDS-WRAPPER | High | open — deferred authorisation replays against evidence that post-dates it |
| — | observation | — | emptied `state_ids` accepted on restore; restores correctly, no drift reachable (§6.1) |

### What has to happen before B16–B20 go live

All of it is ours:

1. **C-04** — add the elevation-region exit to `LOGOUT` / `IDLE_DEADLINE` /
   `ABSOLUTE_DEADLINE`, and make `revoked` refuse elevation outright.
2. **C-07b** — drop `onUnhandled: "error"` from B18, or put a pre-validating
   wrapper in front of the kill switch's control path. A dead kill switch after
   a mistyped release is worse than any event we would lose to `defer`.
3. **C-06** — declare `OPERATOR_RESOLVED` (and a `SWEEP_DUE` escape) in
   `stale_lockout`.
4. **W-03** — stamp authorisation freshness and re-validate on deferred replay.
5. **Set `maxIterations` explicitly** on B18 and B19 rather than inheriting
   1000. The fix makes the budget real again, which makes the number a genuine
   operational choice: 1 002 `flatten_all_positions` calls is still 1 002 calls.
   §2.2 shows the budget maps 1:1 (`max+2`), so a small number — 5 or 10 — buys
   a fast, loud trip. Pair it with a supervisor that alarms on
   `last_error is RunawayChainError`.

### Library posture for this group

**GO.** The one library Blocker that stood against B16–B20 is closed, closed on
both service kinds, and closed with an observable, distinct error class. The
five control-plane machines are now gated only by our own contract work.
