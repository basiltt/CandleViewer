"""LC-21 - persisted snapshots carry no schema version or machine identity.

`get_persisted_snapshot()` emits exactly nine keys, none of which identify the
snapshot format or the machine that produced it. A snapshot written by an older
build, or by a *different* machine that happens to share state ids, restores
silently.
"""

from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, create_machine

CFG_V1 = {"id": "o", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
# A *different* machine that happens to reuse the id `o` and the state id `o.a`.
CFG_OTHER = {"id": "o", "initial": "a",
             "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}

EXPECTED_META = ("version", "schema_version", "machine_id", "machine_hash", "taken_at")


async def main() -> int:
    interp = await Interpreter(create_machine(CFG_V1)).start()
    snapshot = json.loads(interp.get_snapshot())
    await interp.stop()

    print(f"OBSERVED snapshot keys: {sorted(snapshot)}")
    for key in EXPECTED_META:
        print(f"OBSERVED   {key!r} present: {key in snapshot}")

    raised = None
    try:
        restored = Interpreter.from_snapshot(json.dumps(snapshot), create_machine(CFG_OTHER))
        await restored.start()
        state = sorted(restored.current_state_ids)
        await restored.stop()
    except Exception as exc:  # noqa: BLE001
        raised, state = type(exc).__name__, None
    print(f"OBSERVED restoring the snapshot into a *different* machine raised={raised} state={state}")

    # A hand-forged future-format snapshot is also accepted without complaint.
    forged = dict(snapshot, version=99, unknown_future_field={"x": 1})
    try:
        r2 = Interpreter.from_snapshot(json.dumps(forged), create_machine(CFG_V1))
        await r2.start()
        await r2.stop()
        print("OBSERVED a snapshot claiming version=99 restores without error")
    except Exception as exc:  # noqa: BLE001
        print(f"OBSERVED version=99 snapshot rejected: {type(exc).__name__}")

    print("EXPECTED get_persisted_snapshot() writes a 'version' (and ideally a "
          "machine-structure hash), and from_snapshot() rejects a version or "
          "hash it does not understand")
    return 1 if "version" not in snapshot else 0


sys.exit(asyncio.run(main()))
