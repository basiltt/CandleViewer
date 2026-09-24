"""(e) One BaseException case, isolated in its own process.

`_SafePlugin._guarded` (base_interpreter.py:239-251) catches `Exception`,
not `BaseException`. That is a deliberate and correct choice for
`CancelledError` -- swallowing cancellation would be a bug. This script
establishes what actually happens for each `BaseException` a hook can
realistically raise, one per process because the first one kills the
interpreter's run loop.

Reported per case:
  * does it escape the hook dispatch?
  * does the run loop die, and does `status` follow?
  * is a `send(..., wait=True)` awaiter resolved, or left hanging?
  * does `stop()` still work?

Usage:  python e3_baseexception_case.py <KeyboardInterrupt|SystemExit|MemoryError|CancelledError>
"""

from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"BACK": {"target": "a"}}},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1


CLASSES = {
    "KeyboardInterrupt": KeyboardInterrupt,
    "SystemExit": SystemExit,
    "MemoryError": MemoryError,
    "CancelledError": asyncio.CancelledError,
}


async def run(name: str) -> dict:
    exc_cls = CLASSES[name]

    class BadBase(PluginBase):
        def on_transition(self, i, f, t, tr):  # noqa: ANN001
            raise exc_cls("from a plugin hook")

    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"bump": bump})))
    i.use(BadBase())
    await i.start()

    out: dict = {"exception": name}
    try:
        r = await asyncio.wait_for(i.send("GO", wait=True), 3)
        out["receipt"] = [r.changed, repr(r.error)]
        out["awaiter"] = "resolved"
    except asyncio.TimeoutError:
        out["awaiter"] = "HUNG (wait=True never resolved in 3s)"
    except BaseException as exc:  # noqa: BLE001
        out["awaiter"] = f"raised {type(exc).__name__}: {exc}"

    await asyncio.sleep(0.05)
    out["status"] = i.status
    out["states"] = sorted(i.current_state_ids)
    out["context_n"] = i.context["n"]
    loop_task = i._event_loop_task
    out["run_loop_task_done"] = loop_task.done() if loop_task else None
    if loop_task is not None and loop_task.done():
        try:
            loop_task.result()
            out["run_loop_exception"] = None
        except BaseException as exc:  # noqa: BLE001
            out["run_loop_exception"] = f"{type(exc).__name__}: {exc}"

    # Is the machine still usable?
    try:
        r2 = await asyncio.wait_for(i.send("BACK", wait=True), 3)
        out["next_event"] = [r2.changed, repr(r2.error)]
    except asyncio.TimeoutError:
        out["next_event"] = "HUNG"
    except BaseException as exc:  # noqa: BLE001
        out["next_event"] = f"raised {type(exc).__name__}"

    try:
        await asyncio.wait_for(i.stop(), 3)
        out["stop"] = "ok"
    except asyncio.TimeoutError:
        out["stop"] = "HUNG"
    except BaseException as exc:  # noqa: BLE001
        out["stop"] = f"raised {type(exc).__name__}: {exc}"
    return out


def main() -> int:
    name = sys.argv[1]
    try:
        out = asyncio.run(run(name))
    except BaseException as exc:  # noqa: BLE001
        out = {
            "exception": name,
            "escaped_asyncio_run": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(out, indent=2, default=repr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
