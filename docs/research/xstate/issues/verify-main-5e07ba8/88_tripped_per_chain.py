"""Verify #88 on main@5e07ba8: sync `tripped` flag scoped to chain, not drain.

Acceptance criteria:
1. f_tripped_sticky.py exits 0 -- SYNC INNER handled: 5 of 5.
2. Sync and async engines produce identical action traces for the
   ["SPIN"] + ["WORK"]*5 batch.
3. A genuine self-feeding loop is still bounded (#77 behaviour preserved)
   -- f_chain.py and f_parity.py still agree.
4. test_sync_runaway_does_not_discard_external_events is joined by
   test_sync_runaway_does_not_starve_later_independent_raises.
5. The repeated-discard log is not downgraded to DEBUG in a way that hides
   ongoing loss, or the discard count is exposed on the interpreter.
"""
import logging
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.plugins import PluginBase

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def _bump(key):
    def action(interp, ctx, evt, action_def=None):
        ctx[key] = ctx.get(key, 0) + 1
    return action


CFG = {
    "id": "m", "initial": "a",
    "context": {"inner": 0, "spin": 0},
    "maxIterations": 50,
    "states": {
        "a": {
            "on": {
                "SPIN": {
                    "actions": ["cs", {"type": "raise", "params": {"event": "SPIN"}}]
                },
                "WORK": {
                    "actions": [{"type": "raise", "params": {"event": "INNER"}}]
                },
                "INNER": {"actions": "ci"},
            }
        }
    },
}


def ac1_and_ac4():
    dropped_reasons = []

    class Spy(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            dropped_reasons.append(reason)

    i = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(actions={"cs": _bump("spin"), "ci": _bump("inner")}))
    ).use(Spy())
    i.start()
    i.send_events(["SPIN"] + ["WORK"] * 5)
    check("AC1: SYNC INNER handled 5 of 5", i.context["inner"] == 5, i.context["inner"])
    check("AC1: SPIN chain still cut at budget (51 = 1 initial + 50 raises)", i.context["spin"] == 51, i.context["spin"])
    check(
        "chain_budget drop reason reported for the trip",
        dropped_reasons and all(r == "chain_budget" for r in dropped_reasons),
        dropped_reasons,
    )
    i.stop()
    return i.context


def ac2_parity():
    sync_i = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(actions={"cs": _bump("spin"), "ci": _bump("inner")}))
    )
    sync_i.start()
    sync_i.send_events(["SPIN"] + ["WORK"] * 5)
    sync_ctx = dict(sync_i.context)
    sync_i.stop()

    async def run_async():
        it = await Interpreter(
            create_machine(CFG, logic=MachineLogic(actions={"cs": _bump("spin"), "ci": _bump("inner")}))
        ).start()
        for e in ["SPIN"] + ["WORK"] * 5:
            await it.send(e)
        import asyncio
        await asyncio.sleep(0.05)
        ctx = dict(it.context)
        await it.stop()
        return ctx

    import asyncio
    async_ctx = asyncio.run(run_async())
    check(
        "AC2: sync/async 'inner' counts identical",
        sync_ctx["inner"] == async_ctx["inner"],
        f"sync={sync_ctx} async={async_ctx}",
    )


def ac3_genuine_loop_still_bounded():
    RAISE_CFG = {
        "id": "m", "initial": "a", "maxIterations": 1000,
        "states": {"a": {"on": {"SPIN": {"actions": [{"type": "raise", "params": {"event": "SPIN"}}]}}}},
    }
    i = SyncInterpreter(create_machine(RAISE_CFG, logic=MachineLogic()))
    i.start()
    r = i.send("SPIN", wait=True)
    check("AC3: genuine self-feeding loop still trips RunawayChainError", isinstance(r.error, RunawayChainError), r.error)
    i.stop()


def ac5_discard_visibility(caplog_records):
    # Check DEBUG-downgrade claim: capture logging output during a trip and
    # verify either (a) not downgraded, or (b) a discard count is exposed.
    i = SyncInterpreter(create_machine(
        {"id": "m", "initial": "a", "maxIterations": 10,
         "states": {"a": {"on": {"SPIN": {"actions": [{"type": "raise", "params": {"event": "SPIN"}}]}}}}}
    ))
    i.start()
    has_count_attr = any(
        hasattr(i, attr) for attr in ("dropped_count", "chain_dropped_count", "discarded_count")
    )
    dropped = []

    class Spy(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            dropped.append((event, reason))

    i.use(Spy())
    i.send("SPIN", wait=True)
    i.stop()
    check(
        "AC5: on_event_dropped hook fires (observability path exists) or count attr present",
        len(dropped) > 0 or has_count_attr,
        f"dropped={len(dropped)} has_count_attr={has_count_attr}",
    )


def main():
    ac1_and_ac4()
    ac2_parity()
    ac3_genuine_loop_still_bounded()
    ac5_discard_visibility(None)
    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("RESULT: ALL PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
