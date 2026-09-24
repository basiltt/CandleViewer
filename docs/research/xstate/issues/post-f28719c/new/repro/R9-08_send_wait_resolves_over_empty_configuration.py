"""Verify #197 on f28719c: `await send(EV, wait=True)` never resolves
ok=True/err=None over an empty configuration (current_state_ids == []);
if that instant occurs, get_persisted_snapshot() must agree it's mid-step.

Matrix: {def, async def} service x {Interpreter, SyncInterpreter} (SyncInterpreter
is synchronous by construction -- send() cannot return while mid-step, so the
sync cells assert current_state_ids is never observed empty at all).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError, SnapshotCorruptError

FAIL: list[str] = []
ROWS: list[dict] = []

CFG = {
    "id": "m197", "initial": "a", "maxIterations": 38,
    "after": {"17": {"target": "#m197.a.c"}},
    "states": {"a": {
        "initial": "a", "always": {"target": "#m197.a.a.a"},
        "states": {
            "a": {"initial": "a", "invoke": {"id": "inv", "src": "svc"},
                  "states": {"a": {"type": "final"}}},
            "c": {},
        },
    }},
}


async def async_svc(i, c, e):
    return {"ok": 1}


def def_svc(i, c, e):
    return {"ok": 1}


def mk(svc):
    return create_machine(copy.deepcopy(CFG), logic=MachineLogic(services={"svc": svc}))


def snap(it) -> str:
    try:
        it.get_persisted_snapshot()
        return "PRODUCED"
    except (SnapshotMidStepError, SnapshotCorruptError) as e:
        return f"REFUSED:{type(e).__name__}"


async def async_cell(kind: str, laps: int = 25):
    svc = def_svc if kind == "def" else async_svc
    bad = None
    empty_hits = 0
    for _lap in range(laps):
        it = Interpreter(mk(svc))
        await asyncio.wait_for(it.start(), 10)
        for ev in ("GO", "GO", "PING", "NOPE"):
            try:
                await asyncio.wait_for(it.send(ev, wait=True), 8)
            except Exception:
                continue
            if not list(it.current_state_ids):
                empty_hits += 1
                s = snap(it)
                ok, err, status = it.last_transition_ok, it.last_error, it.status
                if ok is True and err is None and s == "PRODUCED":
                    bad = {"lap": _lap, "ok": ok, "err": str(err), "status": status, "snap": s}
                elif ok is True and err is None:
                    # success-shaped receipt but snapshot side agrees mid-step ->
                    # still a violation per the issue (receipt/config disagreement)
                    bad = {"lap": _lap, "ok": ok, "err": str(err), "status": status, "snap": s}
        await asyncio.wait_for(it.stop(), 10)
        if bad:
            break
    row = {"engine": "async", "service": kind, "laps": laps, "empty_hits": empty_hits, "violation": bad}
    ROWS.append(row)
    if bad:
        FAIL.append(f"async/{kind}: success-shaped receipt over empty configuration at lap {bad['lap']}: {bad}")


def sync_cell(laps: int = 25):
    empty_hits = 0
    for _lap in range(laps):
        it = SyncInterpreter(mk(def_svc))
        it.start()
        if not it.current_state_ids:
            empty_hits += 1
        for ev in ("GO", "GO", "PING", "NOPE"):
            try:
                it.send(ev)
            except Exception:
                pass
            if not it.current_state_ids:
                empty_hits += 1
        it.stop()
    ROWS.append({"engine": "sync", "service": "def", "laps": laps, "empty_hits": empty_hits})
    if empty_hits:
        FAIL.append(f"sync/def: observed empty current_state_ids {empty_hits} times across {laps} laps")


async def main() -> int:
    for kind in ("def", "async"):
        await async_cell(kind)
    sync_cell()
    print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2, default=str))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
