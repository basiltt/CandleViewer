"""t2 (@19cb1f1) -- STANDALONE. #204 / SCXML 6.1 `statesToInvoke`:
a state entered AND exited within one macrostep must never submit its
service; a state entered and still active when the macrostep settles must
submit it EXACTLY ONCE.

Matrix (x {def, async def} x {async engine, sync engine}):
  M1 roll_forward  -- `always` carries the machine straight out of the
                      invoking state          -> submitted 0
  M2 stay          -- plain entry, no always  -> submitted 1
  M3 parallel      -- invoking region entered alongside a sibling that
                      reaches `final`         -> submitted 1 (region stays)
  M4 rollback      -- entry action raises under actionErrorPolicy
                      "rollback"              -> submitted 0

Run: python t2_states_to_invoke_matrix.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


INV = {"id": "svc1", "src": "svc", "onDone": {"target": "#t2.settled"}}

SHAPES: Dict[str, Dict[str, Any]] = {
    "M1_roll_forward": {
        "expect": 0,
        "cfg": {
            "id": "t2", "initial": "idle", "context": {},
            "states": {
                "idle": {"on": {"GO": "work"}},
                "work": {"invoke": dict(INV), "always": {"target": "past"}},
                "past": {}, "settled": {},
            },
        },
    },
    "M2_stay": {
        "expect": 1,
        "cfg": {
            "id": "t2", "initial": "idle", "context": {},
            "states": {
                "idle": {"on": {"GO": "work"}},
                "work": {"invoke": dict(INV)},
                "settled": {},
            },
        },
    },
    "M3_parallel_sibling_final": {
        "expect": 1,
        "cfg": {
            "id": "t2", "initial": "idle", "context": {},
            "states": {
                "idle": {"on": {"GO": "par"}},
                "par": {
                    "type": "parallel",
                    "states": {
                        "a": {"initial": "run",
                              "states": {"run": {"invoke": dict(INV)}}},
                        "b": {"initial": "s",
                              "states": {"s": {"always": {"target": "f"}},
                                         "f": {"type": "final"}}},
                    },
                },
                "settled": {},
            },
        },
    },
    "M4_rollback": {
        "expect": 0,
        "cfg": {
            "id": "t2", "initial": "idle", "actionErrorPolicy": "rollback",
            "context": {},
            "states": {
                "idle": {"on": {"GO": "work"}},
                "work": {"entry": ["boom"], "invoke": dict(INV)},
                "settled": {},
            },
        },
    },
}


def build(kind: str, submitted: List[str]):
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            submitted.append("x")
            time.sleep(0.02)
            return {"ok": True}

    else:

        async def svc(i, ctx, e):  # noqa: ANN001
            submitted.append("x")
            await asyncio.sleep(0.02)
            return {"ok": True}

    def boom(i, ctx, e, ad):  # noqa: ANN001
        raise RuntimeError("entry blew up")

    return MachineLogic(actions={"boom": boom}, services={"svc": svc})


async def run_async(name: str, kind: str) -> Dict[str, Any]:
    sub: List[str] = []
    cfg = copy.deepcopy(SHAPES[name]["cfg"])
    itp = Interpreter(create_machine(cfg, logic=build(kind, sub)))
    row = {"engine": "async", "shape": name, "kind": kind,
           "expect": SHAPES[name]["expect"]}
    try:
        await itp.start()
        await itp.send("GO")
        await asyncio.sleep(0.35)
        row["state"] = sorted(itp.current_state_ids)
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await itp.stop()
        except Exception:  # noqa: BLE001
            pass
    row["submitted"] = len(sub)
    return row


def run_sync(name: str, kind: str) -> Dict[str, Any]:
    sub: List[str] = []
    cfg = copy.deepcopy(SHAPES[name]["cfg"])
    itp = SyncInterpreter(create_machine(cfg, logic=build(kind, sub)))
    row = {"engine": "sync", "shape": name, "kind": kind,
           "expect": SHAPES[name]["expect"]}
    try:
        itp.start()
        itp.send("GO")
        row["state"] = sorted(itp.current_state_ids)
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            itp.stop()
        except Exception:  # noqa: BLE001
            pass
    row["submitted"] = len(sub)
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for name in SHAPES:
        for kind in ("def", "async def"):
            rows.append(await run_async(name, kind))
            rows.append(run_sync(name, kind))
    viol = [
        (r["engine"], r["shape"], r["kind"], r["submitted"], r["expect"])
        for r in rows
        if r["submitted"] != r["expect"]
    ]
    gaps: List[Any] = []
    for name in SHAPES:
        for kind in ("def", "async def"):
            a = [r for r in rows if r["engine"] == "async"
                 and r["shape"] == name and r["kind"] == kind][0]
            s = [r for r in rows if r["engine"] == "sync"
                 and r["shape"] == name and r["kind"] == kind][0]
            if a["submitted"] != s["submitted"]:
                gaps.append((name, kind, a["submitted"], s["submitted"]))
    emit("t2_states_to_invoke_matrix",
         {"claim": "#204 SCXML 6.1: entered+exited in one macrostep never "
                   "submits; still-active submits exactly once",
          "rows": rows, "violations": viol, "engine_parity_gaps": gaps,
          "result": "FAIL" if (viol or gaps) else "PASS"})
    return 1 if (viol or gaps) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
