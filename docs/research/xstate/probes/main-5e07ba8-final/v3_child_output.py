import asyncio
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
CHILD={"id":"kid","initial":"w","context":{"ctxkey":1},"output":{"code":7},"states":{"w":{"always":"fin"},"fin":{"type":"final"}}}
PAR={"id":"m","initial":"run","states":{"run":{"invoke":{"id":"kid","src":"kidm","onDone":{"target":"done","actions":["cap"]}}},"done":{}}}
seen={}
def cap(i,c,e,a): seen['data']=e.data
async def main():
    kid=create_machine(CHILD,logic=MachineLogic())
    i=Interpreter(create_machine(PAR,logic=MachineLogic(actions={"cap":cap},services={"kidm":kid})))
    await i.start(); await asyncio.sleep(0.4)
    print("ASYNC done.invoke data:",seen.get('data'))
    await i.stop()
asyncio.run(main())
seen.clear()
kid=create_machine(CHILD,logic=MachineLogic())
s=SyncInterpreter(create_machine(PAR,logic=MachineLogic(actions={"cap":cap},services={"kidm":kid})))
s.start(); print("SYNC done.invoke data:",seen.get('data'))
