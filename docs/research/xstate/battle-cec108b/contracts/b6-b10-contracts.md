# Contract machines end-to-end — B6, B7, B8, B9, B10 (round 6, `cec108b`)

**Library:** `_ref/xstate-statemachine` @ `main` = **cec108b** ("Merge PR #164 from basiltt/fix/0.8.1-round5"; unreleased 0.8.1, `__version__` still reports `0.8.0` — keyed on commit).
**Contracts:** the corrected catalogue JSON from `battle-3ed3099/contracts/<B>.fixed.machine.json` where present, else `<B>.machine.json` — copied here as `<B>.machine.json`. All five are CD-01-clean (no `on["*"]` scaffolding).
**Engine:** async `Interpreter` primary, `SyncInterpreter` for parity information. `SimulatedClock` throughout, bounded inbox `OverflowPolicy.RAISE`, stub `MachineLogic(strict=True)`.
**Date:** 2026-09-20. Scripts in this directory (`c1`–`c11`, `repro/f1`–`f9`).

---

## 0. Headline

| | |
|---|---|
| Builds unmodified from the corrected catalogue JSON | **5 / 5** — zero `InvalidConfigError`, zero `ImplementationMissingError` |
| Policy block honoured as written | **5 / 5** (see §1 for the one read-back gap) |
| Invariant / scenario checks (`c2`) | **55 run — 53 PASS, 2 FAIL** |
| Round-5 cross-contract analogues (`c10`) | **7 / 7 PASS** |
| Snapshot/restore at every macrostep boundary (`c3`) | **31 / 31 MATCH**; **0** spurious `SnapshotMidStepError` at quiescence |
| Cross-machine reconnect / divergence (`c7`) | **4 / 4 PASS**, byte-identical to the `3ed3099` baseline |
| **LIBRARY defects** | **1** (LD-03, medium — engine asymmetry) + **1 carried, now FIXED** (LD-01) |
| **OUR-CONTRACT defects** | **1** (CD-03, high — B8 `naked`⇄`verifying` livelock) |
| **Needs wrapper** | **2** (W-04 denial-vs-defer, W-05 CV-C32 stays) |

### What changed since `3ed3099`

- **LD-01 is FIXED.** #152 landed: a raising guard on an `invoke.onDone` no longer aborts the whole selection pass. The unguarded fallback candidate *is* taken, so B8's `verifying` now falls through to `naked` instead of stranding. The old "silent permanent strand in the safety machine" ship-blocker is closed (`repro/f4`).
- **`Receipt.denied` (#153) works** and is a genuine discriminator (`repro/f5`, `repro/f7`).
- **Two new findings**, both surfaced by the *same* B8 shape that LD-01 used to mask: CD-03 and LD-03. Fixing LD-01 did not create them — it made them reachable. The strand became a spin.

---

## 1. Build + policy read-back (`c1_build.py` → `c1_build.json`)

All five build and start clean.

| | id | build | actions/guards/services/events | start configuration |
|---|---|---|---|---|
| B6 | `twap` | OK | 12 / 7 / 4 / 9 | `twap.armed` |
| B7 | `chase` | OK | 11 / 8 / 4 / 10 | `chase.working` |
| B8 | `position_protection` | OK | 10 / 5 / 4 / 8 | `sl.flat` + `watchdog.idle` |
| B9 | `rule_instance` | OK | 27 / 9 / 2 / 15 | `rule_instance.draft` |
| B10 | `alert` | OK | 7 / 3 / 1 / 7 | `alert.armed` |

`actionErrorPolicy`, `onUnhandled`, `guardErrorPolicy`, `strictTargets` and `logic.strict` all read back verbatim off `MachineNode`. `"*" in known_events` is **False** on all five, so `strict: true` is live — the CD-01 fix holds on this commit.

**Read-back gap (informational):** `spawnBlockingTimeout` reads `<missing>` off the built `MachineNode` on all five. The key is accepted at `create_machine` without error but is not exposed as an attribute, so a contract cannot *assert* its own spawn timeout post-build. Not a behavioural defect in this group (no contract here spawns), but it defeats a conformance lint that wants to verify the §1.3b block by read-back. Track as a low-severity observability gap.

---

## 2. Invariants (`c2_invariants.py` → `c2.out`) — 53 / 55

B6 (10/10), B7 (10/10), B9 (16/16), B10 (7/7) are **all PASS**, and each result matches the `3ed3099` run. The catalogue's lifecycle invariants are enforced by the engine as written on these four machines:

- **B1-analogue** (fill during submit): `USER_PAUSE` into `submitting_slice` → `Receipt.deferred=True`, `on_unhandled_event(disposition="deferred")`, replayed into `twap.paused` on `done.invoke`. **PASS.**
- **B4-analogue** (late leg fill in `completing`): amend `onError` = order-not-found-after-fill → `completing`, not a failure. **PASS.**
- **B18-analogue** (`send_priority` preemption): 80 queued `TRIGGER`s, then `send_priority("KILL_SWITCH")` — the kill lands first. **PASS.**
- **B19-analogue** (divergence): `reconcile_children` failure → terminal `twap.failed`. **PASS.**
- Bounded inbox: 200 concurrent sends into a 4-deep inbox → `QueueOverflowError`. **PASS.**
- `actionErrorPolicy: "fail"` on B8: raising `bump_attach_attempts` → `status="error"`, configuration rolled back, `TransitionFailedError` retained. **PASS.**

Both failures are on **B8** and are analysed below. Neither is a regression in the library; one is our contract's shape and one is an engine asymmetry that the LD-01 fix exposed.

### 2.1 `INV-B8-b raising guard surfaces` — FAIL, but the verdict is stale

The check asserts the `send(wait=True)` **call site raises**. It does not (`call_raised: NO-RAISE`) — but on `cec108b` the receipt now carries the exception:

```
receipt: changed=False  deferred=False  denied=True  error=RuntimeError
interpreter.last_transition_ok = False
interpreter.last_error = RuntimeError('guard-boom:tightens_only')
```

A crashed guard **is** distinguishable from a denial *if the caller reads `Receipt.error`*. The transition is correctly not taken. The assertion in `c2_invariants.py` predates `Receipt.error`/`denied` and is too strict; the *contract* obligation ("a crashed guard is NOT a denial") is met on the `wait=True` path. **Reclassified as a harness-assertion defect, not a library defect** — but see W-04, because `denied=True` is set in *both* cases.

### 2.2 `SL_DEADLINE during attaching pre-empts into naked` — FAIL, and it is real (CD-03)

The check reads the configuration two settles after `SL_DEADLINE` and finds `sl.verifying`, not `sl.naked`. A minimal 4-state repro (`repro/f1_sl_deadline_preempt.py`, no catalogue JSON) shows the **pre-emption itself is correct**: with an in-flight gated `attach`, `SL_DEADLINE` moves `attaching → naked` immediately, `changed=True`, and the late service completion does not resurrect `verifying`.

What the B8 check actually caught is that the machine **does not stay** in `naked`. See CD-03.

---

## 3. CD-03 (OUR-CONTRACT, HIGH) — B8 `naked` ⇄ `verifying` is an unbounded invoke-driven livelock

**Reproduced:** `repro/f2_naked_verify_livelock.py`, `repro/f8_watchdog_miss_concurrency.py`.

The catalogue gives B8 two invoking states that target each other:

```
naked     .invoke(attach_fallback_sl).onDone      -> verifying
verifying .invoke(read_position_sl)  .onDone[guard exchange_reports_sl] -> protected
                                     .onDone[fallback]                  -> naked
```

When the fallback attach *succeeds* but the exchange still does not report an SL — the precise real-world case of a broker accepting the order and not attaching it — the two states hand off to each other for ever. Measured over an 8 s budget:

```
laps (attach_fallback_sl invocations): 4209     (523 / s)
raise_critical_alert fired:            4209     <-- P1 pager, 523 times a second
status:                                running
interpreter.error:                     None
last_transition_ok:                    True
last_error:                            None
on_event_dropped:                      []
```

**Every documented health signal reads clean.** `last_transition_ok` is `True` because every individual lap *is* a successful transition. There is no budget trip on the async engine (see LD-03). The failure mode is an alert storm plus a hot spin, not a stall — the opposite of the LD-01 strand it replaced, and much louder downstream.

This is **our contract's defect, not the library's**: the engine is faithfully executing a cycle we wrote. Two independent confirmations that the library is not at fault:

- The escape hatch works. `POSITION_FLAT` is declared on `naked`, and both `send()` (2 attempts — the first lands while in `verifying` and is correctly *deferred*, the second applies) and `send_priority()` (1 attempt) break the cycle and reach `sl.flat` (`repro/f3_escape_hatch.py`). The machine stays fully responsive while spinning.
- No event is lost. 8 concurrent `WATCHDOG_MISS` produce exactly 8 `naked` entries when the heal guard is `True` (`repro/f8`). The earlier "miss lost under concurrency" reading was a harness bug — it read the final leaf, which is legitimately `protected` after the machine re-heals. Corrected in `c10`; now 7/7 PASS.

**Catalogue action (blocking for B8):** `naked` must not re-enter `verifying` unconditionally on a fallback-attach success. Required changes:
1. Add a **bounded** fallback-attempt counter (`fallback_attempts` + `fallback_attempts_left` guard) on `naked.invoke.onDone`, exactly as `attaching.onError` already does with `attach_attempts_left`.
2. On exhaustion, route to the existing **`naked_unrecoverable`** state, which already pages the owner. It is currently only reachable via `attach_fallback_sl` *erroring* — a successful-but-useless attach can never reach it, which is the hole.
3. Make `raise_critical_alert` edge-triggered (dedupe on `naked_since`), so a re-entry storm cannot become a pager storm. Entry actions fire on every entry by design; the de-duplication is the contract's job.

**Generalise it:** add **`CV-LINT-XS16` — no two invoking states may target each other on their success paths without a bounded counter on at least one edge.** This shape is statically detectable in the catalogue JSON and B8 is unlikely to be the only instance.

---

## 4. LD-03 (LIBRARY, MEDIUM) — the chain budget does not apply to engine events on the async engine, but does on the sync engine

**Reproduced:** `repro/f9_sync_budget_signal.py` vs `repro/f2_naked_verify_livelock.py`; `c11_sync_parity.py`.

The *same* B8 cycle, the *same* script, the two engines:

| | async `Interpreter` | `SyncInterpreter` |
|---|---|---|
| laps before stopping | **unbounded** (4209 in 8 s, still going) | **500**, then returns |
| `Receipt.error` | n/a (engine-driven) | **`RunawayChainError`** |
| `on_event_dropped` | `[]` | `[("done.invoke.ver", "chain_budget")]` |
| `last_transition_ok` | `True` | `False` |
| configuration after | legal, 1 leaf/region | legal, 1 leaf/region |
| still responsive | yes | yes |

**Root cause**, `interpreter.py:1424` — the async budget check is explicitly skipped for system events:

```python
if self._raise_depth > limit and not is_system_event(event):
```

The comment cites **#120**: an engine completion "is finished work and cannot self-feed; dropping it strands the machine in the invoking state. *The sync engine spares these by construction; mirror that here.*" The premise is false in the presence of a two-state invoke cycle — `done.invoke.*` events **can** self-feed indirectly, via a second state whose own invoke completes back into the first. And the parenthetical is backwards on this commit: the sync engine does **not** spare them; it charges them and trips `RunawayChainError` at 500 laps. The mirroring is inverted.

This is a genuine **parity defect**, and it is the one case where the sync engine gives the *safer* answer: it is the only configuration in which CD-03 produced any signal at all.

**Severity: MEDIUM, not HIGH.** #120's concern is legitimate — charging `done.invoke` unconditionally would strand a machine that is merely slow — and the async behaviour is not *incorrect* so much as *unbounded*. The library does not owe us cycle detection. But the asymmetry should be resolved deliberately rather than by accident, and the #120 comment should be corrected either way.

**Suggested library fix (for upstream, not applied here):** keep the system-event exemption for the *drop* decision, but still **count** system events and emit a distinct observable signal (a `on_event_dropped(reason=...)`-style hook or a `chain_budget_exceeded` warning on `last_error`) when the depth passes the limit without dropping. That preserves #120 — nothing is stranded — while making an engine-driven livelock visible, which is exactly what CD-03 needed and did not get.

**Until then this is NEEDS-WRAPPER**, because the async engine is our primary: `cv.statechart` must supply its own detector (see W-03 from the previous round, now upgraded — a stall detector is not enough, it must also detect a *spin*: transitions advancing with no progress in a liveness variable).

---

## 5. W-04 (NEEDS-WRAPPER) — `denied` and `deferred` are both true for a guard-refused event, and the refusal is replayed later

**Reproduced:** `repro/f5_denied_conflation.py`, `repro/f6_denied_defer_buffer.py`, `repro/f7_disposition_precedence.py`.

Two distinct issues with #153's `Receipt.denied` under the catalogue-mandated `onUnhandled: "defer"`.

**(a) `denied=True` does not mean "denied".** Under `guardErrorPolicy: "raise"`, a guard that *crashed* also sets `denied=True`:

| case | `changed` | `deferred` | `denied` | `error` |
|---|---|---|---|---|
| guard returned `False` (true denial) | False | **True** | True | `None` |
| guard **raised** (not a denial) | False | False | True | `RuntimeError` |
| no handler declared | False | False | **False** | `None` |

`denied` alone re-merges the two cases #153 exists to separate. The **correct discriminator is the pair** `(denied, error)`: a true denial is `denied=True and error is None`. This must be written into the wrapper and into §1.3b; any code that branches on `Receipt.denied` by itself is wrong on the order path. Same on both engines (`c11_sync_parity.json`).

**(b) A denial is *stored*, and applies later against a changed world.** `onUnhandled: "defer"` takes precedence over the `guard_denied` disposition:

| `onUnhandled` | `on_unhandled_event` disposition | receipt |
|---|---|---|
| `"defer"` (mandated on the order path) | **`"deferred"`** | `deferred=True, denied=True` |
| `"ignore"` | `"guard_denied"` | `deferred=False, denied=True` |
| `"error"` | `"errored"` | `deferred=False, denied=True` |

So on the order path the `guard_denied` disposition is **never observed** — it is shadowed by `deferred`. Worse, `repro/f6` shows the stored denial is not inert:

```
3x TIGHTEN_SL denied by tightens_only=False   -> deferred_count = 3
flip tightens_only -> True; send WATCHDOG_MISS (forces a config change)
set_trading_stop invocations: 0 before -> 3 after
```

Three amendments a risk guard **refused** were replayed and executed later, unprompted, because the configuration changed and the guard's answer had moved. On an order path that is a stale-order hazard: a refused amend is not a queued amend.

**Wrapper requirement (CV-C25):** on the order path, a guard denial must be terminal for that event. Either (i) `@cv_guard` distinguishes "refuse and discard" from "not applicable here" and the wrapper drains the defer buffer of denied events at the end of the macrostep, or (ii) the order path moves to `onUnhandled: "ignore"` on states whose handlers are guard-gated and relies on `Receipt.denied`. (i) is preferred — it keeps defer for genuinely-unhandled events, which B1/B4 need. **This is a wrapper obligation, not a library defect:** the library's precedence is defensible and documented; it is simply the wrong default for us.

---

## 6. W-05 — CV-C32 (all services `async def`) must STAY; `service_executor` does not replace it

**Reproduced:** `c9_cvc32_executor.py` → `c9_cvc32_executor.json`. This was an explicit question for this round.

#149 moved plain-`def` services off the event loop onto a `service_executor`. It does fix loop starvation — but not inbox latency.

| service | executor | heartbeat gap during a 0.5 s service | **`send(PING, wait=True)` latency** | PING action ran |
|---|---|---|---|---|
| `async def` | default | 0.033 s | **0.001 s** | yes |
| plain `def` | default (owned pool) | 0.033 s | **0.441 s** | **no** |
| plain `def` | custom `ThreadPoolExecutor` | 0.034 s | **0.437 s** | **no** |

The asyncio loop keeps turning (heartbeat gaps are identical — that is #149 working as advertised), but **"the entering macrostep awaits the result"**, so the machine's own inbox is blocked for the service's full duration. An event sent during a 0.5 s plain-`def` service waits 440 ms for its receipt and its action does not run until the service completes. A custom executor changes nothing — the wait is in the macrostep, not the pool.

Ordering also still differs by service kind: `send(GO); send(CANCEL)` into an invoking state gives `x.bad` (cancel wins) with `async def` and `x.ok` (service wins) with plain `def`. #116's ordering guarantee holds, but it is a *different* guarantee from the async one, so the two kinds are not interchangeable.

**Verdict: CV-C32 stays as written.** On the order path a 440 ms inbox stall is a missed cancel. Additional data point: `SyncInterpreter` raises `NotSupportedError` for an `async def` service, so the sync engine **cannot** satisfy CV-C32 at all — sync parity runs in this group had to substitute plain-`def` services (`c11_sync_parity.py:sync_logic`). CV-C32 is therefore implicitly an *async-engine-only* constraint; §1.3b should say so.

---

## 7. Snapshot / restore at every macrostep boundary (`c3_snapshot.py` → `c3.out`)

Snapshot at quiescence between **every** macrostep, restore into a fresh interpreter, resume, compare states *and* the accumulated action trace.

```
B6 {'MATCH': 7}   B7 {'MATCH': 7}   B8 {'MATCH': 6}   B9 {'MATCH': 7}   B10 {'MATCH': 4}
SnapshotMidStepError at a quiescent point: NONE
```

**31 / 31 MATCH.** Identical to the `3ed3099` result. The #142/#143 legality tightening (exactly one active leaf per region, both directions) did **not** produce any false positive on the one parallel machine in this group (B8) — including immediately after a 16-event concurrent storm across both regions (`c10`, B11-analogue check 3, snapshot `OK`). `has_dormant_timers` is `False` and `pending_invocations()` is empty at every crashpoint, and the deferred buffer round-trips.

## 8. Cross-machine + sync parity (`c7_crossmachine_and_sync.py` → `c7.out`)

4 / 4 PASS, and the JSON is **byte-identical to the `3ed3099` baseline** (diffed directly):

- B13-analogue reconnect: `WS_DISCONNECT` (freeze) → `paused`; `RESUME` → `reconciling` running `rearm_deadlines_from_context` **then** `reconcile_children` → `armed`. No shortcut.
- Freeze policy off: `WS_DISCONNECT` held (`deferred=1`, disposition `deferred`), not dropped.
- B19-analogue divergence → terminal `twap.failed`.
- INV-B6-b: restore re-registers no deadlines spontaneously; `has_dormant_timers=False`.

Sync parity on B6/B9/B10: identical final configuration and action trace. The only parity *difference* found anywhere in this group is LD-03 (§4), and it favours the sync engine.

## 9. Round-5 cross-contract analogues (`c10_analogues.py`) — 7 / 7 PASS

| Check | Verdict |
|---|---|
| B11-analogue: 16 concurrent hazards keep both B8 regions legal (1 leaf each) | PASS |
| B11-analogue: no `WATCHDOG_MISS` lost — 8 concurrent misses → 8 `naked` entries | PASS |
| B11-analogue: snapshot at quiescence after the storm, no `SnapshotMidStepError` | PASS |
| B19-analogue: 20× arm/disarm flap leaves a single legal leaf | PASS |
| B19-analogue: `stale_lockout` survives the flap; 5 unelevated rearms do not escape | PASS |
| B16-analogue: elevated `HUMAN_REARM` is the one exit | PASS |
| B16-analogue: elevation cleared → 3 rearms all refused, machine stays `kill_switched` | PASS |

B17's 2FA + pen-test gate shape is B9's two-flag `always` chain, verified in both deny and raise polarity in `c2` (checks 43–44). B18's mechanism is `send_priority`, verified in `c2` check 47.

---

## 10. Findings register

| ID | Class | Sev | Summary | Status |
|---|---|---|---|---|
| **LD-01** | LIBRARY | was HIGH | raising guard on `invoke.onDone` aborted the whole selection pass → silent permanent strand in B8 | **FIXED on `cec108b`** by #152; fallback candidate is taken, B8 falls through to `naked` |
| **LD-03** | LIBRARY | MED | chain budget exempts system events on the async engine but charges them on sync; an invoke-driven livelock is unbounded and silent on async, `RunawayChainError` on sync. #120's "the sync engine spares these" is inverted | **OPEN** — needs wrapper; suggest upstream count-without-dropping |
| **CD-03** | OUR-CONTRACT | HIGH | B8 `naked` ⇄ `verifying` unbounded cycle when fallback attach succeeds but the exchange reports no SL: 523 laps/s, 523 P1 alerts/s, every health signal clean | **OPEN, blocking for B8** — bound the fallback counter → `naked_unrecoverable`; dedupe the alert; add `CV-LINT-XS16` |
| **W-04** | NEEDS-WRAPPER | HIGH | `denied=True` also set for a *crashed* guard (discriminator must be `denied and error is None`); and under mandated `onUnhandled:"defer"` a denial is deferred and **replayed later** — 3 refused amends executed after the guard flipped | **OPEN** — CV-C25 |
| **W-05** | NEEDS-WRAPPER | MED | `service_executor` (#149) does **not** retire CV-C32: a plain-`def` service still blocks the machine's inbox for its full duration (441 ms vs 1 ms) and has different completion ordering; `SyncInterpreter` cannot run `async def` at all | **CV-C32 STAYS**, scoped async-engine-only |
| **OBS-01** | LIBRARY | LOW | `spawnBlockingTimeout` accepted by `create_machine` but not exposed on `MachineNode`; the §1.3b block cannot be fully verified by read-back | OPEN, informational |
| **HD-01** | HARNESS | — | `c2`'s `INV-B8-b raising guard` asserts a call-site raise; on `cec108b` the signal is `Receipt.error` + `last_error`. Assertion is stale, contract obligation is met | Documented, not re-scored |

## 11. Verdict for this group

**B6, B7, B9 and B10 are fit on `cec108b` as written.** Every catalogue invariant is enforced by the engine, snapshot/restore is trace-exact at all 31 macrostep boundaries, the defer buffer is durable across restore, the priority lane pre-empts a loaded inbox, and the bounded inbox raises. No regression against `3ed3099` anywhere in this group.

**B8 remains the only ship-blocker, but the blocker has moved and the library is no longer the cause.** The previous round's LD-01 — a silent permanent strand in the safety machine — is genuinely fixed by #152. What that fix revealed is that our own B8 contract contains an unbounded invoke cycle (CD-03) which the async engine will run for ever without a single health signal (LD-03). The safety invariant itself is still strong: `protected` remains unreachable without a confirmed SL. It is again the *liveness* half that fails — no longer as a stall, now as a spin.

**Ship gate for B8:** CD-03 fixed in the catalogue, W-04 and the upgraded spin-detector wrapper in place. LD-03 should be raised upstream but is wrapper-coverable and is not itself a blocker.

The most useful result of the round is the pattern: **fixing a strand turns it into a spin.** Both are liveness failures and the library reports neither on the async path. Any adoption gate that checks only "is the machine stuck" will pass CD-03 at 523 alerts a second. The detector must watch a progress variable, not a transition counter.

---

## 12. Scripts

| File | Purpose |
|---|---|
| `c1_build.py` | build + policy read-back + start smoke (→ `c1_build.json`) |
| `c2_invariants.py` | 55 invariant/scenario checks (→ `c2.out`) |
| `c3_snapshot.py` | snapshot/restore at every macrostep boundary (→ `c3.out`) |
| `c7_crossmachine_and_sync.py` | reconnect/resync, divergence, sync parity (→ `c7.out`) |
| `c9_cvc32_executor.py` | W-05 — `service_executor` vs CV-C32 (→ `.json`) |
| `c10_analogues.py` | B11/B16/B19 cross-contract analogues (→ `.json`) |
| `c11_sync_parity.py` | sync parity for this round's findings (→ `.json`) |
| `repro/f1_sl_deadline_preempt.py` | minimal 4-state: `SL_DEADLINE` pre-emption is correct |
| `repro/f2_naked_verify_livelock.py` | **CD-03** — 4209 laps / 8 s, all signals clean |
| `repro/f3_escape_hatch.py` | CD-03 — `POSITION_FLAT` / `send_priority` do break the cycle |
| `repro/f4_guard_raise_sinks.py` | **LD-01 re-test** — fallback now taken, fix confirmed |
| `repro/f5_denied_conflation.py` | **W-04(a)** — crashed guard also reads `denied=True` |
| `repro/f6_denied_defer_buffer.py` | **W-04(b)** — 3 refused amends replayed after the guard flipped |
| `repro/f7_disposition_precedence.py` | W-04 — `defer` shadows the `guard_denied` disposition |
| `repro/f8_watchdog_miss_concurrency.py` | no miss lost; corrects a harness misreading |
| `repro/f9_sync_budget_signal.py` | **LD-03** — sync trips `RunawayChainError` at 500 laps |

Library source untouched; no git run in the project repo; all scripts inside the 120 s bound.
