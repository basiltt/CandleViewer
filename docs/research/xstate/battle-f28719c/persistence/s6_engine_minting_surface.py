# -*- coding: utf-8 -*-
"""S6 -- can user code mint an engine-minted completion? (#195 surface)

#195 replaced the bare-`isinstance` trust with PRIVATE subclasses
(`_EngineDone` / `_EngineError` / `_EngineAfter`, `events.py:567-585`) that
"are not exported and have no public name". This probe enumerates the ways
a caller reaches a private name in Python anyway, and then asks the only
question that matters: does the resulting object drive a real `onDone`
under `strict: True` + `onUnhandled: "error"` while the genuine service is
still running?

Vectors:
  1. `from xstate_statemachine.events import engine_done`  (module attr)
  2. `events._EngineDone("done.invoke.k", ...)`            (private class)
  3. `type(genuine)(...)` from a captured genuine event
  4. a user subclass of the PUBLIC `DoneEvent`
  5. `genuine._replace(data=...)`                          (NamedTuple)
  6. `pickle.loads(pickle.dumps(genuine))` retyped
  7. `copy.deepcopy(genuine)`
  8. a snapshot record with `"engine": true`               (see also s1)

Each vector is reported as MINTED / refused at construction, and then run
END TO END. `__slots__` on the private classes is checked too.

STANDALONE. XS_SVC=def|async.
"""
from __future__ import annotations

import asyncio
import copy
import os
import pickle

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import events as E

KIND = os.environ.get("XS_SVC", "async")
BREACH: list[str] = []

SPEC = {
    "id": "sec",
    "initial": "a",
    "strict": True,
    "onUnhandled": "error",
    "states": {
        "a": {
            "invoke": [{"id": "k", "src": "svc",
                        "onDone": {"target": "won"}}],
            "on": {"KNOWN": {"target": "b"}},
        },
        "b": {},
        "won": {"entry": ["mark"]},
    },
}


def build():
    bag = {"mark": 0}

    async def svc_async(interp, ctx, ev):
        await asyncio.sleep(5.0)
        return {"real": True}

    def svc_def(interp, ctx, ev):
        import time

        time.sleep(5.0)
        return {"real": True}

    def mark(interp, ctx, ev, act):
        bag["mark"] += 1

    logic = MachineLogic(
        actions={"mark": mark},
        services={"svc": svc_async if KIND == "async" else svc_def},
    )
    return create_machine(SPEC, logic=logic), bag


async def end_to_end(name, make):
    """Send the candidate at a live machine; report what happened."""
    m, bag = build()
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.05)
    try:
        ev = make()
    except Exception as exc:  # noqa: BLE001
        print("  %-42s construct-refused %s" % (name, type(exc).__name__))
        await i.stop()
        return
    sysf = E.is_system_event(ev)
    try:
        i.send(ev)
        await asyncio.sleep(0.2)
        leaves = sorted(i.current_state_ids)
        err = type(i.error).__name__ if i.error else None
        drove = "sec.won" in leaves or bag["mark"] > 0
        print("  %-42s system=%-5s leaves=%s err=%s%s"
              % (name, sysf, leaves, err,
                 "  <-- DROVE onDone" if drove else ""))
        if drove:
            BREACH.append("%s drove a real onDone" % name)
    except Exception as exc:  # noqa: BLE001
        print("  %-42s system=%-5s send-raised %s (enforced)"
              % (name, sysf, type(exc).__name__))
    finally:
        try:
            await i.stop()
        except Exception:  # noqa: BLE001
            pass


async def capture_genuine():
    """Get hold of a real engine completion object."""
    got = {}
    spec = {"id": "c", "initial": "a",
            "states": {"a": {"invoke": [{"id": "k", "src": "s",
                                         "onDone": {"target": "b"}}]},
                       "b": {}}}

    def spy(interp, ctx, ev, act):
        got["ev"] = ev

    async def s(interp, ctx, ev):
        return {"v": 1}

    spec["states"]["b"] = {"entry": ["spy"]}
    m = create_machine(spec, logic=MachineLogic(actions={"spy": spy},
                                                services={"s": s}))
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.2)
    await i.stop()
    return got.get("ev")


async def main() -> None:
    print("=== S6 engine-completion minting surface [%s] ===" % KIND)
    gen = await capture_genuine()
    print("captured genuine: %r type=%s system=%s"
          % (getattr(gen, "type", None), type(gen).__name__,
             E.is_system_event(gen)))
    print("private classes reachable as module attrs: %s"
          % [n for n in ("_EngineDone", "engine_done", "_ENGINE_MINTED_TYPES")
             if hasattr(E, n)])
    print("__slots__ on _EngineDone:", getattr(E._EngineDone, "__slots__",
                                               "<none>"))

    A = ("done.invoke.k", {"fake": 1}, "k")
    print("\n=== construction + end-to-end ===")
    await end_to_end("1 events.engine_done(...)", lambda: E.engine_done(*A))
    await end_to_end("2 events._EngineDone(...)", lambda: E._EngineDone(*A))
    await end_to_end("3 type(genuine)(...)", lambda: type(gen)(*A))
    await end_to_end("4 public DoneEvent(...)", lambda: E.DoneEvent(*A))

    class UserDone(E.DoneEvent):
        pass

    await end_to_end("5 user subclass of DoneEvent",
                     lambda: UserDone(*A))
    await end_to_end("6 genuine._replace(data=...)",
                     lambda: gen._replace(data={"fake": 1}))
    await end_to_end("7 pickle round-trip of genuine",
                     lambda: pickle.loads(pickle.dumps(gen)))
    await end_to_end("8 deepcopy of genuine", lambda: copy.deepcopy(gen))

    print("\nBREACHES:", BREACH if BREACH else "none")
    print("VERDICT:", "FAIL" if BREACH else "PASS")


asyncio.run(main())
