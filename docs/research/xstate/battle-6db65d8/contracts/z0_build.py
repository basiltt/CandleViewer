# -*- coding: utf-8 -*-
"""Step 0: create_machine on B1-B5 with both service styles."""
from __future__ import annotations
import asyncio, json
import cv6db as K

for b in ["B1", "B2", "B3", "B4", "B5"]:
    c = K.cfg(b)
    for style in ("async", "def"):
        try:
            st = K.Stub(c, svc_style=style)
            m = K.build(c, st)
            K.rec("%s.build.%s" % (b, style), True,
                  "acts=%d guards=%d svcs=%d delays=%s"
                  % (len(st.acts), len(st.guards), len(st.svcs), st.delays))
        except Exception as e:
            K.rec("%s.build.%s" % (b, style), False, repr(e))
K.dump("res_z0.json")
