"""Attack S: v2-upcast minting vector — THE round-10 security question.

Can an attacker who can write a snapshot blob (but not sign it) forge a
v2-shaped record (kind="after"/"done"/"error", no "engine" flag, version=2)
and have `upcast()` mint it as an engine-provenance event on restore,
thereby firing an `after`/`onDone`/`onError` transition that a v3-aware
`restore_event` would otherwise have refused as hand-written user traffic?

Standalone: stdlib + xstate_statemachine only.
"""
import asyncio
import json

from xstate_statemachine import create_machine, Interpreter, MachineLogic

CFG = {
    "id": "guard",
    "initial": "waiting",
    "context": {},
    "states": {
        "waiting": {
            "after": {"60000": "late_fired"},
            "on": {"DONE": "manual_done"},
        },
        "late_fired": {"type": "final"},
        "manual_done": {"type": "final"},
    },
}


async def attack_s():
    m = create_machine(CFG)
    interp = Interpreter(m)
    await interp.start()
    snap = json.loads(interp.get_snapshot())
    await interp.stop()

    # Forge a v2-shaped snapshot: version=2, no scheduled_sends field,
    # a pending_events entry that looks like a fired `after` completion,
    # WITHOUT the v3 "engine" flag (attacker doesn't know about it, or
    # deliberately omits it hoping upcast still mints it).
    forged = dict(snap)
    forged["version"] = 2
    forged.pop("scheduled_sends", None)
    forged["pending_events"] = [
        {
            "kind": "after",
            "type": "after.60000.guard.waiting",
            "scheduled_for": 0.0,
            "fired_at": 0.0,
            # deliberately NOT setting "engine": True -- attacker-forged
        }
    ]
    forged_str = json.dumps(forged)

    m2 = create_machine(CFG)
    restored = Interpreter.from_snapshot(forged_str, m2, verify_machine_hash=False)
    await restored.start()
    await asyncio.sleep(0.05)
    config = list(restored.current_state_ids) if hasattr(restored, "current_state_ids") else None
    fired = "guard.late_fired" in (config or [])
    await restored.stop()
    print(f"attack_s v2_forged_after_record_fires_early: {fired}")
    print(f"attack_s config_after_restore: {config}")
    print(f"attack_s VULNERABLE_IF_TRUE: {fired}")


if __name__ == "__main__":
    asyncio.run(attack_s())
