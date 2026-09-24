"""LC-21 verification on xstate-statemachine 0.8.0.

CHANGELOG [wave 2 / #45]: "Snapshot envelope v1. Persisted snapshots gain
version, machine_id, machine_hash, and taken_at. from_snapshot refuses a
newer version with SnapshotVersionError and a mismatched id or hash with
SnapshotDriftError; from_snapshot(..., verify_machine_hash=False) opts out.
Unversioned 0.7.x payloads restore exactly as before."

This is a DEFAULT fix: version/machine_hash are always emitted, and drift
checking (verify_machine_hash=True) is the default. Also verifies the
opt-out and the legacy-unversioned-payload backward compat path.
"""

from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SnapshotDriftError,
    SnapshotVersionError,
    create_machine,
)

CFG_V1 = {"id": "o", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
# A *different* machine that happens to reuse the id `o` and the state id `o.a`.
CFG_OTHER = {"id": "o", "initial": "a",
             "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
# LC-23-style semantic drift: same ids, guard added to FILL-equivalent transition.
CFG_DRIFT = {"id": "o", "initial": "a",
             "states": {"a": {"on": {"GO": {"target": "b", "guard": "never"}}}, "b": {}}}
DRIFT_LOGIC = MachineLogic(guards={"never": lambda ctx, evt: False})

EXPECTED_META = ("version", "machine_id", "machine_hash", "taken_at")


async def main() -> int:
    interp = await Interpreter(create_machine(CFG_V1)).start()
    snapshot = json.loads(interp.get_snapshot())
    await interp.stop()

    print(f"OBSERVED snapshot keys: {sorted(snapshot)}")
    meta_present = {}
    for key in EXPECTED_META:
        meta_present[key] = key in snapshot
        print(f"OBSERVED   {key!r} present: {meta_present[key]}")
    all_meta_present = all(meta_present.values())

    # Different machine, same ids: default (verify_machine_hash=True) should raise drift.
    raised = None
    try:
        restored = Interpreter.from_snapshot(json.dumps(snapshot), create_machine(CFG_OTHER))
        await restored.start()
        state = sorted(restored.current_state_ids)
        await restored.stop()
    except Exception as exc:  # noqa: BLE001
        raised, state = type(exc).__name__, None
    print(f"OBSERVED restoring into a *different* machine raised={raised} state={state}")
    drift_detected = raised == "SnapshotDriftError"

    # Future version rejected.
    forged = dict(snapshot, version=99, unknown_future_field={"x": 1})
    try:
        r2 = Interpreter.from_snapshot(json.dumps(forged), create_machine(CFG_V1))
        await r2.start()
        await r2.stop()
        print("OBSERVED a snapshot claiming version=99 restores without error")
        future_rejected = False
    except SnapshotVersionError as exc:
        print(f"OBSERVED version=99 snapshot rejected: {type(exc).__name__}")
        future_rejected = True
    except Exception as exc:  # noqa: BLE001
        print(f"OBSERVED version=99 snapshot rejected with unexpected type: {type(exc).__name__}")
        future_rejected = False

    # verify_machine_hash=False opt-out allows drifted restore.
    try:
        r3 = Interpreter.from_snapshot(
            json.dumps(snapshot), create_machine(CFG_OTHER), verify_machine_hash=False
        )
        await r3.start()
        await r3.stop()
        opt_out_works = True
        print("OBSERVED verify_machine_hash=False allows drifted restore")
    except Exception as exc:  # noqa: BLE001
        opt_out_works = False
        print(f"OBSERVED verify_machine_hash=False unexpectedly raised: {type(exc).__name__}")

    # Legacy unversioned (0.7.x, nine-key) payload still restores.
    legacy = {k: v for k, v in snapshot.items() if k in EXPECTED_META or k not in EXPECTED_META}
    legacy = dict(snapshot)
    for k in EXPECTED_META:
        legacy.pop(k, None)
    try:
        r4 = Interpreter.from_snapshot(json.dumps(legacy), create_machine(CFG_V1))
        await r4.start()
        legacy_state = sorted(r4.current_state_ids)
        await r4.stop()
        legacy_ok = legacy_state == ["o.a"]
        print(f"OBSERVED legacy unversioned payload restores: state={legacy_state}")
    except Exception as exc:  # noqa: BLE001
        legacy_ok = False
        print(f"OBSERVED legacy unversioned payload raised unexpectedly: {type(exc).__name__}")

    # Guard-added drift (LC-23 concrete case) also detected via machine_hash.
    guard_drift_raised = None
    try:
        rd = Interpreter.from_snapshot(json.dumps(snapshot), create_machine(CFG_DRIFT, logic=DRIFT_LOGIC))
        await rd.start()
        await rd.stop()
    except Exception as exc:  # noqa: BLE001
        guard_drift_raised = type(exc).__name__
    print(f"OBSERVED guard-added drift (same state ids) raised={guard_drift_raised}")
    guard_drift_detected = guard_drift_raised == "SnapshotDriftError"

    print("EXPECTED get_persisted_snapshot() writes version/machine_id/machine_hash/taken_at; "
          "from_snapshot() raises SnapshotDriftError on structural drift by default, "
          "SnapshotVersionError on a future version, allows opt-out via verify_machine_hash=False, "
          "and still restores legacy unversioned (0.7.x) payloads.")

    ok = (
        all_meta_present
        and drift_detected
        and future_rejected
        and opt_out_works
        and legacy_ok
        and guard_drift_detected
    )
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
