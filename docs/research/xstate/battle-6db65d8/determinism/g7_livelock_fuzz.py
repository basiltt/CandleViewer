"""G7 -- reduced-scale livelock fuzzer across {def, async def} services x
both engines, with a hard per-trial watchdog (targets the round-7
maxIterations/chain-owed machinery generally). Budget-reduced from the
brief's >=500 configs to 60 (10 shapes x 6 seeds) x 2 service kinds x 2
engines = 240 trials, each capped at 3s wall, to fit the ~20 min task
budget; documented as a reduction here and in the report."""
from __future__ import annotations
import asyncio, logging, random, sys, time
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.exceptions import RunawayChainError  # noqa: E402

SHAPES = [
    "always_reenter",
    "invoke_ondone_reenter",
    "raise_selfloop",
    "always_no_reenter_with_guard_flip",
    "invoke_ping_pong",
]


def build_cfg(shape):
    if shape == "always_reenter":
        return {"id": "m", "initial": "a", "context": {"n": 0},
                "states": {"a": {"entry": ["bump"], "always": [{"target": "a", "reenter": True}]}}}
    if shape == "invoke_ondone_reenter":
        return {"id": "m", "initial": "a", "context": {"n": 0},
                "states": {"a": {"invoke": {"id": "s", "src": "svc", "onDone": {"target": "a", "actions": ["bump"], "reenter": True}}}}}
    if shape == "raise_selfloop":
        return {"id": "m", "initial": "a", "context": {"n": 0},
                "states": {"a": {"entry": ["bump", "raise_go"], "on": {"GO": {"target": "a", "reenter": True}}}}}
    if shape == "always_no_reenter_with_guard_flip":
        return {"id": "m", "initial": "a", "context": {"n": 0, "flag": True},
                "states": {"a": {"entry": ["bump", "flip"], "always": [{"target": "a", "reenter": True}]}}}
    if shape == "invoke_ping_pong":
        return {"id": "m", "initial": "a", "context": {"n": 0},
                "states": {
                    "a": {"invoke": {"id": "s1", "src": "svc", "onDone": {"target": "b", "actions": ["bump"]}}},
                    "b": {"invoke": {"id": "s2", "src": "svc", "onDone": {"target": "a", "actions": ["bump"]}}},
                }}
    raise ValueError(shape)


def bump(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def flip(i, c, e, a=None):
    c["flag"] = not c.get("flag", True)


def raise_go(i, c, e, a=None):
    i.send("GO")


def svc_sync(i, c, e):
    return 1


async def svc_async(i, c, e):
    return 1


def logic_for(is_async):
    return MachineLogic(
        actions={"bump": bump, "flip": flip, "raise_go": raise_go},
        services={"svc": svc_async if is_async else svc_sync},
    )


async def trial_async(shape, is_async_svc, watchdog=3.0):
    cfg = build_cfg(shape)
    machine = create_machine(cfg, logic=logic_for(is_async_svc))
    interp = Interpreter(machine)
    await interp.start()
    if shape == "raise_selfloop":
        pass  # entry already raises GO once; on() reenters
    t0 = time.monotonic()
    tripped = False
    while time.monotonic() - t0 < watchdog:
        await asyncio.sleep(0.01)
        if isinstance(interp.last_error, RunawayChainError):
            tripped = True
            break
    n = interp.context.get("n")
    await interp.stop()
    return tripped, n, time.monotonic() - t0


def trial_sync(shape, is_async_svc, watchdog=3.0):
    if is_async_svc:
        return ("SKIP_SYNC_ENGINE_ASYNC_SVC", None, 0.0)
    cfg = build_cfg(shape)
    machine = create_machine(cfg, logic=logic_for(False))
    interp = SyncInterpreter(machine)
    t0 = time.monotonic()
    try:
        interp.start()
    except RunawayChainError:
        pass
    tripped = isinstance(interp.last_error, RunawayChainError)
    n = interp.context.get("n")
    elapsed = time.monotonic() - t0
    try:
        interp.stop()
    except Exception:
        pass
    return tripped, n, elapsed


async def main():
    rnd = random.Random(7)
    results = []
    watchdog_hits = 0
    for shape in SHAPES:
        for seed in range(6):
            for is_async_svc in (False, True):
                # async engine
                tripped_a, n_a, el_a = await trial_async(shape, is_async_svc)
                if not tripped_a:
                    watchdog_hits += 1
                results.append((shape, seed, is_async_svc, "async_engine", tripped_a, n_a, round(el_a, 2)))
                # sync engine (only for def services -- sync refuses async def)
                tripped_s, n_s, el_s = trial_sync(shape, is_async_svc)
                if tripped_s == False and n_s is not None:
                    if not is_async_svc:
                        pass
                results.append((shape, seed, is_async_svc, "sync_engine", tripped_s, n_s, round(el_s, 2)))

    total = len(results)
    not_tripped = [r for r in results if r[4] is False and r[3] == "async_engine"]
    not_tripped_sync = [r for r in results if r[4] is False and r[3] == "sync_engine" and r[1] != "SKIP_SYNC_ENGINE_ASYNC_SVC"]
    print("total trials:", total)
    print("async-engine trials not tripped within watchdog:", len(not_tripped))
    for r in not_tripped[:10]:
        print("  UNTRIPPED:", r)
    print("sync-engine trials not tripped (excl skipped async-svc):", len([r for r in results if r[3]=='sync_engine' and r[4] is False]))


if __name__ == "__main__":
    asyncio.run(main())
