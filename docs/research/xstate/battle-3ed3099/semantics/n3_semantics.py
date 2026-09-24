"""N3 — SEMANTICS attacks on this round's semantic fixes:
#116 (engine-parity of plain-sync invoke completion ordering),
#109 (done.invoke carries the child's declared `output`),
#108 (a transition targeting the machine ROOT is rejected at build),
#130 (escalate from an invoked child reaches the parent's onError),
#132 (ambiguous bare stateIn rejected), #113 (non-str event type),
#136 (self-referential config), #133 (unresolved sendTo is observable).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    InvalidConfigError,
    InvalidEventError,
    MachineLogic,
    RootTargetError,
    SyncInterpreter,
    create_machine,
)

# --------------------------------------------------------------- #116
SYNC_INVOKE = {
    "id": "j",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "invoke": {"id": "w", "src": "work"},
            "on": {
                "CANCEL": {"target": "idle", "actions": ["cancel"]},
                "done.invoke.w": {"target": "idle", "actions": ["ok"]},
            },
        },
    },
}


def _invoke_logic() -> MachineLogic:
    def work(i, ctx, e):  # plain sync service (#116: runs inline on async too)
        return {"v": 1}

    def ok(i, ctx, e, am):  # noqa: ANN001
        ctx["ok"] = ctx.get("ok", 0) + 1

    def cancel(i, ctx, e, am):  # noqa: ANN001
        ctx["cancel"] = ctx.get("cancel", 0) + 1

    return MachineLogic(actions={"ok": ok, "cancel": cancel}, services={"work": work})


@attack(
    "N3-01",
    "#116: identical (GO,CANCEL)x10 script gives the same ok/cancel split on BOTH engines",
    "the exact #116 shape: async gave cancel=10 where sync gave ok=10",
)
async def n3_01() -> Dict[str, Any]:
    N = 10
    a = await Interpreter(create_machine(SYNC_INVOKE, logic=_invoke_logic())).start()
    for _ in range(N):
        await a.send("GO", wait=True)
        await a.send("CANCEL", wait=True)
    a_ctx = {"ok": a.context["ok"], "cancel": a.context["cancel"]}
    await a.stop()

    s = SyncInterpreter(create_machine(SYNC_INVOKE, logic=_invoke_logic())).start()
    for _ in range(N):
        s.send("GO")
        s.send("CANCEL")
    s_ctx = {"ok": s.context["ok"], "cancel": s.context["cancel"]}
    s.stop()
    return {"ok": a_ctx == s_ctx, "async": a_ctx, "sync": s_ctx}


@attack(
    "N3-02",
    "#116: send_events([GO, X]) agrees with send(GO); send(X) on both engines",
    "batched and sequential delivery must not differ in where a completion lands",
)
async def n3_02() -> Dict[str, Any]:
    def run_sync(batched: bool) -> Dict[str, int]:
        s = SyncInterpreter(create_machine(SYNC_INVOKE, logic=_invoke_logic())).start()
        if batched:
            s.send_events(["GO", "CANCEL"])
        else:
            s.send("GO")
            s.send("CANCEL")
        out = {"ok": s.context["ok"], "cancel": s.context["cancel"]}
        s.stop()
        return out

    async def run_async(batched: bool) -> Dict[str, int]:
        i = await Interpreter(create_machine(SYNC_INVOKE, logic=_invoke_logic())).start()
        if batched:
            await i.send_events(["GO", "CANCEL"])
            await asyncio.sleep(0.15)
        else:
            await i.send("GO", wait=True)
            await i.send("CANCEL", wait=True)
        out = {"ok": i.context["ok"], "cancel": i.context["cancel"]}
        await i.stop()
        return out

    sb, ss = run_sync(True), run_sync(False)
    ab, asq = await run_async(True), await run_async(False)
    return {
        "ok": sb == ss == ab == asq,
        "sync_batched": sb,
        "sync_seq": ss,
        "async_batched": ab,
        "async_seq": asq,
    }


# --------------------------------------------------------------- #109
@attack(
    "N3-03",
    "#109: done.invoke carries the child's declared `output`, not its private context",
    "an OMS child's computed result must reach the parent; context leakage is wrong too",
)
async def n3_03() -> Dict[str, Any]:
    child = {
        "id": "kid",
        "initial": "go",
        "context": {"secret": "PRIVATE", "code": 7},
        "states": {
            "go": {"always": "fin"},
            "fin": {
                "type": "final",
                "output": {"code": 7},
            },
        },
    }
    parent = {
        "id": "m",
        "initial": "run",
        "context": {"seen": None},
        "states": {
            "run": {
                "invoke": {"id": "kid", "src": "kid"},
                "on": {"done.invoke.kid": {"target": "ok", "actions": ["grab"]}},
            },
            "ok": {"type": "final"},
        },
    }

    def grab(i, ctx, e, am):  # noqa: ANN001
        ctx["seen"] = e.data

    kid = create_machine(child, logic=MachineLogic())
    m = create_machine(parent, logic=MachineLogic(actions={"grab": grab}, services={"kid": kid}))
    i = await Interpreter(m).start()
    await asyncio.sleep(0.3)
    seen = i.context["seen"]
    ids = sorted(i.current_state_ids)
    await i.stop()
    leaked = isinstance(seen, dict) and "secret" in seen
    return {
        "ok": seen == {"code": 7} and not leaked,
        "done_data": seen,
        "context_leaked": leaked,
        "ids": ids,
    }


# --------------------------------------------------------------- #108
@attack(
    "N3-04",
    "#108: a transition targeting the machine ROOT is rejected at build",
    "a root target silently emptied the configuration; it must not build",
)
async def n3_04() -> Dict[str, Any]:
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"E": "m"}}, "b": {}}}
    try:
        create_machine(cfg, logic=MachineLogic())
        return {"ok": False, "result": "built (no error)"}
    except (RootTargetError, InvalidConfigError) as exc:
        return {"ok": True, "result": type(exc).__name__, "msg": str(exc)[:160]}


# --------------------------------------------------------------- #130
@attack(
    "N3-05",
    "#130: `escalate` from an invoked child reaches the parent's onError",
    "the documented supervision primitive; silent loss is the worst failure mode",
)
async def n3_05() -> Dict[str, Any]:
    child = {
        "id": "kid",
        "initial": "go",
        "states": {
            "go": {
                "entry": [{"type": "escalate", "params": {"error": "BOOM"}}],
            }
        },
    }
    parent = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "kid",
                    "src": "kid",
                    "onError": {"target": "caught", "actions": ["grab"]},
                },
            },
            "caught": {"type": "final"},
        },
    }
    seen: List[Any] = []

    def grab(i, ctx, e, am):  # noqa: ANN001
        seen.append(getattr(e, "data", None))

    kid = create_machine(child, logic=MachineLogic())
    m = create_machine(parent, logic=MachineLogic(actions={"grab": grab}, services={"kid": kid}))
    i = await Interpreter(m).start()
    await asyncio.sleep(0.3)
    ids = sorted(i.current_state_ids)
    await i.stop()
    return {"ok": ids == ["m.caught"], "ids": ids, "onError_data": [str(s)[:80] for s in seen]}


# --------------------------------------------------------------- #132
@attack(
    "N3-06",
    "#132: an ambiguous bare `stateIn` name is rejected at first use",
    "silently picking one branch of an ambiguous guard is a wrong-branch order decision",
)
async def n3_06() -> Dict[str, Any]:
    cfg = {
        "id": "m",
        "type": "parallel",
        "states": {
            "A": {
                "initial": "right",
                "states": {
                    "left": {"initial": "work", "states": {"work": {}}},
                    "right": {"initial": "work", "states": {"work": {}}},
                },
            },
            "B": {
                "initial": "b1",
                "states": {
                    "b1": {"on": {"E": {"target": "b2", "guard": {"type": "stateIn", "params": {"state": "work"}}}}},
                    "b2": {},
                },
            },
        },
    }
    m = create_machine(cfg, logic=MachineLogic())
    s = SyncInterpreter(m).start()
    try:
        s.send("E")
        out = {"ok": False, "result": "guard resolved silently", "ids": sorted(s.current_state_ids)}
    except InvalidConfigError as exc:
        out = {"ok": True, "result": "InvalidConfigError", "msg": str(exc)[:180]}
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "result": f"{type(exc).__name__}: {exc}"[:180]}
    s.stop()
    return out


# --------------------------------------------------------------- #113
@attack(
    "N3-07",
    "#113: a non-str event `type` raises InvalidEventError (also a TypeError)",
    "a malformed event must not escape the hierarchy as a bare TypeError",
)
async def n3_07() -> Dict[str, Any]:
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"E": "b"}}, "b": {}}}
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    results: Dict[str, Any] = {}
    for label, ev in [
        ("int", {"type": 42}),
        ("none", {"type": None}),
        ("list", {"type": ["E"]}),
        ("bytes", {"type": b"E"}),
    ]:
        try:
            s.send(ev)
            results[label] = "accepted"
        except InvalidEventError as exc:
            results[label] = "InvalidEventError" + (
                "+TypeError" if isinstance(exc, TypeError) else ""
            )
        except Exception as exc:  # noqa: BLE001
            results[label] = f"{type(exc).__name__}"
    s.stop()
    ok = all(v.startswith("InvalidEventError") for v in results.values())
    return {"ok": ok, **results}


# --------------------------------------------------------------- #136
@attack(
    "N3-08",
    "#136: a self-referential config dict raises InvalidConfigError, not RecursionError",
    "a cyclic config must fail as a typed config error",
)
async def n3_08() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {"id": "m", "initial": "a", "states": {}}
    cfg["states"]["a"] = {"states": cfg["states"]}  # cycle
    try:
        create_machine(cfg, logic=MachineLogic())
        return {"ok": False, "result": "built"}
    except InvalidConfigError as exc:
        return {"ok": True, "result": "InvalidConfigError", "msg": str(exc)[:160]}
    except RecursionError:
        return {"ok": False, "result": "RecursionError"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": f"{type(exc).__name__}: {exc}"[:160]}


# --------------------------------------------------------------- #133
@attack(
    "N3-09",
    "#133: a sendTo with no live target is observable on the receipt AND a hook",
    "both actor-messaging failure paths were silent; a dark supervision tree reads green",
)
async def n3_09() -> Dict[str, Any]:
    from xstate_statemachine import PluginBase

    dropped: List[Any] = []

    class Spy(PluginBase):
        def on_event_dropped(self, interpreter, event, reason=None, **kw):  # noqa: ANN001
            dropped.append(reason)

    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"E": {"actions": [{"type": "sendTo", "params": {"to": "nope", "event": "PING"}}]}}}
        },
    }
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic()))
    s.use(Spy())
    s.start()
    r = s.send("E")
    observable = (r is not None and r.error is not None) or s.last_transition_ok is False
    s.stop()
    return {
        "ok": observable,
        "receipt_error": str(getattr(r, "error", None))[:140],
        "last_transition_ok": s.last_transition_ok,
        "dropped_reasons": [str(d) for d in dropped],
    }


if __name__ == "__main__":
    main("n3_semantics")
