# Do #205's hardening knobs stop the v2-downgrade forge?
import asyncio, json, copy
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"vault","initial":"locked","context":{"o":0},
 "states":{"locked":{"after":{600000:{"target":"open","actions":["log"]}}},"open":{"entry":["log"]}}}
def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"log":lambda i,c,e,a:c.__setitem__("o",c["o"]+1)}))
async def main():
    i=await Interpreter(mk()).start(); await asyncio.sleep(0.05)
    base=json.loads(json.dumps(i.get_persisted_snapshot())); await i.stop()
    good_hash=base["machine_hash"]
    forged=copy.deepcopy(base); forged["version"]=2
    forged["pending_events"]=[{"type":"after.600000.vault.locked","kind":"after","payload":{}}]
    for label,kw in (("defaults",{}),
                     ("minimum_version=1",{"minimum_version":1}),
                     ("minimum_version=3",{"minimum_version":3}),
                     ("expected_machine_hash (correct)",{"expected_machine_hash":good_hash})):
        try:
            r=Interpreter.from_snapshot(json.dumps(forged), mk(), **kw)
            await r.start(); await asyncio.sleep(0.12)
            print(f"  {label:34s} -> states={sorted(r.current_state_ids)} FORGE_WORKED={'open' in str(r.current_state_ids)}")
            await r.stop()
        except Exception as e:
            print(f"  {label:34s} -> BLOCKED {type(e).__name__}: {str(e)[:70]}")
asyncio.run(main())
