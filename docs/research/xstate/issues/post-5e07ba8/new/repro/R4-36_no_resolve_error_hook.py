"""R4-36: StateNotFoundError under strict_targets=False has no dedicated
plugin hook.

When a transition's target cannot be resolved (allowed because the machine
was built with strict_targets=False), the interpreter surfaces the failure
via Receipt.error / last_error and an ERROR log record, but no plugin
on_* hook fires for it -- unlike action failures (on_action_error) and
guard failures (on_guard_error), which both have a dedicated hook.

Exits 1 (defect present: no dedicated hook fired) while the gap exists,
0 once a hook such as on_resolve_error is added and fires here.
"""
import sys

from xstate_statemachine import (
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def on_action_error(self, interpreter, action, error):
        self.calls.append("on_action_error")

    def on_guard_error(self, interpreter, guard_name, event, error):
        self.calls.append("on_guard_error")

    def on_error(self, interpreter, error):
        self.calls.append("on_error")

    def on_transition_failed(self, interpreter, transition, failed_actions):
        self.calls.append("on_transition_failed")


def main() -> int:
    cfg = {
        "id": "m_snf",
        "initial": "a",
        "states": {"a": {"on": {"GO": "does.not.exist"}}},
    }
    # strict_targets=False permits an unresolved literal target string to
    # reach runtime instead of failing machine construction.
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()

    receipt = interp.send("GO", wait=True)

    print("OBSERVED:")
    print(f"  receipt.error        = {receipt.error!r}")
    print(f"  last_transition_ok   = {interp.last_transition_ok}")
    print(f"  last_error           = {interp.last_error!r}")
    print(f"  plugin hooks fired   = {rec.calls}")

    # The failure is visible via receipt/last_error, but no dedicated
    # resolve-error hook (e.g. on_resolve_error) fired -- unlike the action-
    # and guard-error paths, which both call a dedicated plugin hook.
    dedicated_hook_fired = any(
        name not in ("on_error",) for name in rec.calls
    ) and any("resolve" in name for name in rec.calls)

    print(
        "\nEXPECTED: a dedicated hook (e.g. on_resolve_error) fires, "
        "mirroring on_action_error / on_guard_error"
    )

    if dedicated_hook_fired:
        print("RESULT: dedicated resolve-error hook fired -- fixed")
        return 0
    else:
        print("RESULT: no dedicated resolve-error hook fired -- defect present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
