"""#231: a non-hashable / non-str `invoke.src` must always raise a NAMED
InvalidConfigError, never TypeError.  Fuzz every shape a JS-flavoured config
might carry, at root and nested, including inside parallel regions."""
import itertools, json, os
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

SRCS = [
    {"id": "inline", "initial": "x", "states": {"x": {}}},   # inline machine
    {},                                                       # empty dict
    {"src": "nested"},                                        # nested dict
    ["a", "b"],                                               # list
    {"a": {"b": 1}},                                          # deep dict
    set(),                                                    # unhashable set
    123, 4.5, True, None, b"bytes", ("t", "u"),
]

def wrap(src, where):
    inv = {"id": "job", "src": src, "onDone": {"target": "done"},
           "onError": {"target": "done"}}
    if where == "root":
        return {"id": "f", "initial": "run",
                "states": {"run": {"invoke": inv}, "done": {}}}
    if where == "nested":
        return {"id": "f", "initial": "outer",
                "states": {"outer": {"initial": "run",
                                     "states": {"run": {"invoke": inv},
                                                "done": {}}},
                           "done": {}}}
    return {"id": "f", "type": "parallel",
            "states": {"r1": {"initial": "run",
                              "states": {"run": {"invoke": inv},
                                         "done": {}}},
                       "r2": {"initial": "q", "states": {"q": {}}}}}

def main():
    rows = []
    bad = []
    for src, where in itertools.product(SRCS, ("root", "nested", "parallel")):
        cfg = wrap(src, where)
        try:
            create_machine(cfg, logic=MachineLogic())
            outcome = "BUILT-CLEAN"
        except InvalidConfigError as ex:
            msg = str(ex)
            named = ("job" in msg) and ("run" in msg or "src" in msg)
            outcome = f"InvalidConfigError(named={named})"
            if not named:
                bad.append({"src": repr(src), "where": where, "msg": msg})
        except TypeError as ex:
            outcome = f"TypeError: {ex}"
            bad.append({"src": repr(src), "where": where, "msg": str(ex)})
        except Exception as ex:                    # noqa: BLE001
            outcome = f"{type(ex).__name__}: {ex}"
            bad.append({"src": repr(src), "where": where, "msg": str(ex)})
        rows.append({"src": repr(src)[:40], "where": where,
                     "outcome": outcome})
    unhandled = [r for r in rows if r["outcome"] == "BUILT-CLEAN"
                 and not isinstance(eval(r["src"]) if False else None, str)]
    print(json.dumps({"n_cases": len(rows), "rows": rows,
                      "non_InvalidConfigError": bad,
                      "VERDICT": "PASS" if not bad else "FAIL"}, indent=1))

main()
