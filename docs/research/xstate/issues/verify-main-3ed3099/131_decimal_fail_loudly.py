"""Verify #131: get_snapshot() must fail loudly (not silently stringify) on
non-JSON-native pending event data (e.g. Decimal), per the CHANGELOG claim
that non-JSON pending data raises SnapshotSerializationError.
"""
import decimal
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent
from xstate_statemachine.exceptions import SnapshotSerializationError

import asyncio

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"done.invoke.svc": {"target": "b"}}}, "b": {}},
}


async def main() -> int:
    i = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await i.start()
    i._event_queue.put_nowait(
        DoneEvent(
            type="done.invoke.svc",
            data={"amount": decimal.Decimal("10.50")},
            src="svc",
        )
    )

    raised = None
    try:
        i.get_snapshot()
    except SnapshotSerializationError as exc:
        raised = exc
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(
        "criterion: persisting non-JSON-native event data raises "
        "SnapshotSerializationError naming the offending event type",
        isinstance(raised, SnapshotSerializationError)
        and "svc" in str(raised) or (raised is not None and "done.invoke.svc" in str(raised)),
    )
    print("raised:", type(raised).__name__, "->", raised)

    # Now confirm a JSON-safe payload still round-trips fine (no false
    # positive / regression on the common case).
    i2 = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await i2.start()
    i2._event_queue.put_nowait(
        DoneEvent(type="done.invoke.svc", data={"amount": "10.50"}, src="svc")
    )
    s = i2.get_snapshot()
    check("criterion: JSON-safe payload still persists without error", bool(s))
    await i.stop()
    await i2.stop()

    ok = all(c for _, c in results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
