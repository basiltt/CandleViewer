"""s6 (@f28719c) -- STANDALONE MINIMAL. #195 boundary: `restore_event`
mints a TRUSTED engine completion from any dict carrying "engine": true,
and that event, sent in-process through the PUBLIC `send()` API, drives a
real `onDone` -- bypassing `strict` -- while the genuine service is still
running.

The public route is `xstate_statemachine.is_system_event` + the
documented persistence helpers. This probe reaches `restore_event`
through `xstate_statemachine.events`, which is a public module (no
leading underscore) re-exported by the package.

Control: the SAME record without the flag is refused under `strict`.

Run: python s6_restore_event_forgery_minimal.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import events as EV


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def make_service(kind: str):
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            time.sleep(0.6)
            return {"v": "GENUINE"}

        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        await asyncio.sleep(0.6)
        return {"v": "GENUINE"}

    return asvc


CFG = {
    "id": "s6",
    "initial": "idle",
    "strict": True,
    "context": {"n": 0, "seen": None},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"invoke": {"id": "fill", "src": "svc",
                            "onDone": {"target": "done", "actions": ["mark"]}}},
        "done": {"type": "final"},
    },
}

FORGED = {"kind": "done", "type": "done.invoke.fill",
          "data": {"v": "FORGED"}, "src": "fill"}


async def cell(kind: str, flag: bool) -> Dict[str, Any]:
    seen: List[Any] = []

    def mark(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        ctx["seen"] = getattr(e, "data", None)
        seen.append(getattr(e, "data", None))

    logic = MachineLogic(actions={"mark": mark}, services={"svc": make_service(kind)})
    itp = Interpreter(create_machine(copy.deepcopy(CFG), logic=logic))
    await itp.start()
    await itp.send("GO")
    await asyncio.sleep(0.05)          # genuine service IN FLIGHT

    rec = dict(FORGED, engine=True) if flag else dict(FORGED)
    ev = EV.restore_event(rec)
    row: Dict[str, Any] = {
        "service_kind": kind,
        "record_engine_flag": flag,
        "restored_class": type(ev).__name__,
        "is_system_event": EV.is_system_event(ev),
        "state_before": list(itp.current_state_ids),
    }
    try:
        await itp.send(ev)
        row["send"] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        row["send"] = f"refused:{type(exc).__name__}"
    await asyncio.sleep(0.05)
    row["state_after"] = list(itp.current_state_ids)
    row["onDone_ran_while_service_in_flight"] = len(seen)
    row["payload_applied"] = seen[0] if seen else None
    await asyncio.sleep(0.8)           # let the genuine service land
    row["onDone_total"] = len(seen)
    row["final_state"] = list(itp.current_state_ids)
    row["ctx_seen"] = itp.context.get("seen")
    await itp.stop()
    return row


async def main() -> int:
    rows = []
    for kind in ("def", "async def"):
        for flag in (True, False):
            rows.append(await cell(kind, flag))
    bad = []
    for r in rows:
        if r["record_engine_flag"] and r["onDone_ran_while_service_in_flight"]:
            bad.append([r["service_kind"],
                        "forged engine:true record drove onDone past strict",
                        r["payload_applied"]])
        if not r["record_engine_flag"] and r["send"] == "ACCEPTED":
            bad.append([r["service_kind"], "unflagged DoneEvent accepted under strict"])
    emit("s6_restore_event_forgery_minimal",
         {"rows": rows, "violations": bad,
          "source": "events.py:414 `trusted = record.get('engine') is True` -> "
                    "engine_done(); events.py:283 is_system_event trusts the "
                    "minted subclass; no check that the record came from a "
                    "genuine snapshot round-trip",
          "result": "PASS" if not bad else "FAIL"})
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
