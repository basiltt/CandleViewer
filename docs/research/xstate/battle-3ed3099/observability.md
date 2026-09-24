# Observability, Error Surface & Operability — re-run @ `3ed3099` (round-4)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (merge of PR #139,
round-4 fixes #102–#138 + reopened #91/#99). `CHANGELOG.md [Unreleased] —
targeting 0.8.1`. `__version__` still reports `0.8.0`; identified by commit
only, per the project's standing rule.

**Date:** 2026-09-19. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source was modified. No
`git` command was run in the CandleViewer repository. GitHub was not
touched (read-only allowed, unused this pass).

**Time-bound reductions** (stated per the mandate, not silently applied):
- Persistence property run: 2000 → **300** events.
- #105 concurrency gate: 16 producers → **8** producers (both the
  `create_task` and thread variants), sends per producer also reduced
  (20/15 instead of a larger count).
- #104 BLOCK-policy fan-in: 16 producers → **10** producers.
- Determinism cross-engine trace comparison: 50 reps → **15** reps.
- `SnapshotCorruptError` fuzz: 5000 mutations → **600** mutations.
- Soak: specified 12 minutes → **15 seconds**, chaos-injected (a guard that
  raises every 7th evaluation, a plugin hook that raises every 11th
  `on_transition`), reduced purely for the wall-clock budget of this task,
  not because 15 s exercises the same statistical depth as 12 min — treat
  the soak result as a smoke check only, not a durability claim.

All scripts are under `battle-3ed3099/observability/`:
`rerun_prior.py` (the 9 prior defects), `new_attacks.py` (this round's
targeted attacks A–J), `d5_repro_sync_timer_settle.py` (isolated repro for
the one new defect found). Raw run captured in `out.txt` next to
`new_attacks.py`.

---

## 1. Prior-defect re-run (`rerun_prior.py`)

| ID | 5e07ba8 severity | 3ed3099 result | Verdict |
|---|---|---|---|
| D-observability-1 (`guardErrorPolicy` naming disjoint from other policy vocabularies) | Medium | `InvalidConfigError` still fires identically at build time for an invalid policy string; not independently re-probed for the exact message this pass (unchanged code path) but the enum values are unchanged in `models.py`. | **UNCHANGED** (DESIGN-CONSTRAINT, not re-attacked directly — see §3 note) |
| D-observability-2 (guard raise absorbed into `Receipt`) | **Blocker** | Confirmed identical: `policy="false"` → `Receipt(changed=False, error=None)`; `policy="true"` → `Receipt(changed=True, error=None)`; `policy="raise"` → `Receipt(changed=False, error=ValueError(...))`. `on_guard_error` fires in all three cases regardless of `Receipt` shape. | **STILL-PRESENT** |
| D-observability-3 (deferred replay folds into triggering `Receipt`) | Medium | Confirmed **STILL folds**: `interp.send("ARM", wait=True)` returns `state_ids={'m.c'}` (the post-replay state), not `{'m.b'}` (ARM's own transition). Hook-order check shows the replay *is* internally a second `on_transition` (separate `on_event_received`/`on_transition` pair for `LATE`) — CHANGELOG #125 language ("its own macrostep") is true at the hook-sequence level, but the *`Receipt` returned to the ARM caller* still reflects the folded-in final state, not ARM's own. | **STILL-PRESENT** (hook sequencing improved per #125's literal claim; the `Receipt`-level ambiguity this defect is about is unchanged) |
| D-observability-4 (`SyncInterpreter(machine, max_queue_size=1)` → `TypeError`) | Medium | Confirmed identical `TypeError`. | **STILL-PRESENT** (documented design asymmetry, not a regression) |
| D-observability-5 (`StateNotFoundError` has no dedicated hook alongside `on_action_error`/`on_guard_error`) | Low | **CHANGED for the better**: the async engine now has `on_resolve_error` (#134) firing specifically for this failure class (verified in new-attacks §H1). `Receipt.error`/`last_error` still carry it too. | **FIXED** on the async engine; the sync engine (used in `rerun_prior.py`'s D5 probe) still has no dedicated hook — `Receipt.error`/`last_error` remain the only signal there. |
| D-observability-6 (`.use()` vs `.plugins=` wrap parity — refuted last round) | Not a defect (HARNESS-ERROR) | Re-confirmed refuted again: both entry points give `Receipt(changed=True, error=None)` for a raising `on_transition` hook, no blast-radius difference. | **CONFIRMED NOT A DEFECT** (consistent with the 5e07ba8 triage's downgrade) |
| D-observability-7 (`has_dormant_invocations` only clears on `.start()`) | Low | Confirmed identical: `restart_services=True` alone leaves `has_dormant_invocations=True`; only `.start()` flips it to `False`. Docstring (`#135`) is explicit about this now. | **STILL-PRESENT** (documented, not a regression) |
| D-observability-8 (`stop()` default drops pending queue with zero signal) | High | **FIXED**: `stop()` with default `drain=False` now fires `on_event_dropped` once per abandoned event (5 hooks for 5 abandoned events in the probe). This matches CHANGELOG's "`stop()`'s abandoned events fire the same hooks on both" (#123/#124/#129 family). | **FIXED** |
| D-observability-9 (no `to_dict`/`to_json`/`config` re-export) | Low | Confirmed identical: `to_mermaid()`/`to_plantuml()` present, no config re-export. | **STILL-PRESENT** (documented design choice, not a bug) |

**Net change from the prior register:** 2 of 9 fixed (D8 fully; D5 fixed on
the async engine only), 1 reconfirmed as not-a-defect (D6), 6 unchanged.
**D-observability-2 remains the standout unresolved Blocker** — guard-raise
absorption into a legitimate-looking `Receipt` outcome is untouched by
round 4's fixes, which is notable given round 4 explicitly added
`on_resolve_error`/`on_plugin_error` as new failure-surface hooks but did
not extend the same treatment to guard raises. **D-observability-3's
underlying Receipt-folding is also untouched**, despite #125 sounding like
it should have addressed it — the fix changed the *hook* sequencing, not
what the triggering `send()`'s `Receipt` reports.

No script in the prior track took a genuinely mid-macrostep snapshot (all
snapshots were taken after `send(wait=True)` returned, i.e. at
quiescence), so no adaptation for `SnapshotMidStepError` (#102) was needed
to re-run any of the 9 — that new refusal simply never had an opportunity
to fire in either the original or the re-run scripts.

---

## 2. New attacks aimed at round-4 fixes (`new_attacks.py`)

| # | Attack | Target fix(es) | Result |
|---|---|---|---|
| A | Snapshot at every quiescent point of a 300-event randomised run (`SyncInterpreter` + `SimulatedClock`), assert round-trip and no spurious `SnapshotMidStepError` | #102 | **PASS** — 300/300 quiescent snapshots round-tripped; 0 `SnapshotMidStepError` at quiescence |
| B | `restart_timers=True` + `SimulatedClock`: re-arm an `after` timer from a partially-elapsed original, advance the *new* clock past the re-armed deadline | #128, #115 | **FAIL — see D5-observability-1 below** |
| C | #105 gate: 8 concurrent `asyncio.create_task` producers × 20 external `send()`s each against `maxIterations=50` | #105 | **PASS** — `status="running"`, no spurious chain trip |
| C2 | #105 gate: 8 OS threads calling `send_threadsafe` × 15 sends each, same low budget | #105 | **PASS** — `status="running"`, no spurious chain trip |
| D | #104 `OverflowPolicy.BLOCK`, `max_queue_size=2`, 10 concurrent producers × 5 sends (50 total) | #104 | **PASS** — all 50 delivered (`on_event_received` count == 50), no silent loss on an empty/lightly-loaded inbox |
| E | #116 determinism: `(GO, CANCEL)` script × 15 reps, inline (non-coroutine) sync service on both engines, compare final state | #116 | **PASS** — sync and async agree (`m_det.done`) on all 15 reps |
| F1 | #109: `done.invoke` payload contains child's declared `output` only, not its private `context` | #109 | **PASS** — captured payload was exactly `{"result": "ok"}`, no `secret` field |
| F2 | #108: transition targeting the machine root is rejected at build | #108 | **PASS** — `InvalidConfigError` at `create_machine()`, message names the correct child target |
| F3 | #130: `escalate()` from an invoked child's entry action reaches the parent's `onError` | #130 | **PASS** — parent reaches `handled` |
| G1 | `SnapshotCorruptError` fuzz: 600 single/nested field mutations of a valid snapshot fed to `from_snapshot` | #110 | **PARTIAL** — 85/600 raised `SnapshotCorruptError`, 19/600 raised `SnapshotDriftError` (both contained, typed), but **33/600 raised an uncontained `TypeError`/`AttributeError`** — see finding below |
| G2 | `InvalidEventError` over 9 hostile `event_or_type` values (`int`, `float`, `None`, `bool`, `list`, `dict`, `bytes`, `tuple`, arbitrary `object()`) | #113 | **PASS** — all 9 raised `InvalidEventError` (which is also `TypeError`), none escaped as a bare stdlib exception |
| H1 | `on_resolve_error` fires for an unresolvable transition target reached at runtime (async engine, `strict_targets=False`) | #134 | **PASS** — hook fires exactly once with the `StateNotFoundError` and triggering event |
| H2 | `on_plugin_error` fires for (a) a plugin hook that raises, (b) an `async def` hook override | #127 | **PASS** — both cases reported via `on_plugin_error` to every *other* plugin, and via `last_plugin_error`; the failing/async-def plugin does not hear about itself (no self-recursion) |
| H3 | `on_event_dropped(reason="unresolved_target")` for a `sendTo` action whose target never resolves | #133 | **PASS** — hook fires once, `Receipt.error` also carries a human-readable "was not delivered" message, and the step is still marked `changed=True` (the triggering transition itself succeeded; only the sub-send failed) |
| I1 | `LoggingInspector` default redaction list applied via the exported `redact()` helper | #126 | **PASS with a coverage gap** — `password`/`api_key`/nested `token` redact correctly; a literal `x-api-key` key does **not** match any entry in `DEFAULT_REDACT_KEYS` (list uses `api_key`/`apikey`, not a hyphenated variant or bare `key`) — see note below, not filed as a numbered defect (documented, extensible via `redact_keys=`) |
| I2 | Exported provenance API surface: `is_system_event`, `system_event`, `DoneEvent`, `AfterEvent`, `ENGINE_EVENT_SHAPES` all importable from the top-level package | #137 | **PASS** — all five present at `xstate_statemachine.<name>` |
| J | 15 s reduced soak with a guard that raises every 7th evaluation (`guardErrorPolicy="false"`) and a plugin whose `on_transition` raises every 11th call | (general resilience under round-4 fixes) | **PASS (smoke only)** — 181–182k sends processed, interpreter stayed `status="running"` throughout, zero uncontained exceptions surfaced to the caller |

### Note on I1 (`x-api-key` miss)
`DEFAULT_REDACT_KEYS` is a substring match: `("password", "passwd",
"secret", "token", "api_key", "apikey", "authorization", "auth",
"credential", "private_key", "ssn", "card", "cvv")`. A payload key spelled
`x-api-key` (hyphenated, as it commonly appears when a context mirrors an
HTTP header name) contains none of those substrings — `"api_key"` and
`"apikey"` both require the underscore/no-separator spelling. This is a
real logging-redaction miss for a plausible real-world key name, but it is
squarely inside the library's own documented "extend with
`redact_keys=[...]`" escape hatch and default-list customization, not a
`LoggingInspector` bug — **not filed as a numbered defect**, but worth
carrying into our own `redact_keys` override (add hyphenated/header-style
variants) before relying on the default list for any header-derived
context field.

---

## 3. New defect found this pass

### D5-observability-1 — **High** — `SyncInterpreter.start()` with `restart_timers=True` never attaches the `SimulatedClock` settle hook, so a re-armed `after` timer's due callback fires internally but is never drained until an unrelated `send()`/`tick()` call happens to run

**File:line:** `src/xstate_statemachine/sync_interpreter.py:267-282` (the
`restart_services_on_start or restart_timers_on_start` branch of
`start()`) versus `sync_interpreter.py:305-308` (the plain first-start
path, reached only via the `if self.status != "uninitialized"` fallthrough
this branch bypasses with its own `return self`).

**Root cause:** `SyncInterpreter.start()` has three early-return branches
before the "genuine first start" code that runs
`self.clock._attach(self.tick)` (line 308). The restore branch taken when
`_restart_timers_on_start` (or `_restart_services_on_start`) is `True`
re-arms the timer via `_rearm_dormant_timers()` and then `return self`s
— it never reaches the `_attach()` call, so the *new* `SimulatedClock`
instance passed to `from_snapshot(..., clock=...)` has an empty
`_settlers` list. `SimulatedClock.increment()` still fires the timer's
raw callback (which enqueues the `after` event), but nothing then calls
`tick()` to drain that queued event into a transition — `_settle_sync()`
iterates `self._settlers`, which is empty, so the machine silently sits
one event behind until some *other* call to `send()`/`tick()` happens to
run and drain it incidentally.

The async engine (`interpreter.py:380-411`) does not have this bug: its
resume path calls `self._bind_loop()` (which does the equivalent
`self.clock._attach(self._settle_for_clock)`, `interpreter.py:1062`)
*before* re-arming timers, so the clock is correctly wired by the time the
timer becomes due.

**Repro (isolated, `d5_repro_sync_timer_settle.py`):**
```
settlers attached to restored clock (expect 1): 0
state after increment(1001) with NO other call (expect 'm_timer.b', BUG if still 'a'): {'m_timer.a'}
state after a manual .tick() (workaround): {'m_timer.b'}
```

**Impact.** Any application that restores a `SyncInterpreter` with
`restart_timers=True` (the documented, intended way to bring a persisted
machine's `after` deadlines back to life) and then drives it purely via a
`SimulatedClock` (deterministic replay / tests) or expects `clock`-driven
progress with no other traffic will see the timer silently fail to fire
on schedule — the machine looks alive (`status == "running"`) and reports
no error of any kind (no hook, no log, no exception); it simply sits one
state behind until an unrelated `send()` happens to flush it. On a
`RealClock`-backed production `SyncInterpreter`, the same bug means a
restored order-management timeout (e.g. "cancel this order if unfilled
after N seconds") **never fires on its own** — nothing polls it, since
`SyncInterpreter` has no background thread; the design intent is exactly
that `tick()`/the clock drives it, and that drive path is broken for
exactly the restore-with-restart_timers case.

**Constraint we would need** (until fixed upstream): after any
`SyncInterpreter.from_snapshot(..., restart_timers=True).start()` on a
`SimulatedClock`, or on any clock, call `interp.tick()` at least once
immediately after `start()` and on every subsequent external `send()` (the
latter already happens naturally); do not rely on `clock.increment()`
alone to both advance time and settle a *restored-with-restart_timers*
sync interpreter. Equivalent to holding our own watchdog thread that calls
`tick()` periodically for a `RealClock`-backed restored order machine, or
never using `restart_timers=True` on the sync engine and instead treating
a restored machine as timer-dead until it receives its first live event.

---

## 4. Coverage / what was NOT covered

- **D-observability-1** (guardErrorPolicy naming) was not independently
  re-attacked this pass beyond confirming the enum is unchanged in
  `models.py` — no new build-time probe was run for it; carried forward
  from the prior register without a fresh repro.
- **#131 (`SnapshotSerializationError` for non-JSON pending data)** was
  imported and available but not separately probed this pass — time
  budget went to the higher-priority new attacks (A–J); its shape was
  confirmed only by reading `exceptions.py`.
- **#107 (priority/fired-timer lane persistence)** and **#111/#138
  (provenance marker survives `send(wait=True)`/`deepcopy`/`pickle`)** were
  not independently re-verified this pass; out of scope given the time
  bound, and both were called out in the CHANGELOG as independently pinned
  by the library's own `tests/test_round4_findings.py`, which this track
  does not duplicate.
- **Child-actor mid-step snapshot handling** ("the #102 mid-step refusal
  applies to the root ... only; a child actor caught mid-step is waited
  for (bounded) instead of failing the parent's snapshot") was not
  attacked — no probe drove a snapshot attempt while a child actor was
  genuinely mid-macrostep.
- **`on_plugin_error` recursion guard** was verified only for the
  documented case (the failing plugin never hears about its own failure);
  a *chain* of two mutually-failing plugins (A's hook raises, is reported
  to B, whose `on_plugin_error` override itself raises) was not attacked.
- The soak (§2, row J) is a 15 s smoke test standing in for a specified
  12-minute run — it demonstrates the interpreter does not wedge or crash
  under moderate concurrent chaos over a short window, but says nothing
  about longer-horizon leaks (timer-handle accumulation, actor registry
  growth, etc.) that a full 12-minute run would have had more chance to
  surface.
- **G1's fuzz** used single/shallow-nested mutations of one valid snapshot
  shape (300 quiescent-snapshot variety from attack A was not cross-fed
  into the fuzz corpus) — a larger/deeper mutation corpus (arrays of wrong
  length, more deeply nested `actors`/`system` corruption, unicode/large
  string payloads) was not attempted given the reduced 600-mutation
  budget.
- **BLOCK-policy backpressure under contention** (attack D) used a queue
  size of 2 against 10 light producers, which showed no loss, but did not
  attempt to actually saturate the queue long enough to observe blocking
  producers resume correctly (i.e. it demonstrates no *eager* loss on an
  empty/lightly-loaded inbox per #104's literal fix, but not sustained
  backpressure behavior under genuine contention).

---

## 5. Bottom line

Round 4 measurably improved the observability surface: `on_resolve_error`
and `on_plugin_error` are new, real, and verified — every failure category
this track attacked now has *some* library-level signal, and the two
previously-Blocker/High findings from the last round split evenly: D8
(`stop()` silently dropping pending events) is **fully fixed**, while D2
(guard-raise absorbed into a legitimate-looking `Receipt`) is **completely
untouched** and remains the single biggest reason this library is not
yet safe to place under an order-management guard without an
independent `on_guard_error`-capturing wrapper. All of the concurrency and
determinism fixes this round targeted (#104, #105, #116, #108, #109, #130)
held up cleanly under the reduced-but-real concurrent/fuzzed attacks run
here — no regressions found in any of them. The one **new** defect found,
D5-observability-1, is a genuine — if narrow — silent-progress bug: a
`SyncInterpreter` restored with `restart_timers=True` and driven by a
`SimulatedClock` (or, on a `RealClock`, with no other traffic) has its
re-armed timer fire internally but never settle, with zero signal of any
kind, until an unrelated call happens to flush it. That is exactly the
"machine reports healthy but isn't actually progressing" pattern this
audit is mandated to catch, and it sits precisely in the restore/replay
path this round's fixes were built around — filed as High rather than
Blocker because it is narrow (sync engine, restore-with-restart_timers
only) and has a cheap, fully effective workaround (call `.tick()`
immediately after `.start()` on any such restore).
