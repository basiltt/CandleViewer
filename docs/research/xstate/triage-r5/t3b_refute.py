import json, asyncio
from xstate_statemachine import create_machine, MachineLogic, Interpreter
def gboom(c,e): raise RuntimeError("guardboom")
R={}
async def main():
    # 1. does status flip BEFORE the receipt resolves? (call-site discriminator)
    m=create_machine({"id":"u","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":"b"}},"b":{}}},logic=MachineLogic())
    i=await Interpreter(m).start()
    r=await i.send("NOPE", wait=True)
    R["discriminator_available_at_callsite"]={"status":i.status,"error":repr(i.error)[:50],"receipt_changed":r.changed}
    # 2. benign no-op under onUnhandled:ignore -> is it byte-identical INCLUDING status?
    m2=create_machine({"id":"n","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}},logic=MachineLogic())
    i2=await Interpreter(m2).start(); r2=await i2.send("NOPE", wait=True)
    R["benign_noop"]={"changed":r2.changed,"error":repr(r2.error),"deferred":r2.deferred,"status":i2.status}
    # 3. guardErrorPolicy raise -> receipt carries the error?
    for pol in ("false","true","raise"):
        m3=create_machine({"id":"g","initial":"a","guardErrorPolicy":pol,"states":{"a":{"on":{"GO":{"target":"b","guard":"bad"}}},"b":{}}},logic=MachineLogic(guards={"bad":gboom}))
        i3=await Interpreter(m3).start(); r3=await i3.send("GO",wait=True)
        R["guard_"+pol]={"changed":r3.changed,"error":repr(r3.error)[:40],"status":i3.status,
                         "last_ok":i3.last_transition_ok,"last_error":repr(i3.last_error)[:40]}
    # 4. on_guard_error / on_unhandled_event plugin hooks = out-of-band discriminator?
    seen=[]
    class P:
        def __getattr__(self,n):
            def f(*a,**k):
                if n in ("on_unhandled_event","on_guard_error"): seen.append((n,)+tuple(str(x)[:30] for x in a[1:]))
            return f
    m4=create_machine({"id":"u2","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":{"target":"b","guard":"no"}}},"b":{}}},logic=MachineLogic(guards={"no":lambda c,e:False}))
    i4=Interpreter(m4); i4.use(P()); await i4.start(); await i4.send("GO",wait=True)
    R["hook_discriminator"]=seen
asyncio.run(main())
print(json.dumps(R,indent=1,default=str))
