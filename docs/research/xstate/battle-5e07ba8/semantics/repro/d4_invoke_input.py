"""D-semantics: how invoke `input` reaches a child MACHINE's context.

`_build_initial_context` (base_interpreter.py:530) deliberately refuses to
overwrite declared context keys, exposing input only at context["input"].
This documents the CONTRACT, so the adopting project uses the supported
`context` factory form rather than expecting key merge.
"""
import asyncio, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

def probe(child_cfg, label):
    seen = {}
    def note(i, c, e, a): seen["ctx"] = dict(c) if isinstance(c, dict) else c
    child = create_machine(child_cfg, logic=MachineLogic(actions={"note": note}))
    CFG = {"id":"m","initial":"run","context":{"n":11},"states":{
      "run":{"invoke":{"id":"kid","src":"childMachine",
             "input": lambda a: {"seed": a["context"]["n"]},
             "onDone":"ok"}}, "ok":{}}}
    async def m():
        i = await Interpreter(create_machine(CFG, logic=MachineLogic(
            services={"childMachine": child}))).start()
        await asyncio.sleep(0.25); await i.stop()
    asyncio.run(m())
    print(f"{label:34} child context at entry = {seen.get('ctx')}")

probe({"id":"c","initial":"w","context":{"seed":0},
       "states":{"w":{"entry":["note"],"always":"fin"},"fin":{"type":"final"}}},
      "declared context dict")
probe({"id":"c","initial":"w",
       "context": lambda a: {"seed": (a.get("input") or {}).get("seed", -1)},
       "states":{"w":{"entry":["note"],"always":"fin"},"fin":{"type":"final"}}},
      "context FACTORY reading input")
