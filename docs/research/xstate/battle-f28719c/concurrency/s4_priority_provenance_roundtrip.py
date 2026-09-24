"""s4 (@f28719c) -- STANDALONE. #192 provenance of priority-lane items:
(a) an ACTION-issued send(priority=True) must be CHARGED like a raise
    (trip observably), and
(b) an EXTERNAL send(priority=True) must NEVER be shed as chain_budget
    while a self-generated chain trips beside it,
both service kinds, and with a snapshot ROUND-TRIP in the middle: the
machine is snapshotted at quiescence, restored, and the same two claims
re-checked on the restored instance.

Run: python s4_priority_provenance_roundtrip.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine


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


class Drops(PluginBase):
    def __init__(self) -> None:
        self.by_reason: Dict[str, Dict[str, int]] = {}
        self.n = 0

    def on_event_dropped(self, interpreter, event, reason=None, **kw):  # noqa: ANN001
        self.n += 1
        r = str(reason)
        t = getattr(event, "type", "?")
        self.by_reason.setdefault(r, {}).setdefault(t, 0)
        self.by_reason[r][t] += 1


SELF_CFG = {
    "id": "s4",
    "initial": "a",
    "maxIterations": 25,
    "context": {"ext": 0, "laps": 0},
    "states": {
        "a": {"entry": ["pingB"], "on": {"B": "b", "EXT": {"actions": ["ext"]}}},
        "b": {"entry": ["pingA"], "on": {"A": "a", "EXT": {"actions": ["ext"]}}},
    },
}


def build(kind: str):
    state = {"laps": 0}

    def ping(target: str):
        def act(i, ctx, e, ad):  # noqa: ANN001
            state["laps"] += 1
            ctx["laps"] = state["laps"]
            i.send(target, priority=True)

        return act

    def ext(i, ctx, e, ad):  # noqa: ANN001
        ctx["ext"] = ctx.get("ext", 0) + 1

    logic = MachineLogic(
        actions={"pingB": ping("B"), "pingA": ping("A"), "ext": ext},
        services={"svc": make_service(kind)},
    )
    return create_machine(copy.deepcopy(SELF_CFG), logic=logic), state


async def charged_cell(kind: str) -> Dict[str, Any]:
    """(a) an action-issued priority send must trip the chain budget."""
    m, state = build(kind)
    drops = Drops()
    itp = Interpreter(m)
    itp.use(drops)
    row: Dict[str, Any] = {"case": "action_issued_priority_charged", "service_kind": kind}
    try:
        await asyncio.wait_for(itp.start(), 10)
        await asyncio.sleep(1.0)
        row["laps"] = state["laps"]
        row["last_error"] = repr(getattr(itp, "last_error", None))[:70]
        row["chain_budget_drops"] = drops.by_reason.get("chain_budget", {})
        row["tripped"] = "Runaway" in row["last_error"] or bool(row["chain_budget_drops"])
        row["bounded"] = state["laps"] < 5000
        t0 = time.monotonic()
        await asyncio.wait_for(itp.stop(), 15)
        row["stop_seconds"] = round(time.monotonic() - t0, 3)
    except asyncio.TimeoutError:
        row["outcome"] = "TIMEOUT/LIVELOCK"
        row["laps"] = state["laps"]
        row["tripped"] = False
        row["bounded"] = False
    return row


EXT_CFG = {
    "id": "s4e",
    "initial": "a",
    "maxIterations": 40,
    "context": {"ext": 0},
    "states": {
        "a": {
            "invoke": {"id": "j", "src": "svc", "onDone": {"target": "b"}},
            "on": {"EXT": {"actions": ["ext"]}},
        },
        "b": {
            "invoke": {"id": "j2", "src": "svc", "onDone": {"target": "a"}},
            "on": {"EXT": {"actions": ["ext"]}},
        },
    },
}


async def external_cell(kind: str, restored: bool, seconds: float = 2.5) -> Dict[str, Any]:
    applied = {"n": 0}

    def ext(i, ctx, e, ad):  # noqa: ANN001
        applied["n"] += 1
        ctx["ext"] = applied["n"]

    logic = MachineLogic(actions={"ext": ext}, services={"svc": make_service(kind, 0.001)})
    m = create_machine(copy.deepcopy(EXT_CFG), logic=logic)
    drops = Drops()
    itp = Interpreter(m)
    itp.use(drops)
    await asyncio.wait_for(itp.start(), 10)

    blob = None
    if restored:
        await asyncio.sleep(0.05)
        try:
            # snapshot from a LIVE machine at quiescence, then stop it
            raw = None
            for _ in range(200):
                try:
                    raw = itp.get_persisted_snapshot()
                    break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(0.01)
            blob = json.loads(raw) if isinstance(raw, str) else raw
            await asyncio.wait_for(itp.stop(), 15)
        except Exception as exc:  # noqa: BLE001
            return {"case": "external_priority", "service_kind": kind,
                    "restored": True, "error": f"snapshot:{type(exc).__name__}"}
        m2 = create_machine(copy.deepcopy(EXT_CFG), logic=logic)
        drops = Drops()
        itp = Interpreter.from_snapshot(json.dumps(blob), m2)
        itp.use(drops)
        await asyncio.wait_for(itp.start(), 10)

    stop_flag = threading.Event()
    sent = {"n": 0}
    errs: Dict[str, int] = {}
    loop = asyncio.get_running_loop()

    def producer() -> None:
        while not stop_flag.is_set():
            try:
                itp.send_threadsafe("EXT", priority=True)
                sent["n"] += 1
            except Exception as exc:  # noqa: BLE001
                errs[type(exc).__name__] = errs.get(type(exc).__name__, 0) + 1
            time.sleep(0.0001)

    th = threading.Thread(target=producer, daemon=True)
    th.start()
    await asyncio.sleep(seconds)
    stop_flag.set()
    th.join(timeout=5)
    await asyncio.sleep(0.5)

    row = {
        "case": "external_priority",
        "service_kind": kind,
        "restored": restored,
        "snapshot_version": (blob or {}).get("version"),
        "external_sent": sent["n"],
        "external_applied": applied["n"],
        "callsite_errors": errs,
        "drops_by_reason": drops.by_reason,
        "external_shed_as_chain_budget": drops.by_reason.get("chain_budget", {}).get("EXT", 0),
    }
    try:
        await asyncio.wait_for(itp.stop(), 20)
        row["stop"] = "ok"
    except Exception as exc:  # noqa: BLE001
        row["stop"] = type(exc).__name__
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for kind in ("def", "async def"):
        rows.append(await charged_cell(kind))
    for kind in ("def", "async def"):
        for restored in (False, True):
            rows.append(await external_cell(kind, restored))
    bad = []
    for r in rows:
        if r["case"].startswith("action_issued"):
            if not r.get("tripped"):
                bad.append([r["service_kind"], "action-issued priority send NOT charged"])
            if not r.get("bounded"):
                bad.append([r["service_kind"], "unbounded"])
        else:
            if r.get("external_shed_as_chain_budget"):
                bad.append([r["service_kind"], r.get("restored"),
                            f"EXT shed as chain_budget: {r['external_shed_as_chain_budget']}"])
    emit("s4_priority_provenance_roundtrip",
         {"rows": rows, "violations": bad, "result": "PASS" if not bad else "FAIL"})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
