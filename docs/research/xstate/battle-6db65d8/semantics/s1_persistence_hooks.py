"""S1 - PERSISTENCE: snapshot from EVERY hook must be refused-or-legal, never torn.

Round-7 attacks against #169 (entry/exit-action snapshot refusal at root) and the
read-side legality rules. Property run over random machines.
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
    PluginBase,
    SnapshotMidStepError,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)


def _try_snap(interp: Any) -> Dict[str, Any]:
    """Take a snapshot; classify as refused / accepted(blob)."""
    try:
        blob = interp.get_persisted_snapshot()
        return {"r": "ACCEPTED", "blob": blob}
    except SnapshotMidStepError:
        return {"r": "REFUSED"}
    except XStateMachineError as exc:  # noqa: BLE001
        return {"r": f"TYPED:{type(exc).__name__}"}
    except Exception as exc:  # noqa: BLE001
        return {"r": f"UNTYPED:{type(exc).__name__}: {exc}"}


class HookSnapper(PluginBase):
    """Calls get_persisted_snapshot() from every hook it can reach."""

    def __init__(self) -> None:
        self.results: List[Dict[str, Any]] = []

    def _grab(self, where: str, interp: Any) -> None:
        rec = _try_snap(interp)
        rec["where"] = where
        self.results.append(rec)

    def on_transition(self, interp, from_ids, to_ids, transition):  # noqa: ANN001
        self._grab("on_transition", interp)

    def on_action_execute(self, interp, action):  # noqa: ANN001
        self._grab("on_action_execute", interp)

    def on_guard_evaluated(self, interp, guard_name, event, result):  # noqa: ANN001
        self._grab("on_guard_evaluated", interp)

    def on_event_received(self, interp, event):  # noqa: ANN001
        self._grab("on_event_received", interp)


# ---------------------------------------------------------------- machines --
NESTED_PAR = {
    "id": "oms",
    "initial": "idle",
    "context": {"qty": 0, "px": 0},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "type": "parallel",
            "states": {
                "fill": {
                    "initial": "a",
                    "states": {
                        "a": {
                            "entry": ["bump_qty", "bump_px"],
                            "on": {"NEXT": "b"},
                        },
                        "b": {"exit": ["bump_qty", "bump_px"], "on": {"BACK": "a"}},
                    },
                },
                "risk": {
                    "initial": "ok",
                    "states": {
                        "ok": {"on": {"BREACH": {"target": "bad", "cond": "always_ok"}}},
                        "bad": {},
                    },
                },
            },
        },
    },
}


def _logic() -> MachineLogic:
    def bump_qty(i_, ctx, e, am):  # noqa: ANN001
        ctx["qty"] = ctx.get("qty", 0) + 100

    def bump_px(i_, ctx, e, am):  # noqa: ANN001
        ctx["px"] = 101

    def always_ok(ctx, e):  # noqa: ANN001
        return True

    return MachineLogic(
        actions={"bump_qty": bump_qty, "bump_px": bump_px},
        guards={"always_ok": always_ok},
    )


def _torn(blob: Dict[str, Any]) -> bool:
    """A snapshot is TORN if qty and px disagree (they are written together)."""
    ctx = blob.get("context", {})
    q, p = ctx.get("qty", 0), ctx.get("px", 0)
    # qty bumped but px not yet written (or vice versa) => half-applied pair
    return (q > 0) != (p > 0)


@attack(
    "S1-01",
    "Snapshot from EVERY plugin hook (transition/action/guard/event) on a "
    "nested+parallel machine is refused-or-legal, never torn - both engines",
    "#169 refuses on _step_in_flight at root; the hook surface is the whole "
    "attack surface, not just entry actions",
)
async def s1_01() -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True, "torn": [], "untyped": [], "by_where": {}}
    for engine in ("sync", "async"):
        snap = HookSnapper()
        m = create_machine(NESTED_PAR, logic=_logic())
        if engine == "sync":
            i = SyncInterpreter(m).use(snap).start()
            for ev in ("GO", "NEXT", "BREACH", "BACK"):
                i.send(ev)
            i.stop()
        else:
            i = await Interpreter(m).use(snap).start()
            for ev in ("GO", "NEXT", "BREACH", "BACK"):
                await i.send(ev, wait=True)
            await i.stop()
        for rec in snap.results:
            key = f"{engine}:{rec['where']}:{rec['r'].split(':')[0]}"
            out["by_where"][key] = out["by_where"].get(key, 0) + 1
            if rec["r"].startswith("UNTYPED"):
                out["ok"] = False
                out["untyped"].append(rec)
            if rec["r"] == "ACCEPTED" and _torn(rec["blob"]):
                out["ok"] = False
                out["torn"].append(
                    {"engine": engine, "where": rec["where"],
                     "ctx": rec["blob"].get("context")}
                )
    return out


# ------------------------------------------------- property: 300 machines --
def _rand_machine(rng: random.Random, idx: int) -> Dict[str, Any]:
    """Random nested/parallel machine whose actions write a PAIR of keys."""
    n = rng.randint(2, 4)
    regions: Dict[str, Any] = {}
    for r in range(rng.randint(1, 3)):
        sts: Dict[str, Any] = {}
        for s in range(n):
            nxt = f"s{(s + 1) % n}"
            node: Dict[str, Any] = {"on": {"STEP": nxt, "ALT": f"s{(s + 2) % n}"}}
            if rng.random() < 0.6:
                node["entry"] = ["bump_qty", "bump_px"]
            if rng.random() < 0.4:
                node["exit"] = ["bump_qty", "bump_px"]
            if rng.random() < 0.2:
                node["always"] = {"target": nxt, "cond": "sometimes"}
            sts[f"s{s}"] = node
        regions[f"r{r}"] = {"initial": "s0", "states": sts}
    return {
        "id": f"p{idx}",
        "type": "parallel",
        "context": {"qty": 0, "px": 0, "tick": 0},
        "states": regions,
    }


@attack(
    "S1-02",
    "Property, 300 random nested/parallel machines x both engines: no hook "
    "snapshot is ever TORN and no rejection is untyped",
    "the refusal must hold across shapes, not just the one repro machine",
)
async def s1_02() -> Dict[str, Any]:
    rng = random.Random(70001)
    out: Dict[str, Any] = {
        "ok": True, "machines": 0, "snapshots": 0,
        "accepted": 0, "refused": 0, "torn": [], "untyped": [],
    }

    def logic() -> MachineLogic:
        st = {"n": 0}

        def bump_qty(i_, ctx, e, am):  # noqa: ANN001
            ctx["qty"] = ctx.get("qty", 0) + 1

        def bump_px(i_, ctx, e, am):  # noqa: ANN001
            ctx["px"] = ctx.get("qty", 0)  # paired invariant: px == qty

        def sometimes(ctx, e):  # noqa: ANN001
            st["n"] += 1
            return st["n"] % 7 == 0

        return MachineLogic(
            actions={"bump_qty": bump_qty, "bump_px": bump_px},
            guards={"sometimes": sometimes},
        )

    for idx in range(300):
        cfg = _rand_machine(rng, idx)
        for engine in ("sync", "async"):
            snap = HookSnapper()
            try:
                m = create_machine(cfg, logic=logic())
                if engine == "sync":
                    i = SyncInterpreter(m).use(snap).start()
                    for _ in range(4):
                        i.send(rng.choice(["STEP", "ALT"]))
                    i.stop()
                else:
                    i = await Interpreter(m).use(snap).start()
                    for _ in range(4):
                        await i.send(rng.choice(["STEP", "ALT"]), wait=True)
                    await i.stop()
            except XStateMachineError:
                continue
            for rec in snap.results:
                out["snapshots"] += 1
                if rec["r"].startswith("UNTYPED"):
                    out["ok"] = False
                    if len(out["untyped"]) < 5:
                        out["untyped"].append(rec["r"])
                elif rec["r"] == "REFUSED":
                    out["refused"] += 1
                elif rec["r"] == "ACCEPTED":
                    out["accepted"] += 1
                    ctx = rec["blob"].get("context", {})
                    if ctx.get("px") != ctx.get("qty"):
                        out["ok"] = False
                        if len(out["torn"]) < 5:
                            out["torn"].append(
                                {"machine": cfg["id"], "engine": engine,
                                 "where": rec["where"], "ctx": ctx}
                            )
        out["machines"] += 1
    return out


if __name__ == "__main__":
    main("s1_persistence_hooks")
