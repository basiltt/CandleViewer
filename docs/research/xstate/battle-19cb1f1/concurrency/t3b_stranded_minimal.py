"""t3b (@19cb1f1) -- STANDALONE MINIMAL for t3. ONE machine, both service
kinds, both engines. `rollback + onDone` re-entry storm, maxIterations=8.

Records, per cell: did the chain trip (RunawayChainError seen on the
error hook / `last_error`)? did `on_invocation_stranded` fire? does
`has_dormant_invocations` say the machine is wedged? and is the ERROR log
#207 promises present?

The #207 contract is: wedged => hook fired. A cell with
`dormant == True` and `hook == 0` is the defect.

Run: python t3b_stranded_minimal.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


LIMIT = 8
CFG = {
    "id": "t3b", "initial": "idle", "maxIterations": LIMIT, "context": {},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"invoke": {"id": "spin", "src": "svc",
                            "onDone": {"target": "work"}}},
    },
}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.stranded: List[Any] = []
        self.dropped: List[Any] = []
        self.errors: List[str] = []

    def on_invocation_stranded(self, itp, state_id, invoke_id, error):  # noqa: ANN001
        self.stranded.append([state_id, invoke_id, type(error).__name__])

    def on_event_dropped(self, itp, event, reason):  # noqa: ANN001
        self.dropped.append([getattr(event, "type", str(event)), reason])

    def on_error(self, itp, error):  # noqa: ANN001
        self.errors.append(type(error).__name__)


class LogCap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.recs: List[str] = []

    def emit(self, record):  # noqa: ANN001
        self.recs.append(record.getMessage())


def build(kind: str) -> MachineLogic:
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            return {"ok": 1}

    else:

        async def svc(i, ctx, e):  # noqa: ANN001
            return {"ok": 1}

    return MachineLogic(services={"svc": svc})


def attach() -> LogCap:
    cap = LogCap()
    logging.getLogger("xstate_statemachine").addHandler(cap)
    logging.getLogger().addHandler(cap)
    return cap


def detach(cap: LogCap) -> None:
    logging.getLogger("xstate_statemachine").removeHandler(cap)
    logging.getLogger().removeHandler(cap)


async def cell_async(kind: str) -> Dict[str, Any]:
    spy, cap = Spy(), attach()
    itp = Interpreter(create_machine(copy.deepcopy(CFG), logic=build(kind)))
    itp.use(spy)
    row: Dict[str, Any] = {"engine": "async", "kind": kind}
    try:
        await itp.start()
        await itp.send("GO")
        await asyncio.sleep(1.5)
        row["state"] = sorted(itp.current_state_ids)
        row["dormant"] = bool(itp.has_dormant_invocations)
        row["pending"] = [str(p) for p in itp.pending_invocations()]
    except Exception as exc:  # noqa: BLE001
        row["error"] = type(exc).__name__
    finally:
        try:
            await itp.stop()
        except Exception:  # noqa: BLE001
            pass
        detach(cap)
    row["hook_stranded"] = spy.stranded
    row["hook_dropped"] = spy.dropped[:5]
    row["n_dropped"] = len(spy.dropped)
    row["plugin_errors"] = spy.errors[:5]
    row["error_logs_207"] = [m for m in cap.recs if "#207" in m][:2]
    row["n_error_logs"] = len(cap.recs)
    return row


def cell_sync(kind: str) -> Dict[str, Any]:
    spy, cap = Spy(), attach()
    itp = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=build(kind)))
    itp.use(spy)
    row: Dict[str, Any] = {"engine": "sync", "kind": kind}
    try:
        itp.start()
        itp.send("GO")
        row["state"] = sorted(itp.current_state_ids)
        row["dormant"] = bool(itp.has_dormant_invocations)
        row["pending"] = [str(p) for p in itp.pending_invocations()]
    except Exception as exc:  # noqa: BLE001
        row["error"] = type(exc).__name__
    finally:
        try:
            itp.stop()
        except Exception:  # noqa: BLE001
            pass
        detach(cap)
    row["hook_stranded"] = spy.stranded
    row["hook_dropped"] = spy.dropped[:5]
    row["n_dropped"] = len(spy.dropped)
    row["plugin_errors"] = spy.errors[:5]
    row["error_logs_207"] = [m for m in cap.recs if "#207" in m][:2]
    row["n_error_logs"] = len(cap.recs)
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for kind in ("def", "async def"):
        rows.append(await cell_async(kind))
        rows.append(cell_sync(kind))
    viol = [
        (r["engine"], r["kind"], "wedged but on_invocation_stranded silent",
         r.get("state"), r["n_dropped"])
        for r in rows
        if r.get("dormant") and not r["hook_stranded"]
    ]
    emit("t3b_stranded_minimal",
         {"claim": "#207: a chain cut that strands an invocation fires "
                   "on_invocation_stranded + an ERROR log",
          "limit": LIMIT, "rows": rows, "violations": viol,
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
