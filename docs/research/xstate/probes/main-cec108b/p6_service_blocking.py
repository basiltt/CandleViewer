"""K-7: #149 claims the loop keeps turning during a plain service. But the
entering MACROSTEP awaits the result. Do inbound events / after timers of
THIS machine actually get processed, or only unrelated asyncio tasks?
Also: pool saturation (max_workers=4) serialises region entry.
"""
import asyncio
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine


async def probe_inbound_during_service():
    log = []

    def slow(i, c, e):
        time.sleep(0.5)
        return 1

    def note(i, c, e, a):
        log.append((e.type, round(time.monotonic() - T0, 3)))

    cfg = {
        "id": "x",
        "type": "parallel",
        "states": {
            "work": {
                "initial": "s",
                "states": {
                    "s": {"invoke": {"src": "slow", "onDone": "d"}},
                    "d": {"type": "final"},
                },
            },
            "ui": {
                "initial": "idle",
                "states": {
                    "idle": {
                        "on": {"PING": {"actions": ["note"]}},
                        "after": {"100": {"actions": ["note"]}},
                    }
                },
            },
        },
    }
    m = create_machine(
        cfg, logic=MachineLogic(services={"slow": slow}, actions={"note": note})
    )
    i = Interpreter(m)
    global T0
    T0 = time.monotonic()
    await i.start()
    await asyncio.sleep(0.05)
    await i.send("PING")
    await asyncio.sleep(0.9)
    print(f"[A] events handled during a 0.5s plain service: {log}")
    print("    (PING at ~0.05 and after@100ms => processed live; "
          "both >0.5 => macrostep still blocks the MACHINE)")
    await i.stop()


async def probe_pool_saturation_latency():
    """9 plain services, pool of 4, each 0.2s: when does the LAST finish?"""
    def slow(i, c, e):
        time.sleep(0.2)
        return 1

    n = 9
    cfg = {
        "id": "sat",
        "type": "parallel",
        "states": {
            f"r{k}": {
                "initial": "s",
                "states": {
                    "s": {"invoke": {"src": "slow", "onDone": "d"}},
                    "d": {"type": "final"},
                },
            }
            for k in range(n)
        },
    }
    m = create_machine(cfg, logic=MachineLogic(services={"slow": slow}))
    i = Interpreter(m)
    t0 = time.monotonic()
    await i.start()
    while i.status == "running" and time.monotonic() - t0 < 5:
        await asyncio.sleep(0.01)
    dt = time.monotonic() - t0
    print(f"[B] {n} x 0.2s plain services, pool=4: all done in {dt:.2f}s "
          f"(ideal concurrent=0.2s, serialised={n*0.2:.1f}s) status={i.status}")
    await i.stop()


async def main():
    await probe_inbound_during_service()
    await probe_pool_saturation_latency()


if __name__ == "__main__":
    asyncio.run(main())
