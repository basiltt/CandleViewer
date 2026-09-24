"""t1 (@19cb1f1) -- STANDALONE. #203 says an `after` transition matches only
an engine-minted `AfterEvent` (`_EngineAfter`). This probe asks whether
"engine-minted" is a checkable property or merely a TYPE anyone can
construct. Four vectors, both service kinds, both engines:

  V1 import path : xstate_statemachine.events._EngineAfter(...)
  V2 type(held)  : type(events.engine_after(...))(...)
  V3 pickle      : pickle round-trip of a genuine engine after
  V4 snapshot    : events.restore_event({"kind":"after", ..., "engine": true})

A 60-second `after` must NOT fire in the 0.2 s this probe runs.

Run: python t1_after_provenance_forgery.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import pickle
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine import events as EV


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


AFTER_TYPE = "after.60000.t1.wait"

CFG = {
    "id": "t1",
    "initial": "wait",
    "strict": True,
    "context": {"fired": 0},
    "states": {
        "wait": {"after": {60000: {"target": "late", "actions": ["boom"]}}},
        "late": {"type": "final"},
    },
}


def make_logic(rec: List[str]):
    def boom(i, ctx, e, ad):  # noqa: ANN001
        ctx["fired"] = ctx.get("fired", 0) + 1
        rec.append(type(e).__name__)

    return MachineLogic(actions={"boom": boom})


def forge(vector: str):
    if vector == "V1_import_path":
        return EV._EngineAfter(AFTER_TYPE)
    if vector == "V2_type_of_held":
        genuine = EV.engine_after(AFTER_TYPE)
        return type(genuine)(AFTER_TYPE)
    if vector == "V3_pickle":
        return pickle.loads(pickle.dumps(EV.engine_after(AFTER_TYPE)))
    if vector == "V4_snapshot_record":
        return EV.restore_event(
            {"kind": "after", "type": AFTER_TYPE, "engine": True}
        )
    if vector == "CONTROL_public_class":
        from xstate_statemachine import AfterEvent

        return AfterEvent(AFTER_TYPE)
    raise AssertionError(vector)


VECTORS = [
    "V1_import_path",
    "V2_type_of_held",
    "V3_pickle",
    "V4_snapshot_record",
    "CONTROL_public_class",
]


async def cell_async(vector: str) -> Dict[str, Any]:
    rec: List[str] = []
    itp = Interpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(rec)))
    await itp.start()
    row: Dict[str, Any] = {"engine": "async", "vector": vector}
    try:
        ev = forge(vector)
        row["forged_class"] = type(ev).__name__
        row["is_system_event"] = bool(EV.is_system_event(ev))
        await itp.send(ev)
        row["send"] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        row["send"] = f"refused:{type(exc).__name__}"
    await asyncio.sleep(0.2)
    row["state"] = sorted(itp.current_state_ids)
    row["action_ran"] = len(rec)
    await itp.stop()
    return row


def cell_sync(vector: str) -> Dict[str, Any]:
    rec: List[str] = []
    itp = SyncInterpreter(
        create_machine(copy.deepcopy(CFG), logic=make_logic(rec))
    )
    itp.start()
    row: Dict[str, Any] = {"engine": "sync", "vector": vector}
    try:
        ev = forge(vector)
        row["forged_class"] = type(ev).__name__
        row["is_system_event"] = bool(EV.is_system_event(ev))
        itp.send(ev)
        row["send"] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        row["send"] = f"refused:{type(exc).__name__}"
    row["state"] = sorted(itp.current_state_ids)
    row["action_ran"] = len(rec)
    itp.stop()
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for v in VECTORS:
        rows.append(await cell_async(v))
        rows.append(cell_sync(v))
    viol = [
        (r["engine"], r["vector"], r["state"])
        for r in rows
        if r["action_ran"] > 0 or "t1.late" in r["state"]
    ]
    emit(
        "t1_after_provenance_forgery",
        {
            "claim": "#203: only an engine-minted AfterEvent drives an `after`",
            "rows": rows,
            "violations": viol,
            "source": "events.py:579 `_EngineAfter` is a plain subclass; "
            "provenance == type identity, constructible by import path, "
            "type(held), pickle and events.py:414 restore_event('engine': true)",
            "result": "FAIL" if viol else "PASS",
        },
    )
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
