"""D13-persistence-1 repro (xstate-statemachine 0.9.0).

A malformed v3 `chain_trips` field escapes `from_snapshot` as a RAW
`ValueError` / `TypeError` instead of the library's `SnapshotCorruptError`.

Every other envelope field added before #226 -- `version`, `status`,
`state_ids`, `context`, `pending_events`, `scheduled_sends`, `deferred` --
is shape-checked and reported as `SnapshotCorruptError`.  The two fields
#226 introduced are not: `base_interpreter.py:1993` does a bare
`int(snapshot.get("chain_trips") or 0)` after the validator has run.

Impact: a caller whose restore loop does the documented
`except SnapshotCorruptError: <quarantine the blob>` does NOT catch a
corrupt chain-trip field, so a truncated / partially-written journal record
escapes as an unexpected exception type.

stdlib + xstate_statemachine only.
"""
import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotCorruptError

CFG = {"id": "d13", "initial": "a", "states": {"a": {"on": {"P": "a"}}}}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def main() -> int:
    i = Interpreter(build())
    await i.start()
    raw = i.get_persisted_snapshot()
    base = json.loads(raw) if isinstance(raw, str) else raw
    await i.stop()

    print("envelope version:", base.get("version"))
    print("chain_trips present:", "chain_trips" in base)

    bad = 0
    for value in ("NaN", [1, 2], {"a": 1}, "1e3"):
        blob = dict(base)
        blob["chain_trips"] = value
        try:
            Interpreter.from_snapshot(
                json.dumps(blob), build(), verify_machine_hash=False
            )
            print(f"  chain_trips={value!r:12} -> ACCEPTED")
        except SnapshotCorruptError as exc:
            print(f"  chain_trips={value!r:12} -> SnapshotCorruptError (ok)")
        except Exception as exc:  # noqa: BLE001
            bad += 1
            print(
                f"  chain_trips={value!r:12} -> RAW "
                f"{type(exc).__name__}: {exc}"
            )

    # control: the same corruption in an OLDER field is reported properly
    ctl = dict(base)
    ctl["deferred"] = 5
    try:
        Interpreter.from_snapshot(
            json.dumps(ctl), build(), verify_machine_hash=False
        )
        print("  control deferred=5 -> ACCEPTED (unexpected)")
    except SnapshotCorruptError:
        print("  control deferred=5 -> SnapshotCorruptError (the contract)")

    # `last_chain_error` is not shape-checked either: a dict is str()'d
    lce = dict(base)
    lce["last_chain_error"] = {"not": "a message"}
    k = Interpreter.from_snapshot(
        json.dumps(lce), build(), verify_machine_hash=False
    )
    print("  last_chain_error={'not': 'a message'} -> latched as",
          repr(str(k.last_chain_error)))

    print("\nVERDICT:", "REPRODUCED" if bad else "not reproduced",
          f"({bad} raw leaks)")
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
