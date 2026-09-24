"""G2 -- v0.9.0 concurrency / semantics: #225 task-identity provenance,
#232 RuntimeWarning on a dropped wait=True receipt, #219 residual.

A: task-identity matrix. The #225 predicate is "is the CURRENT TASK running
   one of my actions?", and its sharpest observable is the #219 guard on
   `send(..., wait=True)`: refused (INTERNAL) vs a resolving Receipt
   (EXTERNAL). Plain-queue routing is NOT a usable oracle -- an internal
   send is drained later in the SAME macrostep, so it lands either way.
     a1 action -> await send(wait=True)              expect REFUSED
     a2 action -> helper task -> send(wait=True)     expect OK  (#225)
     a4 action -> task -> task -> send(wait=True)    expect OK
     a5 def service -> send_threadsafe (other thread) expect OK
     a6 child action -> parent send(wait=True)       expect OK
     a7 after handler -> send(wait=True)             expect REFUSED
B: 200 machines x worker-spawned-from-action outliving the action. Every
   worker send must land (no internal-queue starvation with the loop idle).
C: 100 concurrent ensure_future(send(wait=True)) hand-outs while the
   spawning actions keep awaiting.
D: #232 RuntimeWarning -- where does it surface, and under -W error inside
   asyncio what breaks?

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import gc
import logging
import os
import sys
import warnings

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

DEFECTS = []
NM = int(os.environ.get("N_MACHINES", "200"))


def cfg(mid):
    return {
        "id": mid,
        "initial": "a",
        "context": {"hits": 0},
        "states": {
            "a": {"entry": ["kick"], "on": {"PING": {"actions": ["bump"]}}},
        },
    }


# --------------------------------------------------------------- A: matrix
async def matrix(kind):
    """Each cell returns 'REFUSED:<Exc>' or 'OK:<Receipt-ish>'."""
    rows = []

    async def run(label, mk_action, extra_cfg=None):
        box = {}
        c = extra_cfg or {
            "id": "mx",
            "initial": "a",
            "context": {},
            "states": {
                "a": {"entry": ["k"], "on": {"P": {"target": "b"}}},
                "b": {},
            },
        }
        m = create_machine(
            c, logic=MachineLogic(actions={"k": mk_action(box)})
        )
        it = Interpreter(m)
        await it.start()
        for _ in range(200):
            if "verdict" in box:
                break
            await asyncio.sleep(0.01)
        v = box.get("verdict", "TIMEOUT(no outcome in 2s)")
        await it.stop()
        rows.append((label, v))
        print(f"  A/{kind:9s} {label:40s} -> {v}")
        return v

    def _record(box):
        async def go(coro):
            try:
                r = await coro
                box["verdict"] = f"OK:{type(r).__name__}"
            except Exception as exc:  # noqa: BLE001
                box["verdict"] = f"REFUSED:{type(exc).__name__}"

        return go

    # a1: the action's own task awaits its own receipt
    def mk_a1(box):
        go = _record(box)
        if kind == "def":

            def k(i, c, e, a=None):
                # a def action cannot await; record what it got back
                r = i.send("P", wait=True)
                box["verdict"] = f"DEF-RETURNED:{type(r).__name__}"
                asyncio.ensure_future(go(r))  # counts as "used" (#232)

            return k

        async def k(i, c, e, a=None):
            await go(i.send("P", wait=True))

        return k

    # a2: helper task spawned by the action awaits it
    def mk_a2(box):
        go = _record(box)

        async def helper(i):
            await asyncio.sleep(0.01)
            await go(i.send("P", wait=True))

        if kind == "def":

            def k(i, c, e, a=None):
                asyncio.ensure_future(helper(i))

            return k

        async def k(i, c, e, a=None):
            asyncio.ensure_future(helper(i))
            for _ in range(3):
                await asyncio.sleep(0.002)  # action keeps awaiting

        return k

    # a4: action -> task -> task -> send
    def mk_a4(box):
        go = _record(box)

        async def inner(i):
            await asyncio.sleep(0.01)
            await go(i.send("P", wait=True))

        async def outer(i):
            await asyncio.sleep(0.005)
            asyncio.ensure_future(inner(i))

        if kind == "def":

            def k(i, c, e, a=None):
                asyncio.ensure_future(outer(i))

            return k

        async def k(i, c, e, a=None):
            asyncio.ensure_future(outer(i))

        return k

    # a5: another THREAD (the documented send_threadsafe path)
    def mk_a5(box):
        def worker(i):
            import time

            time.sleep(0.01)
            try:
                r = i.send_threadsafe("P").result(timeout=3)
                box["verdict"] = f"OK:{type(r).__name__}"
            except Exception as exc:  # noqa: BLE001
                box["verdict"] = f"REFUSED:{type(exc).__name__}"

        if kind == "def":

            def k(i, c, e, a=None):
                asyncio.get_running_loop().run_in_executor(None, worker, i)

            return k

        async def k(i, c, e, a=None):
            asyncio.get_running_loop().run_in_executor(None, worker, i)

        return k

    # a7: an `after` handler's action awaits its own receipt
    A7_CFG = {
        "id": "mx7",
        "initial": "a",
        "context": {},
        "states": {
            "a": {"after": {5: {"target": "t"}}},
            "t": {"entry": ["k"], "on": {"P": {"target": "b"}}},
            "b": {},
        },
    }

    for label, mk, cfg_ in (
        ("a1 action awaits own receipt", mk_a1, None),
        ("a2 action -> helper task -> receipt", mk_a2, None),
        ("a4 action -> task -> task -> receipt", mk_a4, None),
        ("a5 other thread -> send_threadsafe", mk_a5, None),
        ("a7 after-handler awaits own receipt", mk_a1, A7_CFG),
    ):
        await run(label, mk, cfg_)

    # a6: a CHILD's action sends to its PARENT interpreter
    box6 = {}
    go6 = _record(box6)

    async def child_k(i, c, e, a=None):
        parent = c.get("_p") or box6.get("parent")
        if parent is not None:
            await go6(parent.send("P", wait=True))

    def child_k_def(i, c, e, a=None):
        parent = box6.get("parent")
        if parent is not None:
            asyncio.ensure_future(go6(parent.send("P", wait=True)))

    pcfg = {
        "id": "mxp",
        "initial": "a",
        "states": {"a": {"on": {"P": {"target": "b"}}}, "b": {}},
    }
    ccfg = {
        "id": "mxc",
        "initial": "a",
        "states": {"a": {"entry": ["ck"]}},
    }
    pm = create_machine(pcfg, logic=MachineLogic())
    cm = create_machine(
        ccfg,
        logic=MachineLogic(
            actions={"ck": child_k_def if kind == "def" else child_k}
        ),
    )
    p = Interpreter(pm)
    await p.start()
    box6["parent"] = p
    ci = Interpreter(cm)
    await ci.start()
    for _ in range(200):
        if "verdict" in box6:
            break
        await asyncio.sleep(0.01)
    v6 = box6.get("verdict", "TIMEOUT")
    rows.append(("a6 child action -> parent receipt", v6))
    print(f"  A/{kind:9s} {'a6 child action -> parent receipt':40s} -> {v6}")
    await ci.stop()
    await p.stop()

    expect = {
        "a1 action awaits own receipt": "REFUSED",
        "a2 action -> helper task -> receipt": "OK",
        "a4 action -> task -> task -> receipt": "OK",
        "a5 other thread -> send_threadsafe": "OK",
        "a7 after-handler awaits own receipt": "REFUSED",
        "a6 child action -> parent receipt": "OK",
    }
    for label, v in rows:
        want = expect[label]
        if kind == "def" and v.startswith("DEF-RETURNED"):
            continue  # a def action cannot await; #232 covers it (part D)
        if not v.startswith(want):
            DEFECTS.append(
                f"A/{kind} {label}: got {v}, expected {want}* (#225/#219)"
            )
    return rows


# ------------------------------------------------- B: 200 outliving workers
async def part_b(kind):
    its = []
    done = {"n": 0}

    async def worker(i):
        await asyncio.sleep(0.02)  # outlive the action
        await i.send("PING")
        done["n"] += 1

    def bump(i, c, e, a=None):
        c["hits"] = c.get("hits", 0) + 1

    def kick_def(i, c, e, a=None):
        asyncio.ensure_future(worker(i))

    async def kick_async(i, c, e, a=None):
        asyncio.ensure_future(worker(i))

    lg = MachineLogic(
        actions={
            "kick": kick_def if kind == "def" else kick_async,
            "bump": bump,
        }
    )
    for n in range(NM):
        m = create_machine(cfg(f"b{n}"), logic=lg)
        its.append(Interpreter(m))
    await asyncio.gather(*(i.start() for i in its))
    # Loop stays idle apart from the workers; poll to convergence.
    for _ in range(600):
        if sum(i.context.get("hits", 0) for i in its) >= NM:
            break
        await asyncio.sleep(0.01)
    landed = sum(i.context.get("hits", 0) for i in its)
    await asyncio.gather(*(i.stop() for i in its))
    print(
        f"  B/{kind:9s} machines={NM} worker_sends_issued={done['n']} "
        f"landed={landed}/{NM}"
    )
    if landed != NM:
        DEFECTS.append(
            f"B/{kind}: {NM - landed}/{NM} worker sends never drained "
            f"(internal-queue starvation, #225)"
        )


# --------------------------------------- C: 100 concurrent hand-out receipts
async def part_c(kind):
    c = {
        "id": "cc",
        "initial": "a",
        "states": {
            "a": {"entry": ["hand"], "on": {"GO": {"target": "b"}}},
            "b": {},
        },
    }
    res = {"ok": 0, "bad": []}

    async def finish(fut):
        try:
            r = await fut
            res["ok"] += 1
            return r
        except Exception as exc:  # noqa: BLE001
            res["bad"].append(type(exc).__name__)

    def hand_def(i, ctx, e, a=None):
        fut = asyncio.ensure_future(i.send("GO", wait=True))
        asyncio.ensure_future(finish(fut))

    async def hand_async(i, ctx, e, a=None):
        fut = asyncio.ensure_future(i.send("GO", wait=True))
        asyncio.ensure_future(finish(fut))
        # keep awaiting AFTER handing out -- the #225 regression shape
        for _ in range(5):
            await asyncio.sleep(0.002)

    lg = MachineLogic(
        actions={"hand": hand_def if kind == "def" else hand_async}
    )
    its = [
        Interpreter(create_machine({**c, "id": f"cc{n}"}, logic=lg))
        for n in range(100)
    ]
    await asyncio.gather(*(i.start() for i in its))
    for _ in range(300):
        if res["ok"] + len(res["bad"]) >= 100:
            break
        await asyncio.sleep(0.01)
    states = sum(1 for i in its if "b" in str(i.current_state_ids))
    await asyncio.gather(*(i.stop() for i in its))
    print(
        f"  C/{kind:9s} receipts_resolved={res['ok']}/100 "
        f"failures={res['bad'][:5]} advanced={states}/100"
    )
    if res["ok"] != 100:
        DEFECTS.append(
            f"C/{kind}: only {res['ok']}/100 handed-out receipts resolved "
            f"({res['bad'][:5]})"
        )


# ----------------------------------------------- D: #232 RuntimeWarning
async def part_d():
    c = {
        "id": "dd",
        "initial": "a",
        "states": {"a": {"entry": ["drop"], "on": {"B": {"target": "b"}}}, "b": {}},
    }

    def drop(i, ctx, e, a=None):
        r = i.send("B", wait=True)  # def action cannot await -> dropped
        del r

    m = create_machine(c, logic=MachineLogic(actions={"drop": drop}))
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        it = Interpreter(m)
        await it.start()
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
        await it.stop()
    hits = [
        (x.category.__name__, str(x.message)[:90])
        for x in w
        if issubclass(x.category, RuntimeWarning)
    ]
    print(f"  D1 dropped receipt warnings = {hits}")
    if not hits:
        DEFECTS.append("D1: #232 RuntimeWarning never surfaced")

    # D2: -W error inside asyncio -- where does the exception land?
    m2 = create_machine({**c, "id": "dd2"}, logic=MachineLogic(actions={"drop": drop}))
    seen = {"loop_exc": [], "raised": None}

    def handler(loop, ctx):
        seen["loop_exc"].append(type(ctx.get("exception")).__name__)

    loop = asyncio.get_running_loop()
    old = loop.get_exception_handler()
    loop.set_exception_handler(handler)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            it2 = Interpreter(m2)
            try:
                await it2.start()
                await asyncio.sleep(0.05)
                gc.collect()
                await asyncio.sleep(0.05)
            except Exception as exc:  # noqa: BLE001
                seen["raised"] = type(exc).__name__
            st = it2.status
            le = type(it2.last_error).__name__
            await it2.stop()
    finally:
        loop.set_exception_handler(old)
    print(
        f"  D2 -W error: raised_to_caller={seen['raised']} "
        f"loop_exception_handler={seen['loop_exc']} status={st} "
        f"last_error={le}"
    )


async def main():
    print("G2 -- #225 task identity, #232 RuntimeWarning, #219 residual\n")
    print("A -- task-identity matrix (loop idle; did the send land?)")
    for kind in ("def", "async def"):
        await matrix(kind)
    print(f"\nB -- {NM} machines x action-spawned worker outliving the action")
    for kind in ("def", "async def"):
        await part_b(kind)
    print("\nC -- 100 concurrent ensure_future(send(wait=True)) hand-outs")
    for kind in ("def", "async def"):
        await part_c(kind)
    print("\nD -- #232 RuntimeWarning surface")
    await part_d()
    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS:
        print("   -", d)
    return 1 if DEFECTS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
