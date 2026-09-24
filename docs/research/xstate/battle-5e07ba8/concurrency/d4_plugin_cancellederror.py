"""D-concurrency-4 (minimal): a plugin hook raising `asyncio.CancelledError`
silently kills the run loop. `status` stays `"running"`, every awaiter of
`send(wait=True)` hangs forever, and every later event is dropped.

Mechanism
---------
1. `_SafePlugin._guarded` (base_interpreter.py:239-251) contains plugin
   failures by catching `Exception`. `CancelledError` derives from
   `BaseException`, so it is deliberately NOT caught -- correct, since
   swallowing a genuine cancellation would be a bug.

2. It therefore propagates out of the `on_transition` dispatch
   (base_interpreter.py:2464), up through `_execute_transition` and
   `_process_event`, into `_run_event_loop`.

3. `_run_event_loop` has (interpreter.py:1274-1275):

       except asyncio.CancelledError:
           raise

   with an explicit architecture note that it must NOT set
   `status = "stopped"`, because cancellation normally comes from an
   enclosing TaskGroup or supervisor and `stop()` owns the status
   transition. That reasoning is sound for cancellation arriving from
   OUTSIDE. It is wrong here: nobody cancelled anything. The
   `CancelledError` was MANUFACTURED by ordinary user code running inside
   the loop, and the loop cannot tell the two apart.

Result: the run-loop task completes with `CancelledError`, nothing drains
the queue, and the machine reports itself healthy:

    status                 == "running"      <-- WRONG
    is_running             == False           <-- correct (see below)
    current_state_ids      == {'px.b'}          (a real, plausible state)
    send("X", wait=True)   hangs forever -- no error, no timeout
    the pending receipt is never failed, because `_fail_all_receipts`
    only runs from `_teardown`, which only `stop()` reaches.

`is_running` (interpreter.py:296-299) DOES catch this: it additionally
requires `_event_loop_task` to exist and not be done, precisely so a
machine that cannot process events never claims it can. That check is the
mitigation and it works. But `status` -- the attribute the library's own
`stop()`, `_refuse_if_not_running()` and every documented example switch
on -- still reads `"running"`, so:

  * `_refuse_if_not_running()` returns False, so later events are QUEUED
    rather than refused: no `on_event_dropped` hook, no warning, and
    `queue_depth` grows without bound.
  * `_fail_all_receipts()` only runs from `_teardown`, which only `stop()`
    reaches, so a `wait=True` awaiter hangs with no error and no timeout.

This is the failure mode base_interpreter.py:2340 calls "permanently dead
and reporting itself healthy", reached by a different route.

A plugin does not need to be malicious. `raise asyncio.CancelledError` is
what you get from any hook that wraps `await`-based work with
`task.cancel()` semantics, from `concurrent.futures.CancelledError`
(which IS `asyncio.CancelledError` since 3.8), and from any library that
re-raises cancellation out of a synchronous shim.

Run:
    python d4_plugin_cancellederror.py
"""

from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"BACK": {"target": "a", "actions": ["bump"]}}},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1


class MetricsExporter(PluginBase):
    """An observer whose async transport surfaced a cancellation."""

    def on_transition(self, interpreter, from_states, to_states, transition):  # noqa: ANN001
        raise asyncio.CancelledError("metrics push was cancelled")


async def main() -> int:
    interp = Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    )
    interp.use(MetricsExporter())
    await interp.start()

    await interp.send("GO")  # fire-and-forget; the hook fires during this
    await asyncio.sleep(0.1)

    print("status            :", interp.status)
    print("is_running        :", interp.is_running)
    print("current_state_ids :", sorted(interp.current_state_ids))
    print("context           :", dict(interp.context))
    print("last_transition_ok:", interp.last_transition_ok)
    print("last_error        :", repr(interp.last_error))

    task = interp._event_loop_task
    print("run loop done     :", task.done() if task else None)
    if task is not None and task.done():
        try:
            task.result()
            print("run loop exception:", None)
        except BaseException as exc:  # noqa: BLE001
            print("run loop exception:", f"{type(exc).__name__}: {exc}")

    print("\nnow ask the 'running' machine a question:")
    try:
        r = await asyncio.wait_for(interp.send("BACK", wait=True), 3)
        print("  receipt:", r)
        hung = False
    except asyncio.TimeoutError:
        print("  send(BACK, wait=True) HUNG: no receipt, no error, no timeout")
        hung = True

    print("  queue_depth after:", interp.queue_depth)
    print("  context after    :", dict(interp.context))
    dead_but_healthy = hung and interp.status == "running"
    await interp.stop()

    print(
        "\nRESULT:",
        "FAIL - run loop dead, status reported 'running', awaiters hang forever"
        if dead_but_healthy
        else "PASS",
    )
    return 1 if dead_but_healthy else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
