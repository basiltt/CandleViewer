# -*- coding: utf-8 -*-
"""R7-07 -- a root `get_persisted_snapshot()` harvests a CHILD actor's
half-applied context.

The #169 fix removed the `in flight AND illegal` conjunction at the ROOT
(`base_interpreter.py:1389`) but deliberately left legality as the test for
the CHILD branch (`base_interpreter.py:1393-1395`):

    if self._step_in_flight():
        if _seen is None:
            raise SnapshotMidStepError(self.id)     # root: in-flight alone
        if not self._configuration_is_legal():
            self._await_settled_for_snapshot()      # child: legality only

The comment immediately above it (`:1385-1391`) already states that
legality is necessary but NOT sufficient -- inside an entry action the new
leaf is already active (legal) while the context that entry is writing is
half-applied. That is exactly the child's situation here, so the torn blob
simply moved one level down the hierarchy.

This is the fully correct-usage shape: NO action hook, the root quiescent
and NOT in flight, the snapshot taken from an ordinary coroutine outside
every action, and the child's entry written as `async def` (the style the
documentation recommends). The torn blob nests under
`actors[...]["snapshot"]` and restores clean, because the child's
configuration IS legal.

Note the mechanism meant to cover this case, `_await_settled_for_snapshot`
(`base_interpreter.py:1280-1289`), is inoperative on the async engine --
it spins `time.sleep` on the event-loop thread. Here it is never even
entered, because the configuration is legal.

Derived from battle-221ce7c/semantics/repro/d7s3b_correct_usage_no_hook.py
and d7s3c_torn_blob_restores_clean.py.
Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == the root ACCEPTED a snapshot carrying a torn child context.
"""
import asyncio
import copy
import json
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

WATCHDOG = 60.0

PARENT = {
    "id": "par",
    "initial": "run",
    "states": {"run": {"invoke": {"src": "child", "id": "kid"}}},
}
CHILD = {
    "id": "kid",
    "initial": "x",
    "context": {"q": 0, "p": 0},
    "states": {
        "x": {"on": {"STEP": "y"}},
        "y": {"entry": ["set_q", "set_p"]},
    },
}


async def set_q(interp, ctx, evt, action_def):
    ctx["q"] = 100
    await asyncio.sleep(0.05)   # yields the loop MID-ENTRY, between the
                                # two halves of a paired context write


async def set_p(interp, ctx, evt, action_def):
    ctx["p"] = 101


def child_logic():
    return MachineLogic(actions={"set_q": set_q, "set_p": set_p})


def build_root():
    child = create_machine(copy.deepcopy(CHILD), logic=child_logic())
    return create_machine(
        copy.deepcopy(PARENT), logic=MachineLogic(services={"child": child})
    )


def torn(ctx):
    return (ctx.get("q", 0) > 0) != (ctx.get("p", 0) > 0)


async def main():
    root = await Interpreter(build_root()).start()
    kid = next(a for k, a in root._actors.items() if k.endswith("kid"))

    task = asyncio.ensure_future(kid.send("STEP", wait=True))
    await asyncio.sleep(0.02)   # child is now mid-entry: q written, p not

    print("root in flight during child entry : %s" % root._step_in_flight())
    print("kid  in flight during child entry : %s" % kid._step_in_flight())

    verdict, sub = None, None
    try:
        blob = root.get_persisted_snapshot()
        sub = list((blob.get("actors") or {}).values())[0]["snapshot"]
        ctx = sub["context"]
        verdict = "ACCEPTED"
        print("root snapshot during child entry  : ACCEPTED child=%s ctx=%s%s"
              % (sub["state_ids"], ctx, "   >>> TORN" if torn(ctx) else ""))
    except Exception as exc:
        verdict = type(exc).__name__
        print("root snapshot during child entry  : REFUSED (%s)" % verdict)

    await task
    settled = dict(kid.context)
    print("settled truth                     : child=%s ctx=%s"
          % (sorted(kid.current_state_ids), settled))

    restored_clean = False
    if verdict == "ACCEPTED" and torn(sub["context"]):
        rb = await Interpreter.from_snapshot(
            json.dumps(sub), create_machine(copy.deepcopy(CHILD),
                                            logic=child_logic())
        ).start()
        restored_clean = rb.last_error is None
        print("torn blob restores                : %s ctx=%s "
              "last_error=%r status=%r"
              % (sorted(rb.current_state_ids), dict(rb.context),
                 rb.last_error, rb.status))
        await rb.stop()

    await root.stop()
    print()
    if verdict == "ACCEPTED" and torn(sub["context"]):
        print("REPRODUCED: with the root settled and NOT in flight, no action "
              "hook and no plugin, the root snapshot ACCEPTED a child blob "
              "carrying %s against settled truth %s%s."
              % (sub["context"], settled,
                 "; it restores clean with last_error=None"
                 if restored_clean else ""))
        print("EXPECTED  : the child branch applies the same in-flight test "
              "the root now uses (base_interpreter.py:1389) rather than a "
              "legality test, refusing with SnapshotMidStepError.")
        return 1
    print("NOT reproduced (verdict=%r)." % (verdict,))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(asyncio.wait_for(main(), WATCHDOG)))
