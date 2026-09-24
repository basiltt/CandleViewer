# -*- coding: utf-8 -*-
"""n0: create_machine for B16-B20 on 19cb1f1, both service spellings."""
from __future__ import annotations
import json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
import cv19 as H
from cv19 import Stub
from xstate_statemachine.exceptions import InvalidConfigError

res = {}
for b in ["B16", "B17", "B18", "B19", "B20"]:
    c = H.cfg(b)
    try:
        st = Stub(c, svc_style=os.environ["CV_SVC_STYLE"])
        m = H.build(c, st)
        H.rec("build/%s" % b, True, "acts=%d guards=%d svcs=%d delays=%s" % (
            len(st.acts), len(st.guards), len(st.svcs), st.delays))
    except InvalidConfigError as e:
        H.rec("build/%s" % b, False, "InvalidConfigError: %r" % (e,))
    except Exception as e:
        H.rec("build/%s" % b, False, repr(e))
H.dump("results/n0_build.json")
