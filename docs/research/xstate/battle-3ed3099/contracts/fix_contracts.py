# -*- coding: utf-8 -*-
"""Produce <B>.machine.json: our catalogue JSON with the retired A3 scaffolding
stripped (E50-T09), and log the diff.

Removes, per catalogue sec 1.3b: every `"*": {"actions": ["defer"]}` handler, every
`drain_deferred` entry action and the `_deferred` context key. Nothing else is
touched.
"""
from __future__ import annotations
import json, copy, pathlib

DIFF = []

# Actions whose name is stolen by the engine's `spawn_` / `spawn_blocking_`
# built-in action prefix (see repro/r2_spawn_prefix_steals_action_name.py).
# These are ordinary application actions in our catalogue (B2 INV-B2-e says
# legs are addressed through the app-owned registry, never a library actor),
# so the name must not start with `spawn_`.
RENAME = {"spawn_all_legs": "launch_all_legs",
          "spawn_entry_order": "submit_entry_order"}

# B2's `raise_evaluate` is written as a plain named action, but its whole job is
# to emit the internal EVALUATE event. A named action cannot do that: CV-C16
# forbids `send()` from an action, and the only bounded self-emission shape is
# the `raise` built-in. Replaced with the built-in.
REPLACE = {"raise_evaluate": {"type": "raise",
                              "params": {"event": {"type": "EVALUATE"}}}}


def builtins_(node, path):
    def fix(lst, where):
        for n, a in enumerate(lst):
            if a in REPLACE:
                DIFF.append("%s: %s action %r -> built-in %s (a named action "
                            "cannot emit an event)"
                            % (path, where, a, json.dumps(REPLACE[a])))
                lst[n] = copy.deepcopy(REPLACE[a])
    for key in ("entry", "exit"):
        if isinstance(node.get(key), list):
            fix(node[key], key)
    for ev, tr in (node.get("on") or {}).items():
        for t in (tr if isinstance(tr, list) else [tr]):
            if isinstance(t, dict) and isinstance(t.get("actions"), list):
                fix(t["actions"], "on[%s]" % ev)
    for n, s in (node.get("states") or {}).items():
        builtins_(s, path + "." + n)


def rename(node, path):
    for key in ("entry", "exit"):
        v = node.get(key)
        if isinstance(v, list):
            for n, a in enumerate(v):
                if a in RENAME:
                    DIFF.append("%s: rename %s action %s -> %s (engine `spawn_` "
                                "prefix claims the name)" % (path, key, a, RENAME[a]))
                    v[n] = RENAME[a]
    on = node.get("on") or {}
    for ev, tr in on.items():
        for t in (tr if isinstance(tr, list) else [tr]):
            if not isinstance(t, dict):
                continue
            acts = t.get("actions")
            if isinstance(acts, list):
                for n, a in enumerate(acts):
                    if a in RENAME:
                        DIFF.append("%s on[%s]: rename action %s -> %s (engine "
                                    "`spawn_` prefix claims the name)"
                                    % (path, ev, a, RENAME[a]))
                        acts[n] = RENAME[a]
    for n, s in (node.get("states") or {}).items():
        rename(s, path + "." + n)


def strip(node, path):
    on = node.get("on")
    if isinstance(on, dict) and "*" in on:
        DIFF.append("%s: remove on['*'] = %s" % (path, json.dumps(on["*"])))
        del on["*"]
        if not on:
            node.pop("on")
    for key in ("entry", "exit"):
        v = node.get(key)
        if isinstance(v, list) and "drain_deferred" in v:
            DIFF.append("%s: remove '%s' action drain_deferred" % (path, key))
            node[key] = [a for a in v if a != "drain_deferred"]
            if not node[key]:
                node.pop(key)
        elif v == "drain_deferred":
            DIFF.append("%s: remove '%s' action drain_deferred" % (path, key))
            node.pop(key)
    for n, s in (node.get("states") or {}).items():
        strip(s, path + "." + n)


def main():
    here = pathlib.Path(__file__).parent
    log = {}
    for b in ("B1", "B2", "B3", "B4", "B5"):
        DIFF.clear()
        cfg = json.loads((here / (b + ".orig.json")).read_text(encoding="utf-8"))
        out = copy.deepcopy(cfg)
        if "_deferred" in (out.get("context") or {}):
            DIFF.append("context: remove reserved key '_deferred'")
            out["context"].pop("_deferred")
        strip(out, out["id"])
        rename(out, out["id"])
        builtins_(out, out["id"])
        (here / (b + ".machine.json")).write_text(
            json.dumps(out, indent=2) + "\n", encoding="utf-8")
        log[b] = list(DIFF)
        print(b, len(DIFF), "edits")
        for d in DIFF:
            print("   ", d)
    (here / "catalogue-diff.json").write_text(json.dumps(log, indent=1), encoding="utf-8")


main()
