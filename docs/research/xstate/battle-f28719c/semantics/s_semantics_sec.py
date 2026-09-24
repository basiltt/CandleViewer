"""D9-S: SCXML §3.13 eventless selection + engine-provenance security.

S1  `always` at a DEEPER depth vs a named handler at a SHALLOWER depth
    (#196): the named handler's action must fire exactly once and the
    spinning `always` must never consume the named event. Both engines.
S2  Engine-provenance forgery sweep (#195): public class / import path /
    `type(held_instance)(...)` / `_replace` on a genuinely received
    completion / deepcopy / pickle / `Event` + `_ENGINE_MARK`.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import pickle
import sys
import traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    DoneEvent,
    Event,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.events import engine_done, is_system_event

logging.disable(logging.CRITICAL)

_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


def main(group: str) -> None:
    out, npass = [], 0
    for a in _REG:
        rec = {"id": a["id"], "title": a["title"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {"exc": f"{type(exc).__name__}: {exc}",
                             "tb": traceback.format_exc()[-1500:]}
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:6} {a['title'][:86]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1300])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


# ==========================================================================
# S1 -- deeper `always` must not consume a shallower named event (#196)
# ==========================================================================
DEEP_ALWAYS = {
    "id": "m",
    "maxIterations": 8,
    "initial": "p",
    "states": {
        "p": {
            "initial": "q",
            "on": {"E": {"actions": "named"}},
            "states": {
                "q": {"always": {"target": "q2", "actions": "al"}},
                "q2": {"always": {"target": "q", "actions": "al"}},
            },
        }
    },
}


@attack("S1", "SCXML 3.13: a spinning DEEPER `always` never consumes a "
              "SHALLOWER named event; same trip lap on both engines")
async def s1() -> Dict[str, Any]:
    out = {}
    for eng in ("async", "sync"):
        hits: List[str] = []
        logic = MachineLogic(actions={
            "named": lambda i, c, e, a: hits.append("named"),
            "al": lambda i, c, e, a: hits.append("always"),
        })
        m = create_machine(copy.deepcopy(DEEP_ALWAYS), logic=logic)
        if eng == "async":
            itp = await Interpreter(m).start()
            await itp.send("E")
            await asyncio.sleep(0.3)
            err = itp.last_error
            await itp.stop()
        else:
            itp = SyncInterpreter(m).start()
            itp.send("E", wait=True)
            err = itp.last_error
            itp.stop()
        out[eng] = {
            "named_fired": hits.count("named"),
            "always_laps": hits.count("always"),
            "err": type(err).__name__ if err else None,
        }
    return {
        "ok": (all(v["named_fired"] == 1 for v in out.values())
               and out["async"]["always_laps"] == out["sync"]["always_laps"]),
        "engines_agree_on_trip_lap":
            out["async"]["always_laps"] == out["sync"]["always_laps"],
        "runs": out,
    }


# ==========================================================================
# S2 -- engine-provenance forgery sweep (#195)
# ==========================================================================
FORGE_M = {
    "id": "oms",
    "strict": True,
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {"invoke": [
            {"src": "ping", "id": "ping", "onDone": {"actions": "grab"}},
            {"src": "fill", "id": "fill",
             "onDone": {"target": "settled", "actions": "book"}},
        ]},
        "settled": {},
    },
}


@attack("S2", "Engine-provenance forgery sweep: only the engine may mint a "
              "system event -- incl. `_replace` on a RECEIVED completion")
async def s2() -> Dict[str, Any]:
    import xstate_statemachine.events as E

    genuine = engine_done("done.invoke.q", 1, "q")
    surfaces = {
        "public_DoneEvent": is_system_event(DoneEvent("done.invoke.q", 1, "q")),
        "deepcopy_of_genuine(legit)": is_system_event(copy.deepcopy(genuine)),
        "pickle_of_genuine(legit)":
            is_system_event(pickle.loads(pickle.dumps(genuine))),
        "_replace_retype": is_system_event(
            genuine._replace(type="done.invoke.OTHER")),
        "private_import_path":
            is_system_event(E._EngineDone("done.invoke.q", "F", "q")),
        "type_of_held_instance":
            is_system_event(type(genuine)("done.invoke.q", "F", "q")),
    }
    ev = Event("X")
    object.__setattr__(ev, "_provenance", E._ENGINE_MARK)
    surfaces["Event_plus_ENGINE_MARK"] = is_system_event(ev)

    # End-to-end: does a re-typed completion drive a REAL onDone while the
    # genuine service is still outstanding?
    booked: List[Any] = []

    async def ping(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return "pong"

    async def fill(i, c, e):  # noqa: ANN001
        await asyncio.sleep(3.0)
        return {"qty": 100}

    def grab(i, c, e, a):  # noqa: ANN001
        i.send(e._replace(type="done.invoke.fill",
                          data={"qty": 999999}, src="fill"))

    def book(i, c, e, a):  # noqa: ANN001
        booked.append((e.type, e.data))

    logic = MachineLogic(actions={"grab": grab, "book": book},
                         services={"ping": ping, "fill": fill})
    itp = await Interpreter(
        create_machine(copy.deepcopy(FORGE_M), logic=logic)).start()
    await itp.send("GO")
    await asyncio.sleep(0.5)
    state = sorted(itp.current_state_ids)
    await itp.stop()

    forgeable = [k for k, v in surfaces.items()
                 if v and "legit" not in k and k != "public_DoneEvent"]
    return {
        "ok": not forgeable and not booked,
        "surfaces": surfaces,
        "FORGEABLE_SURFACES": forgeable,
        "end_to_end_state": state,
        "end_to_end_booked_while_fill_outstanding": booked,
    }


if __name__ == "__main__":
    main("s_semantics_sec")
