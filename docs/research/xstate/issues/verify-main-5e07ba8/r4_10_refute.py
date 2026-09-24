import asyncio
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

CONFIG = {"id":"t","initial":"waiting","context":{"fired":False},
  "states":{"waiting":{"after":{"300":{"target":"expired","actions":["mark"]}},"on":{"OK":{"target":"ok"}}},
            "expired":{"type":"final"},"ok":{"type":"final"}}}
def mark(i,c,e,a): c["fired"]=True
def build(): return create_machine(CONFIG, logic=MachineLogic(actions={"mark":mark}))

async def main():
    # real-clock reference
    i1 = await Interpreter(build()).start()
    await asyncio.sleep(0.5)
    print("REF real clock:", sorted(i1.current_state_ids), i1.context); await i1.stop()

    for rs in (False, True):
        i2 = await Interpreter(build()).start()
        await asyncio.sleep(0.05)
        blob = i2.get_snapshot(); await i2.stop()
        i3 = Interpreter.from_snapshot(blob, build(), restart_services=rs)
        await i3.start()
        await asyncio.sleep(0.8)   # way past 300ms
        print(f"ASYNC restart={rs}:", sorted(i3.current_state_ids), i3.context,
              "dormant=", i3.has_dormant_invocations, "pending=", i3.pending_invocations())
        await i3.stop()

    # sync engine
    for rs in (False, True):
        s = SyncInterpreter(build()).start()
        blob = s.get_snapshot(); s.stop()
        s2 = SyncInterpreter.from_snapshot(blob, build(), restart_services=rs).start()
        import time; time.sleep(0.5); s2.tick()
        print(f"SYNC  restart={rs}:", sorted(s2.current_state_ids), s2.context,
              "dormant=", s2.has_dormant_invocations)
        s2.stop()
asyncio.run(main())
