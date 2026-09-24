"""N3 — SEMANTICS attacks on the round-5 fixes.

guardErrorPolicy raise fallback (#152); Receipt.denied vs deferred vs
unhandled matrix (#153); RootTargetError non-downgradable (#147);
"fail" parent onError on both engines (#145); escalate without an explicit
invoke id (#156); spawn_* namespace (#155); per-macrostep settle budget (#151).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    RootTargetError,
    SyncInterpreter,
    create_machine,
)


@attack(
    "N3-01",
    '#152: guardErrorPolicy "raise" cancels ONLY its own candidate — the unguarded fallback on invoke.onDone is taken',
    "a throwing guard must not swallow a service completion",
)
async def n3_01() -> Dict[str, Any]:
    def boom_guard(ctx, e):  # noqa: ANN001
        raise RuntimeError("guard blew up")

    async def svc(i_, ctx, e):  # noqa: ANN001
        return {"v": 1}

    cfg = {
        "id": "g",
        "initial": "work",
        "guardErrorPolicy": "raise",
        "context": {},
        "states": {
            "work": {
                "invoke": {
                    "src": "svc",
                    "onDone": [
                        {"target": "never", "guard": "boom"},
                        {"target": "fallback"},
                    ],
                }
            },
            "never": {},
            "fallback": {},
        },
    }
    out: Dict[str, Any] = {}
    for label, run in (("async", True), ("sync", False)):
        logic = MachineLogic(guards={"boom": boom_guard}, services={"svc": svc})
        m = create_machine(cfg, logic=logic)
        if run:
            i = await Interpreter(m).start()
            for _ in range(200):
                await asyncio.sleep(0.005)
                if sorted(i.current_state_ids) != ["g.work"]:
                    break
            out[label] = {
                "ids": list(i.current_state_ids),
                "last_error": type(i.last_error).__name__ if i.last_error else None,
            }
            await i.stop()
        else:
            def ssvc(i_, ctx, e):  # noqa: ANN001
                return {"v": 1}

            m = create_machine(
                cfg,
                logic=MachineLogic(guards={"boom": boom_guard}, services={"svc": ssvc}),
            )
            i = SyncInterpreter(m).start()
            out[label] = {
                "ids": list(i.current_state_ids),
                "last_error": type(i.last_error).__name__ if i.last_error else None,
            }
            i.stop()
    ok = all(v["ids"] == ["g.fallback"] for v in out.values())
    return {"ok": ok, **out}


@attack(
    "N3-02",
    "#153: Receipt matrix — denied (guard refused) vs deferred vs unhandled (undeclared) are distinguishable",
    "an OMS must tell 'rejected by a rule' from 'nobody listened'",
)
def n3_02() -> Dict[str, Any]:
    reasons: List[Any] = []

    class Insp:
        def on_unhandled_event(  # real signature (plugins.py:356)
            self, interp, event, active_state_ids, disposition  # noqa: ANN001
        ):
            reasons.append((event.type, disposition))

    cfg = {
        "id": "r",
        "initial": "a",
        "onUnhandled": "defer",
        "context": {},
        "states": {
            "a": {
                "on": {
                    "DENIED": {"target": "b", "guard": "never"},
                    "OK": "b",
                }
            },
            "b": {},
        },
    }
    m = create_machine(
        cfg, logic=MachineLogic(guards={"never": lambda ctx, e: False})
    )
    i = SyncInterpreter(m)
    i.use(Insp())
    i.start()
    rows: Dict[str, Any] = {}
    for ev in ("DENIED", "UNDECLARED", "OK"):
        r = i.send(ev, wait=True)  # sync engine returns a Receipt only with wait=True
        rows[ev] = {
            "denied": getattr(r, "denied", None),
            "deferred": getattr(r, "deferred", None),
            "changed": getattr(r, "changed", None),
            "state_ids": list(getattr(r, "state_ids", []) or []),
        }
    i.stop()
    ok = (
        rows["DENIED"]["denied"] is True
        and rows["DENIED"]["changed"] is False
        and rows["UNDECLARED"]["denied"] is False
        and rows["OK"]["changed"] is True
        and rows["OK"]["denied"] is False
    )
    return {"ok": ok, "rows": rows, "hook_reasons": reasons}


@attack(
    "N3-03",
    "#147: a root target is a non-downgradable RootTargetError under strict_targets=False too",
    "the #108 hole must not reopen through the lenient flag",
)
def n3_03() -> Dict[str, Any]:
    cfg = {
        "id": "rt",
        "initial": "a",
        "states": {"a": {"on": {"GO": "#rt"}}, "b": {}},
    }
    res: Dict[str, str] = {}
    for label, kwargs in (
        ("strict_true", {"strict_targets": True}),
        ("strict_false", {"strict_targets": False}),
        ("default", {}),
    ):
        try:
            m = create_machine(cfg, logic=MachineLogic(), **kwargs)
            i = SyncInterpreter(m).start()
            i.send("GO")
            res[label] = f"ACCEPTED -> {i.current_state_ids}"
            i.stop()
        except RootTargetError:
            res[label] = "RootTargetError"
        except Exception as exc:  # noqa: BLE001
            res[label] = f"{type(exc).__name__}: {str(exc)[:60]}"
    ok = all(v == "RootTargetError" for v in res.values())
    return {"ok": ok, **res}


@attack(
    "N3-04",
    '#145: a child stopped by actionErrorPolicy "fail" fails its parent\'s invoke (onError) on BOTH engines',
    "a bricked child must surface to the supervisor, not hang the parent in `work`",
)
async def n3_04() -> Dict[str, Any]:
    def boom(i_, ctx, e, am):  # noqa: ANN001
        raise RuntimeError("child died")

    child = {
        "id": "kid",
        "initial": "go",
        "actionErrorPolicy": "fail",
        "states": {
            "go": {"entry": ["boom"]},
        },
    }
    parent = {
        "id": "sup",
        "initial": "work",
        "states": {
            "work": {
                "invoke": {"id": "kid", "src": "kid", "onError": "failed"},
            },
            "failed": {},
        },
    }

    def mk():
        return create_machine(
            parent,
            logic=MachineLogic(
                services={
                    "kid": create_machine(
                        child, logic=MachineLogic(actions={"boom": boom})
                    )
                }
            ),
        )

    out: Dict[str, Any] = {}
    i = await Interpreter(mk()).start()
    for _ in range(300):
        await asyncio.sleep(0.005)
        if sorted(i.current_state_ids) == ["sup.failed"]:
            break
    out["async"] = list(i.current_state_ids)
    await i.stop()
    j = SyncInterpreter(mk()).start()
    out["sync"] = list(j.current_state_ids)
    j.stop()
    return {"ok": all(v == ["sup.failed"] for v in out.values()), **out}


@attack(
    "N3-05",
    "#156: `escalate` from an ANONYMOUS invoke (no explicit id) reaches the parent's onError",
    "the invoke id must come from what the parent knows the child by, not from the actor-id string",
)
async def n3_05() -> Dict[str, Any]:
    child = {
        "id": "kid",
        "initial": "go",
        "states": {
            "go": {
                "entry": [
                    {"type": "escalate", "params": {"error": "child says no"}}
                ]
            }
        },
    }
    parent = {
        "id": "sup",
        "initial": "work",
        "states": {
            # 👉 deliberately NO "id" on the invoke
            "work": {"invoke": {"src": "kid", "onError": "caught"}},
            "caught": {},
        },
    }

    def mk():
        return create_machine(
            parent,
            logic=MachineLogic(
                services={"kid": create_machine(child, logic=MachineLogic())}
            ),
        )

    out: Dict[str, Any] = {}
    i = await Interpreter(mk()).start()
    for _ in range(300):
        await asyncio.sleep(0.005)
        if sorted(i.current_state_ids) == ["sup.caught"]:
            break
    out["async"] = list(i.current_state_ids)
    await i.stop()
    j = SyncInterpreter(mk()).start()
    out["sync"] = list(j.current_state_ids)
    j.stop()
    return {"ok": all(v == ["sup.caught"] for v in out.values()), **out}


@attack(
    "N3-06",
    "#155: a USER action named `spawn_order` wins over the built-in spawn prefix",
    "a built-in must not claim a name out of the user's namespace",
)
def n3_06() -> Dict[str, Any]:
    calls: List[str] = []

    def spawn_order(i_, ctx, e, am):  # noqa: ANN001
        calls.append("user")
        ctx["ran"] = True

    cfg = {
        "id": "sp",
        "initial": "a",
        "context": {"ran": False},
        "states": {"a": {"on": {"GO": {"target": "b", "actions": ["spawn_order"]}}}, "b": {}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"spawn_order": spawn_order}))
    i = SyncInterpreter(m).start()
    i.send("GO")
    ran = i.context.get("ran")
    actors = list(getattr(i, "_actors", {}) or {})
    err = type(i.last_error).__name__ if i.last_error else None
    i.stop()
    return {
        "ok": ran is True and calls == ["user"] and not actors and err is None,
        "user_action_ran": ran,
        "calls": calls,
        "actors_spawned": actors,
        "last_error": err,
    }


@attack(
    "N3-07",
    "#151: the always-settle budget is PER MACROSTEP — send_events([A,B]) matches send(A); send(B)",
    "two independent events in one batch must not share one allowance",
)
def n3_07() -> Dict[str, Any]:
    # a ladder of `always` hops just under the budget, taken twice
    cfg = {
        "id": "s",
        "initial": "a",
        "context": {"hops": 0, "n": 0},
        "maxIterations": 12,
        "states": {
            "a": {"on": {"A": "l0", "B": "l0"}},
            "l0": {"always": {"target": "l1", "actions": ["hop"]}},
            "l1": {"always": {"target": "l2", "actions": ["hop"]}},
            "l2": {"always": {"target": "l3", "actions": ["hop"]}},
            "l3": {"always": {"target": "l4", "actions": ["hop"]}},
            "l4": {"always": {"target": "a", "actions": ["hop"]}},
        },
    }

    def hop(i_, ctx, e, am):  # noqa: ANN001
        ctx["hops"] = ctx.get("hops", 0) + 1

    def mk():
        return create_machine(cfg, logic=MachineLogic(actions={"hop": hop}))

    i = SyncInterpreter(mk()).start()
    i.send("A")
    i.send("B")
    seq = {"hops": i.context["hops"], "ids": list(i.current_state_ids),
           "err": type(i.last_error).__name__ if i.last_error else None}
    i.stop()
    j = SyncInterpreter(mk()).start()
    j.send_events(["A", "B"])
    batch = {"hops": j.context["hops"], "ids": list(j.current_state_ids),
             "err": type(j.last_error).__name__ if j.last_error else None}
    j.stop()
    return {"ok": seq == batch, "sequential": seq, "batched": batch}


if __name__ == "__main__":
    main("n3_semantics")
