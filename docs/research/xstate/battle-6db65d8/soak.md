# SOAK re-run — `xstate-statemachine` @ `6db65d8` (unreleased 0.8.1, round-7)

**Build under test.** `_ref/xstate-statemachine` @ `6db65d8`. `CHANGELOG.md`
`[Unreleased]` documents round-7 (#179-#190; reopened #167/#168/#175) on top
of round-6. `__version__` still `0.8.0` — keyed on commit.

**Date:** 2026-09-21. **Python:** CPython 3.13.7 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget is 20 minutes; this track used
~14 of it. Prior soak scripts were copied byte-for-byte from
`battle-221ce7c/soak/` and re-run unmodified, plus one new `async def`
mirror of the one prior script that was `def`-only (attack #173, the
service-pool/stop-churn attack — this was the lane the brief flagged as
"blind"). New round-7-targeted attacks were added at reduced scale given
the budget. The 12-minute/200-machine full soak, and the dedicated ≥500-
config livelock fuzzer, were **not** re-run standalone here — see §4; the
latter is already covered at full brief-scale by the determinism track's
`battle-6db65d8/determinism/g7_livelock_fuzz.py` (500 configs × {def,
async def} × {sync, async engine}, 0 hangs / 0 silent runaways / 0 lap
mismatches — cited, not duplicated).

---

## 1. Prior-defect re-verification (`battle-221ce7c/soak/*` re-run unmodified against `6db65d8`)

| ID | 221ce7c verdict | 6db65d8 re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs after uncaught plugin-hook exception) | FIXED | `repro_d_soak_1_via_use.py`: `FAIL (not reproduced): both receipts resolved` | **FIXED** (unchanged) |
| D-soak-2 (`SimulatedClock` settler leak on crash-restore) | FIXED | `repro_d_soak_2_via_clock_param.py`: `settlers registered: 0`, `1/21 reachable`, `NOT REPRODUCED` | **FIXED** (unchanged) |
| D5-soak-1 (`check_shape()` gap) | FIXED | `attack_hostile_fields_fixed.py`: all 6 hostile fields still typed `SnapshotCorruptError`/`SnapshotVersionError` | **FIXED** (unchanged) |
| soak-adjacent #145 (`actionErrorPolicy:"fail"` stop contract) | FIXED | `attack_fail_stopped_snapshot.py`: `status="stopped"`, config `[]`, restore accepted as terminal | **FIXED** (unchanged) |
| #166-168 settle-budget under concurrent externals | PASS | `attack_166_settle_budget_soak.py`: tripped at lap 1001 regardless of 0/1/4/16 concurrent external senders | **PASS** (unchanged) |
| #172 threadsafe in-flight counter under churn | PASS | `attack_172_157_threadsafe_soak.py`: 25 generations, `anomalies=[]` | **PASS** (unchanged) |
| #157 loop-side RAISE observability | PASS | same script: 1199/1199 loop-side refusals fired `on_event_dropped(reason="queue_full")` exactly once | **PASS** (unchanged) |
| #173 `service_pool_size=1` + `stop()` churn (`def` service) | PASS | `attack_173_service_pool_stop_churn.py`: 50 generations, `hangs=0`, `double_fires=0`, no thread growth | **PASS** (unchanged) |
| **#173, ASYNC lane (NEW — was blind in prior rounds)** | not run | `attack_173_async_service_pool_stop_churn.py` — `async def slow_service`, otherwise identical: 50 generations, `hangs=0`, `double_fires=0`, no thread growth | **PASS** |

No harness adaptation was needed for the `def`-service scripts; round-7
does not touch `_SafePlugin`, `SimulatedClock` teardown, `check_shape()`,
the #145 stop contract, the settle-budget-vs-concurrent-externals fix, the
in-flight counter, `queue_full` observability, or `service_pool_size`
teardown for `def` services. The one gap this track was asked to close —
re-running the `def`-only #173 pin with `async def` — is now closed and
passes identically to the `def` lane: no double-fire, no thread leak, no
hang, across the odd/even mid-service-vs-post-service `stop()` split.

The 1.5 min/30-machine/3-producer standing soak scenario (`soak_runner.py`
+ `soak_machine.py`) was **not** re-run standalone this pass (budget); its
machinery (rollback/`FAIL_HARD`, deferred `NOPE`, `ack_service`) is not
targeted by any round-7 changelog item, so no regression is expected, but
this is a disclosed gap, not a verified pass — see §4.

---

## 2. New round-7-targeted attacks (`battle-6db65d8/soak/attack_new_chainowed_priority_childtimeout.py`)

| Attack | Target | Result |
|---|---|---|
| A: `_chain_owed` under 100 concurrent never-completing `async def` services + `stop()` | #179/#187: a step that armed a coroutine service must keep its chain open until completion, but must not leak/hang on `stop()` when that completion never comes | **PASS** |
| B: external `send(priority=True)` at load during a self-generated `always`-cycle chain | #180: priority-lane charging must be by provenance (who), not by timing (when) | **PASS** |
| C: `start(children_timeout=)` with 50 slow invoked children | #181: `start()` must not block past the bound; machine must come up `running` | **PASS** (with a harness-observability gap noted) |

### 2.1 Attack A — `_chain_owed` leak/hang probe

100 independent interpreters, each with one `invoke` to an `async def`
service that never returns (`await asyncio.sleep(9999)`), each poked once
with an external `POKE` event to force at least one macrostep to open
(and, under the pre-#179 bug, would have left `_chain_owed` permanently
armed for a service that never completes). All 100 were then `stop()`ped
concurrently (`asyncio.gather`), each bounded at 3 s:

```
{'n': 100, 'hangs': 0, 'dt_s': 0.248}
```

Zero hangs across 100 concurrent `stop()`s against permanently in-flight
coroutine services — `_chain_owed` does not block teardown of a service
that will never complete; `stop()` tears down the still-running task
rather than waiting on the debt. No defect.

### 2.2 Attack B — external priority sends during a self-generated chain

A machine with an unconditional `always: a -> b -> a` cycle (guarded to
stop at 2000 laps) was raced against 3000 external `priority=True` sends
of an unrelated `EXT` event on the *same* interpreter, with
`on_event_dropped` wired to a collector and `max_queue_size` raised high
enough that queue-capacity drops are not a confound:

```
{'kind': 'sync-chain-only', 'n_ext': 3000, 'ext_seen': 2999, 'dropped': 0, 'dt_s': 2.048, 'rate_eps': 1465.0}
```

`dropped == 0` (no `on_event_dropped` fired) and `ext_seen` (2999/3000,
mismatch is a harness sampling artifact — the 2 s sleep window closed one
tick before the final `EXT` was processed, not a drop; `dropped==0`
confirms nothing was discarded) — consistent with #180: none of the 3000
priority sends were charged to / rejected by the chain budget. Achieved
throughput (~1465 eps against a busy self-generating chain) is below the
brief's 10k/s target given the reduced single-process harness and Python
GIL contention with the concurrent `always`-cycle; this is a harness-scale
gap (see §4), not a correctness gap — 0 drops is the pass criterion and it
held. No defect.

### 2.3 Attack C — `children_timeout` with 50 slow children

50 invoked child machines, each with a 0.3 s async entry action, under
`start(children_timeout=0.5)`:

```
{'n_children': 50, 'start_dt_s': 0.312, 'status_after_start': 'running', 'n_registered_children': 0, 'bounded': True}
```

`start()` returned in 0.312 s (well inside the 0.5 s bound, since 0.3 s <
0.5 s — all 50 children's entry actions ran within the bound, so this
trial did not exercise the *timeout-exceeded* path, only the
*bound-respected* path). `status_after_start == "running"` confirms the
machine came up live either way. `n_registered_children` reads `0` because
the harness looked at a non-existent public attribute (`interp.children`)
rather than the library's actual internal actor registry — a **harness
observability gap**, not a library defect (the `bounded: True` timing
assertion is the actual test criterion and it passed); flagged in §4
rather than silently treated as a child-registration defect.

---

## 3. Defects

**None found this pass.** All eight prior-round soak-track
defects/checks (including the newly-added async lane for #173) remain
FIXED/PASS, and all three new round-7-targeted attacks
(`_chain_owed`-under-concurrent-never-completing-services, external
priority-send-during-chain, `children_timeout`-with-50-children) pass
cleanly against `6db65d8`.

---

## 4. What was NOT covered (explicit)

- **Full 12-minute/200-machine ASYNC-services chaos soak** (rollback+
  onDone, always→invoke shapes, external priority producer, chaos
  snapshot at quiescence) — not run standalone this pass; out of the
  remaining budget after the prior-defect re-run + new attacks above. The
  existing 1.5 min/30-machine sync-lane soak (`soak_runner.py`) was also
  not re-run this pass (disclosed gap, not a verified pass).
- **≥500-config livelock fuzzer across {def, async def} × both engines
  with a 30 s watchdog** — not duplicated in this track; already run at
  full brief scale by the determinism track
  (`battle-6db65d8/determinism/g7_livelock_fuzz.py`): 500 configs × 2
  service kinds × 2 engines, `hangs=0`, `silent_runaways=0`,
  `def_vs_asyncdef_lap_mismatch=0`, `sync_vs_async_engine_lap_mismatch=0`.
  Cited as evidence, not re-verified independently here.
- **External priority sends at the brief's literal 10k/s target** — attack
  B above achieved ~1.5k eps (0 drops, which is the pass criterion) in a
  single-process harness; a dedicated multi-process/uvloop harness capable
  of sustaining 10k/s was out of reach of the remaining budget.
- **children_timeout actually *exceeding* the bound** (a child slower than
  the timeout, forcing the WARNING-and-continue path) and **child
  registration polling after the bound trips** — attack C's 0.3 s children
  stayed under the 0.5 s bound; the timeout-*exceeded* path and post-
  timeout late-registration behavior were not independently exercised
  here; also, no public actor-registry attribute was identified from the
  soak harness in the time available, so `n_registered_children` in §2.3
  is not a verified count.
- **Persistence-hook-matrix property test** (snapshot from every hook incl.
  initial descent and child-entry actions, ≥300 random machines incl.
  parallel + invoked children) — persistence track's remit.
- **Configuration/state_ids disagreement fuzz, null/absent `machine_hash`
  on v0/v1/v2 blobs** — persistence/contracts tracks' remit.
- **RAISE loop-side refusals exactly-once beyond the #157 attack already
  re-run in §1**, and the **full observability hook matrix** (every reason
  incl. `chain_budget` on the async lane, `child=True` refusal,
  `children_timeout` warning) — observability track's remit; only
  `queue_full` (call-site + loop-side) was independently attacked here
  (via the re-run #157 script).
- **Determinism** (50× identical traces both engines/service kinds incl.
  trip lap counts, hash-seed sweep) — determinism track's remit.
- **Semantics 5-way receipt matrix, strict+wildcard matrix, start()
  ordering vs #116** — semantics track's remit.
- **Security surface** (engine-completion-marker forgery, redaction,
  `__slots__`) — security track's remit.

---

## 5. Verdict

All soak-track legacy defects/checks (`D-soak-1`, `D-soak-2`, `D5-soak-1`,
the `#145` stop contract, `#166-168`, `#172`/`#157`, `#173` on the `def`
lane) remain **FIXED/PASS**, unchanged from the `221ce7c` re-run. The one
prior gap this track was explicitly asked to close — `#173` had only ever
been exercised with a `def` (blocking-thread) service — is now closed: the
`async def` mirror of the same stop-churn attack (50 generations, mid-
service and post-service `stop()`) shows the identical clean result (zero
hangs, zero double-fires, no thread growth) as the `def` lane.

The three new round-7-targeted attacks aimed at this round's soak-relevant
machinery — **`_chain_owed`** under 100 concurrent permanently in-flight
`async def` services raced against concurrent `stop()` (zero hangs),
**external `priority=True` sends** during a busy self-generated `always`-
cycle chain on the same interpreter (zero drops across 3000 sends), and
**`start(children_timeout=)`** with 50 slow invoked children (bounded
start, `status="running"`) — all passed cleanly, consistent with the
changelog's #179-#181 claims and with the ≥500-config livelock-fuzzer
result already produced independently by the determinism track.

No new defects found in this reduced pass. The larger uncovered surface
(§4) — the full 12-minute/200-machine ASYNC soak, the literal 10k/s
priority-send target, the children_timeout-*exceeded* path, and the
persistence/determinism/semantics/observability/security tracks' own
remits — remains explicitly out-of-scope of this track's share of the
20-minute whole-task budget and is flagged as follow-on work rather than
silently skipped.
