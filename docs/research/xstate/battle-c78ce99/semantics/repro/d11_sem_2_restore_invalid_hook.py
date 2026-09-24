"""D11-semantics-2: #214's `on_invalid_event` never fires on the restore path.

The CHANGELOG for #214 states a restored user event refused by `strict` is
"reported (`on_invalid_event`, `last_error`) and the event dropped".
`last_error` IS set and the event IS dropped. But `_report_invalid_event`
iterates `self._plugins`, and `from_snapshot` constructs the interpreter
(base_interpreter.py:1822) and runs the whole restore -- including
`_admit_restored` -- BEFORE any caller can attach a plugin: there is no
`plugins=` parameter on `from_snapshot`, and `.use()` can only be called on
the object it returns, after the refusal has already happened.

So the hook half of the promise is structurally unreachable, and the
task's "exactly-once" observability requirement is "exactly-zero".

Exit 1 == reproduced. Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio, copy, json, logging, sys
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

CFG = {"id": "L", "initial": "a", "strict": True,
       "states": {"a": {"on": {"X": "b"}}, "b": {}}}


class Obs(PluginBase):
    def __init__(self) -> None:
        self.invalid: List[Any] = []

    def on_invalid_event(self, i, exc, raw):  # noqa: ANN001
        self.invalid.append((type(exc).__name__, getattr(raw, "type", raw)))


async def run(kind: str) -> Dict[str, Any]:
    def noop(i, c, e, a):  # noqa: ANN001
        pass

    async def noop_a(i, c, e, a):  # noqa: ANN001
        pass

    lg = MachineLogic(actions={"noop": noop_a if kind == "async" else noop})
    m0 = Interpreter(create_machine(copy.deepcopy(CFG), logic=lg))
    await m0.start(); await asyncio.sleep(0.05)
    snap = m0.get_persisted_snapshot(); await m0.stop()
    snap["pending_events"] = [{"type": "NOPE", "kind": "event"}]

    o = Obs()
    # The earliest a caller can possibly attach a plugin:
    m = Interpreter.from_snapshot(
        json.dumps(snap), create_machine(copy.deepcopy(CFG), logic=lg)
    ).use(o)
    await m.start(); await asyncio.sleep(0.2)
    res = {
        "last_error": type(m.last_error).__name__ if m.last_error else None,
        "event_dropped": not any("L.b" in s for s in m.current_state_ids),
        "on_invalid_event_calls": len(o.invalid),
        "from_snapshot_has_plugins_kwarg":
            "plugins" in Interpreter.from_snapshot.__doc__ if
            Interpreter.from_snapshot.__doc__ else False,
    }
    await m.stop()
    return res


async def main() -> int:
    out = {k: await run(k) for k in ("plain", "async")}
    repro = [k for k, v in out.items()
             if v["last_error"] == "UnknownEventError"
             and v["on_invalid_event_calls"] == 0]
    out["REPRODUCED"] = bool(repro)
    out["note"] = ("last_error is set and the event is dropped, but the "
                   "on_invalid_event half of #214's promise fires 0 times")
    print(json.dumps(out, indent=1))
    return 1 if repro else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
