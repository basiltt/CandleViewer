import asyncio
from xstate_statemachine import Interpreter, create_machine, MachineLogic
from xstate_statemachine.events import ErrorEvent, DoneEvent

CHILD={"id":"c","initial":"w","states":{"w":{"on":{"FIN":"d"}},"d":{"type":"final"}}}
LOG=[]
PARENT={"id":"p","initial":"run","states":{
 "run":{"invoke":{"id":"job","src":"child","onDone":{"target":"ok","actions":["note_done"]},
                  "onError":{"target":"bad","actions":["note_err"]}},
        "on":{"LEAVE":"gone"}},
 "ok":{},"bad":{},"gone":{}}}

def note_done(i,ctx,e,ad=None): LOG.append(("onDone",type(e).__name__))
def note_err(i,ctx,e,ad=None): LOG.append(("onError",type(e).__name__,type(getattr(e,'error',None)).__name__))

async def main():
    # 1) teardown: leave the invoking state -> child must stop, no onDone
    logic=MachineLogic(actions={"note_done":note_done,"note_err":note_err},
                       services={"child":create_machine(CHILD)})
    i=Interpreter(create_machine(PARENT,logic=logic)); await i.start()
    await asyncio.sleep(0.05)
    kid=list(i._actors.values())[0] if i._actors else None
    print("child running before LEAVE:", kid.status if kid else None)
    await i.send("LEAVE"); await asyncio.sleep(0.1)
    print("after LEAVE: state=",i.current_state_ids," child=",kid.status if kid else None,
          " actors=",list(i._actors)," LOG=",LOG)
    print("tasks alive:", len([t for t in asyncio.all_tasks() if not t.done()]))
    await i.stop()

    # 2) error delivery: child service raises -> ErrorEvent?
    LOG.clear()
    async def boom(i,ctx,e): raise ValueError("nope")
    logic2=MachineLogic(actions={"note_done":note_done,"note_err":note_err},services={"child":boom})
    j=Interpreter(create_machine(PARENT,logic=logic2)); await j.start()
    await asyncio.sleep(0.15)
    print("error path: state=",j.current_state_ids," LOG=",LOG)
    await j.stop()

    # 3) success ordering
    LOG.clear()
    logic3=MachineLogic(actions={"note_done":note_done,"note_err":note_err},
                        services={"child":create_machine(CHILD)})
    k=Interpreter(create_machine(PARENT,logic=logic3)); await k.start()
    await asyncio.sleep(0.05)
    kid3=list(k._actors.values())[0]
    await kid3.send("FIN"); await asyncio.sleep(0.15)
    print("done path: state=",k.current_state_ids," LOG=",LOG)
    await k.stop()
asyncio.run(main())
