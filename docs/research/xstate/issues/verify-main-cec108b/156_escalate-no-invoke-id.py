"""Verify #156 on cec108b: escalate reaches onError without an explicit
invoke.id, and the explicit-id case still works too (regression guard).
Exit 0 only if all criteria pass."""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

CHILD = {
    "id": "c", "initial": "w",
    "states": {"w": {"entry": [{"type": "escalate", "params": {"error": "child exploded"}}]}},
}


def parent(explicit: bool):
    inv = {"src": "kid", "onError": "caught"}
    if explicit:
        inv["id"] = "kid"
    return {"id": "p", "initial": "w", "states": {"w": {"invoke": inv}, "caught": {}}}


def main() -> int:
    results = []
    for explicit in (False, True):
        s = SyncInterpreter(
            create_machine(parent(explicit), logic=MachineLogic(services={"kid": create_machine(CHILD)}))
        ).start()
        reached = s.value == "caught"
        s.stop()
        results.append((f"sync onError reached (explicit_id={explicit})", reached))

        async def run_async():
            i = await Interpreter(
                create_machine(parent(explicit), logic=MachineLogic(services={"kid": create_machine(CHILD)}))
            ).start()
            for _ in range(50):
                if i.value == "caught":
                    break
                await asyncio.sleep(0.01)
            v = i.value
            await i.stop()
            return v

        av = asyncio.run(run_async())
        results.append((f"async onError reached (explicit_id={explicit})", av == "caught"))

    print("RESULTS:")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
