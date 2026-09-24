"""t4 (@19cb1f1) -- STANDALONE. #204 arms the invokes of states recorded
at entry and still active when the macrostep settles. This probe asks what
happens when the state that must be re-armed is the one the machine is
ALREADY in: `onDone` targeting the invoking state itself.

  SELF   work --invoke spin--> onDone target "work"
  HOP    work --invoke spin--> onDone target "hop" --always--> "work"

Semantically identical loops. SCXML 3.12: a transition with a target
exits and re-enters its source, so both must re-invoke and both must be
bounded by `maxIterations`.

Observed: HOP re-invokes and trips the chain budget; SELF runs the entry
actions once, submits the service ONCE, never re-enters, and parks with
`has_dormant_invocations == True`, no `on_invocation_stranded`, no
`last_error` -- the exact "wedged and indistinguishable from a slow
service" state #207 was opened to make observable.

Control CLEAN: a normal `onDone -> different state` machine must end
`dormant == False`.

Run: python t4_self_target_ondone_never_rearms.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


LIMIT = 20

SELF = {
    "id": "m", "initial": "idle", "maxIterations": LIMIT, "context": {},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"entry": ["ent"],
                 "invoke": {"id": "spin", "src": "svc",
                            "onDone": {"target": "work"}}},
    },
}
HOP = {
    "id": "m", "initial": "idle", "maxIterations": LIMIT, "context": {},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"entry": ["ent"],
                 "invoke": {"id": "spin", "src": "svc",
                            "onDone": {"target": "hop"}}},
        "hop": {"always": {"target": "work"}},
    },
}
CLEAN = {
    "id": "m", "initial": "idle", "maxIterations": LIMIT, "context": {},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"entry": ["ent"],
                 "invoke": {"id": "spin", "src": "svc",
                            "onDone": {"target": "rest"}}},
        "rest": {},
    },
}

SHAPES = {"SELF": SELF, "HOP": HOP, "CLEAN_control": CLEAN}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.stranded: List[Any] = []

    def on_invocation_stranded(self, itp, state_id, invoke_id, error):  # noqa: ANN001
        self.stranded.append([state_id, invoke_id])


def build(kind: str, sub: List[int], ent: List[int]) -> MachineLogic:
    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            sub[0] += 1
            return {"ok": 1}

    else:

        async def svc(i, c, e):  # noqa: ANN001
            sub[0] += 1
            return {"ok": 1}

    def ent_a(i, c, e, a):  # noqa: ANN001
        ent[0] += 1

    return MachineLogic(actions={"ent": ent_a}, services={"svc": svc})


def finish(row, itp, spy, sub, ent) -> Dict[str, Any]:
    row["entries"] = ent[0]
    row["submits"] = sub[0]
    row["state"] = sorted(itp.current_state_ids)
    row["dormant"] = bool(itp.has_dormant_invocations)
    row["last_error"] = type(getattr(itp, "last_error", None)).__name__
    row["hook_stranded"] = spy.stranded
    return row


async def cell_async(name: str, kind: str) -> Dict[str, Any]:
    sub, ent, spy = [0], [0], Spy()
    itp = Interpreter(
        create_machine(copy.deepcopy(SHAPES[name]), logic=build(kind, sub, ent))
    )
    itp.use(spy)
    row = {"engine": "async", "shape": name, "kind": kind}
    await itp.start()
    await itp.send("GO")
    await asyncio.sleep(1.0)
    finish(row, itp, spy, sub, ent)
    await itp.stop()
    return row


def cell_sync(name: str, kind: str) -> Dict[str, Any]:
    sub, ent, spy = [0], [0], Spy()
    itp = SyncInterpreter(
        create_machine(copy.deepcopy(SHAPES[name]), logic=build(kind, sub, ent))
    )
    itp.use(spy)
    row = {"engine": "sync", "shape": name, "kind": kind}
    try:
        itp.start()
        itp.send("GO")
        finish(row, itp, spy, sub, ent)
    except Exception as exc:  # noqa: BLE001
        row["error"] = type(exc).__name__
    finally:
        try:
            itp.stop()
        except Exception:  # noqa: BLE001
            pass
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for name in SHAPES:
        for kind in ("def", "async def"):
            rows.append(await cell_async(name, kind))
            rows.append(cell_sync(name, kind))

    viol: List[Any] = []
    for r in rows:
        if "error" in r:
            continue  # sync + async def == documented NotSupportedError
        if r["shape"] == "SELF":
            if r["submits"] <= 1:
                viol.append((r["engine"], r["kind"],
                             "self-target onDone never re-armed the invoke",
                             r["submits"], r["entries"]))
            if r["dormant"] and not r["hook_stranded"]:
                viol.append((r["engine"], r["kind"],
                             "parked dormant with no stranded hook and "
                             "no last_error", r["last_error"]))
        if r["shape"] == "CLEAN_control" and r["dormant"]:
            viol.append((r["engine"], r["kind"],
                         "control machine reported dormant"))

    emit("t4_self_target_ondone_never_rearms",
         {"claim": "SCXML 3.12: an onDone with a target exits and re-enters "
                   "its source, so SELF and HOP are the same loop",
          "limit": LIMIT, "rows": rows, "violations": viol,
          "source": "base_interpreter.py:4952 `_states_to_invoke.append` is "
                    "reached only from state ENTRY; a self-targeting "
                    "transition that never exits the state therefore never "
                    "re-records it, and _arm_pending_invokes (4958) has "
                    "nothing to arm",
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
