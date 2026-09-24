# -*- coding: utf-8 -*-
"""R6-03 class probe: actionErrorPolicy rollback + invoke.onDone.

B2 `unwinding` invokes `unwind_machine`; its onDone action `mark_unwound`
raises. Under rollback the machine returns to `unwinding`, re-arming the
invoke. Question: does the chain budget trip (bounded + observable), or does
the loop run free until something else stops it?

Measures invocation count against wall time at several settle horizons.
"""
from __future__ import annotations
import asyncio, json, time
import cv221 as K
import d_b2_lib as L  # guard/action tables


async def run(horizon: float):
    c = L.with_total(2)
    st = L.b2_stub(guard_vals={"policy_all_or_none_and_any_failed": True},
                   raising=["mark_unwound"])
    m, i, p = await K.new_async(c, st)
    await i.send("CONFIRM")
    t0 = time.perf_counter()
    r = await asyncio.wait_for(i.send("LEG_FAILED"), 20)
    send_sec = time.perf_counter() - t0
    marks = []
    t1 = time.perf_counter()
    while time.perf_counter() - t1 < horizon:
        await asyncio.sleep(0.25)
        marks.append((round(time.perf_counter() - t1, 2),
                      st.svc_calls.count("unwind_machine")))
    out = {
        "horizon": horizon, "send_sec": round(send_sec, 4),
        "states": K.ids(i), "status": i.status,
        "error": None if i.error is None else repr(i.error),
        "last_error": repr(getattr(i, "last_error", "<absent>")),
        "invocations": st.svc_calls.count("unwind_machine"),
        "action_errors": len(p.action_errors),
        "growth": marks,
    }
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    res = []
    for h in (1.0, 3.0):
        r = await run(h)
        print(json.dumps(r), flush=True)
        res.append(r)
    json.dump(res, open("out_r603_probe.json", "w"), indent=1, default=str)
    # verdict
    a, b = res
    grew = b["invocations"] > a["invocations"] * 1.5
    print("\nVERDICT: unbounded-in-time=%s  h1=%d h3=%d  last_error=%s"
          % (grew, a["invocations"], b["invocations"], b["last_error"]))


asyncio.run(main())
