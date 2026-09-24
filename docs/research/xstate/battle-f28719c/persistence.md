# Battle track — PERSISTENCE @ `f28719c` (unreleased 0.8.1)

**Library:** `main` @ `f28719c` (“Merge pull request #202 from basiltt/fix/0.8.1-round8”); `__version__` still reports 0.8.0, so every result below keys on the **commit**.
**Scope:** round-8 fixes #192–#201 (+ reopened #181, #186) as they touch persistence, plus the standing persistence surface.
**Scripts:** `docs/research/xstate/battle-f28719c/persistence/*.py` — all STANDALONE (stdlib + `xstate_statemachine`), run via `run.sh` (async services) and `rund.sh` (`XS_SVC=def`). Raw output in `out/`.

---

## 0. Bottom line

Round 8 closed the persistence defects that were filed against it. Four of the five prior persistence defects are **FIXED** (`D8-persistence-1` engine-completion forgery, `-3` `children_timeout`, `-4` chain parity — now partially, `-5` `state_ids: []`), and every round-5/6/7 regression still holds: 0 torn blobs, 0 raw leaks, 0 round-trip mismatches across 320 random machines × both service kinds, and a 200-machine / 4-minute soak with **0 dropped external priority sends**.

Two things did **not** move, and one new one is worth naming:

* **D9-persistence-1 (High).** The `"engine": true` flag is a *plaintext, self-asserted* trust bit inside the snapshot. A hand-written `pending_events` record carrying it restores as a genuine engine completion and **drives a real `onDone`** while the real service is still running — the exact end-to-end breach #195 was filed to close, moved from the in-process surface to the persisted one. The library documents this as the intended trust boundary; whether that is acceptable depends entirely on whether the snapshot store is inside the trust perimeter. For an OMS it is not, unqualified.
* **D9-persistence-2 (Medium, carried).** `state_ids` still outranks `configuration` when the two are *consistently* forged together, and the v0 / absent-`version` downgrade still bypasses the drift check. Both are documented, both are reachable by a caller who can edit the blob.
* **D9-persistence-3 (Low, NEW).** The priority lane’s #192 provenance flag is **not persisted**. A pending external `send(priority=True)` survives a round-trip only as ordinary inbox traffic; on the restored machine it has lost both its lane and its shed-immunity.

**Verdict for adoption:** persistence is sound against *corruption* and *accident* and is now demonstrably free of torn writes. It is **not** an authenticity boundary. A wrapper must treat a snapshot blob as trusted input — sign it, or store it where only the process can write it.

---

## 1. Method

| | |
|---|---|
| Interpreter | `Interpreter` (async) and `SyncInterpreter` where parity is the point |
| Service kinds | **every** service/action result below was produced on both `def` and `async def` (`XS_SVC`) |
| Bounds | each script ≤ 120 s except the soak (240 s, reduced from the brief’s 12 min — **stated**) and the 320-machine property (≈ 350 s/lane); livelock fuzz at 200 configs (reduced from 500, **stated**) |
| Determinism | `r11_determinism.py` (50× identical traces, both engines, both kinds, hash-seed sweep) |

Reduced-from-brief parameters, all for the 20-minute wall-clock bound: soak 240 s not 720 s; livelock fuzz 200 configs not 500; `t2_property.py` 250 hypothesis examples not 2,000; property machines 320 not "≥300" per lane (met).

---

## 2. Prior defects: FIXED / STILL-PRESENT / CHANGED

### 2.1 Round-8 persistence defects

| ID | Prior sev | Verdict on `f28719c` | Evidence |
|---|---|---|---|
| **D8-persistence-1** (`DoneEvent`/`AfterEvent` carry no provenance, exempt from `strict`; #195) | High | **FIXED in-process — RE-OPENS across persistence.** See `D9-persistence-1`. | `r10_doneevent_forgery.py` → **VERDICT PASS**, both kinds (was FAIL, 6 failures): a user-built `DoneEvent` now raises `UnknownEventError` under `strict`. `s6_engine_minting_surface.py`: public `DoneEvent` and a user subclass of it are both refused end-to-end. But `s1_engine_forgery_roundtrip.py` → **FAIL** both kinds. |
| **D8-persistence-2** (drift bypass by version downgrade; #185) | High | **STILL-PRESENT — by documented design.** | `r3_version_downgrade.py`: 3/3 downgrade forms (`version=0`+hash removed / `version` key removed / `version=0`+`hash=None`) still **ACCEPTED into the DRIFTED machine**, `['m.a'] → JUMP → ['m.c']`, under default `verify_machine_hash=True`. `check_identity` (`persistence.py:344-352`) returns early for `not versioned`. |
| **D8-persistence-3** (`children_timeout` no-op against `def` child entry; #194/#181) | Medium | **FIXED** | `r5_children_timeout_def.py` → **VERDICT PASS** (was FAIL): the WARNING now fires at every bound with the `def`-cannot-be-pre-empted explanation. `s8_children_timeout_scale.py` (50+50 children): async 50 children start in **0.122 s** at `bound=0.2` — per child, not 50·D; `def` lane 5.03 s **with** the WARNING; mixed lane likewise. |
| **D8-persistence-4** (service-kind chain parity false for `invoke_pingpong` / `rollback_ondone`; #179/#201) | Medium | **CHANGED — mostly FIXED, one documented asymmetry remains.** | `r12_livelock_fuzz.py 200 5`: **0 lap-count mismatches, 0 HANGS, 0 SILENT trips** (was 50 mismatches); `invoke_pingpong` and `rollback_ondone` now trip in the `async` lane too. `s7_chain_parity_settled.py`: `invoke_pingpong` **28 laps on all three lanes**. `rollback_ondone`: both async lanes trip, **sync/def does not** — exactly what #201’s pin says is *not* promised. `r13_chain_parity_min.py` still prints FAIL: it samples at a fixed deadline, before the async lanes settle; **superseded by `s7`**. |
| **D8-persistence-5** (`state_ids: []` beside a populated `configuration`; #198/#186) | Low | **FIXED for the filed mutation.** Residue → `D9-persistence-2`. | `r2_readside_matrix.py` part 2: `state_ids emptied` → **`SnapshotCorruptError`** (was ACCEPT/relocate), as do `empty`, `key removed`, `superset`, `contradict`, `leaf stripped`. The remaining unsound cell is `state_ids forged m.b` *with a matching `configuration`* — a consistent forgery, not a contradiction. |

### 2.2 Round-8 cross-track defects landing on this track

| ID | Verdict | Evidence |
|---|---|---|
| **R8-09 / #199** (`get_persisted_snapshot()` from `on_interpreter_start` returns a torn blob, both engines) | **FIXED** | `s4_start_hook_snapshot.py`, both kinds, **both engines**: `on_interpreter_start` → `refused SnapshotMidStepError`, `entry@start` → `refused`, `on_transition(init)` → `accepted ['w.r1.a','w.r2.c']`. 0 write-accepted/read-refused blobs. `q1b_start_entry_window_min.py` → PASS. |
| **R8-08 / #198** | see `D8-persistence-5` | |

### 2.3 Regression check on previously-clean results (both service lanes)

| Script | Prior (`6db65d8`) | Now (`f28719c`) | `def` lane |
|---|---|---|---|
| `p0_smoke.py` | v2, 16 keys | **unchanged** | — |
| `t1_crashpoints.py` | 20/22 static | **20/22**, same 2 timer divergences | **identical** |
| `t2_property.py` | — | **250 cases, 0 failing** (MAXEX reduced) | — |
| `t3_probes.py` | P1/P5/P6/P8/P9/P10 PASS | **all PASS** (1 MB context round-trip 825 ms / 339 ms) | — |
| `t4_receipts_provenance.py` | PASS | **PASS** | — |
| `t6_action_boundary.py` | 6/6 refused | **6/6 refused** | **identical** |
| `t7_rollback.py` | correct | **unchanged** | — |
| `d2_after_timer_lost.py` | `restart_services` re-arms | **unchanged** (documented) | — |
| `d3_torn_snapshot.py`, `d6_priority_lane.py` | mid-step refused | **`SnapshotMidStepError`**, as designed | — |
| `d5_invoke_dormancy.py` | `restart_services=True` re-runs the service | **unchanged — CV-P05 stands** (calls 1 → 2) | **confirmed** |
| `q2_readside_gaps.py` | PASS | **PASS** | — |
| `q3_resume_parity_sentinel.py` | PASS | **PASS**, no `__slots__` aliasing | — |
| `n4_restart_timers.py` | 5/5 | **5/5** | — |
| `n5_corrupt_fuzz.py` | 0 raw, 0 unsound | **0 raw, 0 unsound** | **0 raw, 0 unsound** |
| `n6_hostile_and_hooks.py` | redaction targeted | **`secrets LEAKED: []`**, API surface PASS | — |
| `n7_restore_event_type.py` | dies on first hostile input | **unchanged** | — |
| `n10_semantics_persist.py` | 4/4 PASS | **4/4 PASS** | — |
| `m2_roundtrip_edges.py` | 7/7 | **7/7 PASS** | — |
| `n1_priority_lane_107.py`, `r7_child_actor_restore.py` | PASS | **unchanged** | — |
| `r11_determinism.py` | PASS | **PASS** (50×, both engines, both kinds, hash-seed sweep) | — |
| `d3b_partial_parallel.py` | — | **superseded**: the probe now never captures a blob (mid-step refusal) and dies in its own JSON decode — the refusal *is* the result | — |

---

## 3. New attacks on this round's machinery

| # | Script | Attack | Result |
|---|---|---|---|
| S1 | `s1_engine_forgery_roundtrip.py` | **`"engine": true` forgery in a persisted record.** Take an honest snapshot, rewrite one `pending_events` record into `{"type":"done.invoke.k","kind":"done","data":{...},"src":"k","engine":true}`, restore under `strict:True` + `onUnhandled:"error"` while the real service is still running | **FAIL, both kinds — `D9-persistence-1`.** Restores as `_EngineDone`, `is_system_event=True`, and **drives the real `onDone`**: `leaves=['sec.won'] mark=1 err=None`. Control without the flag → `DoneEvent`, `system=False` |
| S2 | `s2_lane_provenance_roundtrip.py` | **Priority-lane provenance across a round-trip.** Snapshot with a pending external `send(priority=True)` beside an inbox event; restore and inspect the lane. Plus: does the chain budget survive a restore? | **PASS on the safety criteria, one gap — `D9-persistence-3`.** Order preserved (`EXT, INB` live → persisted → restored). Records carry `['kind','payload','type']` only: **no lane/provenance field**; the restored `_priority_queue` is **empty** — the external priority send returns as ordinary inbox traffic. Budget: restored machine did not run away |
| S3 | `s3_v1_restore.py` | **v1 (0.8.0-written) restore.** `version:1` with both fields, `state_ids`-only, empty `configuration`, and v0 legacy; plus a v1 completion record with no `kind`/`engine` | **PASS.** v1-both-fields ACCEPT; v1 `state_ids`-only and v1 empty-`configuration` → `SnapshotCorruptError` (#198); **v0 legacy still ACCEPT**. A pre-#195 `done.invoke` record restores as a plain `Event`, `system=False` — no provenance laundering from old data |
| S4 | `s4_start_hook_snapshot.py` | **Snapshot from `on_interpreter_start`** (#199), `entry@start`, and `on_transition(init)` — both engines, both kinds, parallel machine with an invoke | **PASS.** Every early window `refused SnapshotMidStepError`; the first *accepted* window is `on_transition(init)` and its blob reads back correctly. **0 write-accepted / read-refused** |
| S5 | `s5_machine_property.py 320 11` | **Property, ≥300 random machines per lane**: 1–3 parallel regions, nested compounds with `always`, `after` timers, invoked `def`/`async def` services **and invoked child machines whose entry action half-writes its own context**. Snapshot at every hook; 5 accept criteria | **PASS both lanes.** async: 320 machines / **2,059 attempts**, 1,423 refused, 636 accepted → **0 torn, 0 mismatch, 0 raw, 0 half-written child, 0 raises**. def: 1,958 attempts, 639 accepted → same zeroes. Windows incl. `start` 320, `transition` 990, `unhandled` 429, `quiescent` 320 |
| S6 | `s6_engine_minting_surface.py` | **Eight ways to mint an engine completion**: `events.engine_done`, `events._EngineDone`, `type(genuine)(...)`, public `DoneEvent`, a user subclass of it, `genuine._replace()`, `pickle` round-trip, `deepcopy` — each run **end-to-end** under `strict` + `onUnhandled:"error"` | **The #195 boundary is exactly "do not import a private name".** Public `DoneEvent` and a user subclass are **refused** (`UnknownEventError`) — the filed defect is closed. The private names `_EngineDone` / `engine_done` / `_ENGINE_MINTED_TYPES` are plain module attributes: importing one, or `type(captured)(...)`, mints a working forgery that drives `onDone`. `_replace` / `pickle` / `deepcopy` of a genuine event **preserve** provenance (intended, #85). `__slots__ = ()` on `_EngineDone`, confirmed |
| S7 | `s7_chain_parity_settled.py` | **Chain parity, settled rather than sampled**: poll until the cycle stops turning (≤20 s) instead of reading at a fixed deadline | **Resolves `D8-persistence-4`.** `invoke_pingpong`: **28 laps on sync/def, async/def and async/async** — full parity. `rollback_ondone`: both async lanes trip; **sync/def does not** — the asymmetry #201 explicitly declines to promise |
| S8 | `s8_children_timeout_scale.py` | **`children_timeout` with 50 `def` + 50 `async` children**, hold 0.1 s, bound 0.2 s: is `start()` bounded per child or by N·D, and does the WARNING always fire? | **PASS.** 50 async children: `start()` **0.122 s** at bound 0.2 — per child, not 5 s. 50 `def` children: 5.03 s (bound cannot pre-empt a blocking `def` on the loop thread) **with the WARNING**. Mixed 50+50: 5.04 s, WARNING present. Control `bound=None`: 0.108 s |
| R8 | `r8_soak_async.py 240 200` | **200-machine soak, async services**, parallel regions, chaos snapshot/restore at quiescence, external `send(priority=True)` producer | **PASS.** 243 s, 19,552 cycles, **13,806 snapshots / 13,806 restores, 0 midstep, 0 round-trip mismatch, 0 raw exceptions**; `ext_sent 58,656 / ext_dropped 0`, drop reasons `{}`. RSS 30.5 → 119.7 MB, objects 20,700 → 21,501 (bounded, no leak) |
| R12 | `r12_livelock_fuzz.py 200 5` | **Livelock fuzz**, 5 shapes × {def, async} × both engines, 30 s watchdog | **PASS.** 200 configs, **0 HANGS, 0 SILENT trips, 0 lap-count mismatches** (was 50). `always_cycle` and `sendto_selfloop` trip on both kinds; `invoke_pingpong` and `rollback_ondone` show the engine-level asymmetry S7 explains |
| R11 | `r11_determinism.py` | 50× identical traces, both engines, both kinds, incl. trip laps + `PYTHONHASHSEED` sweep | **PASS** |

---

## 4. Defects

### D9-persistence-1 — a snapshot record can self-assert engine provenance and drive a real `onDone` (High, NEW / re-opened surface)

**Repro:** `s1_engine_forgery_roundtrip.py` (both kinds; `out/s1_engine_forgery_roundtrip.txt`, `.DEF.txt`).
**Source:** `events.py:414` — `trusted = record.get("engine") is True`; `events.py:429` — `return engine_done(*args) if trusted else DoneEvent(*args)`.

#195 closed the in-process forgery by minting private subclasses, then re-opened it on the persisted side by introducing a **plaintext boolean that anyone who can write the blob can set**. The flag is not derived from anything — not the machine hash (which covers the *machine*, not the payload), not a MAC, not a nonce.

```
  forged record  -> _EngineDone  system=True
  no-flag record -> DoneEvent    system=False
  restored+started leaves=['sec.won'] mark=1 err=None
```

The machine is `strict: True`, `onUnhandled: "error"`, and its genuine 5-second service is **still running** when the forged completion moves it to `won` and runs the `won` entry action. In OMS terms: a row edited in the snapshot table fabricates a fill for an order that is still working.

The library states this is the intended boundary (`events.py:403-412`: "A caller who can write arbitrary snapshot records already controls `state_ids` and `context` outright (#185), so this is the correct trust boundary"). That argument is sound for *integrity* but not for *capability*: `state_ids` relocates the machine to a state a reader can audit, whereas a forged completion also **fires `onDone` actions** — side effects — and does so while the real invocation is outstanding, producing a duplicate when the genuine completion lands.

**Severity: High** as a wrapper obligation, not as a library bug under the maintainer's stated model. **Wrapper obligation:** sign or MAC every persisted blob, or strip `engine` from every record on read and accept the loss of genuine in-flight completions.

### D9-persistence-2 — consistent `state_ids`/`configuration` forgery and the v0 drift bypass (Medium, CARRIED)

**Repro:** `r2_readside_matrix.py` part 2 (`state_ids forged m.b -> ACCEPT ['m.b'] <- RELOCATED`); `r3_version_downgrade.py` (3/3 downgrade forms accepted into the drifted machine).
**Source:** `persistence.py:344-352` (`versioned = bool(version)`; `if snap_hash is None and not versioned: return`), `base_interpreter.py:1725`.

#198 closed the *asymmetric* mutations. What remains is the symmetric one — edit both fields consistently — and the v0 downgrade, which by design disables drift checking entirely: set `version: 0`, drop `machine_hash`, and a blob restores into a **structurally different machine**, after which an event only the new machine declares moves it (`['m.a'] -> JUMP -> ['m.c']`). Both are documented; both are one `json.loads`/`json.dumps` away for anyone with write access to the store. Same mitigation as D9-persistence-1.

### D9-persistence-3 — the #192 priority-lane provenance flag is not persisted (Low, NEW)

**Repro:** `s2_lane_provenance_roundtrip.py` part A, both kinds.
**Source:** `interpreter.py:355` (`_priority_queue: deque[Tuple[AnyEvent, bool]]`), `interpreter.py:1488` (`return [ev for ev, _ in self._priority_queue] + inbox` — the flag is dropped), `interpreter.py:1490-1491` (`_enqueue_restored` -> `_put_inbox`).

The whole point of #192 is that a lane item carries whether it is external or self-generated, so the shed site never destroys an external `send(priority=True)`. A snapshot **flattens** the lane and the restore path puts every record on the **inbox**:

```
  live pending order: ['EXT', 'INB']
  record keys       : [['kind','payload','type'], ['kind','payload','type']]
  restored priority lane: []
  => the external priority send came back as ORDINARY inbox traffic
```

Order is preserved, so nothing is lost or reordered — which is why this is **Low**. What is lost is the *guarantee*: the restored `EXT` no longer jumps the inbox, and on a machine whose first restored step opens a chain it is no longer distinguishable, by the shed site, from work the machine generated itself. A crash-restart during a burst therefore silently downgrades exactly the events #180/#192 were written to protect.

---

## 5. Not covered

- **12-minute soak** — run at **240 s** (`r8_soak_async.py 240 200`) for the 20-minute task bound. Nothing in the 4-minute window trends badly (RSS and object count both flat after warm-up), but a 12-minute figure is not in evidence.
- **Livelock fuzz at 500 configs** — run at **200**; the per-shape counts are already 20 per cell and perfectly consistent, so the extra 300 would add confidence, not information.
- **10 k/s external priority producer** — the soak's producer sustained ~240 ext-sends/s across 200 machines (58,656 / 243 s) with 0 dropped; a dedicated 10 k/s single-machine producer belongs to the **concurrency** track and was not re-run here.
- **200-concurrent `def`-service arm-then-rollback**, **RAISE loop-side exactly-once**, the full **SCXML §3.13 eventless-selection matrix**, the **guard-crash/denied/deferred receipt matrix**, and the **hook matrix incl. shed-by-provenance drops / settle-trip per step** — semantics and observability tracks; this track verified only the persistence-visible consequences (`n10_semantics_persist.py` 4/4, `t4_receipts_provenance.py`, `n6_hostile_and_hooks.py`).
- **`t2_property.py`** at its full 2,000 hypothesis examples (ran 250).
- **`d3b_partial_parallel.py`** no longer produces a measurement: the mid-step guard refuses before it can capture, so its own JSON decode raises. Retained for provenance; superseded by `s5`.

---

## 6. Verdict

**Round 8 delivered on this track.** Every persistence defect filed against `6db65d8` that the round undertook to fix is fixed and stays fixed under adversarial re-test: the engine-completion forgery is closed in-process, `children_timeout` is per child and always warns, `state_ids: []` is refused, the `on_interpreter_start` tear is gone, and the chain-parity gap is closed for `invoke_pingpong` with the one remaining asymmetry explicitly pinned rather than papered over. The structural evidence is strong — **0 torn blobs in 4,017 snapshot attempts across 640 random machines and two service kinds**, 13,806 chaos restores in the soak with 0 mismatches, and 0 dropped external priority sends.

**What blocks unqualified adoption is not a bug, it is a boundary.** `from_snapshot` treats the blob as trusted input, and says so. Under that model a snapshot store is part of the TCB: anyone who can write a row can relocate the machine (`state_ids`, v0 downgrade) **and fabricate a service completion with side effects** (`"engine": true`). For a financial OMS that is a deployment constraint, not a library choice — but it must be written down and enforced by the wrapper, because nothing in the API will enforce it.

**Recommended wrapper obligations (this track):**
1. **Authenticate every blob** — HMAC over the serialised snapshot with a process-held key; verify before `from_snapshot`. This single control closes D9-persistence-1 and -2 together.
2. **Pin `version` and `verify_machine_hash=True`**; reject any payload whose declared `version` is below the one this build writes, so the v0 bypass is unreachable.
3. **Never snapshot before `on_transition(init)`** — the library now refuses, so this is defence in depth.
4. **Carry an idempotency key on every invoked service** — `restart_services=True` re-runs it (CV-P05, unchanged).
5. **Re-issue, do not rely on, external priority sends after a restore** (D9-persistence-3): treat a restored queue as ordinary inbox traffic.

**Track verdict: PASS with three carried obligations.** No new blocking library defect on the persistence surface at `f28719c`.
