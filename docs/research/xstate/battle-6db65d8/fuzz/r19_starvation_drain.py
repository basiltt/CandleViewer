"""R19 -- is D8-fuzz-3's starvation TRANSIENT (a backlog that drains once the
producer stops) or PERMANENT (a live-lock the queued events never escape)?

r18 left `priority=427, inbox=499` after the producer stopped and a 1 s wait.
This script stops sending and then watches the queues and the applied
watermark for 10 s, sampling every 0.5 s.  It also reports CPU, because a
livelock and a slow drain look the same in the queue depth alone.
"""
import asyncio, logging, os, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import psutil
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": 50,
    "context": {"ext": 0},
    "on": {"EXT": {"actions": ["extbump"]}},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "always": {"target": "b2"},
            "initial": "b2",
            "states": {
                "b2": {
                    "invoke": {"id": "s", "src": "svc", "onDone": {"target": "#m.a"}}
                }
            },
        },
    },
}


async def a_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def p_svc(i, c, e):
    return {"ok": 1}


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


async def run(async_svc, n=500, watch=10.0):
    p = psutil.Process()
    it = Interpreter(
        create_machine(
            dict(CFG),
            logic=MachineLogic(
                services={"svc": a_svc if async_svc else p_svc},
                actions={"extbump": extbump},
            ),
        )
    )
    await asyncio.wait_for(it.start(), 10)
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        await asyncio.sleep(0)
    kind = "async def" if async_svc else "plain def"
    print(f"== {kind}: producer STOPPED after {n} GO + {n} EXT; watching drain ==")
    c0 = p.cpu_times().user
    t0 = time.time()
    last = None
    while time.time() - t0 < watch:
        await asyncio.sleep(0.5)
        ext = (it.context or {}).get("ext", 0)
        row = (
            round(time.time() - t0, 1),
            ext,
            it._event_queue.qsize(),
            len(it._priority_queue),
            it.status,
            type(it.last_error).__name__ if it.last_error else None,
        )
        if row[1:] != (last[1:] if last else None):
            print(
                f"   t={row[0]:>4}s applied={row[1]:<5} inbox={row[2]:<5} "
                f"priority={row[3]:<5} status={row[4]} err={row[5]}"
            )
        last = row
    cpu = p.cpu_times().user - c0
    ext = (it.context or {}).get("ext", 0)
    drained = it._event_queue.qsize() == 0 and len(it._priority_queue) == 0
    print(
        f"   after {watch}s idle: applied={ext}/{n} inbox={it._event_queue.qsize()} "
        f"priority={len(it._priority_queue)} cpu={cpu:.1f}s "
        f"({100*cpu/watch:.0f}% of one core) "
        f"=> {'DRAINED' if drained else 'STUCK (permanent starvation)'}"
    )
    await it.stop()


async def main():
    for a in (False, True):
        await run(a)


asyncio.run(main())
