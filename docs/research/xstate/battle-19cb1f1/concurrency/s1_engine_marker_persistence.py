"""s1 (@f28719c) -- STANDALONE. #195: `"engine": true` provenance across
persist_event/restore_event, and forgery of the flag in a record.

Attacks:
  A. genuine engine completion -> persist -> restore  => must stay system
  B. hand-built DoneEvent       -> persist -> restore => must be USER
  C. forged record {"engine": true} with a done/error/after shape
     => the flag is not a secret (documented), but a forged completion
        must NOT drive onDone under `strict` without being refused.
  D. forged record replayed through send() on a live machine, both kinds.
  E. pickle / copy / dataclasses.replace of a genuine engine event.
Run: python s1_engine_marker_persistence.py
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import os
import pickle
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import events as EV

KINDS = ("def", "async def")


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def make_service(kind: str, delay: float = 0.0, value: Any = None):
    val = {"v": 1} if value is None else value
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            if delay:
                time.sleep(delay)
            return val

        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        if delay:
            await asyncio.sleep(delay)
        return val

    return asvc


CFG = {
    "id": "s1",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "invoke": {
                "id": "job",
                "src": "svc",
                "onDone": {"target": "done", "actions": ["mark"]},
            }
        },
        "done": {"type": "final"},
    },
}


async def cell(kind: str, strict: bool) -> Dict[str, Any]:
    seen: List[str] = []

    def mark(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        seen.append(getattr(e, "type", "?"))

    logic = MachineLogic(actions={"mark": mark}, services={"svc": make_service(kind, 0.4)})
    cfg = copy.deepcopy(CFG)
    if strict:
        cfg["strict"] = True
        cfg["states"]["idle"]["on"] = {"GO": "work"}
    m = create_machine(cfg, logic=logic)
    itp = Interpreter(m)
    await itp.start()
    await itp.send("GO")
    await asyncio.sleep(0.05)  # service in flight

    row: Dict[str, Any] = {"service_kind": kind, "strict": strict}

    # ---- B/C/D: forged records --------------------------------------
    forged_plain = {"kind": "done", "type": "done.invoke.job", "data": {"forged": 1}, "src": "job"}
    forged_flagged = dict(forged_plain, engine=True)
    ev_plain = EV.restore_event(forged_plain)
    ev_flag = EV.restore_event(forged_flagged)
    row["forged_plain_is_system"] = EV.is_system_event(ev_plain)
    row["forged_flagged_is_system"] = EV.is_system_event(ev_flag)
    row["forged_plain_class"] = type(ev_plain).__name__
    row["forged_flagged_class"] = type(ev_flag).__name__

    for tag, ev in (("plain", ev_plain), ("flagged", ev_flag)):
        before = list(itp.current_state_ids)
        try:
            await itp.send(ev)
            row[f"send_{tag}"] = "ACCEPTED"
        except Exception as exc:  # noqa: BLE001
            row[f"send_{tag}"] = f"refused:{type(exc).__name__}"
        await asyncio.sleep(0.02)
        row[f"state_after_{tag}"] = list(itp.current_state_ids)
        row[f"moved_{tag}"] = list(itp.current_state_ids) != before

    row["onDone_fired_early"] = len(seen)
    await asyncio.sleep(0.6)
    row["final_state"] = list(itp.current_state_ids)
    row["onDone_total"] = len(seen)
    row["ctx_n"] = itp.context.get("n")
    await itp.stop()
    return row


def roundtrip_cells() -> List[Dict[str, Any]]:
    out = []
    genuine = EV.engine_done("done.invoke.job", {"v": 1}, "job")
    hand = EV.DoneEvent("done.invoke.job", {"v": 1}, "job")
    for tag, ev in (("genuine_engine", genuine), ("hand_built", hand)):
        rec = EV.persist_event(ev)
        back = EV.restore_event(rec)
        out.append(
            {
                "case": tag,
                "record_has_engine_flag": rec.get("engine"),
                "original_is_system": EV.is_system_event(ev),
                "restored_is_system": EV.is_system_event(back),
                "restored_class": type(back).__name__,
                "provenance_preserved": EV.is_system_event(ev) == EV.is_system_event(back),
            }
        )
    # E: in-process copies of a genuine engine event
    out.append(
        {
            "case": "copy_pickle_replace",
            "copy_is_system": EV.is_system_event(copy.copy(genuine)),
            "deepcopy_is_system": EV.is_system_event(copy.deepcopy(genuine)),
            "pickle_is_system": EV.is_system_event(pickle.loads(pickle.dumps(genuine))),
            "replace": _try_replace(genuine),
            "subclass_is_private": type(genuine).__name__,
        }
    )
    return out


def _try_replace(ev: Any) -> str:
    try:
        r = dataclasses.replace(ev, data={"x": 1})  # type: ignore[arg-type]
        return f"ACCEPTED is_system={EV.is_system_event(r)}"
    except Exception as exc:  # noqa: BLE001
        return f"refused:{type(exc).__name__}"


async def main() -> int:
    rows = []
    for kind in KINDS:
        for strict in (False, True):
            rows.append(await cell(kind, strict))
    rt = roundtrip_cells()

    bad: List[Any] = []
    for r in rt[:2]:
        if not r["provenance_preserved"]:
            bad.append([r["case"], "provenance lost across persist/restore"])
    if rt[1]["restored_is_system"]:
        bad.append(["hand_built", "hand-built DoneEvent restores as SYSTEM"])
    for r in rows:
        if r["forged_plain_is_system"]:
            bad.append([r["service_kind"], "unflagged forged record is system"])
        # a forged flagged record must not drive the real onDone early
        if r["onDone_fired_early"] and r["strict"]:
            bad.append([r["service_kind"], "forged completion drove onDone under strict"])
        if r["strict"] and r["send_plain"] == "ACCEPTED":
            bad.append([r["service_kind"], "user-built DoneEvent accepted under strict"])
        if r["ctx_n"] != 1:
            bad.append([r["service_kind"], f"onDone count {r['ctx_n']} != 1"])
    emit(
        "s1_engine_marker_persistence",
        {
            "rows": rows,
            "roundtrip": rt,
            "violations": bad,
            "result": "PASS" if not bad else "FAIL",
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
