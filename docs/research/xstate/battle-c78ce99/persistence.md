# Battle track — PERSISTENCE @ `c78ce99` (unreleased 0.8.1)

**Library:** `main` @ `c78ce99` ("Merge pull request #217 from basiltt/fix/0.8.1-round10"); `__version__` still reports 0.8.0, so every result keys on the **commit**.
**Scope:** round-10 fixes #212–#216 as they touch persistence, plus the standing persistence surface re-attacked.
**Scripts:** `docs/research/xstate/battle-c78ce99/persistence/*.py` — all STANDALONE (stdlib + `xstate_statemachine`), every one proved from the neutral cwd `<home>` via `runall.sh`, which runs each on **both** service kinds (`XS_SVC=async` / `XS_SVC=def`). Raw output in `out/*.txt` (async) and `out/*.DEF.txt` (`def`).

---

## 0. Bottom line

Round 10 delivers on the two semantic reversals, and delivers on both service kinds and both engines:

* **#212 is correct and complete.** A `raise(delay=)` self-send is now a timer with exactly the `after` rule. 200 machines × 1 ms ping-pong for 10 s: **0 `RunawayChainError`, 0 `chain_budget` drops, 200/200 still beating**, on both kinds (`x4`). Zero-delay cycles still trip, including in a chart that *also* arms a delayed send (`x4/B`). A 500-config × 2-kind × 2-engine livelock fuzz with the new oracle is **2000/2000 clean** (`x6`). The measured `raise(delay=)` beat rate is indistinguishable from the `after:` spelling at every rung (`x5`) — parity, not approximation.
* **#213 v3 round-trip is exact.** 300 random machines × 2 kinds, armed self-sends snapshotted at a random point inside the delay: **600/600** carried the right `remaining_ms` (±0.5 ms) and `send_id`, fired **not early, not late, exactly once** after the remainder (`x1`). 200 concurrent restores behave identically (`x9/B`).
* **#214 restore-`strict` and lane restore work.** A fired timer restores ahead of the inbox (`x3/A`); an unknown restored user event is refused, recorded in `last_error`, and dropped (`x3/D`).
* **#215 start()-descent-settle is bounded** — 100 concurrent starts of an `always` + descent-`raise` chart return in 0.01 s with identical lap counts (`x9/A`).
* **#216 top-level key checking is complete**: 47/47 policy-key mutations warned, 47/47 raised under `strict_config=True`, and the "did you mean" hint named the right key **47/47** (`x7/A`).
* **Determinism is total:** 50× traces on both engines, both kinds, including a `scheduled_sends` restore, produce **one digest — the same digest on both engines** — and it is invariant across `PYTHONHASHSEED` (`x11`).

Three new defects, one of them the most serious thing this track has found in several rounds:

* **D11-persistence-1 (High) — an unbounded `_timer_handles` leak on the `raise(delay=)` path**, i.e. on the very heartbeat shape #212 was fixed to make legal. Exactly **1.00 dead handle retained per beat, for ever**: 463 MB in 24 s at 200 machines (`x13`, `x14`), both engines. #212 made self-paced heartbeats legal; this makes running one a memory leak.
* **D11-persistence-2 (High) — the v2-downgrade minting vector is real.** A forged `"version": 2` blob mints an engine `after` that fires a 600 s timer instantly under `strict: True` + `onUnhandled: "error"`, and an engine `done.invoke` that drives `onDone` — both refused at `"version": 3` (`x2`). This is the question the round was set to answer.
* **D11-persistence-3 (Medium) — #216 is top-level only**; a `states.<id>` key typo silently deletes `entry` / `after` / `always` / `invoke` with `strictConfig: true` AND `strict_config=True` both set (`x7/B`, `x8`).

Plus one **contract gap** (not a defect): `x10` shows the #215 lap-parity claim does **not** generalise — async runs ~2× the sync laps on a neighbouring shape.

**Verdict: ADOPT with constraints** (§6).

---

## 1. Prior-defect table (round-9 persistence findings re-run at `c78ce99`)

Every script from `battle-19cb1f1/persistence/` re-run on both kinds. Status legend: **FIXED** / **STILL-PRESENT** / **CHANGED** / **SUPERSEDED**.

| Prior defect | Script (both kinds) | Status @ c78ce99 | Evidence |
|---|---|---|---|
| **R10-04** armed delayed self-`raise` lost across snapshot | `u4/B`, `x1` | **FIXED** | v3 `scheduled_sends` carries it; 600/600 random machines round-trip the remaining delay exactly (`out/x1_*.txt`) |
| **R10-05a** restore bypasses `strict` | `x3/D` | **FIXED** | unknown restored user event refused, `last_error=UnknownEventError`, not enqueued |
| **R10-05b** restore drops lane provenance | `x3/A`, `s2` | **FIXED** | `lane: "priority"` round-trips; timer restores ahead of inbox |
| **R10-05c** 0.8.0 `after` record silently refused (migration cliff) | `x2/A` | **FIXED — and this is the new attack surface** | v2 `done`/`error`/`after` upcast to `_Engine*`, `system=True`. Fixes the cliff, opens **D11-persistence-2** |
| **#206** delayed self-ping-pong must trip | `u4/A` | **SUPERSEDED** (by #212) | `u4/A` reports `HANG laps=781` and `VERDICT: FAIL` — that FAIL **is** the new correct behaviour. Replacement assertion written and passing: `x15` |
| **#203** `after` provenance gate | `u2` | **STILL-PRESENT, as designed** | `u2` "BREACHES" C/D/E/F are all cases where the attacker supplies `"engine": true` or imports the private class — the documented trust boundary, not a defect (`from_snapshot` docstring). Vector B and G correctly refused |
| **#204** `statesToInvoke` across the boundary | `u3` | **FIXED** (holds) | exit 0 both kinds |
| **#207** stranded invocations | `u5` | **FIXED** (holds) | exit 0 both kinds |
| **#208** receipts never success-shaped over an illegal config | `u6` | **FIXED** (holds) | exit 0 both kinds |
| **#209/#215** lap parity | `s7`, `r13`, `x10` | **CHANGED** | pinned shape S1 now PASSES all 3 lanes at limits 1..25; a neighbouring shape S2 does not — see **§4 contract gap** |
| **#107** priority lane persisted | `n1/A` | **CHANGED** | lane still persisted; route A's "replayed on restore = False" is the #214 `strict`/provenance gate acting on a **hand-injected** `AfterEvent` with no `engine` flag — correct now, was a gap before |
| **R10-09** `SnapshotMidStepError` reports `child=False` | `t5` | **STILL-PRESENT** | `t5` exit 1, unchanged; Low/attribution-only, as classified in round 10 |
| mid-step snapshot refusal | `d6`, `n1/B`, `u1` | **STILL-PRESENT, as designed** | `SnapshotMidStepError` raised — the documented contract; `d6` exits 1 because the script does not catch it |
| `restore_event` type guard (#158) | `n7` | **STILL-PRESENT, as designed** | exit 1 = `SnapshotCorruptError` on `type: 42`, which is the assertion |
| strict refuses hand-built `done.invoke` at the call site | `r10_forgery_*` | **STILL-PRESENT, as designed** | exit 1 = `UnknownEventError` raised, which is the point |
| `n5_corrupt_fuzz`, `t2`, `t8` | — | **TIMEOUT (124)** at the 115 s bound | long-running property scripts; not a hang — they are budget-bounded by the harness. Re-covered by `x1` (300-machine property) and `x6` |

**No prior persistence defect regressed.** The one FAIL that is a real behaviour change (`u4/A`) is the intended #212 reversal, and §2.7 carries the replacement assertion.

---

## 2. New attacks

### 2.1 `x1_v3_roundtrip_property.py` — v3 round-trip property, 300 random machines × 2 kinds — **PASS**

Random state counts, 1–3 concurrently armed `raise(delay=)` self-sends, delays from {1, 5, 17, 50, 120, 333, 1000} ms, optional `send_id`, driven by a `SimulatedClock`. Each machine is snapshotted at a *random* fraction (0–90 %) of its delay, restored onto a fresh clock, and then advanced to **just short of** the remainder and **past** it.

```
X1 kind=async N=300 OK=300      VERDICT PASS
X1 kind=def   N=300 OK=300      VERDICT PASS
```

All 600 blobs were `version: 3`, `remaining_ms` within 0.5 ms of exact, `send_id` present when armed with one, and **no** machine fired at `start()`, fired early, missed, or double-fired.

### 2.2 `x2_v2_upcast_minting.py` — the v2 minting vector — **DEFECT (D11-persistence-2)**

The upcast matrix is as documented:

```
v2 done    -> engine_flag=True  class=_EngineDone   system=True
v2 error   -> engine_flag=True  class=_EngineError  system=True
v2 after   -> engine_flag=True  class=_EngineAfter  system=True
v2 event   -> engine_flag=None  class=Event         system=False
v2 system  -> engine_flag=None  class=Event         system=True
```

But `version` is a field of the payload the attacker writes, and `machine_hash` is a fingerprint the attacker can compute from the public chart (the library says so in `from_snapshot`'s docstring). Setting `"version": 2` therefore mints:

```
v2 forged, strict+onUnhandled=error: fired=1 states=['vict.expired'] -> MINTED=YES
v3 forged (control)                : fired=0 states=['vict.waiting'] -> MINTED=no
v2 forged, lax machine             : fired=1                          -> MINTED=YES
v2 forged done.invoke              : n=1 states=['dv.ok']             -> MINTED=YES
v3 forged done.invoke (control)    : n=0 states=['dv.work']           -> MINTED=no
```

Identical on both kinds. A 600 000 ms timer fires **instantly**, and an `onDone` fires for an invocation that never ran — the exact behaviours #203 exists to forbid and that v3 correctly forbids. Mitigation exists and works (`part F`): `from_snapshot(minimum_version=3)` refuses the v2 payload with `SnapshotVersionError`.

### 2.3 `x3_lane_hash_strict.py` — lane ordering, hash coverage, restore-strict — **PASS with two documented notes**

* **A** timer ahead of inbox on restore even when the inbox record is listed first: `order = ['after.600000.ord.waiting', 'USER']` — **PASS**.
* **B** a forged `"lane": "priority"` on a *user* record reorders the restored inbox but **cannot mint** an engine event — ordering, not provenance. Documented, not a defect.
* **C** `structure_hash` does **not** cover a `raise(delay=)` param: `delay=50` and `delay=5000` hash identically (`8fffa431ddf747da`). The hash is a *chart* fingerprint and `scheduled_sends` is unauthenticated like every other field — consistent with the stated contract, but it means a `scheduled_sends` blob replays into a chart whose delays were retuned, with no drift signal. Wrapper constraint below.
* **D** restore-strict matrix: known user event applied; unknown refused with `last_error=UnknownEventError` and **not** applied (`n=0`), once and only once; system record admitted.

One observability gap: `on_invalid_event` never fired in **D**, because a plugin cannot be attached before `from_snapshot` runs the check. `last_error` is the only channel. See CV-C51.

### 2.4 `x4` / `x5` — #212 concurrency and scaling — **PASS**

```
A. 200 machines x 1 ms ping-pong for 10.0s        [async]        [def]
   cpu/wall                                        1.00           1.00
   beats/machine min                               622            573
   runaway / chain_budget_drops                    0 / 0          0 / 0
   still beating in 2nd half                       200/200        200/200
B. pure zero-delay cycle                           TRIPPED=True   TRIPPED=True
   mixed 1 ms + zero-delay                         TRIPPED=True   TRIPPED=True
C. snapshot/restore a live ping-pong               PASS           PASS
```

`x5` ladders the rate and shows the `raise(delay=)` path is **exactly** the `after:` path, both capped by the ~15.6 ms Windows timer granularity, not by the engine:

```
   raise n=  1 period=1ms  achieved_period=15.67ms   after n=  1  15.68ms
   raise n= 10 period=1ms  achieved_period= 8.11ms   after n= 10   8.63ms
   raise n= 50 period=1ms  achieved_period= 2.92ms   after n= 50   2.38ms
   raise n=200 period=25ms achieved_period=32.36ms  eff 77.2%  cpu/wall 0.35
   raise n=1000 period=25ms achieved_period=60.87ms eff 41.1%  cpu/wall 1.00
```

Capacity number for a wrapper: **~200 machines at a 25 ms period** runs at 77 % of nominal on one core; 1000 saturates it.

### 2.5 `x6_livelock_fuzz_212.py` — livelock fuzz with the new oracle — **PASS (2000/2000)**

500 random 2–4-state cycles, each edge independently a zero-delay `raise`, a `raise(delay=1..5)` (30 % with a `send_id`), or an `after:`. Oracle: a cycle containing **any** delayed edge must **not** trip and must beat ≥3 times; an all-zero-delay cycle **must** trip.

```
X6 kind=async N=500   delayed-cycle async OK 439  sync OK 439
                      zero-cycle    async OK  61  sync OK  61   VERDICT PASS
X6 kind=def   N=500   (identical)                               VERDICT PASS
```

> Harness note: the sync lane is driven with a `SimulatedClock` **outside** any running loop. An earlier version pumped a `RealClock` from inside `asyncio` and reported 10 false violations; that was my driver, not the library, and is recorded here so the number is not mistaken for a finding.

### 2.6 `x7` / `x8` — #216 config-key fuzz — **top level PASS, nested DEFECT (D11-persistence-3)**

```
A. TOP-LEVEL: 47 mutations: warned=47 silent=0
   strict_config=True raised=47 silent=0
   hint named the right key: 47/47                       VERDICT PASS
C. `x-` prefix: accepted silently BY DESIGN, never read as a policy
D. kwarg is None -> config `strictConfig` wins; kwarg set -> kwarg wins
E. 'Strict' typo -> machine.strict=False, forged done.invoke refused=False,
   warned=yes   (the warning is the fix working)
B. NESTED: 30 mutations tried, 30 silently accepted     VERDICT NOT CHECKED
```

`x8` proves the nested gap is behavioural, not cosmetic, with `"strictConfig": true` **and** `strict_config=True` both set:

```
entry  -> Entry    correct=1,['nk.a']  typo=0,['nk.a']  warned=False  LOST SILENTLY=YES
after  -> After    correct=1,['nk.b']  typo=0,['nk.a']  warned=False  LOST SILENTLY=YES
always -> Always   correct=1,['nk.b']  typo=0,['nk.a']  warned=False  LOST SILENTLY=YES
invoke -> Invoke   correct=1,['nk.b']  typo=0,['nk.a']  warned=False  LOST SILENTLY=YES
```

### 2.7 `x15_superseded_206_restated.py` — the replacement for the superseded assertion — **PASS**

```
1 ms delayed ping-pong        laps=384 rate=63.8/s cpu/wall=0.03 TRIPPED=False
2 ms delayed ping-pong        laps=374 rate=62.0/s cpu/wall=0.01 TRIPPED=False
5 ms delayed ping-pong        laps=369 rate=61.5/s cpu/wall=0.03 TRIPPED=False
1 ms, restored from v3 blob   laps=387 rate=64.0/s cpu/wall=0.04 TRIPPED=False
zero-delay (control)          laps= 13                           TRIPPED=True
```

Runs indefinitely (384 laps vs `maxIterations=12`), CPU bounded by the clock (`cpu/wall ≤ 0.04`), the restored machine behaves identically, and the zero-delay control still trips at 13 laps.

### 2.8 `x9_concurrent_restore_215.py` — concurrency under restore — **A/B PASS, C see §4**

```
A. 100 concurrent start()s, always + descent raise
   all start()s returned in 0.01s  WATCHDOG_HANG=False
   laps: min=21 max=21 distinct=1  errors={None: 100}      PASS
B. 200 v3 snapshots w/ scheduled_sends, restored concurrently
   remaining_ms + send_id correct in blob : 200/200
   fired at start (must be 0)             : 0
   fired 1 ms early (must be 0)           : 0
   fired exactly once after the remainder : 200/200 (dups 0)  PASS
```

### 2.9 `x11_determinism_v3.py` — **PASS**

```
async distinct traces = 1 [('74e07d063486da18', 50)]
sync  distinct traces = 1 [('74e07d063486da18', 50)]
sample scheduled_sends = [('TICK', 60.00000000000001, 'hb')]
async/sync agree on (scheduled_sends, restored states, log) = True
PYTHONHASHSEED 0 / 1 / 12345 -> same digest each time      PASS
```

The two engines produce the **same digest**, not merely two self-consistent ones.

### 2.10 `x12` / `x13` / `x14` — soak, and the leak it exposed

> **Reduced parameter, said out loud:** the task asks for a 12-minute soak. The per-script hard bound is 120 s, so `x12` runs the identical shape for **1.7 min per lane** (200 machines, 10–50 ms `raise(delay=)` heartbeats, 20 external `EXT`/250 ms, chaos snapshot+restore every 2 s). The leak below is linear and was reproduced at four independent durations, so the shortened run does not weaken it.

```
X12 kind=async NM=200 MINS=1.7                       [def]
  wall=102s cpu=52s cpu/wall=0.51                    0.49
  beats/machine min=2492 med=2494 max=2495           2498/2500/2502
  external sent=6680 handled=6680 lost=0             6660/6660/0
  heartbeat stall windows 0/334                      0/333
  chaos ok=49 fail=0 skipped=0  w/ scheduled_sends=42   49/0/0/40
  statuses={'running': 200} runaway=0                 same
  rss 33012 -> 740660 KB  (delta 707648 KB)          708788 KB
```

Every functional invariant holds — **0 lost external events, 0 stalled heartbeat windows, 49/49 chaos restores clean, 0 runaways** — and then RSS grows **708 MB in 102 s**. `x13` attributes it with four same-duration arms:

```
A idle, no timers            rss  31.0 ->  31.0 MB (+  0.0)  beats=0
B raise(delay=) heartbeat    rss  43.1 -> 506.3 MB (+463.3)  beats=303322
C after: heartbeat (control) rss  38.3 ->  38.2 MB (+ -0.1)  beats=431618
D heartbeat + ext + chaos    rss  43.7 -> 497.2 MB (+453.6)  beats=306493
```

The `after:` control is **flat at more beats**. The growth is specific to the `raise(delay=)` path, is monotone in the 6-second trace samples (155 → 263 → 389 → 506 MB), and is mostly reclaimed on `stop()` — a per-interpreter unbounded retention, not a cycle. `x14` names the container:

```
raise(delay=) heartbeat
  t= 3s beats= 190 _timer_handles={'hb': 190} _armed_self_sends=1 _scheduled_sends=1
  t= 6s beats= 377 _timer_handles={'hb': 377}
  t= 9s beats= 566 _timer_handles={'hb': 566}
  t=12s beats= 753 _timer_handles={'hb': 753}
  FINAL beats=753 retained=753 already-fired among them=752 ratio handles/beat=1.00
after: heartbeat (control)
  t=12s beats= 748 _timer_handles={'hb.b': 1}   FINAL retained=1  ratio=0.00
```

Sync engine, same shape, 500 `SimulatedClock` increments: `timer_handles {'hb': 501}` — both engines.

---

## 3. Defects

### D11-persistence-1 — unbounded `_timer_handles` growth on every `raise(delay=)`, both engines

**Severity (OMS): High.** Class: **LIBRARY-DEFECT**. Repro: `x13_rss_attribution.py`, `x14_timer_handle_leak.py` (both kinds); visible in the soak `x12`.

Every delayed self-send records its timer handle under the **interpreter** id:

* `interpreter.py:2354` — `self._timer_handles.setdefault(self.id, []).append(handle)`
* `sync_interpreter.py:1194` — same pattern

The only pruner runs on state **exit** and pops by **state** id:

* `interpreter.py:2557` — `for handle in self._timer_handles.pop(state.id, []):`

`self.id` is the machine id and is never a state that exits, so the list under it is append-only for the life of the interpreter. Measured retention is exactly **1.00 handle per beat**, of which 752/753 were already fired. The `after` path takes `interpreter.py:2748` with `owner_id = state.id` and **is** pruned — which is precisely why the `after:` control arm is flat.

Impact: #212 was fixed so that a self-paced heartbeat or poller is a legal, indefinitely-running shape. This defect means that exact shape leaks ~19 MB/s per 200 machines at a 10 ms period, i.e. the newly-blessed pattern cannot be run for a trading session. `stop()` reclaims it, so the workaround is periodic recycling — unacceptable for an OMS process. Also note `clock.clear_timeout` is called per-handle on shutdown over a list that may hold millions of entries.

### D11-persistence-2 — a forged `"version": 2` snapshot mints engine `after` / `done` events

**Severity (OMS): High.** Class: **LIBRARY-DEFECT (design)**. Repro: `x2_v2_upcast_minting.py` parts B/C/D, both kinds.

`persistence.upcast()` (lines ~426-440) upcasts any v2 record of kind `done` / `error` / `after` with `rec.setdefault("engine", True)`, reasoning that "a v2 writer had exactly ONE minter". That reasoning holds for a *genuine* v2 writer; it does not hold for a payload, because **`version` is a field of the same payload the attacker controls**, and `machine_hash` is (by the library's own docstring) a fingerprint computable from the public chart, not a MAC. The attacker downgrades their own blob and the engine grants provenance it refuses at v3.

Observed: a 600 000 ms `after` fires **instantly** on a machine with `strict: True` + `onUnhandled: "error"`; a `done.invoke.k` drives `onDone` for an invocation that never ran. Both refused at `"version": 3`.

This is arguably within the stated trust boundary ("a snapshot is TRUSTED INPUT"), and the library provides the correct lever. But #214 *narrowed* v3 specifically to stop this and then left a one-field bypass, so the security property a reader would infer from the v3 gate is not the property that holds. At minimum this belongs in the `upcast` docstring and the migration note; better, `minimum_version` should default to the version that closes it once 0.8.0 blobs are drained.

Mitigation confirmed working: `from_snapshot(blob, machine, minimum_version=3)` → `SnapshotVersionError`.

### D11-persistence-3 — #216 checks the top level only; a nested state-node key typo is silent under every strict setting

**Severity (OMS): Medium.** Class: **LIBRARY-DEFECT**. Repro: `x7_config_key_fuzz_216.py` part B, `x8_nested_key_gap.py`, both kinds.

`validation.validate_top_level_keys` is called once, from `factory.create_machine`, against the top-level dict. `states.<id>` nodes are parsed by `StateNode.__init__` with plain `.get()` lookups and no key check. So `Entry` / `After` / `Always` / `Invoke` / `MaxIterations` on a *state* silently delete that state's behaviour — with `"strictConfig": true` in the config **and** `strict_config=True` passed to `create_machine`. 30/30 nested mutations accepted silently.

This is the same failure mode #216 was opened for ("a misspelled policy silently reverts to its default"), one level down, and it is arguably worse: a missing `after` on a state is a timeout that never fires, which is an OMS correctness bug, not a policy degradation. `KNOWN_MACHINE_KEYS` already contains the state-level names (`entry`, `exit`, `after`, `always`, `invoke`, `onDone`, `initial`, `type`, `on`, `states`), so the fix is to apply the same validator per node.

---

## 4. Contract gap (not a defect): #215 lap parity does not generalise

`x10_lap_parity_shapes.py` sweeps limits 1..25 on three lanes (sync, async-`def`, async-`async`) over four shapes:

```
S1 PINNED  raise+on / always        disagreements 0/25   PASS
S2 VARIANT raise+always / on+always disagreements 25/25  FAIL
S3 always-only cycle                disagreements 0/25   PASS
S4 raise-only cycle                 disagreements 0/25   PASS
```

S2 numbers (limit: sync, async-def, async-async): `1:(2,5,5) 2:(3,5,5) 3:(5,9,9) 5:(7,13,13) 9:(11,21,21)` — async runs roughly **2×** the sync laps at every limit, and the two async kinds agree with each other.

The changelog says "`always` + zero-delay `raise` agrees on all three lanes at limits 1–25, pinned as a sweep". That is true of the pinned chart (S1) and of each ingredient alone (S3, S4). It is **not** true when a single state carries **both** an `always` and a zero-delay `raise` (S2). This is not a regression — it is a claim stated more broadly than the fix. A wrapper must not rely on cross-engine lap equivalence for charts of the S2 shape; budget only on the engine it ships.

---

## 5. Not covered

* **The full 12-minute soak.** Run at 1.7 min/lane against the 120 s script bound (§2.10). The leak is linear and reproduced at four durations, but a full-session soak (and the resulting absolute RSS ceiling) is untested.
* **Multi-process / cross-host restore** of a v3 blob; all restores here are in-process.
* **`scheduled_sends` for a delayed send targeting a CHILD actor** (`sendTo`) — `_armed_self_sends` is populated only when `actor is self`, so a delayed send to a child has no v3 record. Not exercised; the #212 rule matrix item "sendTo child" is **not covered**.
* **`cancel(id)` interaction with a restored `scheduled_sends` record** — whether cancelling by the restored `send_id` reaches the re-armed timer. Not tested.
* **Redaction** of context in snapshots — no redaction surface was exercised.
* **Actor-tree restore under the v3 layout** at scale (`r7` passes at small scale only).
* Whether D11-persistence-1 also affects `sendTo`-to-child delayed sends (the same line 2354 runs for `actor is not self`, so it very likely does) — measured for self-sends only.

---

## 6. Verdict

**ADOPT with constraints.** Round 10's two reversals are correctly and completely implemented, and the persistence surface is in better shape than any prior round: the v3 round-trip is exact over 600 randomised machines, determinism is byte-identical across engines and hash seeds, and the 2000-run livelock fuzz under the new oracle is clean. No prior persistence defect regressed.

The blocker for Phase 3 is **D11-persistence-1**: the heartbeat pattern that #212 was fixed to legitimise leaks a timer handle per beat on both engines, which rules out long-lived self-paced pollers until it is fixed. That is a small, well-localised fix (key the handle by the owning state id, or prune on fire).

New wrapper constraints:

* **CV-C49** — Do not use `raise(delay=)` for a long-lived heartbeat or poller until D11-persistence-1 is fixed. Use `after:` — measured identical in rate (`x5`) and flat in RSS (`x13/C`). If `raise(delay=)` is required for its `send_id`/cancel semantics, bound process lifetime and monitor RSS.
* **CV-C50** — Always call `from_snapshot(..., minimum_version=3)` once 0.8.0-era blobs are drained, and authenticate snapshots (HMAC over the JSON) outside the library before restoring. `machine_hash` is not a MAC and `version` is attacker-controlled (D11-persistence-2).
* **CV-C51** — Restore-time `strict` refusals surface **only** via `last_error`; `on_invalid_event` cannot fire because no plugin is attached yet. Check `interp.last_error` immediately after every `from_snapshot`, before `start()`.
* **CV-C52** — Validate chart JSON against a schema in CI. `create_machine(strict_config=True)` covers the top level only; nested state-node key typos are silent (D11-persistence-3) and silently delete `entry`/`after`/`always`/`invoke`.
* **CV-C53** — `structure_hash` does not cover `raise(delay=)` params (`x3/C`): retuning a delay does **not** invalidate old snapshots, so a `scheduled_sends` record replays the *old* remaining delay into the *new* chart with no drift signal. Version chart changes explicitly.
* **CV-C54** — Do not rely on cross-engine lap-count equivalence for charts where one state carries both `always` and a zero-delay `raise` (§4). Size `maxIterations` against the engine actually shipped.
* **CV-C55** — Capacity: ~200 interpreters at a 25 ms heartbeat run at 77 % of nominal on one core; 1000 saturates it (`x5`). Size accordingly, and note the ~15.6 ms Windows timer floor makes any period below ~16 ms nominal-only.
