"""Verify #134: PluginBase.on_resolve_error fires when a transition target
cannot be resolved under strict_targets=False, on both engines.
"""
import sys

from xstate_statemachine import MachineLogic, PluginBase, SyncInterpreter, create_machine
import asyncio
from xstate_statemachine import Interpreter

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def on_resolve_error(self, interpreter, error, event):
        self.calls.append(("on_resolve_error", type(error).__name__))


def test_sync():
    cfg = {
        "id": "m_snf",
        "initial": "a",
        "states": {"a": {"on": {"GO": "does.not.exist"}}},
    }
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = interp.send("GO", wait=True)
    interp.stop()
    return rec.calls, receipt


async def _async_main():
    cfg = {
        "id": "m_snf2",
        "initial": "a",
        "states": {"a": {"on": {"GO": "does.not.exist"}}},
    }
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = Recorder()
    i = Interpreter(machine)
    i.use(rec)
    await i.start()
    receipt = await i.send("GO", wait=True)
    await i.stop()
    return rec.calls, receipt


def main() -> int:
    calls, receipt = test_sync()
    print("sync engine hook calls:", calls, "receipt:", receipt)
    check(
        "criterion: on_resolve_error fires on SyncInterpreter for unresolved target",
        any(name == "on_resolve_error" for name, _ in calls),
    )

    calls2, receipt2 = asyncio.run(_async_main())
    print("async engine hook calls:", calls2, "receipt:", receipt2)
    check(
        "criterion: on_resolve_error fires on async Interpreter for unresolved target",
        any(name == "on_resolve_error" for name, _ in calls2),
    )

    check(
        "criterion: PluginBase.on_resolve_error exists with no-op default",
        hasattr(PluginBase(), "on_resolve_error"),
    )

    ok = all(c for _, c in results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
