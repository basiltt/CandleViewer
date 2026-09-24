"""D13-fuzz-1 repro -- a snapshot-RESTORED interpreter never fires
`on_interpreter_start` (nor `on_transition` for its initial configuration),
on either engine, whether the plugin arrives via `from_snapshot(plugins=)`
(#230) or `.use()`.

`Interpreter.start()` has two paths. A fresh interpreter falls through to
the normal descent, which fires `on_interpreter_start`. A restored one hits
the "resume a snapshot-restored interpreter" early-return at the top of
`start()` (interpreter.py:591-618 / sync_interpreter.py analogue), which
binds the loop, re-arms `scheduled_sends` and returns -- never touching the
plugin notification. #230 exists so a restore-time refusal reaches
`on_invalid_event`, but the hook that tells a plugin "a machine came up" is
silently skipped for exactly the machines an operator most wants to see.

CONTROL: the same plugin on a FRESH interpreter of the same chart.

Expected (correct): 'start' appears in BOTH logs.
Observed @ v0.9.0: 'start' appears only in the fresh log.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "d13",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {},
    },
}


def bump(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def bump_async(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


class Spy(PluginBase):
    def __init__(self):
        self.log = []

    def on_interpreter_start(self, interpreter):
        self.log.append("start")

    def on_event_received(self, interpreter, event):
        self.log.append(f"recv:{event.type}")

    def on_transition(self, interpreter, from_s, to_s, transition):
        self.log.append("transition")

    def on_interpreter_stop(self, interpreter):
        self.log.append("stop")


def logic(kind):
    return MachineLogic(
        actions={"bump": bump if kind == "def" else bump_async}
    )


async def async_cell(kind):
    m = create_machine(dict(CFG), logic=logic(kind))

    fresh_spy = Spy()
    fresh = Interpreter(m)
    fresh.use(fresh_spy)
    await fresh.start()
    blob = fresh.get_snapshot()
    await fresh.stop()

    plug_spy = Spy()
    r1 = Interpreter.from_snapshot(blob, m, plugins=[plug_spy])
    await r1.start()
    await r1.send("GO")
    await asyncio.sleep(0)
    await r1.stop()

    use_spy = Spy()
    r2 = Interpreter.from_snapshot(blob, m)
    r2.use(use_spy)
    await r2.start()
    await r2.send("GO")
    await asyncio.sleep(0)
    await r2.stop()

    return fresh_spy.log, plug_spy.log, use_spy.log


def sync_cell():
    m = create_machine(dict(CFG), logic=logic("def"))

    fresh_spy = Spy()
    fresh = SyncInterpreter(m)
    fresh.use(fresh_spy)
    fresh.start()
    blob = fresh.get_snapshot()
    fresh.stop()

    plug_spy = Spy()
    r1 = SyncInterpreter.from_snapshot(blob, m, plugins=[plug_spy])
    r1.start()
    r1.send("GO")
    r1.stop()

    return fresh_spy.log, plug_spy.log


async def main():
    print("D13-fuzz-1 -- on_interpreter_start is skipped on a restored start\n")
    bad = 0
    for kind in ("def", "async def"):
        fresh, plug, use = await async_cell(kind)
        print(f"  async engine / {kind}")
        print(f"    CONTROL fresh  .use()      : {fresh}")
        print(f"    RESTORED from_snapshot(plugins=): {plug}")
        print(f"    RESTORED .use()            : {use}")
        for label, log in (("plugins=", plug), (".use()", use)):
            if "start" not in log:
                bad += 1
                print(
                    f"    ==> DEFECT async/{kind}/{label}: "
                    f"on_interpreter_start never fired"
                )

    fresh, plug = sync_cell()
    print("  sync engine / def")
    print(f"    CONTROL fresh  .use()      : {fresh}")
    print(f"    RESTORED from_snapshot(plugins=): {plug}")
    if "start" not in plug:
        bad += 1
        print("    ==> DEFECT sync/def/plugins=: on_interpreter_start never fired")

    print(f"\nresult: {'FAIL' if bad else 'PASS'}  ({bad} cells)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
