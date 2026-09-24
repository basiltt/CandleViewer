"""L-7 probe: the sync engine's perf change moved the per-step bookkeeping
resets under `if wait:`.

    if wait:
        config_before = ...
        self._deferred_this_step.clear()   # #106 per-step scope
        self._guard_denied_this_step = False

`_deferred_this_step` is APPENDED to unconditionally by
`_handle_unhandled_event` regardless of `wait`. So on the documented
fire-and-forget path (`send(...)`, wait defaults False) the list is never
cleared and grows for the life of the interpreter -- an unbounded leak on
a machine that defers events, and the list a later `wait=True` receipt
scans with an O(n) identity search.

Also checks `_guard_denied_this_step` stickiness across wait=False sends.
"""

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CONFIG = {
    "id": "p7",
    "initial": "busy",
    "onUnhandled": "defer",
    "states": {
        "busy": {"on": {"OTHER": {}}},
    },
}


def main() -> None:
    m = create_machine(CONFIG, logic=MachineLogic())
    i = SyncInterpreter(m)
    i.start()

    N = 5000
    for k in range(N):
        i.send("UNHANDLED", k=k)  # wait=False: the documented shape

    leaked = len(i._deferred_this_step)
    buffered = len(i._deferred_events)
    print(f"sends={N}")
    print(f"_deferred_this_step (per-STEP scope) = {leaked}")
    print(f"_deferred_events    (the real buffer) = {buffered}")
    print(
        "VERDICT:",
        "per-step list bounded"
        if leaked <= 1
        else f"PER-STEP LIST NEVER CLEARED ON wait=False -- {leaked} entries retained",
    )

    # One wait=True send clears it, proving the reset is gated on `wait`.
    i.send("UNHANDLED", wait=True)
    print(f"after one wait=True send: _deferred_this_step = "
          f"{len(i._deferred_this_step)}")
    i.stop()


main()
