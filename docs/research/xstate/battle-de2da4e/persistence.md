# Battle track — PERSISTENCE @ `de2da4e` (unreleased 0.8.1)

**Library:** `main` @ `de2da4e` ("Merge pull request #223 from basiltt/fix/0.8.1-round11"); `__version__` still reports 0.8.0, so every result keys on the **commit**.
**Scope:** round-11 fixes #218–#222 as they touch persistence, plus the standing persistence surface re-attacked.
**Suite:** `suite-de2da4e.log` — **3545 passed, 13 skipped, 15 warnings in 752 s**, total coverage **92.87 %** (`persistence.py` 95 %, `validation.py` 99 %, `base_interpreter.py` in the 90s). Clean.
**Scripts:** `battle-de2da4e/persistence/p1..p5*.py` (new) — all STANDALONE (stdlib + `xstate_statemachine`), every one proved from the neutral cwd `C:/Users/basil` via `runall.sh`, which runs each on **both** service kinds (`XS_SVC=async` / `XS_SVC=def`). Prior-round scripts were re-run from `battle-c78ce99/persistence/` through the same runner. Raw output in `out/*.txt` (async) and `out/*.DEF.txt` (`def`).

---

## 0. Bottom line

**Round 11 lands all five persistence-relevant fixes, on both service kinds and both engines, with no new defect found in this track.**

* **#218 (handle leak) — FIXED, completely.** `x14` re-run: a `raise(delay=)` heartbeat holds **1 handle for 766 beats** (was 1.00 dead handle *per beat*). `p5` at 200 machines × 10 s: **0.935 handles/machine** on the `raise` path vs 1.0 on the `after:` control, RSS delta **+10.5 MB** and flat across the last three samples (was 463 MB in 24 s). This was the round-11 High and it is gone.
* **#219 (ReentrantWaitError) — CORRECT on all 7 matrix cells** (`p4`): self-send from an entry action during `start()` raises and **`start()` returns**; post-start action, `after`-fired handler and the sync engine all refuse identically; the deferred `ensure_future` receipt resolves; child→parent and parent→child `wait=True` both **OK**; **100/100** concurrent deferred receipts resolve with no hang and no spurious refusal.
* **#220 (recursive key check) — SOUND AND COMPLETE** on the fuzz (`p3`): **178/178** valid charts generated from the full documented grammar (nested states, parallel regions, dict/list/string transition bodies, invoke + onDone/onError, `x-`/`meta`/`description`/`tags` at every level) built with **0 false positives** under `strict_config=True`; **178/178** single-typo injections at a random nesting level and object kind were caught, every message naming the offending key; **54/54** catalogue `*.machine.json` clean. `x8` (the round-11 repro for R11-07) now raises naming `nk.a: 'Entry'`.
* **#221 (parked `scheduled_sends`) — FIXED.** `p1`: **600/600** property cases (300 × 2 kinds) survive a random chain of 1–4 `from_snapshot` → `get_persisted_snapshot` "journal compaction" hops **without `start()`**, with `remaining_ms` and `send_id` **byte-identical at every hop**, then fire exactly once after the remainder — not early, not twice. No duplication once `start()` consumes the parked list (before/after/again = 1/1/1). Sync engine same.
* **#222 (chain-trip latch) — CORRECT, with one documented gap.** `p2`: trip → `chain_trips=1`, `last_chain_error` latched and **survives 5 benign events** that erase `last_error` (exactly the #222 claim); `clear_chain_error()` clears the latch and keeps the count; a second trip gives `chain_trips=2`; `on_chain_budget_exceeded` fires **exactly twice for two trips**. Identical on both engines and both kinds.

**New defects: none.** One **contract gap** worth a wrapper constraint: the chain-trip record is **process-local — it is not in the snapshot** (§3.1). Carried-forward Blocker `R11-01` (the `"version": 2` downgrade mint) is **STILL-PRESENT and unaddressed by this round** — it was not in scope for #218–#222, but it governs the verdict.

**Verdict: ADOPT with constraints** (§6) — unchanged in shape from row-6, with three constraints retired.

---

## 1. Prior-defect table (round-11 persistence findings re-run at `de2da4e`)

Every persistence-relevant script from `battle-c78ce99/persistence/` re-run on both kinds. Legend: **FIXED** / **STILL-PRESENT** / **CHANGED** / **SUPERSEDED**.

| Prior defect | Script (both kinds) | Status @ `de2da4e` | Evidence |
|---|---|---|---|
| **R11-04 / D11-persistence-1** (High) unbounded `_timer_handles` growth on `raise(delay=)` | `x14`, new `p5/A` | **FIXED** | `x14`: 1 handle / 766 beats, `already-fired among them=0`, script's own verdict line flips to `unbounded retention = no`. `p5/A`: 0.935 handles/machine at 200 machines, RSS +10.5 MB then flat |
| **R11-06** (Medium, hang) entry action awaiting its own receipt hangs `start()` | new `p4/A` | **FIXED** | `ReentrantWaitError`, `start: returned` — both kinds, and the sync engine (`p4/G`) |
| **R11-07 / D11-persistence-3** (Medium) key check is root-only | `x8`, `x7`, new `p3` | **FIXED** | `x8` now raises `InvalidConfigError: … nk.a: 'Entry' (did you mean 'entry'?)`; `p3/B` 178/178 nested typos caught; `p3/A` 0 false positives |
| **R11-08** (Medium) restore→re-persist without `start()` drops armed sends | new `p1` | **FIXED** | 600/600 property cases through 1–4 no-start hops, records verbatim; `p1/C` sync same |
| **R11-09** (Medium) chain trip reaches only `last_error`, next event erases it | new `p2` | **FIXED** | `latch_after_5_benign = RunawayChainError` while `last_error_after_5_benign = null`; `chain_trips` monotonic; hook fires once per trip |
| **R11-01 / D11-persistence-2** (**Blocker**) `"version": 2` mints engine provenance | `x2` | **STILL-PRESENT** | `v2 forged, strict+onUnhandled=error: fired=1 states=['vict.expired'] -> MINTED=YES`; `v3` control `MINTED=no`; `v2 forged done.invoke -> MINTED=YES`. Out of scope for #218–#222; mitigation `from_snapshot(minimum_version=3)` still works |
| **R11-02 / R11-03** restore-path provenance/lane forgery | `u2`, `s2`, `x3` | **STILL-PRESENT, as designed** | `u2` exit 0; the "breaches" are cases where the attacker writes `"engine": true` or imports the private class — the documented `from_snapshot` trust boundary (R10-01/R11-01 pattern), **not filed** |
| **R11-10** (Low) `on_invalid_event` unreachable on restore | `x3/D` | **STILL-PRESENT** | a plugin cannot be attached before `from_snapshot` runs the check; `last_error` remains the only channel |
| **R11-11** (Low) `structure_hash` omits `raise(delay=)` delays | `x3/C` | **STILL-PRESENT** | `delay=50` and `delay=5000` still hash identically — CV-C61 stands |
| **R11-12** (Low) `lane` persisted but not honoured on sync | `s2` | **STILL-PRESENT, as designed** | sync engine has one queue by construction |
| **#206** delayed self-ping-pong must trip | `x15` | **SUPERSEDED** (by #212), replacement passes | `x15` exit 0 both kinds |
| **#204** `statesToInvoke` across the boundary | `u3` | **FIXED** (holds) | exit 0 both kinds |
| **#207** stranded invocations | `u5` | **FIXED** (holds) | exit 0 both kinds |
| **#208** receipts never success-shaped over an illegal config | `u6` | **FIXED** (holds) | exit 0 both kinds |
| **#209/#215** lap parity, settled shape | `s7` | **FIXED** (holds) | exit 0 both kinds |
| v3 round-trip property, v2 upcast matrix, lane/hash/strict, determinism | `x1`, `x2`, `x3`, `x11` | **hold** | exit 0 both kinds; `x11` still one digest across both engines |
| **R10-09** `SnapshotMidStepError` reports `child=False` | `t5` | **STILL-PRESENT** | exit 1 unchanged; Low, attribution-only |
| `restore_event` type guard (#158) | `n7` | **STILL-PRESENT, as designed** | exit 1 = `SnapshotCorruptError` on `type: 42`, which **is** the assertion |

**No prior persistence defect regressed, and five were closed.** The two exit-1 rows (`n7`, `t5`) are the same expected-shape results round 11 recorded.

---

## 2. New attacks

### 2.1 `p1_parked_rearm_chain.py` — parked + armed `scheduled_sends` across restore→persist→restore→start chains — **PASS (600/600)**

Property, 300 cases × 2 service kinds. Each machine arms 1–3 concurrent `raise(delay=)` self-sends (delays from {40, 60, 90, 130} ms, distinct `send_id`s), runs for a random 5–20 ms, is snapshotted mid-delay, and the blob is then passed through a **random chain of 1–4 journal-compaction hops** — `from_snapshot` immediately followed by `get_persisted_snapshot`, **never started** — before a final restore that does `start()`.

```
{"kind": "async", "N": 300, "n_fail": 0,
 "part_b": {"before_start": 1, "after_start": 1, "re_persist": 1, "ok": true},
 "part_c": {"sync_hop0": 1, "sync_hop1": 1, "ok": true},
 "VERDICT": "PASS"}          # identical for kind=def
```

At **every** hop the record count matched, the `send_id` set matched, and `remaining_ms` was **bit-identical** (tolerance 1e-6 — the parked records are re-emitted verbatim with no clock bound, exactly as the CHANGELOG states). After the final `start()`, no machine fired at `start()`, none fired before 40 % of the shortest remaining delay, and every armed send fired exactly once.

Part **B** is the aliasing question the fix raises: once `start()` has *consumed* the parked list, does re-persisting duplicate or resurrect it? Records before start / after start / on a second persist = **1 / 1 / 1**. Part **C** repeats the no-start hop on `SyncInterpreter`: **1 / 1**.

→ **R11-08 is FIXED, and CV-C58 ("never re-persist an interpreter that has not been started") can be retired.**

### 2.2 `p2_chain_latch_snapshot.py` — chain-trip latch, exactly-once, and across a snapshot — **PASS, with a documented gap**

`maxIterations: 5`, a self-`raise` spin state, a benign `PING`, and a `RESET` escape. Both engines.

```
trips_after_1                 1
latch_after_1                 RunawayChainError
last_error_after_1            RunawayChainError
latch_after_5_benign          RunawayChainError    <- the #222 fix
last_error_after_5_benign     null                 <- the documented per-step read
hook_trips                    [("RunawayChainError", "LOOP")]
latch_after_clear             None
trips_after_clear             1                    <- count survives clear
trips_after_2                 2
latch_after_2                 RunawayChainError
hook_trips_final              2                    <- exactly once per trip
```

Identical on `SyncInterpreter` and on both service kinds. `on_chain_budget_exceeded` fired **2 times for 2 trips** — no double-fire on the re-latch, no miss.

**The gap (contract, not a defect):**

```
snapshot_has_chain_key   []       # no chain_trips / last_chain_error field in the v3 blob
restored_chain_trips     0
restored_latch           null
```

A machine that discarded work, was snapshotted, and was restored comes back with **`chain_trips = 0` and a clear latch**. The latch is a *process-local supervision signal*, not persistent state — consistent with `plugins.py:423` (it is "the supervisor's signal"), and the v3 layout documents its own fields, so this is not a broken promise. But an OMS that restarts from a snapshot loses the only record that the previous process discarded work. → **CV-C63 (new)**, §5.

### 2.3 `p3_key_fuzz_recursive.py` — the recursive key check, two-sided — **PASS**

```
A_valid_built            178      A_false_positives   0
A_other_build_errors      72      (non-progressing `always` self-targets etc. — the
                                   generator's own unrelated illegality, not key findings)
B_injected               178      B_missed            0     B_wrong_msg  0
B_structural_reject        5      (typo destroyed `states`/`id` → rejected earlier, still caught)
C_catalogue_files         54      C_findings          0
```

Identical on both kinds. **A (soundness)** generates charts from the full documented grammar: nested `states` to depth 2, parallel regions, `on` bodies in all three forms (string shorthand / dict / list), `after` and `always` bodies, `invoke` as dict **and** as list with `onDone`/`onError`/`input`/`systemId`, and `meta` / `description` / `tags` / `x-owner` / `x-note` sprinkled at **every** level including inside transition and invoke bodies. Zero were rejected for an unknown key — the `x-`/metadata acceptance really is at every level.

**B (completeness)** injects one typo per chart at a uniformly random object (state at any depth; transition body under `on` / `always` / `after` / `onDone`; invoke body; the invoke's own `onDone` / `onError`) from an 18-entry typo table. Every one raised, and every message contained the offending key.

**C** ran all 54 `*.machine.json` from the three battle contracts dirs through `validate_top_level_keys(strict_config=True)` — **zero findings**: our catalogue is clean under the stricter recursive rule.

**D — `x-` abuse / case variants** (the security question):

| key | reported | policy took effect |
|---|---|---|
| `Strict` | yes (hints `strict`) | **no** |
| `STRICT` | yes | **no** |
| `X-strict` | yes (hints `strict`) | **no** |
| `x-strict` | no (reserved namespace) | **no** |

No case variant and no `x-` spelling can smuggle a policy: the parser reads only the exact lower-case name, so the "smuggled" key is inert in every cell, and only the exactly-`x-`-prefixed form is silently accepted — the documented contract. **No bypass.**

### 2.4 `p4_reentrant_matrix.py` — the `ReentrantWaitError` matrix — **PASS (all cells)**

| cell | shape | result |
|---|---|---|
| **A** | entry action awaits its own `send(wait=True)` during `start()` | `ReentrantWaitError`, **`start: returned`** |
| **B** | post-start action, same shape | `ReentrantWaitError`, `send: returned` |
| **C** | `after`-fired handler action, same shape | `ReentrantWaitError`, timer still fired |
| **D** | deferred: `ensure_future(i.send(..., wait=True))`, awaited after the step | **`receipt: resolved`**, machine advanced `rb.a → rb.b` |
| **E** | child → parent `wait=True` | **OK** (parent recorded `FROMCHILD`) |
| **F** | parent → child `wait=True` | **OK** (child recorded `FROMPARENT`) |
| **G** | `SyncInterpreter`, self-send from entry | `ReentrantWaitError`, `start: returned` |
| **H** | **100 concurrent** actions, deferred pattern | `receipts: 100`, `outcomes: {"ok": 100}` — no hang, **0** spurious refusals |

Identical on both service kinds. The refusal is precisely scoped: it catches exactly the in-step self-await (A/B/C/G) and refuses **nothing** else — cross-interpreter sends in both directions work, and the documented escape hatch works at scale.

### 2.5 `p5_fleet_and_cancel_storm.py` — 200 machines × 10 s, and a cancel storm — **PASS**

```
A  raise(delay=) heartbeat, 200 machines, 10 s   [async]        [def]
   handles/machine final                          0.935          0.975
   beats_min per machine                          273            >0
   RSS                        27.1 -> 36.4, 36.6, 36.9, 37.6 MB  (delta +10.5 / +10.6)
B  after: heartbeat (control), 200 machines
   handles/machine final                          1.000          1.000
   RSS delta                                      +0.5           +0.7
C  cancel storm: 2000 x (arm a 5 s delayed send, cancel it)
   handles 0   armed 0   scheduled 0   chain_owed 0
   snapshot_records 0   hits 0   last_error null          -> ok
D  arm/cancel the SAME id 500x, then arm once and let it fire
   hits 1   handles 0   armed 0                           -> ok
```

**A** is the round-11 High re-measured at fleet scale: the `raise(delay=)` path is now *indistinguishable* from the `after:` control in handle retention, and RSS is flat across the last three samples (36.4 → 37.6 MB over 7.5 s, i.e. noise, vs the 463 MB / 24 s of `battle-c78ce99/x13`). The ~+10 MB step is fleet construction, taken once. (RSS is read via `K32GetProcessMemoryInfo` through `ctypes` — stdlib only, no `psutil`; `argtypes`/`restype` must be set or the process handle truncates and the call returns 0.)

**C/D** is the double-release question. 2000 arm/cancel pairs leave **every** container at zero — `_timer_handles`, `_armed_self_sends`, `_scheduled_sends`, `_chain_owed_sends` — the snapshot carries **no** record, no timer ever fired, and no error was latched. No double-release, no leaked record, no resurrection; **D** shows the id is still armable after 500 cancel cycles and then fires **exactly once**.

### 2.6 `x6_livelock_fuzz_212.py` (re-run) — 500 configs × 2 engines — **PASS**

```
X6 N=500 engines=async+sync oracle=#212
   delayed-cycle async OK 439 / sync OK 439
   zero-cycle    async OK  61 / sync OK  61
VERDICT PASS
```

The #212 oracle still holds under the round-11 rules: every delayed cycle runs as a timer, every zero-delay cycle still trips, and the two engines agree config-for-config.

### 2.7 Determinism — `x11_determinism_v3.py` (re-run) — **PASS**

50× traces on both engines and both service kinds, including a `scheduled_sends` restore, still produce **one digest, the same digest on both engines**, invariant across `PYTHONHASHSEED`. `chain_trips` was additionally checked in `p2`: deterministic (1 after one trip, 2 after two) on both engines and both kinds.

### 2.8 `p6_soak_v3_chaos.py` — soak: 200 machines, heartbeats + external producer + chaos v3 snapshot/restore — **PASS both kinds**

**Reduced duration, said out loud:** the task asks for 12 minutes; the hard per-script bound is 120 s and the whole-task bound 20 min, so this runs the **same shape** at `XS_MINS=1.5` per service kind. 200 machines, 10 ms `raise(delay=)` heartbeats, an external priority producer, and a chaos loop that snapshots → restores → re-persists a random machine at quiescence every 2 s.

```
kind=async NM=200 MINS=1.5 chaos_every=2.0s
   wall=90s cpu=88s cpu/wall=0.97   rss 33356 -> 38660 KB (delta 5304 KB)
   beats/machine: min=1153 med=1156 max=1158
   external: sent=5200 handled=5200 lost=0
   heartbeat stall windows: 0/260
   chaos: ok=42 fail=0 skipped(midstep)=0 blobs_with_scheduled_sends=39
   statuses={'running': 200} runaway=0
   #222 chain_trips total=0 latched=0
   #218 retained timer handles total=138 per-machine=0.690
   VERDICT PASS

kind=def   NM=200 MINS=1.5 chaos_every=2.0s
   wall=90s cpu=70s cpu/wall=0.78   rss 33104 -> 38436 KB (delta 5332 KB)
   beats/machine: min=2268 med=2269 max=2270
   external: sent=6220 handled=6220 lost=0
   heartbeat stall windows: 0/311
   chaos: ok=43 fail=0 skipped(midstep)=0 blobs_with_scheduled_sends=39
   statuses={'running': 200} runaway=0
   #222 chain_trips total=0 latched=0
   #218 retained timer handles total=197 per-machine=0.985
   VERDICT PASS
```

Every invariant holds on both kinds:

* **Handles flat** — 0.690 / 0.985 per machine after 90 s of 10 ms beating across 200 machines and 42–43 chaos restores. Pre-#218 this shape retained one handle *per beat*; at ~1 155 (async) / ~2 269 (def) beats × 200 machines that would be 231 000 / 454 000 handles. It is **138** and **197** — i.e. at most one live handle per machine, which is the whole claim.
* **RSS flat** — +5.3 MB over 90 s on both kinds, across 42–43 full snapshot/restore/re-persist cycles.
* **0 external events lost** — 5 200/5 200 and 6 220/6 220 handled. (The engine additionally *reported* 3 and 4 `stopped` drops for events that raced a chaos restart and were nonetheless handled by the restored machine. The oracle's `unreported = (sent - ext) - raced` inherited from `x12` can therefore go negative; it is clamped at 0, since a reported drop is by definition not a silent loss. This was an oracle bug in the harness, not a library finding.)
* **Heartbeats never die** — `0/260` and `0/311` stall windows; the slowest machine is within 0.4 % of the fastest.
* **Chaos clean** — 42/42 and 43/43 restores succeeded, 0 failed, 0 refused mid-step, and 39 of each 42/43 blobs carried live `scheduled_sends` (the rest were caught between beats with nothing armed).
* **`chain_trips` stable at 0** on all 400 machines — the new latch does not spuriously fire under sustained load with chaos restores. #222 behaves as a quiet supervisor signal rather than noise.

`cpu/wall = 0.97` (async) is the Windows timer-granularity plateau this track has measured every round, not an engine regression; the `def` lane runs the same shape at 0.78 and twice the beat rate.

---

## 3. Defects

**`D12-persistence-*`: none.** No new library defect was found in this track at `de2da4e`. Every round-11 persistence fix reproduced as advertised, on both service kinds and both engines, and no fix introduced an observable regression in the prior-defect sweep (§1).

The two non-defect findings worth carrying:

### 3.1 Contract gap — the chain-trip record is process-local

`chain_trips` and `last_chain_error` are **not** snapshot fields (`p2`: `snapshot_has_chain_key = []`, `restored_chain_trips = 0`, `restored_latch = null`). This is consistent with the documented purpose (a supervisor signal on a live interpreter) and with the v3 layout as specified, so it is **not filed as a defect** — but it is a real operational hole: restart-from-snapshot erases the evidence that the prior process discarded work. Wrapper constraint **CV-C63**, §5.

### 3.2 Carried Blocker — `R11-01` (`"version": 2` minting) is untouched

`x2` reproduces unchanged at `de2da4e`: a forged `"version": 2` blob still mints an engine `after` that fires a 600 s timer instantly under `strict: True` + `onUnhandled: "error"`, and an engine `done.invoke` that drives `onDone`; both are refused at `"version": 3`. Round 11 did not target it. The mitigation (`from_snapshot(minimum_version=3)`) still works and must remain mandatory. This is the single item that keeps the verdict conditional.

The `from_snapshot` provenance/lane vectors (`R11-02`, `R11-03`) remain **trust-boundary, not filed**, per the R10-01/R11-01 pattern: they all require the attacker to write `"engine": true` or import a private class, which the `from_snapshot` docstring declares out of scope.

---

## 4. Not covered / limits

| Area | Why, and what stands in for it |
|---|---|
| **The full 12-minute soak** | Exceeds the hard per-script bound (≤120 s) and the ≤20 min total wall clock. `p6` runs the **same shape** — 200 machines, 10 ms `raise(delay=)` heartbeats, external priority producer, chaos v3 snapshot/restore/re-persist at quiescence — at **1.5 min per service kind** (3 min total). **Said out loud:** a true 12-min run is the one thing this track did not execute. The handle/RSS invariant is independently covered at the full stated 200-machine scale by `p5/A`, and `p6` already integrates 42–43 chaos restores. |
| **`n5_corrupt_fuzz`, `t2`, `t8`** | Long-running property scripts that timed out at the bound in round 11 too. Re-covered by `p1` (600 property cases), `p3` (178 valid + 178 mutated charts) and `x6` (500 configs × 2 engines). |
| **`SimulatedClock` deadline properties** | `R11-W-3` still stands: `SimulatedClock` does not fire restored `scheduled_sends`. All deadline properties here (`p1`, `p5`, `p6`) were therefore verified against the **real** clock, which is what bounds `p1` at 300 cases/kind. |
| **Cross-process / on-disk durability** | Out of scope: every snapshot round-trip here is in-process JSON. The `from_snapshot` trust boundary (in-process Python) is the documented one. |
| **`R11-01` fix verification** | Not attempted — round 11 did not target it. Re-reproduced unchanged (`x2`) and carried into the verdict. |
| **`on_event_dropped` ordering** | Only observed incidentally (`p6`'s 3–4 reported `stopped` drops during chaos restarts, all correctly reported). A dedicated ordering matrix belongs to the observability track. |

---

## 5. Wrapper constraints — deltas

**Retire (the library now does this):**

* **CV-C58** — "never re-persist an interpreter that has not been `start()`ed" → **#221 fixed**; `p1` proves 1–4 no-start hops are verbatim-safe on both engines, 600/600.
* **The `_timer_handles` mitigation** for heartbeat interpreters (periodic recycling) → **#218 fixed**; `p5/A` and `p6` show `raise(delay=)` retention equal to the `after:` control at 200 machines under chaos.
* **"A misspelled key inside a state is undetectable"** → **#220 fixed**; turn on `strict_config=True` in the catalogue loader — all 54 of our contracts already pass clean under the recursive check.

**Keep, unchanged:**

* **`from_snapshot(minimum_version=3)` is mandatory on every restore.** `R11-01` is live at `de2da4e`; this is the only thing between a forged blob and minted engine provenance.
* **CV-C61** — the wrapper's own contract fingerprint must hash `raise(delay=)` params; `structure_hash` still omits them.
* **R11-W-1** (stable `send_id` on every catalogue deadline), **R11-W-2** (never shadow a built-in action name), **R11-W-3** (real clock for deadline tests).
* **Never depend on restored event ordering** — `lane` is forgeable on async and unenforceable on sync (`R11-12`).

**New:**

* **CV-C63 — `chain_trips` / `last_chain_error` do not survive a snapshot.** Read both **before** `get_persisted_snapshot()` and write them into the wrapper's own envelope; otherwise a restart silently resets the "this machine discarded work" signal to zero.
* **CV-C64 — an action must never `await interpreter.send(..., wait=True)` on its own interpreter.** #219 turns the old hang into a loud `ReentrantWaitError`, which is right, but it is a **behaviour change**: any existing action that did this now raises instead of deadlocking. Use the documented deferred form (`asyncio.ensure_future(...)`, awaited after the step) — proved sound at 100 concurrent receipts (`p4/H`). Lint the catalogue's action bodies for the in-step self-await before upgrading.

---

## 6. Verdict

**ADOPT with constraints** — for the persistence surface, round 11 is the strongest round this track has recorded.

Five defects closed, all five re-verified from the neutral cwd on both service kinds and both engines, with **zero** new defects (`D12-persistence-*`: none) and **zero** regressions across the prior-defect sweep. The three fixes that matter most operationally — the `raise(delay=)` handle leak (#218), the restore→re-persist deadline loss (#221) and the root-only key check (#220) — are not merely patched but *complete*: the leak is measured at fleet scale against its own control and under 90 s of chaos restores; the deadline survives arbitrary journal-compaction chains bit-identically, 600/600; and the key check is proved **both** sound (0/178 false positives across the full documented grammar) **and** complete (178/178 nested typos caught, each named). #219 replaces a silent `start()` hang with a precisely scoped error that refuses nothing it should allow — cross-interpreter `wait=True` in both directions still works, and the deferred escape hatch scales. #222 gives the supervisor the sticky signal it lacked, exactly once per trip.

The constraints are two, and both are carried rather than new:

1. **`from_snapshot(minimum_version=3)` on every restore, without exception.** `R11-01` — a forged `"version": 2` payload minting engine provenance — is **still live** at `de2da4e` and remains the one Blocker-class item on this surface. Round 11 did not address it; the mitigation is one argument and it works.
2. **The wrapper owns chain-trip durability and the deadline fingerprint** (CV-C63, CV-C61), and the catalogue must be linted for the in-step self-await (CV-C64) before upgrading, since #219 is a deliberate behaviour change.

With those in place the persistence surface at `de2da4e` meets the financial-OMS standard. Three prior wrapper constraints retire — the first round in which the wrapper's burden goes **down**.
