# -*- coding: utf-8 -*-
"""Re-check D5-soak-1 (round-4 track): check_shape() gap on history/actors/system.
CHANGELOG #146 claims these are now typed. Confirm FIXED at cec108b."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak_machine as sm
from xstate_statemachine import Interpreter, SnapshotCorruptError
from xstate_statemachine.exceptions import XStateMachineError

import asyncio

async def main():
    m = sm.build()
    interp = Interpreter(m)
    await interp.start()
    await interp.send({"type": "SUBMIT", "payload": {"qty": 5}}, wait=True)
    snap = interp.get_persisted_snapshot()
    results = {}
    for field in ("history", "actors", "system", "deferred", "status", "version"):
        bad = dict(snap)
        bad[field] = 3.14
        try:
            m2 = sm.build()
            Interpreter.from_snapshot(json.dumps(bad, default=repr), m2)
            results[field] = "ACCEPTED (no error)"
        except SnapshotCorruptError as exc:
            results[field] = f"OK: SnapshotCorruptError ({exc})"
        except XStateMachineError as exc:
            results[field] = f"OK (typed, not SnapshotCorruptError): {type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001
            results[field] = f"FAIL: untyped {type(exc).__name__}: {exc}"
    for k, v in results.items():
        print(f"{k}: {v}")
    await interp.stop()

asyncio.run(main())
