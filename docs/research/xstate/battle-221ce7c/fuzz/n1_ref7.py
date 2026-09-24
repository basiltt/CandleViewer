import logging, copy, threading, collections
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
c=collections.Counter()
def mk(actname):
    def f(i,ctx,e,a=None): c.update([actname]); i.send("P" if actname=="ra" else "Q")
    return f
RAISE_PING = {"id":"m","initial":"a","states":{
 "a":{"entry":["ra"],"on":{"P":{"target":"#m.b"}}},
 "b":{"entry":["rb"],"on":{"Q":{"target":"#m.a"}}}}}
lg=MachineLogic(actions={"ra":mk("ra"),"rb":mk("rb")})
it=SyncInterpreter(create_machine(copy.deepcopy(RAISE_PING),logic=lg))
out={}
def r():
    try: it.start()
    except BaseException as e: out['exc']=f"{type(e).__name__}: {str(e)[:80]}"
th=threading.Thread(target=r,daemon=True);th.start();th.join(4)
print(f"  raise_2cycle alive={th.is_alive()} counts={dict(c)} {out}")
