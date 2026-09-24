"""R5-18 repro: new error classes (InvalidEventError, SnapshotMidStepError,
SnapshotSerializationError) raise correctly but reach NO plugin hook -- an
audit log built from hooks never sees them.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
import sys

from xstate_statemachine import (
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


class Spy(PluginBase):
    def __init__(self):
        self.calls = []


def _bind_spy_hooks():
    names = [
        n for n in dir(PluginBase)
        if n.startswith("on_") and callable(getattr(PluginBase, n))
    ]

    def make(name):
        def hook(self, *a, **kw):
            self.calls.append(name)

        return hook

    for n in names:
        setattr(Spy, n, make(n))
    return names


_bind_spy_hooks()

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def invalid_event_case():
    spy = Spy()
    i = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(spy)
    i.start()
    raised = None
    try:
        i.send(42)  # non-str event type -> InvalidEventError
    except Exception as e:  # noqa: BLE001
        raised = type(e).__name__
    i.stop()
    error_hook_fired = any(
        "error" in c or "failed" in c or "dropped" in c for c in spy.calls
    )
    return raised, sorted(set(spy.calls)), error_hook_fired


def midstep_case():
    spy = Spy()
    res = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            res["raise"] = "NO-RAISE"
        except Exception as ex:  # noqa: BLE001
            res["raise"] = type(ex).__name__

    cfg = {
        "id": "ms",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["grab"]}}},
            "b": {},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"grab": grab}))
    i = SyncInterpreter(m)
    i.use(spy)
    i.start()
    i.send("GO")
    i.stop()
    error_hook_fired = any(
        "error" in c or "failed" in c or "dropped" in c for c in spy.calls
    )
    return res.get("raise"), sorted(set(spy.calls)), error_hook_fired


def main() -> int:
    raised1, hooks1, fired1 = invalid_event_case()
    raised2, hooks2, fired2 = midstep_case()

    print("OBSERVED:")
    print(f"  send(42) raised            : {raised1}")
    print(f"  hooks seen (InvalidEvent)   : {hooks1}")
    print(f"  error-shaped hook fired     : {fired1}")
    print(f"  mid-action snapshot raised  : {raised2}")
    print(f"  hooks seen (MidStep)        : {hooks2}")
    print(f"  error-shaped hook fired     : {fired2}")

    print("EXPECTED:")
    print("  both raises are true errors, AND a dedicated plugin hook (e.g.")
    print("  on_transition_failed / on_snapshot_error) fires so an audit log")
    print("  built from hooks alone observes them")

    fail = (raised1 == "InvalidEventError" and not fired1) or (
        raised2 == "SnapshotMidStepError" and not fired2
    )
    if fail:
        print("RESULT: FAIL - error raised but invisible to every plugin hook")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
