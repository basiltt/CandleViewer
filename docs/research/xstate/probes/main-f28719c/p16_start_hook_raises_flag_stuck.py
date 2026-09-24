"""P16 (STANDALONE): #199 raised the in-flight flag before
`on_interpreter_start` -- but on the SYNC engine there is no `finally`
around the hook, so a plugin whose `on_interpreter_start` raises leaves
`_is_processing = True` forever.

The interpreter is then permanently wedged: `get_persisted_snapshot()`
raises `SnapshotMidStepError` and every `send()` is queued instead of
processed, with `status` still whatever start() left.

The async engine sets the flag inside the guarded `try`, so its hook is
covered. Parity gap.

Exit 1 = sync flag stuck after a raising hook.
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic,
)
from xstate_statemachine.plugins import PluginBase

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


class Boom(PluginBase):
    def on_interpreter_start(self, interpreter):
        raise RuntimeError("plugin blew up")


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


def run_sync():
    i = SyncInterpreter(build())
    i.use(Boom())
    try:
        i.start()
    except RuntimeError as exc:
        pass
    flag = i._is_processing
    return flag


async def run_async():
    i = Interpreter(build())
    i.use(Boom())
    try:
        await i.start()
    except RuntimeError:
        pass
    flag = i._processing
    try:
        await i.stop()
    except Exception:
        pass
    return flag


s = run_sync()
a = asyncio.run(asyncio.wait_for(run_async(), 15.0))
print(f"sync  _is_processing stuck after raising start hook: {s}")
print(f"async _processing    stuck after raising start hook: {a}")
print("VERDICT:", "SYNC FLAG STUCK (bug)" if s and not a else ("both stuck" if s and a else "ok"))
sys.exit(1 if s else 0)
