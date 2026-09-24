"""#225 at scale: 200 machines whose actions spawn workers that OUTLIVE the
action and then send back.  Every such send must be EXTERNAL traffic -- no
event may sit in an internal queue waiting for a macrostep that never comes.

Also: 100 concurrent `ensure_future(send(wait=True))` hand-outs while the
spawning actions keep awaiting.
"""
import asyncio, json, os, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

NM = int(os.environ.get("NM", "200"))
ROUNDS = int(os.environ.get("ROUNDS", "5"))

CFG = {"id": "w", "initial": "a", "context": {"acks": 0, "kicks": 0},
       "states": {"a": {"on": {"KICK": {"actions": ["kick"]},
                               "ACK": {"actions": ["ack"]}}}}}

def build(kind):
    async def kick(i, c, e, a):
        c["kicks"] += 1
        async def worker():
            await asyncio.sleep(0.01)      # outlives the action
            i.send("ACK")
        asyncio.ensure_future(worker())
        if kind == "async":
            await asyncio.sleep(0.001)     # the action keeps awaiting after
    def ack(i, c, e, a):
        c["acks"] += 1
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"kick": kick,
                                                      "ack": ack}))

async def part_a(kind):
    ms = [Interpreter(build(kind)) for _ in range(NM)]
    await asyncio.gather(*(m.start() for m in ms))
    for _ in range(ROUNDS):
        for m in ms:
            m.send("KICK")
        await asyncio.sleep(0.05)
    # give workers generous time; the loop is then IDLE -- an internally
    # queued ACK would never be drained.
    await asyncio.sleep(1.0)
    acks = sum(m.context["acks"] for m in ms)
    kicks = sum(m.context["kicks"] for m in ms)
    await asyncio.gather(*(m.stop() for m in ms))
    return {"machines": NM, "kicks": kicks, "acks": acks,
            "expected": NM * ROUNDS, "starved": NM * ROUNDS - acks}

async def part_b(kind):
    """100 concurrent hand-outs while actions keep awaiting."""
    results = []
    i = Interpreter(build(kind))
    await i.start()
    futs = [asyncio.ensure_future(i.send("KICK", wait=True))
            for _ in range(100)]
    done, pending = await asyncio.wait(futs, timeout=8)
    for f in done:
        try:
            f.result()
            results.append("ok")
        except Exception as ex:                 # noqa: BLE001
            results.append(type(ex).__name__)
    await asyncio.sleep(0.5)
    acks = i.context["acks"]
    await i.stop()
    from collections import Counter
    return {"resolved": len(done), "pending": len(pending),
            "outcomes": dict(Counter(results)), "acks_back": acks}

async def main():
    kind = os.environ.get("XS_SVC", "async")
    t = time.perf_counter()
    a = await part_a(kind)
    b = await part_b(kind)
    fails = []
    if a["starved"] != 0:
        fails.append(f"{a['starved']} ACKs never delivered (internal-queue "
                     f"starvation)")
    if b["pending"] or b["outcomes"].get("ok", 0) != 100:
        fails.append(f"hand-outs {b}")
    print(json.dumps({"kind": kind, "wall_s": round(time.perf_counter() - t, 1),
                      "part_a": a, "part_b": b, "fails": fails,
                      "VERDICT": "PASS" if not fails else "FAIL"}, indent=1))

asyncio.run(main())
