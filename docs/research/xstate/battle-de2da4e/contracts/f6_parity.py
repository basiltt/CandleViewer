# -*- coding: utf-8 -*-
"""Async vs Sync parity for B1-B5 + B18 on f28719c (def services on sync)."""
from __future__ import annotations
import asyncio, json
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cvf as K
os.chdir("<home>")
import f1_b1 as Z1, f2_b2 as Z2, f3_b3 as Z3, f4_b45 as Z4, f5_b18 as Z8

CASES = [
    ("B1", K.cfg("B1"), Z1.s1, ["VALIDATE", "SEND", "FIRST_FILL", "EXEC"]),
    ("B3", K.cfg("B3"), Z3.s3, ["ORDER_OPEN", "UNWIND"]),
    ("B4", K.cfg("B4"), Z4.s4, ["LEG_A_FILL", "CHILDREN_TERMINAL"]),
    ("B18", K.cfg("B18"), Z8.s18,
     [("ENGAGE", {"cancel_working": True, "flatten": True})]),
]


async def main():
    out = {}
    for bid, c, mk, script in CASES:
        ra = await K.drive(c, mk(), script, snapshots=False)
        ss = mk(); ss.sync = True; ss.svc_style = "def"
        rs = K.drive_sync(c, ss, script)
        for f in ("states", "context", "actions", "svc_calls"):
            K.rec("%s.parity.%s" % (bid, f), ra[f] == rs[f],
                  "async=%s\nsync=%s" % (ra[f], rs[f]))
        out[bid] = {"async": ra, "sync": rs}
    json.dump(out, open("results/parity.%s.json" % K.STYLE, "w"),
              indent=1, default=str)


if __name__ == "__main__":
    asyncio.run(main())
    K.dump("results/res_parity.json")
