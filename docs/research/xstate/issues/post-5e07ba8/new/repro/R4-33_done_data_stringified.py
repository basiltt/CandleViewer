"""R4-33: `get_snapshot()` uses `json.dumps(default=str)`: a `DoneEvent`
payload with a non-JSON value (e.g. `Decimal`) is SILENTLY stringified. On
restore the `onDone` handler receives a `str` where it expects a `Decimal` --
no error, no warning."""
from __future__ import annotations

import asyncio
import decimal
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent

seen = {}


def cap(i, c, e, a):  # noqa: ANN001
    seen["data"] = e.data


CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"done.invoke.svc": {"target": "b", "actions": ["cap"]}}}, "b": {}},
}


async def main() -> int:
    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"cap": cap})))
    await i.start()
    i._event_queue.put_nowait(
        DoneEvent(type="done.invoke.svc", data={"amount": decimal.Decimal("10.50")}, src="svc")
    )
    s = i.get_snapshot()
    await i.stop()
    print("OBSERVED persisted pending_events:", json.loads(s)["pending_events"])

    i2 = Interpreter.from_snapshot(s, create_machine(CFG, logic=MachineLogic(actions={"cap": cap})))
    await i2.start()
    await asyncio.sleep(0.3)
    d = seen.get("data")
    types = {k: type(v).__name__ for k, v in d.items()}
    print("OBSERVED onDone received:", d, "types:", types)
    await i2.stop()

    print("EXPECTED: restore either preserves the Decimal or raises at persist time; "
          "it must not silently hand the handler a str.")
    ok = isinstance(d["amount"], decimal.Decimal)
    print("RESULT:", "PASS" if ok else "FAIL (Decimal silently coerced to str across snapshot)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
