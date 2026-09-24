"""DE-L3 repro: a `def` action calling send(wait=True) gets the _Awaitable
guard unawaited, silently. STANDALONE: stdlib + xstate_statemachine only.
Run from cwd C:/Users/basil.
"""
import sys, asyncio
sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/src",
)
from xstate_statemachine import create_machine, MachineLogic, Interpreter

result = {}


def my_action(interp, context, event, action_def):
    # A synchronous action calling send(wait=True) on its own interpreter.
    # #219 makes the ASYNC-action shape raise ReentrantWaitError instead of
    # deadlocking -- this sync shape gets neither the receipt nor the error.
    r = interp.send("B", wait=True)
    result["type"] = type(r).__name__


cfg = {
    "id": "m",
    "initial": "s1",
    "actionErrorPolicy": "rollback",
    "states": {
        "s1": {"on": {"A": {"target": "s2", "actions": ["my_action"]}}},
        "s2": {"on": {"B": "s3"}},
        "s3": {"type": "final"},
    },
}
m = create_machine(cfg, logic=MachineLogic(actions={"my_action": my_action}))


async def main():
    i = Interpreter(m)
    await i.start()
    await i.send("A", wait=True)
    print("final status:", i.status, "last_error:", i.last_error)
    print("send(wait=True) returned:", result)
    # The defect: a `def` action asking for a receipt gets the internal
    # guard object back, unawaited, with no error raised anywhere.
    return result.get("type") == "_Awaitable" and i.last_error is None


reproduced = asyncio.run(main())
print()
print("REPRODUCED:", reproduced)
sys.exit(1 if reproduced else 0)
