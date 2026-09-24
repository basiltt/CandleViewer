"""s3 (@f28719c) -- STANDALONE. #196 / SCXML 3.13: an `always` must never
compete for a NAMED event, at any relative depth.

Matrix: always at {same, deeper, shallower} depth vs a named handler, x
{always guard true, always guard false} x both engines x both service
kinds (a service is armed so the lane is exercised).

Invariant per cell: sending NAMED must run the named handler's action
EXACTLY once and leave last_error clean; a spinning `always` must not
consume it.

Run: python s3_eventless_selection_matrix.py
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


def make_service(kind: str, delay: float = 0.0):
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            if delay:
                time.sleep(delay)
            return {"v": 1}

        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        if delay:
            await asyncio.sleep(delay)
        return {"v": 1}

    return asvc


def cfg(where: str, guard_on: bool) -> dict:
    """`where`: same | deeper | shallower -- position of the `always`
    relative to the state that declares the NAMED handler."""
    always = {"target": ".spin", "guard": "canSpin", "actions": ["eventless"]}
    named = {"NAMED": {"actions": ["named"]}}
    base: Dict[str, Any] = {
        "id": "s3",
        "initial": "outer",
        "context": {"named": 0, "eventless": 0, "spin": 0, "on": guard_on},
        "states": {},
    }
    if where == "same":
        base["states"] = {
            "outer": {
                "initial": "a",
                "on": named,
                "always": [always],
                "states": {"a": {}, "spin": {"on": {"BACK": "a"}}},
            }
        }
    elif where == "deeper":
        base["states"] = {
            "outer": {
                "initial": "a",
                "on": named,
                "states": {
                    "a": {"always": [{"target": "b", "guard": "canSpin",
                                      "actions": ["eventless"]}]},
                    "b": {"always": [{"target": "a", "guard": "canSpin",
                                      "actions": ["eventless"]}]},
                },
            }
        }
    else:  # shallower: always on the root-level parent, named on the leaf
        base["states"] = {
            "outer": {
                "initial": "a",
                "always": [{"target": ".spin", "guard": "canSpin",
                            "actions": ["eventless"]}],
                "states": {"a": {"on": named}, "spin": {"on": named}},
            }
        }
    return base


def build(where: str, guard_on: bool, kind: str):
    counts = {"named": 0, "eventless": 0}

    def named(i, ctx, e, ad):  # noqa: ANN001
        counts["named"] += 1
        ctx["named"] = counts["named"]

    def eventless(i, ctx, e, ad):  # noqa: ANN001
        counts["eventless"] += 1
        ctx["eventless"] = counts["eventless"]

    def can_spin(ctx, e):  # noqa: ANN001
        # bounded spin: at most 3 eventless hops, so the machine settles
        return bool(ctx.get("on")) and counts["eventless"] < 3

    logic = MachineLogic(
        actions={"named": named, "eventless": eventless},
        guards={"canSpin": can_spin},
        services={"svc": make_service(kind, 0.01)},
    )
    m = create_machine(copy.deepcopy(cfg(where, guard_on)), logic=logic)
    return m, counts


async def cell(where: str, guard_on: bool, kind: str, engine: str) -> Dict[str, Any]:
    m, counts = build(where, guard_on, kind)
    row = {"always_at": where, "always_guard": guard_on, "service_kind": kind,
           "engine": engine}
    try:
        if engine == "async":
            i = Interpreter(m)
            await asyncio.wait_for(i.start(), 10)
            before = counts["named"]
            await asyncio.wait_for(i.send("NAMED"), 5)
            await asyncio.sleep(0.05)
            row["named_ran"] = counts["named"] - before
            row["eventless_ran"] = counts["eventless"]
            row["last_error"] = repr(getattr(i, "last_error", None))[:60]
            row["state"] = list(i.current_state_ids)
            await asyncio.wait_for(i.stop(), 15)
        else:
            i = SyncInterpreter(m)
            i.start()
            before = counts["named"]
            i.send("NAMED")
            row["named_ran"] = counts["named"] - before
            row["eventless_ran"] = counts["eventless"]
            row["last_error"] = repr(getattr(i, "last_error", None))[:60]
            row["state"] = list(i.current_state_ids)
            i.stop()
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"[:120]
        row["named_ran"] = counts["named"]
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for where in ("same", "deeper", "shallower"):
        for guard_on in (True, False):
            for kind in ("def", "async def"):
                for engine in ("async", "sync"):
                    if engine == "sync" and kind == "async def":
                        continue
                    rows.append(await cell(where, guard_on, kind, engine))
    bad = []
    for r in rows:
        if r.get("named_ran") != 1:
            bad.append([r["always_at"], r["always_guard"], r["engine"],
                        r["service_kind"], f"named_ran={r.get('named_ran')}"])
        if r.get("error"):
            bad.append([r["always_at"], r["engine"], r["error"]])
    # engine parity on named_ran / eventless_ran for the def lane
    parity = []
    for where in ("same", "deeper", "shallower"):
        for guard_on in (True, False):
            a = [r for r in rows if r["always_at"] == where and r["always_guard"] == guard_on
                 and r["engine"] == "async" and r["service_kind"] == "def"]
            s = [r for r in rows if r["always_at"] == where and r["always_guard"] == guard_on
                 and r["engine"] == "sync"]
            if a and s and (a[0].get("named_ran"), a[0].get("eventless_ran")) != (
                    s[0].get("named_ran"), s[0].get("eventless_ran")):
                parity.append([where, guard_on, a[0].get("eventless_ran"),
                               s[0].get("eventless_ran")])
    emit("s3_eventless_selection_matrix",
         {"rows": rows, "violations": bad, "engine_parity_gaps": parity,
          "result": "PASS" if not bad and not parity else "FAIL"})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
