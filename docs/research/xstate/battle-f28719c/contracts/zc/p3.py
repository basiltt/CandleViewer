"""Tail latency of the async-service chain after send(wait=True) returns."""
import asyncio, time, statistics
import cvz as K
import z_b3 as Z
C3 = K.cfg("B3")
async def burn(stop):
    while not stop.is_set():
        await asyncio.sleep(0)
async def once(load):
    st = Z.s3(svc={"reduce_only_close": RuntimeError("no"),
                   "assert_native_sl": RuntimeError("no sl")})
    m, i, p = await K.new_async(C3, st)
    stop = asyncio.Event()
    bs = [asyncio.create_task(burn(stop)) for _ in range(load)]
    for ev in ("ORDER_OPEN", "UNWIND"):
        await i.send(ev, wait=True)
    t0 = time.perf_counter()
    at_return = sorted(i.current_state_ids)
    for _ in range(2000):
        if sorted(i.current_state_ids) == ["leg.error"]:
            break
        await asyncio.sleep(0.001)
    d = time.perf_counter() - t0
    stop.set(); await asyncio.gather(*bs)
    await i.stop()
    return at_return, d
async def m():
    for load in (0, 50, 400):
        ds = []
        for _ in range(6):
            r, d = await once(load)
            ds.append(d)
        print("load=%d at_send_return=%s tail_ms med=%.1f max=%.1f"
              % (load, r, statistics.median(ds)*1000, max(ds)*1000))
asyncio.run(m())
