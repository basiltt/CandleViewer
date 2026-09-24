# -*- coding: utf-8 -*-
"""Step 1 for B6..B10 on 6db65d8: build + policy read-back, both service
styles ("def" and "async def"). Also asserts the mandated policy block is
honoured verbatim by the engine.
"""
from __future__ import annotations
import asyncio, json

import cv6db as H
from cv6db import Stub

BS = ["B6", "B7", "B8", "B9", "B10"]
MAND = {
    "action_error_policy": "rollback",
    "on_unhandled": "defer",
    "guard_error_policy": "raise",
}


def pol(m):
    out = {}
    for a in ("action_error_policy", "on_unhandled", "guard_error_policy",
              "strict_targets", "spawn_blocking_timeout"):
        out[a] = getattr(m, a, "<missing>")
    return out


async def main():
    info = {}
    for b in BS:
        c = H.cfg(b)
        row = {}
        for style in ("async", "def"):
            st = Stub(c, svc_style=style)
            try:
                m = H.build(c, st)
                row[style] = {
                    "built": True, "id": m.id, "policy": pol(m),
                    "counts": {"actions": len(st.acts), "guards": len(st.guards),
                               "services": len(st.svcs), "events": len(st.events)},
                }
            except Exception as e:
                row[style] = {"built": False, "exc": repr(e)}
        info[b] = row
        ok = row["async"].get("built") and row["def"].get("built")
        H.rec(b + "/build", ok, str(row["async"].get("exc", "")))
        if ok:
            p = row["async"]["policy"]
            declared = {k: v for k, v in MAND.items()}
            got = {k: str(p[k]).lower() for k in declared}
            exp = {k: v for k, v in declared.items()}
            if b == "B8":
                exp["action_error_policy"] = "fail"  # as catalogued
            H.rec(b + "/policy", got == exp, json.dumps({"got": got, "exp": exp}))
            H.rec(b + "/strictTargets", p["strict_targets"] is True, str(p))
    # start configuration, both styles
    for b in BS:
        c = H.cfg(b)
        for style in ("async", "def"):
            st = Stub(c, svc_style=style)
            try:
                m, i, p = await H.new_async(c, st)
                await H.quiesce(i, 3)
                info.setdefault(b, {}).setdefault("start", {})[style] = {
                    "states": H.ids(i), "svc_calls": list(st.svc_calls),
                    "status": i.status,
                }
                await asyncio.wait_for(i.stop(), 5)
            except Exception as e:
                info[b].setdefault("start", {})[style] = {"exc": repr(e)}
        s = info[b]["start"]
        same = s["async"].get("states") == s["def"].get("states")
        H.rec(b + "/start-parity(def vs async svc)", same, json.dumps(s))
    (H.HERE / "k6_build.json").write_text(json.dumps(info, indent=1, default=str),
                                          encoding="utf-8")
    H.dump("k6_build_results.json")


asyncio.run(main())
