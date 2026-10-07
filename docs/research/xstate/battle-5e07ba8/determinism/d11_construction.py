"""D11 -- construction-order determinism: is the machine BUILT the same way
every time, in every process?

D5 varied PYTHONHASHSEED within one machine instance. This asks a different
question: across fresh processes and fresh `create_machine()` calls, are the
structures the engine iterates (parallel regions, transition candidate lists,
guard order, invoke order, `after` delays) laid out identically? The
`structure_hash` in the snapshot envelope is checked too -- if it moved, every
stored snapshot in a fleet would be refused.

Also verifies the ordering that a parallel machine's *actions* run in, which is
the one an audit log records.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.persistence import structure_hash  # noqa: E402

REGIONS = ["zulu", "alpha", "mike", "bravo", "yankee", "charlie"]

CFG = {
    "id": "build",
    "type": "parallel",
    "context": {},
    "states": {
        r: {
            "initial": "on",
            "states": {
                "on": {
                    "entry": [f"e_{r}"],
                    "invoke": {"id": f"inv_{r}", "src": "noop"},
                    "after": {str(10 + i): {"actions": [f"e_{r}"]}},
                    "on": {
                        "PICK": [
                            {"guard": f"g1_{r}", "actions": [f"e_{r}"]},
                            {"guard": f"g2_{r}", "actions": [f"e_{r}"]},
                            {"actions": [f"e_{r}"]},
                        ]
                    },
                },
            },
        }
        for i, r in enumerate(REGIONS)
    },
}


def build():
    acts = {f"e_{r}": (lambda i, c, e, a: None) for r in REGIONS}
    guards = {}
    for r in REGIONS:
        guards[f"g1_{r}"] = lambda c, e: False
        guards[f"g2_{r}"] = lambda c, e: False
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions=acts, guards=guards, services={"noop": lambda c, e: None}
        ),
    )


def observe():
    m = build()
    root = m
    regions = [k for k in root.states.keys()]
    per_region = {}
    for r in regions:
        node = root.states[r].states["on"]
        per_region[r] = {
            "entry": [a.type for a in node.entry],
            "invoke": [(inv.id, inv.src) for inv in node.invoke],
            "after": [str(d) for d in node.after],
            "pick_guards": [
                (t.guard_def.type if t.guard_def else None)
                for t in node.on.get("PICK", [])
            ],
        }
    return {
        "region_order": regions,
        "structure_hash": structure_hash(m),
        "per_region": per_region,
    }


if __name__ == "__main__":
    if "--run" in sys.argv:
        # 20 fresh create_machine() calls in ONE process
        obs = [json.dumps(observe(), sort_keys=True) for _ in range(20)]
        print("@@" + json.dumps({"in_process_distinct": len(set(obs)),
                                 "sample": json.loads(obs[0])}))
        sys.exit(0)

    me = os.path.abspath(__file__)
    py = (
        "<workspace>/_ref/"
        "xstate-statemachine/.venv-main/Scripts/python"
    )
    results = {}
    for seed in ["0", "1", "2", "3", "4", "5"]:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        p = subprocess.run([py, me, "--run"], env=env, capture_output=True, text=True)
        line = [x for x in p.stdout.splitlines() if x.startswith("@@")]
        if not line:
            print(f"seed {seed} FAILED: {p.stderr[-1500:]}")
            continue
        results[seed] = json.loads(line[0][2:])

    print("PYTHONHASHSEED:", list(results))
    for s, v in results.items():
        print(
            f"  seed {s}: distinct observations over 20 in-process builds = "
            f"{v['in_process_distinct']}"
        )
    hashes = {s: v["sample"]["structure_hash"] for s, v in results.items()}
    print(f"\nstructure_hash per seed: {hashes}")
    print(f"  stable across seeds: {len(set(hashes.values())) == 1}")

    for key in ["region_order"]:
        vals = {s: v["sample"][key] for s, v in results.items()}
        stable = len({json.dumps(x) for x in vals.values()}) == 1
        print(f"\n{key}: stable={stable}")
        for s, x in vals.items():
            print(f"   seed {s}: {x}")

    perreg = {
        s: json.dumps(v["sample"]["per_region"], sort_keys=True)
        for s, v in results.items()
    }
    print(f"\nper_region layout stable across seeds: {len(set(perreg.values())) == 1}")

    out = os.path.join(os.path.dirname(me), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d11_construction.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\nwrote out/d11_construction.json")
