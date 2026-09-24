"""R4 - snapshot READ-SIDE guards: configuration/state_ids disagreement
fuzz + null/absent `machine_hash` on v0 / v1 / v2 blobs.

#185: the v0 bypass must be keyed on the DECLARED version, so a
`version: 2` blob that lost its hash in transit is drift, not a free pass.
#186: `configuration` and `state_ids` must AGREE or the blob is corrupt --
`configuration or state_ids` let an emptied configuration silently win.

Both engines. Machines carry a real invoked service in both spellings so
the `actors` section of the blob is populated.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random

from common2 import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
    emit,
    make_service,
)

CFG = {
    "id": "r4",
    "initial": "top",
    "context": {"n": 0},
    "states": {
        "top": {
            "type": "parallel",
            "states": {
                "A": {
                    "initial": "a1",
                    "states": {"a1": {"on": {"S": {"target": "a2"}}}, "a2": {}},
                },
                "B": {
                    "initial": "b1",
                    "states": {"b1": {"on": {"S": {"target": "b2"}}}, "b2": {}},
                },
            },
        }
    },
}


def mk(kind: str):
    return create_machine(
        CFG, logic=MachineLogic(services={"s": make_service(kind)})
    )


async def good_blob(kind: str) -> dict:
    i = Interpreter(mk(kind))
    await asyncio.wait_for(i.start(), 10)
    await asyncio.wait_for(i.send("S"), 5)
    b = i.get_persisted_snapshot()
    await i.stop()
    return b if isinstance(b, dict) else json.loads(b)


def restore(engine: str, kind: str, blob: dict, **kw):
    cls = Interpreter if engine == "async" else SyncInterpreter
    try:
        r = cls.from_snapshot(json.dumps(blob), mk(kind), **kw)
        return {
            "disposition": "ACCEPTED",
            "status": r.status,
            "state_ids": sorted(getattr(r, "current_state_ids", [])),
        }
    except Exception as exc:  # noqa: BLE001
        return {"disposition": f"refused:{type(exc).__name__}", "msg": str(exc)[:90]}


MUTATORS = {
    # --- #186: configuration vs state_ids ---
    "config_emptied": lambda b: b.update({"configuration": []}),
    "config_dropped": lambda b: b.pop("configuration", None),
    "config_rewritten_other_leaf": lambda b: b.update(
        {"configuration": ["r4.top.A.a2", "r4.top.B.b1"]}
    ),
    "config_superset": lambda b: b.update(
        {"configuration": sorted(set(b["configuration"]) | {"r4.top"})}
    ),
    "config_subset_one_region": lambda b: b.update(
        {"configuration": b["configuration"][:1]}
    ),
    "state_ids_emptied": lambda b: b.update({"state_ids": []}),
    "state_ids_rewritten": lambda b: b.update({"state_ids": ["r4.top.A.a1"]}),
    "both_emptied": lambda b: b.update({"configuration": [], "state_ids": []}),
    "config_bogus_id": lambda b: b.update({"configuration": ["r4.nope"]}),
    # --- #185: machine_hash on a versioned payload ---
    "v2_hash_null": lambda b: b.update({"version": 2, "machine_hash": None}),
    "v2_hash_absent": lambda b: (b.update({"version": 2}), b.pop("machine_hash", None)),
    "v2_hash_empty_str": lambda b: b.update({"version": 2, "machine_hash": ""}),
    "v2_hash_wrong": lambda b: b.update({"version": 2, "machine_hash": "dead" * 4}),
    "v1_hash_null": lambda b: b.update({"version": 1, "machine_hash": None}),
    "v1_hash_absent": lambda b: (b.update({"version": 1}), b.pop("machine_hash", None)),
    "v0_no_version_no_hash": lambda b: (
        b.pop("version", None),
        b.pop("machine_hash", None),
    ),
    "version_null_hash_null": lambda b: b.update(
        {"version": None, "machine_hash": None}
    ),
}

#: A mutation that MUST be refused (drift or corruption). The three
#: unversioned/compatible cases are the documented bypass.
MUST_REFUSE = set(MUTATORS) - {"v0_no_version_no_hash", "config_superset"}


async def main() -> int:
    rows = []
    bad = []
    for kind in ("def", "async def"):
        base = await good_blob(kind)
        for name, fn in MUTATORS.items():
            for engine in ("async", "sync"):
                b = copy.deepcopy(base)
                fn(b)
                r = restore(engine, kind, b)
                row = {"mutation": name, "engine": engine, "kind": kind, **r}
                rows.append(row)
                if name in MUST_REFUSE and r["disposition"] == "ACCEPTED":
                    bad.append(row)
    # --- structured fuzz: random disagreements between the two fields ---
    rng = random.Random(4242)
    leaves = ["r4.top.A.a1", "r4.top.A.a2", "r4.top.B.b1", "r4.top.B.b2", "r4.top"]
    fuzz_accepted_disagreements = []
    base = await good_blob("def")
    for _ in range(400):
        b = copy.deepcopy(base)
        b["configuration"] = rng.sample(leaves, rng.randint(0, len(leaves)))
        b["state_ids"] = rng.sample(leaves, rng.randint(0, len(leaves)))
        agree = sorted(b["configuration"]) == sorted(b["state_ids"])
        r = restore("async", "def", b)
        if not agree and r["disposition"] == "ACCEPTED":
            fuzz_accepted_disagreements.append(
                {"configuration": b["configuration"], "state_ids": b["state_ids"], **r}
            )
    emit(
        "r4_snapshot_readside_guards",
        {
            "rows": rows,
            "accepted_but_should_refuse": bad,
            "fuzz_trials": 400,
            "fuzz_accepted_disagreements": fuzz_accepted_disagreements[:10],
            "fuzz_accepted_count": len(fuzz_accepted_disagreements),
            "result": "FAIL"
            if bad or fuzz_accepted_disagreements
            else "PASS",
        },
    )
    return 1 if bad or fuzz_accepted_disagreements else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
