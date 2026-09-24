---
r5: R5-13
title: "Bug: `SyncInterpreter.start()`'s restore branch returns before `clock._attach()`, so `restart_timers=True` / `from_snapshot(clock=)` re-arm a deadline nothing will ever drain"
labels: [bug, severity/high, area/timers]
severity: High
repro_script: repro/R5-13_sync-restore-skips-clock-attach.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

#128 added `from_snapshot(restart_timers=True)` so a restored machine's
`after` deadlines are re-armed from zero, and #117 added the
`from_snapshot(clock=)` parameter. Both land on the same early `return self`
in `SyncInterpreter.start()`: the resume branch at `sync_interpreter.py:268-283`
returns before the `if isinstance(self.clock, SimulatedClock):
self.clock._attach(self.tick)` at `:307-308` that the normal start path runs.
The deadline is therefore re-armed on a clock with **zero attached settlers**
— `clock.increment()` past the deadline does nothing, while
`has_dormant_timers` reports `False`, i.e. "re-armed". An explicit `tick()`
recovers it, proving the deadline exists and only the settler is missing.
Two round-4 features that were designed to compose both fail on this one line.

## Environment

- Commit: `3ed3099` (`main`, merge of #139 `fix/0.8.1-round4`; unreleased
  0.8.1 — `__version__` still reports `0.8.0`, so this build is identified
  by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-13 repro: `SyncInterpreter.start()`'s restored branch returns before the
`SimulatedClock` settler is attached.

`sync_interpreter.py:268-283` handles the restart_services/restart_timers
resume path and `return self` at :283 -- before the
`if isinstance(self.clock, SimulatedClock): self.clock._attach(self.tick)` at
:307-308 that the normal start path runs. The re-armed `after` deadline is
registered on a clock that will never drive the interpreter:
`has_dormant_timers` reports False ("re-armed"), but `clock.increment()` past
the deadline does nothing. An explicit `tick()` recovers it, proving the
deadline exists and only the settler is missing. Control: a
constructor-injected clock fires on `increment()` alone.
Exits 1 while present, 0 once fixed. Stdlib + xstate_statemachine only.
"""

import json
import logging
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "tm", "initial": "idle", "context": {"late": 0},
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {"after": {"50": {"target": "idle", "actions": ["late"]}}},
    },
}


def mk():
    def late(i, c, e, a):
        c["late"] += 1

    return create_machine(CFG, logic=MachineLogic(actions={"late": late}))


def settlers(clock):
    return len(getattr(clock, "_settlers", []))


def main() -> int:
    # CONTROL: fresh interpreter, constructor-injected SimulatedClock
    c1 = SimulatedClock()
    ctrl = SyncInterpreter(mk(), clock=c1).start()
    ctrl.send("GO")
    ctrl_settlers = settlers(c1)
    c1.increment(200)
    ctrl_late = ctrl.context["late"]
    ctrl.stop()
    # snapshot taken while `armed`
    c2 = SimulatedClock()
    src = SyncInterpreter(mk(), clock=c2).start()
    src.send("GO")
    snap = json.dumps(src.get_persisted_snapshot(), default=str)
    src.stop()
    # SUBJECT: restore with restart_timers=True and a fresh SimulatedClock
    c3 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(snap, mk(), clock=c3, restart_timers=True)
    r.start()
    subj_dormant = r.has_dormant_timers
    subj_settlers = settlers(c3)
    c3.increment(200)
    subj_late = r.context["late"]
    r.tick()  # the deadline IS there; only the settler is missing
    subj_late_after_tick = r.context["late"]
    r.stop()
    print("OBSERVED:")
    print("  CONTROL (ctor clock)  attached_settlers :", ctrl_settlers)
    print("  CONTROL               late after +200ms :", ctrl_late)
    print("  SUBJECT (restored)    has_dormant_timers:", subj_dormant)
    print("  SUBJECT               attached_settlers :", subj_settlers)
    print("  SUBJECT               late after +200ms :", subj_late)
    print("  SUBJECT               late after tick() :", subj_late_after_tick)
    print("EXPECTED:")
    print("  the restored interpreter attaches the settler exactly like the")
    print("  constructor path: attached_settlers=1 and late=1 after +200ms,")
    print("  with no explicit tick() required.")
    if subj_settlers == 0 and subj_late == 0 and ctrl_late >= 1:
        print("RESULT: FAIL - restored start() skipped clock._attach; "
              "has_dormant_timers=False is a false 're-armed' signal")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  CONTROL (ctor clock)  attached_settlers : 1
  CONTROL               late after +200ms : 1
  SUBJECT (restored)    has_dormant_timers: False
  SUBJECT               attached_settlers : 0
  SUBJECT               late after +200ms : 0
  SUBJECT               late after tick() : 1
EXPECTED:
  the restored interpreter attaches the settler exactly like the
  constructor path: attached_settlers=1 and late=1 after +200ms,
  with no explicit tick() required.
RESULT: FAIL - restored start() skipped clock._attach; has_dormant_timers=False is a false 're-armed' signal
```

Exit status `1`.

Three details worth drawing out:

- **`has_dormant_timers` is `False`** — the library's own "is the parked work
  re-armed?" signal says yes, while the timer cannot fire. A health check on
  the documented signal passes.
- **`late` goes to `1` after an explicit `tick()`** — the deadline was
  genuinely re-armed by #128. The only thing missing is the settler that
  makes `clock.increment()` drive the interpreter, which is what
  `SimulatedClock` exists for.
- **The async engine is not affected.** Our determinism track's re-run
  (`battle-3ed3099/determinism/n2b_restart_timers.py`) reports
  `sync`: `subject_attached_settlers: 0`, `subject_late: 0`,
  `subject_late_after_tick: 1`; `async`: `VERDICT: OK`. The async engine
  attaches its settler in `_bind_loop` (`interpreter.py:1058-1062`), which
  the run loop always reaches.

The `from_snapshot(clock=)` half (#117) fails on the same line and is
isolated by `probes/main-3ed3099/p4_clock_attach.py`: `ctor_settlers: 1`
versus `restored_settlers_after_start: 0`.

## Expected behaviour

The library's own contract for `SimulatedClock`, stated in the comment
immediately above the line that is skipped
(`sync_interpreter.py:305-308`):

> A SimulatedClock drives us through `tick()` after each increment so
> `clock.increment(ms)` leaves the machine settled (#49).

and for the async engine at `interpreter.py:1058-1061`:

> A SimulatedClock must let THIS interpreter settle after firing timers, or
> `await clock.increment()` returns before the machine has processed the
> AfterEvent it just queued.

`docs/_guide/snapshots.md:132` documents the restore contract:

> Pass `from_snapshot(..., restart_timers=True)` (defaults to the value of
> `restart_services`) to have `start()` re-arm every dormant timer **from
> zero** (0.8.1, #128).

"Re-arm" must mean "will fire through the interpreter's normal drive path",
otherwise `has_dormant_timers` reporting `False` afterwards is false.
`docs/_guide/interpreters.md:223` makes `has_dormant_timers`/
`has_dormant_invocations` the designated health signal after a restore, in
preference to `status`; a signal designated for health checks must not report
`re-armed` for a deadline that cannot fire.

Concretely expected: after `SyncInterpreter.from_snapshot(snap, machine,
clock=SimulatedClock(), restart_timers=True).start()`, the restored
interpreter behaves identically to a constructor-injected one —
`len(clock._settlers) == 1`, and `clock.increment(ms)` past the deadline
fires the `after` transition with no explicit `tick()`.

## Root cause analysis

`SyncInterpreter.start()` has four early returns before the real start path.
The first is the resume branch (`sync_interpreter.py:268-283`):

```python
if self.status == "running" and (
    self._restart_services_on_start or self._restart_timers_on_start
):
    # 🔁 #44: restored with restart_services=True. Sync services run
    #    inline, so this both re-invokes and processes their results.
    # ⏱️ #128: restart_timers re-arms `after` deadlines from zero.
    logger.info("♻️ Resuming restored interpreter '%s'...", self.id)
    if self._restart_services_on_start:
        self._restart_services_on_start = False
        self._restart_dormant_invocations()
    if self._restart_timers_on_start:
        self._restart_timers_on_start = False
        self._rearm_dormant_timers()
    self._process_event_queue()
    self._process_transient_transitions()
    return self                                    # <-- :283
```

The clock attach lives in the *uninitialized* path, twenty-five lines later
(`:304-308`):

```python
logger.info("🏁 Starting sync interpreter '%s'...", self.id)
self.status = "running"
# 🧪 A SimulatedClock drives us through `tick()` after each increment
#    so `clock.increment(ms)` leaves the machine settled (#49).
if isinstance(self.clock, SimulatedClock):
    self.clock._attach(self.tick)
```

`from_snapshot()` sets `status = "running"` on the restored object, so a
restored interpreter *never* reaches `:304`. Two other early returns share
the same problem and the same fix:

- `:284-295` — restored *with a persisted inbox* (review F8): replays the
  queue, `return self` at `:295`.
- `:296-301` — "already running, skipping start", `return self` at `:301`.

So the attach is conditioned on a code path (`status == "uninitialized"`)
that is orthogonal to the condition it actually depends on (this interpreter
now owns a `SimulatedClock` and has not yet registered with it). The bug is
purely one of placement; nothing about the restore logic itself is wrong, and
`_rearm_dormant_timers()` does its job.

The async engine avoids it by attaching in `_bind_loop`
(`interpreter.py:1047-1062`), which is called from the run-loop startup on
every path including a resume — the structurally correct location, since it
keys off "this interpreter is now bound to its driver" rather than off a
status value.

Why this was not caught: `#128`'s own regression coverage drives the restored
machine with an explicit `tick()` (which works), and the `n2b` probe in our
audit is the first to assert on `clock.increment()` alone plus
`len(clock._settlers)`.

## Impact

**General users.** Any `SyncInterpreter` test suite or simulation that (a)
restores from a snapshot and (b) drives time with `SimulatedClock.increment()`
silently stops advancing timers. The machine is not broken — it processes
sent events normally, and an explicit `tick()` works — so the symptom is
"my `after` transition never fires after a restore, but only in the restored
case", with `has_dormant_timers` actively asserting the opposite. Because
`SimulatedClock` is the recommended way to test timer-driven machines
deterministically, this makes restore-path timer tests unreliable in exactly
the direction that produces false confidence: a test that asserts the timer
*did not* fire passes for the wrong reason.

`from_snapshot(clock=)` (#117) is affected identically, so the two round-4
features cannot be composed at all on this engine.

**Order-management scenario (our adoption audit, #26).** Our order machines
use `after` deadlines for the exchange-ack timeout and the cancel-window
expiry, and our replay/backtest harness restores each order from its
persisted snapshot and advances a `SimulatedClock` over recorded market time.
With this bug the restored orders' timeouts never fire during replay: an
order that timed out in production is replayed as still awaiting ack, so
reconciliation reports no discrepancy where a real one existed, and the
timeout branch of every order machine is effectively untested in the replay
suite. `has_dormant_timers == False` is what we would have used to assert the
restore was sound. Production (real clock) is not affected, which makes this
a test-fidelity and reconciliation defect rather than a live order-path one —
hence High rather than Blocker.

## Proposed fix

**Attach the settler where the interpreter acquires its driver, not on one
status path.** Mirror the async engine's structure: extract the attach into a
small idempotent helper and call it at the top of `start()`, before any of
the early returns.

```python
def _attach_clock(self) -> None:
    """Register this interpreter's `tick` with a SimulatedClock, once."""
    if isinstance(self.clock, SimulatedClock) and not self._clock_attached:
        self.clock._attach(self.tick)
        self._clock_attached = True

def start(self) -> "SyncInterpreter":
    if self.status == "stopped":
        raise InvalidConfigError(...)
    self._attach_clock()          # every path below now has a live clock
    if self.status == "running" and (
        self._restart_services_on_start or self._restart_timers_on_start
    ):
        ...
```

The idempotence flag matters because `start()` may be called more than once
on a restored interpreter (the "already running" path at `:296-301` returns
without error today), and `SimulatedClock._attach` appends to a list — a
double attach would tick the interpreter twice per increment. Alternatively
make `_attach` itself idempotent by identity, which is the more robust place
for the guard and also protects any user calling it directly.

**Order within the resume branch.** Attaching *before*
`_rearm_dormant_timers()` is preferable: the re-armed deadlines are then
registered against a clock that already knows how to drive this interpreter,
and there is no window in which a deadline exists without a settler.

**Also cover `from_snapshot(clock=)` explicitly.** #117 lets a caller hand in
a clock at restore time; the constructor path is not involved at all there,
so the attach must happen in `start()` (as above) rather than in
`__init__` — confirming that `start()` is the right home for it.

**Consider making `has_dormant_timers` honest as defence in depth.** If it is
cheap to do so, have it report `True` when a `SimulatedClock` is in use and
this interpreter is not among its settlers — the signal would then have
caught this bug rather than masked it. This is secondary to the fix above.

**Compatibility.** Restored sync interpreters on a `SimulatedClock` begin
firing timers on `increment()` where previously they did not — which is the
documented behaviour, so no configuration that worked before breaks, but any
downstream test asserting the (incorrect) non-firing will need updating.
Code that compensated with an explicit `tick()` continues to work, since
`tick()` on a settled machine is a no-op. Real-clock users are unaffected.

## Acceptance criteria

- [ ] `repro/R5-13_sync-restore-skips-clock-attach.py` exits `0`.
- [ ] `tests/test_round5_findings.py::test_sync_restore_restart_timers_attaches_simulated_clock`
      — after `from_snapshot(..., clock=SimulatedClock(), restart_timers=True).start()`,
      `len(clock._settlers) == 1` and `clock.increment(200)` alone fires the
      `after` transition (no explicit `tick()`).
- [ ] `tests/test_round5_findings.py::test_sync_restore_with_persisted_inbox_attaches_clock`
      — covers the second early return (`sync_interpreter.py:284-295`).
- [ ] `tests/test_round5_findings.py::test_sync_from_snapshot_clock_param_attaches`
      — pins #117's `from_snapshot(clock=)` path specifically
      (`ctor_settlers == restored_settlers_after_start`).
- [ ] `tests/test_round5_findings.py::test_sync_start_twice_does_not_double_attach`
      — `len(clock._settlers)` stays `1` after a second `start()`, and one
      `increment()` advances the machine exactly one step.
- [ ] `tests/test_round5_findings.py::test_sync_async_restored_timer_parity`
      — the same restore-and-increment scenario reaches the same
      configuration on both engines (the async half passes today).
- [ ] `tests/test_round5_findings.py::test_has_dormant_timers_false_implies_timer_can_fire`
      — the signal and the behaviour cannot disagree.
- [ ] Changelog entry under the #128/#117 follow-up noting that restored
      sync interpreters now drive a `SimulatedClock` on `increment()`.

## Related

- **Round-4 issues:** #128 (`restart_timers=True` / `has_dormant_timers` —
  the re-arm itself works; the settler is what is missing), #117
  (`from_snapshot(clock=)` — fails on the identical line), #44 (the
  `restart_services` resume branch that the early `return self` belongs to),
  #49 (the `SimulatedClock` settle contract quoted above), #135
  (`has_dormant_*` as the documented post-restore health signal, which this
  bug makes untrue for timers).
- **Note:** #128's *dormancy* half is sound and was re-verified — after a
  plain restore without `restart_timers`, `has_dormant_timers` correctly
  stays `True` and the timer correctly never fires. Only the re-arm path is
  affected.
- **Register source ids:** R5-13 ← `D5-determinism-1`, `D5-observability-1`,
  `J-6`.
- **Evidence:** `battle-3ed3099/determinism/n2b_restart_timers.py` (sync vs
  async, with control); `probes/main-3ed3099/p4_clock_attach.py` (isolates
  the `from_snapshot(clock=)` half); `33-r5-findings-register.md` §2/§3
  R5-13.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7
- Commit: `3ed3099`
- Re-ran `repro/R5-13_sync-restore-skips-clock-attach.py` fresh: exit `1`,
  output unchanged (control `attached_settlers=1, late=1`; subject
  `attached_settlers=0, late=0` after `increment(200)`, `late=1` only after
  an explicit `tick()`).
- Root-cause citations checked against source: `SyncInterpreter.start()`
  (`sync_interpreter.py:237`) has three early `return self` statements at
  `:283`, `:295`, `:301` (the resume/replay/already-running branches), all
  before the `if isinstance(self.clock, SimulatedClock): self.clock._attach(self.tick)`
  block at `:307-308` in the uninitialized path — exact line numbers match
  the citation.
- Duplicate check: `gh issue list --search "clock attach restore"` returns
  #115 (`_attach()` has no paired detach — a leak, not a missing attach),
  #117 (`from_snapshot(clock=)` — the feature this bug also breaks, already
  cited under Related), #128 (`restart_timers` re-arm itself, already
  cited), #107 (persisted timer lane, a different defect) — none report the
  restored branch skipping `_attach` entirely. No duplicate found.
- Self-contained, no project-name/label leak: confirmed.
