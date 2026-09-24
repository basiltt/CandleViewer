"""S4 - SEMANTICS + DETERMINISM + SECURITY, round 7.

Targets: #170 4-way receipt matrix, #171 start() ordering vs #116, entry-window
refusal child-vs-root, trip determinism across 50 runs, perf-PR shared-sentinel
aliasing, __slots__ attribute surface.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

# ------------------------------------------------ S4-01 4-way receipt mtx --
MTX = {
    "id": "r",
    "initial": "a",
    "onUnhandled": "ignore",
    "guardErrorPolicy": "raise",
    "context": {},
    "states": {
        "a": {
            "on": {
                "DENY": {"target": "b", "cond": "say_no"},
                "CRASH": {"target": "b", "cond": "blow_up"},
                "OK": "b",
            }
        },
        "b": {},
    },
}


def _mtx_logic() -> MachineLogic:
    def say_no(ctx, e):  # noqa: ANN001
        return False

    def blow_up(ctx, e):  # noqa: ANN001
        raise RuntimeError("guard exploded")

    return MachineLogic(guards={"say_no": say_no, "blow_up": blow_up})


@attack(
    "S4-01",
    "#170: the 4-way matrix denied / crashed-guard / unhandled / ok is fully "
    "discriminated by (denied, error is None, deferred, changed) - both engines",
    "an OMS must tell 'rule refused' from 'rule broke' from 'nobody listened'",
)
async def s4_01() -> Dict[str, Any]:
    want = {
        # (denied, error_is_none, deferred, changed)
        "DENY": (True, True, False, False),
        "CRASH": (False, False, False, False),
        "NOPE": (False, True, False, False),
        "OK": (False, True, False, True),
    }
    rows: Dict[str, Any] = {}
    ok = True
    for engine in ("sync", "async"):
        for ev in ("DENY", "CRASH", "NOPE", "OK"):
            m = create_machine(MTX, logic=_mtx_logic())
            if engine == "sync":
                i = SyncInterpreter(m).start()
                r = i.send(ev, wait=True)
                i.stop()
            else:
                i = await Interpreter(m).start()
                r = await i.send(ev, wait=True)
                await i.stop()
            got = (
                bool(r.denied),
                r.error is None,
                bool(r.deferred),
                bool(r.changed),
            )
            rows[f"{engine}:{ev}"] = {
                "denied": got[0], "error": type(r.error).__name__ if r.error else None,
                "deferred": got[2], "changed": got[3],
            }
            if got != want[ev]:
                ok = False
                rows[f"{engine}:{ev}"]["EXPECTED"] = want[ev]
    # the discriminator must be INJECTIVE across the four cases
    keys = {tuple(sorted(v.items())) for k, v in rows.items() if k.startswith("sync:")}
    return {"ok": ok and len(keys) == 4, "rows": rows, "distinct_sync_rows": len(keys)}


# ----------------------------------------- S4-02 start() ordering vs #116 --
ORD = {
    "id": "o", "initial": "boot",
    "context": {"log": []},
    "states": {
        "boot": {
            "invoke": {"src": "kid", "id": "kid",
                       "onDone": {"target": "up", "actions": ["mark_done"]}},
            "on": {"CANCEL": {"target": "cancelled", "actions": ["mark_cancel"]}},
        },
        "up": {"on": {"CANCEL": {"target": "cancelled", "actions": ["mark_cancel"]}}},
        "cancelled": {},
    },
}


def _ord_logic() -> MachineLogic:
    def kid(i_, ctx, e):  # noqa: ANN001  plain def -> executor
        return 7

    def mark_done(i_, ctx, e, am):  # noqa: ANN001
        ctx["log"].append("done")

    def mark_cancel(i_, ctx, e, am):  # noqa: ANN001
        ctx["log"].append("cancel")

    return MachineLogic(
        services={"kid": kid},
        actions={"mark_done": mark_done, "mark_cancel": mark_cancel},
    )


@attack(
    "S4-02",
    "#171/#116: start(); send(CANCEL) yields the IDENTICAL trace on both "
    "engines 20x, and actors declared by the initial config are registered "
    "the instant `await start()` returns",
    "'the machine is up' must mean the same thing on both engines",
)
async def s4_02() -> Dict[str, Any]:
    sync_traces, async_traces, actors_seen = set(), set(), []
    for _ in range(20):
        s = SyncInterpreter(create_machine(ORD, logic=_ord_logic())).start()
        s.send("CANCEL")
        sync_traces.add(json.dumps(s.context["log"]))
        s.stop()

        a = await Interpreter(create_machine(ORD, logic=_ord_logic())).start()
        actors_seen.append(sorted(a._actors.keys()))
        await a.send("CANCEL", wait=True)
        async_traces.add(json.dumps(a.context["log"]))
        await a.stop()
    return {
        "ok": (
            len(sync_traces) == 1
            and len(async_traces) == 1
            and sync_traces == async_traces
        ),
        "sync_traces": sorted(sync_traces),
        "async_traces": sorted(async_traces),
        "actors_at_start_return_sample": actors_seen[0],
    }


# --------------------------------- S4-03 determinism of the TRIP POINT ----
TRIP = {
    "id": "t", "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "s0"}},
        "s0": {"entry": ["tick"], "always": {"target": "s1", "cond": "yes"}},
        "s1": {"entry": ["tick"], "always": {"target": "s0", "cond": "yes"}},
    },
}


def _trip_logic() -> MachineLogic:
    def tick(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": tick}, guards={"yes": lambda c, e: True})


@attack(
    "S4-03",
    "50x: the runaway TRIP POINT (lap count at the budget) is identical on "
    "every run and identical between the two engines",
    "a nondeterministic trip point is a nondeterministic audit trail",
)
async def s4_03() -> Dict[str, Any]:
    sy, asy = set(), set()
    for _ in range(50):
        s = SyncInterpreter(create_machine(TRIP, logic=_trip_logic())).start()
        try:
            s.send("GO")
        except Exception:  # noqa: BLE001
            pass
        sy.add(s.context["n"])
        s.stop()
    for _ in range(50):
        a = await Interpreter(create_machine(TRIP, logic=_trip_logic())).start()
        try:
            await asyncio.wait_for(a.send("GO", wait=True), 20)
        except Exception:  # noqa: BLE001
            pass
        asy.add(a.context["n"])
        await a.stop()
    return {
        "ok": len(sy) == 1 and len(asy) == 1 and sy == asy,
        "sync_lap_counts": sorted(sy),
        "async_lap_counts": sorted(asy),
    }


# ------------------------------- S4-04 perf-PR shared-sentinel aliasing ----
SENT = {
    "id": "sn", "initial": "a",
    "context": {"orders": [], "n": 0},
    "states": {
        "a": {"entry": ["push"], "on": {"GO": "b"}},
        "b": {"entry": ["push"], "exit": ["push"], "on": {"BACK": "a"}},
    },
}


@attack(
    "S4-04",
    "#165/#176 perf PRs: two machines built from the SAME config dict share "
    "no mutable state - no cross-talk in context, history, actors or the "
    "shared init/exit sentinels",
    "__slots__ + shared sentinels is exactly the change that aliases state",
)
async def s4_04() -> Dict[str, Any]:
    def push(i_, ctx, e, am):  # noqa: ANN001
        ctx["orders"].append(i_.id if hasattr(i_, "id") else "?")
        ctx["n"] = ctx.get("n", 0) + 1

    def L() -> MachineLogic:
        return MachineLogic(actions={"push": push})

    m1 = create_machine(SENT, logic=L())
    m2 = create_machine(SENT, logic=L())
    i1 = await Interpreter(m1).start()
    i2 = await Interpreter(m2).start()
    for _ in range(5):
        await i1.send("GO", wait=True)
        await i1.send("BACK", wait=True)
    n1, n2 = i1.context["n"], i2.context["n"]
    ids1, ids2 = sorted(i1.current_state_ids), sorted(i2.current_state_ids)
    aliased_ctx = i1.context is i2.context
    aliased_list = i1.context["orders"] is i2.context["orders"]
    aliased_hist = i1._history is i2._history if hasattr(i1, "_history") else False
    # the CONFIG dict itself must be unmutated by machine construction
    cfg_clean = SENT["states"]["a"]["entry"] == ["push"]
    await i1.stop()
    await i2.stop()
    return {
        "ok": (
            n2 == 1  # i2 only ran its own initial entry
            and n1 > n2
            and not aliased_ctx
            and not aliased_list
            and not aliased_hist
            and cfg_clean
            and ids2 == ["sn.a"]
        ),
        "i1_action_count": n1,
        "i2_action_count": n2,
        "i1_states": ids1,
        "i2_states": ids2,
        "aliased_context": aliased_ctx,
        "aliased_list": aliased_list,
        "aliased_history": aliased_hist,
        "config_dict_unmutated": cfg_clean,
    }


@attack(
    "S4-05",
    "#165/#176 __slots__: every declared slot is a real slot (no per-instance "
    "dict entry) and every documented public attribute still reads. NOTE: "
    "`__dict__` is deliberately retained (base_interpreter.py:464 comment), "
    "so ad-hoc attributes are ACCEPTED by design - recorded, not a defect.",
    "__slots__ must not have dropped a public attribute while optimising",
)
async def s4_05() -> Dict[str, Any]:
    PUB = [
        "id", "status", "context", "current_state_ids", "last_error",
        "last_transition_ok", "machine",
    ]
    out: Dict[str, Any] = {"missing": [], "typo_accepted": []}
    for engine in ("sync", "async"):
        m = create_machine(SENT, logic=MachineLogic(actions={"push": lambda *a: None}))
        i = SyncInterpreter(m).start() if engine == "sync" else await Interpreter(m).start()
        for name in PUB:
            if not hasattr(i, name):
                out["missing"].append(f"{engine}.{name}")
        # by-design: __dict__ is retained, so ad-hoc attrs are accepted
        try:
            i.__totally_bogus_attr__ = 1  # type: ignore[attr-defined]
            out["typo_accepted"].append(engine)
        except AttributeError:
            pass
        # but a DECLARED slot must live in the slot, not the instance dict
        i.status = i.status
        if "status" in getattr(i, "__dict__", {}):
            out.setdefault("slot_leaked_to_dict", []).append(engine)
        if engine == "sync":
            i.stop()
        else:
            await i.stop()
    out["adhoc_attrs_accepted_BY_DESIGN"] = out.pop("typo_accepted")
    out["ok"] = not out["missing"] and not out.get("slot_leaked_to_dict")
    return out


# -------------------------- S4-06 entry-window refusal: child vs root ------
PARENT = {
    "id": "par", "initial": "run",
    "context": {"q": 0, "p": 0},
    "states": {
        "run": {
            "invoke": {"src": "child", "id": "kid"},
            "on": {"GO": "done"},
        },
        "done": {},
    },
}
CHILD = {
    "id": "kid", "initial": "x",
    "context": {"q": 0, "p": 0},
    "states": {
        "x": {"on": {"STEP": "y"}},
        "y": {"entry": ["set_q", "set_p"]},
    },
}


@attack(
    "S4-06",
    "#169: a snapshot taken at the ROOT while a CHILD actor is mid-entry "
    "either waits for the child to settle or refuses - it never records the "
    "child's half-applied context",
    "the bounded-wait child path is exactly where the legality conjunction "
    "still lives; it must not leak a torn child blob",
)
async def s4_06() -> Dict[str, Any]:
    def set_q(i_, ctx, e, am):  # noqa: ANN001
        ctx["q"] = 100

    def set_p(i_, ctx, e, am):  # noqa: ANN001
        ctx["p"] = 101

    torn: List[Any] = []
    refused = 0
    accepted = 0

    class Mid(PluginBase):
        def __init__(self, root) -> None:  # noqa: ANN001
            self.root = root

        def on_action_execute(self, interp, action):  # noqa: ANN001
            nonlocal refused, accepted
            try:
                blob = self.root.get_persisted_snapshot()
                accepted += 1
                for _aid, sub in (blob.get("actors") or {}).items():
                    # the child's own blob nests under ["snapshot"]
                    kidsnap = (sub or {}).get("snapshot", {}) if isinstance(sub, dict) else {}
                    c = kidsnap.get("context", {}) or {}
                    if (c.get("q", 0) > 0) != (c.get("p", 0) > 0):
                        torn.append({
                            "actor": _aid,
                            "child_state_ids": kidsnap.get("state_ids"),
                            "ctx": c,
                        })
            except Exception:  # noqa: BLE001
                refused += 1

    logic_c = MachineLogic(actions={"set_q": set_q, "set_p": set_p})
    child_m = create_machine(CHILD, logic=logic_c)
    root = await Interpreter(
        create_machine(PARENT, logic=MachineLogic(services={"child": child_m}))
    ).start()
    # actor ids are namespaced by the parent: "par:kid"
    kid = next(
        (a for k, a in root._actors.items() if k.endswith("kid")), None
    )
    if kid is not None:
        kid.use(Mid(root))
        await kid.send("STEP", wait=True)
    await root.stop()
    return {
        # the probe must actually have run, else it proves nothing
        "ok": (not torn) and kid is not None and (accepted + refused) > 0,
        "child_registered": kid is not None,
        "root_snapshots_accepted": accepted,
        "root_snapshots_refused": refused,
        "torn_child_blobs": torn[:3],
    }


if __name__ == "__main__":
    main("s4_semantics_det_sec")
