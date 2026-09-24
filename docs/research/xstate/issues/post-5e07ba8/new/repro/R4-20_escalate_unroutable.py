"""R4-20: `escalate()` from an invoked child is unroutable -- it reaches
neither `onError` nor `"*"`, because the escalation event's `type`/`src` are
minted from the runtime actor id, not the declared invoke id."""
import asyncio
import logging

logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

got = []


def spy(i, c, e, a):  # noqa: ANN001
    got.append(e.type)


child = create_machine(
    {
        "id": "child",
        "initial": "w",
        "states": {"w": {"entry": [{"type": "escalate", "params": {"error": "child failed"}}]}},
    },
    logic=MachineLogic(),
)

CFG = {
    "id": "m",
    "initial": "run",
    "states": {
        "run": {
            "invoke": {"id": "kid", "src": "childMachine", "onError": "caught"},
            "on": {"*": {"actions": ["spy"]}},
        },
        "caught": {},
    },
}


async def main() -> int:
    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(services={"childMachine": child}, actions={"spy": spy}))
    ).start()
    await asyncio.sleep(0.4)
    states = sorted(i.current_state_ids)
    print("OBSERVED parent state     :", states)
    print("OBSERVED events seen by '*':", got)
    print("EXPECTED: parent reaches ['m.caught'] via onError")
    ok = "m.caught" in states
    print("RESULT:", "PASS" if ok else "FAIL (escalate unroutable to onError)")
    await i.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
