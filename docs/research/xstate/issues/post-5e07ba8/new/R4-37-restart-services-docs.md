---
r4: R4-37
title: "Docs: from_snapshot(restart_services=True) reports status=\"running\" before dormant invokes are actually restarted"
labels: [documentation, severity/low, area/persistence]
severity: Low
repro_script: repro/R4-37_restart_services_no_signal.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`Interpreter.from_snapshot(..., restart_services=True)` records the intent
to re-invoke dormant services (`_restart_services_on_start`), but the actual
re-invocation only happens inside `start()`. Between the `from_snapshot()`
call and the subsequent `start()` call, the restored interpreter's `status`
already reads `"running"` while `has_dormant_invocations` is still `True` —
a caller that checks dormancy before calling `start()` (a reasonable thing
to do when deciding whether a restore succeeded) sees a contradictory pair:
"I'm running" plus "my invokes are still dormant".

## Environment

- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- OS: Windows 11
- Editable install via `.venv-main`

## Current behaviour and why it is insufficient

```python
"""R4-37: from_snapshot(restart_services=True) has no effect until start()
is called, with no signal in between.

Interpreter.from_snapshot(..., restart_services=True) only records the
intent (`_restart_services_on_start`); the actual re-invocation of dormant
services happens inside start(). In between those two calls, `status`
already reads "running" while `has_dormant_invocations` is still True --
a caller who checks dormancy before calling start() sees a contradictory
pair (status says running, but the dormant invoke has not actually been
restarted).

Exits 1 (defect present) if, immediately after from_snapshot(restart_services=True)
and before start(), status == "running" AND has_dormant_invocations is True.
Exits 0 once that ordering no longer produces a contradictory pair.
"""
import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


async def main() -> int:
    async def slow_service(interp, ctx, ev):
        await asyncio.sleep(100)
        return "done"

    cfg = {
        "id": "m_dormant",
        "initial": "a",
        "states": {"a": {"invoke": {"src": "slow_service", "id": "svc"}}},
    }
    logic = MachineLogic(services={"slow_service": slow_service})
    machine = create_machine(cfg, logic=logic)

    interp = Interpreter(machine)
    await interp.start()
    snap = json.dumps(interp.get_persisted_snapshot())
    await interp.stop()

    restored = Interpreter.from_snapshot(snap, machine, restart_services=True)

    status_before_start = restored.status
    dormant_before_start = restored.has_dormant_invocations

    print("OBSERVED (after from_snapshot(restart_services=True), before start()):")
    print(f"  status                    = {status_before_start!r}")
    print(f"  has_dormant_invocations   = {dormant_before_start!r}")

    print(
        "\nEXPECTED: status should not read 'running' while dormant "
        "invocations have not yet been restarted -- the two signals should "
        "not contradict each other before start() runs"
    )

    await restored.start()
    await asyncio.sleep(0.05)
    print(f"\nAfter start(): has_dormant_invocations = {restored.has_dormant_invocations}")
    await restored.stop()

    defect_present = (status_before_start == "running") and dormant_before_start
    if defect_present:
        print("\nRESULT: contradictory pair observed before start() -- defect present")
        return 1
    else:
        print("\nRESULT: no contradiction -- fixed")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED (after from_snapshot(restart_services=True), before start()):
  status                    = 'running'
  has_dormant_invocations   = True

EXPECTED: status should not read 'running' while dormant invocations have not yet been restarted -- the two signals should not contradict each other before start() runs

After start(): has_dormant_invocations = False

RESULT: contradictory pair observed before start() -- defect present
```

## Expected behaviour

Either (a) `status` should not read `"running"` until `start()` has actually
run and dormant invokes have been handled, or (b) if `status="running"`
immediately after `from_snapshot()` is intentional (e.g. it reflects "this
interpreter's state machine is in a running state", not "the event loop is
processing"), then the `restart_services` parameter's docstring must say so
explicitly: `status` becomes accurate for scheduling purposes only after
`start()` is called, and `has_dormant_invocations` is the correct signal to
check in the interim, not `status`.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:1290`:

```python
interpreter._restart_services_on_start = restart_services
```

`from_snapshot` sets this flag and returns; the interpreter's `status`
property (set earlier during snapshot restoration) already reports
`"running"` at this point because the restored state machine is logically
in a running state (it has active state nodes), even though the Python-level
event loop and dormant service re-invocation have not started. The actual
re-invocation of dormant services driven by `_restart_services_on_start`
happens later, inside `start()` (`interpreter.py:338-340` for the async
engine, `sync_interpreter.py:265-270` for the sync engine). There is no
intermediate state/flag distinguishing "logically running, restart pending"
from "actually running, services restarted".

## Impact

For general users, code written defensively — "check `has_dormant_invocations`
before deciding whether to call `start()`" — is misled by `status` already
saying `"running"`, which looks like confirmation that everything, including
services, is live. For the adopting project's order-management scenario, a
supervisor process restoring interpreters after a crash and auditing
`status`/`has_dormant_invocations` together before deciding whether to
re-enqueue a `start()` call could treat a not-yet-restarted order machine as
already fully live. The severity is Low because the documented discipline —
always call `start()` immediately after `from_snapshot(restart_services=True)`,
then assert `has_dormant_invocations is False` — fully closes the gap; this
is purely an ordering/documentation trap for code that checks status first.

## Proposed API/text

Add to the `restart_services` parameter's docstring in
`Interpreter.from_snapshot` (and the sync equivalent):

> Note: setting `restart_services=True` only records the intent to
> re-invoke dormant services; the actual re-invocation happens inside
> `start()`. Between calling `from_snapshot(restart_services=True)` and
> calling `start()`, `status` may already report `"running"` while
> `has_dormant_invocations` is still `True`. Always call `start()`
> immediately after `from_snapshot(..., restart_services=True)` and treat
> `has_dormant_invocations` — not `status` — as the source of truth for
> whether dormant services have actually been restarted.

As a stronger alternative, introduce an intermediate status value (e.g.
`"restoring"`) that `status` reports between `from_snapshot()` and the
completion of `start()`, so the two signals never disagree; this is a
larger change and should be considered for a future minor version rather
than 0.8.1.

## Acceptance criteria

- [ ] `restart_services` parameter docstring in `base_interpreter.py`'s `from_snapshot` documents the status/has_dormant_invocations ordering caveat.
- [ ] `docs/` guide page for persistence/restore mentions the same caveat with a code example.
- [ ] `tests/test_persistence.py::test_restart_services_docstring_matches_behavior` (new, or existing test extended) asserts the documented ordering.
- [ ] `repro/R4-37_restart_services_no_signal.py` continues to demonstrate the (now-documented) behavior, or exits 0 if an intermediate status value is implemented instead.

## Related

- Register source: `battle-5e07ba8/observability/probe_matrix2.py` (`probe_dormant_invoke_restore`).
- Register row: R4-37 in `30-r4-findings-register.md`.
- Root cause file: `base_interpreter.py:1290`; re-invocation call sites: `interpreter.py:338-340`, `sync_interpreter.py:265-270`.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-37_restart_services_no_signal.py` in a fresh process: exit code 1, output matches the Observed section (`status='running'`, `has_dormant_invocations=True` before `start()`; `has_dormant_invocations=False` after `start()`).
- Confirmed root cause: `base_interpreter.py` sets `interpreter._restart_services_on_start = restart_services` in `from_snapshot` (~line 1290) with no accompanying status change; the actual re-invocation is gated on that flag in `interpreter.py` (~lines 337-340, inside `start()`, guarded by `if self._restart_services_on_start: ... self._restart_dormant_invocations()`) and in `sync_interpreter.py` (~lines 265-271, `if self.status == "running" and self._restart_services_on_start: ... self._restart_dormant_invocations()`). Matches the register's citation closely (line numbers off by ~1-2 lines only).
- No external XState/SCXML claim to check (this is about this library's own `status`/`has_dormant_invocations` API contract, not SCXML semantics).
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine --state all --search "restart_services dormant"` finds only issue #44 ("restore does not restart invokes... parked machines report running"), which is CLOSED and was about restart not happening at all (now fixed, per the repro's own confirmation that `has_dormant_invocations` becomes `False` after `start()`). This finding is a distinct, narrower docs/ordering gap in the already-fixed behavior, not a duplicate.
- No project name/label leakage found in the file.
- Status: reproducible, defect confirmed present.
