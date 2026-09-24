# -*- coding: utf-8 -*-
"""p0: create_machine for B16-B20 on c78ce99 under #216 strictConfig.

Three builds per machine:
  a) as-carried JSON, strict_config=True  -> must be clean (no unknown keys)
  b) JSON + "strictConfig": true          -> config-level opt-in, must be clean
  c) JSON with a deliberately typo'd policy key -> must raise InvalidConfigError
Both service spellings.
"""
from __future__ import annotations
import copy, json, os, sys

os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
import cvc78 as H
from cvc78 import Stub
from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.validation import KNOWN_MACHINE_KEYS

STYLE = os.environ["CV_SVC_STYLE"]

for b in ["B16", "B17", "B18", "B19", "B20"]:
    c = H.cfg(b)
    unknown = sorted(k for k in c if k not in KNOWN_MACHINE_KEYS
                     and not k.startswith("x-"))
    H.rec("keys/%s no unknown top-level key" % b, not unknown,
          "unknown=%s; keys=%s" % (unknown, sorted(c)))
    st = Stub(c, svc_style=STYLE)
    # (a) explicit strict_config=True
    try:
        create_machine(copy.deepcopy(c), logic=st.logic(),
                       strict_targets=True, strict_config=True)
        H.rec("build/%s strict_config=True" % b, True,
              "acts=%d guards=%d svcs=%d" % (len(st.acts), len(st.guards),
                                             len(st.svcs)))
    except Exception as e:
        H.rec("build/%s strict_config=True" % b, False, repr(e))
    # (b) config-level "strictConfig": true
    c2 = copy.deepcopy(c)
    c2["strictConfig"] = True
    try:
        create_machine(c2, logic=Stub(c, svc_style=STYLE).logic(),
                       strict_targets=True)
        H.rec("build/%s config strictConfig:true" % b, True)
    except Exception as e:
        H.rec("build/%s config strictConfig:true" % b, False, repr(e))
    # (c) negative control: typo'd policy must be refused
    c3 = copy.deepcopy(c)
    c3["actionErrorPolicyy"] = c3.pop("actionErrorPolicy")
    c3["strictConfig"] = True
    try:
        create_machine(c3, logic=Stub(c, svc_style=STYLE).logic(),
                       strict_targets=True)
        H.rec("build/%s typo refused" % b, False, "built clean -- #216 miss")
    except InvalidConfigError as e:
        H.rec("build/%s typo refused" % b,
              "actionErrorPolicy" in repr(e), repr(e)[:180])
    except Exception as e:
        H.rec("build/%s typo refused" % b, False, "wrong exc " + repr(e))

H.dump("results/p0_build.json")
