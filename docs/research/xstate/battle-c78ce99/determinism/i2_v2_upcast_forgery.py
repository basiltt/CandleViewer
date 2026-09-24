"""i2: v2-upcast minting security probe (#214).

The claim to verify: a v2-shaped (version==2, no `engine` flag) `after`/
`done`/`error` record is upcast as engine-minted and fires; a CURRENT
version (v3) record of the same shape, without the engine flag, is NOT
upcast and stays untrusted user traffic (pinned by the library's own
test_v3_record_without_engine_flag_is_user_traffic). This probe attacks
the boundary directly: what happens with version==2 exactly at the fired
deadline is engine-standing, but can an attacker who controls the pending
snapshot forge an `onDone`/`error.platform` completion this way too (not
just `after`), and does downgrading version alone (without any invoke ever
having existed) let a forged `done.invoke.*` drive an onDone transition
that was never armed?
"""
"""i2: v2-upcast minting security probe (#214).

The claim to verify: a v2-shaped (version==2, no `engine` flag) `after`/
`done`/`error` record is upcast as engine-minted and fires; a CURRENT
version (v3) record of the same shape, without the engine flag, is NOT
upcast and stays untrusted user traffic (pinned by the library's own
test_v3_record_without_engine_flag_is_user_traffic). This probe attacks
the boundary directly with a service that genuinely never resolves within
the probe window (so any onDone firing is necessarily the forged record,
not a real completion racing the snapshot), using the ASYNC engine so the
invoke is truly still pending when the snapshot is taken.
"""
import asyncio
import json

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

CFG = {
    "id": "inv",
    "initial": "wait",
    "context": {"onDoneFired": 0, "onErrFired": 0},
    "states": {
        "wait": {
            "invoke": {
                "src": "svc",
                "onDone": {"target": "done", "actions": ["markDone"]},
                "onError": {"target": "failed", "actions": ["markErr"]},
            },
        },
        "done": {},
        "failed": {},
    },
}


async def svc(i, c, e):
    # never resolves in the probe window (only cancelled by stop())
    await asyncio.sleep(60)
    return "real"


def mark_done(i, c, *_):
    c["onDoneFired"] += 1


def mark_err(i, c, *_):
    c["onErrFired"] += 1


async def blob_of():
    logic = MachineLogic(
        services={"svc": svc},
        actions={"markDone": mark_done, "markErr": mark_err},
    )
    m = create_machine(CFG, logic=logic)
    s = Interpreter(m)
    await s.start()
    await asyncio.sleep(0.05)
    assert s.value == "wait", f"invoke resolved for real before snapshot: {s.value}"
    b = s.get_persisted_snapshot()
    await s.stop()
    return b, logic


async def attack_forged_done(version):
    """Forge a done.invoke record with no real invoke behind it and see
    if the engine treats it as engine-minted and drives onDone, at the
    given snapshot `version`."""
    blob, logic = await blob_of()
    blob["version"] = version
    blob["pending_events"] = [
        {
            "kind": "done",
            "type": "done.invoke.inv.wait",
            "data": {"forged": True},
            "src": "inv.wait",
        }
    ]
    m = create_machine(CFG, logic=logic)
    r = Interpreter.from_snapshot(json.dumps(blob), m)
    await r.start()
    await asyncio.sleep(0.05)
    result = {
        "value": r.value,
        "onDoneFired": r.context["onDoneFired"],
        "last_error": str(r.last_error) if r.last_error else None,
    }
    await r.stop()
    return result


async def attack_forged_error(version):
    blob, logic = await blob_of()
    blob["version"] = version
    blob["pending_events"] = [
        {
            "kind": "error",
            "type": "error.platform.inv.wait",
            "data": {"forged": True},
            "src": "inv.wait",
        }
    ]
    m = create_machine(CFG, logic=logic)
    r = Interpreter.from_snapshot(json.dumps(blob), m)
    await r.start()
    await asyncio.sleep(0.05)
    result = {
        "value": r.value,
        "onErrFired": r.context["onErrFired"],
        "last_error": str(r.last_error) if r.last_error else None,
    }
    await r.stop()
    return result


async def main():
    out = {
        "v2_forged_done_invoke": await attack_forged_done(2),
        "v3_forged_done_invoke": await attack_forged_done(3),
        "v2_forged_error_platform": await attack_forged_error(2),
        "v3_forged_error_platform": await attack_forged_error(3),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

