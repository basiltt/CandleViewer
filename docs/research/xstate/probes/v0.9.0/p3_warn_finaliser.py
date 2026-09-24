"""S-probe 3: #232 RuntimeWarning determinism + -W error behaviour +
false positive when the guard is stored and awaited later."""
import asyncio, gc, sys, warnings
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {"id": "m", "initial": "a", "states": {
    "a": {"entry": ["drop"], "on": {"B": "b"}}, "b": {}}}

MODE = sys.argv[1]
box = {}

def drop_def(i, c, e, a):
    r = i.send("B", wait=True)
    if MODE == "store_later":
        box["r"] = r          # stored, awaited later
    # else: dropped on the floor

async def main():
    m = create_machine(CFG, logic=MachineLogic(actions={"drop": drop_def}))
    i = Interpreter(m)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.start()
        await asyncio.sleep(0.15)
        gc.collect(); await asyncio.sleep(0.05); gc.collect()
        msgs = [str(x.message)[:60] for x in w if x.category is RuntimeWarning]
    print(MODE, "warnings=", len(msgs), msgs)
    if MODE == "store_later":
        try:
            await asyncio.wait_for(box["r"], 2)
            print("  later-await: OK")
        except Exception as ex:
            print("  later-await:", type(ex).__name__, ex)
        del box["r"]
    print("  state=", sorted(i.current_state_ids))
    await i.stop()
    gc.collect()

asyncio.run(asyncio.wait_for(main(), 25))
