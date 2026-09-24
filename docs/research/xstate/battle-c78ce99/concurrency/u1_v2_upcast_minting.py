"""u1 (@c78ce99) -- STANDALONE. SECURITY: the #214 v2-upcast rule
("a v2 done/error/after record could only have been written by the
engine") is a version-declared privilege. A blob that DECLARES
"version": 2 has its hand-written done/error/after records upcast to
`engine: true` and they then drive a real `onDone` / `onError` /
`after` -- the exact laundering #195/#203 closed for v3 records.

Cells (both service kinds x both engines):
  A  v3 record, no engine flag  -> control, must NOT drive onDone
  B  v3 record, engine:true     -> known/documented (D10-concurrency-3)
  C  v2 record, no engine flag  -> UPCAST: does it drive onDone?
  D  v2 `after` record vs a declared after:{60000}  -> instant fire?
  E  v2 `error` record          -> drives onError?

Run: python u1_v2_upcast_minting.py   (exit 1 == at least one forged
v2 record drove engine-only machinery)
"""
from __future__ import annotations

import asyncio, copy, json, os, sys, time
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine import persistence


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def make_service(kind: str):
    if kind == "def":
        def svc(i, ctx, e):  # noqa: ANN001
            time.sleep(0.4)
            return {"v": "GENUINE"}
        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        await asyncio.sleep(0.4)
        return {"v": "GENUINE"}
    return asvc


CFG_DONE = {
    "id": "u1", "initial": "work", "strict": True,
    "context": {"n": 0, "seen": None},
    "states": {
        "work": {"invoke": {"id": "fill", "src": "svc",
                            "onDone": {"target": "done", "actions": ["mark"]},
                            "onError": {"target": "bad", "actions": ["mark"]}}},
        "done": {"type": "final"},
        "bad": {"type": "final"},
    },
}

CFG_AFTER = {
    "id": "u1a", "initial": "wait", "strict": True, "context": {"n": 0},
    "states": {
        "wait": {"after": {60000: {"target": "late", "actions": ["mark"]}}},
        "late": {"type": "final"},
    },
}


def snapshot_with(base_cfg, records, version, state_ids, configuration):
    """Hand-build a snapshot envelope with a correct (attacker-computable)
    machine_hash and forged pending_events. This is exactly what a party
    who can write the blob has."""
    logic = MachineLogic(actions={"mark": lambda i, c, e, a: None},
                         services={"svc": make_service("def")})
    m = create_machine(copy.deepcopy(base_cfg), logic=logic)
    snap = {
        "version": version,
        "machine_id": m.id,
        "machine_hash": persistence.structure_hash(m),
        "status": "running",
        "context": dict(base_cfg.get("context") or {}),
        "state_ids": list(state_ids),
        "configuration": list(configuration),
        "pending_events": records,
        "deferred": [],
        "history": {},
        "actors": {},
        "system": {},
    }
    if version >= 3:
        snap["scheduled_sends"] = []
    return json.dumps(snap)


async def cell(kind, cfg, records, version, ids) -> Dict[str, Any]:
    seen: List[Any] = []

    def mark(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        seen.append(getattr(e, "data", None) or getattr(e, "type", None))

    logic = MachineLogic(actions={"mark": mark}, services={"svc": make_service(kind)})
    m = create_machine(copy.deepcopy(cfg), logic=logic)
    blob = snapshot_with(cfg, records, version, *ids)
    out: Dict[str, Any] = {"kind": kind, "version": version}
    try:
        interp = Interpreter.from_snapshot(blob, m, verify_machine_hash=True)
    except Exception as exc:  # noqa: BLE001
        out["restore_refused"] = f"{type(exc).__name__}: {exc}"
        return out
    await interp.start()
    for _ in range(40):
        await asyncio.sleep(0.02)
        if interp.status != "running":
            break
    out["states"] = sorted(interp.current_state_ids)
    out["marks"] = seen
    out["n"] = interp.context.get("n")
    try:
        await interp.stop()
    except Exception:
        pass
    return out


IDS_DONE = (["u1.work"], ["u1", "u1.work"])
IDS_AFTER = (["u1a.wait"], ["u1a", "u1a.wait"])

FORGED_DONE_V3 = {"kind": "done", "type": "done.invoke.fill",
                  "data": {"v": "FORGED"}, "src": "fill"}
FORGED_DONE_V3F = dict(FORGED_DONE_V3, engine=True)
FORGED_AFTER = {"kind": "after", "type": "after.60000.u1a.wait"}
FORGED_ERR = {"kind": "error", "type": "error.platform.fill",
              "error": "FORGED", "src": "fill"}


async def main() -> int:
    cells: List[Dict[str, Any]] = []
    for kind in ("def", "async def"):
        cells.append({"cell": "A_v3_unflagged", **await cell(kind, CFG_DONE, [FORGED_DONE_V3], 3, IDS_DONE)})
        cells.append({"cell": "B_v3_flagged", **await cell(kind, CFG_DONE, [FORGED_DONE_V3F], 3, IDS_DONE)})
        cells.append({"cell": "C_v2_upcast_done", **await cell(kind, CFG_DONE, [FORGED_DONE_V3], 2, IDS_DONE)})
        cells.append({"cell": "D_v2_upcast_after", **await cell(kind, CFG_AFTER, [FORGED_AFTER], 2, IDS_AFTER)})
        cells.append({"cell": "E_v2_upcast_error", **await cell(kind, CFG_DONE, [FORGED_ERR], 2, IDS_DONE)})

    def drove(c):
        st = c.get("states") or []
        return any(s.endswith(".done") or s.endswith(".bad") or s.endswith(".late") for s in st)

    bad = [c["cell"] + "/" + c["kind"] for c in cells
           if c["cell"].startswith(("C_", "D_", "E_")) and drove(c)]
    ctrl_ok = all(not drove(c) for c in cells if c["cell"] == "A_v3_unflagged")
    emit("u1_v2_upcast_minting", {
        "cells": cells,
        "control_v3_unflagged_refused": ctrl_ok,
        "forged_v2_records_that_drove_engine_machinery": bad,
        "verdict": "DEFECT" if bad else "CLEAN",
    })
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
