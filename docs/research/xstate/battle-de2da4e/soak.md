# SOAK re-run — `xstate-statemachine` @ `de2da4e` (unreleased 0.8.1, round-11)

**Build under test.** `_ref/xstate-statemachine` @ `de2da4e` (round-11 fix
PR, #218–#222 on top of round-10). `__version__` still `0.8.0` — keyed on
commit.

**Date:** 2026-09-23. **Python:** CPython 3.13.7 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget 20 minutes; individual
scripts capped ≤60 s. Given the budget, this pass (1) re-ran every prior
`battle-c78ce99/soak/*` script byte-for-byte unmodified, and (2) added
one focused new standalone script (`attack_new_r11_handles_reentrant_latch.py`)
covering the three round-11 behaviors most exercised by soak-style
conditions (timer-handle flatness, ReentrantWaitError, chain-trip latch).
The 12-min/200-machine full soak, the ≥300-case persistence property
matrix, the ≥500-config livelock fuzzer, and the 50×-trace determinism
sweep specified in the brief were **not** run at full scale this pass —
see §4.

---

## 1. Prior-defect re-verification (`battle-c78ce99/soak/*` re-run unmodified against `de2da4e`)

| ID | c78ce99 verdict | de2da4e re-run result | Verdict |
|---|---|---|---|
| #166-168 settle-budget under concurrent externals | PASS | tripped at `n_reached=1001` regardless of 0/1/4/16 concurrent senders, `ALL_TRIPPED=True` | **PASS** (unchanged) |
| #172 threadsafe in-flight counter under churn | PASS | 25 generations, `anomalies=[]` | **PASS** (unchanged) |
| #157 loop-side RAISE observability | PASS | 1199/1199 refusals fired `on_event_dropped(reason="queue_full")` exactly once | **PASS** (unchanged) |
| #173 `service_pool_size=1` + `stop()` churn (`def`) | PASS | 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| #173 (`async def` lane) | PASS | 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| round-7 B: external `priority=True` sends during self-generated chain | PASS | `ext_seen=2997/3000, dropped=0` | **PASS** (unchanged; same known microstep-cap artifact) |
| round-7 C: `children_timeout`, 50 slow children | PASS | `bounded=True`, same `n_registered_children` harness gap | **PASS** (unchanged) |
| #195 forgery-under-load (200 hand-built events, `strict=True`, both engines) | PASS | `onDone_fires_from_forged=0` both engines, `call_site_refused=200/200` | **PASS** (unchanged) |
| `attack_fail_stopped_snapshot` (`actionErrorPolicy:"fail"` stop contract) | PASS | `status=stopped`, config `[]`, restore accepted terminal snapshot | **PASS** (unchanged) |
| `attack_hostile_fields_fixed` (6 hostile snapshot fields) | PASS | 5/6 typed `SnapshotCorruptError` correctly; `version` field still silently accepted (pre-existing, not round-11 scope) | **PASS** (unchanged) |
| `repro_d_soak_1_via_use` (D-soak-1, `wait=True` receipt hang) | FIXED | both receipts resolved, "not reproduced" | **FIXED** (unchanged) |
| `attack_new_r9_soak_2` §C (stranded-invocation hook, 20-way) | PASS | sync `exactly_once=True`; async sample shows `hook_fires=0` in the printed 2-item sample (same as prior runs — harness reports `async_ok_exactly_once=False` but this is the pre-existing sampling-window artifact noted in earlier rounds, not new) | **PASS** (unchanged) |

**SUPERSEDED note (carried forward, not re-triggered this pass).**
`attack_new_r9_soak_2.py` §B (`raise(delay=1ms)` ping-pong vs
`maxIterations`) is the same script flagged **SUPERSEDED** in the
c78ce99 report (#212 overturned the #206 "delayed self-send is a chain
debt" rule). Re-run here: `async: lap=800, sync: lap=1` — i.e. sync still
trips at lap 1 with `last_error=None` printed (no exception raised in the
harness's try/except capture), consistent with the already-recorded
SUPERSEDED status; this script asserts nothing new and was not rewritten,
since it is not one of the round-11-touched code paths (#212's rule is
unchanged in round-11).

No script in `battle-c78ce99/soak/` invoked `send(..., wait=True)` where
the *awaiting action's own interpreter* was the target of the send (the
shape #219 changes) — every `wait=True` call in the corpus is either (a)
an external caller awaiting its own send outside of an action context, or
(b) awaiting a different interpreter's send from inside a parent's action
(none present). **No SUPERSEDED rewrites were needed**: none of the
carried-forward scripts hit the new `ReentrantWaitError` path, so none
required "expect ReentrantWaitError now" rewrites.

---

## 2. New round-11 attack: `attack_new_r11_handles_reentrant_latch.py`

Single standalone script, three sub-attacks, run to completion in <1 s:

**(A) Timer-handle flatness — #218.** `raise(delay=1)` self-heartbeat,
both `Interpreter` (async) and `SyncInterpreter`, sampled after 200 beats.
Result: `{'handles_after_200_beats': 0}` — the handle is released on
fire, not accumulated. **Holds** (no D12 filed).

**(B) ReentrantWaitError matrix — #219.** Entry action on state `x`
awaits (async) / calls (sync) `send({"type": "GO"}, wait=True)` on its
*own* interpreter during `start()`. Both engines raised
`ReentrantWaitError` from inside the action, the send was still accepted
as a queued event (machine reached `value='y'`), and `start()` completed
(`status='running'`) rather than hanging. Exact matches for both `async`
and `def` lanes:
```
async: seen=1 ReentrantWaitError ("...that is a deadlock...."), status=running, value=y
sync:  seen=1 ReentrantWaitError (same message), value_before=x, value_after=y
```
**Holds** — matches CHANGELOG #219 and `tests/test_round11_findings.py::TestReentrantWaitIsRefused` exactly (self-wait sub-case only; sendTo-self, child→parent, parent→child, and after-fired-handler sub-cases from the brief's matrix were **not** run this pass — see §4).

**(C) Chain-trip latch across a benign event — #222.** `PING` chain
(`bump` + self-`reping`) trips the 50-iteration cap once; a subsequent
`BENIGN` event (no chain work) is sent; then `clear_chain_error()` is
called. Result:
```
trips_after_trip=1, latch_set_after_trip=True,
trips_after_benign=1, latch_still_set_after_benign=True,
latch_after_clear=None
```
`chain_trips` stayed monotonic at 1 (the benign event did not add a
spurious trip), `last_chain_error` survived the benign event
(`latch_still_set_after_benign=True` — this is exactly the bug #222
fixes: pre-fix this would have been `False`), and `clear_chain_error()`
correctly reset the latch to `None`. **Holds** (no D12 filed).

---

## 3. Defects found this pass

**None.** All three round-11 fixes (#218 handle release, #219
ReentrantWaitError, #222 sticky latch) held under the attacks run; all
17 carried-forward c78ce99 soak scripts reproduced their prior PASS/FIXED
verdicts unmodified. No D12-soak-n defects to report.

---

## 4. Not covered this pass (time-budget disclosure)

Per the 20-minute whole-task bound, the following items from the battle
brief were **not** attempted or were reduced:

- **Persistence property matrix** (parked+armed `scheduled_sends` across
  restore→persist→restore→start chains, ≥300 property cases; #221's
  "re-persist without start() keeps armed sends" specifically) — not run.
- **Concurrency soak** (200 heartbeat machines × 10 s handle/RSS
  flatness; 100 concurrent `ensure_future`-pattern actions issuing
  `ReentrantWaitError`; child→parent `wait=True` sends; cancel-storm
  double-release check) — not run.
- **Recursive key-check fuzzer** (typo fuzzer at every nesting level for
  #220, and a valid-grammar generator asserting 0 false positives under
  `strict_config`) — not run.
- **Livelock fuzzer** (≥500 configs × kinds × engines) — not run.
- **Determinism sweep** (50× traces, both engines, both kinds, including
  `chain_trips` counts) — not run.
- **Full ReentrantWaitError matrix** — only the *self* sub-case was
  exercised; *sendTo self*, *child→parent*, *parent→child*, and
  *after-fired-handler* sub-cases were not run.
- **Security probes** (strict_config bypass via `x-` prefix abuse / key
  case variants; snapshot forgery of `scheduled_sends`/`lane`/`engine`)
  — not run.
- **12-minute / 200-machine full soak** with chaos v3 snapshot/restore/
  re-persist and external priority producer — not run at any scale this
  pass (the brief's own reduced-scale precedent from the c78ce99 report,
  30-machine/20s, was also not repeated here due to time).
- The full pytest+coverage background run (`suite-de2da4e.log`) completed
  during this pass: **3545 passed, 13 skipped, 0 failed, 92.87% coverage**
  in 752.21s — a strong corroborating signal for round-11 stability, but
  it exercises the library's own unit/integration suite, not this
  battle-track's adversarial soak scenarios.

---

## 5. Verdict

**No regressions, no new defects.** Round-11's three targeted fixes
(#218 timer-handle release, #219 ReentrantWaitError, #222 sticky
chain-trip latch) each held under a standalone, targeted attack; all
carried-forward round-10 soak defects/passes reproduced unchanged on
`de2da4e`. The battle brief's full adversarial matrix (persistence
property fuzzing, 200-machine 12-minute soak, security/forgery probes,
determinism sweep, livelock fuzzer) was **not completed** this pass due
to the 20-minute wall-clock bound — see §4 for the explicit list. This
report should be treated as a **partial, time-boxed spot-check**, not a
full soak-track clearance; the outstanding items in §4 remain open work
for a follow-up pass with a larger time budget.
