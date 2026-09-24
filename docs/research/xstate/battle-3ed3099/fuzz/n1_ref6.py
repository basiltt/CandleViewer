import logging, copy, threading, collections
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
# Does the same defeat happen WITHOUT invokes -- e.g. two states each raising one event?
RAISE_PING = {"id":"m","initial":"a","states":{
 "a":{"entry":[{"type":"xstate.raise","event":"P"}],"on":{"P":{"target":"#m.b"}}},
 "b":{"entry":[{"type":"xstate.raise","event":"Q"}],"on":{"Q":{"target":"#m.a"}}}}}
# parallel regions, one invoke each, onDone -> common parallel ancestor
PAR = {"id":"m","initial":"p","states":{"p":{"type":"parallel","states":{
 "r1":{"initial":"x","states":{"x":{"invoke":{"id":"i1","src":"s1","onDone":{"target":"#m.p"}}}}},
 "r2":{"initial":"y","states":{"y":{"invoke":{"id":"i2","src":"s2","onDone":{"target":"#m.p"}}}}}}}}}
def run(name,cfg,secs=3):
    c=collections.Counter()
    lg=MachineLogic(services={"s1":lambda i,x,e:(c.update(['s1']),{"o":1})[1],
                              "s2":lambda i,x,e:(c.update(['s2']),{"o":1})[1]})
    out={}
    try: it=SyncInterpreter(create_machine(copy.deepcopy(cfg),logic=lg))
    except BaseException as e: print(f"  {name:<14} BUILD {type(e).__name__}: {str(e)[:70]}"); return
    def r():
        try: it.start()
        except BaseException as e: out['exc']=f"{type(e).__name__}: {str(e)[:70]}"
    th=threading.Thread(target=r,daemon=True);th.start();th.join(secs)
    print(f"  {name:<14} alive={th.is_alive()} counts={dict(c)} {out}")
run("raise_ping_pong",RAISE_PING)
run("parallel_2invoke",PAR)
