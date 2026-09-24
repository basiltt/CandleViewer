"""D5 -- dict/set iteration dependence under PYTHONHASHSEED 1..5.

Where the engine iterates a `set` or a dict whose keys are strings, CPython's
per-process string hash randomisation can change the order. This script prints
the observables that could plausibly depend on it:

  * parallel-region ENTRY order (which region's `entry` action runs first);
  * parallel-region EXIT order;
  * guard evaluation order when several transitions are candidates;
  * actor teardown order on `stop()`;
  * the invoke start order across regions;
  * `current_state_ids` / snapshot `configuration` serialisation order.

Driver: `d5_hashseed.py --run` executes one run and prints one JSON line. With
no flag it re-executes itself under PYTHONHASHSEED=1..5 (plus 0 = disabled) and
compares.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CHILD = {
    "id": "kid",
    "initial": "u",
    "states": {"u": {"on": {"F": {"target": "d"}}}, "d": {"type": "final"}},
}

# Six sibling regions with deliberately hash-unfriendly names, each with an
# entry action, an exit action and its own invoked child actor.
REGIONS = ["zulu", "alpha", "mike", "bravo", "yankee", "charlie"]

CFG = {
    "id": "par",
    "type": "parallel",
    "context": {},
    "states": {
        r: {
            "initial": "on",
            "states": {
                "on": {
                    "entry": [f"enter_{r}"],
                    "exit": [f"exit_{r}"],
                    "invoke": {"id": f"a_{r}", "src": "kidm"},
                    "on": {
                        # every region handles LEAVE, so all six exit at once
                        "LEAVE": {"target": "off"},
                        # every region has a GUARDED candidate for PICK
                        "PICK": [
                            {"guard": f"g_{r}", "actions": [f"hit_{r}"]},
                            {"actions": [f"miss_{r}"]},
                        ],
                    },
                },
                "off": {"entry": [f"off_{r}"]},
            },
        }
        for r in REGIONS
    },
}


def one_run():
    ev = {
        "entry": [],
        "exit": [],
        "guards": [],
        "svc_start": [],
        "off": [],
    }

    class P(PluginBase):
        def on_guard_evaluated(self, i, name, event, result):
            ev["guards"].append((name, bool(result)))

        def on_service_start(self, i, inv):
            ev["svc_start"].append(inv.id)

    acts = {}
    for r in REGIONS:
        acts[f"enter_{r}"] = (
            lambda i, c, e, a, r=r: ev["entry"].append(r)
        )
        acts[f"exit_{r}"] = lambda i, c, e, a, r=r: ev["exit"].append(r)
        acts[f"off_{r}"] = lambda i, c, e, a, r=r: ev["off"].append(r)
        acts[f"hit_{r}"] = lambda i, c, e, a: None
        acts[f"miss_{r}"] = lambda i, c, e, a: None
    guards = {f"g_{r}": (lambda c, e, r=r: False) for r in REGIONS}

    m = create_machine(
        CFG,
        logic=MachineLogic(
            actions=acts,
            guards=guards,
            services={"kidm": create_machine(CHILD, logic=MachineLogic())},
        ),
    )
    interp = SyncInterpreter(m, clock=SimulatedClock())
    interp.start()
    ids_after_start = sorted(interp.current_state_ids)
    raw_ids = list(interp.current_state_ids)
    actors_before = list(interp._actors.keys())
    interp.send("PICK")
    interp.send("LEAVE")
    snap = interp.get_persisted_snapshot()
    teardown = []
    # observe actor teardown order
    orig = interp._actors

    class Watch(dict):
        pass

    interp.stop()
    return {
        "entry_order": ev["entry"],
        "exit_order": ev["exit"],
        "off_entry_order": ev["off"],
        "guard_order": [g for g, _ in ev["guards"]],
        "svc_start_order": ev["svc_start"],
        "actors_map_order": actors_before,
        "current_state_ids_raw": raw_ids,
        "snapshot_configuration": snap["configuration"],
        "snapshot_actors": list(snap["actors"].keys()),
        "snapshot_value_keys": list(snap["value"].keys())
        if isinstance(snap["value"], dict)
        else snap["value"],
    }


SEEDS = ["0", "1", "2", "3", "4", "5"]

if __name__ == "__main__":
    if "--run" in sys.argv:
        print("@@" + json.dumps(one_run(), default=str))
        sys.exit(0)
    me = os.path.abspath(__file__)
    py = (
        "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
        "xstate-statemachine/.venv-main/Scripts/python"
    )
    results = {}
    for s in SEEDS:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = s
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        p = subprocess.run(
            [py, me, "--run"], env=env, capture_output=True, text=True
        )
        line = [x for x in p.stdout.splitlines() if x.startswith("@@")]
        if not line:
            print(f"seed {s}: FAILED\n{p.stdout}\n{p.stderr[-2000:]}")
            continue
        results[s] = json.loads(line[0][2:])

    keys = list(next(iter(results.values())).keys())
    print(f"PYTHONHASHSEED values tested: {list(results)}")
    print(f"{'observable':28s} {'stable?':10s} distinct")
    unstable = {}
    for k in keys:
        vals = {json.dumps(results[s][k]) for s in results}
        ok = len(vals) == 1
        if not ok:
            unstable[k] = sorted(vals)
        print(f"{k:28s} {'YES' if ok else 'NO ':10s} {len(vals)}")
    for k, v in unstable.items():
        print(f"\n-- {k} --")
        for s in results:
            print(f"   seed {s}: {json.dumps(results[s][k])}")
    out = os.path.join(os.path.dirname(me), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d5_hashseed.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"per_seed": results, "unstable": list(unstable)}, f, indent=2
        )
    print("\nwrote out/d5_hashseed.json")
