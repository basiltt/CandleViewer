# Contract machines end-to-end — B16–B20 on `main` @ `3ed3099`

**Library** `xstate-statemachine` @ `3ed3099` (unreleased 0.8.1; `__version__`
still reports `0.8.0` — keyed on commit).
**Engine** async `Interpreter` primary, `SimulatedClock`, bounded inbox
(`max_queue_size`, `OverflowPolicy.RAISE`) on the order-adjacent paths.
`SyncInterpreter` run for parity information only.
**Machines** B16 `session`, B17 `live_gate`, B18 `kill_switch`,
B19 `reconciliation`, B20 `risk_lockout` — XML/JSON taken verbatim from
`docs/plan/28-statechart-catalogue.md` §B16.1–§B20.1, including the §1.3b
mandatory policy block.
**Scripts** `contracts/c0_build.py`, `c0b_lazy.py`, `c1_b16.py`, `c1b_b16x.py`,
`c2_b17.py`, `c2b_b17x.py`, `c3_b18.py`, `c3b_b18x.py`, `c4_b19.py`,
`c5_b20.py`, `c6_headline.py`; helpers `charness.py` (pre-existing) +
`cdrv.py` (new). Raw JSON under `contracts/results/`.
**Method** every finding below was reproduced from a standalone script before
it was counted. Nothing is inferred from reading source.

---

## 0. Headline

| | |
|---|---|
| Machines that build from the catalogue JSON unchanged | **5 / 5** |
| `InvalidConfigError` / `ImplementationMissingError` at build | **0** (see C-01 — that is itself the finding) |
| Invariant scenarios driven | 47 |
| Invariants PASS | 21 |
| Invariants FAIL | 6 |
| `SnapshotMidStepError` raised across ~40 snapshot/restore cycles at quiescence | **0** |
| Snapshot-every-macrostep traces equal to the uninterrupted run | **13 / 13** |
| LIBRARY defects | 1 (L-01) + 1 doc/observability gap (L-02) |
| OUR-CONTRACT defects | 5 (C-01 … C-05) |
| Needs-wrapper items | 4 (W-01 … W-04) |

**No fixed copy of any machine was required.** All five configs are valid for
the library as written; `<B>.machine.json` overrides were not created. The
catalogue defects below are semantic, not structural.

**The two that matter.**

1. **C-02 — the "dead but harmless" `"*"` scaffolding is neither.** §1.3b
   E50-T09 states that with `onUnhandled: "defer"` set, the inline
   `"*": {"actions": ["defer"]}` handler "never fires". It fires. It is an
   ordinary internal transition, it *wins*, and it **silently destroys the
   event**: `onUnhandled` is never consulted, `deferred_count` stays `0`, the
   `on_unhandled_event` hook never fires, and the receipt reads
   `changed=False, error=None, deferred=False` — the exact inadmissible shape
   §1.3b already prohibits as a gate. In B19 this eats `UNKNOWN_ORDER`
   arriving during a sweep, which is a reconciliation trigger being dropped on
   the floor.
2. **L-01 / C-03 — `actionErrorPolicy: "fail"` leaves the machine on the
   SOURCE state, permanently bricked, with its outward effects already
   applied.** On B20, a raise in `broadcast_lockout` (last in the `locked`
   entry list, per CV-C02) leaves the configuration on `risk_lockout.clear`
   — tag `trading_allowed` — after `halt_new_orders`, `audit_lockout` and
   `raise_lockout_alert` have all run. `status` goes `error`, every
   subsequent event is refused, and **`get_persisted_snapshot()` happily
   persists that state**, contradicting MUST-01 ("the snapshot writer refuses
   to persist a faulted context"). Identical on B17.

---

## 1. Step 1 — build with stub `MachineLogic`

`c0_build.py`, `results/c0_build.json`; `c0b_lazy.py`.

| Machine | id | root | build (full stub) | build (bare `MachineLogic()`) | actions / guards / services |
|---|---|---|---|---|---|
| B16 | `session` | `parallel` | OK | **OK** | 18 / 1 / 0 |
| B17 | `live_gate` | compound | OK | **OK** | 10 / 3 / 0 |
| B18 | `kill_switch` | compound | OK | **OK** | 9 / 5 / 2 |
| B19 | `reconciliation` | compound | OK | **OK** | 22 / 3 / 3 |
| B20 | `risk_lockout` | compound | OK | **OK** | 16 / 5 / 0 |

Every key of the §1.3b block is read and honoured by the machine object:
`action_error_policy`, `guard_error_policy`, `on_unhandled`,
`spawn_blocking_timeout_ms` (5000.0). `strictTargets` and `strict` behave as
specified — an undeclared event name raises `UnknownEventError` **at the call
site** (verified on B16, `c1b_b16x.py::strict`).

### C-01 — missing implementations are not a build error (OUR-CONTRACT / needs wrapper)

`create_machine(cfg, logic=MachineLogic(strict=True))` with **zero** actions,
guards and services **builds successfully** for all five machines. The failure
surfaces only at first use, as a receipt:

```
send("EVIDENCE_RECORDED", wait=True)
  -> changed=False, error=ImplementationMissingError("Guard 'all_evidence_present' not implemented.")
```

The catalogue assumes `create_machine` is the conformance gate. It is not.
For a safety machine, a missing guard is a denial that looks like a
transition that legitimately did not fire. **W-01** below is the wrapper.

---

## 2. B16 — AuthSession / step-up

`c1_b16.py`, `c1b_b16x.py`; `results/c1_b16.json`, `results/c1b_b16x.json`.

Happy path `MFA_OK → REQUEST → STEP_UP_OK → REQUEST` reaches
`['session.auth.active', 'session.elevation.elevated']`; both regions enter
and advance independently; `reenter: true` on `auth.active` re-runs the full
entry list (`stamp_idle_deadline`, `audit_login`) as intended.

| Invariant | Verdict | Evidence |
|---|---|---|
| **INV-B16-a** elevation cannot outlive the session | **FAIL** | see C-04 |
| **INV-B16-b** every revocation records a specific reason + broadcasts | **PASS** | all six reasons distinct: `set_revoke_admin` / `_logout` / `_idle` / `_expired` / `_timeout` / `_locked`, each followed by `audit_session_revoked`, `broadcast_revocation` |
| **INV-B16-c** every step-up attempt audited | **PARTIAL FAIL** | see C-05 |
| **INV-B16-d** `revoked` is terminal; never un-revoked | **PASS (auth region)** / **FAIL (as a session)** | see C-04 |
| **INV-B16-e** deadlines are absolute, honoured on restore | **PASS (library side)** | snapshot/restore at every macrostep is trace-identical; `has_dormant_timers` is exposed and `from_snapshot(clock=, restart_timers=True)` works. The re-evaluation itself is boot-procedure code, not machine code (B20.7) |

Snapshot/restore at quiescence between every macrostep, three sequences
(`happy`, `inv_a`, `inv_d`): **0 `SnapshotMidStepError`**, `diffs = {}` on
state ids, context and status. Parallel regions round-trip correctly.

### C-04 — `REVOKE` clears elevation but `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` do not (OUR-CONTRACT, Blocker)

INV-B16-a says "leaving the active auth state clears elevation
**unconditionally**". The JSON implements it as an event-name coincidence:
`elevation.elevated` handles exactly one event, `REVOKE`. Reproduced:

| terminating event | final configuration |
|---|---|
| `REVOKE` | `auth.revoked` + `elevation.normal` ✅ |
| `LOGOUT` | `auth.revoked` + **`elevation.elevated`** ❌ |
| `IDLE_DEADLINE` | `auth.revoked` + **`elevation.elevated`** ❌ |
| `ABSOLUTE_DEADLINE` | `auth.revoked` + **`elevation.elevated`** ❌ |

Worse, elevation can be *acquired* after revocation: from
`['session.auth.revoked', 'session.elevation.normal']`, sending `STEP_UP_OK`
returns `changed=True` and lands on `elevation.elevated`, running
`stamp_elevated_until` and `audit_step_up`. `elevated_until_us` is described
as "a derived value of the elevation region" — so a revoked session derives
as elevated. This is a privilege-escalation shape in an auth machine.

**Fix is ours, in the JSON**, not a wrapper: the elevation region must react
to the auth region's exit, not to a list of event names. Two options, both
library-supported: (a) put the elevation region's clearing transition on
`onDone` of the `auth` region (`auth.revoked` is `type: "final"`, so the
region completes and the engine emits `done.state.session.auth`), or (b) make
elevation a child of `auth.active` so the region is destroyed on exit. (a) is
the smaller edit and preserves the orthogonal shape.

### C-05 — `STEP_UP_OK` while already elevated is not audited (OUR-CONTRACT, minor)

INV-B16-c: "every step-up attempt, success or failure, writes an audit
record". The `elevation.normal → elevated` transition carries
`["stamp_elevated_until", "audit_step_up"]`; the `elevated → elevated`
re-entry carries only `["stamp_elevated_until"]`. Reproduced: the trace for
`STEP_UP_FAILED, STEP_UP_OK, STEP_UP_OK` is
`[audit_step_up_failed, stamp_elevated_until, audit_step_up,
stamp_elevated_until, schedule_elevation_deadline]` — the second, successful
step-up (an elevation *extension*, the interesting one for C-2.9) leaves no
audit record. Add `audit_step_up` to the re-entry transition.

### W-02 — the deferral buffer is unbounded in a terminal region

`c1b_b16x.py::defer_growth`. With the session revoked, 300 `REQUEST` events
were accepted, all reported `deferred` by `on_unhandled_event`, and
`deferred_count` reached **300** with no cap, no `on_event_dropped`, and no
back-pressure — `max_queue_size` bounds the *inbox*, not the defer buffer.
Since `auth.revoked` is `final`, nothing will ever drain them. For a session
fleet this is an unbounded per-session leak driven by remote traffic.
Not a library defect (the policy is doing what it says), but it needs the
wrapper in **W-02**.

---

## 3. B17 — LiveEnablement gate

`c2_b17.py`, `c2b_b17x.py`; `results/c2_b17.json`, `results/c2b_b17x.json`.

| Invariant | Verdict | Evidence |
|---|---|---|
| **INV-B17-b** enable requires owner + step-up elevation + still-valid evidence | **PASS on the guard, FAIL on arrival order** | guard denial works exactly (`owner=T, elevated=F` → stays `eligible`, runs `audit_enable_denied`, `changed=False`). But see C-02/W-03 |
| **INV-B17-c** `EVIDENCE_INVALIDATED` demotes immediately | **PASS** | from `enabled`: → `locked`, `[clear_evidence_item, raise_critical_alert]`. From `eligible`: → `locked` |
| **INV-B17-d** `EMERGENCY_DISABLE` ungated, always succeeds | **PASS** | with `owner=False, elevated=False`, `EMERGENCY_DISABLE` from `enabled` → `locked`, `changed=True`, no guard consulted (`guard_calls` tail unchanged) |
| **INV-B17-e** every enable / denial / disable audited | **PASS** | `audit_enable_denied`, `audit_live_enabled`, `audit_live_disabled` all observed on their respective paths |
| **INV-B17-a** records, does not enforce | **N/A** (architectural; nothing in the machine contradicts it) |

Snapshot every macrostep over
`EVIDENCE_RECORDED, ENABLE_REQUESTED, DISABLE_REQUESTED, ENABLE_REQUESTED,
EMERGENCY_DISABLE`: **0 `SnapshotMidStepError`**, `diffs = {}`, and the action
trace is **byte-identical** to the uninterrupted run. Sync engine agrees
(no invokes on this machine).

### C-02 (B17 instance) — `ENABLE_REQUESTED` is deferred while `locked` and auto-fires the instant evidence lands

`c2b_b17x.py::deferred_enable_autoreplay`. `locked` has no
`ENABLE_REQUESTED` handler, so `onUnhandled: "defer"` holds it
(`deferred=True`, `deferred_count=1`). The next `EVIDENCE_RECORDED` that
satisfies `all_evidence_present` moves the gate to `eligible` — and the
held enable request **replays in the same settling pass and enables live
trading**:

```
transitions: init->[locked], EVIDENCE_RECORDED->[eligible], ENABLE_REQUESTED->[enabled]
actions:     record_evidence, record_enable, audit_live_enabled,
             broadcast_live_enabled, enable_live_visual_language
```

No human pressed anything between "evidence recorded" and "live enabled".
This is `onUnhandled: "defer"` behaving exactly as documented; it is our
contract that is wrong to apply it to a machine whose events are *human
authorisations*. Authorisation events must not be replayable: the operator's
intent was scoped to the state they observed. **W-03.**

### C-03 (B17 instance) — `actionErrorPolicy: "fail"` after the outward effect

See §7 (L-01) for the shared analysis. On B17, a raise in
`enable_live_visual_language` (last in the `enabled` entry list) leaves ids
`['live_gate.eligible']`, `status=error`, after `record_enable`,
`audit_live_enabled` and `broadcast_live_enabled` have all executed — i.e.
**the world was told live is enabled and the machine says it is not**, and
the machine can no longer be driven to `EMERGENCY_DISABLE` (`changed=False`,
`status` stays `error`).

---

## 4. B18 — KillSwitch

`c3_b18.py`, `c3b_b18x.py`; `results/c3_b18.json`, `results/c3b_b18x.json`.

| Invariant | Verdict | Evidence |
|---|---|---|
| **INV-B18-a/b** the block is a synchronous flag, set *before* the recording event is processed | **PASS** | `block_new_orders_immediately` ran and the flag read `True` **at the caller's `await send(..., wait=True)` return**, with the configuration already at `cancelling` and the invoke in flight. Bounded inbox (`max_queue_size=8`, `RAISE`) in place |
| **INV-B18-c** `engaged` requires all flat; anything less pages | **PASS** | `all_accounts_flat=True` → `engaged`; `False` → `engaged_incomplete` + `[page_owner, emit_incomplete_metric]`. `RETRY_FLATTEN` re-enters `flattening` and re-pages |
| **INV-B18-d** release requires owner + elevation (+ residual ack) | **FAIL — the denial bricks the machine** | see C-03b |
| **INV-B18-e** engage / release audited | **PASS** | `record_engagement, audit_kill_switch` … `audit_kill_switch_released` |
| service `onError` paths | **PASS** | `cancel_all_working_orders` raises → `error.platform.cx` → `engaged` + `raise_critical_alert`; `flatten_all_positions` raises → `engaged_incomplete` + `raise_critical_alert` + `page_owner` |

Snapshot every macrostep, three sequences (`engage_only`, `full`,
`incomplete`): **0 `SnapshotMidStepError`**, `diffs = {}`, action traces
identical — including across the `always` fan-out in `engaging` and the two
`invoke` completions. The `always` chain resolves in one macrostep
(`ENGAGE->[engaging]`, `->[cancelling]`).

### Kill switch via `send_priority` preempts a busy inbox — **PASS, with a fatal caveat**

`c3b_b18x.py::busy_priority`. The machine was parked in `cancelling` with a
genuinely awaiting 400 ms service, and **20** `RETRY_FLATTEN` events were
flooded behind it (`queue_depth == 20`). `send_priority("RELEASE")` returned
in **0.7 ms** — it jumped 20 queued events and an in-flight invoke. The
priority lane works, and works at the latency a kill switch needs.

But the answer it returned was `changed=False`, and `status` flipped to
**`error`**, because `RELEASE` is not handled in `cancelling` and B18 is the
one machine carrying `onUnhandled: "error"`. The machine ended parked in
`cancelling` forever. **A kill switch that cannot be released while it is
engaging is a kill switch that is not releasable when it matters.**

### C-03b — on B18 a guard-denied event is indistinguishable from an unhandled one, and `onUnhandled: "error"` bricks the machine (OUR-CONTRACT, Blocker)

`c3b_b18x.py::denied_release`. From `engaged`, `RELEASE` with
`owner_and_elevated=False`:

```
before: ids=[kill_switch.engaged]  status=running
after:  ids=[kill_switch.engaged]  status=error
        receipt: changed=False, error=None, deferred=False
        interp.last_error = None
        on_unhandled_event hook: ('RELEASE', 'errored')
        subsequent RETRY_FLATTEN: changed=False, status stays error
        get_persisted_snapshot(): succeeds, persists status="error"
```

Three compounding problems, all reproduced:

1. **A guard denial and an unhandled event are the same thing to the engine.**
   A transition whose only candidate is guarded-out selects nothing, so
   `onUnhandled` fires. An *authorised, expected, correctly-denied* release
   attempt is therefore treated as a protocol violation.
2. **`onUnhandled: "error"` is terminal.** The machine is unusable
   afterwards. On the one machine in the catalogue whose entire job is to be
   available in an emergency, a wrong-privilege button press disables it.
3. **The caller cannot see any of it.** The receipt is
   `changed=False, error=None` and `interp.last_error` is `None`. The only
   signal is the `on_unhandled_event` plugin hook — out-of-band, and not
   correlated to the `wait=True` caller. This is the *same* inadmissible
   receipt shape §1.3b already banned for the `defer` case, now also present
   for the `error` case.

`onUnhandled: "error"` must come off B18 (or every guarded transition needs
an explicit unguarded fallback arm that audits the denial, as B17 and B20
already do for exactly this reason — B18 is the outlier). See **W-04**.

### Sync parity (informational)

`SyncInterpreter` cannot run B18 at all: `NotSupportedError: Service
'cancel_all_working_orders' is async and not supported.` Same for B19. This
is documented library behaviour, not a defect, but it means B18/B19 have no
sync fallback path.

---

## 5. B19 — Reconciliation job

`c4_b19.py`, `c6_headline.py`; `results/c4_b19.json`,
`results/c6_headline.json`.

The full pipeline works. `idle → fetching → diffing → [remediating] →
reporting → (idle | divergent)` resolves correctly for every combination of
the three guards, and all four triggers (`SWEEP_DUE`, `RECONNECTED`,
`UNKNOWN_ORDER`, `STARTUP`) stamp their distinct trigger action.

| Invariant / scenario | Verdict | Evidence |
|---|---|---|
| reconnect / resync sequence | **PASS** | `RECONNECTED` → `set_trigger_reconnect` → full sweep → `idle` |
| divergence, auto-remediate on | **PASS** | `store_divergences, store_remediations, persist_report, …` |
| divergence unresolved | **PASS** | → `divergent` (`needs_attention`) + `raise_divergence_alert`; `OPERATOR_RESOLVED` → `idle` |
| fetch fails → backoff → retry | **PASS** | `error.platform.fetch` → `backing_off` + `bump_failures, schedule_retry_deadline`; `RETRY_DUE` → `fetching` |
| failures exhausted → `stale_lockout` | **PASS** | `lock_account_for_new_orders, page_owner` |
| diff / remediate `onError` | **PASS** | both route to `reporting`; remediate error also `raise_critical_alert` |
| **INV-B19-f** every sweep persists a report | **PASS** | `persist_report` on every path that reaches `reporting`, including both error paths |
| **cancel a mid-flight sweep delivers no stale `done.invoke`** | **PASS — important** | see below |
| **INV-B19-b** `stale_lockout` cleared only by `OPERATOR_RESOLVED` | **FAIL** | see C-06 |
| **INV-B19-e** parked mid-fetch is a silent hang | **CONFIRMED, and the library gives the tools** | see below |

**Cancel-mid-flight (the property the catalogue's "why this shape" rests on)
holds.** `c4_b19.py::cancel_midflight`: parked in `fetching` with a 400 ms
service, `CANCEL` returned `changed=True` and moved to `idle` immediately;
700 ms later — long past when the fetch would have resolved — the machine was
**still `idle`**, transitions were exactly
`[init->idle, SWEEP_DUE->fetching, CANCEL->idle]`, and no
`store_exchange_state` ever ran. No stale result was applied. This is the
single most consequential corruption path for reconciliation and the library
closes it.

**Snapshot every macrostep** across `clean` (2 sweeps), `divergent` and
`remediate`: **0 `SnapshotMidStepError`**, `diffs = {}`, traces identical —
across three chained invokes and an `always` fan-out.

**Parked mid-fetch** (`parked_midfetch`): snapshotting *during* an invoke is
allowed (the root is settled; only the service is in flight) and restores to
`fetching`. With `restart_services=False` the machine sits in `fetching`
forever — the LC-19 silent hang, confirmed. The library now makes it
*detectable*: `has_dormant_invocations == True`, `has_dormant_timers ==
False`, and `pending_invocations()` returns
`PendingInvocation(state_id='reconciliation.fetching', invoke_id='fetch',
src='fetch_exchange_state')`. `restart_services=True` re-drives it. CV-C20's
reconcile-on-restore requirement is implementable exactly as written.

### C-02 — the inline `"*"` defer scaffolding destroys events (OUR-CONTRACT, Blocker)

`c6_headline.py::x1_star_shadows_defer`. B19 is the only one of these five
machines that still carries the E50-T09 scaffolding inline (on `fetching` and
`remediating`). §1.3b says it is dead. Side-by-side, same machine, same run:

**`fetching` (inline `"*"` present):**
```
send("UNKNOWN_ORDER", wait=True)
  receipt:        changed=False, error=None, deferred=False
  deferred_count: 0
  on_unhandled_event hook:  (never fired)
  transitions:    ... SWEEP_DUE->[fetching], *->[fetching]
  actions:        ... emit_recon_started, defer
  after the sweep completes: set_trigger_unknown NEVER runs
```

**`backing_off` (no inline `"*"`):**
```
send("UNKNOWN_ORDER", wait=True)
  receipt:        changed=False, error=None, deferred=True
  deferred_count: 1
  on_unhandled_event hook:  ('UNKNOWN_ORDER', 'deferred')
```

The inline handler is a real internal transition and it wins. The event is
consumed, the runtime buffer never sees it, and the `defer` *action* — which
in our stub does nothing, and in `cv.statechart` is scheduled for deletion —
is the only thing that "handles" it. `UNKNOWN_ORDER` is a reconciliation
trigger (INV-B19-c: unknown orders are resolved by lookup); dropping it means
an unknown order is never reconciled.

It gets worse: the correctly-deferred copy from `backing_off` **also dies**.
On `RETRY_DUE` the machine enters `fetching`, the held `UNKNOWN_ORDER`
replays there, and the inline `"*"` eats it (`after_retry_trace` shows
`stamp_start, emit_recon_started, defer` and
`unknown_order_replayed == False`). The scaffolding does not merely fail to
help; it converts a durable buffered event into a lost one.

**E50-T09 is not cosmetic and is not deferrable.** The scaffolding must be
stripped from all twenty contracts before any of them runs, and CV-LINT must
reject a `"*"` handler on any machine configured `onUnhandled: "defer"`.

### C-06 — `stale_lockout` contradicts its own invariant (OUR-CONTRACT)

INV-B19-b: "`stale_lockout` locks the account for new orders and is cleared
only by `OPERATOR_RESOLVED`." The JSON's `stale_lockout` handles **only**
`RECONNECTED`, and has no `OPERATOR_RESOLVED` handler. Reproduced:

- `RECONNECTED` from `stale_lockout` → `fetching` + `reset_failures`. The
  lockout is cleared **by a network event**, with no operator involved. Since
  `failures_exhausted` is still true, the machine bounces straight back to
  `stale_lockout`, re-running `lock_account_for_new_orders` and **paging the
  owner again** on every reconnect — a page storm during exactly the network
  instability that caused the lockout.
- `OPERATOR_RESOLVED` from `stale_lockout` → `changed=False, deferred=True`,
  held forever (the machine never leaves `stale_lockout` on its own).

Either the invariant or the JSON is wrong. Given INV-B19-a ("its own faults
escalate to `stale_lockout` rather than retrying forever"), the JSON is wrong:
`stale_lockout` should handle `OPERATOR_RESOLVED`, and `RECONNECTED` should
either not be handled there or be guarded on `!failures_exhausted`.

---

## 6. B20 — RiskLockout

`c5_b20.py`; `results/c5_b20.json`.

| Invariant | Verdict | Evidence |
|---|---|---|
| **INV-B20-b** edge-triggered band walk | **PASS** | `none→warn→none→warn→breach` produced exactly one `emit_risk_warning` per *entry* into `warning`; the `none` pass while already clear was internal (`changed=False`, `update_pnl` only) |
| **INV-B20-e** manual mode ignores expiry and logs it | **PASS** | `until_mode_is_time_based=False` → `EXPIRY_DUE` internal, stays `locked`, runs `log_expiry_ignored_manual_mode`. Time-based → `clear` + `[resume_new_orders, reset_daily_counters_if_new_day]` |
| **INV-B20-f** overrides gated and audited, denials too | **PASS** | permitted → `clear` + `[resume_new_orders, audit_override]`; denied → stays `locked` + `audit_override_denied` |
| **INV-B20-c** `breaches_daily_loss_cap` is deny-polarity; a failure never permits trading | **PASS (fail-safe), but not as specified** | see below |
| **INV-B20-a** `halt_new_orders` is a synchronous flag | **N/A** (architectural) |
| **INV-B20-d** absolute-deadline expiry survives restore | **PASS (library side)** | snapshot every macrostep is trace-identical; re-evaluation is boot code |
| entry-action failure under `actionErrorPolicy: "fail"` | **FAIL** | see §7 |

**Snapshot every macrostep**, four sequences (`lock_expire`, `lock_override`,
`breach`, `warn`): **0 `SnapshotMidStepError`**, `diffs = {}`, traces
identical. Sync engine parity: **exact match** on ids, context and the full
action trace for `MANUAL_LOCK, EXPIRY_DUE` (B20 has no invokes).

**Guard-raise polarity.** `guardErrorPolicy: "raise"` is honoured and is
**fail-safe here by luck of ordering**: a raising `breaches_daily_loss_cap`
aborts the whole `PNL_UPDATE` transition — the machine stays `clear`,
`changed=False`, `error=RuntimeError`, and, crucially, **the machine remains
usable**: a subsequent `MANUAL_LOCK` succeeded and reached `locked`
(`status=running`). That is the correct A6 outcome for B20. Note the
contrast with B18, where the equivalent situation is terminal — the
difference is `onUnhandled: "error"`, not `guardErrorPolicy`. The catalogue's
guard contract ("returns `False` on any internal error") is *inconsistent*
with the mandated `guardErrorPolicy: "raise"`; the observed raise-and-abort
behaviour is the safer of the two and the tables in §B20.4 should be
corrected to match the policy block rather than the reverse.

---

## 7. L-01 — `actionErrorPolicy: "fail"` leaves the source configuration and refuses all further events, while the snapshot writer persists it

**Classification: LIBRARY defect (behaviour + contract), compounded by an
OUR-CONTRACT defect (C-03).**
Reproduced on **both** `fail`-policy machines, three raising actions each:
`c2b_b17x.py`, `c5_b20.py`, `c6_headline.py::x2_fail_leaves_source_state`.

B20, raise in `broadcast_lockout` (the **last** action of the `locked` entry
list — the placement CV-C02 mandates for outward effects):

```
intended target:  risk_lockout.locked      (tag: trading_blocked)
ids after:        risk_lockout.clear       (tag: trading_allowed)
status:           error
receipt:          changed=False, error=RuntimeError
already executed: set_breach_manual, halt_new_orders, compute_until,
                  schedule_expiry_deadline, raise_lockout_alert,
                  audit_lockout, broadcast_lockout
subsequent OVERRIDE_REQUESTED: changed=False, status stays error
get_persisted_snapshot():  SUCCEEDS  -> {"status": "error",
                                         "state_ids": ["risk_lockout.clear"]}
```

Identical shape on B17 (`enable_live_visual_language`, → stays
`live_gate.eligible`, `status=error`, `EMERGENCY_DISABLE` refused).

Three separate problems:

1. **The configuration is left on the source, not on the target and not in a
   fault state.** §1.3b describes `fail` as "a half-applied step in a
   safety-invariant machine must halt, not continue", and §B20.5 says a
   raising action "aborts the transition and routes to **this machine's fault
   state**". There is no fault state and no routing: the machine silently
   reads as the *pre-transition* state. For B20 that is literally the
   difference between `trading_blocked` and `trading_allowed`, after
   `halt_new_orders` has already run. Any consumer reading `current_state_ids`
   or the state's tags — which is how the catalogue says the flag is
   projected — gets the wrong answer.
2. **`status = error` is terminal and silent.** Every subsequent `send`
   returns `changed=False` with `error=None`, and the machine logs
   "dropping event … nothing drains the queue after shutdown". A safety
   machine that stops accepting `EMERGENCY_DISABLE` / `OVERRIDE_REQUESTED`
   after one action raise is a worse failure than the one it was protecting
   against. Nothing in the `fail` documentation says the machine becomes
   permanently inert.
3. **MUST-01 is unenforceable as written.** §B20.5 / §B17.5: "the snapshot
   writer refuses to persist a faulted context." `get_persisted_snapshot()`
   does not refuse — it persists `status: "error"` with the source
   `state_ids`. Restoring that blob yields a machine that reports the wrong
   configuration *and* the wrong liveness. #102's `SnapshotMidStepError`
   covers the no-leaf window; this is a different window (a legal leaf, but
   the *wrong* one) and is not covered.

Item 1 is arguably by-design (rollback-of-configuration is what `fail` and
`rollback` share), but it is not what the library's own prose promises, and
it is the opposite of safe for the machines the policy table assigns `fail`
to. Items 2 and 3 are, on the evidence, defects worth filing. Until they are
fixed, **C-03** stands: assigning `actionErrorPolicy: "fail"` to B8/B17/B18/
B20 does not achieve "halt, not continue" — it achieves "silently revert and
brick". The contract must either add an explicit `faulted` state that the
`fail` path can be *routed* to (which requires library support it does not
have) or move to `rollback` + an explicit fault transition driven by a
wrapper (**W-01**).

### L-02 — a denied/unhandled event is invisible to the `wait=True` caller (library, observability)

Confirmed on B18 (`denied_release`) and restated from §1.3b's withdrawn
CV-C06 clause: for `changed=False, error=None`, the caller cannot distinguish
*no-op* / *guard-denied* / *deferred* / *unhandled-and-errored*.
`Receipt.deferred` (#84) closes exactly one of those four. `interp.last_error`
stays `None` even when the machine transitions to `status=error` via
`onUnhandled`. The `on_unhandled_event` hook sees it but is not correlated to
the send. The out-of-band discriminator §1.3b requires ("a correlated
`on_event_deferred` hook") is still absent, and the gap is now demonstrably
wider than the defer case alone.

---

## 8. Wrapper specifications

### W-01 — `cv.statechart.factory` conformance gate + fault routing

*Closes C-01, mitigates L-01.*

```
factory.create(contract_json, logic) ->
  1. Structural lint (CV-LINT-XS1..XS14) BEFORE create_machine.
  2. Collect every action/guard/service name the JSON references
     (walk entry/exit/on/always/after/invoke.onDone/onError) and assert
     each is present in `logic`. Raise ContractIncompleteError listing
     ALL missing names at once. create_machine will NOT do this.
  3. MachineLogic(strict=True); one logic object per create_machine call.
  4. Wrap every action in @cv_action: on exception, write
     context["_fault"], then explicitly `send_priority` a FAULT event
     that the machine handles from ANY state into an explicit
     `faulted` leaf. Set actionErrorPolicy to "rollback", not "fail",
     so the interpreter stays `running` and the FAULT event can land.
     "fail" is unusable until L-01 is fixed.
  5. After construction, assert interp.status == "running" before the
     machine is published to any consumer, and re-assert on every
     receipt: a transition to status=="error" is a page, not a log line.
```

### W-02 — bounded, observable defer buffer

*Closes the B16 unbounded-growth finding.*

```
Before every send: if interp.deferred_count > DEFER_CAP (propose 32),
  refuse the send at the gateway, emit a metric, and page. The library
  bounds the inbox (max_queue_size) but NOT the defer buffer, and a
  machine in a final/terminal region will never drain it.
Additionally: refuse to send ANY event to an interpreter whose active
  configuration is entirely final/terminal — `deferring into a grave`
  is always a caller bug.
```

### W-03 — authorisation events are not replayable

*Closes C-02's B17 instance.*

```
Every event that carries human authority (ENABLE_REQUESTED,
DISABLE_REQUESTED, RELEASE, OVERRIDE_REQUESTED, STEP_UP_OK) carries
`authorised_for_state` and `authorised_at_us` in its payload. The
gateway refuses to enqueue such an event; instead it sends it only
after asserting the CURRENT configuration equals `authorised_for_state`
and the authorisation is within TTL. An authorisation that would be
deferred is REJECTED at the call site with a "gate moved under you"
error the operator sees, never held.
Enforced by CV-LINT: no machine may leave an authorisation event
unhandled in any state it can be sent from.
```

### W-04 — denial arms on every guarded transition; drop `onUnhandled: "error"` from B18

*Closes C-03b.*

```
CV-LINT: on any machine, every `on` entry whose transition array's LAST
element carries a guard is a lint ERROR. A guarded transition must end
in an unguarded fallback arm that audits the denial (B17 and B20
already do this; B18's RELEASE and RETRY_FLATTEN do not).
Separately: B18 moves to onUnhandled: "defer" + an explicit "*"-free
closed vocabulary check in the gateway. `onUnhandled: "error"` is
terminal on this library, and a terminal kill switch is not a kill
switch. The closed-vocabulary property B18 wanted is already delivered
by `strict: true`, which raises at the CALL SITE (verified) and does
not brick the machine.
```

---

## 9. Defect register

| ID | Class | Machine | Severity | Summary |
|---|---|---|---|---|
| **L-01** | LIBRARY | B17, B20 | **Blocker** | `actionErrorPolicy: "fail"` reverts to the source configuration, flips `status` to a terminal `error` that refuses all further events, and `get_persisted_snapshot()` persists it — contradicting "routes to the machine's fault state" and MUST-01 |
| **L-02** | LIBRARY | B18 (all) | High | `changed=False, error=None` + `last_error is None` for a guard-denied *and* an `onUnhandled: "error"`-killed event; no correlated hook for the `wait=True` caller |
| **C-01** | OUR-CONTRACT | all | High | catalogue assumes `create_machine` validates implementations; it does not — missing guards surface as a failed receipt at first use (W-01) |
| **C-02** | OUR-CONTRACT | B19 (+B17 shape) | **Blocker** | the inline `"*": {"actions": ["defer"]}` scaffolding §1.3b calls dead **fires, wins, and destroys the event**; also destroys events correctly held by the runtime buffer when they replay into such a state. E50-T09 must land first |
| **C-03** | OUR-CONTRACT | B8, B17, B18, B20 | **Blocker** | the `actionErrorPolicy: "fail"` row of the §1.3b policy table does not achieve "halt, not continue" on this library (see L-01); use `rollback` + explicit fault routing (W-01) |
| **C-03b** | OUR-CONTRACT | B18 | **Blocker** | `onUnhandled: "error"` makes a guard-denied `RELEASE` terminal; the kill switch is disabled by a wrong-privilege button press, and is unreleasable while `engaging`/`cancelling` (W-04) |
| **C-04** | OUR-CONTRACT | B16 | **Blocker** | elevation survives `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE`, and can be *acquired* after revocation — INV-B16-a and -d both violated |
| **C-05** | OUR-CONTRACT | B16 | Low | `STEP_UP_OK` while already elevated writes no audit record (INV-B16-c) |
| **C-06** | OUR-CONTRACT | B19 | High | `stale_lockout` handles only `RECONNECTED` (not `OPERATOR_RESOLVED`), inverting INV-B19-b and producing a page storm on flapping connectivity |
| **W-01…W-04** | needs wrapper | — | — | specified in §8 |

## 10. What held up

Worth stating plainly, because it is most of the surface area:

- **Snapshot/restore at quiescence is solid.** ~40 snapshot→stop→
  `from_snapshot`→`start`→resume cycles across 13 sequences and 5 machines,
  including parallel regions (B16), chained `invoke`s (B18, B19) and `always`
  fan-outs (B18, B19): **zero `SnapshotMidStepError`**, and every resumed run
  was trace-identical to its uninterrupted twin on state ids, context, status
  and the full ordered action list. #102's window is real but is not hit by a
  caller who snapshots at quiescence, which is what CV-C20 already mandates.
- **`from_snapshot(clock=)` and `restart_timers=` (#117, #128) work**, and
  `has_dormant_invocations` / `has_dormant_timers` / `pending_invocations()`
  make the LC-19 static-restore hang *detectable* for the first time.
- **`send_priority` preempts a saturated inbox and an in-flight invoke in
  0.7 ms** with 20 events queued — the bounded-latency property B18 depends on.
- **Cancelling a mid-flight invoke delivers no stale `done.invoke`** (B19),
  which is the corruption path the catalogue's §B19 shape was chosen to avoid.
- **`strict: true` raises `UnknownEventError` at the call site**,
  `strictTargets` and `guardErrorPolicy: "raise"` behave exactly as the policy
  block specifies, and `spawnBlockingTimeout` is read (5000 ms).
- **Sync/async parity** is exact where the sync engine can run at all
  (B20: identical ids, context and action trace). B18 and B19 cannot run on
  `SyncInterpreter` because their services are async — documented, but it
  means those two have no sync fallback.

---

*Time-bounded run. Parameterisations were kept small deliberately: the defer
growth probe stopped at 300 events (no cap was found, so the result is a
lower bound, not a measured limit), the busy-inbox probe used 20 queued
events rather than a full saturation sweep, and property/fuzz coverage of
these five machines was not attempted — this pass was scenario-driven against
the listed invariants, as scoped.*
