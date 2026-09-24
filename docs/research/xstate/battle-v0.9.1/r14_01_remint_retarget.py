import asyncio, os
from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.events import re_mint
KIND=os.environ.get("K","async")
cap={}
async def aq(i,c,e): return 1
async def av(i,c,e): await asyncio.sleep(30); return 2
def dq(i,c,e): return 1
async def adone(i,c,e,a=None): cap['ev']=e
def ddone(i,c,e,a=None): cap['ev']=e
cfg={"id":"m","type":"parallel","states":{
 "a":{"initial":"r","states":{"r":{"invoke":{"src":"quick","onDone":{"target":"d","actions":"cap"}}},"d":{}}},
 "pay":{"initial":"w","states":{"w":{"invoke":{"src":"victim","onDone":"settled"}},"settled":{}}}}}
from xstate_statemachine import MachineLogic
lg=MachineLogic(services={"quick":aq if KIND=="async" else dq,"victim":av},actions={"cap":adone if KIND=="async" else ddone})
async def main():
  it=await Interpreter(create_machine(cfg,logic=lg)).start()
  for _ in range(50):
    if 'ev' in cap: break
    await asyncio.sleep(0.05)
  print("orig",cap["ev"])
  f=re_mint(cap['ev'],type="done.invoke.m.pay.w",src=cap["ev"].src.replace("m.a.r","m.pay.w") if cap["ev"].src else "m.pay.w")
  await it.send(f)
  for _ in range(40):
    if "pay.settled" in str(it.current_state_ids): break
    await asyncio.sleep(0.05)
  print(KIND, sorted(it.current_state_ids)); await it.stop()
  raise SystemExit(1 if any("settled" in s for s in it.current_state_ids) else 0)
asyncio.run(main())
