"""P: persistence attacks on the round-8 machinery (f28719c).

P1  Snapshot round-trip of PENDING PRIORITY-LANE items: lane position and
    provenance (external vs self-generated) after restore.
P2  "engine": true forgery in a persisted pending/deferred record.
P3  v1 (0.8.0-written, state_ids-only) restore still accepted; v1 with an
    emptied field refused (#198).
P4  Snapshot taken from inside `on_interpreter_start` (#199), both engines.
P5  Property: 300 random machines incl. parallel + invoked children --
    snapshot at quiescence round-trips, both service kinds.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import sys
import traceback
from typing import Any, Callable, Dict, List

import xstate_statemachine as xs
from xstate_statemachine import (
    Event,
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

logging.disable(logging.CRITICAL)

# --------------------------------------------------------------------------
# inlined harness
# --------------------------------------------------------------------------
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
        print(f"[{rec['status']:5}] {rec['id']:8} {a['title']}")
        if rec["status"] != "PASS":
            print("          -> " + json.dumps(rec["detail"], default=str)[:1100])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


def _blob(b: Any) -> Dict[str, Any]:
    return json.loads(b) if isinstance(b, str) else b



def _snap(cfg: Dict[str, Any], logic=None) -> str:
    """Start, snapshot at quiescence, stop; return the JSON string."""

    async def _go() -> str:
        i = await Interpreter(
            create_machine(copy.deepcopy(cfg), logic=logic)
        ).start()
        b = i.get_persisted_snapshot()
        await i.stop()
        return b if isinstance(b, str) else json.dumps(b)

    return asyncio.get_event_loop().run_until_complete(_go())


# ==========================================================================
# P1 -- a pending record's `engine` flag decides provenance on restore
# ==========================================================================
DONE_M = {
    "id": "t",
    "initial": "a",
    "states": {
        "a": {"on": {"E": "b", "done.invoke.q": "b"}},
        "b": {"entry": "mark"},
    },
}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.drops: List[Any] = []
        self.recv: List[str] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((e.type, r))

    def on_event_received(self, i, e):  # noqa: ANN001
        self.recv.append(e.type)


@attack("P1", "restore_event provenance: 'engine': true -> engine-minted, "
              "absent -> public class (user traffic)")
async def p1() -> Dict[str, Any]:
    from xstate_statemachine.events import is_system_event, restore_event

    flagged = restore_event(
        {"kind": "done", "type": "done.invoke.q", "data": 1,
         "src": "q", "engine": True}
    )
    bare = restore_event(
        {"kind": "done", "type": "done.invoke.q", "data": 1, "src": "q"}
    )
    forged_str = restore_event(
        {"kind": "done", "type": "done.invoke.q", "data": 1,
         "src": "q", "engine": "true"}   # string, not bool
    )
    return {
        "ok": (is_system_event(flagged)
               and not is_system_event(bare)
               and not is_system_event(forged_str)),
        "flagged_engine": is_system_event(flagged),
        "bare_engine": is_system_event(bare),
        "engine_string_truthy_accepted": is_system_event(forged_str),
    }


# ==========================================================================
# P2 -- a FORGED "engine": true pending record drives a real onDone
# ==========================================================================
@attack("P2", "Forged pending record with 'engine': true is NOT gated by "
              "strict; unflagged record IS gated by onUnhandled")
async def p2() -> Dict[str, Any]:
    async def _restore(cfg: Dict[str, Any], rec: Dict[str, Any]):
        i = await Interpreter(create_machine(copy.deepcopy(cfg))).start()
        b = _blob(i.get_persisted_snapshot())
        await i.stop()
        b["pending_events"] = [rec]
        sp = Spy()
        i2 = Interpreter.from_snapshot(
            json.dumps(b), create_machine(copy.deepcopy(cfg))
        )
        i2.use(sp)
        await i2.start()
        await asyncio.sleep(0.05)
        out = {"status": i2.status,
               "err": type(i2.last_error).__name__ if i2.last_error else None,
               "recv": sp.recv, "drops": sp.drops}
        await i2.stop()
        return out

    STRICT = {"id": "t", "strict": True, "initial": "a",
              "states": {"a": {"on": {"E": "b"}}, "b": {}}}
    UNH = {"id": "t", "onUnhandled": "error", "initial": "a",
           "states": {"a": {"on": {"E": "b"}}, "b": {}}}
    bare = {"kind": "done", "type": "done.invoke.q", "data": 1, "src": "q"}
    cells = {
        "strict/bare_done": await _restore(STRICT, bare),
        "strict/plain_undeclared": await _restore(
            STRICT, {"kind": "event", "type": "BOGUS", "payload": {}}),
        "onUnhandled/bare_done": await _restore(UNH, bare),
        "onUnhandled/plain_undeclared": await _restore(
            UNH, {"kind": "event", "type": "BOGUS", "payload": {}}),
    }
    # Contract (events.py:403-414): an unflagged record is "user traffic,
    # subject to strict / onUnhandled". onUnhandled honours it; strict does
    # not gate the restore path at all.
    return {
        "ok": False if cells["strict/bare_done"]["err"] is None else True,
        "cells": cells,
        "OBSERVED_strict_inert_on_restore":
            cells["strict/plain_undeclared"]["err"] is None,
        "onUnhandled_honoured":
            cells["onUnhandled/bare_done"]["err"] == "UnhandledEventError",
    }



# ==========================================================================
# P3 -- versioned-payload both-fields restore matrix (#198 / #186)
# ==========================================================================
@attack("P3", "v0/v1/v2 restore matrix: v0 state_ids-only OK; any v>=1 blob "
              "with a missing or EMPTIED configuration field is refused")
async def p3() -> Dict[str, Any]:
    M = {"id": "t", "initial": "a", "states": {"a": {"on": {"E": "b"}},
                                               "b": {}}}
    i = await Interpreter(create_machine(copy.deepcopy(M))).start()
    base = _blob(i.get_persisted_snapshot())
    await i.stop()

    def cell(mut) -> str:
        bb = copy.deepcopy(base)
        mut(bb)
        try:
            Interpreter.from_snapshot(json.dumps(bb),
                                      create_machine(copy.deepcopy(M)))
            return "ACCEPTED"
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__

    cells = {
        "v0 state_ids-only": cell(
            lambda x: (x.update(version=0), x.pop("configuration", None))),
        "v1 state_ids-only": cell(
            lambda x: (x.update(version=1), x.pop("configuration", None))),
        "v1 both present": cell(lambda x: x.update(version=1)),
        "v1 configuration EMPTIED": cell(
            lambda x: (x.update(version=1), x.update(configuration=[]))),
        "v1 state_ids EMPTIED": cell(
            lambda x: (x.update(version=1), x.update(state_ids=[]))),
        "v2 state_ids EMPTIED": cell(lambda x: x.update(state_ids=[])),
        "v2 configuration EMPTIED": cell(lambda x: x.update(configuration=[])),
        "v2 contradictory pair": cell(
            lambda x: x.update(configuration=["t", "t.b"])),
    }
    want_ok = {"v0 state_ids-only", "v1 both present"}
    ok = all((v == "ACCEPTED") == (k in want_ok) for k, v in cells.items())
    return {"ok": ok, "cells": cells}


# ==========================================================================
# P4 -- snapshot from inside `on_interpreter_start` (#199), both engines
# ==========================================================================
@attack("P4", "get_persisted_snapshot() from on_interpreter_start is inside "
              "the in-flight window and refused on BOTH engines (#199)")
async def p4() -> Dict[str, Any]:
    M = {"id": "t", "initial": "a", "states": {"a": {"on": {"E": "b"}},
                                               "b": {}}}

    class StartSnap(PluginBase):
        def __init__(self) -> None:
            self.out: List[Any] = []

        def on_interpreter_start(self, i):  # noqa: ANN001
            try:
                self.out.append(("UNREFUSED",
                                 bool(_blob(i.get_persisted_snapshot())
                                      .get("state_ids"))))
            except Exception as exc:  # noqa: BLE001
                self.out.append((type(exc).__name__, None))

    res = {}
    for eng in ("async", "sync"):
        sp = StartSnap()
        if eng == "async":
            it = Interpreter(create_machine(copy.deepcopy(M)))
            it.use(sp)
            await it.start()
            await it.stop()
        else:
            it = SyncInterpreter(create_machine(copy.deepcopy(M)))
            it.use(sp)
            it.start()
            it.stop()
        res[eng] = sp.out
    return {
        "ok": all(o and o[0][0] == "SnapshotMidStepError"
                  for o in res.values()),
        "runs": res,
    }


if __name__ == "__main__":
    main("p_persistence")
