"""Corruption hygiene: a malformed v3 field should surface as the library's
own `SnapshotCorruptError`, not as a raw stdlib exception.  Compare the NEW
#226 fields against the established ones.
"""
import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotCorruptError

CFG = {"id": "hg", "initial": "a", "states": {"a": {"on": {"P": "a"}}}}
def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())

CASES = [
    ("chain_trips", "NaN"),
    ("chain_trips", [1, 2]),
    ("chain_trips", {"a": 1}),
    ("chain_trips", "12"),
    ("last_chain_error", {"a": 1}),
    ("last_chain_error", [1]),
    ("version", "three"),
    ("status", 42),
    ("state_ids", "not-a-list"),
    ("context", "not-a-dict"),
    ("pending_events", "nope"),
    ("scheduled_sends", "nope"),
    ("deferred", 5),
]

async def main():
    i = Interpreter(build())
    await i.start()
    b = i.get_persisted_snapshot()
    base = json.loads(b) if isinstance(b, str) else b
    await i.stop()
    rows = []
    for key, val in CASES:
        f = dict(base)
        f[key] = val
        try:
            k = Interpreter.from_snapshot(json.dumps(f), build(),
                                          verify_machine_hash=False)
            rows.append({"key": key, "value": repr(val),
                         "outcome": "ACCEPTED",
                         "read_back": repr(getattr(k, "chain_trips", None))
                         if key == "chain_trips" else None})
        except SnapshotCorruptError as ex:
            rows.append({"key": key, "value": repr(val),
                         "outcome": "SnapshotCorruptError",
                         "msg": str(ex)[:90]})
        except Exception as ex:                 # noqa: BLE001
            rows.append({"key": key, "value": repr(val),
                         "outcome": f"RAW {type(ex).__name__}",
                         "msg": str(ex)[:90]})
    raw = [r for r in rows if r["outcome"].startswith("RAW")]
    print(json.dumps({"rows": rows, "raw_leaks": raw,
                      "VERDICT": "PASS" if not raw else "LEAK"}, indent=1))

asyncio.run(main())
