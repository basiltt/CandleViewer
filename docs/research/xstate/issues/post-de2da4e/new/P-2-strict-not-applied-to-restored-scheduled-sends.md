---
id: P-2
title: "Bug: `strict` is not applied to restored `scheduled_sends` — `_rearm_restored_self_sends` bypasses `_admit_restored`"
labels: [bug, persistence, validation, timers, events, severity/medium]
severity: Medium
repro_script: repro/P-2-strict-not-applied-to-restored-scheduled-sends.py
commit: de2da4e
verified: true
---

## Summary

This is from our "make it perfect" list after twelve rounds of adoption
review: the library is adopted and running, and these are the few items
left between *adopt with constraints* and *nothing open*.

#214 closed the hole where the restore path bypassed the `strict`
call-site check, by routing every restored `pending_events` record through
`_admit_restored`. The sibling list added by #213 — `scheduled_sends` — did
not get the same treatment: `_rearm_restored_self_sends` re-arms each
record straight through `_arm_restored_self_send` with no strict check.

So the two restore lanes disagree about the same record. An undeclared
event type placed in `pending_events` is refused, reported via
`on_invalid_event` and recorded on `last_error`; **the identical record
placed in `scheduled_sends` is armed silently and delivered to the run
loop**, on a machine with `strict: True`.

This is a one-line fix and we have a proposed acceptance test below.

## Environment

* Library: `main` @ `de2da4e` (unreleased 0.8.1; `__version__` still
  reports `0.8.0`, so this keys on the commit).
* CPython 3.13.7, Windows 11, fresh venv, run from a neutral cwd.
* Both engines; snapshot envelope v3; chart declares `"strict": True`.

## Minimal reproduction

Standalone: stdlib + `xstate_statemachine` only, every helper inlined, run
from the neutral cwd `<home>`. **Exit 1 = reproduced.**

```python
"""STANDALONE repro -- P-2: `strict` is NOT applied to restored
`scheduled_sends`, because `_rearm_restored_self_sends` bypasses
`_admit_restored`.

`from_snapshot` checks every restored `pending_events` record against
`strict` (#214, `base_interpreter.py:1935` -> `_admit_restored`). The
sibling list `scheduled_sends` is re-armed by
`_rearm_restored_self_sends` (`base_interpreter.py:1269`) with no such
check, so an undeclared event type parked in a snapshot is admitted on a
`strict: True` machine and delivered to the run loop.

Library @ de2da4e (unreleased 0.8.1; __version__ still reports 0.8.0).
stdlib + xstate_statemachine only. Every helper inlined. Run from ANY cwd.

Exit 1 == DEFECT REPRODUCED (the two restore lanes disagree).
"""

import asyncio
import copy
import json
import sys

from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.machine_logic import MachineLogic

# `strict: True` -- the declaration rule this probe is about.
CONFIG = {
    "id": "p2",
    "initial": "a",
    "strict": True,
    "states": {
        "a": {"on": {"KNOWN": "b"}},
        "b": {},
    },
}

# A type the chart never declares. `strict` must refuse it from EVERY door.
UNDECLARED = {"type": "UNDECLARED_TYPO", "payload": {}, "kind": "event"}


def _machine():
    return create_machine(copy.deepcopy(CONFIG), logic=MachineLogic())


def _base_blob(machine):
    """A real, self-minted v3 snapshot -- no hand-forged envelope."""
    interp = SyncInterpreter(machine).start()
    blob = json.loads(interp.get_snapshot())
    interp.stop()
    return blob


def _sanity_send_is_refused(machine):
    """Control: the SAME type via send() is refused, so strict is really on."""
    interp = SyncInterpreter(machine).start()
    try:
        interp.send(UNDECLARED["type"])
        return False
    except Exception:  # noqa: BLE001 -- UnknownEventError
        return True
    finally:
        interp.stop()


def _lane_pending(machine, blob):
    """Lane A -- the record rides `pending_events` (goes via _admit_restored)."""
    b = copy.deepcopy(blob)
    b["pending_events"] = [dict(UNDECLARED)]
    b["scheduled_sends"] = []
    interp = SyncInterpreter.from_snapshot(json.dumps(b), machine)
    return len(list(interp.pending_events)), interp.last_error


def _lane_scheduled(machine, blob):
    """Lane B -- the SAME record rides `scheduled_sends`."""
    b = copy.deepcopy(blob)
    b["pending_events"] = []
    rec = dict(UNDECLARED)
    rec["remaining_ms"] = 1.0
    rec["send_id"] = "p2-probe"
    b["scheduled_sends"] = [rec]
    interp = SyncInterpreter.from_snapshot(json.dumps(b), machine)
    parked = len(interp._restored_self_sends)
    armed = interp._rearm_restored_self_sends()
    return parked, armed, interp.last_error


async def _lane_scheduled_async(machine, blob):
    """Lane B on the async engine, end to end: does the event reach the loop?"""
    b = copy.deepcopy(blob)
    b["pending_events"] = []
    rec = dict(UNDECLARED)
    rec["remaining_ms"] = 1.0
    rec["send_id"] = "p2-probe"
    b["scheduled_sends"] = [rec]
    interp = Interpreter.from_snapshot(json.dumps(b), machine)

    seen = []
    original = interp._process_event

    async def spy(event, *a, **k):  # observation only; library untouched
        seen.append(getattr(event, "type", event))
        return await original(event, *a, **k)

    interp._process_event = spy
    await asyncio.wait_for(interp.start(), timeout=10.0)
    await asyncio.sleep(0.20)
    await interp.stop()
    return UNDECLARED["type"] in seen


async def main():
    print("P-2 -- `strict: True`, the same undeclared record on the two restore lanes\n")

    machine = _machine()
    blob = _base_blob(machine)

    control = _sanity_send_is_refused(machine)
    print(f"  control  send()         -> refused: {control}")

    n_pending, err_a = _lane_pending(machine, blob)
    name_a = type(err_a).__name__ if err_a is not None else None
    print(f"  lane A   pending_events -> enqueued={n_pending}  last_error={name_a}")

    parked, armed, err_b = _lane_scheduled(machine, blob)
    name_b = type(err_b).__name__ if err_b is not None else None
    print(f"  lane B   scheduled_sends-> parked={parked} armed={armed}  last_error={name_b}")

    reached = await _lane_scheduled_async(machine, blob)
    print(f"  lane B   async engine   -> undeclared event reached the run loop: {reached}")

    print()
    a_refused = n_pending == 0 and err_a is not None
    b_admitted = armed == 1 and err_b is None
    print(f"strict is genuinely on (send refused)              : {control}")
    print(f"lane A refuses the undeclared type (#214, correct) : {a_refused}")
    print(f"lane B admits the SAME type under strict           : {b_admitted}")
    print(f"async engine delivers it to the run loop           : {reached}")

    reproduced = control and a_refused and b_admitted
    print(f"\nREPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), timeout=60.0)))
    except asyncio.TimeoutError:
        print("WATCHDOG: hung")
        sys.exit(2)
```

## Observed behaviour

```
P-2 -- `strict: True`, the same undeclared record on the two restore lanes

  control  send()         -> refused: True
  lane A   pending_events -> enqueued=0  last_error=UnknownEventError
  lane B   scheduled_sends-> parked=1 armed=1  last_error=None
  lane B   async engine   -> undeclared event reached the run loop: True

strict is genuinely on (send refused)              : True
lane A refuses the undeclared type (#214, correct) : True
lane B admits the SAME type under strict           : True
async engine delivers it to the run loop           : True

REPRODUCED: True
```

Exit code **1**. Note `last_error=None` on lane B: the admission is not
only wrong, it is **silent** — `on_invalid_event` does not fire and nothing
is recorded, so an operator has no way to learn the restore admitted
traffic `strict` was configured to refuse.

## Expected behaviour

Lane B matches lane A. An undeclared type in `scheduled_sends` is **not**
armed; the refusal is reported the way an invalid `send()` is
(`on_invalid_event`, `last_error = UnknownEventError`);
`_rearm_restored_self_sends()` returns `0`; and the event never reaches the
run loop. A registered event schema that rejects the payload is likewise
honoured, since `_check_strict` covers both.

## Root cause analysis

`base_interpreter.py:1269` — `_rearm_restored_self_sends`:

```python
records, self._restored_self_sends = self._restored_self_sends, []
for rec in records:
    event = restore_event(rec)
    delay_ms = float(rec.get("remaining_ms") or 0.0)
    self._arm_restored_self_send(          # <-- no _admit_restored
        event, max(delay_ms, 0.001), rec.get("send_id")
    )
return len(records)
```

Compare the `pending_events` loop at `base_interpreter.py:1935`, which does
the right thing:

```python
for record in snapshot.get("pending_events") or []:
    ev = restore_event(record)
    if not interpreter._admit_restored(ev):
        continue
    interpreter._enqueue_restored(ev, priority=record.get("lane") == "priority")
```

`_admit_restored` (`base_interpreter.py:1222`) is the shared helper #214
introduced for exactly this purpose — its docstring says *"Mirrors the
`send()` call-site check"* — and it is called from precisely one place.

The gap is a sequencing artefact rather than a design decision: #213 added
`scheduled_sends`, #214 hardened the restore path against `strict`, and
#221 later extended `scheduled_sends` with parking. At no point did the two
lines of work meet. Both engines are affected, since
`_rearm_restored_self_sends` lives in the shared base and is called from
`interpreter.py:579` and `sync_interpreter.py:318,340`.

One subtlety worth stating explicitly, because it is the reason this is a
real check and not a no-op: `_check_strict` exempts engine-minted events by
**provenance** (`is_system_event`, `base_interpreter.py:2412`), not by
name. A genuine `raise(delay=)` self-send therefore still passes — as it
must, since #206 charges it to the chain budget — while a record whose
provenance does not survive as engine-minted is checked like the user
traffic it is. So the fix does not break the legitimate re-arm path.

## Impact

* **`strict: True` is not restore-safe** — the property #214 exists to
  guarantee. An adopter who enabled `strict` as a typo/contract net has a
  door where it does not apply.
* **Silent**: no exception, no `on_invalid_event`, no `last_error`. The
  contrast with lane A makes it worse — the same record is loudly refused
  on one path and quietly admitted on the other, so a test written against
  lane A gives false assurance about lane B.
* **Asymmetry is durable across compaction**: because #221 re-emits parked
  records verbatim, an unchecked record survives arbitrarily many
  restore→re-persist journal-compaction hops without ever meeting a check.
* **Security-adjacent, though not itself a trust-boundary break.** A
  snapshot store is already a trust boundary the `from_snapshot` docstring
  declares (we are not filing the forged-`"engine": true` vectors, per that
  boundary). But #214 chose to make `strict` hold on the restore path
  anyway, and this is a gap in that stated guarantee, not a new claim
  about it. Rated Medium on our board for exactly that reason: it weakens
  a documented defence in depth rather than opening the front door.
* Registered event schemas are bypassed on the same path, so a payload a
  schema would reject is armed too.

## Proposed fix

One line, matching the `pending_events` loop:

```python
# base_interpreter.py, _rearm_restored_self_sends (~1269)
records, self._restored_self_sends = self._restored_self_sends, []
armed = 0
for rec in records:
    event = restore_event(rec)
    if not self._admit_restored(event):      # #214 parity
        continue
    delay_ms = float(rec.get("remaining_ms") or 0.0)
    self._arm_restored_self_send(
        event, max(delay_ms, 0.001), rec.get("send_id")
    )
    armed += 1
return armed
```

Note the return value must become "how many were **armed**", not
`len(records)` — the docstring already says *"Returns how many were
armed"*, so this makes the implementation match its own contract. The only
current caller sites (`interpreter.py:579`,
`sync_interpreter.py:318,340`) use it for logging, so the narrower count is
the more useful one and nothing depends on the old meaning.

Docstring addendum for the same function, mirroring `_admit_restored`'s:
a restored delayed self-send is checked against `strict` like a sent one; a
refusal is reported via `on_invalid_event` / `last_error` and the send is
dropped, so a restore that discarded a deadline is never silent.

## Acceptance criteria

* `repro/P-2-strict-not-applied-to-restored-scheduled-sends.py` exits
  **0**: lane B reports `armed=0`, `last_error=UnknownEventError`, and the
  async spy never sees the undeclared type.
* New test `test_restored_scheduled_send_is_refused_by_strict`,
  parametrised over both engines: a snapshot whose `scheduled_sends`
  carries an undeclared type restores with the record dropped,
  `on_invalid_event` fired once, and `last_error` an `UnknownEventError`.
* New test `test_restored_scheduled_send_honours_event_schema`: a record
  whose payload a registered schema rejects is dropped the same way.
* New test `test_rearm_returns_the_number_actually_armed`: a mixed list of
  one legal and one refused record returns `1`.
* **Non-regression, the important half**: a genuine `raise(delay=)`
  self-send still round-trips and fires — the existing #213/#221 pins
  (including the 600-case parked/armed property over both service kinds)
  pass unchanged, and a `strict: True` machine whose own delayed self-raise
  is in the snapshot still re-arms it.
* A `strict: False` machine is unaffected: every record arms as today.

## Verification

- Repro run from the neutral cwd `<home>` with the `.venv-main`
  interpreter: **exit 1**, no `ImportError`, output as quoted above —
  lane A refuses, lane B admits, and the async engine delivers the
  undeclared event to the run loop.
- The code block under "## Minimal reproduction" is **byte-identical** to
  `repro/P-2-strict-not-applied-to-restored-scheduled-sends.py`
  (5164 bytes, compared programmatically).
- Root-cause lines confirmed open in current source at `de2da4e`:
  - `base_interpreter.py:1222` — `def _admit_restored(self, event)`, the
    strict gate.
  - `base_interpreter.py:1935` — `if not interpreter._admit_restored(ev):
    continue`, inside the `pending_events` loop (lane A), with the
    `#214` comment block at `1927-1933` stating the intent: "a restored
    USER event is checked against `strict` like a sent one".
  - `base_interpreter.py:1925` — `dict(r) for r in (snapshot.get(
    "scheduled_sends") or [])`, where the sibling list is read in with
    **no** admission call (lane B).
  - `base_interpreter.py:1269-1284` — `_rearm_restored_self_sends`, which
    loops the parked records straight into `_arm_restored_self_send` with
    no strict check, confirming the bypass.
  - Call sites confirmed: `sync_interpreter.py:318` and
    `interpreter.py:579`.
  - `base_interpreter.py:2412` — `if is_system_event(event):`, the
    provenance branch the restored record rides past.
- The asymmetry is the point and is confirmed both ways in one run: the
  **identical** record dict is refused on `pending_events` and admitted on
  `scheduled_sends`, on a machine with `strict: True`, with a positive
  control showing `send()` of the same type is refused.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `scheduled_sends`, `strict`, `restore`.
  `#214` (the `pending_events` fix), `#213` (which added `scheduled_sends`)
  and `#221` are all CLOSED; none covers strict on the `scheduled_sends`
  lane.

## Related

* #214 (restore-path `strict`, which this extends to the sibling lane),
  #213 (`scheduled_sends`), #221 (parked records, which carry the unchecked
  record across compaction hops), #51 (`strict`), #206 (chain-budget
  standing of restored self-sends).
* `base_interpreter.py:1222` `_admit_restored` — the existing helper, today
  reachable from one call site.
* Our adoption audit (#26), round 12 — persistence and security tracks.
