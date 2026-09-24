import json, asyncio
from xstate_statemachine import create_machine, MachineLogic, Interpreter
R={}
class P:
    def __init__(s): s.seen=[]
    def __getattr__(s,n):
        def f(*a,**k):
            if n=="on_unhandled_event": s.seen.append((a[1].type,a[3]))
        return f
async def case(name, cfg, ev, guards=None):
    m=create_machine(cfg,logic=MachineLogic(guards=guards or {}))
    i=Interpreter(m); p=P(); i.use(p); await i.start()
    r=await i.send(ev,wait=True)
    R[name]={"changed":r.changed,"error":repr(r.error)[:30],"deferred":r.deferred,
             "status":i.status,"last_ok":i.last_transition_ok,"hook":p.seen}
    await i.stop()
async def main():
    base=lambda pol,g=None: {"id":"m","initial":"a","onUnhandled":pol,
        "states":{"a":{"on":{"GO":({"target":"b","guard":g} if g else "b")}},"b":{}}}
    await case("A_real_noop_ignore", base("ignore"), "NOPE")
    await case("B_guard_denied_ignore", base("ignore","no"), "GO", {"no":lambda c,e:False})
    await case("C_unhandled_error", base("error"), "NOPE")
    await case("D_deferred", base("defer"), "NOPE")
    await case("E_guard_denied_error", base("error","no"), "GO", {"no":lambda c,e:False})
asyncio.run(main())
print(json.dumps(R,indent=1,default=str))
