# Restore then re-persist without `start()` silently drops every armed delayed self-send — #213's own failure mode, one hop later

**Severity:** Medium
**Build:** `main` @ `c78ce99` (merge of PR #217, `fix/0.8.1-round10`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory.
**Both `def` and `async def` action spellings exercised — the defect is present on both.**
**r11:** R11-08 · **Labels:** bug, severity/medium, area/interpreter, persistence, timers

---

## Summary

#213's v3 `scheduled_sends` round-trip is exact — we verified 600/600 trials carrying the right `remaining_ms` (±0.5 ms) and `send_id` and firing not early, not late, exactly once. This report is about the **second hop**.

`from_snapshot` parks the restored records in `interpreter._restored_self_sends`. Only `start()` converts them into live armed sends via `_rearm_restored_self_sends`, which also **consumes** the list. But `get_persisted_snapshot` builds `scheduled_sends` from `self._armed_self_sends` only (`_persist_scheduled_sends`) — the **live** dict, which is empty before `start()`.

The parked list is therefore written by neither path:

```
snapshot (1 record)  ->  from_snapshot  ->  get_persisted_snapshot  ->  0 records
```

The normal hop is sound and serves as the control: `snapshot -> restore -> start() -> re-persist` preserves the record and its `send_id`.

## Observed

```json
{
  "async def": {
    "hop1_records": 1,
    "hop2_records_NO_start": 0,
    "hop2_records_WITH_start (control)": 1,
    "hop1_send_ids": ["sla"],
    "hop2_send_ids_WITH_start": ["sla"],
    "snapshot_version": 3
  },
  "def": {
    "hop1_records": 1,
    "hop2_records_NO_start": 0,
    "hop2_records_WITH_start (control)": 1,
    "hop1_send_ids": ["sla"],
    "hop2_send_ids_WITH_start": ["sla"],
    "snapshot_version": 3
  }
}
```

Both lanes drop the record; the control preserves it, `send_id` and all. A 300-machine property run over the *normal* hop shows 0 failures and 0 missing records, so this is specific to the restore→re-persist path.

## Why it matters

Loading a snapshot and writing it back **without starting an interpreter** is not an exotic operation — it is what a journal-compaction job does, what a snapshot-migration job does when moving between storage backends, and what any offline "rewrite these blobs" utility does. None of those has a reason to `start()` the machine; starting it would arm real timers and run real work, which is exactly what such a job wants to avoid.

The result is that a maintenance job silently destroys every deadline in every snapshot it touches. There is no error, no warning, and nothing in `last_error`; the rewritten blob is structurally valid and restores into a legal configuration. The loss surfaces later as a deadline that simply never fires — which is the precise failure mode #213 was filed to fix.

## Suggested direction

Have `_persist_scheduled_sends` union `self._armed_self_sends` with any **unconsumed** `self._restored_self_sends`, so a record that has been restored but not yet re-armed still serialises. That keeps the invariant "a snapshot round-trips through `from_snapshot` + `get_persisted_snapshot` without loss" true regardless of whether `start()` has run.

Alternatively, if re-persisting an un-started interpreter is considered out of contract, raising on it would at least make the loss loud — but the union seems both cheaper and more useful, since the parked records are already in memory and already in the right shape.

## Environment

CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv, `xstate-statemachine` `main` @ `c78ce99`. `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.

## Repro

Standalone — stdlib plus `xstate_statemachine` only, all helpers inlined, runs from any working directory. Uses a 60 s delay so the send cannot fire during the probe. **Exit 1 = defect present** (hop 1 carries a record, the no-start re-persist carries none, and the `start()` control carries one); exit 0 = fixed.

```python
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
```

## Acceptance criteria

- `test_repersist_without_start_preserves_scheduled_sends__def` / `__async_def` — snapshot a machine with an armed delayed self-send, `from_snapshot`, then `get_persisted_snapshot` **without** `start()`; assert the `scheduled_sends` record (and its `send_id` and remaining delay) survives.
- `test_repersist_with_start_unchanged` — regression guard for the control path, which is correct today.
- `test_double_repersist_is_idempotent` — restore → re-persist → restore → re-persist; the record must survive both hops rather than being consumed by the first.
- `test_remaining_ms_not_reset_by_repersist` — the remaining delay must continue to count down from the original deadline rather than restarting.
