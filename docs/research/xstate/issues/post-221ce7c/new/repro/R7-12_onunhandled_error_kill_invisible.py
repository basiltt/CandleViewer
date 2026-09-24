# -*- coding: utf-8 -*-
"""R7-12 -- under `onUnhandled: "error"`, an unhandled event terminates the
interpreter, but the sender's `Receipt` is success-shaped: `changed=False,
error=None, deferred=False, denied=False`. The caller that CAUSED the fatal
kill cannot tell from the return value that anything happened; only the
`on_unhandled_event` plugin hook and the `status`/`last_error` attributes
(polled separately, not returned to the sender) show it.

This is the same ergonomics class #153 fixed by adding `Receipt.denied` --
but that field does not cover the fatal-kill disposition.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13. Runs
on both engines (async first, then sync).

Exit code 1 == the killing send's own Receipt was fully success-shaped
(error=None, denied=False) even though it killed the interpreter. Exit code
0 == the receipt was discriminable.
"""
import asyncio

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CONFIG = {
    "id": "p",
    "initial": "a",
    "onUnhandled": "error",
    "context": {},
    "states": {"a": {"on": {"KNOWN": {}}}},
}


async def run_async() -> bool:
    m = create_machine(CONFIG, logic=MachineLogic())
    it = Interpreter(m)
    await it.start()
    before_running = it.is_running
    rcpt = await it.send("UNKNOWN_EVENT", wait=True)
    after_running = it.is_running
    print("async: before_running=%s after_running=%s receipt=%r last_error=%r "
          "status=%s" % (before_running, after_running, rcpt, it.last_error,
                          getattr(it, "status", "?")))
    success_shaped = (
        rcpt is not None
        and rcpt.error is None
        and rcpt.denied is False
        and rcpt.changed is False
    )
    await it.stop()
    return before_running and not after_running and success_shaped


def run_sync() -> bool:
    m = create_machine(CONFIG, logic=MachineLogic())
    it = SyncInterpreter(m)
    it.start()
    before_running = it.is_running
    rcpt = it.send("UNKNOWN_EVENT", wait=True)
    after_running = it.is_running
    print("sync : before_running=%s after_running=%s receipt=%r last_error=%r "
          "status=%s" % (before_running, after_running, rcpt, it.last_error,
                          getattr(it, "status", "?")))
    success_shaped = (
        rcpt is not None
        and rcpt.error is None
        and rcpt.denied is False
        and rcpt.changed is False
    )
    it.stop()
    return before_running and not after_running and success_shaped


async def main() -> int:
    async_bad = await run_async()
    sync_bad = run_sync()
    if async_bad or sync_bad:
        print("REPRODUCED: the send() that triggered the onUnhandled='error' "
              "fatal kill returned a success-shaped Receipt (error=None, "
              "denied=False, changed=False) even though the interpreter's own "
              "`status`/`is_running` flipped to dead. async_bad=%s sync_bad=%s"
              % (async_bad, sync_bad))
        print("EXPECTED  : the killing event's Receipt must be discriminable -- "
              "populate Receipt.error (and/or an explicit disposition) before "
              "the interpreter tears down, so the sender can tell its event "
              "just killed the machine.")
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
