"""Recursive nested unknown-key fuzz (#220) vs strict_config, both a
typo-catch pass and a valid-grammar false-positive pass.
STANDALONE: stdlib + xstate_statemachine only.
"""
import sys, itertools
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic
from xstate_statemachine.exceptions import InvalidConfigError

TYPOS = {
    "root": ["contxt", "verion", "onUnhandld"],
    "state": ["entyr", "onn", "afterr", "invok"],
    "transition": ["taget", "gaurd", "actoins"],
    "invoke": ["srcc", "onDonee", "systemid"],
}

results = []
for level, keys in TYPOS.items():
    for bad in keys:
        if level == "root":
            cfg = {"id": "m", "initial": "a", "states": {"a": {}}, bad: 1}
        elif level == "state":
            cfg = {"id": "m", "initial": "a", "states": {"a": {bad: 1}}}
        elif level == "transition":
            cfg = {"id": "m", "initial": "a",
                   "states": {"a": {"on": {"GO": {bad: "a"}}}}}
        else:  # invoke
            cfg = {"id": "m", "initial": "a",
                   "states": {"a": {"invoke": {"id": "x", "src": "s", bad: 1}}}}
        try:
            create_machine(cfg, logic=MachineLogic(services={"s": lambda i, c, e, a: None}), strict_config=True)
            caught = False
        except InvalidConfigError:
            caught = True
        results.append((level, bad, caught))

bad_misses = [r for r in results if not r[2]]
print("typo cells:", len(results), "misses:", len(bad_misses))
for r in bad_misses:
    print("  MISS:", r)

# valid-grammar generation: exercise every documented key at every level,
# assert ZERO false positives under strict_config.
valid_cfg = {
    "id": "m", "initial": "a", "context": {}, "version": 1,
    "actionErrorPolicy": "fail", "guardErrorPolicy": "raise",
    "onUnhandled": "ignore", "maxIterations": 100, "spawnBlockingTimeout": 1,
    "strict": False, "strictTargets": False, "strictConfig": True,
    "x-custom": 1, "meta": {"k": 1}, "description": "d", "tags": ["t"],
    "states": {
        "a": {
            "id": "a", "type": "atomic", "output": {}, "entry": [], "exit": [],
            "on": {"GO": {"target": "b", "actions": [], "guard": "g",
                          "internal": False, "reenter": True, "x-y": 1,
                          "meta": {}, "description": "d", "tags": []}},
            "always": [{"target": "b"}],
            "after": {100: {"target": "b"}},
            "invoke": {"id": "x", "src": "s", "input": {}, "systemId": "sid",
                       "onDone": {"target": "b"}, "onError": {"target": "b"},
                       "x-z": 1, "meta": {}, "description": "d", "tags": []},
            "onDone": {"target": "b"},
            "history": "shallow",
        },
        "b": {"type": "final"},
    },
}


def guard_g(i, c, e):
    return True


try:
    create_machine(valid_cfg, logic=MachineLogic(
        services={"s": lambda i, c, e, a: None},
        guards={"g": guard_g},
    ), strict_config=True)
    fp = False
except InvalidConfigError as exc:
    fp = True
    print("FALSE POSITIVE on valid grammar:", exc)

print("false_positive_on_valid_grammar:", fp)
print("D12-security verdict: typo misses=%d fp=%s" % (len(bad_misses), fp))
