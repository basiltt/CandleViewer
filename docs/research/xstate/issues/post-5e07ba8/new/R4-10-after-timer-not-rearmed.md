---
r4: R4-10
title: "Bug: `after` timers are never re-armed by `from_snapshot()`, and there is no dormancy signal for a lost timer"
labels: [bug, severity/low, area/persistence, area/timers]
severity: Low
repro_script: repro/R4-10_after_timer_not_rearmed.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

A state with an `after` timer is snapshotted while the timer is armed but has
not yet fired. After `Interpreter.from_snapshot()` + `start()`, the deadline
never fires again -- not with the default static restore, and not with
`restart_services=True`. Worse, none of the library's documented liveness
signals (`has_dormant_invocations`, `pending_invocations()`,
`clock.pending`) report anything is wrong: they all read as "healthy" while a
real deadline sits permanently expired. For a long-running stateful service
that relies on `after` for timeouts, a crash/restart at any point before the
timer fires silently and permanently disables that timeout.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-10: `after` timers are never re-armed by `from_snapshot()`, in either
`restart_services` mode, and there is no dormancy signal for a lost timer.

Standalone: no harness import. Uses a small local `attach_clock` helper
copied from `battle-5e07ba8/persistence/harness.py`, since `from_snapshot()`
has no `clock=` parameter.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.base_interpreter import _accepts_kwarg
from xstate_statemachine.clock import SimulatedClock

CONFIG = {
    "id": "timeout_demo",
    "initial": "waiting",
    "context": {"fired": False},
    "states": {
        "waiting": {
            "after": {"5000": {"target": "expired", "actions": ["mark"]}},
            "on": {"OK": {"target": "done_ok"}},
        },
        "expired": {"type": "final"},
        "done_ok": {"type": "final"},
    },
}


def mark(interp, ctx, event, ad):  # noqa: ANN001
    ctx["fired"] = True


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


def attach_clock(interp, clock: SimulatedClock) -> None:
    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


async def main() -> int:
    # --- reference: no crash -------------------------------------------
    c1 = SimulatedClock()
    i1 = await Interpreter(build(), clock=c1).start()
    await asyncio.sleep(0.02)
    await c1.increment(6000)
    await asyncio.sleep(0.02)
    ref_states = sorted(i1.current_state_ids)
    ref_fired = i1.context["fired"]
    print("REFERENCE  after 6 s :", ref_states, "fired =", ref_fired)
    await i1.stop()

    results = {}
    for restart in (False, True):
        c2 = SimulatedClock()
        i2 = await Interpreter(build(), clock=c2).start()
        await asyncio.sleep(0.02)
        await c2.increment(1000)
        blob = i2.get_snapshot()
        now = c2.now()
        await i2.stop()

        c3 = SimulatedClock()
        c3._now = now  # virtual time survives the crash
        i3 = Interpreter.from_snapshot(blob, build(), restart_services=restart)
        attach_clock(i3, c3)
        await i3.start()
        await asyncio.sleep(0.02)
        print(
            f"  restart_services={restart}: "
            f"dormant={i3.has_dormant_invocations} "
            f"pending_invocations={i3.pending_invocations()} "
            f"clock.pending={c3.pending}"
        )
        await c3.increment(10000)  # 11 s total -- well past the 5 s deadline
        await asyncio.sleep(0.02)
        states = sorted(i3.current_state_ids)
        fired = i3.context["fired"]
        print(
            f"  RESTORED after 11 s: {states} fired = {fired} status={i3.status}"
        )
        results[restart] = (states, fired)
        await i3.stop()

    print(
        "EXPECTED: both restores reach ['timeout_demo.expired'] with fired=True, "
        "matching the reference run."
    )
    ok = all(states == ["timeout_demo.expired"] and fired for states, fired in results.values())
    print("RESULT:", "PASS" if ok else "FAIL (after timer lost across restore)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
REFERENCE  after 6 s : ['timeout_demo.expired'] fired = True
  restart_services=False: dormant=False pending_invocations=[] clock.pending=0
  RESTORED after 11 s: ['timeout_demo.waiting'] fired = False status=running
  restart_services=True: dormant=False pending_invocations=[] clock.pending=0
  RESTORED after 11 s: ['timeout_demo.waiting'] fired = False status=running
EXPECTED: both restores reach ['timeout_demo.expired'] with fired=True, matching the reference run.
RESULT: FAIL (after timer lost across restore)
```

Both restores stay in `timeout_demo.waiting` forever, `fired` stays `False`
even 11 virtual seconds after start (6 s past the 5 s deadline), and every
documented health signal (`has_dormant_invocations`, `pending_invocations()`,
`clock.pending`) reports nothing pending. The reference (uninterrupted) run
correctly reaches `timeout_demo.expired` with `fired=True`.

## Expected behaviour

XState v5's persisted snapshot restores an actor "from where it left off"
(https://stately.ai/docs/persistence): delayed transitions armed at snapshot
time are expected to resume counting down (or fire immediately if already
due) once the actor is restarted -- the same contract SCXML gives `<send>`
with `delay` (§6.2/§C.1): a delayed event is scheduled relative to when the
enclosing state was entered, and that schedule survives an implementation's
"resume from persisted state". The library already re-arms *invoked services*
on restore when `restart_services=True` (`_restart_dormant_invocations()`);
`after` timers have no equivalent, undocumented as a gap in either
mode.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:1344-1370`,
`_restart_dormant_invocations()`:

```python
def _restart_dormant_invocations(self) -> None:
    """Re-invoke every dormant invoke through the normal entry path. ..."""
    for pending in self.pending_invocations():
        state = self.machine.get_state_by_id(pending.state_id)
        if state is None:
            continue
        for invocation in state.invoke:
            ...
```

This method iterates `state.invoke` exclusively; there is no analogous walk
over `state.after` anywhere in the restore path (`interpreter.py`'s `start()`,
around line 340, calls it only inside the `restart_services` branch). A
restored interpreter's active leaf states are never checked for an `after`
map, so no `set_timeout`/priority delivery is ever scheduled for them --
static restore (`restart_services=False`) and service-restarting restore
(`restart_services=True`) behave identically for timers, because neither path
touches them.

The dormancy surface has the same gap: `pending_invocations()` and
`has_dormant_invocations` are built purely from `state.invoke` bookkeeping
(persisted invocation records); there is no `pending_timers()` or equivalent,
so a lost `after` deadline is invisible to any caller checking the documented
liveness API before/after a restore.

## Impact

**General users.** Every `after`-driven timeout that has not yet fired when a
process is snapshotted is silently disarmed by any restart -- deploy, OOM
kill, failover, etc. There is no code path and no restart option that
re-arms it, and there is no API that reports it happened. A service built to
"snapshot on every transition, restore on boot" for durability effectively
loses all of its `after`-based deadlines the moment it restarts.

**Concrete order-management scenario.** An order machine arms
`after: {5000: "expire"}` as an exchange-ack timeout: if the venue does not
acknowledge within 5 s, the order machine must treat it as failed and take
compensating action. A crash 1 s into that window, followed by a normal
restart-from-snapshot, leaves the order parked in `waiting` forever with no
ack timeout in effect and `has_dormant_invocations=False` telling any health
check the machine has nothing outstanding. The order silently loses its
one liveness guarantee and can sit unresolved indefinitely.

## Proposed fix

**Design.** Extend the restore path to re-arm `after` timers, and add a
timer-dormancy surface so the situation is at least observable even before a
fix lands.

1. In `_restart_dormant_invocations()` (or a sibling
   `_restart_dormant_timers()` called alongside it from `start()`), after
   `_enter_states`-equivalent bookkeeping, walk each active state's
   `state.after` map. For each entry, compute remaining delay as
   `scheduled_duration - elapsed_since_state_entry` (persist the entry
   timestamp per active state if not already available; if unavailable,
   the conservative option is to fire "already elapsed" timers immediately
   and re-arm any not-yet-elapsed ones for their full remaining duration).
2. Route the re-armed timer the same way a live timer is: through
   `self.clock.set_timeout` / the priority-lane delivery path used by a
   normal `after` (`interpreter.py`, `#48` priority lane), not a bespoke path.
3. Add `pending_timers()` (mirroring `pending_invocations()`) that reports,
   for each active state with an unfired `after`, its state id and remaining
   delay; fold its truthiness into `has_dormant_invocations` (or add a
   sibling `has_dormant_timers` and OR them into a combined health flag) so
   existing health-check code that already reads `has_dormant_invocations`
   is not silently blind to timers.
4. Make this unconditional (not gated by `restart_services`), since a timer
   is not an external service call and re-arming it carries none of
   `restart_services`'s side-effect-duplication risk.

**Compatibility.** Additive; changes only the restore path for machines that
declare `after`. No snapshot schema change needed if timestamps can be
derived from existing state entry bookkeeping; otherwise a new optional
field, defaulting to "unknown -> fire immediately" for old snapshots.

**Alternatives considered.**
1. *Document the gap only.* Leaves the liveness hole in place; rejected as
   insufficient given `after` is a documented, first-class transition type.
2. *Always fire immediately on restore instead of computing remaining
   delay.* Simpler, but breaks a legitimate use of `after` as a
   "no sooner than N seconds" debounce; the remaining-delay computation is
   only marginally more work and matches the semantics of every other
   engine.

## Acceptance criteria

- [ ] `Interpreter.from_snapshot(...).start()` re-arms every active state's
      `after` timers, with or without `restart_services=True`.
- [ ] A new `pending_timers()` (or equivalent) reports dormant timers before
      restart, mirroring `pending_invocations()`.
- [ ] `repro/R4-10_after_timer_not_rearmed.py` exits `0`.
- [ ] `tests/test_persistence_timers.py::test_after_timer_rearmed_on_restore`
      -- snapshot mid-countdown, restore, advance virtual clock past the
      original deadline: the transition fires exactly once.
- [ ] `tests/test_persistence_timers.py::test_after_timer_elapsed_before_restore_fires_promptly`
      -- snapshot after the deadline has already elapsed (but before the
      original process dequeued it), restore: the transition fires without
      waiting a further full delay.
- [ ] `tests/test_persistence_timers.py::test_pending_timers_reports_dormant_after`

## Related

- Register row `R4-10` (filed High, DOWNGRADE to Low; the static default is
  documented, but the missing opt-in and the missing dormancy signal are not).
  Source id `D-persistence-2`; unmerged 1:1.
- Evidence: `battle-5e07ba8/persistence/d2_after_timer_lost.py`.
- **`R4-11`** -- the priority lane (where a *fired* `after` event lives) is
  also never persisted. Together, there is no window, before or after
  firing, in which an `after`-driven deadline survives a crash.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-10_after_timer_not_rearmed.py` in a fresh process: exit code `1`,
  output matches the Observed section verbatim (both `restart_services=False`
  and `restart_services=True` restores stay in `timeout_demo.waiting`,
  `fired=False`, and all three liveness signals read healthy).
- Root cause confirmed at `src/xstate_statemachine/base_interpreter.py`,
  `_restart_dormant_invocations` (walks `state.invoke` only, no `state.after`
  walk anywhere in the restore path).
- XState v5 persistence claim confirmed against
  https://stately.ai/docs/persistence: restoring resumes invocations
  (recursively) from the persisted snapshot; the doc does not carve out
  `after` timers as an exception, consistent with "resume where it left off."
- No duplicate found on `gh issue list -R basiltt/xstate-statemachine --state
  all --search "after timer"` (issues #48/#49/#56/#76/#50 cover perf,
  clock-injection, docs, and threading defects for `after`, none address
  re-arming on restore).
- Self-contained; no project-name/label leak.
