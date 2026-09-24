"""D13-persistence-2 repro (xstate-statemachine 0.9.0).

`on_interpreter_start` NEVER fires on a snapshot-restored interpreter, on
either engine and whether the plugin is attached with the new
`from_snapshot(plugins=...)` (#230) or with `.use()`.

`start()` on a restored actor takes the "resume" branch
(`interpreter.py:588`, `sync_interpreter.py:311/333`) which returns before
the `for plugin in self._plugins: plugin.on_interpreter_start(self)` call at
`interpreter.py:664` / `sync_interpreter.py:388`.  The hook's contract says
"called when the interpreter's `start()` method begins" and `start()` is the
documented way to resume a restored actor (its own docstring says so), so a
plugin that opens a DB handle / starts a metrics timer / registers the actor
in a supervisor in that hook is silently skipped for every restored machine
-- exactly the machines a restart-heavy deployment has most of.

`on_interpreter_stop` DOES fire, so a lifecycle plugin sees an unmatched
stop with no start.

stdlib + xstate_statemachine only.
"""
import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {"id": "d13b", "initial": "a", "states": {"a": {"on": {"P": "a"}}}}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


class Life(PluginBase):
    def __init__(self):
        self.events = []

    def on_interpreter_start(self, interpreter):
        self.events.append("start")

    def on_interpreter_stop(self, interpreter):
        self.events.append("stop")


def as_str(blob):
    return blob if isinstance(blob, str) else json.dumps(blob)


async def main() -> int:
    bad = []

    # ---- control: a FRESH interpreter, both engines --------------------
    spy = Life()
    i = Interpreter(build())
    i.use(spy)
    await i.start()
    await i.stop()
    print("async fresh  .use()           ->", spy.events)
    if "start" not in spy.events:
        bad.append("async fresh")

    spy = Life()
    s = SyncInterpreter(build())
    s.use(spy)
    s.start()
    s.stop()
    print("sync  fresh  .use()           ->", spy.events)
    if "start" not in spy.events:
        bad.append("sync fresh")

    # ---- the blob ------------------------------------------------------
    i = Interpreter(build())
    await i.start()
    blob = as_str(i.get_persisted_snapshot())
    await i.stop()

    # ---- restored: plugins= (the #230 route) ---------------------------
    spy = Life()
    k = Interpreter.from_snapshot(blob, build(), plugins=[spy])
    await k.start()
    await asyncio.sleep(0.05)
    await k.stop()
    print("async restored plugins=       ->", spy.events)
    if "start" not in spy.events:
        bad.append("async restored plugins=")

    # ---- restored: .use() before start() -------------------------------
    spy = Life()
    k = Interpreter.from_snapshot(blob, build())
    k.use(spy)
    await k.start()
    await asyncio.sleep(0.05)
    await k.stop()
    print("async restored .use()         ->", spy.events)
    if "start" not in spy.events:
        bad.append("async restored .use()")

    # ---- restored: sync engine -----------------------------------------
    spy = Life()
    k = SyncInterpreter.from_snapshot(blob, build(), plugins=[spy])
    k.start()
    k.stop()
    print("sync  restored plugins=       ->", spy.events)
    if "start" not in spy.events:
        bad.append("sync restored plugins=")

    print("\nmissing on_interpreter_start on:", bad)
    print("VERDICT:", "REPRODUCED" if bad else "not reproduced")
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
