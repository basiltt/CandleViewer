"""P9 (STANDALONE): #193 moved the `def`-service executor handoff into the
engine-held task and added `await asyncio.sleep(0)` before submission.

Check the #116 contract still holds: the entering macrostep awaits the
plain service, so an external event sent immediately after cannot pre-empt
the completion. Also check both service kinds and that a rolled-forward
state (an `always` out of the invoking state) never submits the callable.

Exit 1 if the `def` service is submitted for a state the machine left, or
if ordering regressed.
"""
import asyncio, json, sys, time
from xstate_statemachine import create_machine, Interpreter, MachineLogic

ORDER = []
SUBMITTED = {"n": 0}

ORDERING_CFG = {
    "id": "m",
    "initial": "load",
    "states": {
        "load": {"invoke": {"id": "s", "src": "s",
                            "onDone": {"target": "ok", "actions": ["seen_done"]}},
                 "on": {"PING": {"actions": ["seen_ping"]}}},
        "ok": {"on": {"PING": {"actions": ["seen_ping"]}}},
    },
}

ROLLFWD_CFG = {
    "id": "m",
    "initial": "arm",
    "context": {"go": True},
    "states": {
        "arm": {"invoke": {"id": "s", "src": "s"},
                "always": [{"target": "gone", "cond": "always_true"}]},
        "gone": {},
    },
}


def def_service(i, c, e):
    SUBMITTED["n"] += 1
    time.sleep(0.05)
    return "R"


async def async_service(i, c, e):
    SUBMITTED["n"] += 1
    await asyncio.sleep(0.05)
    return "R"


def seen_done(i, c, e, adef=None):
    ORDER.append("done")


def seen_ping(i, c, e, adef=None):
    ORDER.append("ping")


def build(cfg, svc):
    return create_machine(
        json.loads(json.dumps(cfg)),
        logic=MachineLogic(
            services={"s": svc},
            actions={"seen_done": seen_done, "seen_ping": seen_ping},
            guards={"always_true": lambda c, e: True},
        ),
    )


async def ordering(svc):
    ORDER.clear()
    i = Interpreter(build(ORDERING_CFG, svc))
    await i.start()
    await i.send("PING")
    await asyncio.sleep(0.4)
    out = list(ORDER)
    await i.stop()
    return out


async def rollforward(svc):
    SUBMITTED["n"] = 0
    i = await Interpreter(build(ROLLFWD_CFG, svc)).start()
    await asyncio.sleep(0.4)
    n, ids = SUBMITTED["n"], sorted(i.current_state_ids)
    await i.stop()
    return n, ids


async def main():
    rows = []
    for label, svc in (("def", def_service), ("async def", async_service)):
        rows.append((label, await ordering(svc), await rollforward(svc)))
    return rows


bad = 0
for label, order, (n, ids) in asyncio.run(asyncio.wait_for(main(), 30.0)):
    print(f"{label:>9}: order={order} rollforward_submissions={n} states={ids}")
    # `def` must complete inside the entering step (#116); `async def` is
    # interruptible by design, so PING legitimately precedes its completion.
    if label == "def" and order[:1] != ["done"]:
        bad = 1
    if n:
        bad = 1
print("VERDICT:", "REGRESSION" if bad else "contract holds (ok)")
sys.exit(bad)
