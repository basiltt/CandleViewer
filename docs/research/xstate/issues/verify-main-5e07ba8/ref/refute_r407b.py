import asyncio
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter
cfg = {"id":"m","initial":"a","onUnhandled":"defer",
 "states":{"a":{"on":{"GO":"b"}},"b":{"on":{"BACK":"a"}}}}
# purely string API, no Event construction at all
i = SyncInterpreter(create_machine(cfg)).start()
fp=0
for k in range(3000):
    i.send("NOPE")
    r = i.send("GO", wait=True)
    if r.deferred: fp+=1
    i.send("BACK")
print("SYNC string-API false deferred:", fp, "/3000")

async def main():
    a = await Interpreter(create_machine(cfg)).start()
    f=0
    for k in range(1500):
        await a.send("NOPE")
        r = await a.send("GO", wait=True)
        if r.deferred: f+=1
        await a.send("BACK")
    print("ASYNC false deferred:", f, "/1500", "residue ids:", len(a._deferred_this_step))
    await a.stop()
asyncio.run(main())
