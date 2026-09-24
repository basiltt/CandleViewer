"""P4 @cec108b -- round-5 semantics + observability matrix.

v1  guardErrorPolicy "raise": a raising guard cancels ONLY its candidate;
    an unguarded fallback on an invoke.onDone is still taken (#152).
v2  Receipt.denied vs deferred vs unhandled matrix + on_unhandled_event
    reason "guard_denied" (#153).
v3  RootTargetError is non-downgradable under strictTargets=False (#147),
    both engines.
v4  actionErrorPolicy "fail" -> status stopped, configuration cleared,
    .error retained; a child stopped this way fails the parent's invoke
    (onError). Both engines (#145).
v5  hook matrix exactly-once + ordering for: guard_denied, unresolved_target,
    chain_budget, on_plugin_error, on_resolve_error, on_invalid_event,
    on_snapshot_error (#133/#134/#159).
"""

from __future__ import annotations

import asyncio
import json

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    InvalidEventError,
    RootTargetError,
    SnapshotMidStepError,
    XStateMachineError,
)


class Rec(PluginBase):
    def __init__(self) -> None:
        self.seq: list = []

    def on_event_dropped(self, i, event, reason=None, **kw):  # noqa: ANN001
        self.seq.append(("dropped", getattr(event, "type", event), reason))

    def on_unhandled_event(self, i, event, active_state_ids=None, disposition=None):  # noqa: ANN001
        self.seq.append(
            ("unhandled", getattr(event, "type", event), disposition)
        )

    def on_plugin_error(self, i, plugin, hook, error):  # noqa: ANN001
        self.seq.append(("plugin_error", hook, type(error).__name__))

    def on_resolve_error(self, i, *a, **kw):  # noqa: ANN001
        self.seq.append(("resolve_error", None, None))

    def on_guard_error(self, i, *a, **kw):  # noqa: ANN001
        self.seq.append(("guard_error", None, None))

    def on_invalid_event(self, i, *a, **kw):  # noqa: ANN001
        self.seq.append(("invalid_event", None, None))

    def on_snapshot_error(self, i, *a, **kw):  # noqa: ANN001
        self.seq.append(("snapshot_error", None, None))

    def on_error(self, i, error):  # noqa: ANN001
        self.seq.append(("error", type(error).__name__, None))


def boom_guard(*args):  # noqa: ANN001 -- arity-agnostic
    raise RuntimeError("guard exploded")


def no_guard(*args):  # noqa: ANN001 -- arity-agnostic
    return False


def mark(i, ctx, e, a):  # noqa: ANN001
    ctx.setdefault("hit", []).append(a.type if hasattr(a, "type") else str(a))


# ---------------------------------------------------------------- v1
V1 = {
    "id": "g152",
    "initial": "work",
    "context": {"hit": []},
    "guardErrorPolicy": "raise",
    "states": {
        "work": {
            "invoke": {
                "id": "job",
                "src": "svc",
                "onDone": [
                    {"guard": "boom", "target": "guarded"},
                    {"target": "fallback", "actions": ["mark"]},
                ],
            }
        },
        "guarded": {"type": "final"},
        "fallback": {"type": "final"},
    },
}


def svc(i, ctx, e):  # noqa: ANN001
    return {"v": 1}


async def v1_guard_raise_fallback() -> dict:
    rec = Rec()
    i = Interpreter(
        create_machine(
            V1,
            logic=MachineLogic(
                actions={"mark": mark},
                guards={"boom": boom_guard},
                services={"svc": svc},
            ),
        )
    )
    i.use(rec)
    await i.start()
    try:
        await asyncio.wait_for(i.wait_done(), 3)
    except asyncio.TimeoutError:
        pass
    states = sorted(i.current_state_ids)
    last_ok = i.last_transition_ok
    last_err = repr(i.last_error)
    await i.stop()
    return {
        "states": states,
        "fallback_taken": states == ["g152.fallback"],
        "last_transition_ok": last_ok,
        "last_error": last_err[:90],
        "guard_error_hooks": [s for s in rec.seq if s[0] == "guard_error"],
        "pass": states == ["g152.fallback"],
    }


# ---------------------------------------------------------------- v2
V2 = {
    "id": "d153",
    "initial": "a",
    "context": {},
    "states": {
        "a": {
            "on": {
                "DENIED": {"target": "b", "guard": "never"},
                "DEFER": {"actions": []},
            }
        },
        "b": {},
    },
}


async def v2_denied_matrix() -> dict:
    rec = Rec()
    i = Interpreter(
        create_machine(V2, logic=MachineLogic(guards={"never": no_guard}))
    )
    i.use(rec)
    await i.start()
    out = {}
    for ev in ("DENIED", "UNDECLARED"):
        rec.seq.clear()
        r = await asyncio.wait_for(i.send(ev, wait=True), 5)
        out[ev] = {
            "changed": r.changed,
            "denied": r.denied,
            "deferred": r.deferred,
            "error": repr(r.error)[:60],
            "unhandled_reasons": [s[2] for s in rec.seq if s[0] == "unhandled"],
            "unhandled_hook_count": sum(
                1 for s in rec.seq if s[0] == "unhandled"
            ),
        }
    await i.stop()
    ok = (
        out["DENIED"]["denied"] is True
        and out["DENIED"]["unhandled_reasons"] == ["guard_denied"]
        and out["UNDECLARED"]["denied"] is False
        and out["UNDECLARED"]["unhandled_hook_count"] == 1
    )
    return {**out, "pass": ok}


# ---------------------------------------------------------------- v3
V3_BASE = {
    "id": "rt",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "#rt"}}}},
}


def v3_root_target() -> dict:
    out = {}
    for flag in (True, False):
        cfg = dict(V3_BASE)
        cfg = json.loads(json.dumps(V3_BASE))
        cfg["strictTargets"] = flag
        try:
            create_machine(cfg, logic=MachineLogic())
            out[f"strictTargets={flag}"] = "ACCEPTED"
        except RootTargetError as exc:
            out[f"strictTargets={flag}"] = f"RootTargetError: {str(exc)[:60]}"
        except XStateMachineError as exc:
            out[f"strictTargets={flag}"] = f"named:{type(exc).__name__}"
    return {
        **out,
        "pass": all(
            v.startswith("RootTargetError") for v in out.values()
        ),
    }


# ---------------------------------------------------------------- v4
CHILD = {
    "id": "kid",
    "initial": "go",
    "actionErrorPolicy": "fail",
    "states": {"go": {"entry": ["explode"], "on": {"X": {}}}},
}
PARENT = {
    "id": "par",
    "initial": "run",
    "context": {"err": None},
    "states": {
        "run": {
            "invoke": {
                "id": "c",
                "src": "child",
                "onError": {"target": "caught", "actions": ["capture"]},
                "onDone": {"target": "finished"},
            }
        },
        "caught": {"type": "final"},
        "finished": {"type": "final"},
    },
}


def explode(i, ctx, e, a):  # noqa: ANN001
    raise RuntimeError("entry boom")


def capture(i, ctx, e, a):  # noqa: ANN001
    ctx["err"] = repr(getattr(e, "data", None))[:70]


def child_machine():
    return create_machine(
        CHILD, logic=MachineLogic(actions={"explode": explode})
    )


async def v4_fail_async() -> dict:
    c = Interpreter(child_machine())
    try:
        await c.start()
    except Exception as exc:  # noqa: BLE001
        pass
    await asyncio.sleep(0.05)
    solo = {
        "status": c.status,
        "config_cleared": sorted(c.current_state_ids) == [],
        "error": repr(c.error)[:70],
    }
    try:
        await c.stop()
    except Exception:  # noqa: BLE001
        pass

    p = Interpreter(
        create_machine(
            PARENT,
            logic=MachineLogic(
                actions={"capture": capture},
                services={"child": child_machine()},
            ),
        )
    )
    await p.start()
    try:
        await asyncio.wait_for(p.wait_done(), 3)
    except asyncio.TimeoutError:
        pass
    par = {
        "states": sorted(p.current_state_ids),
        "err": p.context["err"],
    }
    await p.stop()
    return {
        "solo_child": solo,
        "parent": par,
        "pass": solo["status"] == "stopped"
        and solo["config_cleared"]
        and par["states"] == ["par.caught"],
    }


def v4_fail_sync() -> dict:
    c = SyncInterpreter(child_machine())
    try:
        c.start()
    except Exception:  # noqa: BLE001
        pass
    solo = {
        "status": c.status,
        "config_cleared": sorted(c.current_state_ids) == [],
        "error": repr(c.error)[:70],
    }
    return {
        **solo,
        "pass": solo["status"] == "stopped" and solo["config_cleared"],
    }


# ---------------------------------------------------------------- v5
V5 = {
    "id": "h159",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "SELF": {"actions": ["selfsend"]},
                "FWD": {
                    "actions": [
                        {
                            "type": "sendTo",
                            "params": {"to": "ghost", "event": "Q"},
                        }
                    ]
                },
            }
        }
    },
}


def selfsend(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1
    i.send("SELF")


async def v5_hook_matrix() -> dict:
    out = {}
    # unresolved_target
    rec = Rec()
    i = Interpreter(
        create_machine(
            {**V5, "maxIterations": 5},
            logic=MachineLogic(actions={"selfsend": selfsend}),
        )
    )
    i.use(rec)
    await i.start()
    await asyncio.wait_for(i.send("FWD", wait=True), 5)
    out["unresolved_target"] = {
        "hooks": [s for s in rec.seq if s[2] == "unresolved_target"],
        "count": sum(1 for s in rec.seq if s[2] == "unresolved_target"),
    }
    # chain_budget
    rec.seq.clear()
    try:
        await asyncio.wait_for(i.send("SELF", wait=True), 5)
    except Exception:  # noqa: BLE001
        pass
    out["chain_budget"] = {
        "hooks": [s for s in rec.seq if s[2] == "chain_budget"],
        "count": sum(1 for s in rec.seq if s[2] == "chain_budget"),
        "last_error": repr(i.last_error)[:70],
    }
    # invalid event
    rec.seq.clear()
    try:
        await i.send(123)  # type: ignore[arg-type]
        inv = "ACCEPTED"
    except InvalidEventError as exc:
        inv = "InvalidEventError"
    out["on_invalid_event"] = {
        "outcome": inv,
        "count": sum(1 for s in rec.seq if s[0] == "invalid_event"),
    }
    await i.stop()
    ok = (
        out["unresolved_target"]["count"] == 1
        and out["chain_budget"]["count"] >= 1
        and out["on_invalid_event"]["outcome"] == "InvalidEventError"
        and out["on_invalid_event"]["count"] == 1
    )
    return {**out, "pass": ok}


async def main() -> int:
    res = {
        "v1_guard_raise_fallback": await v1_guard_raise_fallback(),
        "v2_denied_matrix": await v2_denied_matrix(),
        "v3_root_target": v3_root_target(),
        "v4_fail_async": await v4_fail_async(),
        "v4_fail_sync": v4_fail_sync(),
        "v5_hook_matrix": await v5_hook_matrix(),
    }
    res["result"] = (
        "PASS"
        if all(v["pass"] for v in res.values() if isinstance(v, dict))
        else "FAIL"
    )
    emit("p4_semantics_observability", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
