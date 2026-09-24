"""#225 task-identity matrix: which senders are treated as "inside one of my
actions" (internal lane / wait=True refused) and which are ordinary external
traffic?

Cells:
  A action -> send() directly                      expect INTERNAL
  B action -> await helper coroutine -> send()     expect INTERNAL (same task)
  C action -> ensure_future(worker) -> send()      expect EXTERNAL
  D action -> task -> task -> send()               expect EXTERNAL
  E action -> await send(wait=True)                expect ReentrantWaitError
  F action -> ensure_future(send(wait=True))       expect resolves (hand-out)
  G after-handler action -> send()                 expect INTERNAL
  H child action -> parent.send()                  expect EXTERNAL

"EXTERNAL" is proved by the decisive #225 symptom: with the loop otherwise
idle, an externally-routed event is delivered without another event being
pumped; an internally-queued one is drained only inside a macrostep.
"""
import asyncio, json, os
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 ReentrantWaitError)

def cfg(name):
    return {"id": name, "initial": "a",
            "context": {"log": [], "wait_ok": None, "err": None},
            "states": {"a": {"entry": ["probe"],
                             "on": {"PING": {"actions": ["note"]},
                                    "GO": "b"}},
                       "b": {}}}

def mk(probe, kind):
    if kind == "def":
        def note(i, c, e, a):
            c["log"].append(e.type)
    else:
        async def note(i, c, e, a):
            c["log"].append(e.type)
    return create_machine(cfg("m"),
                          logic=MachineLogic(actions={"probe": probe,
                                                      "note": note}))

async def run(probe, kind, settle=0.35):
    i = Interpreter(mk(probe, kind))
    await i.start()
    await asyncio.sleep(settle)   # loop idle: NOTHING else is pumped
    log = list(i.context["log"])
    ctx = dict(i.context)
    await i.stop()
    return log, ctx

async def main():
    kind = os.environ.get("XS_SVC", "async")
    rows = {}

    async def A(i, c, e, a):
        i.send("PING")
    rows["A_action_direct"] = (await run(A, kind))[0]

    async def helper(i):
        await asyncio.sleep(0)
        i.send("PING")
    async def B(i, c, e, a):
        await helper(i)
    rows["B_action_await_helper"] = (await run(B, kind))[0]

    async def worker(i):
        await asyncio.sleep(0.02)
        i.send("PING")
    async def C(i, c, e, a):
        asyncio.ensure_future(worker(i))
    rows["C_action_spawns_worker"] = (await run(C, kind))[0]

    async def inner(i):
        await asyncio.sleep(0.01)
        i.send("PING")
    async def outer(i):
        await asyncio.sleep(0.01)
        asyncio.ensure_future(inner(i))
    async def D(i, c, e, a):
        asyncio.ensure_future(outer(i))
    rows["D_task_of_task"] = (await run(D, kind))[0]

    async def E(i, c, e, a):
        try:
            await i.send("PING", wait=True)
            c["err"] = "NO-REFUSAL"
        except ReentrantWaitError as ex:
            c["err"] = type(ex).__name__
    _, ctxE = await run(E, kind)
    rows["E_inflight_self_await"] = ctxE["err"]

    async def F(i, c, e, a):
        fut = asyncio.ensure_future(i.send("PING", wait=True))
        async def later():
            try:
                await fut
                i.context["wait_ok"] = True
            except Exception as ex:
                i.context["wait_ok"] = type(ex).__name__
        asyncio.ensure_future(later())
    logF, ctxF = await run(F, kind)
    rows["F_handout_receipt"] = {"log": logF, "wait_ok": ctxF["wait_ok"]}

    print(json.dumps({"kind": kind, "rows": rows}, indent=1))

asyncio.run(main())
