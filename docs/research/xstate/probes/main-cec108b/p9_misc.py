"""K-9..K-12: Receipt.denied+defer, _die double-cancel, RootTargetError,
service_executor reuse after stop()."""
import asyncio, concurrent.futures, json, time
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)
from xstate_statemachine.exceptions import RootTargetError, InvalidConfigError

# --- RootTargetError hierarchy
import xstate_statemachine.exceptions as X
print("[1] RootTargetError MRO:", [c.__name__ for c in RootTargetError.__mro__][:5])
for flag in (True, False):
    try:
        create_machine({"id":"r","initial":"a","states":{"a":{"on":{"G":"#r"}}}},
                       logic=MachineLogic(), strict_targets=flag)
        print(f"    strict_targets={flag}: ACCEPTED (bad)")
    except RootTargetError as e:
        print(f"    strict_targets={flag}: RootTargetError ok")
    except Exception as e:
        print(f"    strict_targets={flag}: {type(e).__name__}: {e}")

# --- Receipt.denied with defer
async def denied_defer():
    cfg={"id":"d","initial":"a","states":{"a":{
        "on":{"G":[{"target":"b","guard":"never"}], "D":{"target":"a","actions":["defer"]}}},
        "b":{}}}
    m=create_machine(cfg, logic=MachineLogic(guards={"never": lambda c,e: False}))
    i=Interpreter(m); await i.start()
    r=await i.send("G", wait=True)
    print(f"[2] guard-denied receipt: changed={r.changed} denied={r.denied} deferred={r.deferred}")
    r2=await i.send("NOPE", wait=True)
    print(f"    undeclared event:     changed={r2.changed} denied={r2.denied}")
    await i.stop()

# --- _die under double cancel
async def die_double():
    cfg={"id":"k","initial":"a","states":{"a":{"on":{"X":"a"}}}}
    m=create_machine(cfg, logic=MachineLogic())
    i=Interpreter(m); await i.start()
    t=i._event_loop_task
    t.cancel(); t.cancel()
    await asyncio.sleep(0.05)
    print(f"[3] double-cancel: status={i.status} is_running={i.is_running} "
          f"err={type(i.error).__name__ if i.error else None}")
    # cancel before first turn
    i2=Interpreter(create_machine(cfg, logic=MachineLogic()))
    await i2.start()
    i2._event_loop_task.cancel()
    await asyncio.sleep(0.05)
    print(f"    cancel-early: status={i2.status} is_running={i2.is_running}")

# --- executor reuse after stop
async def exec_after_stop():
    def slow(i,c,e):
        time.sleep(0.05); return 1
    cfg={"id":"e","initial":"s","states":{"s":{"invoke":{"src":"slow","onDone":"d"}},
         "d":{"type":"final"}}}
    ex=concurrent.futures.ThreadPoolExecutor(max_workers=2)
    m=create_machine(cfg, logic=MachineLogic(services={"slow":slow}))
    i=Interpreter(m, service_executor=ex); await i.start()
    await asyncio.sleep(0.2)
    print(f"[4] caller-supplied executor: status={i.status}")
    await i.stop()
    print(f"    after stop, caller executor shut down? "
          f"{getattr(ex, '_shutdown', None)} (should be False/None)")
    ex.shutdown()

async def main():
    await denied_defer(); await die_double(); await exec_after_stop()
asyncio.run(main())
