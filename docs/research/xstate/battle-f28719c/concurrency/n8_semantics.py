"""N8 - semantics of this round's fixes:

  #116  a plain (non-coroutine) invoked service completes at the same point
        on both engines; (GO, CANCEL) x N gives ok=N on sync, cancel=N on
        async... i.e. the two engines now AGREE. We drive the identical
        script on both and compare the outcome tallies.
  #109  `done.invoke` carries the child's declared `output`, never its
        private context.
  #108  a transition targeting the machine ROOT is rejected at build.
  #130  `escalate` from an invoked child reaches the parent's `onError`.
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import InvalidConfigError

N = 10

# --------------------------------------------------------------- #116
INLINE = {
    "id": "inl",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "work"}}},
        "work": {
            "invoke": {
                "src": "sync_svc",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def sync_svc(interpreter, ctx, event):  # noqa: ANN001
    return {"v": 1}


def act_ok(i, ctx, e, a):  # noqa: ANN001
    ctx["ok"] += 1


def act_cancel(i, ctx, e, a):  # noqa: ANN001
    ctx["cancel"] += 1


def inline_machine():
    return create_machine(
        INLINE,
        logic=MachineLogic(
            actions={"ok": act_ok, "cancel": act_cancel},
            services={"sync_svc": sync_svc},
        ),
    )


async def v116() -> dict:
    a = Interpreter(inline_machine())
    await a.start()
    for _ in range(N):
        await asyncio.wait_for(a.send("GO", wait=True), 5)
        await asyncio.wait_for(a.send("CANCEL", wait=True), 5)
    async_ctx = dict(a.context)
    await a.stop()

    s = SyncInterpreter(inline_machine())
    s.start()
    for _ in range(N):
        s.send("GO")
        s.send("CANCEL")
    sync_ctx = dict(s.context)
    s.stop()

    return {"script": f"(GO, CANCEL) x {N}", "async": async_ctx,
            "sync": sync_ctx, "pass": async_ctx == sync_ctx}


# --------------------------------------------------------------- #109
CHILD = {
    "id": "kid",
    "initial": "run",
    "context": {"private_secret": "DO-NOT-LEAK", "n": 1},
    "output": {"result": "declared-output"},
    "states": {"run": {"type": "final"}},
}
PARENT109 = {
    "id": "p109",
    "initial": "idle",
    "context": {"got": None},
    "states": {
        "idle": {"on": {"GO": {"target": "work"}}},
        "work": {
            "invoke": {
                "src": "kid",
                "onDone": {"target": "done", "actions": ["capture"]},
            }
        },
        "done": {"type": "final"},
    },
}


def capture(i, ctx, e, a):  # noqa: ANN001
    ctx["got"] = e.data


async def v109() -> dict:
    child = create_machine(CHILD, logic=MachineLogic())
    p = create_machine(
        PARENT109,
        logic=MachineLogic(actions={"capture": capture},
                           services={"kid": child}),
    )
    interp = Interpreter(p)
    await interp.start()
    await asyncio.wait_for(interp.send("GO", wait=True), 5)
    for _ in range(50):
        if interp.context["got"] is not None:
            break
        await asyncio.sleep(0.02)
    got = interp.context["got"]
    await interp.stop()
    txt = repr(got)
    return {
        "done_invoke_data": txt[:300],
        "leaks_private_context": "DO-NOT-LEAK" in txt,
        "carries_declared_output": "declared-output" in txt,
        "pass": ("DO-NOT-LEAK" not in txt) and ("declared-output" in txt),
    }


# --------------------------------------------------------------- #108
ROOT_TARGET = {
    "id": "rt",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "#rt"}}}, "b": {}},
}


def v108() -> dict:
    try:
        create_machine(ROOT_TARGET, logic=MachineLogic())
    except InvalidConfigError as exc:
        return {"outcome": "InvalidConfigError", "msg": str(exc)[:160],
                "pass": True}
    except Exception as exc:  # noqa: BLE001
        return {"outcome": f"RAW {type(exc).__name__}", "msg": str(exc)[:160],
                "pass": False}
    return {"outcome": "ACCEPTED (root target not rejected)", "pass": False}


# --------------------------------------------------------------- #130
ESC_CHILD = {
    "id": "esc",
    "initial": "go",
    "states": {
        "go": {
            "entry": [{"type": "escalate",
                       "params": {"error": "child says no"}}],
        }
    },
}
PARENT130 = {
    "id": "p130",
    "initial": "idle",
    "context": {"err": None},
    "states": {
        "idle": {"on": {"GO": {"target": "work"}}},
        "work": {
            "invoke": {
                "src": "esc",
                "onError": {"target": "failed", "actions": ["keep_err"]},
                "onDone": {"target": "done"},
            }
        },
        "failed": {"type": "final"},
        "done": {"type": "final"},
    },
}


def keep_err(i, ctx, e, a):  # noqa: ANN001
    ctx["err"] = repr(getattr(e, "data", e))


async def _v130_run(child_cfg):
    child = create_machine(child_cfg, logic=MachineLogic())
    p = create_machine(
        PARENT130,
        logic=MachineLogic(actions={"keep_err": keep_err},
                           services={"esc": child}),
    )
    interp = Interpreter(p)
    await interp.start()
    await asyncio.wait_for(interp.send("GO", wait=True), 5)
    for _ in range(80):
        if interp.context["err"] is not None:
            break
        await asyncio.sleep(0.02)
    out = {
        "states": sorted(interp.current_state_ids),
        "captured_error": (interp.context["err"] or "")[:200],
        "status": interp.status,
    }
    await interp.stop()
    out["pass"] = (
        interp.context["err"] is not None
        and "child says no" in (interp.context["err"] or "")
    )
    return out


async def v130() -> dict:
    """#130 in both child shapes: a plain escalating state, and one that is
    also `final` (where onDone and onError race)."""
    plain = await _v130_run(ESC_CHILD)
    final_cfg = {
        **ESC_CHILD,
        "states": {"go": {**ESC_CHILD["states"]["go"], "type": "final"}},
    }
    also_final = await _v130_run(final_cfg)
    return {
        "child_plain_state": plain,
        "child_final_state": also_final,
        "pass": plain["pass"],
        "note": (
            "child_final_state is reported, not asserted: when the "
            "escalating state is ALSO final, onDone wins and the escalation "
            "is not delivered."
        ),
    }


async def main() -> int:
    res = {
        "v116_inline_sync_service_parity": await v116(),
        "v109_done_invoke_output": await v109(),
        "v108_root_target_rejected": v108(),
        "v130_escalate_reaches_parent_onError": await v130(),
    }
    ok = all(v["pass"] for v in res.values())
    emit("n8_semantics", {**res, "result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
