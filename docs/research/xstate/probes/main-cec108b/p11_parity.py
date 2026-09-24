"""K-14: engine parity for #145 fail->stopped + parent onError; and
the async 'error' status/config contrast."""
import asyncio, json
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)
from xstate_statemachine.exceptions import TransitionFailedError

CHILD={"id":"kid","initial":"a","actionErrorPolicy":"fail",
       "states":{"a":{"on":{"BOOM":{"target":"b","actions":["boom"]}}},"b":{}}}
PARENT={"id":"par","initial":"run","states":{
    "run":{"invoke":{"src":"kid","id":"k","onError":{"target":"failed","actions":["rec"]},
                     "onDone":"ok"}},
    "failed":{"type":"final"},"ok":{"type":"final"}}}

def boom(i,c,e,a): raise ValueError("kaput")

async def amain():
    seen=[]
    def rec(i,c,e,a): seen.append(e.type)
    kid=create_machine(CHILD, logic=MachineLogic(actions={"boom":boom}))
    m=create_machine(PARENT, logic=MachineLogic(services={"kid":kid},
                                                actions={"rec":rec}))
    i=Interpreter(m); await i.start(); await asyncio.sleep(0.05)
    ch=i._actors.get("k") or list(i._actors.values())[0]
    await ch.send("BOOM"); await asyncio.sleep(0.3)
    print(f"[async] child status={ch.status} parent ids={sorted(i.current_state_ids)} onError={seen}")
    await i.stop()

def smain():
    seen=[]
    def rec(i,c,e,a): seen.append(e.type)
    kid=create_machine(CHILD, logic=MachineLogic(actions={"boom":boom}))
    m=create_machine(PARENT, logic=MachineLogic(services={"kid":kid},
                                                actions={"rec":rec}))
    i=SyncInterpreter(m).start()
    ch=list(i._actors.values())[0] if i._actors else None
    print("[sync] actors:", list(i._actors))
    if ch:
        ch.send("BOOM")
        print(f"[sync] child status={ch.status} parent ids={sorted(i.current_state_ids)} onError={seen}")

asyncio.run(amain()); smain()
