"""N1 — PERSISTENCE attacks against the round-4 snapshot fixes.

Targets: #102 (SnapshotMidStepError never at quiescence), #128
(restart_timers / has_dormant_timers), #117 (from_snapshot(clock=)),
#110 (SnapshotCorruptError), #131 (SnapshotSerializationError),
#107 (priority lane persisted), #86/#87 (engine-event round-trip).
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SnapshotCorruptError,
    SnapshotMidStepError,
    SnapshotSerializationError,
    SyncInterpreter,
    create_machine,
)

PING = {
    "id": "p",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"GO": {"target": "a", "actions": ["bump"]}}},
    },
}


def _logic() -> MachineLogic:
    def bump(i, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"bump": bump})


@attack(
    "N1-01",
    "2k-event property run: snapshot at EVERY quiescent point succeeds and round-trips",
    "#102 must never fire at quiescence; snapshot must be a fixed point of state+context",
)
async def n1_01() -> Dict[str, Any]:
    rnd = random.Random(20260919)
    m = create_machine(PING, logic=_logic())
    interp = await Interpreter(m).start()
    N = 2000
    failures: List[Any] = []
    for i in range(N):
        await interp.send("GO" if rnd.random() < 0.8 else "NOPE", wait=True)
        try:
            snap = interp.get_persisted_snapshot()
        except SnapshotMidStepError as exc:
            failures.append({"i": i, "midstep": str(exc)})
            break
        blob = json.dumps(snap)
        r = await Interpreter.from_snapshot(blob, create_machine(PING, logic=_logic())).start()
        same = sorted(r.current_state_ids) == sorted(
            interp.current_state_ids
        ) and r.context.get("n") == interp.context.get("n")
        await r.stop()
        if not same:
            failures.append({"i": i, "restored": sorted(r.current_state_ids)})
            break
    n = interp.context["n"]
    await interp.stop()
    return {"ok": not failures, "events": N, "bumps": n, "failures": failures}


@attack(
    "N1-02",
    "Snapshot taken from INSIDE an action still raises SnapshotMidStepError (#102 holds)",
    "the refusal must be exactly at mid-step, not merely absent",
)
async def n1_02() -> Dict[str, Any]:
    seen: Dict[str, Any] = {}

    def probe(i_, ctx, e, am):  # noqa: ANN001
        try:
            probe.interp.get_persisted_snapshot()
            seen["result"] = "snapshot-succeeded"
        except SnapshotMidStepError as exc:
            seen["result"] = "SnapshotMidStepError"
            seen["msg"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            seen["result"] = f"{type(exc).__name__}: {exc}"

    cfg = {
        "id": "q",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {"entry": ["probe"], "on": {"GO": "a"}},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"probe": probe}))
    i = await Interpreter(m).start()
    probe.interp = i
    await i.send("GO", wait=True)
    await i.stop()
    return {"ok": seen.get("result") == "SnapshotMidStepError", **seen}


@attack(
    "N1-03",
    "restart_timers=True re-arms a dormant `after` on a SimulatedClock",
    "#128: a restored order-timeout must fire; has_dormant_timers must report honestly",
)
async def n1_03() -> Dict[str, Any]:
    cfg = {
        "id": "t",
        "initial": "arm",
        "states": {
            "arm": {"after": {1000: "fired"}},
            "fired": {"type": "final"},
        },
    }
    mk = lambda: create_machine(cfg, logic=MachineLogic())  # noqa: E731
    c0 = SimulatedClock()
    i = await Interpreter(mk(), clock=c0).start()
    snap = json.dumps(i.get_persisted_snapshot())
    await i.stop()

    c1 = SimulatedClock()
    off = await Interpreter.from_snapshot(snap, mk(), clock=c1).start()
    dormant_off = off.has_dormant_timers
    await c1.increment(5000)
    ids_off = sorted(off.current_state_ids)
    await off.stop()

    c2 = SimulatedClock()
    on = await Interpreter.from_snapshot(
        snap, mk(), clock=c2, restart_timers=True
    ).start()
    dormant_on = on.has_dormant_timers
    await c2.increment(5000)
    ids_on = sorted(on.current_state_ids)
    await on.stop()

    ok = (
        dormant_off is True
        and ids_off == ["t.arm"]
        and dormant_on is False
        and ids_on == ["t.fired"]
    )
    return {
        "ok": ok,
        "dormant_without_restart": dormant_off,
        "ids_without_restart": ids_off,
        "dormant_with_restart": dormant_on,
        "ids_with_restart": ids_on,
    }


@attack(
    "N1-04",
    "Non-JSON pending payload raises SnapshotSerializationError, never stringified",
    "#131: silent coercion of an order payload would corrupt a restored OMS",
)
async def n1_04() -> Dict[str, Any]:
    class Opaque:
        pass

    cfg = {
        "id": "s",
        "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }
    m = create_machine(cfg, logic=MachineLogic())
    i = SyncInterpreter(m).start()
    # queue an event carrying an unserialisable payload without processing it
    i._event_queue.append(
        __import__("xstate_statemachine").Event(
            type="LATER", payload={"obj": Opaque()}
        )
    )
    out: Dict[str, Any] = {}
    try:
        blob = json.dumps(i.get_persisted_snapshot())
        out["result"] = "serialised"
        out["blob_has_object_repr"] = "Opaque object at" in blob
    except SnapshotSerializationError as exc:
        out["result"] = "SnapshotSerializationError"
        out["msg"] = str(exc)[:200]
    except Exception as exc:  # noqa: BLE001
        out["result"] = f"{type(exc).__name__}: {exc}"[:200]
    i.stop()
    return {"ok": out.get("result") == "SnapshotSerializationError", **out}


@attack(
    "N1-05",
    "Priority (fired-timer) lane survives a snapshot (#107)",
    "a due order timeout queued at priority must not be lost across a restart",
)
async def n1_05() -> Dict[str, Any]:
    cfg = {
        "id": "pr",
        "initial": "a",
        "states": {"a": {"on": {"URGENT": "b"}}, "b": {"type": "final"}},
    }
    mk = lambda: create_machine(cfg, logic=MachineLogic())  # noqa: E731
    i = SyncInterpreter(mk()).start()
    i._priority_queue.append(
        __import__("xstate_statemachine").Event(type="URGENT")
    ) if hasattr(i, "_priority_queue") else None
    has_lane = hasattr(i, "_priority_queue")
    snap = i.get_persisted_snapshot()
    blob = json.dumps(snap)
    persisted = "URGENT" in blob
    i.stop()
    return {
        "ok": (not has_lane) or persisted,
        "engine_has_priority_lane": has_lane,
        "urgent_in_blob": persisted,
    }


@attack(
    "N1-06",
    "from_snapshot(clock=) injects the clock (#117) on both engines",
    "a restored machine must use the caller's clock, not a fresh RealClock",
)
async def n1_06() -> Dict[str, Any]:
    cfg = {
        "id": "c",
        "initial": "arm",
        "states": {"arm": {"after": {500: "done"}}, "done": {"type": "final"}},
    }
    mk = lambda: create_machine(cfg, logic=MachineLogic())  # noqa: E731
    c0 = SimulatedClock()
    i = await Interpreter(mk(), clock=c0).start()
    blob = json.dumps(i.get_persisted_snapshot())
    await i.stop()
    c1 = SimulatedClock()
    r = await Interpreter.from_snapshot(blob, mk(), clock=c1, restart_timers=True).start()
    injected = r.clock is c1
    await c1.increment(1000)
    ids = sorted(r.current_state_ids)
    await r.stop()
    return {"ok": injected and ids == ["c.done"], "clock_injected": injected, "ids": ids}


@attack(
    "N1-07",
    "Round-trip of a snapshot is idempotent: snapshot(restore(s)) == s",
    "an OMS restarted twice must not drift; drift = silent state corruption",
)
async def n1_07() -> Dict[str, Any]:
    m = create_machine(PING, logic=_logic())
    i = await Interpreter(m).start()
    for _ in range(7):
        await i.send("GO", wait=True)
    s1 = i.get_persisted_snapshot()
    await i.stop()
    r = await Interpreter.from_snapshot(json.dumps(s1), create_machine(PING, logic=_logic())).start()
    s2 = r.get_persisted_snapshot()
    await r.stop()

    def strip(d: Any) -> Any:
        if isinstance(d, dict):
            return {
                k: strip(v)
                for k, v in sorted(d.items())
                if k not in ("machine_hash", "timestamp", "version", "taken_at")
            }
        if isinstance(d, list):
            return [strip(x) for x in d]
        return d

    a, b = strip(s1), strip(s2)
    return {"ok": a == b, "s1": json.dumps(a)[:300], "s2": json.dumps(b)[:300]}


if __name__ == "__main__":
    main("n1_persistence")
