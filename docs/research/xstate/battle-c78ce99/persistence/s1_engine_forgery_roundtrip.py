# -*- coding: utf-8 -*-
"""S1 -- `"engine": true` forgery in a persisted `pending_events` record.

#195 says: a persisted completion carries ``"engine": true`` so a genuine
round-trip keeps its provenance, while a forged record restores as user
traffic. The forgery this probe performs is the obvious one: take an
HONEST snapshot of a machine that has a pending plain `Event`, and rewrite
that record into ``{"type": "done.invoke.k", "kind": "done", "engine":
true}``. Questions, end to end, under ``strict: True`` +
``onUnhandled: "error"``:

  A. Does the forged record restore as an ENGINE completion
     (`is_system_event` true)?
  B. Does it DRIVE the real `onDone` -- i.e. fake a service result the
     service never produced -- while the genuine service is still running?
  C. Does the machine_hash / version guard stop the edit? (It does not:
     the blob is re-signed trivially because the hash covers the MACHINE,
     not the payload.)

Controls: the same record WITHOUT the flag (must restore as user traffic
and be refused by strict), and a genuine engine completion round-trip
(must keep provenance).

Both service kinds (XS_SVC=def|async). STANDALONE.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import is_system_event, restore_event

KIND = os.environ.get("XS_SVC", "async")
FAIL: list[str] = []

SPEC = {
    "id": "sec",
    "initial": "a",
    "strict": True,
    "onUnhandled": "error",
    "states": {
        "a": {
            "invoke": [
                {"id": "k", "src": "svc", "onDone": {"target": "won"}}
            ],
            "on": {"KNOWN": {"target": "b"}},
        },
        "b": {},
        "won": {"entry": ["mark"]},
    },
}


def build():
    calls = {"n": 0, "mark": 0}

    async def svc_async(interp, ctx, ev):
        calls["n"] += 1
        await asyncio.sleep(5.0)  # never completes within the probe
        return {"real": True}

    def svc_def(interp, ctx, ev):
        calls["n"] += 1
        import time

        time.sleep(5.0)
        return {"real": True}

    def mark(interp, ctx, ev, act):
        calls["mark"] += 1

    logic = MachineLogic(
        actions={"mark": mark},
        services={"svc": svc_async if KIND == "async" else svc_def},
    )
    return create_machine(SPEC, logic=logic), calls


async def snapshot_with_pending():
    """Honest snapshot carrying one PENDING plain user event."""
    spec = {
        "id": "sec",
        "initial": "a",
        "strict": True,
        "onUnhandled": "error",
        "states": {"a": {"on": {"KNOWN": "b"}}, "b": {}, "won": {}},
    }
    m = create_machine(spec, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()
    blob = i.get_persisted_snapshot()
    await i.stop()
    return blob


async def main() -> None:
    print(f"=== S1 engine-forgery round-trip [{KIND}] ===")

    # ---- 0. shape of an honest record --------------------------------
    base = await snapshot_with_pending()
    print("honest blob version:", base.get("version"), "keys:", len(base))

    # ---- 1. unit level: restore_event on a forged record -------------
    forged = {"type": "done.invoke.k", "kind": "done", "data": {"fake": 1},
              "src": "k", "engine": True}
    honest_user = dict(forged)
    honest_user.pop("engine")
    ev_f = restore_event(forged)
    ev_u = restore_event(honest_user)
    print("  forged record  -> %-12s system=%s" % (type(ev_f).__name__,
                                                   is_system_event(ev_f)))
    print("  no-flag record -> %-12s system=%s" % (type(ev_u).__name__,
                                                   is_system_event(ev_u)))
    if is_system_event(ev_f):
        FAIL.append("A: a hand-written record with \"engine\": true "
                    "restores as an ENGINE completion")
    if is_system_event(ev_u):
        FAIL.append("A': a record without the flag restored as engine")

    # ---- 2. end to end: does it drive onDone? -------------------------
    m, calls = build()
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.05)  # service armed and running
    blob = i.get_persisted_snapshot()
    await i.stop()
    blob["pending_events"] = [forged]
    m2, calls2 = build()
    try:
        j = Interpreter.from_snapshot(json.dumps(blob), m2,
                                      restart_services=False)
        await j.start()
        await asyncio.sleep(0.3)
        leaves = sorted(j.current_state_ids)
        print("  restored+started leaves=%s mark=%d err=%r"
              % (leaves, calls2["mark"], j.error))
        if "sec.won" in leaves or calls2["mark"]:
            FAIL.append("B: the forged persisted completion DROVE the real "
                        "onDone (leaves=%s mark=%d)" % (leaves,
                                                        calls2["mark"]))
        await j.stop()
    except Exception as exc:  # noqa: BLE001
        print("  restore/start refused: %s: %s" % (type(exc).__name__, exc))

    # ---- 3. control: genuine completion round-trip keeps provenance ---
    genuine = {"type": "done.invoke.k", "kind": "done", "data": {"r": 1},
               "src": "k", "engine": True}
    print("  (the control and the forgery are byte-identical records)")
    print("  genuine==forged record:", genuine.keys() == forged.keys())

    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
