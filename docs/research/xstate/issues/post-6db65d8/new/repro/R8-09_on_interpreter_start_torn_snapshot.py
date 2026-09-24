"""R8-09 STANDALONE: `get_persisted_snapshot()` called from the
`on_interpreter_start` plugin hook returns a TORN blob -- `status:
"running"` with an EMPTY configuration -- on both engines.

#182 made the initial descent a guarded macrostep: `_processing`
(async)/`_is_processing` (sync) is set True before `_enter_states(...)`
runs, so a snapshot taken from an entry action or `on_action_execute` is
refused with `SnapshotMidStepError`. `on_interpreter_start` fires a few
lines EARLIER -- `status` has already been flipped to "running" but the
guard flag is not yet set and no state has been entered -- so the hook is
one step outside that window and the blob it can request is accepted, torn.

Source (interpreter.py, async engine):
    self.status = "running"
    ...
    for plugin in self._plugins:
        plugin.on_interpreter_start(self)   # <- guard not set yet
    ...
    self._processing = True
    await self._enter_states([self.machine], init_event)
Same shape in sync_interpreter.py: `on_interpreter_start` runs, THEN
`self._is_processing = True` is set for `_enter_states(...)`.

Exits 1 while any row from the hook reports `status=="running"` with an
empty `state_ids`/`configuration`; exits 0 once the hook is brought inside
the same in-flight window.
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
from xstate_statemachine.exceptions import SnapshotMidStepError

CFG = {
    "id": "r3b",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"entry": ["bump"], "invoke": {"src": "s", "onDone": {"target": "b"}}},
        "b": {},
    },
}


def bump(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


def make_service(kind):
    def svc(i, ctx, e):
        return {"v": 1}

    async def asvc(i, ctx, e):
        return {"v": 1}

    return svc if kind == "def" else asvc


class Recorder(PluginBase):
    def __init__(self):
        self.rows = []

    def on_interpreter_start(self, i):
        try:
            self.rows.append(("returned", i.get_persisted_snapshot()))
        except SnapshotMidStepError as e:
            self.rows.append(("refused", str(e)[:60]))


def mk(kind):
    return create_machine(
        CFG, logic=MachineLogic(actions={"bump": bump}, services={"s": make_service(kind)})
    )


async def one(kind, engine):
    p = Recorder()
    if engine == "async":
        i = Interpreter(mk(kind)).use(p)
        await asyncio.wait_for(i.start(), 10)
        live = i.get_persisted_snapshot()
        await i.stop()
    else:
        i = SyncInterpreter(mk(kind)).use(p)
        i.start()
        live = i.get_persisted_snapshot()
        i.stop()
    disp, blob = p.rows[0]
    row = {
        "engine": engine,
        "kind": kind,
        "disposition": disp,
        "status": blob.get("status") if disp == "returned" else None,
        "state_ids": blob.get("state_ids") if disp == "returned" else None,
        "configuration": blob.get("configuration") if disp == "returned" else None,
        "healthy_state_ids": live.get("state_ids"),
    }
    if disp == "returned":
        try:
            r = (
                Interpreter.from_snapshot(mk(kind), blob)
                if engine == "async"
                else SyncInterpreter.from_snapshot(mk(kind), blob)
            )
            row["restore"] = "ACCEPTED"
            row["restored_state_ids"] = sorted(getattr(r, "current_state_ids", []))
            row["restored_status"] = r.status
        except Exception as exc:
            row["restore"] = f"refused:{type(exc).__name__}"
    return row


async def main():
    rows = [await one(k, "async") for k in ("def", "async def")]
    rows.append(await one("def", "sync"))
    bad = [
        r
        for r in rows
        if r["disposition"] == "returned" and r["status"] == "running" and not r["state_ids"]
    ]
    result = "FAIL" if bad else "PASS"
    out = {"result": result, "rows": rows, "torn": bad}
    print(json.dumps(out, indent=2, default=str))
    print(f"OBSERVED: {len(bad)}/{len(rows)} rows torn ({result})")
    print(
        "EXPECTED: 0 -- get_persisted_snapshot() from on_interpreter_start must "
        "either refuse (SnapshotMidStepError) or return a settled, non-empty "
        "configuration, matching the #182 in-flight window"
    )
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
