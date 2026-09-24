"""LC-19 verification on xstate-statemachine main @ 5327ba6 (pre-0.8.1).

CHANGELOG [Added] (#44): "has_dormant_invocations on both engines. After
a static from_snapshot() the machine reports status == 'running' ... while
every invoke in the configuration is parked. status is therefore not a
liveness signal after a restore; this boolean (and pending_invocations())
is."

This is an OPT-IN fix for restart_services; has_dormant_invocations /
pending_invocations() are unconditional, always-available inspection APIs.
Per the task's "need": verify has_dormant_invocations on BOTH engines is
True after a static from_snapshot() with parked invokes, False after
restart_services=True, and False when there are no pending invocations at
all -- consistent with pending_invocations().
"""

from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

calls = {"place": 0, "entry": 0}


async def place(interp, ctx, evt):  # noqa: ANN001
    calls["place"] += 1
    await asyncio.sleep(5)
    return {"ok": True}


def place_sync(interp, ctx, evt):  # noqa: ANN001
    calls["place"] += 1
    return {"ok": True}


def on_entry(interp, ctx, evt, action):  # noqa: ANN001
    calls["entry"] += 1


CFG = {
    "id": "o",
    "initial": "submitting",
    "states": {
        "submitting": {
            "entry": ["on_entry"],
            "invoke": {"id": "place", "src": "place", "onDone": "submitted"},
        },
        "submitted": {},
    },
}

# A machine with NO invokes at all, for the "no pending invocations" case.
CFG_NO_INVOKE = {
    "id": "plain",
    "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


async def check_async() -> bool:
    ok = True
    logic = MachineLogic(actions={"on_entry": on_entry}, services={"place": place})

    interp = await Interpreter(create_machine(CFG, logic=logic)).start()
    await asyncio.sleep(0.1)
    snapshot = interp.get_snapshot()
    await interp.stop()

    # --- default from_snapshot: dormant invoke present -> True
    calls["place"] = calls["entry"] = 0
    restored_default = Interpreter.from_snapshot(snapshot, create_machine(CFG, logic=logic))
    dormant_before_start = restored_default.has_dormant_invocations
    await restored_default.start()
    await asyncio.sleep(0.3)
    dormant_after_start = restored_default.has_dormant_invocations
    pending_after_start = restored_default.pending_invocations()
    print(
        f"OBSERVED [async] default from_snapshot: has_dormant_invocations "
        f"before_start={dormant_before_start} after_start={dormant_after_start} "
        f"pending_invocations={pending_after_start} place_calls={calls['place']}"
    )
    print("EXPECTED [async] True/True, consistent with a non-empty pending_invocations()")
    if not (dormant_before_start and dormant_after_start and len(pending_after_start) == 1):
        ok = False
    await restored_default.stop()

    # --- restart_services=True: dormant invoke re-invoked -> False
    calls["place"] = calls["entry"] = 0
    restored = Interpreter.from_snapshot(
        snapshot, create_machine(CFG, logic=logic), restart_services=True
    )
    await restored.start()
    await asyncio.sleep(0.3)
    dormant_after_restart = restored.has_dormant_invocations
    pending_after_restart = restored.pending_invocations()
    print(
        f"OBSERVED [async] restart_services=True: has_dormant_invocations="
        f"{dormant_after_restart} pending_invocations={pending_after_restart} "
        f"place_calls={calls['place']}"
    )
    print("EXPECTED [async] False, consistent with empty pending_invocations(), place re-invoked")
    if dormant_after_restart or pending_after_restart or calls["place"] < 1:
        ok = False
    await restored.stop()

    # --- no pending invocations at all (plain machine) -> False
    plain = await Interpreter(create_machine(CFG_NO_INVOKE)).start()
    dormant_plain = plain.has_dormant_invocations
    print(f"OBSERVED [async] plain machine (no invokes): has_dormant_invocations={dormant_plain}")
    print("EXPECTED [async] False")
    if dormant_plain:
        ok = False
    await plain.stop()

    return ok


def check_sync() -> bool:
    """The sync engine's `invoke` runs inline on `start()`, so to build a
    snapshot shaped like "parked mid-invoke" we start a base interpreter
    (its sync `place_sync` completes immediately, landing in `submitted`),
    take its persisted snapshot, then hand-craft the state back to
    `submitting` -- exactly as `test_restart_services_behaves_identically_
    on_both_engines` does in tests/test_restore_services.py.
    """
    import json

    ok = True
    logic = MachineLogic(actions={"on_entry": on_entry}, services={"place": place_sync})

    base = SyncInterpreter(create_machine(CFG, logic=logic)).start()
    snap = base.get_persisted_snapshot()
    snap["state_ids"] = ["o.submitting"]
    snap["configuration"] = ["o", "o.submitting"]
    snap["value"] = "submitting"
    base.stop()
    snapshot = json.dumps(snap)

    # --- default from_snapshot: dormant invoke present -> True
    calls["place"] = calls["entry"] = 0
    restored_default = SyncInterpreter.from_snapshot(
        snapshot, create_machine(CFG, logic=logic)
    )
    dormant_before_start = restored_default.has_dormant_invocations
    restored_default.start()
    dormant_after_start = restored_default.has_dormant_invocations
    pending_after_start = restored_default.pending_invocations()
    print(
        f"OBSERVED [sync] default from_snapshot: has_dormant_invocations "
        f"before_start={dormant_before_start} after_start={dormant_after_start} "
        f"pending_invocations={pending_after_start} place_calls={calls['place']}"
    )
    print("EXPECTED [sync] True/True, consistent with a non-empty pending_invocations()")
    if not (dormant_before_start and dormant_after_start and len(pending_after_start) == 1):
        ok = False
    restored_default.stop()

    # --- restart_services=True: dormant invoke re-invoked -> False
    calls["place"] = calls["entry"] = 0
    restored = SyncInterpreter.from_snapshot(
        snapshot, create_machine(CFG, logic=logic), restart_services=True
    )
    restored.start()
    dormant_after_restart = restored.has_dormant_invocations
    pending_after_restart = restored.pending_invocations()
    print(
        f"OBSERVED [sync] restart_services=True: has_dormant_invocations="
        f"{dormant_after_restart} pending_invocations={pending_after_restart} "
        f"place_calls={calls['place']}"
    )
    print("EXPECTED [sync] False, consistent with empty pending_invocations(), place re-invoked")
    if dormant_after_restart or pending_after_restart or calls["place"] < 1:
        ok = False
    restored.stop()

    # --- no pending invocations at all (plain machine) -> False
    plain = SyncInterpreter(create_machine(CFG_NO_INVOKE)).start()
    dormant_plain = plain.has_dormant_invocations
    print(f"OBSERVED [sync] plain machine (no invokes): has_dormant_invocations={dormant_plain}")
    print("EXPECTED [sync] False")
    if dormant_plain:
        ok = False
    plain.stop()

    return ok


async def main() -> int:
    ok_async = await check_async()
    ok_sync = check_sync()
    ok = ok_async and ok_sync
    print("RESULT:", "FIXED" if ok else "NOT FIXED (see failing checks above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
