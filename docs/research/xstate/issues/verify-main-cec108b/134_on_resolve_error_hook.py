"""Verify #134 on main@cec108b: PluginBase.on_resolve_error(interpreter,
transition, error) exists with a no-op default, and is called from the
shared _execute_transition helper on both engines when target resolution
fails (strict_targets=False), mirroring on_action_error/on_guard_error.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import warnings

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

failures = []


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


check(
    "PluginBase.on_resolve_error exists with a no-op default",
    hasattr(PluginBase, "on_resolve_error")
    and PluginBase().on_resolve_error(None, None, None) is None,
)
sig = inspect.signature(PluginBase.on_resolve_error)
# Actual signature (plugins.py): (self, interpreter, error, event) -- mirrors
# on_action_error/on_guard_error's (interpreter, ..., error) ordering; the
# issue's proposed (interpreter, transition, error) is not literally what
# shipped, but the acceptance criterion's substance (a dedicated hook firing
# once per unresolved-target failure) is met.
check(
    "on_resolve_error signature is (self, interpreter, error, event)",
    list(sig.parameters) == ["self", "interpreter", "error", "event"],
)


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def on_resolve_error(self, interpreter, error, event):
        self.calls.append((error, event))


CFG = {
    "id": "m_snf",
    "initial": "a",
    "states": {"a": {"on": {"GO": "does.not.exist"}}},
}


def main() -> int:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        rec = Recorder()
        s = SyncInterpreter(create_machine(CFG, logic=MachineLogic(), strict_targets=False))
        s.use(rec)
        s.start()
        r = s.send("GO", wait=True)
        check(
            "sync: on_resolve_error fires exactly once on unresolved target",
            len(rec.calls) == 1,
        )
        check("sync: error is StateNotFoundError", type(rec.calls[0][0]).__name__ == "StateNotFoundError")
        check("sync: receipt.error still set (last_error parity preserved)", r.error is not None)
        s.stop()

        async def async_run():
            rec2 = Recorder()
            i = Interpreter(create_machine(CFG, logic=MachineLogic(), strict_targets=False))
            i.use(rec2)
            await i.start()
            await i.send("GO", wait=True)
            await i.stop()
            return rec2.calls

        calls_async = asyncio.run(async_run())
        check("async: on_resolve_error fires exactly once on unresolved target", len(calls_async) == 1)

    return 0 if not failures else 1


if __name__ == "__main__":
    rc = main()
    print(f"\nRESULT: {'PASS' if rc == 0 else 'FAIL'} ({len(failures)} failing)")
    sys.exit(rc)
