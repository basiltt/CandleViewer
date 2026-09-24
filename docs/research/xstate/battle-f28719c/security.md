# Battle-test — SECURITY track — re-run on `f28719c`

**Build under test.** `_ref/xstate-statemachine` @ **`f28719c`** (merge #202,
"0.8.1 round-8": #192–#201 + reopened #181/#186). `__version__` still `0.8.0`;
keyed on commit per convention. Windows 11, `.venv-main`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Re-run of `battle-6db65d8/security/`
(13 scripts, copied verbatim — none needed a `common2` inline fix, none
imported it) plus new attacks on round-8's machinery. **Time-budgeted**
(whole task ≤20 min): livelock fuzz run at N=120 (not ≥500); the 12-min
async soak was **not run** (see Not-Covered). No library source modified;
no `git` in the adopting repo; no `gh` calls.

---

## 1. Prior-defect re-run (13 scripts, both service kinds where applicable)

| ID | 6db65d8 result | f28719c result (this pass) | Status |
|---|---|---|---|
| D6-security-1/#185 (null `machine_hash` on versioned blob) | FIXED | `attack_snapshot_corrupt_fuzz.py`: `mutations=300 accepted_bad=0 uncontrolled=10` (all 10 the documented #185 `SnapshotDriftError` message, verbatim). | **FIXED, holds** |
| D6-security-2 (`send_threadsafe(internal=True)` forgery) | STILL-PRESENT (informational) | `attack_threadsafe_forgery.py` (def): `bump_count=200 status=running`; `attack_threadsafe_forgery_async.py` (async def): `bump_count=1 status=running`. Unchanged. | **STILL-PRESENT, unchanged (informational, both kinds)** |
| #157 (loop-side RAISE refusal observability) | FIXED | `attack_raise_refusal_exactly_once.py`: `refused_futures=199 queue_full_hook_fires=199`, still 1:1. | **FIXED, holds** |
| Async chain-budget under concurrent external load (#166-168/#179/#180) | FIXED, held | `attack_chain_budget_concurrent_external.py`: baseline tripped=True; 16 senders (1784 delivered) concurrent: still tripped=True. | **FIXED, holds** |
| Async-engine livelock (nested_invoke/rollback_ondone/always_cycle/sendto_self) | FIXED by #179 (0/120 RUNAWAY) | `attack_livelock_config_fuzz.py` re-run N=120 (reduced, time budget): `sync:settled=120/120 async:settled=120/120`, 0 DEFECT/RUNAWAY. | **FIXED, holds (still reduced-N; see Not-Covered)** |
| Persistence-hook snapshot never torn | FIXED, held | `attack_hook_snapshot_never_torn.py`: `n=300 refused=600 legal=300 torn=0`. | **FIXED, holds** |
| Persistence quiescence property | FIXED, held | `attack_persistence_quiescence_property.py`: `events=500 mid_step_at_quiescence=0 roundtrip_failures=0`. | **FIXED, holds** |
| Semantics 4-way matrix (guard-crash/denied/deferred/unhandled) | FIXED, held | `attack_semantics_matrix.py`: all assertions pass, incl. `Receipt.denied` discrimination and the round-7 `guardErrorPolicy-raise-fallback` contract note. | **FIXED, holds** |
| `{"type":"GO"}` bypasses `InvalidEventError` | resolved-by-design | `attack_invalid_event_hostile.py`: identical, 8/9 hostile shapes raise, dict-event accepted. | **UNCHANGED, resolved-by-design** |
| `service_pool_size` concurrency / `stop()` mid-service | FIXED, held | `attack_concurrency_service_executor.py`: `runs=200 errors=0 statuses={'stopped'}`, threads flat 1→1. | **FIXED, holds** |
| Hook matrix `on_plugin_error`/`on_resolve_error` | unchanged/documented | `attack_hook_matrix_observability.py`: identical. | **UNCHANGED** |
| Engine-completion-marker forgery (Event subclass / `dataclasses.replace` / `internal=True` / captured-DoneEvent resend) | no forgery surface found (6db65d8) | `attack_engine_completion_marker_forgery.py`: `engine_completion` still a call-site-only kwarg on `_deliver_priority`/`_publish_completion`, not exposed on public `send()`, not read off the `Event` instance. Same result. | **UNCHANGED — no forgery surface (holds)** |
| D-security-2..5 (branch protection, mutable-tag Actions, no SBOM/signing, `except: pass`) | CARRIED FORWARD | Not re-queried (no `gh api`; time budget). | **CARRIED FORWARD, NOT RE-VERIFIED** |

**All 12 re-runnable prior defects/probes: same verdict as `6db65d8`.** No
regression. No `common2` import existed in any of the 13 scripts (all use
`sys.path.insert(0, "src")` + direct `xstate_statemachine` imports), so no
inlining was needed for this batch.

---

## 2. New attacks — round-8 machinery (#192–#201)

| Attack | Script | Result |
|---|---|---|
| **#192 priority-lane provenance survives snapshot/resume; forged `"engine": true`; v1 state_ids-only restore** | `attack_priority_provenance_roundtrip.py` | Resume after an external-priority-send-in-flight snapshot succeeds cleanly (`{'m.b'}`, no raise). `restore_event()` on a hand-built `{"kind":"done","engine":true,...}` dict **does** mint an engine-trusted `DoneEvent` — but this is the **documented** #195 trust boundary (whoever writes the snapshot store already controls `state_ids`/`context` per #185); not a new bypass of a *different* boundary, and not independently exploitable without already controlling the store. v1 (no `machine_hash`) restore is **refused** as `SnapshotDriftError` (#185's version-keyed bypass fix holds for v1 too). |
| **#192 external priority producer during a self-generated `always`/`always` chain, both engines** | `attack_192_external_priority_load.py` | sync: 282 external priority sends attempted during the self-generated chain, chain still **trips** `RunawayChainError`, 0 send-side exceptions (0 dropped observed). async: 351 sends, same result. Confirms #192's provenance-based shed (only self-generated items shed) holds under concurrent external load on both engines. |
| **#193 def-service arm-then-rollback, 200 cycles** | `attack_193_defservice_rollback.py` | A def-service armed by a transition whose entry action then raises (`actionErrorPolicy: rollback`) is cancelled before the executor submission on **every one of 200 cycles** — `service_calls_leaked=0`. This is the exact symptom the round-8 register's R8-02/finding-3 ("not unwound by rollback") described against the pre-#193 code; on `f28719c` it does not reproduce. |
| **#194 `children_timeout` per-child, not aggregate, WARNING always fires** | `attack_194_children_timeout_per_child.py` | 5 invoked child-machines with a blocking (`asyncio.sleep`) entry action past the 0.3s bound: `start()` returns at ~0.32s (not ~1.5s aggregate), machine keeps running, and the documented WARNING (`"...invoked child bring-up exceeded the 0.300s children_timeout (0.315s elapsed, 5 still starting)..."`) fires. Confirms #194's per-child semantics and always-on WARNING. |
| **#198 configuration/state_ids agreement, one-sided-emptying attacks** | `attack_198_configuration_agreement.py` | 4 mutations that previously (R8-08, pre-#198) laundered an emptied field: `state_ids=[]`, `configuration` key removed, `configuration=[]`, and a cross-contradiction (`configuration@a` vs `state_ids@d`) — **all four now refused** as `SnapshotCorruptError`. #198's "both fields present and non-empty on a running v>=1 snapshot" rule holds. |
| **#199 `on_interpreter_start` snapshot, both engines** | `attack_199_oninterpreterstart_snapshot.py` | A plugin's `on_interpreter_start` hook calling `get_snapshot()` is **refused** with `SnapshotMidStepError` on both the sync and async engines. Confirms the in-flight flag is up before the hook fires on both engines (#199). |
| **livelock fuzzer, both engines/kinds, N=120 (reduced)** | `attack_livelock_config_fuzz.py` (reused) | `sync:settled=120/120 async:settled=120/120`, 0 DEFECT — same as `6db65d8`. Not re-run at the brief's ≥500 (time budget; see Not-Covered). |

No new defect is filed by this pass: every attack against round-8's new
machinery (#192 provenance-shed under load, #193 rollback cancellation,
#194 per-child timeout, #198 agreement rule, #199 in-flight window) held
under the attacks attempted. The completion-marker forgery attempt again
found no reachable surface (unchanged from `6db65d8`).

---

## 3. Defects filed this track

**None.** All prior defects hold their `6db65d8` classification; every new
attack against round-8's machinery confirmed the CHANGELOG's fix claims
under adversarial conditions rather than finding a bypass. D6-security-2
(the informational `send_threadsafe(internal=True)` honesty-based trust
boundary) remains open but unchanged — it is documented, not a regression.

---

## 4. Not-covered this pass (time budget)

- **12-minute async soak** (200 machines, async services + external
  priority producer + rollback+onDone + always→invoke + chaos snapshot at
  quiescence) — **not run**. The 20-minute wall-clock bound was spent on
  the 13-script prior-defect re-run + 6 new round-8-targeted attacks +
  the reduced-N livelock fuzz.
- **Livelock fuzz at full N≥500** — ran N=120 only (same as `6db65d8`'s
  reduced pass); recommend a dedicated follow-up at full N.
- **External priority sends at 10k/s sustained** — this pass's producer
  ran ~280-350 sends over a 1s window per engine (8 threads × ~0.5ms sleep
  loop), well under 10k/s; recommend a dedicated throughput probe.
- **`_chain_owed`/#200 task-keyed ledger under 100 concurrent
  never-completing coroutine services + `stop()`** — not independently
  attacked this pass; the closest proxy remains
  `attack_concurrency_service_executor.py` (200 blocking `def` services),
  which does not exercise the async coroutine ledger specifically.
- **Property-based fuzz ≥300 random machines incl. parallel + children**
  for the persistence round-trip — not run as a dedicated Hypothesis
  suite this pass; only hand-built shapes were exercised
  (`attack_priority_provenance_roundtrip.py`, `attack_198_...py`).
- **Determinism: 50× identical traces both engines/kinds incl. trip laps;
  hash-seed sweep** — not run this pass.
- **`__slots__`/redaction fresh hostile-key fuzz** — not re-exercised as a
  runtime attack this pass (was source-inspected only at `6db65d8` and not
  revisited here); no new attribute surface was observed in the round-8
  diff (`priority_queue` items gained a provenance tag, not a new public
  attribute).
- **D-security-2..5** (branch protection, mutable-tag Actions, no
  SBOM/signing, `except: pass`) — carried forward, unverified live
  (no `gh api`, standing constraint).
- **Construct `engine_done` via import path / `dataclasses.replace` /
  pickle** — only the `restore_event()`-from-JSON-dict vector and the
  public-`send()`-surface vector were attempted this pass; a direct
  `pickle.loads` of a crafted `_EngineDone` byte stream and an explicit
  `dataclasses.replace` on a captured instance (the events are
  `NamedTuple`+`__slots__`, not dataclasses, so `dataclasses.replace`
  does not apply — confirmed by inspection, not by a runtime script) were
  not separately scripted.

---

## 5. Verdict

**No new exploitable defect found in round-8's new machinery** (#192
provenance-based priority-lane shed/charge, #193 def-service rollback
cancellation, #194 per-child `children_timeout`, #195 engine-minted event
subclasses, #196 eventless-only settle selection, #198 configuration/
state_ids agreement, #199 in-flight-window coverage of
`on_interpreter_start`, #200 task-keyed `_chain_owed`, #201 lap-parity).
Every prior security-track defect from `6db65d8` re-runs to the identical
verdict on `f28719c` (12/13 scripts re-confirmed FIXED-or-documented,
D6-security-2 STILL-PRESENT-and-unchanged, governance findings carried
forward unverified). Every new attack targeted specifically at this
round's fix set (provenance-under-load, rollback-under-concurrency,
per-child-timeout, agreement-rule-laundering, in-flight-window,
completion-marker-forgery) came back holding, not bypassed. Coverage was
reduced under the 20-minute wall-clock bound — the 12-minute soak, full-N
livelock/`_chain_owed`/10k/s producer attacks, a dedicated Hypothesis
property suite, and the determinism/hash-seed sweep are recommended
follow-ups (§4) before treating this track as exhaustive for round 8.
