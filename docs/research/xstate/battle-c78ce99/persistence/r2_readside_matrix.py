# -*- coding: utf-8 -*-
"""R2 -- read-side matrix on 6db65d8: #185 (machine_hash) x #186 (configuration).

Round 7 claims two read-side holes are closed:

  #185  a null/absent ``machine_hash`` on a *versioned* payload is drift.
  #186  ``configuration`` and ``state_ids`` must agree or the blob is corrupt.

Both claims are version-sensitive (the v0 bypass is deliberate), so this is a
full cross product rather than the two point-probes round 7 used:

    version in {absent, 0, 1, 2} x hash in {honest, wrong, None, removed}
    x target machine in {same, drifted}                      -> 32 cells
    configuration in {intact, empty, missing-key, superset,
                      contradicting, leaf-swapped, ancestor-stripped}
                                                             -> 7 cells

For every cell the *outcome class* is recorded and compared against what the
CHANGELOG entry requires. An ACCEPT is only sound if the restored machine's
leaves equal the leaves the snapshot's ``state_ids`` declared -- the point of
#186 is that no forged key may relocate the machine.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    SnapshotDriftError,
    SnapshotVersionError,
)

A_SPEC = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"on": {"BACK": "a"}},
    },
}
# Structurally different: extra state + different transitions -> different hash.
B_SPEC = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b", "JUMP": "c"}},
        "b": {"on": {"BACK": "a"}},
        "c": {"on": {"BACK": "a"}},
    },
}

RESULTS: list[tuple[str, str, str]] = []


def classify(fn) -> tuple[str, str]:
    try:
        interp = fn()
    except SnapshotDriftError as exc:
        return "DRIFT", str(exc)[:70]
    except SnapshotCorruptError as exc:
        return "CORRUPT", str(exc)[:70]
    except SnapshotVersionError as exc:
        return "VERSION", str(exc)[:70]
    except Exception as exc:  # noqa: BLE001 -- raw leak is itself a finding
        return f"RAW:{type(exc).__name__}", str(exc)[:70]
    leaves = sorted(
        n.id for n in interp._active_state_nodes if not n.states
    )
    return "ACCEPT", repr(leaves)


async def base_blob() -> Dict[str, Any]:
    i = Interpreter(create_machine(A_SPEC), clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.01)
    blob = i.get_persisted_snapshot()
    await i.stop()
    return blob


async def main() -> None:
    blob = await base_blob()
    honest = blob["machine_hash"]
    declared_leaves = sorted(blob["state_ids"])
    print("baseline state_ids   :", declared_leaves)
    print("baseline configuration:", blob["configuration"])
    print("baseline machine_hash :", honest)

    mA, mB = create_machine(A_SPEC), create_machine(B_SPEC)
    print("hash(A)=%s hash(B)=%s" % (mA.structure_hash, mB.structure_hash))

    # ---- part 1: version x hash x target ------------------------------
    print("\n=== 1. version x machine_hash x target machine ===")
    print("%-9s %-9s %-8s %s" % ("version", "hash", "target", "outcome"))
    bad = []
    for ver in ("absent", 0, 1, 2):
        for hk in ("honest", "wrong", "none", "removed"):
            for tgt, mach in (("same", mA), ("drift", mB)):
                b = json.loads(json.dumps(blob))
                if ver == "absent":
                    b.pop("version", None)
                else:
                    b["version"] = ver
                if hk == "wrong":
                    b["machine_hash"] = "deadbeefdeadbeef"
                elif hk == "none":
                    b["machine_hash"] = None
                elif hk == "removed":
                    b.pop("machine_hash", None)
                kind, det = classify(
                    lambda b=b, m=mach: Interpreter.from_snapshot(json.dumps(b), m)
                )
                print("%-9s %-9s %-8s %-8s %s" % (ver, hk, tgt, kind, det))
                # An accept into the DRIFTED machine with a versioned payload
                # whose hash is absent/null is exactly what #185 forbids.
                if tgt == "drift" and kind == "ACCEPT" and ver in (1, 2):
                    bad.append(("#185", ver, hk))
                if kind.startswith("RAW"):
                    bad.append(("RAW", ver, hk, tgt))

    # ---- part 2: configuration vs state_ids ---------------------------
    print("\n=== 2. configuration vs state_ids (#186) ===")
    variants = {
        "intact": lambda b: b,
        "empty": lambda b: b.update(configuration=[]) or b,
        "key removed": lambda b: (b.pop("configuration", None), b)[1],
        "superset(+m.b)": lambda b: b.update(
            configuration=sorted(set(b["configuration"]) | {"m.b"})
        ) or b,
        "contradict(m.b only)": lambda b: b.update(configuration=["m", "m.b"]) or b,
        "leaf stripped": lambda b: b.update(
            configuration=[x for x in b["configuration"] if x != b["state_ids"][0]]
        ) or b,
        "ancestor stripped": lambda b: b.update(
            configuration=list(b["state_ids"])
        ) or b,
        "state_ids emptied": lambda b: b.update(state_ids=[]) or b,
        "state_ids forged m.b": lambda b: b.update(
            state_ids=["m.b"], configuration=["m", "m.b"]
        ) or b,
    }
    for name, mut in variants.items():
        b = mut(json.loads(json.dumps(blob)))
        kind, det = classify(
            lambda b=b: Interpreter.from_snapshot(json.dumps(b), create_machine(A_SPEC))
        )
        note = ""
        if kind == "ACCEPT":
            got = json.loads(det.replace("'", '"'))
            if name not in ("intact", "key removed", "ancestor stripped") and got != declared_leaves:
                note = "  <- RELOCATED, forged key won"
                bad.append(("#186", name, got))
        print("  %-24s %-8s %s%s" % (name, kind, det, note))

    print("\nunsound cells:", bad if bad else "none")
    print("VERDICT:", "FAIL" if bad else "PASS")


asyncio.run(main())
