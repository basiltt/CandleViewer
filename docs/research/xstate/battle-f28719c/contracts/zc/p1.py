import asyncio, json
import cvz as K
C3 = K.cfg("B3")
import z_b3 as Z
async def m():
    for tag, svc in (("both-fail", {"reduce_only_close": RuntimeError("no"),
                                    "assert_native_sl": RuntimeError("no sl")}),
                     ("only-sl-fail", {"poll_until_flat": lambda *a: {"flat": False},
                                       "assert_native_sl": RuntimeError("no sl")})):
        r = await K.drive(C3, Z.s3(svc=svc), ["ORDER_OPEN", "UNWIND"], snapshots=False)
        print(tag, r["states"], r["status"], r["error"])
        print("  acts:", r["actions"])
        print("  svc:", r["svc_calls"], "svc_err:", r["service_errors"][:3])
asyncio.run(m())
