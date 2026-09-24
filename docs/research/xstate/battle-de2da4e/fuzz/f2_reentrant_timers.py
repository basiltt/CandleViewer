"""F2 -- #219 ReentrantWaitError matrix + #218 timer-handle release.

A: ReentrantWaitError matrix, both kinds, both engines where applicable:
     A1 action awaits i.send(..., wait=True) on its OWN interpreter
     A2 same, but the receipt is handed to asyncio.ensure_future and
        awaited AFTER the action returned (must SUCCEED -- #219 says the
        receipt may still be handed out)
     A3 an after-fired handler action doing the same (A1 shape on a clock
        event)
     A4 child -> parent wait=True send (different interpreter: must WORK)
     A5 parent -> child wait=True send from inside a parent action
     A6 sync engine: action calling i.send(..., wait=True) on itself
     A7 100 concurrent actions using the ensure_future pattern
B: #218 timer-handle release -- a 200-beat raise(delay=) heartbeat, both
   engines, both kinds: max len of any interpreter._timer_handles list.
C: cancel storm -- arm+cancel a delayed send 500x: handles + armed sets flat,
   no double-release crash, 0 fires.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import ReentrantWaitError  # noqa: E402

DEFECTS = []
OBS = []


def cfg(mid, extra_states=None):
    c = {
        "id": mid,
        "initial": "a",
        "context": {},
        "states": {
            "a": {"entry": ["probe"], "on": {"PING": {"target": "b"}}},
            "b": {"on": {"PING": {"target": "a"}}},
        },
    }
    if extra_states:
        c["states"].update(extra_states)
    return c


def handle_counts(it):
    th = getattr(it, "_timer_handles", {}) or {}
    return {k: len(v) for k, v in th.items()}


# ------------------------------------------------------------------ part A
async def a1(kind):
    """action awaits wait=True on its own interpreter -> ReentrantWaitError"""
    box = {}

    async def probe_async(i, c, e, a=None):
        try:
            await i.send("PING", wait=True)
            box["r"] = "NO-RAISE (completed)"
        except ReentrantWaitError:
            box["r"] = "ReentrantWaitError"
        except Exception as ex:  # noqa: BLE001
            box["r"] = f"other:{type(ex).__name__}"

    def probe_sync_def(i, c, e, a=None):
        # a `def` action cannot await; the send() coroutine is created and
        # never awaited -> record what the API does with it
        try:
            r = i.send("PING", wait=True)
            box["r"] = f"def-returned:{type(r).__name__}"
            if asyncio.iscoroutine(r):
                r.close()
        except ReentrantWaitError:
            box["r"] = "ReentrantWaitError"
        except Exception as ex:  # noqa: BLE001
            box["r"] = f"other:{type(ex).__name__}"

    lg = MachineLogic(
        actions={"probe": probe_async if kind == "async def"
                 else probe_sync_def}
    )
    m = create_machine(cfg("a1"), logic=lg)
    it = Interpreter(m)
    try:
        await asyncio.wait_for(it.start(), 8)
    except asyncio.TimeoutError:
        box["r"] = "HANG(start timed out)"
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:  # noqa: BLE001
        pass
    return box.get("r", "?")


async def a2(kind):
    """receipt handed to ensure_future inside the action, awaited later."""
    box = {}

    async def probe_async(i, c, e, a=None):
        box["fut"] = asyncio.ensure_future(i.send("PING", wait=True))

    def probe_def(i, c, e, a=None):
        box["fut"] = asyncio.ensure_future(i.send("PING", wait=True))

    lg = MachineLogic(
        actions={"probe": probe_async if kind == "async def" else probe_def}
    )
    m = create_machine(cfg("a2"), logic=lg)
    it = Interpreter(m)
    try:
        await asyncio.wait_for(it.start(), 8)
        r = await asyncio.wait_for(box["fut"], 8)
        box["r"] = f"OK receipt={type(r).__name__} states={it.current_state_ids}"
    except asyncio.TimeoutError:
        box["r"] = "HANG"
    except ReentrantWaitError:
        box["r"] = "ReentrantWaitError (refused even out-of-step)"
    except Exception as ex:  # noqa: BLE001
        box["r"] = f"other:{type(ex).__name__}:{ex}"
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:  # noqa: BLE001
        pass
    return box["r"]


async def a3(kind):
    """the A1 shape inside a handler fired by an `after` clock event."""
    box = {}

    async def probe_async(i, c, e, a=None):
        try:
            await i.send("PING", wait=True)
            box["r"] = "NO-RAISE"
        except ReentrantWaitError:
            box["r"] = "ReentrantWaitError"
        except Exception as ex:  # noqa: BLE001
            box["r"] = f"other:{type(ex).__name__}"

    def probe_def(i, c, e, a=None):
        try:
            r = i.send("PING", wait=True)
            box["r"] = f"def-returned:{type(r).__name__}"
            if asyncio.iscoroutine(r):
                r.close()
        except ReentrantWaitError:
            box["r"] = "ReentrantWaitError"
        except Exception as ex:  # noqa: BLE001
            box["r"] = f"other:{type(ex).__name__}"

    c = {
        "id": "a3",
        "initial": "w",
        "context": {},
        "states": {
            "w": {"after": {"10": {"target": "f", "actions": ["probe"]}}},
            "f": {"on": {"PING": {"target": "w"}}},
        },
    }
    lg = MachineLogic(
        actions={"probe": probe_async if kind == "async def" else probe_def}
    )
    it = Interpreter(create_machine(c, logic=lg))
    await it.start()
    for _ in range(60):
        if "r" in box:
            break
        await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:  # noqa: BLE001
        pass
    return box.get("r", "HANG(handler never returned)")


async def a45(kind, direction):
    """cross-interpreter wait=True from inside an action (must WORK)."""
    box = {}
    peer = {}

    async def probe_async(i, c, e, a=None):
        try:
            await asyncio.wait_for(peer["other"].send("PING", wait=True), 5)
            box["r"] = f"OK peer={peer['other'].current_state_ids}"
        except asyncio.TimeoutError:
            box["r"] = "HANG(cross-interpreter wait deadlocked)"
        except ReentrantWaitError:
            box["r"] = "ReentrantWaitError (wrongly refused: other machine)"
        except Exception as ex:  # noqa: BLE001
            box["r"] = f"other:{type(ex).__name__}"

    def probe_def(i, c, e, a=None):
        box["fut"] = asyncio.ensure_future(peer["other"].send("PING",
                                                              wait=True))

    lg_probe = MachineLogic(
        actions={"probe": probe_async if kind == "async def" else probe_def}
    )
    other = Interpreter(create_machine(cfg("peer"), logic=MachineLogic(
        actions={"probe": lambda i, c, e, a=None: None})))
    await other.start()
    peer["other"] = other
    it = Interpreter(create_machine(cfg("driver"), logic=lg_probe))
    try:
        await asyncio.wait_for(it.start(), 8)
        if "fut" in box:
            r = await asyncio.wait_for(box["fut"], 5)
            box["r"] = f"OK(def/ensure_future) {type(r).__name__}"
    except asyncio.TimeoutError:
        box["r"] = "HANG"
    except Exception as ex:  # noqa: BLE001
        box["r"] = f"other:{type(ex).__name__}"
    for x in (it, other):
        try:
            await asyncio.wait_for(x.stop(), 5)
        except Exception:  # noqa: BLE001
            pass
    return box.get("r", "?")


def a6(kind):
    """sync engine: action calls send(wait=True) on itself."""
    box = {}

    def probe(i, c, e, a=None):
        try:
            i.send("PING", wait=True)
            box["r"] = "NO-RAISE"
        except ReentrantWaitError:
            box["r"] = "ReentrantWaitError"
        except Exception as ex:  # noqa: BLE001
            box["r"] = f"other:{type(ex).__name__}"

    lg = MachineLogic(actions={"probe": probe})
    it = SyncInterpreter(create_machine(cfg("a6sync"), logic=lg))
    try:
        it.start()
    except ReentrantWaitError:
        box.setdefault("r", "ReentrantWaitError(propagated from start)")
    except Exception as ex:  # noqa: BLE001
        box.setdefault("r", f"start-raised:{type(ex).__name__}")
    try:
        it.stop()
    except Exception:  # noqa: BLE001
        pass
    return box.get("r", "?")


async def a7(kind, n=100):
    """100 concurrent interpreters, each action using ensure_future."""
    results = []

    async def one(idx):
        return await a2(kind)

    out = await asyncio.gather(*[one(i) for i in range(n)],
                               return_exceptions=True)
    for o in out:
        results.append(o if isinstance(o, str) else f"EXC:{o!r}")
    ok = sum(1 for r in results if r.startswith("OK"))
    bad = [r for r in results if not r.startswith("OK")]
    return ok, bad[:3]


# ------------------------------------------------------------------ part B
HEART = {
    "id": "hb",
    "initial": "t",
    "context": {"n": 0},
    "states": {
        "t": {
            "entry": [{"type": "raise",
                       "params": {"event": "TICK", "delay": 2, "id": "hb"}}],
            "on": {"TICK": {"actions": ["beat"]}},
        }
    },
}


def beat(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1
    if c["n"] < 200:
        i.send("REARM") if False else None


async def part_b(kind):
    """200-beat raise(delay=) heartbeat; watch _timer_handles growth."""
    n = {"v": 0}

    def beat_def(i, c, e, a=None):
        c["n"] = c.get("n", 0) + 1
        n["v"] = c["n"]
        if c["n"] < 200:
            i._arm = None
        # re-arm via a fresh raise action is done by the chart below

    c = {
        "id": "hb",
        "initial": "t",
        "context": {"n": 0},
        "states": {
            "t": {
                "entry": [{"type": "raise",
                           "params": {"event": "TICK", "delay": 2,
                                      "id": "hb"}}],
                "on": {"TICK": {"actions": [
                    "beat",
                    {"type": "raise", "params": {"event": "TICK",
                                                 "delay": 2, "id": "hb"}},
                ]}},
            }
        },
    }

    async def beat_async(i, ctx, e, a=None):
        beat_def(i, ctx, e, a)

    lg = MachineLogic(
        actions={"beat": beat_async if kind == "async def" else beat_def}
    )
    it = Interpreter(create_machine(json.loads(json.dumps(c)), logic=lg))
    await it.start()
    peak = 0
    for _ in range(300):
        await asyncio.sleep(0.02)
        hc = handle_counts(it)
        peak = max([peak] + list(hc.values()) or [peak])
        if it.context.get("n", 0) >= 200:
            break
    beats = it.context.get("n", 0)
    armed = len(getattr(it, "_armed_self_sends", {}) or {})
    hc = handle_counts(it)
    await it.stop()
    return beats, peak, hc, armed


# ------------------------------------------------------------------ part C
async def part_c(kind):
    """cancel storm: arm + cancel 500 delayed sends."""
    c = {
        "id": "storm",
        "initial": "s",
        "context": {"fired": 0},
        "states": {
            "s": {
                "on": {
                    "ARM": {"actions": [
                        {"type": "raise", "params": {"event": "BOOM",
                                                     "delay": 300,
                                                     "id": "z"}}]},
                    "KILL": {"actions": [
                        {"type": "cancel", "params": {"sendId": "z"}}]},
                    "BOOM": {"actions": ["fired"]},
                }
            }
        },
    }

    def fired(i, ctx, e, a=None):
        ctx["fired"] = ctx.get("fired", 0) + 1

    async def fired_a(i, ctx, e, a=None):
        fired(i, ctx, e, a)

    lg = MachineLogic(
        actions={"fired": fired_a if kind == "async def" else fired}
    )
    it = Interpreter(create_machine(json.loads(json.dumps(c)), logic=lg))
    await it.start()
    peak = 0
    err = None
    try:
        for _ in range(500):
            await it.send("ARM")
            await it.send("KILL")
            hc = handle_counts(it)
            peak = max([peak] + list(hc.values()) or [peak])
    except Exception as ex:  # noqa: BLE001
        err = f"{type(ex).__name__}: {ex}"
    await asyncio.sleep(0.3)
    res = (it.context.get("fired", 0), peak, handle_counts(it),
           len(getattr(it, "_armed_self_sends", {}) or {}),
           len(getattr(it, "_scheduled_sends", {}) or {}), err)
    await it.stop()
    return res


async def main():
    print("F2 -- #219 ReentrantWaitError matrix + #218 handle release")
    print("\nA -- ReentrantWaitError matrix")
    for kind in ("def", "async def"):
        r1 = await a1(kind)
        r2 = await a2(kind)
        r3 = await a3(kind)
        r4 = await a45(kind, "cross")
        print(f"  {kind:9s} A1 self-await          = {r1}")
        print(f"  {kind:9s} A2 ensure_future later = {r2}")
        print(f"  {kind:9s} A3 after-fired handler = {r3}")
        print(f"  {kind:9s} A4 cross-interpreter   = {r4}")
        if kind == "async def" and r1 != "ReentrantWaitError":
            DEFECTS.append(f"A1/{kind}: expected ReentrantWaitError, got {r1}")
        if r3 not in ("ReentrantWaitError",) and kind == "async def":
            DEFECTS.append(f"A3/{kind}: after-fired handler -> {r3}")
        if not str(r2).startswith("OK"):
            DEFECTS.append(f"A2/{kind}: ensure_future receipt -> {r2}")
        if not str(r4).startswith("OK"):
            DEFECTS.append(f"A4/{kind}: cross-interpreter wait -> {r4}")
    print(f"  sync      A6 self-send wait=True  = {a6('def')}")
    ok, bad = await a7("async def", 100)
    print(f"  A7 100 concurrent ensure_future actions: OK={ok}/100 bad={bad}")
    if ok != 100:
        DEFECTS.append(f"A7: only {ok}/100 concurrent ensure_future receipts "
                       f"resolved; samples={bad}")

    print("\nB -- #218 timer-handle release (200-beat raise(delay=) heartbeat)")
    for kind in ("def", "async def"):
        beats, peak, hc, armed = await part_b(kind)
        print(f"  {kind:9s} beats={beats} peak_handles_per_owner={peak} "
              f"final={hc} armed={armed}")
        if peak > 2:
            DEFECTS.append(f"B/{kind}: timer handles peaked at {peak} over "
                           f"{beats} beats (expected <=1-2)")

    print("\nC -- cancel storm (500 arm/cancel pairs)")
    for kind in ("def", "async def"):
        fired, peak, hc, armed, sched, err = await part_c(kind)
        print(f"  {kind:9s} fired={fired} peak_handles={peak} final={hc} "
              f"armed={armed} scheduled={sched} err={err}")
        if fired != 0 or err or armed != 0 or peak > 2 or sched != 0:
            DEFECTS.append(f"C/{kind}: fired={fired} peak={peak} armed={armed}"
                           f" scheduled={sched} err={err}")

    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS:
        print("   -", d)
    raise SystemExit(1 if DEFECTS else 0)


asyncio.run(main())
