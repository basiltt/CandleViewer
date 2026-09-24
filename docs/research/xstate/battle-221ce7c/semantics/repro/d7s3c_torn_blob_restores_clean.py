import asyncio, logging, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
logging.disable(logging.CRITICAL)
PARENT = {"id":"par","initial":"run","states":{"run":{"invoke":{"src":"child","id":"kid"}}}}
CHILD = {"id":"kid","initial":"x","context":{"q":0,"p":0},
         "states":{"x":{"on":{"STEP":"y"}},"y":{"entry":["set_q","set_p"]}}}
async def set_q(i_,c,e,a):
    c["q"]=100; await asyncio.sleep(0.05)
async def set_p(i_,c,e,a): c["p"]=101
async def amain():
    lg=lambda: MachineLogic(services={"child": create_machine(CHILD, logic=MachineLogic(actions={"set_q":set_q,"set_p":set_p}))})
    root=await Interpreter(create_machine(PARENT,logic=lg())).start()
    kid=next(a for k,a in root._actors.items() if k.endswith("kid"))
    t=kid.send("STEP",wait=True); await asyncio.sleep(0.02)
    blob=root.get_persisted_snapshot(); await t; await root.stop()
    r2=Interpreter.from_snapshot(json.dumps(blob), create_machine(PARENT,logic=lg()))
    k2=next(a for k,a in r2._actors.items() if k.endswith("kid"))
    print("restored:", sorted(k2.current_state_ids), dict(k2.context), "error=",r2.error,"status=",r2.status)
    await r2.stop()
asyncio.run(amain())
