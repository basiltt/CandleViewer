"""R4-35: `sendTo` with an unresolvable target silently drops the event --
no error, no receipt failure, no plugin hook."""
import asyncio
import logging

logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "m",
    "initial": "s",
    "states": {
        "s": {
            "on": {
                "GO": {
                    "actions": [
                        {"type": "sendTo", "params": {"to": "no_such_actor", "event": {"type": "PING"}}}
                    ]
                }
            }
        }
    },
}


class Accountant(PluginBase):
    def __init__(self) -> None:
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.dropped.append((event.type, reason))


async def main() -> int:
    acc = Accountant()
    i = Interpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(acc)
    await i.start()
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.1)
    last_error = getattr(i, "last_error", None)
    print("OBSERVED receipt        :", r)
    print("OBSERVED last_transition_ok:", i.last_transition_ok)
    print("OBSERVED last_error     :", last_error)
    print("OBSERVED status         :", i.status)
    print("OBSERVED on_event_dropped:", acc.dropped)
    print(
        "EXPECTED: an unresolved sendTo target fires on_event_dropped (and/or "
        "sets last_error), matching the other drop paths (queue_full, "
        "not_running, chain_budget)."
    )
    ok = bool(acc.dropped)
    print("RESULT:", "PASS" if ok else "FAIL (silent drop: no on_event_dropped)")
    await i.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
