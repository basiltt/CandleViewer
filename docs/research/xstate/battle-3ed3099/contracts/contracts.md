# Contract machines B1–B5, end-to-end on `xstate-statemachine` @ `3ed3099`

**Scope.** B1 Order, B2 TradeGroup, B3 TradeGroupLeg, B4 OCO, B5 Iceberg — the five
order-path contracts from `docs/plan/28-statechart-catalogue.md`, driven against the
async engine with the mandatory §1.3b policy block intact, `SimulatedClock`,
`MachineLogic(strict=True)`, a bounded inbox under `OverflowPolicy.RAISE`, and a
trace plugin on every run. Date 2026-09-19. Library commit `3ed3099`
(unreleased 0.8.1; `__version__` still reads 0.8.0).

**Headline.** The library is not the problem here. 77 invariant scenarios were
driven; **74 pass once our own catalogue JSON is corrected**, and the three that
remain are one genuine gap in our own B4 contract plus the B8 structural-gate item
that is a wrapper obligation by construction. On the JSON **as written in doc 28**,
64 scenarios ran (B3 aborted early on a fatal error), **15 failed, and three of
those lose a fill silently.** Five distinct defects were found. Three are OUR-CONTRACT defects, one is a
LIBRARY defect (a namespace hazard, not a semantics bug), one invariant needs a
wrapper. The snapshot/restore story is clean: across 22 crash points spanning all
five machines, `get_persisted_snapshot()` never raised `SnapshotMidStepError` at a
quiescent point, and every resumed run matched the uninterrupted reference run on
state ids, context **and** full action trace.

## 1. Build phase — no `InvalidConfigError`, no `ImplementationMissingError`

All five machines `create_machine()` cleanly with a stub `MachineLogic` derived
mechanically from the JSON (`charness.collect` walks `entry`/`exit`/`on`/`always`/
`after`/`invoke` and synthesises every action, guard, service and delay).
No validation error on any of the five, on either the original or the corrected
JSON. `strictTargets: true` and `strict: true` are honoured; the absolute
`#order.lifecycle.*` target style resolves.

That clean build is itself part of the finding: **three of the four defects below
are invisible at build time and only surface at runtime**, two of them without an
exception.

## 2. Per-invariant results

`orig` = catalogue JSON verbatim. `fixed` = `<B>.machine.json`, produced by
`fix_contracts.py`, diff logged in `catalogue-diff.json`.

### B1 — Order (23 scenarios)

| Invariant / scenario | orig | fixed | Note |
|---|---|---|---|
| init configuration (parallel regions) | PASS | PASS | `draft` + `not_required` |
| happy path draft→validated→submitting→submitted | PASS | PASS | |
| happy path →filled on `EXEC` | PASS | PASS | |
| **INV-2** terminal never left | PASS | PASS | post-`filled` `CANCEL` is held, not applied |
| **INV-5** `EXEC` during `submitting` is held | **FAIL** | PASS | **D-1**, fill lost |
| **INV-5** held `EXEC` applied after ack | **FAIL** | PASS | **D-1** |
| reject path (`ret_code_ok` false → `rejected`) | PASS | PASS | |
| `actionErrorPolicy: rollback` — no half-commit | PASS | PASS | receipt carries the `RuntimeError` |
| **B8** SL attach failure ⇒ `sl_missing` | PASS | PASS | |
| **INV-B1-f** `sl_present` only from `SL_OBSERVED` | PASS | PASS | |
| **B8** structural gate present | **FAIL** | **FAIL** | **D-4**, needs wrapper |
| **INV-B1-c** `AMEND_REJECTED` keeps order live | PASS | PASS | returns to `partially_filled` |
| **INV-B1-d** fill beats pending cancel | PASS | PASS | `cancel_pending` handles `EXEC` explicitly |
| INV-2 late cancel-ack cannot revive a filled order | PASS | PASS | |
| **B13** transport fault ⇒ `unknown` | PASS | PASS | |
| **INV-B1-e** `unknown` never resubmits | PASS | PASS | `place_order` call count unchanged |
| **B19** second consecutive recon miss ⇒ `rejected` | PASS | PASS | |
| **B19** recon divergence `RECON_FOUND_PARTIAL` | PASS | PASS | |
| **B18** `send_priority` accepted on a full inbox | PASS | PASS | 8 of 12 normal sends raised `QueueOverflowError`; the priority send did not |
| **B18** priority event actually preempts the backlog | **FAIL** | PASS | **D-1** — the `"*"` handler ate `FAULT` too |
| snapshot never mid-step at quiescence (7 crash points) | PASS | PASS | zero `SnapshotMidStepError` |
| snapshot resume — state + context parity | PASS | PASS | |
| snapshot resume — full action-trace parity | PASS | PASS | 15 actions, byte-identical |

### B2 — TradeGroup (13 scenarios)

| Invariant / scenario | orig | fixed |
|---|---|---|
| init `draft` | PASS | PASS |
| `CONFIRM` ⇒ `submitting` | **FAIL** (**D-2**) | PASS |
| **INV-B2-b** not resolved at 1 of 2 legs | **FAIL** (D-2) | PASS |
| happy: 2/2 legs ⇒ `open` via the `EVALUATE` chain | **FAIL** (**D-3**) | PASS |
| **INV-B2-b** `open+failed+skipped ≤ total` | PASS | PASS |
| `ALL_LEGS_FLAT` ⇒ `closed` | **FAIL** (D-2) | PASS |
| **INV-B2-c** `all_or_none` + a failure ⇒ unwind, never rests | **FAIL** (D-2/D-3) | PASS |
| `abort_on_first` ⇒ `aborting` ⇒ `always` ⇒ `partially_open` | **FAIL** (D-2) | PASS |
| quiesce deadline, zero open ⇒ `failed` | **FAIL** (D-2/D-3) | PASS |
| **INV-B2-a** status is a pure function of the counters | PASS | PASS |
| snapshot sweep (5 crash points) × 3 checks | PASS | PASS |

**INV-B2-d** (unwind restartable/idempotent) and **INV-B2-e** (legs via the
app registry, never `sendTo`) are **not decidable from the machine**: the first is a
property of `persist_unwind_plan`'s implementation, the second is precisely what
D-2 below turns into a trap. Both are recorded as wrapper obligations, not as
passes.

### B3 — TradeGroupLeg (13 scenarios)

| Invariant / scenario | orig | fixed |
|---|---|---|
| init `always` chain ⇒ `submitting` | **CRASH** (**D-2**, `ActorSpawningError`) | PASS |
| **INV-B3-a** `sized_qty` computed exactly once | crash | PASS |
| first `EXEC` ⇒ `partially_filled` + ladder | crash | PASS |
| `EXEC` completes the leg ⇒ `filled` | crash | PASS |
| **INV-B3-b** ladder placed once | crash | PASS (with caveat, below) |
| **INV-B3-d** `verify_sl` runs after the close attempts | crash | PASS |
| **INV-B3-e** `close_attempts` bounded ⇒ visible `error` | crash | PASS |
| **INV-B3-e** retry loop terminates (3 attempts, cap `<3`) | crash | PASS |
| **INV-B3-c** authoritative position read per attempt | crash | PASS (3 reads / 3 attempts) |
| `resolving` resolves by lookup, never blind resubmit | crash | PASS |
| **INV-5** `EXEC` during `resolving` survives | crash | PASS |
| snapshot sweep (5 crash points) × 3 checks | crash | PASS |

> **INV-B3-b caveat.** `place_tp_ladder_once` fires on the `open → partially_filled`
> edge, so within one run it is exactly-once. But nothing in the machine makes it
> idempotent across a **restore into `open` followed by a fresh `EXEC`** — that path
> fires it a second time. The invariant's "does not create a second ladder" clause
> must be satisfied inside the action (an idempotency key on the ladder), not by the
> chart. Recorded as a wrapper obligation.

### B4 — OCO (11 scenarios)

| Invariant / scenario | orig | fixed |
|---|---|---|
| `arming` ⇒ `racing`, child ids recorded | PASS | PASS |
| settle ⇒ `completing` | PASS | PASS |
| **INV-B4-b** `completed` requires `CHILDREN_TERMINAL` | PASS | PASS |
| **INV-B4-d** fill on the other leg during settlement is applied | **FAIL** | **FAIL** — **D-5** |
| **INV-B4-a** both fills recorded before settlement decision | **FAIL** | **FAIL** — D-5 |
| **INV-B4-c** overshoot corrected reduce-only | PASS | PASS |
| settle error `order_gone` ⇒ `reconciling` ⇒ `completing` | PASS | PASS |
| settle retry bounded (3 calls, cap 2 failures) ⇒ `failed` | PASS | PASS |
| snapshot sweep (3 crash points) × 3 checks | PASS | PASS |

### B5 — Iceberg (16 scenarios)

| Invariant / scenario | orig | fixed |
|---|---|---|
| `pending` ⇒ `submitting_slice` ⇒ `working` | PASS | PASS |
| **INV-B5-b** one live child (`active_child_id` single-valued) | PASS | PASS |
| slice fill ⇒ `waiting_refill` | PASS | PASS |
| refill ⇒ next slice | PASS | PASS |
| **INV-B5-a** `remaining_qty` never negative | PASS | PASS |
| completion ⇒ `completed` on `CHILDREN_TERMINAL` | PASS | PASS |
| **INV-B5-e** 2 post-only rejects ⇒ `cooling_down` | PASS | PASS |
| **INV-B5-e** cooldown is quiescent (no busy loop) | PASS | PASS |
| cooldown resumes on `COOLDOWN_DUE` | PASS | PASS |
| **INV-B5-c** `slices_done ≤ max_slices`, exhaustion completes | PASS | PASS |
| `WS_DISCONNECT` freezes (policy guard) | PASS | PASS |
| **B13** `RESUME` reconciles children before resuming | PASS | PASS |
| child event during `submitting_slice` survives | **FAIL** (**D-1**) | PASS |
| snapshot sweep (4 crash points) × 3 checks | PASS | PASS |

**INV-B5-d** (absolute deadlines re-armed from context on restore, including the
"expired while down" case) is **not exercised**: B5 carries `next_refill_at_us` in
context but has no `after` block, so the deadline is entirely external. It is a
scheduler obligation, not a chart property — listed as a wrapper item.

---

## 3. Defects

### D-1 — OUR-CONTRACT, **Blocker.** The retired A3 scaffolding does not just fail to help — it silently eats fills.

Catalogue §1.3b / `E50-T09` states the inline `"*": {"actions": ["defer"]}` handler is
"**dead but harmless** — with `onUnhandled: 'defer'` set, the runtime holds the event
before any `"*"` handler is consulted".

**That is exactly backwards.** The wildcard is an ordinary internal transition. It
*matches*, so the event is **handled**; `onUnhandled` is only consulted for an event
that matched nothing. The runtime buffer is therefore never reached, the named
`defer` action is a no-op that does nothing with the event, and the event is gone.

Repro: `repro/r1_star_preempts_defer.py` (12-line machine, both variants in one run):

```
WITHOUT inline '*':  deferred_at_send=1  fills=1  receipt=(changed=False, deferred=True)
WITH    inline '*':  deferred_at_send=0  fills=0  receipt=(changed=False, deferred=False)
hooks with scaffolding: on_event_dropped=[]   on_unhandled_event=[]
```

No exception, no drop hook, no unhandled hook, and the receipt is
`changed=False, error=None, deferred=False` — **indistinguishable from a correct
no-op**. This is LC-03 reintroduced by our own scaffolding, in the exact shape
§1.3b says it closed.

Blast radius on the order path (states carrying the handler, all of which are
occupied during an exchange round trip): B1 `draft`, `validated`, `submitting`,
`cancel_pending`, `amend_pending`; B3 `resolving`; B4 `racing`, `settling_a`,
`settling_b`; B5 `submitting_slice`. Measured consequences: a fill delivered during
B1 `submitting` is lost (`apply_fill` never runs, order rests in `submitted`
forever); a `CHILD_PARTIAL` during B5 `submitting_slice` is lost; and — worst — a
**B18 kill-switch `FAULT` delivered via `send_priority` to a machine parked in
`submitting` is swallowed by the wildcard**, so the priority lane is defeated by our
own JSON. The priority send itself is accepted on a saturated inbox (that part works),
but the event dies on arrival.

**Fix:** land `E50-T09` — strip the `"*"` handlers, the `drain_deferred` entry actions
and the `_deferred` context key. Done mechanically in `fix_contracts.py`;
14 edits on B1, 2 on B3, 5 on B4, 2 on B5, 0 on B2. With those edits every D-1
scenario flips to PASS, `deferred_count` reads 1 at the send point, and the receipt
correctly reports `deferred=True`. **Note the §1.3b prohibition still stands and is
now better supported**: the receipt is only trustworthy *because* the runtime buffer
is reached — with the scaffolding in place the receipt actively lies.

### D-2 — LIBRARY, **Major (namespace hazard).** Any action named `spawn_*` is hijacked and never called.

`base_interpreter._execute_actions` routes any action whose `type` starts with
`spawn_` or `spawn_blocking_` to `_spawn_actor` **before** consulting
`machine.logic.actions`. Every other built-in does the opposite — the source comment
twelve lines below says built-ins are resolved "only when the user has NOT supplied an
action of the same name, so a machine that legitimately defines its own `log` or
`assign` keeps working". `spawn_` is the one prefix that unconditionally claims a
name out of the user's namespace.

Repro: `repro/r2_spawn_prefix_steals_action_name.py`

```
place_all_legs        user_action_called=['place_all_legs']  ids=['m.b']   # control
spawn_all_legs        user_action_called=[]                  ids=['m.a']
spawn_entry_order     user_action_called=[]                  ids=['m.a']
spawn_blocking_thing  user_action_called=[]                  ids=['m.a']
```

The user's implementation is registered, `MachineLogic(strict=True)` is set,
`create_machine()` builds clean — and the action is simply never invoked. The machine
does not advance. On B2 (`spawn_all_legs`, on the `CONFIRM` transition) the failure is
**fully silent**: `ActorSpawningError` is raised inside the action list, swallowed by
`actionErrorPolicy: "rollback"`, and the group sits in `draft` forever — seven of B2's
scenarios failed this way with nothing in the receipt. On B3 (`spawn_entry_order`, an
`entry` action) it escapes as a fatal `ActorSpawningError` naming a service
`'entry_order'` the machine never declared.

Two things are wrong, and they are separable:

1. **Precedence.** `spawn_` should follow the same "user wins" rule as `log`/`assign`.
2. **Diagnosis.** If precedence must stay (arguably a spawn *is* structural), then
   `create_machine()` with `MachineLogic(strict=True)` should reject at **build time**
   an action name that starts with `spawn_` and also has a user implementation, rather
   than deferring to a runtime `ActorSpawningError` that names a service the author
   never wrote. A silent forever-stall on a rollback machine is the worst possible
   outcome.

This one is worth filing. It is also **our defect to work around today**: B2's
INV-B2-e explicitly says legs are addressed through the application-owned registry
and **never** as a library actor, so `spawn_all_legs` was always a misnomer.
`fix_contracts.py` renames `spawn_all_legs → launch_all_legs` and
`spawn_entry_order → submit_entry_order`. Add a linter clause
(**CV-LINT-XS15**: no action name may begin with `spawn_` or `spawn_blocking_`
unless it is genuinely a library spawn).

### D-3 — OUR-CONTRACT, **Major.** B2's `raise_evaluate` cannot do what B2 needs it to do.

B2 drives its own resolution with an internal `EVALUATE` event, emitted by an action
called `raise_evaluate` on four transitions in `submitting`. As written it is a plain
**named** action — and a named action cannot emit an event. CV-C16 forbids calling
`send()` on your own interpreter from an action; the only bounded self-emission shape
the engine offers is the `raise` built-in. So `raise_evaluate` runs, does nothing, no
`EVALUATE` is ever delivered, and the group never leaves `submitting` no matter how
many legs report in — confirmed by trace: `["arm_quiesce_deadline", "count_open",
"raise_evaluate", "count_failed", "raise_evaluate"]`, zero guard evaluations, zero
transitions out. **INV-B2-c is violated in the most dangerous direction**: an
`all_or_none` group with a failed leg never unwinds and never resolves.

Fix in `fix_contracts.py`: replace with the built-in,

```json
{"type": "raise", "params": {"event": {"type": "EVALUATE"}}}
```

Note the `params` nesting — the engine rejects `{"type": "raise", "event": {...}}` at
build with a clear `InvalidConfigError`, which is good behaviour and caught this
immediately. With the built-in, all seven B2 scenarios pass and the `EVALUATE` chain
resolves within one macrostep.

### D-4 — NEEDS WRAPPER. B8's "no position state without native SL" is observable in B1 but not enforced by it.

B1's two regions are fully independent: there is **no `stateIn` guard anywhere in the
B1 JSON**, and no lifecycle transition consults the `protection` region. The machine
therefore happily occupies `lifecycle.partially_filled` ∧ `protection.sl_missing` —
which §B1 says is the point (the §8.8 watchdog must be able to *see* that
combination). But the B8 invariant as the task states it ("no position state
reachable without native SL confirmed") is **not a property this machine enforces**.
It cannot be, in this shape: gating the fill path on the protection region would mean
refusing to record an exchange fill that has already happened.

**Wrapper spec — `cv.statechart.protection_watchdog`:**

- Subscribe to B1 via a plugin `on_transition` hook. Maintain the pair
  `(lifecycle_leaf, protection_leaf)` per order.
- The enforceable invariant is **temporal, not structural**: for every order,
  `protection == sl_missing ∧ lifecycle ∈ {partially_filled, filled, triggered}`
  must hold for no longer than `CV_NAKED_POSITION_MAX_MS`. Entering that pair arms a
  deadline; leaving it disarms.
- On expiry: escalate to the B20 risk lockout and fire the B18 kill switch for that
  account. Do **not** attempt the correction from inside B1 — `request_fallback_sl`
  on `sl_missing` entry is the retry, and it has already run.
- The watchdog owns the alerting. `raise_naked_position_alert` in the machine is the
  *signal*; the wrapper is the *enforcement*.
- Assert at factory time that B1's `protection` region has no incoming edge to
  `sl_present` other than `SL_OBSERVED` (INV-B1-f is structural and **does** hold —
  verified).

### D-5 — OUR-CONTRACT, **Major.** B4 `completing` has no `LEG_B_FILL`/`LEG_A_FILL` handler, so INV-B4-d's deferred fill is deferred forever.

This one survives the D-1 fix, which is what makes it interesting. With the
scaffolding stripped, the runtime correctly holds a `LEG_B_FILL` that arrives while
`settling_b` is in flight — `deferred_count == 1`, receipt `deferred=True`, exactly as
designed. But the settle completes into `completing`, and `completing` handles only
`CHILDREN_TERMINAL`. The replayed fill matches nothing there either, so it is
**re-deferred**, and the trace shows it: `unhandled=[('LEG_B_FILL','deferred'),
('LEG_B_FILL','deferred')]`. `record_fill_b` never runs; `filled_b` stays `"0"`.
INV-B4-a ("both fills recorded before any settlement decision") fails with it.

The deferral machinery is working correctly. The contract is wrong: **deferring an
event is only safe if some reachable state handles it.** B4 defers a fill into a
state graph whose only continuation is terminal.

**Fix (belongs in doc 28, not in the wrapper):** add to `oco.completing`

```json
"LEG_A_FILL": {"actions": ["record_fill_a"]},
"LEG_B_FILL": {"actions": ["record_fill_b"]}
```

as internal transitions, and re-evaluate `position_overshoots` on the way into
`completed`. A late fill on the losing leg is precisely the double-fill the
`overshoot` path exists for; today it is buffered into oblivion instead.

> **Generalise this.** Every `onUnhandled: "defer"` machine needs a static check that
> each deferrable event has a handler in some state reachable from every state that
> can defer it. Proposed **CV-LINT-XS16**. B4 is the one machine of the five that
> fails it; B1, B3 and B5 all pass by inspection (their deferring states lead back to
> a state that handles the held event).

---

## 4. Snapshot / restore at quiescence — clean

22 crash points across the five machines (every macrostep boundary of each script),
each snapshotted, restored into a fresh interpreter with
`from_snapshot(..., clock=SimulatedClock(), restart_services=True, restart_timers=True)`,
resumed with the remainder of the script, and compared against an uninterrupted
reference run.

- **`SnapshotMidStepError`: 0 occurrences.** The #102 refusal window is genuinely
  confined to mid-macrostep; snapshotting at quiescence (`queue_depth == 0 and
  deferred_count == 0`, per CV-C20) never tripped it on any of the five.
- **State + context parity: 5/5 machines, all crash points.**
- **Full action-trace parity: 5/5.** `prefix_trace + resumed_trace == reference_trace`
  element-for-element — no duplicated entry action, no skipped one, including across
  the invoke-bearing states (`submitting`, `resolving`, `arming`, `settling_*`,
  `submitting_slice`) where `restart_services=True` re-drives the invoke.

`from_snapshot(clock=)` (new in this round, #117) removes the need for the
`attach_clock` monkey-patch the earlier persistence harness carried — worth deleting
from `battle-5e07ba8/persistence/harness.py` when that file is next touched.

## 5. Sync engine — parity information only

`sync_parity.py`, same scripts, `SyncInterpreter`:

| | result |
|---|---|
| B1 | reaches `validated` — the `invoke` on `submitting` needs an async service |
| B2 | `closed` — full parity with async |
| B3 | `closing` — parity |
| B4 | `NotSupportedError: Service 'submit_both_legs' is async and not supported` |
| B5 | `NotSupportedError: Service 'submit_child' is async and not supported` |

Expected and correct: B4 and B5 invoke on their initial state, so the sync engine
refuses at `start()` with a clear, immediate error rather than a silent stall. **The
async engine is the only supported engine for the order path** — every one of these
five machines invokes a network-bound service, and three of them do so before the
first user event. Recommend the factory refuse to construct a `SyncInterpreter` for
any machine in the B1–B5 family.

## 6. Out of scope for this pass

Two items the brief lists live in machines outside B1–B5 and were not driven here:
**B17** live-enable gating on 2FA + pen-test flags (machine B17 `live_gate`), and the
**B18** `kill_switch` machine itself. What *was* tested is B18's mechanism as it
applies to the order path — `send_priority` against a saturated B1 inbox — and that
is where D-1's worst consequence showed up. **B13** reconnect/resync was covered
through its order-path surfaces (B1 `unknown`/`RECON_*`, B5 `paused → RESUME →
reconciling`), not as the `ws_conn` machine.

## 7. Actions

| # | Owner | Item |
|---|---|---|
| 1 | doc 28 | **Land `E50-T09` now.** D-1 is a Blocker and the "dead but harmless" note in §1.3b is factually wrong — correct that sentence in the same edit. `fix_contracts.py` + `catalogue-diff.json` are the mechanical diff; traces before/after are proved identical for everything except the fills the scaffolding was losing. |
| 2 | doc 28 | Replace B2's `raise_evaluate` with the `raise` built-in (D-3). |
| 3 | doc 28 | Add the missing fill handlers to B4 `completing` (D-5). |
| 4 | doc 28 | Rename `spawn_all_legs` / `spawn_entry_order` (D-2 workaround). |
| 5 | linter | **CV-LINT-XS15** — no action name beginning `spawn_`/`spawn_blocking_` unless a real library spawn. |
| 6 | linter | **CV-LINT-XS16** — every deferrable event must have a handler in a state reachable from every state that can defer it. |
| 7 | library | File D-2: `spawn_` prefix precedence over user actions + build-time diagnosis. |
| 8 | `cv.statechart` | Implement `protection_watchdog` per D-4. |
| 9 | `cv.statechart` | Factory refuses `SyncInterpreter` for the B1–B5 family. |
| 10 | — | Re-run this suite after each doc-28 edit: `CV_VARIANT=orig` must keep reproducing the failures until the edit lands, then flip. |

## 8. Files

```
contracts/
  charness.py                 stub-logic harness, trace plugin, snapshot compare
  fix_contracts.py            orig -> <B>.machine.json, logs catalogue-diff.json
  b1_order.py                 B1, 23 scenarios        (CV_VARIANT=orig|fixed)
  b2345.py                    B2-B5, 53 scenarios     (CV_VARIANT=orig|fixed)
  sync_parity.py              sync-engine parity, informational
  B{1..5}.orig.json           extracted verbatim from doc 28 sec B<n>.1
  B{1..5}.machine.json        corrected copies
  catalogue-diff.json         every edit, with its reason
  b1_order.{orig,fixed}.json  per-scenario results
  b2345.{orig,fixed}.json     per-scenario results
  sync_parity.json
  repro/
    r1_star_preempts_defer.py            D-1, 12-line minimal repro
    r2_spawn_prefix_steals_action_name.py D-2, 4-case table
```

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 CV_VARIANT=fixed python b1_order.py`
(and `b2345.py`) from `contracts/`, with the `3ed3099` venv. Each completes in
well under 120 s.
