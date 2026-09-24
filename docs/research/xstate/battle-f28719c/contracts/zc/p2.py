import asyncio, json, time
import cvz as K
import z_b3 as Z
C3 = K.cfg("B3")
async def once(extra):
    st = Z.s3(svc={"reduce_only_close": RuntimeError("no"),
                   "assert_native_sl": RuntimeError("no sl")})
    m, i, p = await K.new_async(C3, st)
    for ev in ("ORDER_OPEN", "UNWIND"):
        await i.send(ev, wait=True)
    t0 = time.perf_counter()
    for _ in range(extra):
        await asyncio.sleep(0.01)
        if sorted(i.current_state_ids) == ["leg.error"]:
            break
    out = (sorted(i.current_state_ids), round(time.perf_counter()-t0, 3),
           len(st.svc_calls))
    await i.stop()
    return out
async def m():
    for _ in range(8):
        print(await once(300))
asyncio.run(m())
