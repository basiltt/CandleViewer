"""R11-08 (STANDALONE): restore then re-persist WITHOUT `start()` silently drops
every armed delayed self-send -- the exact failure #213 was filed to fix,
re-appearing one hop later.

`from_snapshot` parks the v3 `scheduled_sends` records in
`interpreter._restored_self_sends`. Only `start()` converts them into live armed
sends via `_rearm_restored_self_sends`, which also CONSUMES the list.
`get_persisted_snapshot` builds `scheduled_sends` from `self._armed_self_sends`
only (`_persist_scheduled_sends`) -- the LIVE dict, which is empty before
`start()`. The parked list is written by neither path.

So: snapshot (1 record) -> restore -> re-persist without start() -> 0 records.
A journal-compaction or snapshot-migration job that loads and re-writes without
starting destroys every deadline, silently.

The NORMAL hop is sound and is the control: snapshot -> restore -> START ->
re-persist preserves the record.

Exit 0 = the record survives the no-start re-persist (defect fixed).
Exit 1 = first hop carries a record, second hop (no start) carries none, and
         the control (with start) carries one.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

DELAY_MS = 60_000  # long enough that it cannot fire during the probe


def cfg() -> dict:
    arm = {
        "type": "raise",
        "params": {"event": "DEADLINE", "delay": DELAY_MS, "id": "sla"},
    }
    return {
        "id": "hop",
        "initial": "working",
        "states": {
            "working": {"entry": [arm], "on": {"DEADLINE": "expired"}},
            "expired": {"type": "final"},
        },
    }


def _sched(snap: dict) -> list:
    return list(snap.get("scheduled_sends") or [])


def _build(kind: str):
    def _noop(i, c, e, a=None):  # noqa: ANN001  plain def
        pass

    async def _noop_async(i, c, e, a=None):  # noqa: ANN001  async def
        pass

    fn = _noop if kind == "def" else _noop_async
    return create_machine(cfg(), logic=MachineLogic(actions={"noop": fn}))


async def one_lane(kind: str) -> dict:
    # --- hop 1: a live machine with an armed 60 s delayed self-send ----------
    live = Interpreter(_build(kind))
    await live.start()
    await asyncio.sleep(0.25)
    snap1 = live.get_persisted_snapshot()          # dict
    raw1 = json.dumps(snap1)                       # from_snapshot wants the string
    await live.stop()

    # --- hop 2a: restore, then re-persist WITHOUT start() (the defect) -------
    r_nostart = Interpreter.from_snapshot(raw1, _build(kind))
    snap2 = r_nostart.get_persisted_snapshot()

    # --- hop 2b: CONTROL -- restore, START, then re-persist ------------------
    r_start = Interpreter.from_snapshot(raw1, _build(kind))
    await r_start.start()
    await asyncio.sleep(0.15)
    snap3 = r_start.get_persisted_snapshot()
    await r_start.stop()

    return {
        "hop1_records": len(_sched(snap1)),
        "hop2_records_NO_start": len(_sched(snap2)),
        "hop2_records_WITH_start (control)": len(_sched(snap3)),
        "hop1_send_ids": [r.get("send_id") for r in _sched(snap1)],
        "hop2_send_ids_WITH_start": [r.get("send_id") for r in _sched(snap3)],
        "snapshot_version": snap1.get("version"),
    }


async def main() -> int:
    results = {}
    for kind in ("async def", "def"):
        results[kind] = await one_lane(kind)
    print(json.dumps(results, indent=2))

    dropped = [
        k
        for k, r in results.items()
        if r["hop1_records"] > 0 and r["hop2_records_NO_start"] == 0
    ]
    control_ok = all(
        r["hop2_records_WITH_start (control)"] == r["hop1_records"]
        for r in results.values()
    )
    print()
    print(f"lanes dropping the record on re-persist : {dropped}")
    print(f"control (restore -> start -> persist) ok: {control_ok}")
    print(f"REPRODUCED: {bool(dropped) and control_ok}")
    return 1 if dropped else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 40)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 40 s")
        sys.exit(2)
