# -*- coding: utf-8 -*-
"""create_machine build check for B1-B5 on f28719c (both service styles)."""
from __future__ import annotations
import json
import cvf28 as K

OUT = {}
for bid in ("B1", "B2", "B3", "B4", "B5"):
    c = K.cfg(bid)
    for style in ("async", "def"):
        try:
            st = K.Stub(c, svc_style=style)
            m = K.build(c, st)
            OUT["%s.%s" % (bid, style)] = {
                "ok": True, "initial": sorted(
                    n.id for n in m.initial_state_nodes) if hasattr(
                    m, "initial_state_nodes") else None,
                "acts": len(st.acts), "guards": len(st.guards),
                "svcs": len(st.svcs), "events": len(st.events),
            }
            print("PASS build %s/%s" % (bid, style))
        except Exception as e:
            OUT["%s.%s" % (bid, style)] = {"ok": False, "exc": repr(e)}
            print("FAIL build %s/%s %r" % (bid, style, e))
json.dump(OUT, open("results/z0_build.json", "w"), indent=1, default=str)
