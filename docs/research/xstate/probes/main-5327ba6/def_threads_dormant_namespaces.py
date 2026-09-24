"""D/E/F — threadsafe strict, dormant invocations, reserved namespaces.

D1  payload SCHEMA violation from a foreign thread -> raises on that thread?
D2  unknown event name from a foreign thread while the loop is SATURATED
D3  strict + unknown event from thread BEFORE start() -> which error?
D4  send_threadsafe on a STOPPED interpreter from a thread
D5  10 threads x 200 sends, half invalid: no invalid event reaches the machine

E1  has_dormant_invocations across snapshot -> restore -> restart_services
    -> snapshot again -> restore
E2  has_dormant_invocations on a LIVE machine with a running invoke
E3  pending_invocations agrees with has_dormant_invocations at every step

F1  SYSTEM_EVENT_PREFIXES monkeypatch: does appending a prefix take effect?
F2  "done." with trailing content: "done.review" vs "doneReview" vs "done"
F3  case variants: "DONE.review", "Done.Review"
F4  a user event named exactly "done" (no dot) -- ordinary semantics?
F5  the build-time UserWarning for a reserved `on` key
F6  "error.validation" invisible to "*" under onUnhandled:"error"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h  # noqa: E402

import xstate_statemachine as xsm  # noqa: E402
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)
from xstate_statemachine.exceptions import (  # noqa: E402
    InvalidEventPayloadError,
    UnknownEventError,
)

warnings.simplefilter("ignore", DeprecationWarning)

STRICT_CFG = {
    "id": "t",
    "initial": "a",
    "context": {"n": 0},
    "strict": True,
    "states": {"a": {"on": {"TICK": {"actions": ["bump"]}}}},
}


def bump(i, c, e, a):
    c["n"] += 1


def mk_strict(**kw):
    return create_machine(dict(STRICT_CFG, **kw), logic=MachineLogic(actions={"bump": bump}))


def _in_thread(fn):
    box = {}

    def run():
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = f"{type(exc).__name__}"

    t = threading.Thread(target=run)
    t.start()
    t.join(10)
    return box


# --------------------------------------------------------------- D1
@_h.probe("D1", "send_threadsafe: payload schema violation raises on the thread",
          {"err": "InvalidEventPayloadError", "n": 0})
async def d1():
    def schema(payload):
        if not isinstance(payload.get("qty"), int):
            raise ValueError("qty must be int")

    m = mk_strict()
    m.event_schemas["TICK"] = schema
    i = Interpreter(m)
    await i.start()
    box = await asyncio.get_running_loop().run_in_executor(
        None, lambda: _in_thread(lambda: i.send_threadsafe("TICK", qty="oops"))
    )
    await asyncio.sleep(0.15)
    out = {"err": box.get("e", "NO-RAISE"), "n": i.context["n"]}
    await i.stop()
    return out


# --------------------------------------------------------------- D2
@_h.probe("D2", "send_threadsafe: unknown event from thread while loop saturated",
          {"err": "UnknownEventError", "n": 0})
async def d2():
    async def slow(i, c, e, a):
        await asyncio.sleep(0.01)
        c["n"] += 1

    m = create_machine(
        dict(STRICT_CFG, states={"a": {"on": {"TICK": {"actions": ["slow"]}}}}),
        logic=MachineLogic(actions={"slow": slow}),
    )
    i = Interpreter(m)
    await i.start()
    for _ in range(200):  # saturate
        await i.send("TICK")
    box = await asyncio.get_running_loop().run_in_executor(
        None, lambda: _in_thread(lambda: i.send_threadsafe("TYPO"))
    )
    out = {"err": box.get("e", "NO-RAISE"), "n": 0}
    await i.stop()
    out["n"] = 0
    return out


# --------------------------------------------------------------- D3
@_h.probe("D3", "send_threadsafe before start(): which error wins?", "DOCUMENT")
def d3():
    i = Interpreter(mk_strict())
    box = _in_thread(lambda: i.send_threadsafe("TYPO"))
    return {"err": box.get("e", "NO-RAISE")}


# --------------------------------------------------------------- D4
@_h.probe("D4", "send_threadsafe on a STOPPED interpreter, unknown event", "DOCUMENT")
async def d4():
    i = Interpreter(mk_strict())
    await i.start()
    await i.stop()
    box = await asyncio.get_running_loop().run_in_executor(
        None, lambda: _in_thread(lambda: i.send_threadsafe("TYPO"))
    )
    box2 = await asyncio.get_running_loop().run_in_executor(
        None, lambda: _in_thread(lambda: i.send_threadsafe("TICK"))
    )
    return {"unknown": box.get("e", "NO-RAISE"), "known": box2.get("e", "NO-RAISE")}


# --------------------------------------------------------------- D5
@_h.probe("D5", "10 threads x 200 sends, half invalid: zero invalid delivered",
          {"rejected": 1000, "n": 1000})
async def d5():
    i = Interpreter(mk_strict())
    await i.start()
    rejected = [0]
    lock = threading.Lock()

    def worker():
        for k in range(200):
            name = "TICK" if k % 2 == 0 else "TYPO"
            try:
                i.send_threadsafe(name)
            except UnknownEventError:
                with lock:
                    rejected[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: [t.join(20) for t in threads]
    )
    for _ in range(200):
        await asyncio.sleep(0.01)
        if i.context["n"] >= 1000:
            break
    out = {"rejected": rejected[0], "n": i.context["n"]}
    await i.stop()
    return out


# =============================================================== E
INV_CFG = {
    "id": "inv",
    "initial": "working",
    "context": {},
    "states": {
        "working": {
            "invoke": {"id": "job", "src": "longJob", "onDone": {"target": "done_"}},
        },
        "done_": {"type": "final"},
    },
}


async def long_job(i, c, e):
    await asyncio.sleep(30)
    return "x"


def mk_inv():
    return create_machine(INV_CFG, logic=MachineLogic(services={"longJob": long_job}))


@_h.probe(
    "E1",
    "dormant across snapshot -> restore -> restart_services -> snapshot -> restore",
    {
        "live": False,
        "restored_static": True,
        "restored_restarted": False,
        "resnapshot_restored_static": True,
    },
)
async def e1():
    live = Interpreter(mk_inv())
    await live.start()
    await asyncio.sleep(0.1)
    out = {"live": live.has_dormant_invocations}
    snap = live.get_snapshot()
    await live.stop()

    r1 = Interpreter.from_snapshot(snap, mk_inv())
    await r1.start()
    await asyncio.sleep(0.05)
    out["restored_static"] = r1.has_dormant_invocations
    snap2 = r1.get_snapshot()
    await r1.stop()

    r2 = Interpreter.from_snapshot(snap, mk_inv(), restart_services=True)
    await r2.start()
    await asyncio.sleep(0.1)
    out["restored_restarted"] = r2.has_dormant_invocations
    await r2.stop()

    r3 = Interpreter.from_snapshot(snap2, mk_inv())
    await r3.start()
    await asyncio.sleep(0.05)
    out["resnapshot_restored_static"] = r3.has_dormant_invocations
    await r3.stop()
    return out


@_h.probe("E2", "snapshot taken from a RESTARTED restore, then restored statically again",
          "DOCUMENT")
async def e2():
    live = Interpreter(mk_inv())
    await live.start()
    await asyncio.sleep(0.1)
    snap = live.get_snapshot()
    await live.stop()

    r = Interpreter.from_snapshot(snap, mk_inv(), restart_services=True)
    await r.start()
    await asyncio.sleep(0.1)
    dormant_after_restart = r.has_dormant_invocations
    snap_from_restarted = r.get_snapshot()
    await r.stop()

    r2 = Interpreter.from_snapshot(snap_from_restarted, mk_inv())
    await r2.start()
    await asyncio.sleep(0.05)
    out = {
        "dormant_after_restart": dormant_after_restart,
        "dormant_after_restore_of_restarted_snapshot": r2.has_dormant_invocations,
        "pending": [p.invoke_id for p in r2.pending_invocations()],
    }
    await r2.stop()
    return out


@_h.probe("E3", "pending_invocations agrees with has_dormant_invocations", True)
async def e3():
    live = Interpreter(mk_inv())
    await live.start()
    await asyncio.sleep(0.1)
    snap = live.get_snapshot()
    await live.stop()
    r = Interpreter.from_snapshot(snap, mk_inv())
    await r.start()
    await asyncio.sleep(0.05)
    ok = bool(r.pending_invocations()) == r.has_dormant_invocations
    await r.stop()
    return ok


# =============================================================== F
@_h.probe("F1", "monkeypatching events.SYSTEM_EVENT_PREFIXES has no effect", "DOCUMENT")
async def f1():
    import xstate_statemachine.events as ev
    import xstate_statemachine.base_interpreter as bi

    orig = ev.SYSTEM_EVENT_PREFIXES
    ev.SYSTEM_EVENT_PREFIXES = orig + ("cv.",)
    unhandled = []

    class W(PluginBase):
        def on_unhandled_event(self, i, e, active, disp):
            unhandled.append((e.type, disp))

    try:
        cfg = {"id": "mp", "initial": "a", "context": {},
               "onUnhandled": "defer", "states": {"a": {"on": {"X": {}}}}}
        i = Interpreter(create_machine(cfg, logic=MachineLogic())); i.use(W())
        await i.start()
        await i.send("cv.something")
        await asyncio.sleep(0.1)
        out = {
            "module_patched": "cv." in ev.SYSTEM_EVENT_PREFIXES,
            "base_interpreter_copy": "cv." in bi._SYSTEM_EVENT_PREFIXES,
            "unhandled_reported": unhandled,
            "deferred": i.deferred_count,
        }
        await i.stop()
        return out
    finally:
        ev.SYSTEM_EVENT_PREFIXES = orig


@_h.probe("F2", "'done.' trailing-content variants: which are treated as system?",
          "DOCUMENT")
async def f2():
    results = {}
    for name in ("done.review", "done.", "done", "doneReview", "done.invoke.x",
                 "donex", "error.validation", "errorx", "after.5", "afterx",
                 "xstate.foo", "___xstateY"):
        unhandled = []

        class W(PluginBase):
            def on_unhandled_event(self, i, e, active, disp):
                unhandled.append(disp)

        cfg = {"id": "ns", "initial": "a", "context": {},
               "onUnhandled": "defer", "states": {"a": {"on": {"NOPE": {}}}}}
        i = Interpreter(create_machine(cfg, logic=MachineLogic())); i.use(W())
        await i.start()
        await i.send(name)
        await asyncio.sleep(0.03)
        results[name] = unhandled[0] if unhandled else "EXEMPT(system)"
        await i.stop()
    return results


@_h.probe("F3", "case variants of a reserved prefix", "DOCUMENT")
async def f3():
    results = {}
    for name in ("DONE.review", "Done.Review", "ERROR.x", "After.5", "XSTATE.y"):
        unhandled = []

        class W(PluginBase):
            def on_unhandled_event(self, i, e, active, disp):
                unhandled.append(disp)

        cfg = {"id": "cs", "initial": "a", "context": {},
               "onUnhandled": "defer", "states": {"a": {"on": {"NOPE": {}}}}}
        i = Interpreter(create_machine(cfg, logic=MachineLogic())); i.use(W())
        await i.start()
        await i.send(name)
        await asyncio.sleep(0.03)
        results[name] = unhandled[0] if unhandled else "EXEMPT(system)"
        await i.stop()
    return results


@_h.probe("F5", "build-time UserWarning for reserved `on` keys", "DOCUMENT")
def f5():
    out = {}
    for key in ("done.review", "error.validation", "done.invoke.job",
                "after.500", "xstate.init", "DONE.review", "done"):
        cfg = {"id": "w", "initial": "a", "context": {},
               "states": {"a": {"on": {key: {}}}}}
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            try:
                create_machine(cfg, logic=MachineLogic())
                out[key] = [w.category.__name__ for w in rec
                            if w.category is UserWarning] or "no-warning"
            except Exception as exc:  # noqa: BLE001
                out[key] = type(exc).__name__
    return out


@_h.probe("F6", "'error.validation' as a user event: visible to '*'?", "DOCUMENT")
async def f6():
    hit = []

    def note(i, c, e, a):
        hit.append(e.type)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = {
            "id": "star", "initial": "a", "context": {},
            "onUnhandled": "error",
            "states": {"a": {"on": {"*": {"actions": ["note"]}}}},
        }
        i = Interpreter(create_machine(cfg, logic=MachineLogic(actions={"note": note})))
    await i.start()
    await i.send("ordinary")
    await i.send("error.validation")
    await i.send("done.review")
    await asyncio.sleep(0.1)
    out = {"matched_by_star": list(hit), "status": i.status}
    await i.stop()
    return out


if __name__ == "__main__":
    _h.main("def_threads_dormant_namespaces")
