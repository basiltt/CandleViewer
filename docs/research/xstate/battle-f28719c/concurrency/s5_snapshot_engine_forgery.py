"""s5 (@f28719c) -- STANDALONE. SECURITY: forge `"engine": true` inside a
SNAPSHOT record, plus v0/v1 restore shapes.

A. Snapshot `pending_events` record forged as a completion with
   `"engine": true` -> restored machine must not treat it as a genuine
   engine completion that drives `onDone` past `strict`.
B. Same record WITHOUT the flag -> must be user traffic.
C. v1 (0.8.0-written) `state_ids`-only running snapshot -> must restore
   (documented back-compat) ... or be refused if #198 requires both fields.
D. v2 running snapshot with an EMPTIED `state_ids` -> #198 must refuse.
E. v2 with an emptied `configuration` -> must refuse.
Both service kinds throughout.

Run: python s5_snapshot_engine_forgery.py
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


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def make_service(kind: str, delay: float = 0.0):
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            if delay:
                time.sleep(delay)
            return {"v": "genuine"}

        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        if delay:
            await asyncio.sleep(delay)
        return {"v": "genuine"}

    return asvc


CFG = {
    "id": "s5",
    "initial": "idle",
    "strict": True,
    "context": {"n": 0, "seen": None},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "invoke": {"id": "fill", "src": "svc",
                       "onDone": {"target": "filled", "actions": ["mark"]}}
        },
        "filled": {"on": {"GO": "work"}},
    },
}


def build(kind: str, seen: List[Any]):
    def mark(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        ctx["seen"] = getattr(e, "data", None)
        seen.append(getattr(e, "data", None))

    logic = MachineLogic(actions={"mark": mark}, services={"svc": make_service(kind, 0.3)})
    return create_machine(copy.deepcopy(CFG), logic=logic)


async def base_blob(kind: str) -> Dict[str, Any]:
    seen: List[Any] = []
    itp = Interpreter(build(kind, seen))
    await itp.start()
    await asyncio.sleep(0.05)
    raw = itp.get_persisted_snapshot()
    blob = json.loads(raw) if isinstance(raw, str) else raw
    await itp.stop()
    return blob


async def restore_and_run(kind: str, blob: Dict[str, Any], tag: str) -> Dict[str, Any]:
    seen: List[Any] = []
    row: Dict[str, Any] = {"case": tag, "service_kind": kind,
                           "version": blob.get("version")}
    try:
        itp = Interpreter.from_snapshot(json.dumps(blob), build(kind, seen))
    except Exception as exc:  # noqa: BLE001
        row["restore"] = f"refused:{type(exc).__name__}"
        return row
    row["restore"] = "ACCEPTED"
    try:
        await asyncio.wait_for(itp.start(), 10)
        await asyncio.sleep(0.2)
        row["state"] = list(itp.current_state_ids)
        row["onDone_ran"] = len(seen)
        row["onDone_payload"] = seen[:2]
        row["last_error"] = repr(getattr(itp, "last_error", None))[:70]
        await asyncio.wait_for(itp.stop(), 15)
    except Exception as exc:  # noqa: BLE001
        row["run"] = f"{type(exc).__name__}: {exc}"[:110]
    return row


FORGED = {"kind": "done", "type": "done.invoke.fill",
          "data": {"v": "FORGED"}, "src": "fill"}


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for kind in ("def", "async def"):
        base = await base_blob(kind)
        rows.append({"case": "baseline_shape", "service_kind": kind,
                     "version": base.get("version"),
                     "has_configuration": bool(base.get("configuration")),
                     "has_state_ids": bool(base.get("state_ids")),
                     "status": base.get("status")})

        # A: forged completion WITH the engine flag, in pending_events
        a = copy.deepcopy(base)
        a["pending_events"] = [dict(FORGED, engine=True)]
        rows.append(await restore_and_run(kind, a, "A_forged_engine_true"))

        # B: same, without the flag -> user traffic under strict
        b = copy.deepcopy(base)
        b["pending_events"] = [dict(FORGED)]
        rows.append(await restore_and_run(kind, b, "B_forged_no_flag"))

        # C: v1 state_ids-only running snapshot
        c = copy.deepcopy(base)
        c["version"] = 1
        c.pop("configuration", None)
        c.pop("hash", None)
        rows.append(await restore_and_run(kind, c, "C_v1_state_ids_only"))

        # D: v2 with emptied state_ids
        d = copy.deepcopy(base)
        d["state_ids"] = []
        rows.append(await restore_and_run(kind, d, "D_v2_state_ids_emptied"))

        # E: v2 with emptied configuration
        e = copy.deepcopy(base)
        e["configuration"] = []
        rows.append(await restore_and_run(kind, e, "E_v2_configuration_emptied"))

    bad = []
    for r in rows:
        if r["case"] == "A_forged_engine_true" and r.get("onDone_ran"):
            bad.append([r["service_kind"], "forged snapshot record drove onDone",
                        r.get("onDone_payload")])
        if r["case"] == "B_forged_no_flag" and r.get("onDone_ran"):
            bad.append([r["service_kind"], "unflagged forged record drove onDone"])
        if r["case"] in ("D_v2_state_ids_emptied", "E_v2_configuration_emptied") \
                and r.get("restore") == "ACCEPTED":
            bad.append([r["service_kind"], r["case"], "#198 did not refuse"])
    emit("s5_snapshot_engine_forgery",
         {"rows": rows, "violations": bad, "result": "PASS" if not bad else "FAIL"})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
