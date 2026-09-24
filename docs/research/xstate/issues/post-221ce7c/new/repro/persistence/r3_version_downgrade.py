"""R8-06: version-downgrade bypass of the #185 drift check.

Same machine id, DIFFERENT structure (drift). Default verify_machine_hash=True.
Control = intact payload must raise SnapshotDriftError.
Variants = attacker edits of the same JSON object.
"""

import asyncio
import json
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)

from xstate_statemachine import create_machine  # noqa: E402
from xstate_statemachine.exceptions import SnapshotDriftError  # noqa: E402


SNAP_MACHINE = {
    "id": "acct",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {},
    },
}

# Drifted: same id, extra state + a transition the snapshotting machine
# never declared.
DRIFTED_MACHINE = {
    "id": "acct",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b", "JUMP": "c"}},
        "b": {},
        "c": {},
    },
}


def variants(snap: dict):
    yield "control (intact)", dict(snap)

    v = dict(snap)
    v["version"] = 0
    v.pop("machine_hash", None)
    yield "version=0 + hash removed", v

    v = dict(snap)
    v.pop("version", None)
    v.pop("machine_hash", None)
    yield "version key removed + hash removed", v

    v = dict(snap)
    v["version"] = 0
    v["machine_hash"] = None
    yield "version=0 + hash=None", v


async def main(kind: str, interp_cls, machine_cls_kwargs):
    snap_m = create_machine(SNAP_MACHINE, **machine_cls_kwargs)
    drift_m = create_machine(DRIFTED_MACHINE, **machine_cls_kwargs)
    print(f"--- {kind} ---")
    print(f"snap hash={snap_m.structure_hash} drift hash={drift_m.structure_hash}")

    interp = interp_cls(snap_m)
    r = interp.start()
    if asyncio.iscoroutine(r):
        await r
    raw = json.loads(interp.get_snapshot())
    r = interp.stop()
    if asyncio.iscoroutine(r):
        await r

    for name, payload in variants(raw):
        try:
            ri = interp_cls.from_snapshot(json.dumps(payload), drift_m)
            r = ri.start()
            if asyncio.iscoroutine(r):
                await r
            r = ri.send("JUMP")
            if asyncio.iscoroutine(r):
                await r
            if hasattr(ri, "wait_for_stable_state"):
                try:
                    await asyncio.wait_for(ri.wait_for_stable_state(), 2)
                except Exception:
                    pass
            states = sorted(ri.current_state_ids)
            print(f"  {name}: ACCEPTED -> after JUMP: {states}")
            r = ri.stop()
            if asyncio.iscoroutine(r):
                await r
        except SnapshotDriftError as e:
            print(f"  {name}: REFUSED SnapshotDriftError ({str(e)[:70]}...)")
        except Exception as e:
            print(f"  {name}: {type(e).__name__}: {str(e)[:90]}")


if __name__ == "__main__":
    from xstate_statemachine import Interpreter, SyncInterpreter

    asyncio.run(main("async engine", Interpreter, {}))
    asyncio.run(main("sync engine", SyncInterpreter, {}))
