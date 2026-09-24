import asyncio, logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, Interpreter
inner=[]
def bump(i,c,e,a): inner.append(1)
cfg={"id":"m","initial":"a","states":{"a":{"on":{
  "SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]},
  "WORK":{"actions":[{"type":"raise","params":{"event":"INNER"}}]},
  "INNER":{"actions":["bump"]}}}}}
async def main():
    i=await Interpreter(create_machine(cfg, logic=MachineLogic(actions={"bump":bump}))).start()
    await i.send_events(["SPIN"]+["WORK"]*5)
    await asyncio.sleep(1.0)
    print("ASYNC INNER handled:", len(inner), "of 5")
    await i.stop()
asyncio.run(main())
