# -*- coding: utf-8 -*-
"""R7-03 -- `await start()` does not return while an invoked child's
`async def` entry action is still running.

`Interpreter.start()` (interpreter.py:561) ends with

    await self._await_actor_bringups()

and `_await_actor_bringups` (interpreter.py:2586) gathers the bring-up
tasks with NO timeout. A bring-up awaits `child.start()`, i.e. arbitrary
user entry actions, so a child whose entry action awaits a lock, a socket
or a slow resolver holds the parent's `await start()` open for exactly as
long as that action runs. `status` reads "running" for the whole wait, and
there is no timeout knob anywhere in `src/`.

The run loop IS spawned before the await (interpreter.py:530), so the
interpreter is live during the window -- this script demonstrates that too:
an event sent while `start()` is still outstanding is accepted and
processed. That is what bounds the severity to High rather than Blocker,
and it is also the caller-side workaround (`asyncio.wait_for`).

Derived from probes/main-221ce7c/p2_start_awaits_child_bringup.py.
Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == `start()` was still outstanding after the bound, i.e. the
unbounded bring-up wait was observed.
"""
import asyncio
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

ENTRY_SLEEP = 30.0   # stands in for any awaiting user entry action
START_BOUND = 5.0    # our caller-side bound; without it start() waits 30s
WATCHDOG = 60.0      # hard stop so this script can never hang a CI runner

CHILD = {
    "id": "kid",
    "initial": "boot",
    "states": {"boot": {"entry": ["slow_entry"], "on": {"GO": {}}}},
}

PARENT = {
    "id": "par",
    "initial": "up",
    "context": {"poked": 0},
    "states": {
        "up": {
            "invoke": {"src": "kid", "id": "kid"},
            "on": {"POKE": {"actions": ["poke"]}},
        }
    },
}


async def slow_entry(interp, ctx, evt, action_def):
    await asyncio.sleep(ENTRY_SLEEP)


def poke(interp, ctx, evt, action_def):
    ctx["poked"] += 1


def build():
    child = create_machine(
        CHILD, logic=MachineLogic(actions={"slow_entry": slow_entry})
    )
    return create_machine(
        PARENT,
        logic=MachineLogic(services={"kid": child}, actions={"poke": poke}),
    )


async def probe():
    loop = asyncio.get_running_loop()
    it = Interpreter(build())
    t0 = loop.time()
    start_task = asyncio.ensure_future(it.start())

    hung = False
    try:
        await asyncio.wait_for(asyncio.shield(start_task), START_BOUND)
        print("start() returned in %.2fs" % (loop.time() - t0))
    except asyncio.TimeoutError:
        hung = True
        print("start() STILL not returned after %.1fs "
              "(child entry action sleeps %.0fs)" % (START_BOUND, ENTRY_SLEEP))
        print("status during the wait = %r" % (it.status,))

    # The run loop is already spawned, so the interpreter is live: show that
    # an event sent inside the window is accepted and processed.
    poked = None
    if hung:
        try:
            await asyncio.wait_for(it.send("POKE", wait=True), 2.0)
            poked = it.context.get("poked")
            print("POKE inside the window: accepted, ctx poked=%r" % (poked,))
        except Exception as exc:
            print("POKE inside the window: %s" % type(exc).__name__)

    start_task.cancel()
    try:
        await asyncio.wait_for(it.stop(), 5.0)
    except Exception as exc:
        print("stop(): %s" % type(exc).__name__)
    return hung, poked


async def main():
    print("child entry action awaits %.0fs; caller bound %.1fs.\n"
          % (ENTRY_SLEEP, START_BOUND))
    hung, poked = await asyncio.wait_for(probe(), WATCHDOG)
    print()
    if hung:
        print("REPRODUCED: `await start()` was still outstanding after %.1fs "
              "because _await_actor_bringups() gathers child bring-ups with "
              "no timeout, while status read 'running' and the run loop was "
              "already serving events (poked=%r)." % (START_BOUND, poked))
        print("EXPECTED  : start() returns within a bounded time, or exposes "
              "a timeout knob; a slow dependency must not hold it open for "
              "an arbitrary user-controlled duration.")
        return 1
    print("NOT reproduced: start() returned within the bound.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
