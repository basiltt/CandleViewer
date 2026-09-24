import sys, threading, time
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
MAXIT=int(sys.argv[1]) if len(sys.argv)>1 else 1000
CFG={"id":"m","type":"parallel","maxIterations":MAXIT,"states":{
 "A":{"initial":"a1","states":{"a1":{"invoke":{"id":"s","src":"svc","onDone":"a1"}},"a2":{}}},
 "B":{"initial":"b1","states":{"b1":{"always":{"target":"#m.A.a1"}}}}}}
def svc(i,c,e): return 1
res={}
def run():
    t0=time.time()
    s=SyncInterpreter(create_machine(CFG,logic=MachineLogic(services={"svc":svc})))
    try: s.start()
    except Exception as ex: res['err']=repr(ex)
    res['t']=time.time()-t0; res['ids']=s.current_state_ids; res['status']=s.status
    res['ok']=s.last_transition_ok; res['lasterr']=s.last_error; res['q']=s.queue_depth
th=threading.Thread(target=run,daemon=True); th.start(); th.join(20)
if th.is_alive(): print(f"maxIterations={MAXIT}: STILL RUNNING after 20s -> NON-TERMINATING")
else: print(f"maxIterations={MAXIT}: settled in {res['t']:.2f}s", res)
