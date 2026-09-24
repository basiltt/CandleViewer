"""Verify #133: an unresolved sendTo target fires plugin.on_event_dropped
with reason "unresolved_target", and the analogous forwardTo path too.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


class Accountant(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):
        self.dropped.append((event.type, reason))


async def test_sendto():
    CFG = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": {
                        "actions": [
                            {
                                "type": "sendTo",
                                "params": {
                                    "to": "no_such_actor",
                                    "event": {"type": "PING"},
                                },
                            }
                        ]
                    }
                }
            }
        },
    }
    acc = Accountant()
    i = Interpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(acc)
    await i.start()
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.1)
    await i.stop()
    return acc.dropped, r


async def test_forwardto():
    CFG = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": {
                        "actions": [
                            {"type": "forwardTo", "params": {"to": "no_such_actor"}}
                        ]
                    }
                }
            }
        },
    }
    acc = Accountant()
    i = Interpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(acc)
    await i.start()
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.1)
    await i.stop()
    return acc.dropped, r


def main() -> int:
    dropped, r = asyncio.run(test_sendto())
    print("sendTo dropped:", dropped, "receipt:", r)
    check(
        "criterion: unresolved sendTo fires on_event_dropped(reason='unresolved_target')",
        any(reason == "unresolved_target" for _, reason in dropped),
    )

    dropped2, r2 = asyncio.run(test_forwardto())
    print("forwardTo dropped:", dropped2, "receipt:", r2)
    check(
        "criterion: unresolved forwardTo fires on_event_dropped too",
        bool(dropped2),
    )

    ok = all(c for _, c in results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
