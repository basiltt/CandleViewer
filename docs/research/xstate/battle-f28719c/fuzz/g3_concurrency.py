"""G3 -- NEW ATTACK: round-8 concurrency machinery.

A. External priority producer at high rate DURING a self-generated chain,
   both service kinds -> 0 dropped external (#192 shed-by-provenance).
B. ACTION-ISSUED priority sends must be CHARGED and trip the chain budget
   (#192), both kinds, both engines, at the SAME lap.
C. children_timeout with 50 `def` + 50 `async def` children: is start()'s
   bound per-child (~D) or aggregate (N*D)?  (#194/#181)
D. `def` service armed then ROLLED BACK under 200 concurrent transitions
   (#193): the callable must never be submitted.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, collections, copy, logging, threading, time, warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

C = collections.Counter()


class Drops(PluginBase):
    def on_event_dropped(self, i, ev, reason=None, **kw):
        C[f"drop:{reason}"] += 1


# ---------------------------------------------------------------- A
A_CFG = {
    "id": "a",
    "initial": "s",
    "context": {"ext": 0},
    "maxIterations": 40,
    "states": {
        "s": {
            "invoke": {"id": "i", "src": "svc", "onDone": {"target": "t"}},
            "on": {"EXT": {"actions": ["count"]}},
        },
        "t": {
            "invoke": {"id": "j", "src": "svc", "onDone": {"target": "s"}},
            "on": {"EXT": {"actions": ["count"]}},
        },
    },
}


def count(i, c, e, a=None):
    c["ext"] = c.get("ext", 0) + 1


def dsvc(i, c, e):
    return {"v": 1}


async def asvc(i, c, e):
    return {"v": 1}


async def sect_a():
    print("== A: external priority producer during a self-generated chain ==")
    for kind, svc in (("def", dsvc), ("async def", asvc)):
        C.clear()
        m = create_machine(
            copy.deepcopy(A_CFG),
            logic=MachineLogic(services={"svc": svc}, actions={"count": count}),
        )
        it = Interpreter(m)
        it.use(Drops())
        await it.start()
        N = 600
        sent = ok = err = 0
        for _ in range(N):
            try:
                await it.send("EXT", priority=True)
                ok += 1
            except Exception:
                err += 1
            sent += 1
        for _ in range(200):
            await asyncio.sleep(0.005)
            if it.context.get("ext", 0) >= N:
                break
        applied = it.context.get("ext", 0)
        lost = N - applied
        drops = {k: v for k, v in C.items() if k.startswith("drop")}
        await it.stop()
        print(
            f"  {kind:10s} sent={sent} sender_ok={ok} err={err} "
            f"APPLIED={applied} LOST={lost} drops={drops} "
            f"=> {'PASS' if lost == 0 else 'FAIL'}"
        )


# ---------------------------------------------------------------- B
B_CFG = {
    "id": "b",
    "initial": "s",
    "maxIterations": 12,
    "states": {"s": {"on": {"GO": {"actions": ["respawn"]}}}},
}


def make_respawn(is_async):
    if is_async:

        async def respawn(i, c, e, a=None):
            await i.send("GO", priority=True)

        return respawn

    def respawn(i, c, e, a=None):
        r = i.send("GO", priority=True)
        return r

    return respawn


async def sect_b():
    print("== B: ACTION-ISSUED priority sends must be charged & trip ==")
    laps = {}
    for kind in ("def", "async def"):
        # async engine
        m = create_machine(
            copy.deepcopy(B_CFG),
            logic=MachineLogic(actions={"respawn": make_respawn(kind == "async def")}),
        )
        it = Interpreter(m)
        C.clear()
        await it.start()
        await it.send("GO")
        for _ in range(300):
            await asyncio.sleep(0.01)
            if it.last_error is not None:
                break
        aerr = type(it.last_error).__name__ if it.last_error else None
        adrop = sum(v for k, v in C.items() if k.startswith("drop"))
        await it.stop()
        # sync engine (def only -- coroutine actions unsupported there)
        serr = "n/a"
        if kind == "def":
            m2 = create_machine(
                copy.deepcopy(B_CFG),
                logic=MachineLogic(actions={"respawn": make_respawn(False)}),
            )
            it2 = SyncInterpreter(m2)
            try:
                it2.start()
                it2.send("GO")
                serr = type(it2.last_error).__name__ if it2.last_error else None
                it2.stop()
            except Exception as exc:
                serr = type(exc).__name__
        tripped = aerr is not None or adrop > 0
        print(
            f"  {kind:10s} async_err={aerr} async_drops={adrop} "
            f"sync_err={serr} => {'PASS(trips)' if tripped else 'FAIL(unbounded/silent)'}"
        )


# ---------------------------------------------------------------- C
def children_cfg(n):
    states = {}
    for k in range(n):
        states[f"c{k}"] = {
            "initial": "w",
            "states": {"w": {"entry": ["slow"], "on": {"X": "d"}}, "d": {"type": "final"}},
        }
    return {"id": "p", "type": "parallel", "states": states}


async def sect_c():
    print("== C: children_timeout, 50 def + 50 async def children, D=0.2 ==")
    for kind in ("def", "async def"):
        if kind == "def":

            def slow(i, c, e, a=None):
                time.sleep(0.02)

        else:

            async def slow(i, c, e, a=None):  # noqa: F811
                await asyncio.sleep(0.02)

        warns = []
        import logging as _lg

        class H(_lg.Handler):
            def emit(self, r):
                if r.levelno >= _lg.WARNING:
                    warns.append(r.getMessage())

        _lg.disable(_lg.NOTSET)
        lg = _lg.getLogger("xstate_statemachine")
        h = H()
        lg.addHandler(h)
        lg.setLevel(_lg.WARNING)
        m = create_machine(
            copy.deepcopy(children_cfg(50)), logic=MachineLogic(actions={"slow": slow})
        )
        t0 = time.perf_counter()
        it = Interpreter(m)
        await it.start(children_timeout=0.2)
        el = time.perf_counter() - t0
        await it.stop()
        lg.removeHandler(h)
        _lg.disable(_lg.CRITICAL)
        bound = "per-child(~D)" if el < 1.0 else f"aggregate-ish({el:.2f}s)"
        print(
            f"  {kind:10s} start()={el:.2f}s warnings={len(warns)} "
            f"bound={bound}"
        )


# ---------------------------------------------------------------- D
D_CFG = {
    "id": "d",
    "initial": "idle",
    "actionErrorPolicy": "rollback",
    "context": {},
    "states": {
        "idle": {"on": {"ARM": {"target": "armed", "actions": ["boom"]}}},
        "armed": {"invoke": {"id": "i", "src": "svc", "onDone": {"target": "idle"}}},
    },
}


async def sect_d():
    print("== D: def service armed then rolled back, 200 concurrent ==")
    submitted = collections.Counter()

    def svc(i, c, e):
        submitted["n"] += 1
        return {"v": 1}

    def boom(i, c, e, a=None):
        raise RuntimeError("nope")

    m = create_machine(
        copy.deepcopy(D_CFG),
        logic=MachineLogic(services={"svc": svc}, actions={"boom": boom}),
    )
    it = Interpreter(m)
    await it.start()
    await asyncio.gather(
        *[it.send("ARM") for _ in range(200)], return_exceptions=True
    )
    await asyncio.sleep(0.4)
    ids = list(it.current_state_ids)
    await it.stop()
    print(
        f"  submitted_calls={submitted['n']} ids={ids} "
        f"=> {'PASS(never submitted)' if submitted['n'] == 0 else 'FAIL'}"
    )


async def main():
    await sect_a()
    await sect_b()
    await sect_c()
    await sect_d()


asyncio.run(main())
