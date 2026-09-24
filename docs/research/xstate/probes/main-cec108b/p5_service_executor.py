"""K-6 probes: service_executor (#149).

1. Default pool is max_workers=4 -> a 5th concurrent plain service is queued
   behind a free worker, and because the macrostep AWAITS it, entering the
   5th invoking state stalls that macrostep for the duration of a slow peer.
2. stop() shuts the pool down with wait=False -> the thread keeps running;
   does anything observe the result / leak?
3. A plain service raising inside the thread -> ErrorEvent/onError?
4. Executor already shut down (restart after stop) -> RuntimeError path.
"""
import asyncio
import threading
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine


def machine(n):
    states = {}
    for k in range(n):
        states[f"s{k}"] = {
            "invoke": {
                "src": "slow",
                "onDone": {"target": f"d{k}"},
                "onError": {"target": f"e{k}"},
            }
        }
        states[f"d{k}"] = {"type": "final"}
        states[f"e{k}"] = {"type": "final"}
    return {
        "id": "pool",
        "type": "parallel",
        "states": {f"r{k}": {"initial": f"s{k}", "states": {
            f"s{k}": states[f"s{k}"],
            f"d{k}": states[f"d{k}"],
            f"e{k}": states[f"e{k}"],
        }} for k in range(n)},
    }


async def probe_pool_size():
    live = []
    peak = {"n": 0}
    lock = threading.Lock()

    def slow(i, c, e):
        with lock:
            live.append(1)
            peak["n"] = max(peak["n"], len(live))
        time.sleep(0.30)
        with lock:
            live.pop()
        return {"ok": True}

    m = create_machine(machine(8), logic=MachineLogic(services={"slow": slow}))
    i = Interpreter(m)
    t0 = time.monotonic()
    await i.start()
    await asyncio.sleep(1.4)
    dt = time.monotonic() - t0
    print(f"[1] 8 concurrent plain services: peak_parallel={peak['n']} "
          f"elapsed={dt:.2f}s status={i.status} ids={sorted(i.current_state_ids)}")
    ex = i._service_executor
    print(f"    executor={type(ex).__name__ if ex else None} "
          f"max_workers={getattr(ex, '_max_workers', None)}")
    await i.stop()


async def probe_loop_alive_during_service():
    ticks = {"n": 0}

    def slow(i, c, e):
        time.sleep(0.5)
        return 1

    cfg = {
        "id": "lp",
        "initial": "s",
        "states": {
            "s": {"invoke": {"src": "slow", "onDone": "d"}},
            "d": {"type": "final"},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(services={"slow": slow}))
    i = Interpreter(m)
    await i.start()

    async def ticker():
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    tk = asyncio.create_task(ticker())
    await asyncio.sleep(0.6)
    tk.cancel()
    print(f"[2] loop turns during a 0.5s plain service: {ticks['n']} "
          f"(loop blocked if ~0) status={i.status}")
    await i.stop()


async def probe_stop_during_service():
    done = threading.Event()

    def slow(i, c, e):
        time.sleep(0.6)
        done.set()
        return 1

    cfg = {
        "id": "sd",
        "initial": "s",
        "states": {"s": {"invoke": {"src": "slow", "onDone": "d"}},
                   "d": {"type": "final"}},
    }
    m = create_machine(cfg, logic=MachineLogic(services={"slow": slow}))
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.1)
    t0 = time.monotonic()
    await i.stop()
    dt = time.monotonic() - t0
    print(f"[3] stop() while a 0.6s plain service runs: blocked {dt:.2f}s "
          f"(service finished already: {done.is_set()})")
    alive = [t.name for t in threading.enumerate() if "xsm-svc" in t.name]
    print(f"    xsm-svc threads still alive after stop(): {alive}")
    await asyncio.sleep(0.8)
    alive2 = [t.name for t in threading.enumerate() if "xsm-svc" in t.name]
    print(f"    after service would have finished: {alive2} "
          f"service_ran_to_completion={done.is_set()}")


async def probe_service_raises():
    seen = []

    def bad(i, c, e):
        raise RuntimeError("thread boom")

    cfg = {
        "id": "br",
        "initial": "s",
        "states": {
            "s": {"invoke": {"src": "bad", "onError": {"target": "e",
                                                        "actions": ["rec"]}}},
            "e": {"type": "final"},
        },
    }

    def rec(i, c, e, a):
        seen.append((e.type, type(getattr(e, "error", None)).__name__))

    m = create_machine(cfg, logic=MachineLogic(services={"bad": bad},
                                               actions={"rec": rec}))
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.3)
    print(f"[4] plain service raising in thread -> onError: {seen} "
          f"ids={sorted(i.current_state_ids)}")
    await i.stop()


async def main():
    await probe_pool_size()
    await probe_loop_alive_during_service()
    await probe_stop_during_service()
    await probe_service_raises()


if __name__ == "__main__":
    asyncio.run(main())
