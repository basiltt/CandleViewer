"""J3 -- recursive unknown-key check fuzzer (#220).

(a) Typo fuzzer: inject a single-character typo into a random known key at a
    random nesting level (root / state / transition / invoke) across many
    randomly generated valid machine configs -- the recursive check must
    catch every one under strict_config.
(b) Valid-grammar generator: build machines using ONLY keys from the known
    sets (root/state/transition/invoke keys, x- prefixed, meta/description/
    tags) and assert ZERO rejections under strict_config=True.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xstate_statemachine import create_machine, InvalidConfigError

ROOT_KEYS = [
    "id", "initial", "states", "type", "output", "on", "entry", "exit",
    "after", "always", "invoke", "onDone", "history", "context", "version",
    "actionErrorPolicy", "guardErrorPolicy", "onUnhandled", "maxIterations",
    "spawnBlockingTimeout", "strict", "strictTargets", "strictConfig",
]
STATE_KEYS = [
    "id", "initial", "states", "type", "output", "on", "entry", "exit",
    "after", "always", "invoke", "onDone", "history", "target",
]
TRANSITION_KEYS = ["target", "actions", "guard", "cond", "internal", "reenter"]
INVOKE_KEYS = ["id", "src", "input", "systemId", "onDone", "onError"]
META_KEYS = ["meta", "description", "tags", "version"]


def _typo(word):
    if len(word) < 2:
        return word + "z"
    i = random.randrange(len(word))
    chars = list(word)
    chars[i] = chr(((ord(chars[i]) - ord("a") + 1) % 26) + ord("a")) if chars[i].isalpha() else "9"
    return "".join(chars)


def valid_machine(depth=2):
    def state(d):
        s = {}
        if d > 0 and random.random() < 0.6:
            kids = {f"s{i}": state(d - 1) for i in range(random.randint(1, 2))}
            s["initial"] = next(iter(kids))
            s["states"] = kids
        s["entry"] = []
        s["on"] = {
            "GO": {"target": "#m.done" if random.random() < 0.3 else None, "actions": [], "guard": None}
        }
        s["on"]["GO"] = {k: v for k, v in s["on"]["GO"].items() if v is not None}
        if random.random() < 0.2:
            s["invoke"] = {"id": "svc", "src": "svc", "onDone": {"actions": []}, "onError": {"actions": []}}
        if random.random() < 0.3:
            s["meta"] = {"note": "ok"}
            s["x-custom"] = 1
        return s

    cfg = {
        "id": "m",
        "initial": "s0",
        "states": {"s0": state(depth), "done": {}},
        "context": {},
        "strict": False,
    }
    return cfg


def make_machine(cfg, strict=True):
    return create_machine(cfg, strict_config=strict, logic={"actions": {}, "guards": {}, "services": {}})


def fuzz_typo(n):
    fails = []
    for i in range(n):
        random.seed(i)
        cfg = valid_machine()
        level = random.choice(["root", "state", "transition", "invoke"])
        if level == "root":
            key = random.choice(ROOT_KEYS)
            cfg[_typo(key)] = cfg.pop(key) if key in cfg else "x"
        elif level == "state":
            s0 = cfg["states"]["s0"]
            key = random.choice([k for k in STATE_KEYS if k in s0]) if any(k in s0 for k in STATE_KEYS) else "entry"
            if key in s0:
                s0[_typo(key)] = s0.pop(key)
            else:
                s0[_typo(key)] = []
        elif level == "transition":
            s0 = cfg["states"]["s0"]
            if "on" in s0 and "GO" in s0["on"]:
                t = s0["on"]["GO"]
                key = random.choice([k for k in TRANSITION_KEYS if k in t]) if any(k in t for k in TRANSITION_KEYS) else "actions"
                if key in t:
                    t[_typo(key)] = t.pop(key)
                else:
                    t[_typo(key)] = []
            else:
                continue
        else:  # invoke
            s0 = cfg["states"]["s0"]
            if "invoke" in s0:
                inv = s0["invoke"]
                key = random.choice([k for k in INVOKE_KEYS if k in inv])
                inv[_typo(key)] = inv.pop(key)
            else:
                continue
        try:
            make_machine(cfg, strict=True)
            fails.append((i, level, "NOT CAUGHT"))
        except InvalidConfigError:
            pass
        except Exception as ex:  # noqa: BLE001
            fails.append((i, level, f"unexpected: {type(ex).__name__}: {ex}"))
    return fails


def fuzz_valid(n):
    fp = []
    for i in range(n):
        random.seed(10000 + i)
        cfg = valid_machine()
        try:
            make_machine(cfg, strict=True)
        except InvalidConfigError as ex:
            fp.append((i, str(ex)))
        except Exception as ex:  # noqa: BLE001
            fp.append((i, f"unexpected: {type(ex).__name__}: {ex}"))
    return fp


def main():
    n = 400
    typo_fails = fuzz_typo(n)
    valid_fp = fuzz_valid(n)
    print(f"typo fuzzer: {n} cases, {len(typo_fails)} not-caught/unexpected")
    for f in typo_fails[:10]:
        print("  ", f)
    print(f"valid-grammar fuzzer: {n} cases, {len(valid_fp)} false positives")
    for f in valid_fp[:10]:
        print("  ", f)
    ok = not typo_fails and not valid_fp
    print("VERDICT", "PASS" if ok else "FAIL")
    with open(os.path.join(os.path.dirname(__file__), "out", "j3_key_fuzz.json"), "w") as fh:
        json.dump({"typo_fails": typo_fails, "valid_fp": valid_fp}, fh, indent=2)


if __name__ == "__main__":
    main()
