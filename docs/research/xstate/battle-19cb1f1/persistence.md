# Battle track — PERSISTENCE @ `19cb1f1` (unreleased 0.8.1)

**Library:** `main` @ `19cb1f1` (“Merge pull request #211 from basiltt/fix/0.8.1-round9”); `__version__` still reports 0.8.0, so every result below keys on the **commit**.
**Scope:** round-9 fixes #203–#210 as they touch persistence, plus the standing persistence surface re-tested adversarially.
**Scripts:** `docs/research/xstate/battle-19cb1f1/persistence/*.py` — all STANDALONE (stdlib + `xstate_statemachine`), every one proved from the neutral cwd `C:/Users/basil` via `rb.sh`, which runs each script on **both** service kinds (`XS_SVC=async` / `XS_SVC=def`). Raw output in `out/*.txt` (async) and `out/*.DEF.txt` (`def`).

---

## 0. Bottom line

Round 9 delivered on the four fixes this track can see, and it delivered cleanly on **both** service kinds:

* **#204 (`statesToInvoke`) is correct across the persistence boundary.** A state entered and exited in one macrostep never submits its service, never persists as invoking, and is never resurrected by `restart_services=True`; a machine parked in a genuinely invoking state restores and arms **exactly once**. (`u3`, both kinds.)
* **#207 (stranded invocations) is exactly-once, correctly identified, and honestly persisted.** 200 concurrent rollback+onDone storms per lane: **200/200 machines reported, 0 duplicates, 0 wrong ids**, hook order is stably `on_event_dropped` → `on_invocation_stranded`, the blob names the invoking state, and a `restart_services=True` restore re-arms it. (`u5`.)
* **#208 (receipts) never reports `ok` over an illegal outcome and never manufactures an error over a legal one** across a 10-shape matrix, and no `ok` receipt was ever paired with an unrestorable blob. (`u6`.)
* **#206 lap parity is exact** (delay=0 and delay=1 ms both cut at 14 laps) and the cut is announced by `on_event_dropped('chain_budget')` **and** an ERROR log. (`u4b` P2.)
* The structural evidence is stronger than last round: **640 random machines × 4,063 snapshot attempts → 0 torn, 0 mismatch, 0 raw, 0 half-written** (`s5`); a 260 s / 200-machine soak with **17,238 chaos restores, 0 midstep, 0 mismatch, and 0 dropped of 133,800 external priority sends**; 5,000 corruption mutations → **0 raw leaks, 0 unsound accepts**, both kinds.

Three defects are filed, one of them new and one of them a straight regression:

* **D10-persistence-1 (High, NEW).** #203 closed `after`-provenance forgery in-process but **re-opened it on the persisted side by the same plaintext `"engine": true` flag** that #195 left open for `done`. A hand-written snapshot record fires a **60-second** timer instantly, under `strict` + `onUnhandled:"error"`. This is #203's own defect shape, moved one layer out.
* **D10-persistence-2 (Medium, NEW).** An **in-flight delayed self-`raise` is silently lost across a snapshot/restore**: it appears in neither `pending_events` nor `deferred`, and the restored machine never reaches the target the live machine reached. #206 made that send a debt of the arming step; the debt does not survive persistence.
* **D10-persistence-3 (Low, CHANGED from `D9-persistence-3`).** The priority lane is still not persisted as a lane, and #203 has now **narrowed the consequence into a second loss**: a genuinely fired `after` that was waiting in the lane is persisted, restored as a *public* `AfterEvent`, and then **refused by its own `after` transition** — it is not merely demoted, it is dropped.

`D9-persistence-1` (done-completion forgery) and `D9-persistence-2` (consistent `state_ids` forgery / v0 downgrade) are **STILL-PRESENT, unchanged and by documented design**.

**Verdict for adoption: PASS with obligations, unchanged in kind from last round but with one more item.** Nothing round 9 fixed was broken by persistence. What blocks unqualified adoption is still the trust boundary, now demonstrably wider by one event class (`after`), plus one genuine new data-loss bug (D10-persistence-2) that a wrapper must work around.

---

## 1. Method

| | |
|---|---|
| Interpreter | `Interpreter` (async) and `SyncInterpreter` where parity is the point |
| Service kinds | **every** result below was produced on both `def` and `async def` (`XS_SVC`); `out/*.DEF.txt` is the `def` lane |
| Neutral cwd | every script run from `C:/Users/basil` with the library on `PYTHONPATH` only — no script imports a sibling helper |
| Bounds | each script ≤ 120 s except: `s5` 320 machines/lane (≈ 170 s), `u5` 200 storms/lane (≈ 60 s), soak 260 s async / 140 s `def` |

**Reduced-from-brief parameters, all for the 20-minute wall-clock bound, stated rather than silently applied:**

* **Soak: 260 s (async) and 140 s (`def`), not 12 minutes.** Both lanes flat after warm-up; a 12-minute figure is not in evidence.
* **Livelock fuzz: 200 configs × 2 kinds × 2 engines, not 500.** Each of the 10 cells is already 20/20 and perfectly consistent (0 hangs, 0 silent, 0 mismatches on both lanes), so the extra 300 would add confidence, not information.
* **Property: 320 machines per lane (640 total), meeting the brief's "≥300".**
* `u5` ran 200 concurrent storms per lane as specified.

**Adaptations for superseded behaviour, recorded in the scripts themselves:**

* `n1_priority_lane_107.py` — #192 changed `_priority_queue` from `deque[Event]` to `deque[(Event, bool)]`. The script's hand-append and two reads were updated to the tuple shape; **without the edit the library's own `_snapshot_pending_events` raises `ValueError: too many values to unpack`** on any hand-populated lane. (The same crash occurs at `f28719c`, so this is not a round-9 regression — it is a pre-existing private-API shape change the prior report did not reach.)
* `u3_states_to_invoke.py` — on the `def` lane a plain-`def` service is the documented uninterruptible kind (#193): the entering step *awaits* it, so a machine can never be observed parked in an invoking state and a snapshot during the hold is correctly refused `SnapshotMidStepError`. The `def` lane therefore runs `hold=0` and the arm-once criterion becomes "the completed state restores **without** re-arming" (expected calls 0) — the same property from the other side of the same window.
* `u4_delayed_debt.py` / `u4b` — **`Interpreter.send()` has no `delay=` keyword.** #206's surface is the declarative `{"type": "raise", "params": {"event": ..., "delay": <ms>}}` action. A `send("EV", delay=0.3)` is silently accepted as **payload** and fires immediately (`u4b` P1: gap 0.2 ms vs the intended 300 ms), on both kinds. Noted as an API-ergonomics hazard, not filed as a defect — `send` documents `**payload`.

---

## 2. Prior defects: FIXED / STILL-PRESENT / CHANGED

### 2.1 Round-9 persistence defects (filed against `f28719c`)

| ID | Prior sev | Verdict on `19cb1f1` | Evidence |
|---|---|---|---|
| **D9-persistence-1 / R9-01** (a snapshot record self-asserts `"engine": true` and drives a real `onDone`) | High / Blocker | **STILL-PRESENT — unchanged, by documented design. WIDENED by #203.** | `s1_engine_forgery_roundtrip.py` → **VERDICT FAIL**, both kinds: forged record → `_EngineDone system=True`, `restored+started leaves=['sec.won'] mark=1 err=None`; genuine and forged records byte-identical. `s6_engine_minting_surface.py` → **6/8 vectors breach** (`engine_done`, `_EngineDone`, `type(genuine)(...)`, `_replace`, `pickle`, `deepcopy`); public `DoneEvent` and a user subclass remain correctly refused. #203 extends the same flag to `after` → **D10-persistence-1**. |
| **D9-persistence-2 / R9-05** (consistent `state_ids`/`configuration` forgery; v0 downgrade bypasses drift) | High | **STILL-PRESENT — unchanged, by documented design.** | `r2_readside_matrix.py` §2: 8/9 mutations refused `SnapshotCorruptError`; the one unsound cell is still `state_ids forged m.b` **with a matching `configuration`** → `ACCEPT ['m.b'] <- RELOCATED`. `r3_version_downgrade.py`: **3/3** downgrade forms still `ACCEPTED into DRIFTED machine: ['m.a'] -> after JUMP ['m.c']` under default `verify_machine_hash=True`. |
| **D9-persistence-3 / R9-10** (the #192 priority-lane provenance flag is not persisted) | Low | **CHANGED — still present, and the consequence is now worse.** | `s2_lane_provenance_roundtrip.py`, both kinds: order preserved (`['EXT','INB']` live → persisted → restored), records carry `['kind','payload','type']` only, **restored priority lane `[]`**. New in round 9: because #203 restores a flag-less `after` record as a *public* `AfterEvent`, a genuinely fired timer waiting in the lane is now **refused** rather than demoted — see **D10-persistence-3** and `n1` route A. |

### 2.2 Round-9 cross-track results landing on this track

| Claim | Verdict | Evidence |
|---|---|---|
| **#204** invoke arms after the eventless settle, both engines both kinds | **HOLDS across persistence** | `u3_states_to_invoke.py` **PASS both kinds** — see §3 U3 |
| **#203** only engine-minted `AfterEvent` drives an `after` | **HOLDS in-process; BREACHED across a snapshot** | `r10_doneevent_forgery.py` **PASS both kinds** (forged `AfterEvent` → `UnknownEventError`); `u2_after_forgery.py` **FAIL both kinds** → **D10-persistence-1** |
| **#206** delayed self-send is charged; lap parity with the zero-delay cycle | **HOLDS live; the in-flight debt is LOST across a snapshot** | `u4b` P2: delay=0 → **14 laps**, delay=1 ms → **14 laps**, both cut with `on_event_dropped('chain_budget')` + ERROR log. `u4` B → **D10-persistence-2** |
| **#207** `on_invocation_stranded` + `RunawayChainError.stranded` + dormancy API | **HOLDS, exactly-once, ids correct, persists honestly** | `u5_stranded_storm.py 200` **PASS both kinds** — see §3 U5 |
| **#208** receipts never `ok` over an illegal configuration | **HOLDS** | `u6_receipt_illegal.py` **PASS both kinds**, 10-shape matrix |
| **#209** lap parity across all three lanes | **HOLDS on this track's shapes** | `s7_chain_parity_settled.py` **PASS both kinds** — `rollback_ondone` now trips on **sync/def** too (was the one documented asymmetry at `f28719c`); `invoke_pingpong` 28 laps on all three lanes |

### 2.3 Regression check on previously-clean results (both service lanes)

| Script | Prior (`f28719c`) | Now (`19cb1f1`) |
|---|---|---|
| `p0_smoke.py` | v2, 16 keys | **unchanged**, both kinds |
| `t1_crashpoints.py` | 20/22 static | **20/22**, same 2 timer divergences, both kinds |
| `t3_probes.py` | all PASS | **all PASS**; 1 MB context round-trip 4.3 ms / 2.6 ms; child actors + bounded inbox PASS |
| `t4_receipts_provenance.py` | PASS | **PASS** — P12: v1 records restore `system=False`, no laundering |
| `t6_action_boundary.py` | 6/6 refused | **6/6 refused**, both kinds |
| `t7_rollback.py`, `n10_semantics_persist.py`, `m2_roundtrip_edges.py` | correct / 4-4 / 7-7 | **unchanged, PASS** |
| `n4_restart_timers.py` | 5/5 | **5/5**, both parallel regions re-armed |
| `n5_corrupt_fuzz.py` | 0 raw, 0 unsound | **5,000 mutations, 0 raw, 0 unsound**, both kinds |
| `n6_hostile_and_hooks.py` | redaction targeted | **`secrets LEAKED: []`**, `qty` still visible, API surface 13/13 |
| `q2`, `q3`, `q1b`, `s3_v1_restore.py`, `s4_start_hook_snapshot.py` | PASS | **PASS**, both kinds; every pre-`on_transition` window still `refused SnapshotMidStepError` |
| `d5_invoke_dormancy.py` | `restart_services=True` re-runs the service | **unchanged — CV-P05 stands** (calls 1 → 2) |
| `r5_children_timeout_def.py`, `s8_children_timeout_scale.py` | PASS | **PASS** — 50 async children start in 0.116 s at bound 0.2; `def` 5.03 s **with** the WARNING |
| `r11_determinism.py` | PASS | **PASS** — 50× per cell, 1 distinct blob, engine + kind parity, `PYTHONHASHSEED` sweep stable. **One caveat:** see §5 (a single non-reproducible `SnapshotMidStepError` after `await send()` returned) |
| `r12_livelock_fuzz.py 200 5` | PASS | **PASS both kinds** — 0 HANGS, 0 SILENT trips, 0 lap-count mismatches |
| `n1_priority_lane_107.py` | crashed (pre-existing) | **runs after the #192 lane-shape adaptation** — route A now regresses → D10-persistence-3 |
| `d3_torn_snapshot.py`, `d6_priority_lane.py`, `d3b_partial_parallel.py` | superseded by the mid-step guard | **still superseded**: each dies in its own decode after a correct `SnapshotMidStepError`; the refusal *is* the result |
| `n7_restore_event_type.py` | dies on first hostile input | **unchanged** — `restore_event({'type': 42})` → `SnapshotCorruptError` (correct; the script does not catch it) |

---

## 3. New attacks on this round's machinery

| # | Script | Attack | Result |
|---|---|---|---|
| **U1** | `u1_quiescent_window.py 400` | **Is the documented "snapshot once the step settles" window actually always open?** 400 iterations × 2 modes (`await send(ev)` and `await send(ev, wait=True)`) of send-then-`get_persisted_snapshot()` on a parallel machine with an invoke | **PASS both kinds. 0/400 refused in every cell** (1,600 attempts total). The advice the error message gives is sound |
| **U2** | `u2_after_forgery.py` | **#203 `after` provenance across the persistence boundary.** Seven vectors against a machine whose only timer is **60 000 ms**, under `strict:True` + `onUnhandled:"error"`: genuine record retargeted, hand record without the flag, hand record **with `"engine": true`**, `events._EngineAfter`, `type(genuine)(...)`, `pickle` of a genuine, and the public `AfterEvent` | **FAIL both kinds — `D10-persistence-1`.** 4 breaches: the `"engine": true` hand record and the three private-name vectors all restore as `_EngineAfter system=True` and **fire the 60-second timer instantly** (`leaves=['sec.fired'] fired=1 status=done`). The two public-class vectors are correctly refused `UnknownEventError` — #203's in-process half is genuinely closed |
| **U3** | `u3_states_to_invoke.py` | **#204 `statesToInvoke` across a snapshot.** (A) machine parked in an invoking state → snapshot → restore `restart_services=True` → **count service calls**; (B) a state rolled forward by an `always` in one macrostep — is its never-armed service persisted or resurrected?; (C) snapshot from `on_transition` into a state with **both** `always` and `invoke` | **PASS both kinds.** A: `pending_invocations=[PendingInvocation('arm.working','k')]`, restored calls **= 1**, exactly once. B: ghost service **0 calls live, 0 after restore**, blob `state_ids=['fwd.settled']`, `actors={}` — the roll-forward state is never persisted as invoking. C: the `on_transition` window is itself `refused SnapshotMidStepError`; from the first accepted window the restore arms **exactly once** |
| **U4** | `u4_delayed_debt.py` | **#206 delayed-self-`raise` debt across snapshot/restore.** (A) 1 ms self-cycle: does the restored machine stay bounded and lap-consistent?; (B) a 300 ms **in-flight** self-`raise`, snapshotted mid-flight; (D) the same for an external (caller-timer) delayed send | **FAIL both kinds on B — `D10-persistence-2`.** A: bounded at **13 laps live and 13 restored**, parity kept. B: the in-flight self-send is **ABSENT from the blob** (`pending_events=[] deferred=[]`) and the restored machine **stays in `a`** where the live one reached `b` — silently lost. D: an external delayed send survives, because it lives in the caller's own timer, not the machine — the asymmetry is the defect's shape |
| **U4b** | `u4b_delay_probes.py` | **P1** does `send(..., delay=D)` delay anything? **P2** how is the #206 delayed-cycle cut announced, and is lap parity with the zero-delay cycle exact? | **P1: `send(delay=)` is not an API** — the value lands in `**payload` and the event fires in **0.1–0.2 ms** against an intended 300 ms, both origins, both kinds (recorded in §1 as an ergonomics hazard, not filed). **P2: PASS** — `delay=0` → **14 laps**, `delay=1 ms` → **14 laps** (#206 promises ±1; observed 0), each cut carrying `on_event_dropped('PONG','chain_budget')` **and** the ERROR log `🛑 Exceeded 12 chained self-raised events` |
| **U5** | `u5_stranded_storm.py 200` | **#207 under 200 concurrent rollback+onDone storms per lane**, plus a chaos snapshot of the stranded machine and a `restart_services=True` restore | **PASS both kinds.** **200/200** machines reported a strand; **200** hook calls, **0 duplicates**, **0 wrong ids** (all `('st.starting','k')`); hook order stably `('dropped','stranded')`; `has_dormant_invocations=True`, `pending_invocations=[('st.starting','k')]`; the blob names `state_ids=['st.starting']` and restores with the invocation **re-armed once** (`service calls=1`, `still_dormant=False`); 2,200 ERROR-log lines name the stranded state |
| **U6** | `u6_receipt_illegal.py` | **#208 receipt matrix, 10 shapes** — 6 illegal (entry raises, entry raises under `rollback`, unhandled under `onUnhandled:error`, refused by `strict`, guard raises, chain trips) and 4 legal (plain, guarded, in-budget `raise` chain, invoke completion) — each via `await send(wait=True)`, then snapshot + restore the result | **PASS both kinds.** No illegal shape produced an `ok` receipt: entry-raises carries `error=RuntimeError`, `strict` raises `UnknownEventError` before any receipt, a raising guard returns `denied=True`. No legal shape was given a spurious error. **Every receipt's own blob restored `ok`** — no `ok`-receipt/unrestorable-blob pairing |
| **S5** | `s5_machine_property.py 320 11` | **Property, 320 random machines per lane** (1–3 parallel regions, nested compounds with `always`, `after` timers, invoked `def`/`async def` services, invoked child machines that half-write their own context), snapshot at every hook | **PASS both lanes. 640 machines / 4,063 attempts → 0 torn, 0 mismatch, 0 raw, 0 half-written, 0 raises.** Windows: `start` 640, `transition` 1,909, `unhandled` 874, `quiescent` 640; 2,786 correctly refused, 1,277 accepted |
| **R8** | `r8_soak_async.py` | **200-machine chaos soak**, parallel regions, snapshot/restore at quiescence, external `send(priority=True)` producer | **PASS both lanes.** async 262 s: 44,600 cycles, **17,238 snapshots / 17,238 restores, 0 midstep, 0 mismatch, 0 raw**, `ext_sent 133,800 / ext_dropped 0`, drop reasons `{}`. `def` 143 s: 39,000 cycles, 10,655 restores, **0 / 0 / 0**, `ext_sent 117,000 / 0 dropped`. Objects 20,725 → 21,526 on both lanes (bounded); RSS 29 → 209 MB async, 29 → 182 MB `def` |
| **R12** | `r12_livelock_fuzz.py 200 5` | **Livelock fuzz**, 5 shapes × {`def`, `async`} × both engines, 30 s watchdog | **PASS both kinds.** 200 configs, **0 HANGS, 0 SILENT trips, 0 lap-count mismatches**; all 10 cells 20/20 |

---

## 4. Defects

### D10-persistence-1 — a snapshot record can self-assert `after` provenance and fire a 60-second timer instantly (High, NEW)

**Repro:** `persistence/u2_after_forgery.py` (both kinds; `out/u2_after_forgery.txt`, `.DEF.txt`).
**Source:** `events.py:414` — `trusted = record.get("engine") is True`; `events.py:439-448` — `return engine_after(*aargs) if trusted else AfterEvent(*aargs)`; written at `events.py:331` (`if kind in ("done","error","after") and is_system_event(event): rec["engine"] = True`).

#203 was filed because "#195 minted `_EngineAfter` but selection still matched the public `AfterEvent` class, so a hand-built event **or a forged snapshot record** fired a 60-second timer instantly". The fix closed the in-process half — `r10_doneevent_forgery.py` now refuses a hand-built `AfterEvent` with `UnknownEventError` on both kinds — and left the **persisted** half open, by routing it through the same plaintext boolean #195 introduced for `done`:

```
  A genuine record, retargeted     _EngineAfter system=True  leaves=['sec.fired'] fired=1 status=done
  B hand record, no engine key     AfterEvent   system=False leaves=['sec.waiting'] raised=UnknownEventError
  C hand record, "engine": true    _EngineAfter system=True  leaves=['sec.fired'] fired=1 status=done   <-- DROVE the 60s after
  D events._EngineAfter(...)       _EngineAfter system=True  ... fired=1   <-- DROVE
  E type(genuine)(...)             _EngineAfter system=True  ... fired=1   <-- DROVE
  F pickle(genuine), retargeted    _EngineAfter system=True  ... fired=1   <-- DROVE
  G public AfterEvent(...)         AfterEvent   system=False raised=UnknownEventError
```

The machine is `strict: True`, `onUnhandled: "error"`, and its only timer is **60 000 ms**; vector C is four lines of JSON in the snapshot store. In OMS terms: a row edited in the snapshot table fires a "cancel-on-timeout" or "end-of-day flatten" timer that was supposed to be an hour away. Note that C is strictly *more* powerful than the `done` forgery of `D9-persistence-1`, because an `after` transition needs no matching in-flight invocation to exist — any state with a timer is reachable.

Vectors D/E/F are the same private-name surface `s6_engine_minting_surface.py` documents for `done`, now confirmed for `after`. The maintainer's stated boundary ("a caller who can write arbitrary snapshot records already controls `state_ids` and `context` outright") applies as before and is sound for *integrity*; as before it does not cover *capability*, since a forged timer **runs the transition's actions**.

**Severity: High** as a wrapper obligation. **Mitigation:** identical to D9-persistence-1 — MAC the blob, or strip `engine` from every record on read. One control closes D9-persistence-1, D9-persistence-2 and this together.

### D10-persistence-2 — an in-flight delayed self-`raise` is silently lost across a snapshot/restore (Medium, NEW)

**Repro:** `persistence/u4_delayed_debt.py` part B/C (both kinds; `out/u4_delayed_debt.txt`, `.DEF.txt`).
**Source:** `interpreter.py:1480-1497` (`_snapshot_pending_events` reads only `_priority_queue` + the inbox deque — a timer that has been *armed but not yet fired* is in neither).

#206 made `{"type": "raise", "params": {"event": "PONG", "delay": 300}}` a **debt of the arming step**: the engine owes that firing and charges it as engine work. A snapshot taken inside the delay window discharges the debt silently — the blob records nothing, and the restored machine simply never receives the event:

```
  live in-window: states=['debt.a'] laps=1
  blob pending_events=[] deferred=[]        <- the in-flight self-send is ABSENT
  live after the delay elapsed: states=['debt.b']   (the live send DID fire)
  restored after 600 ms:       states=['debt.a']   <- LOST
```

Unlike a fired-but-unprocessed `after` (which #107 *does* persist, via the priority lane), an armed-and-pending delayed `raise` has no representation in the snapshot at all — there is no key it could be written to. The consequence is a **state machine that resumes into a state it can never leave**: `a`'s only exit was the delayed `PONG` its own entry action armed, and re-entering `a` on restore does not re-run entry. This is not a trust-boundary issue; it is data loss on the honest path, and it is invisible — no warning, no drop hook, no error.

Note the asymmetry that confirms the diagnosis: part D shows an **external** delayed send (the caller's own `asyncio` timer) survives perfectly, because it never lived inside the interpreter.

**Severity: Medium** — it needs a crash inside a delay window, but OMS charts use delayed self-sends for exactly the timeouts that matter (retry back-off, quote expiry, cancel-on-stale). **Wrapper obligation:** never rely on a delayed `raise` for a deadline that must survive a restart; model it as an `after` on the state (which *is* persisted and re-armed), or re-arm it explicitly in a post-restore pass.

### D10-persistence-3 — the priority lane is still not persisted, and a genuinely fired `after` is now *refused* rather than demoted (Low, CHANGED from D9-persistence-3)

**Repro:** `persistence/s2_lane_provenance_roundtrip.py` part A and `persistence/n1_priority_lane_107.py` route A (both kinds).
**Source:** `interpreter.py:356` (`_priority_queue: deque[Tuple[AnyEvent, bool]]`), `interpreter.py:1497` (`return [ev for ev, _ in self._priority_queue] + inbox` — the flag is dropped), `interpreter.py:1499-1500` (`_enqueue_restored` → `_put_inbox`), plus `events.py:414` for the new half.

The lane itself is unchanged from last round: order is preserved, records carry `['kind','payload','type']` and no provenance field, and the restored `_priority_queue` is `[]` — an external `send(priority=True)` returns as ordinary inbox traffic.

What **changed** in round 9 is the fate of a *fired `after`* sitting in that lane. #107 deliberately persists it ("a FIRED `after` timer waits in the priority lane… omitting it lost the deadline across a snapshot with no trace"), and `persist_event` does write it — but only records an `"engine": true` flag for an event that was engine-minted *in that process*. `n1` route A puts a fired `AfterEvent` in the lane, snapshots, and restores:

```
  SNAPSHOT pending_events = ['after.1000.lanes.waiting'] kinds=['after']   <- persisted, as #107 intends
  restored: states=['lanes.waiting'] fired=0
  VERDICT replayed on restore = False       (was True at 6db65d8, cec108b, 221ce7c)
```

The event round-trips, is restored as a **public** `AfterEvent`, and is then **refused by its own `after` transition** under #203's provenance rule. Before round 9 the deadline was merely demoted; now it is dropped. The regression is only reachable through a hand-populated lane in this probe, so the observed instance is partly an artefact — but the same code path serves a genuinely fired timer, and D10-persistence-1 shows the *only* thing separating the two outcomes is a plaintext boolean the writer controls. That is the exact trade-off #203 made, recorded here so it is not mistaken for a clean win.

**Severity: Low** (needs a crash in the window between a timer firing and its processing). **Wrapper obligation:** unchanged from CV — re-derive deadlines from context after a restore rather than trusting a restored queue.

---

## 5. Not covered / caveats

* **12-minute soak** — run at **260 s (async)** and **140 s (`def`)** for the 20-minute task bound. Both lanes are flat after warm-up (objects 20,725 → 21,526 on both), but a 12-minute figure is not in evidence. RSS climbs to ~209 MB async / ~182 MB `def` across 200 concurrent machines and ~17 k restores; bounded within the window observed, not proven asymptotically.
* **Livelock fuzz at 500 configs** — run at **200** (10 cells × 20). Every cell is internally consistent; the extra 300 would add confidence, not information.
* **One non-reproducible `SnapshotMidStepError`.** During the sweep, a single `r11_determinism.py` run on the `def` lane raised `SnapshotMidStepError` from `get_persisted_snapshot()` *after* `await send()` had returned — i.e. in the window the library's own error message tells callers to use. It has not recurred: 11 subsequent serial runs, 4 concurrent runs, and `u1_quiescent_window.py`'s **1,600 send-then-snapshot attempts across both kinds and both `wait` modes** are all clean (0 refusals). **Not filed** — one observation, not reproduced, and this track's standard is reproduce-before-you-count. It is recorded because it is the visible edge of **R9-08** (`send(wait=True)` resolving at a torn instant, filed by the fuzz track), and because if it is real the caller has no later window to retry from. A wrapper should treat `SnapshotMidStepError` from a post-`send` snapshot as retryable rather than fatal.
* **`SyncInterpreter` coverage** is limited to the parity checks the prior scripts already carry (`r11`, `r12`, `s7`, `s4`). The new U-series attacks (`u2`–`u6`) run on the async engine only; #203/#204/#207/#208 are pinned on both engines by the library's own `tests/test_round9_findings.py`, and this track tested the *persistence* consequence, which is engine-independent by construction (one blob format).
* **`send(delay=)` is not an API** and the ergonomics hazard it creates (silently becoming payload) is recorded in §1, not filed as a defect — `send` documents `**payload`.
* **Cross-track surfaces not re-run here:** the 5 k/s external producer against a single machine, the full SCXML §3.13 eventless-selection matrix, the hash-seed/determinism sweep beyond `r11`, and the redaction matrix beyond `n6` belong to the concurrency / semantics / observability tracks.
* `d3_torn_snapshot.py`, `d6_priority_lane.py` and `d3b_partial_parallel.py` no longer produce measurements — the mid-step guard refuses before they can capture and they die in their own JSON decode. Retained for provenance; superseded by `s5` and `u1`.

---

## 6. Verdict

**Round 9 is a real improvement on this track, and none of its fixes was undone by persistence.** #204 is correct across the boundary in the sharpest form available — a state rolled forward in one macrostep is never persisted as invoking and is never resurrected by `restart_services=True`, while a genuinely invoking state restores and arms **exactly once**, on both service kinds. #207 is the standout: 400 concurrent storms across the two lanes produced **400 reports, 0 duplicates, 0 wrong ids**, a stable hook ordering, an honest blob, and a correct re-arm on restore. #208 held across all ten receipt shapes. #209's remaining asymmetry from last round (`rollback_ondone` not tripping on sync/`def`) is **closed**. The structural evidence is the strongest this track has recorded: 0 torn blobs in 4,063 attempts over 640 random machines, ~28 k chaos restores with 0 mismatches, and **0 dropped of 250,800 external priority sends** across the two soaks.

**What is new is one genuine bug and one widened boundary.** `D10-persistence-2` is the bug: an armed-but-unfired delayed self-`raise` has no representation in the snapshot, so a restore silently drops a deadline the machine owed itself, and can leave the machine in a state with no remaining exit. It is invisible — no hook, no warning — which is what makes it worth a Medium rather than a Low. `D10-persistence-1` is the boundary: #203 fixed `after` forgery in-process and re-opened it on the persisted side through the same plaintext `"engine": true` flag, where it is *more* dangerous than the `done` case it inherits from, because firing a timer needs no in-flight invocation to impersonate.

**The adoption picture is unchanged in kind and one item longer.** `from_snapshot` treats the blob as trusted input and says so; under that model the snapshot store is inside the TCB, and a writer there can now relocate the machine (`state_ids`, v0 downgrade), fabricate a service completion **and** fire any timer in the chart. That is a deployment constraint, not a library choice — but nothing in the API will enforce it.

**Wrapper obligations (this track, `19cb1f1`):**
1. **Authenticate every blob** — HMAC over the serialised snapshot with a process-held key, verified before `from_snapshot`. This single control closes D10-persistence-1, D9-persistence-1 and D9-persistence-2 together.
2. **Pin `version` and `verify_machine_hash=True`**, and reject any payload declaring a `version` below the one this build writes, so the v0 bypass is unreachable. (#205's `minimum_version` / `expected_machine_hash` now make this a one-liner.)
3. **Never model a restart-critical deadline as a delayed `raise`** (D10-persistence-2). Use an `after` on the state, which is persisted and re-armed, or re-derive and re-arm deadlines from context in a post-restore pass.
4. **Re-issue, do not rely on, anything that was queued** — external priority sends and fired-but-unprocessed timers alike (D10-persistence-3).
5. **Carry an idempotency key on every invoked service** — `restart_services=True` re-runs it (CV-P05, unchanged, re-confirmed in `d5` and `u3`/`u5`).
6. **Treat `SnapshotMidStepError` from a post-`send` snapshot as retryable**, not fatal (§5 caveat).

**Track verdict: PASS with obligations** — one new Medium library defect (`D10-persistence-2`), one new High wrapper obligation (`D10-persistence-1`), no new blocker.
