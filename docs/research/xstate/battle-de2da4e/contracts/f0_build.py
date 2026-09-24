# -*- coding: utf-8 -*-
"""F0: every catalogue machine MUST build under recursive strictConfig (#220).

Standalone: stdlib + xstate_statemachine only. Run from any cwd.
"""
from __future__ import annotations
import pathlib, sys, warnings

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cvf as K  # noqa: E402

IDS = ["B1", "B2", "B3", "B4", "B5", "B16", "B17", "B18", "B19", "B20"]

for bid in IDS:
    c = K.cfg(bid)
    st = K.Stub(c)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            m = K.build(c, st)
            ok, note = True, "root=%s acts=%d guards=%d svcs=%d warn=%d" % (
                m.id, len(st.acts), len(st.guards), len(st.svcs), len(w))
        except Exception as e:
            ok, note = False, repr(e)[:300]
    K.rec("F0.build." + bid, ok, note)

# #220 recursion must fire on a deliberately bad nest (negative control)
bad = {"id": "m", "initial": "a", "strictConfig": True,
       "states": {"a": {"entyr": ["x"], "onn": {"GO": "b"}}, "b": {}}}
try:
    K.build(bad, K.Stub(bad))
    K.rec("F0.220.nested-typo-rejected", False, "built clean")
except Exception as e:
    K.rec("F0.220.nested-typo-rejected",
          "entyr" in repr(e) and "onn" in repr(e) and "m.a" in repr(e),
          repr(e)[:200])

K.dump("f0_build.json")
