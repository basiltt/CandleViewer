"""N5b - minimal repros distilled from n5's 5,000-mutation fuzz.

Two distinct defects fall out of N5 part A:

  R1  `from_snapshot` leaks RAW TypeError / ValueError / AttributeError for
      structurally-malformed snapshots (906/5,000 cases). #110 promises
      `SnapshotCorruptError` for malformed snapshots.
  R2  deleting certain keys produces a SILENT restore whose configuration is
      EMPTY and whose status is "running" -- the exact shape #102 was
      written to make impossible, arriving through the corrupt-snapshot door
      instead of the mid-step door (29/5,000 cases).

This script reproduces one concrete case of each, deterministically.
"""

from __future__ import annotations

import asyncio
import json

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    XStateMachineError,
)

CFG = {
    "id": "fz",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"GO": {"target": "a"}}, "after": {500: {"target": "a"}}},
    },
}


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


async def good_snapshot() -> dict:
    live = Interpreter(mk())
    await live.start()
    await asyncio.wait_for(live.send("GO", wait=True), 5)
    s = live.get_persisted_snapshot()
    await live.stop()
    return s


def try_restore(snap) -> dict:
    blob = json.dumps(snap)
    try:
        i = Interpreter.from_snapshot(blob, mk())
    except SnapshotCorruptError as exc:
        return {"outcome": "SnapshotCorruptError", "msg": str(exc)[:80]}
    except XStateMachineError as exc:
        return {"outcome": f"named:{type(exc).__name__}", "msg": str(exc)[:80]}
    except Exception as exc:  # noqa: BLE001
        return {"outcome": f"RAW {type(exc).__name__}", "msg": str(exc)[:120]}
    return {
        "outcome": "RESTORED",
        "state_ids": sorted(i.current_state_ids),
        "status": i.status,
        "context": dict(i.context),
    }


async def main() -> int:
    good = await good_snapshot()
    print("good snapshot keys:", sorted(good))

    cases = {}

    # ---- R1 family: retype a top-level scalar ----
    for key in sorted(good):
        for junk in (None, 7, [], {}, "junk"):
            s = json.loads(json.dumps(good))
            s[key] = junk
            r = try_restore(s)
            if r["outcome"].startswith("RAW"):
                cases.setdefault("R1_raw_exception", []).append(
                    {"key": key, "value": junk, **r}
                )

    # ---- R1/R2 family: delete a top-level key ----
    for key in sorted(good):
        s = json.loads(json.dumps(good))
        del s[key]
        r = try_restore(s)
        if r["outcome"].startswith("RAW"):
            cases.setdefault("R1_raw_exception_on_delete", []).append(
                {"deleted": key, **r}
            )
        elif r["outcome"] == "RESTORED" and not r["state_ids"]:
            cases.setdefault("R2_silent_empty_config", []).append(
                {"deleted": key, **r}
            )

    # ---- R2: drop a leaf from `configuration` (ancestors survive) ----
    r2_live = None
    s = json.loads(json.dumps(good))
    print("configuration:", s["configuration"], "state_ids:", s["state_ids"])
    del s["configuration"][1]          # leaves ["fz"] -- root only, no leaf
    r2 = try_restore(s)
    if r2["outcome"] == "RESTORED" and not r2["state_ids"]:
        cases["R2_silent_empty_config"] = [r2]
        interp = Interpreter.from_snapshot(json.dumps(s), mk())
        await interp.start()
        rec = await asyncio.wait_for(interp.send("GO", wait=True), 5)
        r2_live = {
            "mutation": "del snapshot['configuration'][1] (drop the leaf)",
            "after_start_state_ids": sorted(interp.current_state_ids),
            "status": interp.status,
            "is_running": getattr(interp, "is_running", None),
            "GO_receipt_changed": rec.changed,
            "GO_receipt_error": repr(rec.error),
            "context": dict(interp.context),
        }
        await interp.stop()

    ok = not cases
    emit("n5b_snapshot_corrupt_minimal", {
        "good_snapshot_keys": sorted(good),
        "raw_exception_cases": cases.get("R1_raw_exception", [])[:8],
        "raw_exception_case_count": len(cases.get("R1_raw_exception", [])),
        "raw_on_delete": cases.get("R1_raw_exception_on_delete", []),
        "silent_empty_config": cases.get("R2_silent_empty_config", []),
        "r2_driven_live": r2_live,
        "result": "PASS" if ok else "FAIL",
    })
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
