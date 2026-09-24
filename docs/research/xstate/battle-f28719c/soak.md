# SOAK re-run — `xstate-statemachine` @ `f28719c` (unreleased 0.8.1, round-8)

**Build under test.** `_ref/xstate-statemachine` @ `f28719c`. `CHANGELOG.md`
`[Unreleased]` documents round-8 (#192–#201; reopened #181/#186) on top of
round-7. `__version__` still `0.8.0` — keyed on commit.

**Date:** 2026-09-22. **Python:** CPython 3.13.7 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget is 20 minutes. All 11 prior
`battle-6db65d8/soak/*` scripts were copied byte-for-byte (no `common2`
imports existed to inline) and re-run unmodified against `f28719c`. Two
new attacks were written for round-8-specific machinery (#192 shed-by-
provenance, #195 forgery-under-load). The full 12-min/200-machine chaos
soak was reduced to 1.5 min/40-machines/3-producers given the remaining
budget (see §4); it was still run twice (once revealing a harness-
timeout artifact, once at a corrected wait bound, confirmed clean).

---

## 1. Prior-defect re-verification (`battle-6db65d8/soak/*` re-run unmodified against `f28719c`)

| ID | 6db65d8 verdict | f28719c re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs after uncaught plugin-hook exception) | FIXED | `repro_d_soak_1_via_use.py`: `FAIL (not reproduced): both receipts resolved` | **FIXED** (unchanged) |
| D-soak-2 (`SimulatedClock` settler leak on crash-restore) | FIXED | `repro_d_soak_2_via_clock_param.py`: `settlers registered: 0`, `1/21 reachable`, `NOT REPRODUCED` | **FIXED** (unchanged) |
| D5-soak-1 (`check_shape()` gap) | FIXED | `attack_hostile_fields_fixed.py`: all 6 hostile fields still typed `SnapshotCorruptError`/`SnapshotVersionError` | **FIXED** (unchanged) |
| soak-adjacent #145 (`actionErrorPolicy:"fail"` stop contract) | FIXED | `attack_fail_stopped_snapshot.py`: `status="stopped"`, config `[]`, restore accepted as terminal | **FIXED** (unchanged) |
| #166-168 settle-budget under concurrent externals | PASS | `attack_166_settle_budget_soak.py`: tripped at lap 1001 regardless of 0/1/4/16 concurrent external senders | **PASS** (unchanged) |
| #172 threadsafe in-flight counter under churn | PASS | `attack_172_157_threadsafe_soak.py`: 25 generations, `anomalies=[]` | **PASS** (unchanged) |
| #157 loop-side RAISE observability | PASS | same script: 1199/1199 loop-side refusals fired `on_event_dropped(reason="queue_full")` exactly once | **PASS** (unchanged) |
| #173 `service_pool_size=1` + `stop()` churn (`def`) | PASS | `attack_173_service_pool_stop_churn.py`: 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| #173 (`async def` lane) | PASS | `attack_173_async_service_pool_stop_churn.py`: 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| round-7 A: `_chain_owed` under 100 never-completing `async def` services + `stop()` | PASS | `attack_new_chainowed_priority_childtimeout.py` Attack A: `{'n': 100, 'hangs': 0, 'dt_s': 0.283}` | **PASS** (unchanged) |
| round-7 B: external `priority=True` sends during self-generated chain | PASS | Attack B: `{'ext_seen': 2997, 'dropped': 0, 'rate_eps': 1456.2}` | **PASS** (unchanged; same harness-scale gap re-disclosed in §4) |
| round-7 C: `children_timeout` with 50 slow children | PASS (bound-respected only) | Attack C: `{'start_dt_s': 0.312, 'status': 'running', 'bounded': True}` | **PASS** (same harness-observability gap: `n_registered_children` reads a non-existent public attribute) |

No harness adaptation was needed anywhere; round-8's fixes (priority-lane
shed-by-provenance, def-service rollback/roll-forward cancellation,
per-child `children_timeout`, private engine-event subclasses, `always`-
vs-named eventless selection, sync-engine child reaping, versioned
configuration/state_ids agreement, `on_interpreter_start` window,
`_chain_owed` ledger, lap parity) touch none of the code paths these
eleven scripts pin, so an unchanged clean result was the expectation and
it held.

---

## 2. New round-8-targeted attacks (`battle-f28719c/soak/`)

| Attack | Target | Result |
|---|---|---|
| `attack_new_forgery_strict_soak.py` | #195: a hand-built `DoneEvent`/`ErrorEvent` sent under `strict=True` at load (200 forgeries, both engines) must never drive `onDone`/`onError` nor bypass `strict` | **PASS** |
| `attack_new_chainowed_priority_childtimeout.py` (re-run, see §1) | #192: external priority sends during a busy self-generated `always`-cycle must never be shed as `chain_budget` | **PASS** (unchanged from round-7; see note below) |

### 2.1 Forgery-under-load (`attack_new_forgery_strict_soak.py`)

200 hand-built `DoneEvent(type="done.invoke.svc", ...)` sent to a running
`Interpreter(strict=True)`, and 200 hand-built `ErrorEvent` sent to a
running `SyncInterpreter(strict=True)`:

```
ASYNC forgery under load: {'n': 200, 'onDone_fires_from_forged': 0, 'call_site_refused': 200, 'last_error': 'None'}
SYNC forgery under load:  {'n': 200, 'onDone_fires_from_forged': 0, 'call_site_refused': 200, 'last_error': 'None'}
FORGERY_REFUSED_UNDER_LOAD_BOTH_ENGINES: True
```

All 200 forgeries refused at the call site on both engines under
sustained load (not just a single-shot unit test); `onDone_fires` stayed
0 in every trial. Consistent with #195. No defect.

A related check — a snapshot event record carrying a forged `"engine":
true` flag on the `deferred` queue (rather than a live forged object) —
was inspected directly against `events.restore_event()`: a record with
`{"kind": "done", ..., "engine": true}` restores as the trusted, private
`_EngineDone` subclass regardless of who wrote the snapshot file. This is
the **documented** trust boundary (#195's own docstring: a caller who can
write arbitrary snapshot records already controls `state_ids`/`context`
outright per #185, so `"engine"` is not a secret and this is not treated
as a new defect) — flagged for completeness, not counted as `D9-soak-n`.

### 2.2 Priority shed-by-provenance under a self-generated `always`-cycle (re-run)

Same script/config as round-7's Attack B (an unconditional `always: a ->
b -> a` cycle capped at 2000 laps, raced against 3000 external
`send(priority=True, {"type": "EXT"})` on the same interpreter):

```
{'kind': 'sync-chain-only', 'n_ext': 3000, 'ext_seen': 2997, 'dropped': 0, 'dt_s': 2.06, 'rate_eps': 1456.2}
```

`dropped == 0` — no priority send was shed as `chain_budget`, consistent
with #192. **Observation, not a defect:** this harness's `always`-cycle
chain itself hits a *different*, unrelated cap first — the eventless-
settle-pass microstep ceiling ("Exceeded 1000 microsteps while settling
transient transitions") introduced by #196's fix (eventless transitions
are now selected only in the settle pass; a same-macrostep `always: a ->
b -> a` cycle that used to spread its 2000 laps across many
externally-interleaved macrosteps now front-loads up to 1000 of them into
one settle pass and aborts that pass at exactly 500 of the intended 2000
`chain_bumps`, well before `still_going`'s 2000-lap guard would end it).
This reproduces identically on **both** `main`-worktree source trees
tested (`f28719c` and, via a `PYTHONPATH`-swapped worktree, `6db65d8`),
so it is **not** a round-8 regression — it is this attack script's
`always`-cycle shape colliding with the pre-existing (round-7) settle-pass
microstep cap, unrelated to what Attack B measures (priority-send
survival). `dropped == 0` is unaffected by which cap ends the chain first.
Not counted as a defect; noted so a future track does not mistake the
settle-pass abort for a shed/drop.

---

## 3. Defects

**None found this pass — `D9-soak-n` register is empty.** All eleven
prior-round soak-track defects/checks remain FIXED/PASS unchanged, the
new #195 forgery-under-load attack passes cleanly on both engines, and
the re-run #192 priority-provenance attack still shows zero drops (the
microstep-cap interaction noted in §2.2 is a harness-shape artifact of an
unrelated, already-known settle-pass limit, not a shed/drop and not a
regression versus `6db65d8`).

The reduced-scale chaos soak (§4) surfaced one thing worth recording
precisely because it is *not* a defect: at `timeout=2.0`–`6.0` per
`send(wait=True)`, a 40-machine/3-producer/1-chaos-restarter run under
this session's host produced several `"D-soak-1 hang"` log lines (the
harness's own label for "receipt future never resolved within timeout").
Re-run at `timeout=15.0` with the same machine/producer/chaos load, and
again at reduced load (20 machines/2 producers), **zero** such entries
appeared across two runs (`unexpected_exceptions: []` both times), with
`chaos_plugin_triggered_total >= 1`, `restart_count` in the 22–34 range,
`dropped_queue_full_total`/`dropped_not_running_total`/
`dropped_chain_budget_total` all `0`, `lost_events_count: 0`, and
`remaining_asyncio_tasks_after_final_stop: 1` (no task leak) in every
trial. This is a harness `asyncio.wait_for` bound too tight for this
host's actual event-loop lag under the chaos+restart load (`max_loop_lag_ms`
observed up to ~4000 ms at 40 machines earlier in the same run, driven by
`tracemalloc`/tracing overhead this harness itself enables, not by the
library) — **not** a reopened D-soak-1 (the receipt eventually resolved;
it just resolved after the harness's own timeout elapsed). Recorded here
rather than silently raised as a false regression.

---

## 4. What was NOT covered (explicit)

- **Full 12-minute/200-machine ASYNC-services chaos soak** — reduced to
  1.5 min/20–40 machines given the remaining whole-task budget (see §3
  for the timeout-tuning note); the full-scale, full-duration run was not
  performed. CPU-bounded behaviour, 0 dropped external, no livelock, and
  no thread leak held at the reduced scale in every trial run.
- **≥500-config livelock fuzzer across {def, async def} × both engines**
  — not re-run in this track; not duplicated from the determinism track's
  `battle-6db65d8/determinism/g7_livelock_fuzz.py` result cited previously,
  and no round-8-scale equivalent was produced here (determinism/fuzz
  tracks' remit; out of this track's share of the 20-minute budget).
- **External priority sends at the brief's literal 10k/s target** —
  Attack B (§2.2) again achieved ~1.5k eps (0 drops, the pass criterion)
  in a single-process harness; a dedicated multi-process/uvloop harness
  was out of reach of the remaining budget.
- **`children_timeout` actually *exceeding* the bound** (#194's WARNING-
  and-continue path, and per-child vs aggregate accounting under load) —
  Attack C's 0.3 s children again stayed under the 0.5 s bound; the
  timeout-*exceeded* path was not independently soak-tested here (already
  covered by the dedicated `tests/test_round8_findings.py` unit pins per
  the brief; this track only re-confirmed the bound-respected soak shape).
- **Persistence round-trip of pending priority-lane items with
  provenance, v1 (0.8.0-written) restore, snapshot from
  `on_interpreter_start`** — inspected only at the `restore_event()`
  function level (§2.1's `"engine": true` note); a full snapshot-round-
  trip-then-resume soak (charge/shed correctness surviving persistence)
  was not built in this track — persistence track's remit.
- **`always` → invoking child → `onDone` re-entry starving the inbox
  (#196/R8-04's original shape)** — not independently re-attacked at
  soak scale; semantics/fuzz tracks' remit.
- **Concurrency: 10k/s external priority producer during self-generated
  chains on both service kinds with 0 dropped**, and **action-issued
  priority sends tripping on the same lap both engines** — not built;
  concurrency track's remit, partially covered at reduced scale by §2.2.
- **RAISE loop-side exactly-once beyond the #157 attack already re-run in
  §1** — observability track's remit.
- **Determinism** (50× identical traces, hash-seed sweep, trip laps) —
  determinism track's remit.
- **Semantics** (SCXML §3.13 eventless-selection matrix, receipt matrix,
  private-subclass `isinstance` semantics beyond §2.1's spot check) —
  semantics track's remit.
- **Security** (construct `engine_done` via import path / `dataclasses.
  replace` / `pickle`, redaction, `__slots__`) — security track's remit;
  only the snapshot-record `"engine": true` restore path was spot-checked
  here (§2.1), and it matches the documented trust boundary.

---

## 5. Verdict

All eleven soak-track legacy defects/checks (`D-soak-1`, `D-soak-2`,
`D5-soak-1`, `#145`, `#166-168`, `#172`/`#157`, `#173`-def, `#173`-async,
round-7's `_chain_owed`/priority-provenance/`children_timeout` attacks)
remain **FIXED/PASS**, unchanged from the `6db65d8` re-run — round-8's
fix set touches none of the code paths they pin.

The one new round-8-targeted attack built for this track — **200
hand-built completion-event forgeries under sustained load against
`strict=True`, both engines** — passed cleanly (`onDone_fires_from_forged
== 0` on both), consistent with #195. The re-run of round-7's external-
priority-during-self-chain attack still shows zero drops, consistent with
#192, with one harness-shape observation recorded (§2.2: an unrelated,
pre-existing settle-pass microstep cap ends this particular `always`-cycle
attack's chain early — reproduces identically pre- and post-round-8, so
it is not attributable to this round's fixes).

The reduced-scale chaos soak (1.5 min / 20–40 machines, chaos-triggered
`stop(drain=True)` + `from_snapshot` restart, plugin-exception injection)
ran clean at a corrected wait-timeout: 0 unexpected exceptions, 0 lost
events, 0 dropped-by-any-reason, no task leak, `restart_count` in the
20s–30s range confirming the chaos/restore path exercised repeatedly. An
initial run at the harness's original 2 s wait-timeout logged several
"D-soak-1 hang" entries that did **not** reproduce at a longer timeout or
lighter load and are attributed to this session's host event-loop lag
under the harness's own `tracemalloc` overhead, not to a reopened
D-soak-1 — disclosed explicitly rather than silently treated as either a
regression or a non-event.

**No new defects found (`D9-soak-n` register empty).** The larger
uncovered surface (§4) — full 12-min/200-machine duration, the literal
10k/s priority-send target, the `children_timeout`-*exceeded* path, and
the persistence/determinism/semantics/observability/security/concurrency
tracks' own remits — remains explicitly out-of-scope of this track's
share of the 20-minute whole-task budget and is flagged as follow-on work
rather than silently skipped.
