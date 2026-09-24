# -*- coding: utf-8 -*-
"""B16 extras: defer-buffer growth in a terminal region; guardErrorPolicy."""
import asyncio, json
import cdrv
from cdrv import mk, step, obs
from charness import SETTLE

R = {}

async def main():
    # 1. revoked session keeps accepting elevation + buffers forever
    interp, st, tp, clock, m = await mk("B16")
    await step(interp, clock, "MFA_OK")
    await step(interp, clock, "REVOKE")
    cap = None
    for i in range(300):
        try:
            await interp.send("REQUEST")
        except Exception as e:                                  # noqa: BLE001
            cap = f"{type(e).__name__} at i={i}: {str(e)[:160]}"
            break
    await asyncio.sleep(0.1)
    R["defer_growth"] = {"deferred_count": interp.deferred_count,
                         "cap": cap, "ids": sorted(interp.current_state_ids),
                         "status": interp.status,
                         "unhandled_sample": tp.unhandled[:3],
                         "dropped_sample": tp.dropped[:3]}
    await interp.stop()

    # 2. step-up on a revoked session
    interp, st, tp, clock, m = await mk("B16")
    await step(interp, clock, "MFA_OK"); await step(interp, clock, "REVOKE")
    r = await step(interp, clock, "STEP_UP_OK")
    R["step_up_after_revoke"] = {
        "ids": sorted(interp.current_state_ids),
        "receipt": {"changed": r.changed, "deferred": r.deferred},
        "acts_tail": st.trace[-4:]}
    await interp.stop()

    # 3. guardErrorPolicy: raise -> a crashed guard is NOT a denial
    interp, st, tp, clock, m = await mk(
        "B16", {"guard_raise": {"mfa_attempts_exhausted"}})
    r = await step(interp, clock, "MFA_FAILED")
    R["guard_raise"] = {"ids": sorted(interp.current_state_ids),
                        "changed": r.changed,
                        "error": type(r.error).__name__ if r.error else None,
                        "err_msg": str(r.error)[:160] if r.error else None,
                        "status": interp.status, "acts": list(st.trace)}
    await interp.stop()

    # 4. strict: an undeclared event name must raise at the call site
    interp, st, tp, clock, m = await mk("B16")
    try:
        await interp.send("NOT_A_REAL_EVENT")
        await asyncio.sleep(SETTLE)
        R["strict"] = f"accepted; deferred={interp.deferred_count}"
    except Exception as e:                                       # noqa: BLE001
        R["strict"] = f"{type(e).__name__}: {str(e)[:160]}"
    await interp.stop()

asyncio.run(main())
print(json.dumps(R, indent=2, default=str))
json.dump(R, open("results/c1b_b16x.json","w",encoding="utf-8"), indent=2, default=str)
