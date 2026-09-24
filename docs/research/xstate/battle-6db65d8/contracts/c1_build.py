# -*- coding: utf-8 -*-
"""Step 1: build B6-B10 on cec108b, read back policy block, start smoke."""
import asyncio, json, sys
from cdrv import cfg_of, mk
from charness import Stub, build, ids

async def main():
    out = {}
    for b in ["B6","B7","B8","B9","B10"]:
        cfg = cfg_of(b); rec = {}
        st = Stub(cfg)
        try:
            m = build(cfg, st)
            rec["build"] = "OK"
            rec["policy"] = {k: getattr(m, a, "<missing>") for k, a in [
                ("actionErrorPolicy","action_error_policy"),
                ("onUnhandled","on_unhandled"),
                ("guardErrorPolicy","guard_error_policy"),
                ("strictTargets","strict_targets"),
                ("spawnBlockingTimeout","spawn_blocking_timeout")]}
            rec["strict_logic"] = m.logic.strict
            rec["counts"] = dict(actions=len(st.acts), guards=len(st.guards),
                                 services=len(st.svcs), events=len(st.events))
            rec["known_star"] = "*" in getattr(m, "known_events", set())
        except Exception as e:
            rec["build"] = f"{type(e).__name__}: {e}"
            out[b] = rec; continue
        try:
            interp, st2, tp, clock, m2 = await mk(b)
            rec["start_ids"] = ids(interp); rec["status"] = interp.status
            await interp.stop()
        except Exception as e:
            rec["start"] = f"{type(e).__name__}: {str(e)[:200]}"
        out[b] = rec
    json.dump(out, open("c1_build.json","w"), indent=1)
    print(json.dumps(out, indent=1))

asyncio.run(main())
