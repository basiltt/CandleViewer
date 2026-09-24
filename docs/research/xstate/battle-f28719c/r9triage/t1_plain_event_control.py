"""Control for N-1/N-2: with strict OFF, does a PLAIN Event named
`after.60000.m.work` / `done.state.m.p` drive the transition just as a
hand-built AfterEvent/DoneEvent does?  If yes, the "forgery" is not a
provenance bypass at all -- it is the documented open namespace.
Standalone: stdlib + xstate_statemachine only."""
import asyncio, json
from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.events import AfterEvent, DoneEvent, Event

AFTER = {"id": "m", "initial": "work", "states": {
    "work": {"after": {60000: "expired"}}, "expired": {"type": "final"}}}

DONE = {"id": "m", "initial": "p", "states": {
    "p": {"type": "parallel", "onDone": "finished", "states": {
        "a": {"initial": "x", "states": {"x": {"on": {"GA": "y"}}, "y": {"type": "final"}}},
        "b": {"initial": "x", "states": {"x": {"on": {"GB": "y"}}, "y": {"type": "final"}}}}},
    "finished": {"type": "final"}}}

async def run(cfg, ev):
    m = create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())
    i = Interpreter(m); await i.start()
    try:
        await i.send(ev)
    except Exception as e:
        await i.stop(); return f"refused:{type(e).__name__}"
    await asyncio.sleep(0.05)
    ids = list(i.current_state_ids); await i.stop(); return ids

async def main():
    out = {}
    out["after/AfterEvent"] = await run(AFTER, AfterEvent("after.60000.m.work", None, None))
    out["after/plainEvent"] = await run(AFTER, Event(type="after.60000.m.work", payload={}))
    out["after/plainStr"]   = await run(AFTER, "after.60000.m.work")
    out["done/DoneEvent"] = await run(DONE, DoneEvent("done.state.m.p", None, ""))
    out["done/plainEvent"] = await run(DONE, Event(type="done.state.m.p", payload={}))
    out["done/plainStr"]   = await run(DONE, "done.state.m.p")
    for k, v in out.items(): print(f"{k:22} {v}")
    same_after = out["after/AfterEvent"] == out["after/plainEvent"]
    same_done  = out["done/DoneEvent"] == out["done/plainEvent"]
    print("\nAfterEvent behaves same as a plain Event of that name:", same_after)
    print("DoneEvent  behaves same as a plain Event of that name:", same_done)
    print("VERDICT:", "OPEN-NAMESPACE (not a provenance bypass)" if (same_after and same_done)
          else "PROVENANCE BYPASS (public class is privileged over plain Event)")
asyncio.run(main())
