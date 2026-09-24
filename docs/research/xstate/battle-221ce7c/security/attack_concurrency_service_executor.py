"""New attack: 200 concurrent plain-def (blocking) services on
service_executor + stop() mid-service (#149). Checks: no crash, no hang,
no leaked threads after teardown, stop() during in-flight services
terminates cleanly and does not leave the interpreter or its executor in
a stuck/zombie state."""
import sys, asyncio, threading, time
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter

def slow_service(interp, context, event):
    time.sleep(0.05)
    return {"ok": True}

cfg = {
    "id": "m", "initial": "a", "context": {},
    "states": {
        "a": {
            "invoke": {"src": "slow", "onDone": "b", "onError": "err"},
        },
        "b": {}, "err": {},
    },
}
m = create_machine(cfg, logic=MachineLogic(services={"slow": slow_service}))

before_threads = threading.active_count()

async def one_run():
    interp = Interpreter(m)
    await interp.start()
    await asyncio.sleep(0.01)  # let the service kick off
    await interp.stop()  # stop() MID-SERVICE
    return interp.status

async def main():
    results = await asyncio.gather(*[one_run() for _ in range(200)],
                                    return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    statuses = [r for r in results if not isinstance(r, Exception)]
    print(f"runs=200 errors={len(errors)} statuses={set(statuses)}")
    for e in errors[:5]:
        print(" ERROR:", type(e).__name__, e)

asyncio.run(main())
time.sleep(0.5)
after_threads = threading.active_count()
print(f"threads before={before_threads} after={after_threads} "
      f"(leak if after >> before after GC settle)")
if after_threads > before_threads + 5:
    print("FINDING: possible thread leak from service_executor after 200 "
          "stop()-mid-service cycles.")
else:
    print("OK: no significant thread growth after 200 stop()-mid-service cycles.")
