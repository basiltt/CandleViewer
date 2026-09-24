"""m10 — remaining briefed attacks for the FUZZ track on cec108b.

C1  determinism: 50x identical traces on both engines, incl. an executor
    (plain-def) service — ordering vs #116.
C2  hash-seed sweep: PYTHONHASHSEED variation must not change a trace.
C3  concurrency: 200 concurrent plain-def services via service_executor,
    plus stop() mid-service; leaked threads after the cycle.
C4  send_threadsafe under OverflowPolicy.RAISE at the call site, 16 threads.
C5  thread/task leak after 500 start/stop cycles.
C6  exported API surface diff vs the prior round's __all__.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, subprocess, sys, threading, time
logging.disable(logging.CRITICAL)
import xstate_statemachine as X
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
    QueueOverflowError, XStateMachineError,
)

RESULTS = []


def rec(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{name:30s} {'PASS' if ok else 'FAIL'}  {detail}", flush=True)


TRACE_CFG = {
    "id": "m", "initial": "a", "context": {"log": []},
    "states": {
        "a": {"entry": ["mark"],
              "invoke": {"id": "i", "src": "plain",
                         "onDone": {"target": "b", "actions": ["mark"]}}},
        "b": {"entry": ["mark"], "on": {"GO": "c"}},
        "c": {"entry": ["mark"], "type": "final"},
    },
}


def trace_logic():
    def mark(i, c, e, a):
        c["log"].append(getattr(e, "type", str(e)))

    def plain(i, c, e):          # plain def -> service_executor path
        return {"v": 1}

    return MachineLogic(actions={"mark": mark}, guards={},
                        services={"plain": plain})


def one_sync():
    it = SyncInterpreter(create_machine(copy.deepcopy(TRACE_CFG),
                                        logic=trace_logic()))
    it.start()
    it.send("GO")
    return tuple(it.context["log"]) + tuple(sorted(it.current_state_ids))


async def one_async():
    it = Interpreter(create_machine(copy.deepcopy(TRACE_CFG),
                                    logic=trace_logic()))
    await asyncio.wait_for(it.start(), timeout=8)
    await asyncio.wait_for(it.send("GO", wait=True), timeout=8)
    out = tuple(it.context["log"]) + tuple(sorted(it.current_state_ids))
    try:
        await asyncio.wait_for(it.stop(), timeout=5)
    except Exception:
        pass
    return out


def c1_determinism(n=50):
    s = {one_sync() for _ in range(n)}
    a = {asyncio.run(one_async()) for _ in range(n)}
    ok = len(s) == 1 and len(a) == 1
    rec("C1.determinism_50x", ok,
        f"distinct sync={len(s)} async={len(a)} cross_equal={s == a} "
        f"sync={list(s)[0] if len(s)==1 else '?'} "
        f"async={list(a)[0] if len(a)==1 else '?'}")


def c2_hashseed_sweep():
    here = os.path.dirname(os.path.abspath(__file__))
    code = ("import sys;sys.path.insert(0,r'%s');"
            "import m10_remaining as M;print(M.one_sync())" % here)
    outs = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed,
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, env=env, timeout=60)
        outs.add(r.stdout.strip() or f"ERR:{r.stderr.strip()[-120:]}")
    rec("C2.hashseed_sweep", len(outs) == 1,
        f"distinct={len(outs)} {list(outs)[0][:90]}")


EXEC_CFG = {
    "id": "m", "initial": "a",
    "states": {"a": {"invoke": {"id": "i", "src": "slow",
                                "onDone": "b"}}, "b": {"type": "final"}},
}


def c3_executor_concurrency(n=200):
    started = threading.Semaphore(0)

    def slow(i, c, e):
        started.release()
        time.sleep(0.05)
        return {"ok": 1}

    lg = lambda: MachineLogic(actions={}, guards={}, services={"slow": slow})

    async def run():
        its = [Interpreter(create_machine(copy.deepcopy(EXEC_CFG), logic=lg()))
               for _ in range(n)]
        t0 = time.time()
        await asyncio.gather(*(asyncio.wait_for(i.start(), timeout=30)
                               for i in its))
        # loop must keep turning while services run
        loop_alive = 0
        for _ in range(20):
            await asyncio.sleep(0.005)
            loop_alive += 1
        await asyncio.sleep(1.0)
        done = sum(1 for i in its if sorted(i.current_state_ids) == ["m.b"])
        # stop() mid-service on a fresh batch
        mids = [Interpreter(create_machine(copy.deepcopy(EXEC_CFG), logic=lg()))
                for _ in range(20)]
        await asyncio.gather(*(asyncio.wait_for(i.start(), timeout=30)
                               for i in mids))
        stop_err = ""
        try:
            await asyncio.gather(*(asyncio.wait_for(i.stop(), timeout=10)
                                   for i in mids))
        except Exception as exc:
            stop_err = f"stop:{type(exc).__name__}"
        for i in its:
            try:
                await asyncio.wait_for(i.stop(), timeout=10)
            except Exception:
                pass
        return done, time.time() - t0, loop_alive, stop_err

    before = threading.active_count()
    done, dt, loop_alive, stop_err = asyncio.run(run())
    time.sleep(1.0)
    after = threading.active_count()
    ok = done == n and not stop_err and loop_alive == 20
    rec("C3.executor_200_concurrent", ok,
        f"completed={done}/{n} wall={dt:.1f}s loop_ticks={loop_alive} "
        f"{stop_err} threads {before}->{after}")


def c4_threadsafe_raise(threads=16, each=60):
    from xstate_statemachine import OverflowPolicy
    cfg = {"id": "m", "initial": "a", "context": {"n": 0},
           "states": {"a": {"on": {"BUMP": {"actions": ["bump"]}}}}}

    def bump(i, c, e, a):
        c["n"] += 1
        time.sleep(0.0005)

    async def run():
        it = Interpreter(
            create_machine(copy.deepcopy(cfg),
                           logic=MachineLogic(actions={"bump": bump},
                                              guards={}, services={})),
            max_queue_size=4, overflow_policy=OverflowPolicy.RAISE)
        await asyncio.wait_for(it.start(), timeout=10)
        raised = {"QueueOverflowError": 0}
        untyped = {}

        def worker():
            for _ in range(each):
                try:
                    it.send_threadsafe("BUMP", internal=True)
                except QueueOverflowError:
                    raised["QueueOverflowError"] += 1
                except XStateMachineError as exc:
                    raised[type(exc).__name__] = \
                        raised.get(type(exc).__name__, 0) + 1
                except Exception as exc:
                    untyped[type(exc).__name__] = \
                        untyped.get(type(exc).__name__, 0) + 1

        ts = [threading.Thread(target=worker) for _ in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        await asyncio.sleep(1.0)
        alive = sum(t.is_alive() for t in ts)
        try:
            await asyncio.wait_for(it.stop(), timeout=10)
        except Exception:
            pass
        return raised, untyped, alive, it.context["n"]

    raised, untyped, alive, n = asyncio.run(run())
    ok = not untyped and alive == 0
    rec("C4.threadsafe_raise_16t", ok,
        f"applied={n}/{threads*each} raised={raised} untyped={untyped} "
        f"hung_threads={alive}")


def c5_cycle_leak(cycles=500):
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}},
                                                 "b": {}}}

    async def run():
        for _ in range(cycles):
            it = Interpreter(create_machine(copy.deepcopy(cfg),
                                            logic=MachineLogic({}, {}, {})))
            await asyncio.wait_for(it.start(), timeout=8)
            await asyncio.wait_for(it.send("GO", wait=True), timeout=8)
            await asyncio.wait_for(it.stop(), timeout=8)
        return len(asyncio.all_tasks())

    before = threading.active_count()
    leftover = asyncio.run(run())
    time.sleep(0.5)
    after = threading.active_count()
    ok = after - before <= 2
    rec("C5.leak_500_cycles", ok,
        f"threads {before}->{after} tasks_at_end={leftover}")


def c6_api_surface():
    names = sorted(getattr(X, "__all__", []))
    missing = [n for n in names if not hasattr(X, n)]
    expected = {"InvalidEventError", "RootTargetError", "SnapshotCorruptError",
                "SnapshotMidStepError", "SnapshotSerializationError",
                "QueueOverflowError", "RunawayChainError"}
    absent = sorted(expected - set(names))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "out", "api_surface.json")
    json.dump(names, open(path, "w", encoding="utf-8"), indent=1)
    rec("C6.api_surface", not missing and not absent,
        f"__all__={len(names)} dangling={missing} missing_expected={absent}")


def main():
    c1_determinism()
    c2_hashseed_sweep()
    c3_executor_concurrency()
    c4_threadsafe_raise()
    c5_cycle_leak()
    c6_api_surface()
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n==== {len(RESULTS)-len(bad)}/{len(RESULTS)} PASS ====")


if __name__ == "__main__":
    main()
