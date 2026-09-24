import asyncio, json, sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter, MachineLogic
M=json.load(open("C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/research/xstate/battle-19cb1f1/contracts/B19.machine.json"))
M["states"]["stale_lockout"]["on"]["OPERATOR_RESOLVED"]={"target":"#reconciliation.idle","actions":["unlock_account"]}
names=set()
def collect(d):
    for k,v in d.items():
        if k in("entry","exit","actions"):
            for a in (v if isinstance(v,list) else [v]):
                if isinstance(a,str): names.add(a)
        elif isinstance(v,dict): collect(v)
        elif isinstance(v,list):
            for i in v:
                if isinstance(i,dict): collect(i)
collect(M); names.add("unlock_account")
log=[]
def mk(n):
    def f(i,c,e,ad): log.append(n)
    return f
acts={n:mk(n) for n in names}
async def fetch(i,c,e): raise RuntimeError("net")
async def diff(i,c,e): return []
async def rem(i,c,e): return []
guards={"failures_exhausted":lambda c,e:True,"divergences_found_and_auto_remediate":lambda c,e:False,"unresolved_divergences":lambda c,e:False}
async def main():
    m=create_machine(M,logic=MachineLogic(actions=dict(acts),guards=dict(guards),services={"fetch_exchange_state":fetch,"diff_against_local":diff,"apply_remediations":rem}))
    i=await Interpreter(m).start()
    await i.send("SWEEP_DUE"); await asyncio.sleep(0.2)
    print("async pre",i.current_state_ids)
    await i.send("OPERATOR_RESOLVED"); await asyncio.sleep(0.2)
    print("async post",i.current_state_ids,"unlock" in log)
    await i.stop()
asyncio.run(main())
def sfetch(i,c,e): raise RuntimeError("net")
def sdiff(i,c,e): return []
m=create_machine(M,logic=MachineLogic(actions=dict(acts),guards=dict(guards),services={"fetch_exchange_state":sfetch,"diff_against_local":sdiff,"apply_remediations":sdiff}))
s=SyncInterpreter(m).start()
s.send("SWEEP_DUE"); print("sync pre",s.current_state_ids)
s.send("OPERATOR_RESOLVED"); print("sync post",s.current_state_ids)
