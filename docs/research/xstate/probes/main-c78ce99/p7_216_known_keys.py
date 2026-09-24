"""P-7 (#216): KNOWN_MACHINE_KEYS completeness and scope.

STANDALONE. Questions:
  a) is every key the PARSER reads present in KNOWN_MACHINE_KEYS? (a false
     positive -- a legitimate key reported as unknown -- is the worse bug,
     since strict_config=True then refuses a valid machine)
  b) is the check top-level ONLY? a misspelled policy on a NESTED state, or a
     misspelled `entry`/`invoke` on a nested state, is the same defect.
  c) does `strictConfig: true` in config reach the check, and does the kwarg
     override it in both directions?
"""

import logging
from typing import Any, Dict, List

from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.validation import KNOWN_MACHINE_KEYS


class Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.msgs: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.msgs.append(record.getMessage())


def build(cfg: Dict[str, Any], **kw: Any) -> Any:
    cap = Cap()
    lg = logging.getLogger("xstate_statemachine.validation")
    lg.addHandler(cap)
    lg.setLevel(logging.WARNING)
    try:
        create_machine(cfg, **kw)
        return None, cap.msgs
    except InvalidConfigError as exc:
        return str(exc)[:120], cap.msgs
    finally:
        lg.removeHandler(cap)


BASE: Dict[str, Any] = {"id": "m", "initial": "a", "states": {"a": {}}}


def main() -> None:
    print("KNOWN_MACHINE_KEYS:", len(KNOWN_MACHINE_KEYS))

    # (a) every key the parser actually reads at the ROOT, one at a time.
    # `_NODE_KEYS` + MachineNode.__init__ reads. If any is reported unknown
    # under strict_config=True, strict mode refuses a VALID machine.
    parser_keys = {
        "id": "m", "initial": "a", "states": {"a": {}}, "type": "compound",
        "context": {}, "output": None, "on": {}, "entry": [], "exit": [],
        "after": {}, "always": [], "invoke": [], "onDone": None,
        "tags": [], "meta": {}, "maxIterations": 50, "strict": False,
        "spawnBlockingTimeout": 10, "strictTargets": False,
        "strictConfig": False, "actionErrorPolicy": "continue",
        "guardErrorPolicy": "false", "onUnhandled": "ignore",
        "description": "d", "version": "1",
    }
    missing = [k for k in parser_keys if k not in KNOWN_MACHINE_KEYS]
    print("a) parser keys NOT in KNOWN_MACHINE_KEYS:", missing)
    err, msgs = build(dict(parser_keys), strict_config=True)
    print("   full-key machine under strict_config=True:", err or "OK", msgs)

    # `history` IS in KNOWN_MACHINE_KEYS but is only read on a `type:
    # history` NODE, never at the root; harmless. The reverse matters:
    print("b) 'history' in known:", "history" in KNOWN_MACHINE_KEYS)

    # (b) nested scope
    nested = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"entryy": ["nope"], "actionErrorPolicyy": "halt",
                  "on": {"GO": "b"}},
            "b": {},
        },
    }
    err, msgs = build(nested, strict_config=True)
    print("   nested typos under strict_config=True ->", err or "ACCEPTED SILENTLY",
          "| warnings:", msgs)

    # (c) config key vs kwarg
    for label, cfg_flag, kwarg in (
        ("config strictConfig=true, no kwarg", True, None),
        ("config false, kwarg True", False, True),
        ("config true, kwarg False", True, False),
        ("neither (default)", False, None),
    ):
        cfg = dict(BASE, actionErrorPolicyy="halt")
        if cfg_flag:
            cfg["strictConfig"] = True
        kw = {} if kwarg is None else {"strict_config": kwarg}
        err, msgs = build(cfg, **kw)
        print(f"c) {label:36s} -> {'RAISED' if err else 'warned: ' + str(len(msgs))}")

    # (d) does an unknown key in a NESTED state ever produce any diagnostic?
    err, msgs = build(nested)
    print("d) nested typos, default mode -> warnings:", msgs or "(none)")


if __name__ == "__main__":
    main()
