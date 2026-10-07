# -*- coding: utf-8 -*-
"""STANDALONE: #216 strictConfig conformance of the B1-B5 catalogue JSON.

Proves from a neutral cwd. stdlib + xstate_statemachine only.
Pass 1 = all services `async def`, pass 2 = all plain `def` (CV_SVC_STYLE).
"""
from __future__ import annotations
import json, logging, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cv78 as K  # noqa: E402
from xstate_statemachine.validation import KNOWN_MACHINE_KEYS  # noqa: E402
from xstate_statemachine import create_machine  # noqa: E402
from xstate_statemachine.exceptions import InvalidConfigError  # noqa: E402

BS = ["B1", "B2", "B3", "B4", "B5"]


class Catch(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs = []

    def emit(self, r):
        self.msgs.append(r.getMessage())


def main():
    h = Catch()
    logging.getLogger("xstate_statemachine").addHandler(h)
    for b in BS:
        c = K.cfg(b)
        unknown = sorted(k for k in c if k not in KNOWN_MACHINE_KEYS
                         and not k.startswith("x-"))
        K.rec("%s.cfg.no_unknown_top_keys" % b, not unknown, str(unknown))
        st = K.Stub(c)
        n0 = len(h.msgs)
        try:
            K.build(c, st)  # strict_config=True by default in cv78.build
            ok, note = True, "built with strict_config=True"
        except InvalidConfigError as e:
            ok, note = False, repr(e)[:200]
        K.rec("%s.build.strict_config_true" % b, ok, note)
        K.rec("%s.build.no_warning" % b, len(h.msgs) == n0,
              str(h.msgs[n0:])[:200])
        # config-level "strictConfig": true must be equally clean
        c2 = dict(c); c2["strictConfig"] = True
        try:
            create_machine(json.loads(json.dumps(c2)), logic=st.logic(),
                           strict_targets=c.get("strictTargets", True))
            ok2, note2 = True, "config-level strictConfig ok"
        except InvalidConfigError as e:
            ok2, note2 = False, repr(e)[:200]
        K.rec("%s.build.strictConfig_key" % b, ok2, note2)
        # negative control: a typo MUST be refused
        c3 = dict(c); c3["actionErrorPolicyy"] = "rollback"
        try:
            create_machine(json.loads(json.dumps(c3)), logic=st.logic(),
                           strict_targets=True, strict_config=True)
            ok3, note3 = False, "typo ACCEPTED"
        except InvalidConfigError as e:
            ok3, note3 = "did you mean" in str(e), repr(e)[:160]
        K.rec("%s.build.typo_refused" % b, bool(ok3), note3)
    K.dump("res_build.json")


if __name__ == "__main__":
    os.chdir("<home>")
    main()
