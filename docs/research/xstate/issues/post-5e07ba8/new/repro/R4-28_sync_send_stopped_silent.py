"""R4-28: send() to a stopped/done machine is silent on the sync engine
(no hook fires at all) while the async engine fires on_event_dropped(reason=
'not_running'). SyncInterpreter has no `not_running` drop-hook path in
send(); Interpreter's send() does.

Exits 1 while the sync engine fires zero hooks (received/unhandled/dropped)
for a send() after stop(), and the async engine fires on_event_dropped for
the identical scenario.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}}}
LOGIC = MachineLogic(actions={"noop": lambda i, c, e, a: None})


class Watch(PluginBase):
    def __init__(self):
        self.ev, self.un, self.dr = [], [], []

    def on_event_received(self, i, e):
        self.ev.append(e.type)

    def on_unhandled_event(self, i, e, *a, **k):
        self.un.append(e.type)

    def on_event_dropped(self, i, e, reason=None, *a, **k):
        self.dr.append((e.type, reason))


def sync_hooks():
    w = Watch()
    i = SyncInterpreter(create_machine(CFG, logic=LOGIC))
    i.use(w)
    i.start()
    i.stop()
    i.send("GO")
    return (w.ev, w.un, w.dr)


async def async_hooks():
    w = Watch()
    i = Interpreter(create_machine(CFG, logic=LOGIC))
    i.use(w)
    await i.start()
    await i.stop()
    await i.send("GO")
    await asyncio.sleep(0.05)
    return (w.ev, w.un, w.dr)


if __name__ == "__main__":
    s = sync_hooks()
    a = asyncio.run(async_hooks())
    print(f"OBSERVED: sync hooks={s}  async hooks={a}")
    print(
        "EXPECTED: parity -- either both fire on_event_dropped(reason='not_running'), "
        "or both raise a typed InterpreterStoppedError"
    )
    sync_silent = s == ([], [], [])
    async_dropped = a[2] != []
    if sync_silent and async_dropped:
        print("FAIL: sync send() after stop() is silent (no hook at all); async fires on_event_dropped")
        sys.exit(1)
    print("PASS: engines are at parity for send() after stop()")
    sys.exit(0)
