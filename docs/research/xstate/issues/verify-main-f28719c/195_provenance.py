"""Verify #195 on f28719c: DoneEvent/ErrorEvent/AfterEvent carry provenance;
a hand-built one is refused under strict, and restore_event() only trusts a
record explicitly marked "engine": true.

Matrix: {def, async def} service x {Interpreter, SyncInterpreter} where the
engine supports the service kind (SyncInterpreter refuses async def
services, so that cell is service=def only; the sync engine is still
exercised for provenance/restore checks using a def service).

Standalone (stdlib + xstate_statemachine only).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent, AfterEvent, restore_event, is_system_event
from xstate_statemachine.exceptions import UnknownEventError

FAIL: list[str] = []
ROWS: list[dict] = []

SPEC = {
    "id": "r195", "initial": "a", "strict": True, "onUnhandled": "error",
    "states": {
        "a": {"invoke": [{"id": "k", "src": "svc", "onDone": {"target": "done_", "actions": ["stash"]}}]},
        "done_": {},
    },
}


def build(kind: str):
    def svc_def(i, c, e):
        time.sleep(30)

    async def svc_async(i, c, e):
        await asyncio.sleep(30)

    def stash(i, c, e, a):
        c["got"] = getattr(e, "data", None)

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(services={"svc": svc_def if kind == "def" else svc_async}, actions={"stash": stash}),
    )


def refused(fn, *a, **kw) -> bool:
    try:
        fn(*a, **kw)
        return False
    except UnknownEventError:
        return True


async def async_cell(kind: str):
    i = Interpreter(build(kind))
    await asyncio.wait_for(i.start(children_timeout=0.5), 10)
    await asyncio.sleep(0.02)
    before = sorted(i.current_state_ids)
    forged = DoneEvent(type="done.invoke.k", data={"forged": True}, src="k")
    ok = False
    try:
        await asyncio.wait_for(i.send(forged), 5)
    except UnknownEventError:
        ok = True
    except Exception:
        pass
    await asyncio.sleep(0.05)
    after = sorted(i.current_state_ids)
    moved = after != before
    row = {"engine": "async", "service": kind, "refused": ok, "moved": moved,
           "is_system_event_forged": is_system_event(forged)}
    ROWS.append(row)
    if moved:
        FAIL.append(f"async/{kind}: forged DoneEvent drove onDone")
    if not ok:
        FAIL.append(f"async/{kind}: forged DoneEvent NOT refused under strict")
    if is_system_event(forged):
        FAIL.append(f"async/{kind}: hand-built DoneEvent reports is_system_event True")
    await asyncio.wait_for(i.stop(), 10)


async def async_restore_cell(kind: str, mark_engine: bool):
    rec = {"kind": "done", "type": "done.invoke.k", "data": {"forged": True}, "src": "k"}
    if mark_engine:
        rec["engine"] = True
    ev = restore_event(rec)
    i = Interpreter(build(kind))
    await asyncio.wait_for(i.start(children_timeout=0.5), 10)
    await asyncio.sleep(0.05)
    before = sorted(i.current_state_ids)
    raised = None
    try:
        await asyncio.wait_for(i.send(ev), 5)
    except UnknownEventError as e:
        raised = e
    except Exception:
        pass
    await asyncio.sleep(0.2)
    after = sorted(i.current_state_ids)
    moved = after != before
    row = {"engine": "async", "service": kind, "restore_marked_engine": mark_engine,
           "is_system_event": is_system_event(ev), "moved": moved, "refused": raised is not None}
    ROWS.append(row)
    if mark_engine:
        # genuine round-trip: should be trusted (is_system_event True) and
        # DOES drive onDone since it's treated as the real completion.
        if not is_system_event(ev):
            FAIL.append("restore_event(engine=True) not trusted as system event")
    else:
        if is_system_event(ev):
            FAIL.append("restore_event(no engine marker) forged as trusted system event")
        if moved:
            FAIL.append(f"restore/async/{kind}: unmarked restored DoneEvent drove onDone (forgery succeeded)")
        if raised is None:
            FAIL.append(f"restore/async/{kind}: unmarked restored DoneEvent not refused under strict")
    await asyncio.wait_for(i.stop(), 10)


def sync_cell():
    i = SyncInterpreter(build("def"))
    i.start()
    time.sleep(0.02)
    before = sorted(i.current_state_ids)
    forged = DoneEvent(type="done.invoke.k", data={"forged": True}, src="k")
    ok = False
    try:
        i.send(forged)
    except UnknownEventError:
        ok = True
    except Exception:
        pass
    after = sorted(i.current_state_ids)
    moved = after != before
    ROWS.append({"engine": "sync", "service": "def", "refused": ok, "moved": moved,
                 "is_system_event_forged": is_system_event(forged)})
    if moved:
        FAIL.append("sync/def: forged DoneEvent drove onDone")
    if not ok:
        FAIL.append("sync/def: forged DoneEvent NOT refused under strict")
    i.stop()

    # restore_event on sync engine too
    rec = {"kind": "done", "type": "done.invoke.k", "data": {"forged": True}, "src": "k"}
    ev = restore_event(rec)
    i2 = SyncInterpreter(build("def"))
    i2.start()
    time.sleep(0.02)
    before2 = sorted(i2.current_state_ids)
    raised = None
    try:
        i2.send(ev)
    except UnknownEventError as e:
        raised = e
    except Exception:
        pass
    after2 = sorted(i2.current_state_ids)
    moved2 = after2 != before2
    ROWS.append({"engine": "sync", "service": "def", "restore_marked_engine": False,
                 "is_system_event": is_system_event(ev), "moved": moved2, "refused": raised is not None})
    if is_system_event(ev):
        FAIL.append("sync restore(no engine marker) forged as trusted system event")
    if moved2:
        FAIL.append("sync restore: unmarked restored DoneEvent drove onDone")
    if raised is None:
        FAIL.append("sync restore: unmarked restored DoneEvent not refused under strict")
    i2.stop()


async def afterevent_check():
    a = AfterEvent(type="after.1.x")
    ROWS.append({"case": "AfterEvent hand-built", "is_system_event": is_system_event(a)})
    if is_system_event(a):
        FAIL.append("hand-built AfterEvent reports is_system_event True")


async def main() -> int:
    for kind in ("def", "async"):
        await async_cell(kind)
        await async_restore_cell(kind, mark_engine=False)
        await async_restore_cell(kind, mark_engine=True)
    sync_cell()
    await afterevent_check()
    print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2, default=str))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
