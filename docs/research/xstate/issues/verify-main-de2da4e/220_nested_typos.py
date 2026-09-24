"""VERIFY #220 on de2da4e (STANDALONE; stdlib + xstate_statemachine only).

Claim: unknown-key check recurses into every state, transition and invoke
level (root/state/nested/parallel/transition/invoke), names the offending
path + a "did you mean" hint, strict_config raises (else warns), and
x-/meta/description/tags are accepted at EVERY level. Also: no false
positive on any valid full-featured catalogue machine.

Exit 0 = all cells pass, AND every catalogue machine.json builds clean
under strict_config=True. Exit 1 = any typo missed, any metadata key
rejected, or any catalogue machine falsely flagged.
"""
import glob
import json
import os
import sys

from xstate_statemachine import InvalidConfigError, MachineLogic, create_machine
from xstate_statemachine.logic_loader import LogicLoader
from xstate_statemachine.models import MachineNode


def _stub_logic(cfg):
    """Build a MachineLogic with a harmless no-op for every action/guard/
    service the config references, so the ONLY thing that can reject the
    build is the #220 key validator itself (not a missing user callable
    unrelated to this issue)."""
    tree = MachineNode(config=cfg, logic=MachineLogic())
    actions, guards, services = LogicLoader.required_names(tree)
    return MachineLogic(
        actions={n: (lambda i, c, e, a: None) for n in actions},
        guards={n: (lambda c, e: True) for n in guards},
        services={n: (lambda i, c, e: None) for n in services},
    )

ROOT = r"C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/research/xstate"
CONTRACT_DIRS = [
    f"{ROOT}/battle-c78ce99/contracts",
    f"{ROOT}/battle-19cb1f1/contracts",
    f"{ROOT}/battle-3ed3099/contracts",
]


def _try_build(cfg, strict):
    try:
        create_machine(json.loads(json.dumps(cfg)), strict_config=strict)
        return True, None
    except InvalidConfigError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def cell_root_typo():
    cfg = {"id": "m", "initial": "a", "states": {"a": {}}, "actoinErrorPolicy": "x"}
    built, msg = _try_build(cfg, True)
    ok = (not built) and "actoinErrorPolicy" in (msg or "")
    return ok, msg


def cell_state_level_typo():
    cfg = {"id": "m", "initial": "a", "states": {"a": {"entyr": ["x"]}}}
    built, msg = _try_build(cfg, True)
    ok = (not built) and "entyr" in (msg or "") and "did you mean 'entry'" in (msg or "")
    return ok, msg


def cell_nested_state_typo():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {
                "initial": "inner",
                "states": {"inner": {"onn": {"GO": "a"}}},
            }
        },
    }
    built, msg = _try_build(cfg, True)
    ok = (not built) and "onn" in (msg or "") and "did you mean 'on'" in (msg or "")
    return ok, msg


def cell_parallel_typo():
    cfg = {
        "id": "m",
        "type": "parallel",
        "states": {
            "r1": {"initial": "x", "states": {"x": {}}},
            "r2": {"initial": "y", "states": {"y": {}}, "statuss": "extra"},
        },
    }
    built, msg = _try_build(cfg, True)
    ok = (not built) and "statuss" in (msg or "")
    return ok, msg


def cell_transition_typo():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": {"targit": "b"}}},
            "b": {},
        },
    }
    built, msg = _try_build(cfg, True)
    ok = (not built) and "targit" in (msg or "") and "did you mean 'target'" in (msg or "")
    return ok, msg


def cell_invoke_typo():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"invoke": {"srcc": "svc", "id": "i1"}}},
    }
    built, msg = _try_build(cfg, True)
    ok = (not built) and "srcc" in (msg or "")
    return ok, msg


def cell_strict_false_warns_not_raises():
    cfg = {"id": "m", "initial": "a", "states": {"a": {"entyr": ["x"]}}}
    built, msg = _try_build(cfg, False)
    return built, msg


def _try_build_with_stub_logic(cfg, strict):
    try:
        logic = _stub_logic(cfg)
        create_machine(json.loads(json.dumps(cfg)), logic=logic, strict_config=strict)
        return True, None
    except InvalidConfigError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def cell_metadata_accepted_everywhere():
    cfg = {
        "id": "m",
        "initial": "a",
        "meta": {"k": 1},
        "description": "root",
        "tags": ["r"],
        "x-custom-root": 1,
        "states": {
            "a": {
                "meta": {},
                "description": "state",
                "tags": ["s"],
                "x-custom-state": 1,
                "on": {
                    "GO": {
                        "target": "a",
                        "reenter": True,
                        "meta": {},
                        "description": "t",
                        "tags": ["t"],
                        "x-custom-t": 1,
                    }
                },
                "invoke": {
                    "src": "svc",
                    "id": "i1",
                    "meta": {},
                    "description": "inv",
                    "tags": ["i"],
                    "x-custom-inv": 1,
                },
            }
        },
    }
    built, msg = _try_build_with_stub_logic(cfg, True)
    return built, msg


def cell_catalogue_no_false_positives():
    files = []
    for d in CONTRACT_DIRS:
        files.extend(sorted(glob.glob(os.path.join(d, "*.machine.json"))))
    results = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            results.append((f, "SKIP(load)", str(exc)))
            continue
        try:
            logic = _stub_logic(cfg)
        except Exception as exc:  # noqa: BLE001
            results.append((f, "SKIP(stub)", str(exc)))
            continue
        try:
            create_machine(cfg, logic=logic, strict_config=True)
            results.append((f, True, None))
        except InvalidConfigError as exc:
            results.append((f, False, str(exc)))
        except Exception as exc:  # noqa: BLE001
            results.append((f, False, f"{type(exc).__name__}: {exc}"))
    return files, results


def main():
    fail = False

    cells = [
        ("root typo", cell_root_typo),
        ("state-level typo", cell_state_level_typo),
        ("nested-state typo", cell_nested_state_typo),
        ("parallel-region typo", cell_parallel_typo),
        ("transition typo", cell_transition_typo),
        ("invoke typo", cell_invoke_typo),
    ]
    for name, fn in cells:
        ok, msg = fn()
        print(f"[{name}] {'OK' if ok else 'FAIL'} :: {msg}")
        fail = fail or not ok

    built, msg = cell_strict_false_warns_not_raises()
    ok = built  # strict_config=False must NOT raise
    print(f"[strict_config=False does not raise on nested typo] built={built} {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    built, msg = cell_metadata_accepted_everywhere()
    ok = built
    print(f"[x-/meta/description/tags accepted at every level] built={built} msg={msg} {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    files, results = cell_catalogue_no_false_positives()
    n_files = len(files)
    n_rejected = sum(1 for _, built, _ in results if built is not True)
    print(f"[catalogue sweep] {n_files} files, {n_rejected} rejected/errored")
    for f, built, msg in results:
        if built is not True:
            print(f"  REJECTED: {os.path.basename(f)} :: {msg}")
    ok = n_files > 0 and n_rejected == 0
    fail = fail or not ok
    print(f"[catalogue sweep verdict] {'OK' if ok else 'FAIL'}")

    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
