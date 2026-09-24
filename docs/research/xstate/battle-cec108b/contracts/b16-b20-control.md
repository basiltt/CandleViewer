# Contract machines end-to-end — B16–B20 on `main` @ `cec108b`

**Library** `xstate-statemachine` @ `cec108b` (merge of #164, `fix/0.8.1-round5`;
unreleased 0.8.1, `__version__` still reports `0.8.0` — keyed on commit).
**Engine** async `Interpreter` primary, `SimulatedClock`, bounded inbox
(`max_queue_size=64`, `OverflowPolicy.RAISE`). `SyncInterpreter` for parity
information only.
**Machines** B16 `session`, B17 `live_gate`, B18 `kill_switch`,
B19 `reconciliation`, B20 `risk_lockout` — JSON **re-extracted from
`docs/plan/28-statechart-catalogue.md` §B16.1–§B20.1 on this run**
(`extract.py`), because the round-5 catalogue corrections (CV-C31/CV-C34)
changed those blocks: `actionErrorPolicy: "fail"` is withdrawn everywhere and
all `"*": {"actions": ["defer"]}` scaffolding is gone. The
`battle-3ed3099/contracts/B1[6-9].catalogue.json` copies are **stale** —
they still carry `"fail"` on B17 — and were not used.
**Scripts** `contracts/extract.py`, `k0_build.py`, `k1_b16_b17.py`,
`k2_b18.py`, `k3_b19_b20.py`, `k4_redo.py`, `k5_edges.py`, `k6_failsnap.py`;
helpers `charness.py` + `cdrv.py` (copied unchanged from `battle-3ed3099`).
Raw JSON under `contracts/results/`.
**Method** every finding was reproduced from a standalone script before being
counted. Nothing is inferred from reading library source.

---

## 0. Headline

| | |
|---|---|
| Machines that build from the corrected catalogue JSON unchanged | **5 / 5** |
| `InvalidConfigError` at build (full stub **and** bare `MachineLogic()`) | **0** |
| Invariant scenarios driven | 46 |
| `SnapshotMidStepError` across 9 snapshot-every-macrostep runs (~30 cycles) | **0** |
| Snapshot-every-macrostep traces equal to the uninterrupted run | **9 / 9** |
| LIBRARY defects | **0 new**; 2 round-5 fixes confirmed closed on these machines |
| OUR-CONTRACT defects | 4 (C-04, C-05, C-06 carried forward; C-07 new) |
| Needs-wrapper items | 3 (W-01, W-02, W-04) |

**The round-5 fixes land on the control machines.** Three of the four blockers
from the `3ed3099` run are gone:

* **C-02 is closed at the source.** The `"*"` defer scaffolding is no longer in
  the catalogue, and `onUnhandled: "defer"` now does the job it was supposed to
  do. `UNKNOWN_ORDER` arriving mid-sweep on B19 is **held** (`deferred=True`,
  `deferred_count=1`, `on_unhandled_event(disposition="deferred")`), and replays
  as its own macrostep when the sweep finishes, triggering a second sweep with
  `set_trigger_unknown`. A reconciliation trigger is no longer eaten.
  (`k4_redo.py::b19_unknown_during_sweep`.)
* **L-01 is fixed (#145) and C-03 is moot.** With `"fail"` forced back on for
  the record, a raise in `audit_live_enabled` now gives `status="stopped"`,
  `configuration` cleared, `.error = TransitionFailedError`, and the persisted
  snapshot records `status: "stopped"` with an empty configuration —
  `from_snapshot` then refuses it (`InvalidConfigError`, "has been stopped and
  cannot be restarted"). No bricked-but-resumable machine.
  (`k5_edges.py::fail_policy_b17`, `k6_failsnap.py`.) The catalogue's own
  withdrawal of `"fail"` in favour of `rollback` also works: B20's
  `broadcast_lockout` raise rolls the whole `locked` entry list back to `clear`
  with `status="running"` and a `RuntimeError` on the receipt
  (`k3::b20_rollback`).
* **`Receipt.denied` (#153) lands.** A guard-denied `RELEASE` on B18 returns
  `changed=False, denied=True` — the L-02 blind spot for the `wait=True`
  caller is closed for the *denial* case.

**What still bites (all OUR-CONTRACT).** B18's `onUnhandled: "error"` is still
a foot-gun — see **C-07**, now sharper than the old C-03b. B16's C-04/C-05 and
B19's C-06 are unchanged, because the catalogue corrections did not touch them
(they are ticketed under E50-T14 and their fixes have not been merged into
§B16/§B19).

---

## 1. Step 0 — build from the corrected catalogue

`k0_build.py`, `results/k0_build.json`.

| Machine | id | root | build (full stub) | build (bare `MachineLogic()`) | actions / guards / services | policy |
|---|---|---|---|---|---|---|
| B16 | `session` | `parallel` | OK | **OK** | 18 / 1 / 0 | rollback · defer · raise |
| B17 | `live_gate` | compound | OK | **OK** | 10 / 3 / 0 | rollback · defer · raise |
| B18 | `kill_switch` | compound | OK | **OK** | 9 / 5 / 2 | rollback · **error** · raise |
| B19 | `reconciliation` | compound | OK | **OK** | 20 / 3 / 3 | rollback · defer · raise |
| B20 | `risk_lockout` | compound | OK | **OK** | 16 / 5 / 0 | rollback · defer · raise |

`strictTargets: true`, `strict: true` and `spawnBlockingTimeout: 5000` are read
and honoured on all five. `strict` rejects an undeclared event **at the call
site**: `interp.send("NOT_A_REAL_EVENT")` on B16 raises `UnknownEventError`
listing the known vocabulary (`k5_edges.py::b16_strict`).

### C-01 (carried forward, unchanged) — missing implementations are not a build error

`create_machine(cfg, logic=MachineLogic())` — no actions, no guards, no
services at all — succeeds on all five machines. The catalogue's assumption
that the factory is a conformance gate is still wrong; an unimplemented guard
surfaces at first use, not at load. **W-01** remains required.

### C-07 (new, replaces C-03b) — the catalogue promises `halted` states that do not exist

The §1.3b correction note and the inline comments on B17/B18/B20 say
`"fail"` is withdrawn "in favour of `rollback` + explicit `halted` states".
**No `halted` state exists in any of the five contracts** — `k0_build.py`
records `halted: False` for all of them and the full state lists contain no
such node. `rollback` alone leaves the machine in the *source* state with a
`RuntimeError` on the receipt and nothing that routes the fault anywhere: on
B20, a raise in `broadcast_lockout` puts the machine back on
`risk_lockout.clear` — tag `trading_allowed` — with no record that a lockout
was attempted and no `halted` sink to page from. The rollback is *correct*
(the library does exactly what `rollback` says); the contract is incomplete.
**OUR-CONTRACT, High.** Either add the `halted` states the note promises, or
have the wrapper (W-01) route `on_transition_failed` to an out-of-band halt.

---

## 2. B16 — AuthSession / step-up

`k1_b16_b17.py`, `k5_edges.py`. Root is `parallel` (`auth` ‖ `elevation`).

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path `MFA_OK → REQUEST → STEP_UP_OK → REQUEST` | **PASS** | ends `auth.active` ‖ `elevation.elevated`; `REQUEST` re-enters `active` and re-stamps the idle deadline (`changed=False`, self-target internal re-entry) |
| **INV-B16-a** elevation cannot outlive the session | **FAIL** | see C-04 |
| **INV-B16-b** every revocation records a specific reason + broadcast | **PASS** | all six paths produce `set_revoke_{admin,logout,idle,expired,timeout,locked}` then `audit_session_revoked`, `broadcast_revocation` |
| **INV-B16-c** every step-up attempt audited | **PARTIAL FAIL** | see C-05 |
| **INV-B16-d** `revoked` is terminal; never un-revoked | **PASS (auth region)** / **FAIL (as a session)** | see C-04 |
| **INV-B16-e** deadlines are absolute timestamps evaluated on access | **not exercised** | the contract carries `*_us` context fields but no `after`; nothing for the runtime to get wrong |
| Snapshot/restore at quiescence between every macrostep | **PASS 3/3** | `happy`, `revoke`, `term`: zero `SnapshotMidStepError`, zero `ids`/`ctx`/`status` diffs, transition traces identical |
| Sync parity | **PASS** | `SyncInterpreter` reaches the same configuration and action trace for the happy path and for `MFA_OK → STEP_UP_OK → LOGOUT` |

### C-04 (carried forward, **Blocker**) — only `REVOKE` clears elevation

`k1::b16_inv_a_*`. From `auth.active` ‖ `elevation.elevated`:

| event | final configuration |
|---|---|
| `REVOKE` | `auth.revoked` ‖ `elevation.normal` ✅ |
| `LOGOUT` | `auth.revoked` ‖ **`elevation.elevated`** ❌ |
| `IDLE_DEADLINE` | `auth.revoked` ‖ **`elevation.elevated`** ❌ |
| `ABSOLUTE_DEADLINE` | `auth.revoked` ‖ **`elevation.elevated`** ❌ |

The `elevation` region declares `REVOKE` only. INV-B16-a says elevation is
cleared *unconditionally* on leaving the active auth state; three of the four
exits do not clear it, and `clear_elevated` never runs. This is a
privilege that outlives its session — anything reading the `elevated` tag
after a logout gets a stale `true`.

Worse, **elevation can be acquired after revocation**
(`k5_edges.py::b16_elevate_after_revoke`): `MFA_OK → REVOKE → STEP_UP_OK`
ends on `auth.revoked` ‖ `elevation.elevated`, receipt `changed=True`, with
`stamp_elevated_until`, `audit_step_up` and `schedule_elevation_deadline` all
executed. The `elevation` region has no notion of the session being dead.
INV-B16-d holds only if you read it as a statement about the `auth` region.

**The library is doing exactly the right thing** — in a `parallel` root, a
region that does not declare an event is untouched by it, and `auth.revoked`
being `final` does not stop a sibling region. The defect is ours.

*Fix*: add `LOGOUT`, `IDLE_DEADLINE`, `ABSOLUTE_DEADLINE`, `MFA_TIMEOUT` and a
`MFA_FAILED`-exhausted path to `elevation.elevated` targeting
`elevation.normal` with `clear_elevated`, **and** add a terminal
`elevation.revoked` (or a guard on `STEP_UP_OK` reading the auth region) so
elevation cannot be re-acquired. The simplest correct shape is a third
`elevation` state `dead`, entered from every session-ending event in both
`normal` and `elevated`, with no outgoing transitions.

### C-05 (carried forward, Low) — `STEP_UP_OK` while already elevated is not audited

`k1::b16_inv_c`, trace
`… audit_step_up_failed, stamp_elevated_until, audit_step_up,
schedule_elevation_deadline, stamp_elevated_until, schedule_elevation_deadline`.
The second `STEP_UP_OK` (the re-enter transition inside `elevated`) runs
`stamp_elevated_until` but **not** `audit_step_up`. INV-B16-c says every
step-up attempt writes an audit record. Add `audit_step_up` to the
`elevated → elevated` re-enter transition.

### Deferral in a terminal region (W-02, carried forward)

`k1::b16_inv_d`: `MFA_OK → REVOKE → MFA_OK → REQUEST → STEP_UP_OK` ends with
`deferred_count == 2`. `MFA_OK` and `REQUEST` are declared by the machine
(so `strict` admits them) but undeclared by `auth.revoked`, so
`onUnhandled: "defer"` holds them for ever — the auth region can never leave
`revoked`. The receipts correctly read `deferred=True`, so this is visible,
but the buffer is unbounded and grows for the life of a dead session.
**W-02**: the wrapper caps the defer buffer and drops with an audit record
when the active configuration contains a terminal tag.

---

## 3. B17 — LiveEnablement gate

`k1_b16_b17.py`, `k5_edges.py`, `k6_failsnap.py`.

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path `EVIDENCE_RECORDED → ENABLE_REQUESTED → DISABLE_REQUESTED` | **PASS** | `locked → eligible → enabled → eligible`; `broadcast_live_enabled` + `enable_live_visual_language` on entry to `enabled`, `record_disable` + `audit_live_disabled` on the way out |
| **INV-B17-a** records and orchestrates, does not enforce | **PASS by construction** | no synchronous read path exists on the machine; the tags (`live_blocked` / `live_allowed`) are advisory |
| **INV-B17-b** enable requires owner + elevation + still-valid evidence (2FA + pen-test gate) | **PASS on the guard** | `owner_and_elevated_and_evidence_still_valid=False` → stays `eligible`, runs `audit_enable_denied`, receipt `changed=False`. But see W-03 |
| **INV-B17-c** `EVIDENCE_INVALIDATED` demotes immediately | **PASS** | from `enabled`: → `locked`, `clear_evidence_item` + `raise_critical_alert` |
| **INV-B17-d** `EMERGENCY_DISABLE` is never gated | **PASS** | with `owner_and_elevated=False` it still reaches `locked` with `record_disable` + `raise_critical_alert` |
| **INV-B17-e** every enable/denial/disable audited | **PASS** | each of the three paths writes its `audit_*` action |
| Snapshot/restore at quiescence between every macrostep | **PASS 2/2** | zero mid-step errors, zero diffs, traces identical |
| Sync parity | **PASS** | same configuration + trace as async |

### `rollback` replaces `"fail"` cleanly (C-03 closed)

`k1::b17_rollback`. With `audit_live_enabled` raising — the second action of
the `eligible → enabled` transition, after `record_enable` — the machine stays
on `eligible`, `status` stays `running`, the receipt carries
`error=RuntimeError`, and the context is restored (`enabled_by` still `null`).
The action trace shows all three actions *attempted*
(`record_evidence, record_enable, audit_live_enabled`) but no context effect
survives. This is what CV-C31 asked for. What is missing is the **`halted`
sink** the correction note promises — see **C-07**; today the operator sees a
failed receipt and a gate that silently stayed shut.

For the record, with `"fail"` forced back on (`k5::fail_policy_b17`,
`k6_failsnap.py`), #145 is confirmed: `status="stopped"`, `configuration`
cleared, `.error = TransitionFailedError`, snapshot persists
`status: "stopped"` with an empty configuration, and `from_snapshot` refuses
it with `InvalidConfigError`. **L-01 is closed.**

### W-03 (carried forward) — authorisation events are replayable

`k2::b17_stale_replay`. `ENABLE_REQUESTED` sent while `locked` is deferred
(receipt `deferred=True`), and the moment the final `EVIDENCE_RECORDED`
promotes the gate to `eligible`, the held request **fires by itself**:
final state `enabled`, trace
`record_evidence, record_enable, audit_live_enabled, broadcast_live_enabled,
enable_live_visual_language`. An operator who pressed "enable" against a
`locked` gate, saw it refused, and walked away has enabled live trading
minutes later when an unrelated evidence upload landed. The guard is
re-evaluated, so this is not an authorisation bypass in the narrow sense —
but the *intent* was scoped to the state the operator observed, and the
elevation window that `owner_and_elevated_and_evidence_still_valid` reads may
still be open. **The wrapper must make authorisation events non-deferrable**:
either refuse them at the call site when the gate is not `eligible`, or stamp
them with the configuration they were issued against and have the guard reject
a replay. `strict` cannot help here — `ENABLE_REQUESTED` is a declared event.

---

## 4. B18 — KillSwitch

`k2_b18.py`, `k4_redo.py`, `k5_edges.py`. The only machine with
`onUnhandled: "error"`.

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path `ENGAGE` → `engaging` → `cancelling` → `flattening` → `engaged` | **PASS** | one macrostep; `block_new_orders_immediately` is the **first** action of `engaging`'s entry list, before `cancel_entry_and_poll_drains` and `broadcast_kill_switch` |
| **INV-B18-b** blocking takes effect before the recording event is processed | **PASS (within the contract's reach)** | the `always` chain `engaging → cancelling → …` runs inside the same macrostep as `ENGAGE`, and the block action precedes every outward effect. The synchronous-flag part of the invariant is outside the interpreter by design |
| **INV-B18-c** `engaged` requires all accounts flat | **PASS** | `all_accounts_flat=False` → `engaged_incomplete` with `page_owner` + `emit_incomplete_metric`; `RETRY_FLATTEN` re-runs `flattening` and pages again |
| service failures | **PASS** | `cancel_all_working_orders` raising → `engaged` + `raise_critical_alert`; `flatten_all_positions` raising → `engaged_incomplete` + alert + page |
| **INV-B18-d** release requires owner + elevation (+ residual ack) | **FAIL — the denial kills the machine** | see C-07b |
| **INV-B18-e** engagement and release audited | **PASS** | `record_engagement` + `audit_kill_switch` on engage, `audit_kill_switch_released` on release |
| `send_priority` preemption | **PASS** | `send_priority("ENGAGE", wait=True)` against a `max_queue_size=8` inbox jumps the queue and completes; `changed=True`, machine reaches `engaged` |
| Snapshot/restore at quiescence between every macrostep | **PASS 2/2** | zero mid-step errors, zero diffs, traces identical — including across the invoke-bearing `cancelling`/`flattening` states, with `restart_services=True` |
| Sync parity | **N/A** | `SyncInterpreter` raises `NotSupportedError: Service 'cancel_all_working_orders' is async and not supported` — see §7 |

### C-07b (sharpened C-03b, **Blocker**) — `onUnhandled: "error"` turns two ordinary operator mistakes into a dead kill switch

Two reproductions, both from `engaged`/`cancelling`:

1. **Guard-denied `RELEASE`** (`k5::b18_error_terminal`). Wrong-privilege
   button press in `engaged`: the receipt is now honest —
   `changed=False, denied=True` (#153 works) — but `on_unhandled_event` fires
   with `disposition="errored"`, `interp.status` flips to `"error"` with
   `interp.error = UnhandledEventError`, and **the next event
   (`RETRY_FLATTEN`) comes back `InterpreterStoppedError`**. The kill switch
   is now unreleasable *and* unretryable. `get_persisted_snapshot()` still
   succeeds, recording `status: "error"`.
2. **`RELEASE` arriving while `cancelling`** (`k4::b18_release_while_cancelling`,
   with a genuinely gated `cancel_all_working_orders`). `RELEASE` is
   undeclared in `cancelling`; same outcome — `status="error"`,
   configuration stuck on `cancelling`, `unhandled=[("RELEASE","errored")]`.
   An operator double-clicking release during a slow cancel sweep bricks the
   machine mid-flatten.

Note the ordering that makes this worse than it looks: a **guard denial** is
routed into `onUnhandled` at all. `Receipt.denied` distinguishes it for the
caller, but the `"error"` policy does not — a declared-and-refused event and
an undeclared one are equally fatal. Every other control machine in the
catalogue (B13, B14) survives this because their event vocabularies are
closed in every state; B18's is not.

**OUR-CONTRACT, Blocker. W-04**: drop `onUnhandled: "error"` from B18 in
favour of `"defer"` plus an explicit `strict` vocabulary, and surface refusal
through `Receipt.denied` (now available) rather than through a policy that
stops the interpreter. A safety device must not be disabled by a wrong button
press.

---

## 5. B19 — Reconciliation job

`k3_b19_b20.py`, `k4_redo.py`.

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy sweep `SWEEP_DUE` | **PASS** | `idle → fetching → diffing → reporting → idle` in one macrostep; `set_trigger_periodic, stamp_start, emit_recon_started, store_exchange_state, store_divergences, persist_report, emit_recon_metrics, reset_failures, broadcast_recon_complete` |
| trigger provenance (`STARTUP` / `UNKNOWN_ORDER` / `RECONNECTED`) | **PASS** | each writes its own `set_trigger_*` before the sweep |
| fetch failure → backoff | **PASS** | `bump_failures` + `schedule_retry_deadline`, lands `backing_off` |
| `failures_exhausted` → `stale_lockout` | **PASS** | `lock_account_for_new_orders` + `page_owner` |
| `CANCEL` during a live sweep | **PASS** | with `fetch_exchange_state` genuinely gated, `CANCEL` in `fetching` returns to `idle`, receipt `changed=True`, nothing deferred |
| **INV-B19-b** operator resolution clears the lockout | **FAIL** | see C-06 |
| Snapshot/restore at quiescence between every macrostep | **PASS 2/2** | including across an in-flight `invoke` with `restart_services=True`; zero mid-step errors, zero diffs, traces identical |
| Sync parity | **N/A** | `NotSupportedError` on the async services — §7 |

### C-02 is **closed** — `onUnhandled: "defer"` now holds the trigger

`k4::b19_unknown_during_sweep`, the scenario that was the worst finding of the
`3ed3099` run. With the `"*"` scaffolding removed from the catalogue and a
genuinely gated `fetch_exchange_state` holding the machine in `fetching`:

| observation | value |
|---|---|
| configuration when `UNKNOWN_ORDER` arrives | `reconciliation.fetching` |
| receipt | `changed=False, deferred=True, denied=False, error=None` |
| `deferred_count` | `1` |
| `on_unhandled_event` | `("UNKNOWN_ORDER", "deferred")` |
| after the gate is released | `reconciliation.idle`, `deferred_count=0` |
| action trace tail | `… broadcast_recon_complete, set_trigger_unknown, stamp_start, emit_recon_started, … broadcast_recon_complete` |

The trigger is held, replayed as its own macrostep when the first sweep
finishes, and runs a **second** sweep stamped `set_trigger_unknown`. Exactly
the required behaviour. The event is no longer destroyed, the receipt is no
longer the inadmissible `changed=False, error=None, deferred=False` shape, and
`deferred_count` plus the hook both report it.

### C-06 (carried forward, High) — `stale_lockout` only listens for `RECONNECTED`

`k4::b19_stale_*`. From `stale_lockout`:

| event | outcome |
|---|---|
| `RECONNECTED` | → `fetching`, `reset_failures`; if the fetch fails again → straight back to `stale_lockout`, **re-running `lock_account_for_new_orders` and `page_owner`** |
| `OPERATOR_RESOLVED` | **deferred** (`deferred=True`, `deferred_count=1`), machine stays locked |
| `SWEEP_DUE` | **deferred**, machine stays locked |

Two problems. First, INV-B19-b's operator escape hatch does not exist in the
state that needs it most: `OPERATOR_RESOLVED` is declared on `divergent`, not
on `stale_lockout`, so the one event an operator would send to clear an
account lock is silently buffered for ever. Second, `RECONNECTED` on a
flapping link re-enters `stale_lockout` on every failed retry and **pages the
owner every time** — the trace shows `page_owner` twice after a single flap.
A flapping exchange connection becomes a page storm.

*Fix*: declare `OPERATOR_RESOLVED` on `stale_lockout` (target `idle`, with an
unlock action), and make `page_owner` edge-triggered — guard it on a `paged`
context flag reset by a successful sweep, or move it out of the entry list
onto the `backing_off → stale_lockout` transition only.

---

## 6. B20 — RiskLockout

`k3_b19_b20.py`.

| Invariant | Verdict | Evidence |
|---|---|---|
| breach → lock | **PASS** | `PNL_UPDATE` with `breaches_daily_loss_cap` → `locked`, full entry list `halt_new_orders, compute_until, schedule_expiry_deadline, raise_lockout_alert, audit_lockout, broadcast_lockout`; `halt_new_orders` is first |
| warning band is edge-triggered | **PASS** | `clear → warning` runs `emit_risk_warning` once; `outside_warning_band` returns to `clear` |
| `CAP_BREACH` / `MANUAL_LOCK` | **PASS** | both reach `locked` with their own `set_breach_*` reason |
| expiry honours `until_mode` | **PASS** | time-based → `clear` + `resume_new_orders` + `reset_daily_counters_if_new_day`; manual mode → stays `locked`, `log_expiry_ignored_manual_mode`, receipt `changed=False` |
| override requires owner + elevation + permission | **PASS** | permitted → `clear` + `resume_new_orders` + `audit_override`; denied → stays `locked` + `audit_override_denied`, receipt `changed=False` (**not** fatal — B20 uses `defer`, unlike B18) |
| `actionErrorPolicy: "rollback"` on the entry list | **PASS mechanically, see C-07** | `broadcast_lockout` raising rolls the *whole* `locked` entry back to `clear`, `status="running"`, receipt `error=RuntimeError` |
| Snapshot/restore at quiescence between every macrostep | **PASS 2/2** | zero mid-step errors, zero diffs, traces identical |
| Sync parity | **PASS** | identical configuration and trace (no services on B20) |

The rollback case is the clearest illustration of **C-07**: the machine ends on
`risk_lockout.clear`, tagged `trading_allowed`, after having attempted a
lockout. Nothing in the statechart records the attempt. The `halted` state the
§1.3b note promises is exactly what this needs.

---

## 7. CV-C32 — `service_executor` (#149) does **not** retire the async-only rule

`k4_redo.py::cvc32_plain_def_service`. A plain `def` service
(`time.sleep(0.25)`) installed as B18's `cancel_all_working_orders` on the
async engine:

| | |
|---|---|
| ran and completed | yes, machine reached `kill_switch.engaged` |
| service wall time | 0.251 s |
| event-loop ticks observed *during* the blocking call | **7** (a 20 ms ticker) |
| `Interpreter(service_executor=…)` parameter present | yes |

**#149 works as advertised on the async engine** — the loop keeps turning
while a blocking service runs, so the CV-C32 rationale (a plain-`def` service
stalls every timer and inbound send) no longer applies there.

**But CV-C32 must stay, for the opposite reason.** `SyncInterpreter` refuses
`async def` services outright:
`NotSupportedError: Service 'cancel_all_working_orders' is async and not
supported` — reproduced on both B18 and B19 (`k2::b18_sync`, `k3::b19_sync`).
So the real constraint is not "services must be async" but "**a machine's
services are engine-specific**": async-only on the async engine is fine and
now efficient, but it forecloses `SyncInterpreter` entirely for B18 and B19.
Sync parity for those two machines is therefore **not available**, not
"untested". If a synchronous fallback for the control machines is ever wanted,
the wrapper has to supply a second, `def`-shaped service table — and per #149
the async engine will run that one on its executor without blocking.
Recommend restating CV-C32 as: *services are provided per engine; the async
table is `async def`, the optional sync table is plain `def`, and the two are
generated from one source.*

---

## 8. Defect register

| # | Class | Machines | Severity | Statement |
|---|---|---|---|---|
| **C-04** | OUR-CONTRACT | B16 | **Blocker** | elevation survives `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE`, and can be *acquired after* revocation — INV-B16-a violated, INV-B16-d violated at the session level |
| **C-07b** | OUR-CONTRACT | B18 | **Blocker** | `onUnhandled: "error"` makes a guard-denied `RELEASE` **and** a `RELEASE` arriving mid-`cancelling` terminal (`status="error"`, next event `InterpreterStoppedError`); the kill switch is disabled by a wrong button press (W-04) |
| **C-06** | OUR-CONTRACT | B19 | High | `stale_lockout` declares only `RECONNECTED`: `OPERATOR_RESOLVED` is deferred for ever and a flapping link re-pages the owner on every retry |
| **C-07** | OUR-CONTRACT | B17, B18, B20 (all five) | High | the §1.3b correction promises `rollback` + explicit `halted` states; **no `halted` state exists in any contract**, so a failed transition rolls back to a state that denies anything went wrong |
| **C-01** | OUR-CONTRACT | all | High | `create_machine` is not a conformance gate — a bare `MachineLogic()` builds all five (W-01) |
| **C-05** | OUR-CONTRACT | B16 | Low | `STEP_UP_OK` while already elevated writes no audit record (INV-B16-c) |
| **W-03** | needs wrapper | B17 | High | a deferred `ENABLE_REQUESTED` auto-fires when the gate later becomes eligible; authorisation events must be non-deferrable or configuration-stamped |
| **W-02** | needs wrapper | B16 (shape: all) | Medium | the defer buffer is unbounded in a terminal region — a revoked session accumulates deferred events for ever |
| **W-01** | needs wrapper | all | — | implementation-conformance gate at build + `on_transition_failed` → out-of-band halt, substituting for the missing `halted` states |
| **C-02** | **CLOSED** | B19 | — | the `"*"` scaffolding is gone from the catalogue; `onUnhandled: "defer"` holds and replays `UNKNOWN_ORDER` correctly |
| **C-03 / L-01** | **CLOSED** | B17, B20 | — | `"fail"` now stops the machine with a cleared configuration and a non-resumable snapshot (#145); the catalogue's `rollback` substitution works |
| **L-02** | **partially closed** | B18 | — | `Receipt.denied` (#153) distinguishes guard denial for the `wait=True` caller; what remains is C-07b, a policy choice of ours, not a library gap |

### No new LIBRARY defects

Every surprise in this run traced back to the contract, not the engine. In
particular: the parallel-region behaviour behind C-04 is correct SCXML
semantics; `rollback` restoring the source state is what `rollback` means; and
`onUnhandled: "error"` stopping the interpreter is exactly what that policy
documents. The three round-5 fixes this track depended on (#145 `"fail"`, the
defer path behind C-02, and #153 `Receipt.denied`) all landed and are
reproduced above.

### Snapshot discipline

Nine snapshot-every-macrostep runs across all five machines — including B18's
and B19's `invoke`-bearing states with `restart_services=True,
restart_timers=True` — produced **zero** `SnapshotMidStepError` at quiescence,
**zero** `ids`/`ctx`/`status` divergence from the uninterrupted run, and
**identical** transition traces. Snapshotting at quiescence between macrosteps
is safe on these five contracts on `cec108b`.

### What to do before B16–B20 ship

1. Merge the E50-T14 fixes for C-04 and C-06 into §B16 / §B19 (both are
   one-transition edits with a clear shape, given above).
2. Add the `halted` states the §1.3b correction note already promises (C-07),
   or land W-01 first so `on_transition_failed` has somewhere to go.
3. Drop `onUnhandled: "error"` from B18 (C-07b / W-04) — it is the only
   contract where an operator mistake stops the interpreter, and it guards the
   one machine that must never stop.
4. Restate CV-C32 per §7.
