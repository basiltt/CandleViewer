# -*- coding: utf-8 -*-
"""Does a bare/partial MachineLogic fail at BUILD or at RUN time?"""
import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.clock import SimulatedClock

cfg = json.load(open("B17.catalogue.json", encoding="utf-8"))
res = {}
m = create_machine(cfg, logic=MachineLogic(strict=True))
res["build_bare_strict"] = "OK"

async def main():
    interp = Interpreter(m, clock=SimulatedClock())
    try:
        await interp.start(); await asyncio.sleep(0.05)
        res["start"] = "OK ids=" + str(sorted(interp.current_state_ids))
    except Exception as e:
        res["start"] = f"{type(e).__name__}: {str(e)[:200]}"
    try:
        r = await interp.send("EVIDENCE_RECORDED", wait=True)
        await asyncio.sleep(0.05)
        res["send"] = f"receipt changed={r.changed} error={r.error!r} deferred={getattr(r,'deferred',None)}"
        res["ids"] = sorted(interp.current_state_ids)
    except Exception as e:
        res["send"] = f"{type(e).__name__}: {str(e)[:300]}"
    await interp.stop()
asyncio.run(main())
print(json.dumps(res, indent=2))
json.dump(res, open("results/c0b_lazy.json","w",encoding="utf-8"), indent=2)
