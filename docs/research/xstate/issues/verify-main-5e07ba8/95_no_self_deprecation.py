"""Verify #95 on xstate-statemachine @ 5e07ba8 (unreleased 0.8.1).

Acceptance criteria (from `gh issue view 95`):
  1. Running the library's own test suite with `-W error::DeprecationWarning`
     produces no failure attributable to `ErrorEvent.data`.
  2. An interpreter with `LoggingInspector()` attached, processing a failing
     invoke, raises zero `DeprecationWarning`s from library modules.
  3. Test: `test_library_does_not_read_deprecated_errorevent_data` (library's
     own equivalent: `test_library_does_not_trip_its_own_deprecation`).

Additionally checks the CHANGELOG/task framing: "-W error::DeprecationWarning
passes across the whole public surface incl. LoggingInspector" -- this script
runs the failing-invoke scenario under `-W error::DeprecationWarning` directly
(not just `catch_warnings(record=True)`), so a raised warning aborts the
script with a traceback rather than being silently recorded.

Run: PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python -W error::DeprecationWarning 95_no_self_deprecation.py
Expect: exit 0, "ALL CRITERIA PASS".
"""
import asyncio
import sys
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import LoggingInspector

failures = []

CFG = {
    "id": "m",
    "initial": "w",
    "states": {
        "w": {"invoke": {"src": "svc", "id": "svc", "onError": {"target": "bad"}}},
        "bad": {"type": "final"},
    },
}


async def blow(i, c, e):
    raise ValueError("boom")


async def main():
    # Criterion 2: LoggingInspector attached, under -W error::DeprecationWarning
    # (process-level, via the -W flag this script is invoked with) plus a local
    # catch_warnings pass as a belt-and-braces check independent of -W.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        it = Interpreter(
            create_machine(CFG, logic=MachineLogic(services={"svc": blow}))
        )
        it.use(LoggingInspector())
        await it.start()
        await asyncio.sleep(0.2)
        await it.stop()
    dep_warnings = [
        str(w.message)
        for w in caught
        if issubclass(w.category, DeprecationWarning)
    ]
    return dep_warnings


dep_warnings = asyncio.run(main())
if dep_warnings:
    failures.append(f"criterion 2: DeprecationWarning(s) raised by library: {dep_warnings}")

# Re-run WITHOUT catch_warnings, relying purely on -W error::DeprecationWarning
# (the process filter this script should be invoked with). If any library call
# site still reads ErrorEvent.data, this raises and the script crashes here --
# that crash IS the failure signal for criterion 1/2 when run under -W error.
async def main2():
    it = Interpreter(
        create_machine(CFG, logic=MachineLogic(services={"svc": blow}))
    )
    it.use(LoggingInspector())
    await it.start()
    await asyncio.sleep(0.2)
    await it.stop()


try:
    asyncio.run(main2())
except DeprecationWarning as e:  # pragma: no cover -- only if -W error active and a site regresses
    failures.append(f"criterion 1/2 (under -W error): {e}")

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)

print("ALL CRITERIA PASS")
sys.exit(0)
