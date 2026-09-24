"""New round-11 attacks: (A) timer-handle count stays flat across a
200-beat raise(delay=) heartbeat on both engines (#218). (B)
ReentrantWaitError matrix: self / after-fired-handler send(wait=True)
raises, both engines (#219). (C) chain-trip latch survives a benign
event after the trip (#222): last_chain_error stays set, chain_trips
monotonic, clear_chain_error() clears it.
Standalone: stdlib + xstate_statemachine only. Run from C:/Users/basil.
"""
import asyncio
import sys

sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")

from xstate_statemachine import create_machine, Interpreter, SyncInterpreter, MachineLogic
from xstate_statemachine.exceptions import ReentrantWaitError

HEARTBEAT_CFG = {
    "id": "hb",
    "initial": "beating",
    "states": {
        "beating": {
            "entry": [{"type": "raise", "params": {"event": "TICK", "delay": 1}}],
            "on": {"TICK": {"actions": [{"type": "raise", "params": {"event": "TICK", "delay": 1}}]}},
        }
    },
}


def count_handles(interp):
    ss = getattr(interp, "_scheduled_sends", None)
    if ss is None:
        return None
    return len(ss)


async def a_async():
    m = create_machine(HEARTBEAT_CFG)
    i = Interpreter(m)
    await i.start()
    for _ in range(200):
        before = count_handles(i)
        await asyncio.sleep(0.002)
    after = count_handles(i)
    await i.stop()
    return {"handles_after_200_beats": after}


def a_sync():
    m = create_machine(HEARTBEAT_CFG)
    i = SyncInterpreter(m)
    i.start()
    import time
    t0 = time.time()
    while time.time() - t0 < 0.4:
        i._clock.advance(1) if hasattr(i, "_clock") else None
    after = count_handles(i)
    i.stop()
    return {"handles_sync": after}


SELF_CFG = {
    "id": "dead",
    "initial": "x",
    "states": {"x": {"entry": ["reentrant_wait"], "on": {"GO": "y"}}, "y": {}},
}


async def reentrant_action(interp, ctx, ev, action_def):
    try:
        await interp.send({"type": "GO"}, wait=True)
        return "NO_ERROR"
    except ReentrantWaitError:
        raise


def sync_reentrant_action(interp, ctx, ev, action_def):
    try:
        interp.send({"type": "GO"}, wait=True)
    except ReentrantWaitError:
        raise


async def b_async_self():
    seen = []

    async def act(i, c, e, ad):
        try:
            await i.send({"type": "GO"}, wait=True)
        except ReentrantWaitError as exc:
            seen.append(str(exc))
            raise

    m = create_machine(SELF_CFG, logic=MachineLogic(actions={"reentrant_wait": act}))
    i = Interpreter(m)
    try:
        await asyncio.wait_for(i.start(), 5)
    except ReentrantWaitError:
        pass
    await asyncio.sleep(0.05)
    status, value = i.status, i.value
    if status == "running":
        await i.stop()
    return {"seen": seen, "status": status, "value": value}


def b_sync_self():
    seen = []

    def act(i, c, e, ad):
        try:
            i.send({"type": "GO"}, wait=True)
        except ReentrantWaitError as exc:
            seen.append(str(exc))

    m = create_machine(SELF_CFG, logic=MachineLogic(actions={"reentrant_wait": act}))
    i = SyncInterpreter(m)
    i.start()
    value_before = i.value
    i.send({"type": "GO"})
    value_after = i.value
    i.stop()
    return {"seen": seen, "value_before": value_before, "value_after": value_after}


CHAIN_CFG = {
    "id": "chain",
    "context": {"n": 0},
    "maxIterations": 50,
    "initial": "s",
    "states": {
        "s": {
            "on": {
                "PING": {"actions": ["bump", "reping"]},
                "BENIGN": {"actions": ["noop"]},
            }
        }
    },
}


def bump(interp, ctx, ev, ad):
    ctx["n"] = ctx.get("n", 0) + 1


def reping(interp, ctx, ev, ad):
    interp.send({"type": "PING"})


def noop(interp, ctx, ev, ad):
    pass


async def c_async_latch():
    m = create_machine(CHAIN_CFG, logic=MachineLogic(actions={"bump": bump, "reping": reping, "noop": noop}))
    i = Interpreter(m)
    await i.start()
    try:
        await asyncio.wait_for(i.send({"type": "PING"}, wait=True), timeout=5.0)
    except Exception:
        pass
    trips_after_trip = getattr(i, "chain_trips", None)
    latch_after_trip = getattr(i, "last_chain_error", None)
    await i.send({"type": "BENIGN"})
    trips_after_benign = getattr(i, "chain_trips", None)
    latch_after_benign = getattr(i, "last_chain_error", None)
    cleared = None
    if hasattr(i, "clear_chain_error"):
        i.clear_chain_error()
        cleared = getattr(i, "last_chain_error", "NO_ATTR")
    await i.stop()
    return {
        "trips_after_trip": trips_after_trip,
        "latch_set_after_trip": latch_after_trip is not None,
        "trips_after_benign": trips_after_benign,
        "latch_still_set_after_benign": latch_after_benign is not None,
        "latch_after_clear": cleared,
    }


async def main():
    print("=== A: timer handle count, 200-beat raise(delay=) heartbeat ===")
    print(await a_async())

    print()
    print("=== B: ReentrantWaitError matrix (self wait=True) ===")
    print("async:", await b_async_self())
    print("sync: ", b_sync_self())

    print()
    print("=== C: chain-trip latch across a benign event ===")
    print(await c_async_latch())


if __name__ == "__main__":
    asyncio.run(main())
