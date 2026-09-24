# SOAK triage — `xstate-statemachine` @ `5e07ba8` (unreleased 0.8.1)

Re-verification pass over `soak.md`'s two defects, fresh process, this
session. Interpreter:
`_ref/xstate-statemachine/.venv-main/Scripts/python`, env
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified; no git
run in CandleViewer; GitHub not touched.

| ID | Re-run result | Root cause confirmed in source | Kind | Severity (this pass) |
|---|---|---|---|---|
| D-soak-1 | `REPRODUCED: at least one wait=True receipt never resolved` / `interpreter.status = stopped` / `pending receipt futures: 1`, plus the expected "Task exception was never retrieved" `RuntimeError('boom')` traceback out of `_run_event_loop` | Yes | LIBRARY-DEFECT | **High** (downgraded from soak.md's implicit Blocker-adjacent framing) |
| D-soak-2 | `settlers registered on the clock: 21` / `interpreters still reachable (not GC'able): 21 / 21` / `REPRODUCED: every stopped interpreter is kept alive by the clock` | Yes | LIBRARY-DEFECT | **High** (as rated in soak.md) |

## D-soak-1 — unresolved `wait=True` receipt futures on fatal event-loop exit

**Re-run.** `repro_d_soak_1.py` run standalone, fresh interpreter process:

```
REPRODUCED: at least one wait=True receipt never resolved
  interpreter.status = stopped
  pending receipt futures: 1
Task exception was never retrieved
future: <Task finished name='Task-2' coro=<Interpreter._run_event_loop() ...> exception=RuntimeError('boom')>
Traceback (most recent call last):
  File ".../interpreter.py", line 1208, in _run_event_loop
    plugin.on_event_received(self, event)
  File "repro_d_soak_1.py", line 46, in on_event_received
    raise RuntimeError("boom")
RuntimeError: boom
```
Matches soak.md's cited behavior exactly, including that the crash happens
in `plugin.on_event_received` (interpreter.py:~1206-1208, before the
try/except that wraps `_process_event_and_transient_transitions`) — outside
the per-event `except Exception` guard entirely, so it is a `BaseException`
escaping into the `except BaseException as exc:` handler.

**Source confirmation.** Read `interpreter.py` around the cited lines:
- The plugin-notify loop (`for plugin in self._plugins: plugin.on_event_received(self, event)`, ~line 1206) sits *outside* the per-event `try/except Exception` block that starts a few lines later at `self._processing = True`. Any exception raised there — including a plain `RuntimeError` — skips straight past the per-event receipt-resolution logic (`self._resolve_receipt(...)`, which only runs inside that inner try's normal-completion path) and is caught only by the outer `except BaseException as exc:` handler (~line 1300), which:
  - logs `critical`,
  - sets `self.status = "stopped"`,
  - re-raises,
  - and does **not** call `self._fail_all_receipts()`.
- `_fail_all_receipts()` (interpreter.py:774) exists and is grep-confirmed to be called from exactly one call site in the whole file: line 996, inside the orderly `stop()`/teardown path. The fatal-exception path at ~1300-1319 has no call to it.
- Consequence confirmed directly: any event already sitting in `self._receipts` (i.e., sent with `wait=True`) at the moment a plugin hook, action, or guard throws a `BaseException` that escapes to the run loop is left with a `Future` that is never resolved. A caller `await`-ing it (without its own timeout) hangs forever. The repro's own harness-hardening story in soak.md §1.3 (needing to wrap every `send(wait=True)` in `asyncio.wait_for`) is independent corroboration from the full soak run, not just the minimal repro.

**Kind: LIBRARY-DEFECT.** This is not a harness misuse or a documented
constraint — the library's own architecture comment at ~1201-1220
explicitly frames per-event errors as something that "must not terminate
the run loop" and documents that `SyncInterpreter` raises to its caller
on the equivalent path, i.e. the async engine's own stated design intent is
for callers to be informed of failures, not left hanging. The bug is an
asymmetry between two exception-handling tiers (`except Exception` inside
the loop body vs `except BaseException` around the whole loop) where only
the inner tier resolves receipts. Not a duplicate of any previously-cited
LC/N/F/G/H id or GitHub issue found in this pass (no such cross-reference
exists in soak.md; not independently re-searched against GitHub per the
read-only constraint and since this track doesn't require it).

**Severity reassessment for a financial OMS.** soak.md rates this
implicitly as severe (framed as the harness's most load-bearing finding,
§1.3) but doesn't give it an explicit register letter grade in the excerpt
retained here; on the register's scale I rate it **High**, not Blocker:
- It does **not** by itself cause silent state corruption or money loss on
  the order path — the interpreter's internal state machine, when it dies
  this way, is left in a consistent last-known configuration
  (`_execute_transition` is atomic per the code's own comment), and
  `interp.status` correctly flips to `"stopped"`, which is observable.
  Nothing here forges a false "success" receipt or silently double-applies
  an order action.
- It **does** meet High: silent wrongness from the caller's point of view
  (a `wait=True` caller has no way to distinguish "still processing" from
  "will never resolve" without an external timeout) and a hard operational
  constraint (every `wait=True`/`priority=True, wait=True` call site on an
  order-critical path must carry its own timeout — the library provides no
  such guarantee itself). Given CandleViewer's own CV-C06-style existing
  discipline around `deferred`-handling already requires timeout-wrapping
  awaited sends in comparable spots, this is additive risk (a much larger,
  less enumerable trigger surface — "any uncaught exception in a plugin
  hook/action/guard" vs. just `onUnhandled: "defer"`) rather than a
  categorically new one, which keeps it at High rather than Blocker.

## D-soak-2 — `SimulatedClock` settler list has no detach; every restored interpreter leaks forever, per-tick clock cost grows unbounded

**Re-run.** `repro_d_soak_2.py` run standalone, fresh interpreter process:

```
settlers registered on the clock: 21
interpreters still reachable (not GC'able): 21 / 21
REPRODUCED: every stopped interpreter is kept alive by the clock
```
Matches soak.md exactly (20 restore cycles + 1 original = 21).

**Source confirmation.** Read `clock.py`:
- `self._settlers: List[Callable[[], Any]] = []` declared at line 259.
- `_attach` (line 365) appends `settle` if not already present (line
  370-371) — confirmed idempotent-against-same-callable, as claimed.
- `_settle_sync` (line 332-334) and `_settle` (line 351-358, called from
  `_drain_async`, line 339) both do `for settle in list(self._settlers):`
  — i.e. every `increment()`/`set()`-driven settle pass walks the *entire*
  historical settler list, confirmed linear-in-restart-count per tick.
- Grep of `clock.py` for `_detach`/`remove`/unregister-style names: none
  exist. There is no public or private API to remove an entry from
  `_settlers`.
- `interpreter.py:931` (`self.clock._attach(self._settle_for_clock)`,
  inside `start()`) is confirmed as a call site that adds a settler on
  every `start()`, including every `from_snapshot()` + manual clock
  re-point + `start()` cycle in the documented crash-recovery idiom. No
  corresponding removal exists in `stop()`/teardown.
- `_settle_for_clock` is a bound method of the interpreter instance, so
  each list entry in `_settlers` is a strong reference keeping that
  interpreter (and everything it references transitively: machine,
  context, actor registry, plugin list) reachable from the clock — the
  repro's weakref-based liveness check (21/21 still alive after `gc.collect()`) directly demonstrates this.

**Kind: LIBRARY-DEFECT.** The clock's own re-attach idiom is the one the
CHANGELOG documents (`from_snapshot()` takes no `clock=` argument, so
callers must manually re-point `interp.clock` and re-`_attach`), and that
documented idiom has no corresponding way to detach the superseded
interpreter's settler — this is a missing API, not a misuse of an existing
one. Not a duplicate of a previously-cited id in soak.md; not
independently found in a GitHub search this pass (not required/attempted;
read-only `gh` was available but not needed to confirm the source-level
root cause since the fix is directly visible in `clock.py`).

**Severity reassessment for a financial OMS.** soak.md already rates this
**High** and cites RSS growth (61.8 MB → 340.6 MB peak, +205.8%) and
event-loop lag (single-digit ms → 113.7 s peak) both correlating with
cumulative restart count in the full 25-minute run. I keep this at
**High**, unchanged:
- Does not itself corrupt order state or silently misreport a fill/ack —
  it is a resource-exhaustion / performance-degradation defect, not a
  correctness-on-the-happy-path defect, so it does not meet this register's
  Blocker bar ("can cause money loss or silent state corruption on the
  order path") directly.
- It does meet High cleanly: it is a hard architectural constraint
  (`SimulatedClock` cannot be used as a long-lived, cross-restart-shared
  clock without an external, manual settler-list workaround) with a
  concrete, measured production-shaped failure mode (unbounded RSS growth
  and event-loop lag climbing past 100 s in under 25 minutes of realistic
  chaos-restart cadence) that would eventually starve or OOM a live paper-
  or shadow-trading process built on this documented idiom. Caveat carried
  over from soak.md §5 ("not covered"): the exact split between
  settler-list-walk cost and the sampler's own periodic `gc.collect()` in
  the 113.7 s lag figure was not isolated in this pass either — this pass
  re-confirms the *qualitative* root cause (unbounded settler-list growth,
  no detach path) via the standalone repro and source read, not a fresh
  quantitative rerun of the 25-minute soak (out of the 90 s per-run time
  bound for this triage pass; soak.md's own 25-minute run stands as the
  quantitative evidence and was not repeated here).
- **Does not apply to `RealClock`** (soak.md's own scoping, confirmed by
  the fact that no equivalent settler-list structure exists outside
  `SimulatedClock` in `clock.py`), so production paths that use `RealClock`
  throughout are unaffected; the constraint is scoped to
  `SimulatedClock`-based deterministic-replay / paper-trading harnesses
  that persist across restarts, which is a real but narrower blast radius
  than "every production order path."

## Summary

Both D-soak-1 and D-soak-2 reproduce cleanly in a fresh process this pass,
and both root causes are directly confirmed by reading the cited
`interpreter.py`/`clock.py` source at commit `5e07ba8`. Both are
LIBRARY-DEFECTs, not harness errors, documented design constraints, or
duplicates of another cited id. Severity: D-soak-1 downgraded to **High**
(no direct state-corruption/money-loss path found; it's a caller-visible
hang requiring a mandatory timeout discipline, not a silent-wrongness
Blocker); D-soak-2 confirmed at **High** as originally rated (resource-
exhaustion/performance defect scoped to `SimulatedClock`-based
crash-recovery idioms, not a happy-path correctness Blocker, but a hard
constraint with measured production-shaped impact).
