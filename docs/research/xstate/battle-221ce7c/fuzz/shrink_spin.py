"""Delta-debugging shrinker for the `start()` non-termination defect (D-fuzz-1).

Uses `spin_oracle.spins` -- a select-transition budget rather than a wall
clock -- so each oracle call is milliseconds and a full minimisation runs in
seconds. Reductions attempted, in order of aggressiveness:

  1. delete a non-structural key (entry/exit/on/always/after/invoke/...)
  2. delete a whole child state (repairing `initial` if needed)
  3. collapse a parallel state to a compound one
  4. shorten an `always` guard to no guard

A reduction is kept only if the reduced config STILL spins.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys

sys.path.insert(0, ".")

from gen_config import make_logic  # noqa: E402
from spin_oracle import spins  # noqa: E402

LOGIC = make_logic(sync=True)
LIMIT = 3000


def hangs(cfg) -> bool:
    return spins(cfg, LOGIC, limit=LIMIT)


STRUCTURAL = {"id", "initial", "states", "type"}


def candidates(cfg):
    def walk(node, path):
        if not isinstance(node, dict):
            return
        for k in list(node):
            if k in STRUCTURAL:
                continue
            c = copy.deepcopy(cfg)
            t = c
            for p in path:
                t = t[p]
            del t[k]
            yield (f"drop {'/'.join(map(str, path + [k]))}", c)
        # collapse parallel -> compound
        if node.get("type") == "parallel" and node.get("states"):
            c = copy.deepcopy(cfg)
            t = c
            for p in path:
                t = t[p]
            t.pop("type", None)
            t["initial"] = list(t["states"])[0]
            yield (f"unparallel {'/'.join(map(str, path)) or 'ROOT'}", c)
        states = node.get("states")
        if isinstance(states, dict):
            for sk in list(states):
                c = copy.deepcopy(cfg)
                t = c
                for p in path:
                    t = t[p]
                del t["states"][sk]
                if not t["states"]:
                    continue
                if t.get("initial") == sk:
                    t["initial"] = list(t["states"])[0]
                yield (
                    f"drop state {'/'.join(map(str, path + ['states', sk]))}",
                    c,
                )
            for sk, sv in states.items():
                yield from walk(sv, path + ["states", sk])

    yield from walk(cfg, [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default="min_spin.json")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    if not hangs(cfg):
        print("seed does NOT spin; nothing to do")
        return 1
    print(f"seed spins (size={len(json.dumps(cfg))}); minimising...")

    changed = True
    while changed:
        changed = False
        for desc, cand in candidates(cfg):
            if hangs(cand):
                cfg = cand
                changed = True
                print(f"  kept: {desc}  size={len(json.dumps(cfg))}", flush=True)
                break

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)
    print("\nMINIMAL (" + str(len(json.dumps(cfg))) + " bytes):")
    print(json.dumps(cfg, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
