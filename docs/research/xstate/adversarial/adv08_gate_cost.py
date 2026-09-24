"""Adversarial: is the 'statecharts GATE the hot path' pattern itself cheap enough?"""
import asyncio, time, logging
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic
M={"id":"book","initial":"live","context":{},
 "states":{"live":{"tags":["consumable"],"on":{"GAP":{"target":"#book.desynced"}}},
           "desynced":{"on":{"SNAP":{"target":"#book.live"}}}}}
async def main():
    m=create_machine(M,logic=MachineLogic())
    i=await Interpreter(m).start()
    N=500000
    t=time.perf_counter()
    for _ in range(N): i.matches("live")
    a=(time.perf_counter()-t)/N*1e6
    t=time.perf_counter()
    for _ in range(N): i.has_tag("consumable")
    b=(time.perf_counter()-t)/N*1e6
    flag=True
    t=time.perf_counter()
    for _ in range(N):
        if flag: pass
    c=(time.perf_counter()-t)/N*1e6
    print(f"[gate_cost] per book delta (2k/s x 24 symbols = 48k/s hot path):")
    print(f"   interp.matches('live')   = {a:.3f} us  -> {a*48000/1e6*100:.2f}% of one core at 48k/s")
    print(f"   interp.has_tag(...)      = {b:.3f} us  -> {b*48000/1e6*100:.2f}% of one core")
    print(f"   plain bool flag          = {c:.4f} us  -> {a/c:.0f}x cheaper")
    print(f"   VERDICT: gating by querying the interpreter is affordable but {a/c:.0f}x a bool;")
    print(f"            the machine should PUBLISH a bool the hot path reads, not be queried.")
    await i.stop()
asyncio.run(main())
