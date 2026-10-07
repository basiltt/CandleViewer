# Battle track — PERSISTENCE @ `v0.9.0` / `main` `e3a1f22`

**Library:** tag `v0.9.0` = `91bd979`; `main` = `e3a1f22`. `git diff v0.9.0..HEAD --stat` = **`.github/workflows/publish.yml` only, 1 file, +14/-1** — the publish smoke test. The claim "main is 2 commits ahead, CI only" is **verified**: no source, test or doc file differs, so every result below keys on `v0.9.0` and on `main` identically. `__version__` reports `0.9.0`.
**Not on PyPI.** `pip download xstate-statemachine==0.9.0` fails — the release exists as a tag and a CI workflow, not as a published artefact. Every run here is against the working clone.
**Scope:** round-12 fixes #225–#235 as they touch persistence, plus the standing persistence surface re-attacked.
**Suite:** `suite-v0.9.0.log` — **3577 passed, 13 skipped, 15 warnings in 597 s**, total coverage **92.86 %**, gate 90 % met. Clean.
**Scripts:** `battle-v0.9.0/persistence/n1..n12*.py` + `q0..q2*.py` (new), `repro/d13_p1*.py`, `repro/d13_p2*.py`. All STANDALONE (stdlib + `xstate_statemachine`), every one proved from the neutral cwd `<home>`, on **both** service kinds (`XS_SVC=async` / `XS_SVC=def`) where the kind is meaningful. Prior-round scripts re-run from `battle-de2da4e/persistence/` and `battle-c78ce99/persistence/` through the same `runall.sh`. Raw output in `out/`.

---

## 0. Bottom line

**Round 12 lands every persistence-relevant fix (#226, #227, #230, #231, #233), on both service kinds and both engines. Two new defects, both Medium, both in the new surface #226/#230 introduced.**

* **#226 (chain-trip latch in the v3 envelope) — FIXED and durable.** `n1`: `chain_trips` is byte-stable across **6 consecutive restore→re-persist hops** on both engines and both kinds, the latch comes back as a `RestoredError` carrying the original message verbatim at every hop, a trip *after* a restore is `previous + 1` (monotonic across the restart), `clear_chain_error()` keeps the count, and a cleared latch does **not** resurrect on the next restore. `p2` re-run confirms `snapshot_has_chain_key = ["chain_trips", "last_chain_error"]` where round 11 read `[]`. **Wrapper constraint CV-C63 retires.**
* **#227 (strict + schemas on restored `scheduled_sends`) — FIXED.** `n2`: **640 property cases** (320 × 2 kinds) forging 0–3 undeclared types and schema-violating payloads into the `scheduled_sends` lane of a real v3 blob. Every declared record still fires exactly once; **no** undeclared type was ever admitted; `on_invalid_event` fired **exactly once per refused record**, no more and no less; `last_error` was set in the `start()` window iff a refusal happened and never spuriously; the machine stayed `running` in all 640. A refusal never aborts the restore.
* **#230 (`from_snapshot(plugins=)`) — WORKS for the refusal path, but the lifecycle hook is skipped.** The parameter does attach plugins early enough that `on_invalid_event` sees a restore-time refusal (`n2`, 640/640). **But `on_interpreter_start` never fires on any restored interpreter** — `plugins=` *or* `.use()`, async *or* sync. → **D13-persistence-2**.
* **#233 (sync priority lane on restore) — FIXED.** `n9`: a blob whose `pending_events` are persisted interleaved `N1,P1,N2,P2` replays as `P1,P2,N1,N2` on **both** engines — FIFO within lane, priority lane ahead of the inbox, engines byte-identical. Round 11's `R11-12` ("`lane` persisted but not honoured on sync") is closed.
* **#231 (inline-dict `invoke.src`) — FIXED, and complete.** `n6`: 36 cases = 12 hostile `src` values × 3 nesting positions (root / nested child / parallel region). **33/36 raise a named `InvalidConfigError`** identifying the state and the invoke id; **0 `TypeError`**. The 3 that build clean are `src: null`, which is a different (pre-existing, documented) path — it WARNs at build and dies at `start()` with `ImplementationMissingError: Service 'None' … is not registered` (`n7`). No silent acceptance anywhere.
* **#225 (self-send provenance by task identity) — CORRECT on every matrix cell.** `n3`: action→direct-send, action→awaited-helper→send, action→`ensure_future` worker→send, action→task→task→send all deliver with the loop **idle** (the decisive symptom: an internally-queued event would never be drained); the in-step self-await is still `ReentrantWaitError`; the hand-out receipt resolves. Identical on both kinds. `n8` at scale: **200 machines × 5 rounds = 1000 worker-spawned ACKs, 0 starved**, and **100/100 concurrent `ensure_future(send(wait=True))` hand-outs resolve** while the spawning actions keep awaiting.
* **#232 (RuntimeWarning on a dropped `def`-action receipt) — CORRECT and precisely scoped.** `n4`: `drop` emits exactly one `RuntimeWarning` naming the event, the machine id, the issue number and the two supported shapes; `ensure_future` / `.result()` / `.add_done_callback` are **silent** (0 warnings each). `n5`: under `-W error` **inside asyncio** it surfaces in the **GC finaliser as an unraisable** — `sys.unraisablehook` sees it, `start()` does not raise, no loop exception handler fires, the machine keeps working and the event is still delivered. That is the right place for it; a `-W error` test suite must hook `sys.unraisablehook`, not `pytest.warns`.

**New defects: two, both Medium.**
* **D13-persistence-1** — a malformed `chain_trips` escapes `from_snapshot` as a raw `ValueError` / `TypeError`, not `SnapshotCorruptError`, unlike every pre-#226 envelope field.
* **D13-persistence-2** — `on_interpreter_start` never fires on a restored interpreter, on either engine, via `plugins=` or `.use()`; `on_interpreter_stop` still does.

**Carried Blocker `R11-01` (the `"version": 2` downgrade mint) is STILL-PRESENT and unaddressed by this round** (`x2` reproduces verbatim). It governs the verdict as it has since round 10.

**BENCH-6 improved by ~40 %.** Five runs of **their** `benchmarks/production_characteristics.py --quick`, §2 loaded-timer lateness at 500 busy machines: **+54.8 / +54.0 / +58.3 / +56.4 / +55.0 ms** (median 55.0, spread 4.3 ms). Round 12 read +89.6/+94/+113/+110/+111. Our bar is ≤100 ms; the whole distribution now clears it with ~45 % headroom, where round 12 had three readings over the bar.

**Verdict: ADOPT with constraints** (§6) — one constraint retires (CV-C63), two new wrapper constraints appear for the two new defects, and `R11-01` remains the single conditional.

---

## 1. Prior-defect table (re-run at `v0.9.0`)

Legend: **FIXED** / **STILL-PRESENT** / **CHANGED** / **SUPERSEDED**.

| Prior defect / pin | Script (both kinds) | Status @ `v0.9.0` | Evidence |
|---|---|---|---|
| **R11-08** restore→re-persist without `start()` drops armed sends | `p1` | **FIXED (holds)** | `def` 300/300 PASS; `async` 299/300 with one `hop0 records 0 != 1` — **harness timing, not a defect** (§1.1) |
| **R11-09 / #222** chain trip reaches only `last_error` | `p2` | **FIXED (holds), now durable** | `latch_after_5_benign = RunawayChainError` while `last_error = null`; **`snapshot_has_chain_key = ["chain_trips","last_chain_error"]`** (was `[]`), `restored_chain_trips = 1`, `restored_latch = RestoredError` — the #226 delta |
| **R11-06 / #219** entry action awaiting its own receipt hangs `start()` | `p4` | **FIXED (holds)** | exit 0 both kinds; all 7 matrix cells, incl. the sync engine and 100/100 deferred receipts |
| **R11-07 / #220** key check is root-only | `p3`, `x8` | **FIXED (holds)** | `p3` exit 0 both kinds (178 valid, 0 false positives; 178 nested typos, all named); `x8` exits 1 = `InvalidConfigError … nk.a: 'Entry' (did you mean 'entry'?)`, **which is the assertion** |
| **R11-04 / #218** unbounded `_timer_handles` on `raise(delay=)` | `p5`, `n12` | **FIXED (holds)** | `p5` exit 0 both kinds; `n12` soak: **0 retained handles** across 200 machines × 84 s of 10 ms beating + 40 chaos restores |
| **#206 / #212** delayed self-ping-pong | `x15` | **SUPERSEDED (holds)** | exit 0 both kinds |
| **#212 livelock oracle** | `x6` | **holds** | 500 configs × 2 engines: delayed-cycle async 439 / sync 439, zero-cycle 61 / 61, **PASS** |
| **v3 determinism** | `x11` | **holds** | 50× traces, both engines, both kinds: **one digest** `74e07d063486da18`, invariant across `PYTHONHASHSEED` 0/1/12345 |
| **R11-12** `lane` persisted but not honoured on sync | `x3`, new `n9` | **FIXED** (#233) | `n9`: sync replays `P1,P2,N1,N2` from an interleaved blob, identical to async |
| **R11-11** `structure_hash` omits `raise(delay=)` delays | `x3/C` | **STILL-PRESENT** | `delay=50` and `delay=5000` both hash `8fffa431ddf747da`; **CV-C61 stands** |
| **R11-10** `on_invalid_event` unreachable on restore | `n2`, `x3/D` | **FIXED** (#230) | 640/640 property cases see the refusal on the hook, exactly once per record |
| **R11-01 / D11-persistence-2** (**Blocker**) `"version": 2` mints engine provenance | `x2` | **STILL-PRESENT** | `v2 forged, strict+onUnhandled=error: fired=1 states=['vict.expired'] -> MINTED=YES`; `v2 forged, lax -> MINTED=YES`; `v2 forged onDone -> MINTED=YES`; **`v3` control `MINTED=no`** in all three. Out of scope for #225–#235; `minimum_version=3` still mitigates |
| **R11-02 / R11-03** restore-path provenance/lane forgery | `x3` | **STILL-PRESENT, as designed** | requires writing `"engine": true` or importing a private class — the documented `from_snapshot` trust boundary, **not filed** (R10-01 pattern) |
| **R10-09** `SnapshotMidStepError` reports `child=False` | — | **STILL-PRESENT** | Low, attribution-only, unchanged; not re-run (§4) |

**No prior persistence defect regressed. Two closed this round (R11-10, R11-12), plus the #226 upgrade of R11-09 from "fixed but process-local" to "fixed and durable".**

### 1.1 `p1`'s one `async` miss is the harness, not the library — SUPERSEDED assertion

`p1_parked_rearm_chain.py` failed once on `async` with `hop0 records 0 != 1`: the snapshot taken after a 5–20 ms hold carried **zero** `scheduled_sends` for a 40 ms deadline. Triaged with `q0_p1_flake_triage.py` and `q1`/`q2`:

* **400 clean iterations: 0 misses.** Under synthetic CPU load (`LOAD=1`, 600 iterations): **2 misses**, at elapsed **82.0 ms** and **71.0 ms** against a 40 ms deadline — i.e. the harness's own "hold" overran the deadline.
* In **both** misses the record was in **`pending_events` as `T0`**, not lost: the timer had fired and the event was queued for the next macrostep. `ctx_fired` was still `[]`, so the case looks like a loss only if you inspect `scheduled_sends` alone.
* `q1_fired_window_gap.py` (deadline 40 ms, loop held synchronously busy for 10/39/45/60/80 ms, 15 cases) and `q2_deadline_inflight_loss.py` (slow entry action, snapshot at 4 offsets around the deadline, both kinds) found **0 losses**: every case had the deadline either in `scheduled_sends`, in `pending_events`, or already applied to `context`, and every restore fired `T0` exactly once.

**`p1`'s `hop0` assertion is SUPERSEDED**: it must read `len(scheduled_sends) + len(pending_events)` (or bound the hold below the shortest delay). Rewritten assertion recorded here; the library invariant — *an armed deadline is in exactly one of the three places, never none* — is proved by `q1` + `q2` on both kinds. **No defect.**

### 1.2 `-W error` and the new RuntimeWarning — SUPERSEDED, recorded

No prior script ran under `-W error`, so nothing regressed. But the round-12 note is worth pinning precisely, because it changes how a wrapper's test suite must be written: under `-W error` the #232 warning does **not** become an exception the caller can catch. `n5` shows it is raised inside the receipt's `__del__`, so it reaches `sys.unraisablehook` only — `start()` returns normally, the loop's exception handler is untouched, `status` stays `running`, and the event is still delivered. A `pytest -W error` suite will **not** fail on it; a suite that wants to fail must install an unraisable hook.


---

## 2. New attacks

### 2.1 `n1_latch_restart_chain.py` — #226 latch across N restarts — **PASS both kinds, both engines**

Trip a `maxIterations: 5` two-state self-`raise` cycle, then pass the blob through **6** restore→re-persist hops, then trip again after the last restore.

```
kind=async  fails=[]  VERDICT PASS        kind=def  fails=[]  VERDICT PASS

stage                 trips   latch            msg == original
live                    1     RunawayChainError      -
restore0..restore5      1     RestoredError         True  (x6)
trip_after_restore      2     RunawayChainError   (expected previous+1 = 2)
after_clear             2     NoneType
restore_after_clear     2     NoneType
```

The message that survives every hop is the full original text:
`Machine 'cl' exceeded 5 chained self-generated events in one macrostep and discarded 1 of them. An action raises or sends the event that triggers it; break the cycle or raise 'maxIterations'.`

Four properties, all held: **count monotonic across the restart** (a post-restore trip is `previous + 1`, not 1); **message intact** at hop 6 as at hop 0; **`clear_chain_error()` keeps the count** and clears only the latch; and a **cleared latch does not resurrect** on the next restore (the re-persisted blob writes `last_chain_error: null` while keeping `chain_trips`). Sync engine identical.

*Harness note:* the `sync` engine raises `NotSupportedError: Async action 'bump' not supported by SyncInterpreter` for an `async def` action, so the service-kind axis applies to the async engine only; the script pins `def` on the sync lane and says so inline. That is a documented engine property, not a finding.

### 2.2 `n2_strict_sched_property.py` — #227 + #230 property — **PASS, 640/640**

320 cases × 2 kinds. Each takes a **real** v3 blob, then forges into its `scheduled_sends` lane 1–3 legitimate declared deadlines plus 0–3 undeclared types (`NOPE*`) and, in 40 % of cases with a registered schema, a declared type with a schema-violating payload. Restored with `plugins=[Counter]` on a `strict: True` machine.

```
{"kind": "async", "N": 320, "n_fail": 0, "fails": [], "VERDICT": "PASS"}
{"kind": "def",   "N": 320, "n_fail": 0, "fails": [], "VERDICT": "PASS"}
```

Asserted in every case: declared deadlines fire **exactly once each** (multiset equality, not just membership); **no** undeclared type ever reaches an action; `on_invalid_event` fires **exactly `len(undeclared) + len(bad_payload)` times**; `last_error` is non-`None` in the `start()` window iff a refusal happened and `None` when none did; `status == "running"` — a refusal on either lane never aborts the restore or leaves a half-armed machine. This is the "consistent machine mid-refusal" property the track asked for, at 640 cases.

*Harness note, worth recording for the wrapper:* `event_schemas` values are **callables** (or objects exposing `.validate`), not JSON-Schema dicts — passing a dict makes the library *call* it, which raises `TypeError` and is reported as a payload refusal for **every** event of that type. And schemas are registered via `create_machine(event_schemas=...)`, not via an `"events"` key in the config dict (an `"events"` key is silently ignored — or, under `strict_config=True`, caught by #220). Both cost a debugging cycle here.

### 2.3 `n3_task_identity_matrix.py` — #225 task-identity matrix — **CORRECT on every cell, both kinds**

The decisive oracle: after `start()` the loop is left **idle for 350 ms** and nothing else is sent. An event routed to the internal queue is drained only inside a macrostep, so with the loop idle it would never arrive; an external one arrives.

| Cell | Shape | Expected | Result (async / def) |
|---|---|---|---|
| A | action → `send()` | delivered | `["PING"]` / `["PING"]` |
| B | action → awaited helper coroutine → `send()` | delivered (same task) | `["PING"]` / `["PING"]` |
| C | action → `ensure_future(worker)` → `send()` | delivered (external) | `["PING"]` / `["PING"]` |
| D | action → task → task → `send()` | delivered (external) | `["PING"]` / `["PING"]` |
| E | action → `await send(wait=True)` | `ReentrantWaitError` | `ReentrantWaitError` / `ReentrantWaitError` |
| F | action → `ensure_future(send(wait=True))`, awaited elsewhere | resolves | `wait_ok = true`, `["PING"]` / same |

Cells **C** and **D** are the #225 regression shapes — a worker that outlives its action, and a task of a task. Both are ordinary external traffic now. Cell **E** confirms the guard was narrowed without being removed.

### 2.4 `n8_fleet_spawned_workers.py` — #225 at scale — **PASS both kinds**

```
kind=async  wall 3.5 s      kind=def  wall 1.9 s
part_a  machines 200  kicks 1000  acks 1000  expected 1000  starved 0     (both)
part_b  resolved 100  pending 0  outcomes {"ok": 100}  acks_back 100      (both)
VERDICT PASS
```

**Part A**: 200 machines × 5 rounds; every `KICK` action spawns an `ensure_future` worker that sleeps 10 ms — outliving the action — then sends `ACK` back. After the last round the loop is left idle for a full second. **1000/1000 ACKs delivered, 0 starved.** Pre-#225 every one of these would have been routed to the internal queue and stranded.

**Part B**: 100 concurrent `ensure_future(i.send("KICK", wait=True))` hand-outs against one interpreter whose `KICK` action keeps awaiting after spawning its worker. **100/100 resolve `ok`, 0 pending, 0 spurious refusals, 100 ACKs back.**

### 2.5 `n4` / `n5` — #232 RuntimeWarning content and `-W error` surfacing — **CORRECT**

`n4` (4 modes, warnings captured with `catch_warnings(record=True)` + 3 forced GC passes):

```
drop     -> 1 RuntimeWarning, interpreter.py:2333, event still delivered (log ["B"])
handout  -> 0 warnings
result   -> 0 warnings
cb       -> 0 warnings
```

The message names everything an operator needs:

> send('B', wait=True) on 'rw' was called from inside an action and its receipt was never awaited (#232). A plain `def` action cannot await, so it received this awaitable, not a Receipt. Send without wait=True, or hand the awaitable out (asyncio.ensure_future(...)) to be awaited elsewhere.

Critically, the three supported shapes are **silent** — the warning does not fire on correct code, so it is usable as a CI signal.

`n5` answers "where does it surface under `-W error` inside asyncio?":

```
W = ["error"]
start_exc                 null          <- start() does NOT raise
action_saw                null          <- the action does NOT see it
loop_exception_handler    []            <- the loop handler is NOT called
unraisable                ["RuntimeWarning: send('B', wait=True) on 'rw' ..."]
log                       ["B"]         <- the event was still delivered
status_after              "running"
```

It lands in the receipt's finaliser as an **unraisable**. That is the correct, non-destructive place (it is CPython's own never-awaited-coroutine precedent), but it means `-W error` does **not** convert it into a catchable failure. Recorded as wrapper guidance, not a defect.

### 2.6 `n9_sync_priority_restore.py` — #233 sync priority lane — **PASS**

Blob with `pending_events` persisted in the interleaved order `N1, P1, N2, P2`, the priority records carrying `lane: "priority"`.

```
persisted_order  ["N1","P1","N2","P2"]
expected         ["P1","P2","N1","N2"]
got.sync         ["P1","P2","N1","N2"]
got.async        ["P1","P2","N1","N2"]
fails []  VERDICT PASS      (identical for kind=def)
```

FIFO within the priority lane, whole priority lane ahead of the inbox, and the two engines byte-identical — which is the entire claim of #233 and closes `R11-12`.

### 2.7 `n6` / `n7` — #231 inline-dict `invoke.src` fuzz — **PASS, 33/36 named, 0 TypeError**

12 hostile `src` values (inline machine dict, empty dict, nested dict, deep dict, list, `set()`, `int`, `float`, `bool`, `None`, `bytes`, `tuple`) × 3 positions (root state, nested child state, parallel region) = 36.

```
Counter({'InvalidConfigError(named=True)': 33, 'BUILT-CLEAN': 3})   VERDICT PASS
non_InvalidConfigError: []      <- zero TypeError, zero raw exceptions
```

All 33 name the offending state and the invoke id. The 3 `BUILT-CLEAN` are `src: null` at each position — a distinct, pre-existing path: `n7` shows it logs `Invoke definition in state 'f.run' is missing a 'src' property` at build and then fails at `start()` with `ImplementationMissingError: Service 'None' referenced by state 'f.run' is not registered`, identically under `strict_config=False` and `True`. Loud, not silent — recorded, not filed. (A named `InvalidConfigError` at build would be more consistent with #231's own fix; that is a polish item, not a defect.)

### 2.8 `n10_latch_forgery.py` — forged `chain_trips` / `last_chain_error` — **in-boundary, NOT filed**

Five forgeries in the v3 blob, restored with a hook spy:

| Forgery | Restore | Latch | `on_chain_budget_exceeded` | Normal traffic | After `clear_chain_error()` |
|---|---|---|---|---|---|
| `chain_trips = 10^9` | ok | `RestoredError` | **not fired** | ok | latch `None`, count kept |
| `chain_trips = -5` | ok | `RestoredError` | **not fired** | ok | latch `None`, count kept |
| `chain_trips = "NaN"` | **raw `ValueError`** | — | — | — | — → **D13-persistence-1** |
| count `7`, no message | ok | `None` | **not fired** | ok | — |
| message, count `0` | ok | `RestoredError` | **not fired** | ok | latch `None` |

`boundary_crossings = []`. A forged latch is **inert**: it cannot fire the supervisor hook, cannot drive a transition, cannot survive `clear_chain_error()`, and does not disturb normal traffic. It is reporting-only state inside the documented `from_snapshot` trust boundary (which already applies `state_ids` and `context` verbatim), so per the R10-01 / R11-01 pattern this is **not filed as a security defect**. The one real finding it surfaced — the `"NaN"` row — is filed on *hygiene* grounds, not security (§3.1).

### 2.9 `n11_corrupt_field_hygiene.py` — envelope corruption hygiene — **LEAK on the #226 fields**

13 single-field corruptions of a real v3 blob. Every field that predates #226 is shape-checked and reported as the library's own `SnapshotCorruptError`; the two #226 fields are not.

```
version         'three'      -> SnapshotCorruptError: 'version' 'three' is not an integer.
status          42           -> SnapshotCorruptError: unknown status 42; expected one of [...]
state_ids       'not-a-list' -> SnapshotCorruptError: 'state_ids' must be a list of state-id strings.
context         'not-a-dict' -> SnapshotCorruptError: 'context' is str, expected an object.
pending_events  'nope'       -> SnapshotCorruptError
scheduled_sends 'nope'       -> SnapshotCorruptError
deferred        5            -> SnapshotCorruptError

chain_trips     'NaN'        -> RAW ValueError
chain_trips     [1, 2]       -> RAW TypeError
chain_trips     {'a': 1}     -> RAW TypeError
chain_trips     '12'         -> ACCEPTED, read back as 12      (coerced from a string)
last_chain_error {'a': 1}    -> ACCEPTED, latched as "{'a': 1}"
last_chain_error [1]         -> ACCEPTED
VERDICT LEAK
```

→ **D13-persistence-1** (§3.1).

### 2.10 `n12_soak_v090.py` — soak: 200 machines, heartbeats + spawned workers + external priority + chaos v3 restore with `plugins=` — **PASS both kinds**

**Reduced duration, said out loud:** the task asks for 12 minutes; the hard per-script bound is 120 s, so this runs the **same shape** at **1.4 min per service kind** (2.8 min total). 200 machines, 10 ms `raise(delay=)` heartbeats, an external **priority** producer every 250 ms, `async`-kind actions spawning `ensure_future` workers that send `ACK` back, and a chaos loop that snapshots → restores **with `plugins=[Spy]`** → swaps in the restored machine every 2 s.

```
kind=async  NM=200  MINS=1.4                kind=def  NM=200  MINS=1.4
 rss_kb       32428 -> 32332  (-96)          32332 -> 33000  (+668)
 external     sent 64600  handled 64600  lost 0        (both)
 chaos        ok 40  fail 0  midstep 0  plugin_invalid 0    (both)
 chain_trips_total 0   latched 0                      (both)
 timer_handles_total 0   per-machine 0.0              (both)
 statuses     {"running": 200}                        (both)
 RuntimeWarnings 0                                    (both)
 windows      323                                     (both)
 VERDICT PASS                                         (both)
```

Every invariant holds on both kinds:

* **0 dropped external events** — 64 600/64 600 handled on each kind, all on the priority lane, across 40 chaos restores.
* **Handles flat at literally zero** — better than round 11's 0.690–0.985/machine, because #218's pruner now releases the heartbeat handle as it fires. 323 windows × 200 machines of 10 ms beating retained nothing.
* **RSS flat** — `-96 KB` (async) and `+668 KB` (def) over 84 s and 40 full snapshot/restore/re-persist cycles. No growth at all.
* **`chain_trips` stable at 0** on all 400 machines — the new latch is not noisy under sustained load with chaos restores, and it is not spuriously set by the restore path.
* **0 `RuntimeWarning`s** — #232 does not fire on any supported shape at fleet scale, confirming `n4`'s silence result under load.
* **40/40 chaos restores succeeded**, 0 failed, 0 refused mid-step, and the restore-time `plugins=` spy recorded **0** invalid events (nothing was being forged) — and **0** `on_interpreter_start` calls, which is **D13-persistence-2** observed at scale. The soak's oracle asserts the *observed* count of 0 so that a future fix does not pass unnoticed; the defect is filed separately rather than failing the soak every window.

### 2.11 BENCH-6 — their `production_characteristics.py --quick`, 5 runs

Per the round-12 correction, our own `bench_c_timers` is not the right tool; this is **their** benchmark, §2 = loaded timer lateness.

| busy machines | run 1 | run 2 | run 3 | run 4 | run 5 | median |
|---|---|---|---|---|---|---|
| 0 | +0.1 | +0.2 | +0.1 | +0.1 | +0.1 | **+0.1** |
| 10 | +1.1 | +1.0 | +1.1 | +1.1 | +1.0 | **+1.1** |
| 100 | +10.6 | +9.5 | +10.3 | +10.1 | +10.4 | **+10.3** |
| **500** | **+54.8** | **+54.0** | **+58.3** | **+56.4** | **+55.0** | **+55.0** |

**Distribution at 500 busy machines: min 54.0, median 55.0, max 58.3, spread 4.3 ms.** Against our bar of **≤100 ms p99** the entire observed range clears with ~42 ms of headroom, and the run-to-run spread is small enough that the p99 is not plausibly near the bar. Round 12 measured +89.6 / +94 / +113 / +110 / +111 on the same host and tool — three of five **over** the bar. **This is a ~40–50 % improvement and the first round in which BENCH-6 passes on every reading.** The scaling is clean and roughly linear in machine count (0.1 → 1.1 → 10.3 → 55.0), i.e. lateness tracks total macrostep cost as the benchmark's own note says, with no knee.

---

## 3. Defects

### 3.1 `D13-persistence-1` — **Medium** — a malformed `chain_trips` escapes `from_snapshot` as a raw `ValueError` / `TypeError`

**Repro:** `battle-v0.9.0/persistence/repro/d13_p1_chain_trips_raw.py` (standalone; stdlib + `xstate_statemachine`; run from `<home>`). Exits **1** with 4 raw leaks.

```
envelope version: 3
chain_trips present: True
  chain_trips='NaN'        -> RAW ValueError: invalid literal for int() with base 10: 'NaN'
  chain_trips=[1, 2]       -> RAW TypeError: int() argument must be a string, a bytes-like object or a real number, not 'list'
  chain_trips={'a': 1}     -> RAW TypeError: ... not 'dict'
  chain_trips='1e3'        -> RAW ValueError: invalid literal for int() with base 10: '1e3'
  control deferred=5 -> SnapshotCorruptError (the contract)
  last_chain_error={'not': 'a message'} -> latched as "{'not': 'a message'}"

VERDICT: REPRODUCED (4 raw leaks)
```

**Site:** `src/xstate_statemachine/base_interpreter.py:1993`

```python
interpreter.chain_trips = int(snapshot.get("chain_trips") or 0)
```

and `:1994-1996`, which `str()`s whatever `last_chain_error` holds without a type check. Both run **after** the snapshot validator, which knows nothing about the two fields #226 added.

**Why it matters.** The documented restore contract is "shape errors come back as `SnapshotCorruptError`", and every pre-#226 field honours it — `version`, `status`, `state_ids`, `context`, `pending_events`, `scheduled_sends`, `deferred` all produce a named, catchable `SnapshotCorruptError` under the same corruption (`n11`, 7/7). A production restore loop written to that contract —

```python
try:
    i = Interpreter.from_snapshot(blob, machine, minimum_version=3)
except SnapshotCorruptError:
    quarantine(blob); i = fresh()
```

— does **not** catch a corrupt `chain_trips`, so a truncated or partially-written journal record (exactly what a crash mid-write produces, and exactly what the quarantine path exists for) escapes as an unexpected exception type and takes down the restore worker instead of quarantining one blob. Every other field in the same envelope is protected; this is the newest one.

Two sub-behaviours worth naming: `chain_trips: "12"` is **silently coerced** from a string to `12` (no other field accepts a type-punned value), and `last_chain_error: {"a": 1}` is accepted and latched as the literal text `"{'a': 1}"` — a dict where a message string is specified, stringified into an operator-facing diagnostic.

**Severity Medium, not High:** it needs a corrupt blob to trigger, and the failure is loud (an exception either way) rather than silent. It is not a security issue — a party who can write `chain_trips` can already write `state_ids` (§2.8). It is a **contract inconsistency in the round's own new field**, and the fix is a shape check alongside the existing ones.

### 3.2 `D13-persistence-2` — **Medium** — `on_interpreter_start` never fires on a restored interpreter, on either engine, via `plugins=` or `.use()`

**Repro:** `battle-v0.9.0/persistence/repro/d13_p2_start_hook_restore.py` (standalone). Exits **1**.

```
async fresh  .use()           -> ['start', 'stop']
sync  fresh  .use()           -> ['start', 'stop']
async restored plugins=       -> ['stop']
async restored .use()         -> ['stop']
sync  restored plugins=       -> ['stop']

missing on_interpreter_start on: ['async restored plugins=', 'async restored .use()', 'sync restored plugins=']
VERDICT: REPRODUCED
```

**Site:** `src/xstate_statemachine/interpreter.py:588-620` — the `♻️ Resume a snapshot-restored interpreter` branch — returns `self` at `:620`, **before** the plugin notification loop at `:664`:

```python
for plugin in self._plugins:
    plugin.on_interpreter_start(self)
```

`SyncInterpreter` has the same shape twice: `sync_interpreter.py:311-332` (the `restart_services` / `restart_timers` resume) and `:333-347` (the persisted-inbox resume), both returning before `:388`.

**Why it matters.** The hook's own docstring says *"Called when the interpreter's `start()` method begins… useful for setup tasks, such as connecting to a database, initializing a metrics counter, or logging the start time."* And `start()` is, by the library's own design note at `interpreter.py:583-590`, **the documented way to resume a restored actor** ("Detecting that shape and attaching a loop makes `start()` the documented way to resume a restored actor"). So a plugin that opens a resource, registers the actor with a supervisor, starts a latency timer, or emits a lifecycle metric in that hook is **silently skipped for every restored machine** — and in a restart-heavy deployment, restored machines are most of them. `n12` observes it 40/40 times at fleet scale.

The asymmetry makes it worse than a no-op: **`on_interpreter_stop` does fire**, so a lifecycle plugin sees an unmatched `stop` with no preceding `start`. A naive counter goes negative; a resource-tracking plugin closes a handle it never opened.

It also partly undercuts **#230**, which is the round's own fix. `from_snapshot(plugins=...)` was added so that plugins are registered *before* the persisted events are admitted and a restore-time refusal reaches `on_invalid_event`. That works (`n2`, 640/640). But the one other thing a caller naturally expects from "my plugins are attached early" — the lifecycle hook — is precisely what the resume branch skips, and passing `plugins=` gives no different result from `.use()`.

**Severity Medium:** no state is corrupted and no event is lost; the damage is to observability and to resource lifecycles owned by plugins. It is deterministic, affects both engines and every restore, and has no workaround inside the plugin API (a caller must call the hook manually after `from_snapshot`, which defeats the point of `plugins=`).

### 3.3 Not filed

* **Forged latch fields** (§2.8) — inert inside the documented `from_snapshot` trust boundary; `boundary_crossings = []`. R10-01 pattern.
* **`invoke.src: null`** (§2.7) — WARNs at build, dies loudly at `start()` with `ImplementationMissingError`. Not silent; a build-time `InvalidConfigError` would merely be tidier.
* **`p1`'s async miss** (§1.1) — harness timing; the event was in `pending_events`. Assertion rewritten, library invariant proved by `q1`/`q2`.
* **`-W error` unraisable** (§2.5) — correct CPython-precedent placement; recorded as wrapper test guidance.
* **`R11-02` / `R11-03`** restore-path provenance and lane forgery — unchanged trust-boundary cases.

---

## 4. Not covered / limits

| Area | Why, and what stands in for it |
|---|---|
| **The full 12-minute soak** | Exceeds the hard per-script bound (≤120 s) and the ≤20 min task bound. `n12` runs the **same shape** — 200 machines, 10 ms `raise(delay=)` heartbeats, external priority producer, action-spawned workers, chaos v3 snapshot/restore with `plugins=` — at **1.4 min per service kind**. **Said out loud:** a true 12-min run is the one thing this track did not execute. The handle/RSS invariant is independently covered at 200-machine scale by `p5`, and `n12` integrates 40 chaos restores per kind. |
| **Livelock fuzz at ≥500 configs with *new* round-12 rules** | `x6` re-run at 500 configs × 2 engines against the **#212** oracle (PASS, 439/439 + 61/61). #225–#235 did not change the livelock rules — the round's chain-related change (#226) is about *persisting* the trip, not about *when* it trips — so the existing oracle is still current. A fuzzer written against a changed oracle was therefore not needed. |
| **Config fuzzer beyond `invoke.src`** | `n6` covers the round's own new refusal (36 cases, 0 `TypeError`); `p3` re-run covers the general recursive key grammar (178 valid + 178 mutated, 0 false positives, all named). A combined generator over both axes was not built. |
| **Determinism including `chain_trips` in the digest** | `x11` re-run gives one digest (`74e07d063486da18`) across 50 runs × 2 engines × 2 kinds, hash-seed independent — but its digest predates #226 and does **not** include `chain_trips`. `n1` covers latch determinism separately and exactly (same count and same message at every one of 6 hops, both engines, both kinds). A single digest spanning both was not produced. |
| **`SnapshotMidStepError` child attribution (R10-09)** | Not re-run; Low, attribution-only, out of scope for #225–#235. Carried STILL-PRESENT. |
| **`SimulatedClock` deadline properties** | `R11-W-3` stands: `SimulatedClock` does not fire restored `scheduled_sends`. Every deadline property here (`p1`, `q1`, `q2`, `n2`, `n12`) used the **real** clock, which is what bounds the case counts. |
| **Cross-process / on-disk durability** | Out of scope; every round-trip here is in-process JSON, which is the documented `from_snapshot` boundary. |
| **`R11-01` fix verification** | Not attempted — round 12 did not target it. Re-reproduced unchanged (`x2`) and carried into the verdict. |
| **PyPI artefact** | `v0.9.0` is **not published**; nothing was validated against an installed wheel. If the wheel's `__init__` exports drift from the clone, that is unverified here — though the new `publish.yml` smoke test (the only `main`-vs-tag delta) is designed to catch exactly that. |

---

## 5. Wrapper constraints — deltas

**Retire (the library now does this):**

* **CV-C63** — "`chain_trips` / `last_chain_error` do not survive a snapshot; mirror them into the wrapper's own envelope" → **#226 fixed**. `n1` proves the count is monotonic across 6 restarts and the message comes back verbatim as a `RestoredError`, on both engines and both kinds. The wrapper can drop its shadow copy.
* **"Never depend on restored event ordering on the sync engine"** (the `R11-12` half) → **#233 fixed**. `n9` shows both engines replay an interleaved blob as `P1,P2,N1,N2`. The *other* half of that constraint — `lane` is forgeable in a hostile blob — stands, but that is the trust boundary, not an ordering bug.

**Keep, unchanged:**

* **`from_snapshot(minimum_version=3)` is mandatory on every restore.** `R11-01` is live at `v0.9.0`; `x2` still mints an engine `after` that fires a 600 s timer instantly and an engine `done.invoke` that drives `onDone`, from a forged `"version": 2` blob, under both `strict: True` + `onUnhandled: "error"` and a lax machine. The `v3` control refuses all three. This is the single Blocker-class item on the surface and the mitigation is one argument.
* **CV-C61** — the wrapper's own contract fingerprint must hash `raise(delay=)` params; `structure_hash` still collides `delay=50` with `delay=5000` (`x3/C`, `8fffa431ddf747da` both).
* **R11-W-1** (stable `send_id` on every catalogue deadline), **R11-W-2** (never shadow a built-in action name), **R11-W-3** (real clock for deadline tests).
* **CV-C64** — an action must never `await interpreter.send(..., wait=True)` on its own interpreter. Still correct, and #225 **narrowed** the refusal rather than widening it: a spawned worker and a task-of-a-task are now ordinary external traffic (`n3` C/D, `n8` 1000/1000), so the catalogue lint only needs to find the *in-step* self-await, not every self-send from an action's descendants.

**New:**

* **CV-C65 — wrap `from_snapshot` so a corrupt blob always surfaces as one exception type.** `D13-persistence-1`: a malformed `chain_trips` escapes as raw `ValueError` / `TypeError`, so `except SnapshotCorruptError` is not sufficient to quarantine a bad journal record. Until fixed, catch `(SnapshotCorruptError, ValueError, TypeError)` at the restore boundary — and validate `chain_trips` / `last_chain_error` types in the wrapper before handing the blob over, since the library also coerces `"12"` → `12` and stringifies a dict message.
* **CV-C66 — never put resource acquisition or lifecycle accounting in `on_interpreter_start`.** `D13-persistence-2`: it does not fire on a restored interpreter on either engine, via `plugins=` or `.use()`, while `on_interpreter_stop` does — so a plugin sees an unmatched stop. Do setup at construction or immediately after `from_snapshot(...)`/`start()` in the wrapper's own restore function, and treat `on_interpreter_start` as a fresh-boot-only signal.
* **CV-C67 — a `-W error` test suite must install `sys.unraisablehook` to catch the #232 warning.** It is raised in the receipt's finaliser, so `-W error` neither fails `start()` nor reaches the loop exception handler (`n5`). Without the hook, a `def` action that drops a `wait=True` receipt passes CI silently.
* **Recorded for the catalogue loader (not a constraint, a correction):** `event_schemas` values are callables, not JSON-Schema dicts, and are registered through `create_machine(event_schemas=...)` — an `"events"` key in the config is not the schema surface (§2.2).

---

## 6. Verdict

**ADOPT with constraints.**

Round 12 is a clean, complete round on this surface: five persistence-relevant fixes (#226, #227, #230, #231, #233) all reproduce as advertised on both service kinds and both engines, with **zero regressions** across the prior-defect sweep, two prior findings closed (`R11-10`, `R11-12`), and one wrapper constraint retired (`CV-C63`). The two fixes that matter most operationally are not merely patched but complete: the chain-trip latch is durable across **six** restore hops with the count monotonic and the message intact, and the `scheduled_sends` strict/schema lane is proved consistent under **640** property cases of forged records, with `on_invalid_event` firing exactly once per refusal and the machine always left running. #225's task-identity rewrite is correct on all six matrix cells and holds at 200 machines × 1000 worker-spawned sends with zero starvation — the class of bug that hung a production machine in round 11 is gone, and the guard that replaced it refuses nothing it should allow. The soak is the cleanest this track has recorded: 64 600/64 600 external events on each kind, **zero** retained timer handles, flat RSS, zero spurious chain trips, zero warning noise, 40/40 chaos restores. And **BENCH-6 clears our ≤100 ms bar on all five readings for the first time** (median 55.0 ms vs round 12's 89.6–113).

Against that, three things hold the verdict at *conditional*:

1. **`R11-01` is still live and still a Blocker.** A forged `"version": 2` blob still mints engine provenance — a 600 s `after` that fires instantly, a `done.invoke` that drives `onDone` — under strict machines and lax ones alike, where the `v3` control refuses all of it. Round 12 did not target it. `from_snapshot(minimum_version=3)` on **every** restore remains mandatory and non-negotiable.
2. **Two new Medium defects, both in the surface this round introduced.** `D13-persistence-1` breaks the envelope's own corruption contract for the one field #226 added, so the documented quarantine-on-`SnapshotCorruptError` pattern has a hole exactly where a crash-truncated journal record lands. `D13-persistence-2` means `on_interpreter_start` never fires for a restored machine on either engine — with `on_interpreter_stop` still firing, so lifecycle plugins see unmatched stops — which also blunts #230, the round's own plugin fix, for everything except the refusal path it was written for. Neither loses state or events; both are deterministic, both are one-line-shaped fixes, and both are covered by a new wrapper constraint (`CV-C65`, `CV-C66`) in the meantime.
3. **The release is not on PyPI**, so nothing here was validated against a published artefact.

With `minimum_version=3`, `CV-C61`, `CV-C64`–`CV-C67` and the surviving `R11-W-*` constraints in place, the persistence surface at `v0.9.0` meets the financial-OMS standard. The wrapper's burden goes **down** again this round — one constraint retired and one narrowed (`CV-C64`) against two added, with the two additions being defensive wrappers around defects that are cheap to fix upstream.
