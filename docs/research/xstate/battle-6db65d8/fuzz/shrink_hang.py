"""Minimiser for the F1 start() hang: delta-debug the JSON config by
repeatedly deleting keys / states and keeping any config that still hangs.

"Hangs" is operationalised as: `SyncInterpreter(m).start()` does not return
within `--budget` seconds in a child process. Run under a child process so a
genuinely non-terminating case cannot wedge the minimiser.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

CHILD = r"""
import sys, json, logging, warnings, time
sys.path.insert(0, %r)
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from gen_config import make_logic
from xstate_statemachine import create_machine, SyncInterpreter
cfg = json.load(open(sys.argv[1]))
m = create_machine(cfg, logic=make_logic(sync=True))
i = SyncInterpreter(m)
i.start()
print("RETURNED", sorted(i.current_state_ids))
"""


def hangs(cfg: dict, budget: float) -> bool:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(cfg, fh)
        path = fh.name
    try:
        p = subprocess.run(
            [PY, "-c", CHILD % HERE, path],
            capture_output=True,
            timeout=budget,
            text=True,
        )
        return False  # returned (or raised) => not a hang
    except subprocess.TimeoutExpired:
        return True
    finally:
        os.unlink(path)


def candidates(cfg: dict):
    """Yield (description, reduced_cfg) simplification steps."""

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for k in list(node):
            if k in ("id", "initial", "states", "type"):
                continue
            c = copy.deepcopy(cfg)
            t = c
            for p in path:
                t = t[p]
            del t[k]
            yield (f"drop {'/'.join(map(str, path + [k]))}", c)
        states = node.get("states")
        if isinstance(states, dict):
            for sk in list(states):
                c = copy.deepcopy(cfg)
                t = c
                for p in path:
                    t = t[p]
                del t["states"][sk]
                if t.get("initial") == sk:
                    remaining = list(t["states"])
                    if not remaining:
                        continue
                    t["initial"] = remaining[0]
                yield (f"drop state {'/'.join(map(str, path + ['states', sk]))}", c)
            for sk, sv in states.items():
                yield from walk(sv, path + ["states", sk])

    yield from walk(cfg, [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--budget", type=float, default=8.0)
    ap.add_argument("--out", default="min_hang.json")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    assert hangs(cfg, args.budget), "seed config does not hang"
    print("seed hangs; minimising...")

    changed = True
    while changed:
        changed = False
        for desc, cand in candidates(cfg):
            if hangs(cand, args.budget):
                cfg = cand
                changed = True
                print(
                    f"  kept: {desc}  (size={len(json.dumps(cfg))})", flush=True
                )
                break

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)
    print("\nMINIMAL:\n" + json.dumps(cfg, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
