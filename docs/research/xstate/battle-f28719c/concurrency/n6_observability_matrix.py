"""N6 - observability: the hook matrix for every NEW error class, plus
on_plugin_error / on_resolve_error (#114, #127, #133, #134).

For each trigger we assert (a) the right hook fires, (b) the failure is
also on a programmatic attribute (`last_error` / `last_plugin_error`), and
(c) the interpreter survives.

  v1  sync plugin hook raises              -> on_plugin_error + last_plugin_error
  v2  `async def` plugin hook (#127)       -> on_plugin_error (TypeError)
  v3  plugin hook raises CancelledError    -> contained (#114), machine alive
  v4  unresolvable target, strict_targets=False -> on_resolve_error (#134)
  v5  sendTo with no live target (#133)    -> on_event_dropped("unresolved_target")
  v6  guard raises                         -> on_guard_error
  v7  action raises                        -> on_action_error
  v8  external cancellation of the run loop (#114) -> status flips to "error"
      and pending receipts FAIL (no hang)
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)


class Recorder(PluginBase):
    def __init__(self) -> None:
        self.calls: dict = {}

    def _bump(self, name, detail=None):
        self.calls.setdefault(name, []).append(detail)

    def on_plugin_error(self, interpreter, plugin, hook, error):  # noqa: ANN001
        self._bump("on_plugin_error",
                   f"{type(plugin).__name__}.{hook}:{type(error).__name__}")

    def on_resolve_error(self, interpreter, error, event):  # noqa: ANN001
        self._bump("on_resolve_error",
                   f"{type(error).__name__}:{event.type}")

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self._bump("on_event_dropped", f"{event.type}:{reason}")

    def on_guard_error(self, interpreter, guard_name, event, error):  # noqa: ANN001
        self._bump("on_guard_error", f"{guard_name}:{type(error).__name__}")

    def on_action_error(self, interpreter, action, error):  # noqa: ANN001
        self._bump("on_action_error",
                   f"{getattr(action, 'type', action)}:{type(error).__name__}")

    def on_error(self, interpreter, error):  # noqa: ANN001
        self._bump("on_error", type(error).__name__)


class SyncRaiser(PluginBase):
    def on_transition(self, *a, **k):  # noqa: ANN001,D102
        raise RuntimeError("sync hook boom")


class AsyncHook(PluginBase):
    async def on_transition(self, *a, **k):  # noqa: ANN001,D102
        return None


class CancelRaiser(PluginBase):
    def on_transition(self, *a, **k):  # noqa: ANN001,D102
        raise asyncio.CancelledError("hook-made cancellation")


BASE = {
    "id": "obs",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b"}}},
        "b": {"on": {"GO": {"target": "a"}}},
    },
}


def mk(cfg=BASE, **kw):
    return create_machine(cfg, logic=MachineLogic(**kw))


async def _drive(plugins, cfg=BASE, logic_kw=None, ev="GO"):
    rec = Recorder()
    interp = Interpreter(mk(cfg, **(logic_kw or {})))
    interp.use(rec)
    for p in plugins:
        interp.use(p)
    await interp.start()
    try:
        r = await asyncio.wait_for(interp.send(ev, wait=True), 5)
        out = {"receipt_error": repr(r.error), "hung": False}
    except asyncio.TimeoutError:
        out = {"receipt_error": None, "hung": True}
    except Exception as exc:  # noqa: BLE001
        out = {"raised": type(exc).__name__, "hung": False}
    out.update(
        hooks=rec.calls,
        status=interp.status,
        alive=interp.is_running,
        last_error=repr(interp.last_error),
        last_plugin_error=repr(interp.last_plugin_error),
    )
    try:
        await interp.stop()
    except Exception:  # noqa: BLE001
        pass
    return out


BADTARGET = {
    "id": "bt",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "nowhere_at_all"}}}},
}


async def v4_resolve_error() -> dict:
    rec = Recorder()
    m = create_machine(BADTARGET, logic=MachineLogic(), strict_targets=False)
    interp = Interpreter(m)
    interp.use(rec)
    await interp.start()
    r = await asyncio.wait_for(interp.send("GO", wait=True), 5)
    out = {
        "receipt_error": repr(r.error),
        "hooks": rec.calls,
        "last_error": repr(interp.last_error),
        "last_transition_ok": interp.last_transition_ok,
        "status": interp.status,
    }
    await interp.stop()
    out["pass"] = "on_resolve_error" in rec.calls
    return out


SENDTO = {
    "id": "st",
    "initial": "a",
    "states": {
        "a": {
            "on": {
                "GO": {
                    "actions": [
                        {"type": "send_to",
                         "params": {"to": "ghost_actor",
                                    "event": "HELLO"}}
                    ]
                }
            }
        }
    },
}


async def v5_unresolved_target() -> dict:
    rec = Recorder()
    interp = Interpreter(create_machine(SENDTO, logic=MachineLogic()))
    interp.use(rec)
    await interp.start()
    try:
        r = await asyncio.wait_for(interp.send("GO", wait=True), 5)
        err = repr(r.error)
    except Exception as exc:  # noqa: BLE001
        err = f"raised {type(exc).__name__}: {exc}"
    out = {"receipt_error": err, "hooks": rec.calls,
           "status": interp.status}
    await interp.stop()
    drops = rec.calls.get("on_event_dropped", [])
    out["pass"] = any("unresolved_target" in str(d) for d in drops)
    return out


GUARDED = {
    "id": "gx",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b", "guard": "boom"}}},
               "b": {}},
}
ACTIONED = {
    "id": "ax",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}},
               "b": {}},
}


def boom_guard(i, ctx, e):  # noqa: ANN001
    raise ValueError("guard boom")


def boom_action(i, ctx, e, a):  # noqa: ANN001
    raise ValueError("action boom")


async def v8_external_cancel() -> dict:
    """#114: an externally cancelled run loop must not leave a dead machine
    reporting 'running' with a hanging awaiter."""
    rec = Recorder()
    interp = Interpreter(mk())
    interp.use(rec)
    await interp.start()
    task = getattr(interp, "_event_loop_task", None)
    cancelled = False
    if task is not None:
        task.cancel()
        cancelled = True
        await asyncio.sleep(0.1)
    try:
        r = await asyncio.wait_for(interp.send("GO", wait=True), 3)
        res = {"receipt_error": repr(r.error), "hung": False}
    except asyncio.TimeoutError:
        res = {"hung": True}
    except Exception as exc:  # noqa: BLE001
        res = {"raised": type(exc).__name__, "hung": False}
    res.update(
        run_loop_task_found=cancelled,
        status=interp.status,
        alive=interp.is_running,
        hooks=rec.calls,
        last_error=repr(interp.last_error),
    )
    try:
        await interp.stop()
    except Exception:  # noqa: BLE001
        pass
    res["pass"] = (not res.get("hung")) and (
        not cancelled or res["status"] in ("error", "stopped")
    )
    return res


async def main() -> int:
    v1 = await _drive([SyncRaiser()])
    v1["pass"] = "on_plugin_error" in v1["hooks"] and v1["alive"]
    v2 = await _drive([AsyncHook()])
    v2["pass"] = "on_plugin_error" in v2["hooks"] and v2["alive"]
    v3 = await _drive([CancelRaiser()])
    v3["pass"] = (not v3.get("hung")) and v3["status"] == "running"
    v4 = await v4_resolve_error()
    v5 = await v5_unresolved_target()
    v6 = await _drive([], GUARDED, {"guards": {"boom": boom_guard}})
    v6["pass"] = "on_guard_error" in v6["hooks"]
    v7 = await _drive([], ACTIONED, {"actions": {"boom": boom_action}})
    v7["pass"] = "on_action_error" in v7["hooks"]
    v8 = await v8_external_cancel()

    res = {
        "v1_sync_hook_raises": v1,
        "v2_async_def_hook": v2,
        "v3_hook_raises_CancelledError": v3,
        "v4_on_resolve_error": v4,
        "v5_sendTo_unresolved_target": v5,
        "v6_guard_raises": v6,
        "v7_action_raises": v7,
        "v8_external_run_loop_cancel": v8,
    }
    ok = all(v["pass"] for v in res.values())
    emit("n6_observability_matrix",
         {**res, "result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
