"""s2 (@f28719c) -- STANDALONE. #194 children_timeout is PER CHILD.

Cells: 50 async-def-entry children, 50 def-entry children, and a MIXED
50 def + 50 async set. Entry duration D=1.0s, children_timeout=0.3s.
Claim under test: N coroutine children settle in ~D (not N*D), the bound
is per child, and the WARNING fires on EVERY overrun including the
non-yielding `def` case (#194 reopened #181).

Run: python s2_children_timeout_mixed.py
"""

from __future__ import annotations

import asyncio
import json
import logging
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


class WarnCatch(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.msgs: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        try:
            self.msgs.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass


def child_cfg(cid: str) -> dict:
    return {
        "id": cid,
        "initial": "up",
        "states": {"up": {"entry": ["slow"], "on": {"PING": "up2"}}, "up2": {}},
    }


def parent_cfg(n: int) -> dict:
    return {
        "id": "s2p",
        "initial": "boot",
        "states": {
            "boot": {
                "invoke": [
                    {"id": f"c{i}", "src": f"child{i}"} for i in range(n)
                ]
            }
        },
    }


async def cell(n_def: int, n_async: int, entry_s: float, bound: float) -> Dict[str, Any]:
    n = n_def + n_async
    kinds = ["def"] * n_def + ["async def"] * n_async
    entered: List[str] = []

    def make_entry(kind: str, cid: str):
        if kind == "def":

            def slow(i, ctx, e, ad):  # noqa: ANN001
                time.sleep(entry_s)
                entered.append(cid)

            return slow

        async def aslow(i, ctx, e, ad):  # noqa: ANN001
            await asyncio.sleep(entry_s)
            entered.append(cid)

        return aslow

    services = {}
    for i, k in enumerate(kinds):
        cid = f"s2c{i}"
        cm = create_machine(
            child_cfg(cid),
            logic=MachineLogic(actions={"slow": make_entry(k, cid)}),
        )
        services[f"child{i}"] = cm

    parent = create_machine(parent_cfg(n), logic=MachineLogic(services=services))

    handler = WarnCatch()
    lg = logging.getLogger("xstate_statemachine")
    lg.addHandler(handler)
    lg.setLevel(logging.WARNING)
    itp = Interpreter(parent)
    t0 = time.monotonic()
    try:
        await itp.start(children_timeout=bound)
        start_s = time.monotonic() - t0
        start_err = None
    except Exception as exc:  # noqa: BLE001
        start_s = time.monotonic() - t0
        start_err = f"{type(exc).__name__}: {exc}"
    # responsiveness right after a bounded start()
    t1 = time.monotonic()
    try:
        await asyncio.wait_for(itp.send("NOOP"), 2.0)
        first_send_s = time.monotonic() - t1
    except Exception:  # noqa: BLE001
        first_send_s = time.monotonic() - t1
    await asyncio.sleep(0.05)
    row = {
        "n_def": n_def,
        "n_async": n_async,
        "child_entry_seconds": entry_s,
        "children_timeout": bound,
        "start_seconds": round(start_s, 3),
        "start_error": start_err,
        "first_send_seconds": round(first_send_s, 3),
        "warning_logged": any("children_timeout" in m for m in handler.msgs),
        "warnings": handler.msgs[:2],
        "entered_at_start": len(entered),
        "per_child_bound_respected": start_s <= max(bound * 3, entry_s * 1.6),
        "aggregate_scaling": round(start_s / entry_s, 2),
    }
    try:
        await asyncio.wait_for(itp.stop(), 30)
        row["stop"] = "ok"
    except Exception as exc:  # noqa: BLE001
        row["stop"] = f"{type(exc).__name__}"
    lg.removeHandler(handler)
    return row


async def main() -> int:
    rows = []
    rows.append(await cell(0, 50, 1.0, 0.3))
    rows.append(await cell(50, 0, 1.0, 0.3))
    rows.append(await cell(50, 50, 1.0, 0.3))
    bad = []
    for r in rows:
        if not r["warning_logged"]:
            bad.append([f"def{r['n_def']}/async{r['n_async']}", "overrun with NO warning"])
        # per-child claim: a pure-async set of N must settle near the bound
        if r["n_def"] == 0 and r["start_seconds"] > 1.0:
            bad.append(["pure async", f"start {r['start_seconds']}s not per-child bounded"])
        if r["n_def"] and r["aggregate_scaling"] > r["n_def"] * 0.5:
            bad.append([f"def{r['n_def']}", f"N*D scaling: {r['aggregate_scaling']}x entry"])
    emit(
        "s2_children_timeout_mixed",
        {"rows": rows, "violations": bad, "result": "PASS" if not bad else "FAIL"},
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
