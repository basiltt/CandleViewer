import asyncio, json, cvlib
from cvlib import Rig
async def main():
    cfg = cvlib.load("B8")
    rig = Rig(service_mode={"attach_native_sl": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start(); await asyncio.sleep(0.05)
    await interp.send("POSITION_OPENED"); await asyncio.sleep(0.05)
    mid = sorted(interp.current_state_ids)
    calls_mid = list(rig.calls)
    r = await interp.send("SL_DEADLINE", wait=True); await asyncio.sleep(0.05)
    out = {"mid": mid, "calls_mid": calls_mid,
           "after": sorted(interp.current_state_ids), "calls": list(rig.calls),
           "receipt": {"changed": r.changed, "deferred": r.deferred, "denied": r.denied,
                       "error": type(r.error).__name__ if r.error else None},
           "gates": {k: v.is_set() for k, v in rig.gates.items()},
           "status": interp.status, "trace": interp.context.get("_trace")}
    await interp.stop()
    print(json.dumps(out, indent=1))
asyncio.run(main())
