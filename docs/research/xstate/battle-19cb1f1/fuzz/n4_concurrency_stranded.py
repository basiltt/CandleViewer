"""N4 -- #206 delayed self-send under concurrency + #207 stranded hook storm.

A  100 machines, each a `raise(delay=1ms)` self-ping-pong, run concurrently.
   #206 says a delayed self-send is a DEBT of the arming step and its firing
   is charged as engine work, so the cycle trips at the same lap as the
   zero-delay `raise` cycle (+/-1). Under concurrency every machine must
   trip, and at the SAME lap -- a budget whose trip point depends on load is
   not a budget. Both service/action kinds (`def` and `async def` actions).

B  Zero-delay reference cycle, same shape, same limit: the lap counts must
   agree within 1 (the changelog's own tolerance).

C  #207 stranded-invocation hook under 200 concurrent rollback+onDone
   storms. For each machine that trips: `on_invocation_stranded` must fire
   EXACTLY ONCE per stranded invoke, the ids must be the real
   (state_id, invoke_id), and `RunawayChainError.stranded` must carry the
   same ids. Both service kinds.

D  Ordering: `on_invocation_stranded` vs `on_event_dropped` for the same cut.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import time
import warnings
from collections import Counter

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

MI = 12
N_PINGPONG = 100
N_STORM = 200


def ping_cfg(delay):
    """Self-ping-pong; `delay=None` is the zero-delay `raise` reference."""
    params = {"event": "GO"}
    if delay is not None:
        params["delay"] = delay
    return {
        "id": "pp",
        "initial": "a",
        "maxIterations": MI,
        "context": {"laps": 0},
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": dict(params)}],
                "on": {"GO": "b"},
                "exit": ["tick"],
            },
            "b": {
                "entry": [{"type": "raise", "params": dict(params)}],
                "on": {"GO": "a"},
                "exit": ["tick"],
            },
        },
    }


def tick_def(i, c, e, a=None):
    c["laps"] = c.get("laps", 0) + 1


async def tick_async(i, c, e, a=None):
    c["laps"] = c.get("laps", 0) + 1


class Watch(PluginBase):
    def __init__(self):
        self.order = []
        self.stranded = []
        self.dropped = []
        self.err = None

    def on_invocation_stranded(self, interp, state_id, invoke_id, error):
        self.stranded.append((state_id, invoke_id))
        self.order.append("stranded")
        self.err = error

    def on_event_dropped(self, interp, event, reason=None, **kw):
        self.dropped.append(reason)
        self.order.append("dropped")


async def run_ping(delay, kind):
    tick = tick_def if kind == "def" else tick_async
    m = create_machine(ping_cfg(delay), logic=MachineLogic(actions={"tick": tick}))
    it = Interpreter(m)
    await it.start()
    try:
        await it.send("KICK")
    except Exception:  # noqa: BLE001
        pass
    # wait for CONVERGENCE, not a fixed sample (the #210 lesson)
    prev, stable = -1, 0
    for _ in range(150):
        await asyncio.sleep(0.02)
        if it.last_error is not None:
            break
        cur = it.context.get("laps", 0)
        if cur == prev:
            stable += 1
            if stable > 8:
                break
        else:
            prev, stable = cur, 0
    laps = it.context.get("laps", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    await it.stop()
    return laps, err


# ---------------------------------------------------------------- storm (C/D)

# The library's own #207 pin shape (tests/test_round9_findings.py:518):
# rollback on the onDone target's entry rewinds into the invoking state,
# which re-arms -- the cycle the cut strands.
STORM_CFG = {
    "id": "st",
    "initial": "idle",
    "maxIterations": 6,
    "actionErrorPolicy": "rollback",
    "context": {},
    "states": {
        "idle": {"on": {"GO": "starting"}},
        "starting": {
            "invoke": {"id": "fill", "src": "svc", "onDone": "recording"}
        },
        "recording": {"entry": ["boom"]},
    },
}


def boom(i, c, e, a=None):
    raise RuntimeError("rollback")


def svc_def(i, c, e):
    return {"ok": 1}


async def svc_async(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


async def run_storm(kind):
    w = Watch()
    m = create_machine(
        STORM_CFG,
        logic=MachineLogic(
            actions={"boom": boom},
            services={"svc": svc_def if kind == "def" else svc_async},
        ),
    )
    it = Interpreter(m).use(w)
    await it.start()
    try:
        await it.send("GO")
    except Exception:  # noqa: BLE001
        pass
    # NOTE: `last_error` is set by the rollback's own RuntimeError long
    # before the cut, so breaking on "any error" samples the chain while it
    # is still climbing (the #210 mistake). Wait for the RunawayChainError.
    for _ in range(250):
        if type(it.last_error).__name__ == "RunawayChainError":
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    err = it.last_error
    payload = tuple(getattr(err, "stranded", ()) or ())
    dormant = it.has_dormant_invocations
    pend = [(p.state_id, p.invoke_id) for p in it.pending_invocations()]
    await it.stop()
    return {
        "err": type(err).__name__ if err else None,
        "hook": list(w.stranded),
        "payload": payload,
        "order": w.order[:6],
        "dormant": dormant,
        "pending": pend,
    }


async def main():
    print("N4 -- #206 delayed self-send under load, #207 stranded storm")
    print()
    bad = []

    print(f"A/B: {N_PINGPONG} concurrent delayed(1ms) self-ping-pongs vs the")
    print(f"     zero-delay reference, maxIterations={MI}")
    for kind in ("def", "async def"):
        t0 = time.monotonic()
        res = await asyncio.gather(
            *[run_ping(1, kind) for _ in range(N_PINGPONG)]
        )
        el = time.monotonic() - t0
        laps = Counter(r[0] for r in res)
        errs = Counter(r[1] for r in res)
        ref_laps, ref_err = await run_ping(None, kind)
        print(
            f"   {kind:<9} delayed laps={dict(laps)} errs={dict(errs)} "
            f"({el:.1f}s)   zero-delay ref laps={ref_laps} err={ref_err}"
        )
        if len(laps) != 1:
            bad.append(
                f"A/{kind}: trip lap varies under concurrency: {dict(laps)}"
            )
        if None in errs:
            bad.append(
                f"A/{kind}: {errs[None]}/{N_PINGPONG} machines never tripped "
                f"(delayed self-send not bounded)"
            )
        only = next(iter(laps))
        if abs(only - ref_laps) > 1:
            bad.append(
                f"B/{kind}: delayed cycle trips at lap {only}, zero-delay "
                f"reference at {ref_laps} (changelog tolerance is +/-1)"
            )
    print()

    print(f"C/D: {N_STORM} concurrent rollback+onDone storms, stranded hook")
    for kind in ("def", "async def"):
        t0 = time.monotonic()
        res = await asyncio.gather(*[run_storm(kind) for _ in range(N_STORM)])
        el = time.monotonic() - t0
        hookn = Counter(len(r["hook"]) for r in res)
        ids = Counter(tuple(r["hook"]) for r in res)
        payload_match = sum(
            1
            for r in res
            if tuple(i for _, i in r["hook"]) == tuple(r["payload"])
        )
        tripped = sum(1 for r in res if r["err"] == "RunawayChainError")
        orders = Counter(tuple(r["order"]) for r in res)
        print(
            f"   {kind:<9} tripped={tripped}/{N_STORM} "
            f"hook_count_hist={dict(hookn)} ids={dict(ids)} "
            f"payload_matches_hook={payload_match}/{N_STORM} ({el:.1f}s)"
        )
        print(f"             hook order samples: {dict(orders)}")
        print(f"             sample pending={res[0]['pending']} "
              f"dormant={res[0]['dormant']}")
        if tripped and set(hookn) - {1}:
            bad.append(
                f"C/{kind}: on_invocation_stranded not exactly-once: "
                f"{dict(hookn)}"
            )
        if any(("st.starting", "fill") not in r["hook"] for r in res if r["hook"]):
            bad.append(f"C/{kind}: wrong (state_id, invoke_id) reported")
        if tripped and payload_match != N_STORM:
            bad.append(
                f"C/{kind}: RunawayChainError.stranded disagrees with the "
                f"hook in {N_STORM - payload_match} runs"
            )
        if tripped and any(not r["dormant"] for r in res if r["hook"]):
            bad.append(
                f"C/{kind}: stranded reported but has_dormant_invocations "
                f"is False"
            )
    print()
    print(f"DEFECTS = {len(bad)}")
    for b in bad:
        print(f"   - {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
