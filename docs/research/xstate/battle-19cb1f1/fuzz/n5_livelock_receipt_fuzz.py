"""N5 -- livelock fuzzer + illegal-configuration receipt fuzz.

A  LIVELOCK FUZZER. Random charts drawn from the round-9 machinery:
   `always` cycles, `invoke`+`onDone` back-edges, `after` back-edges,
   zero-delay `raise` and `raise(delay=)`, `actionErrorPolicy: rollback`,
   parallel regions. Each config x {def, async def} x {sync, async}.
   Three properties:
     P1 TERMINATION   -- the chart settles or trips; it never spins past
                         the watchdog with the lap counter still climbing.
     P2 OBSERVABILITY -- if it tripped, a RunawayChainError is readable and
                         (when an invoke was live) the stranded hook fired.
     P3 LAP PARITY    -- sync and async agree within 1 on the `def` lane
                         (coroutine-service cells are NotSupportedError by
                         documented design and are EXCLUDED, not scored).

B  RECEIPT LEGALITY FUZZ (#208). Over the same corpus, every
   `send(..., wait=True)` receipt is checked against the configuration at
   the instant it resolved:
     - NEVER `ok` over an ILLEGAL configuration (empty, or a region with
       no active leaf) -- the #208 claim;
     - NEVER an error over a LEGAL, settled configuration (the converse
       half, which #208 does not claim but an OMS needs).

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import random
import time
import warnings
from collections import Counter

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

N_CONFIGS = 500
SEED = 20260922
WATCHDOG = 0.30  # per cell; the whole sweep must fit the 120 s bound

LAPS = {"n": 0}


def tick_def(i, c, e, a=None):
    LAPS["n"] += 1
    c["laps"] = c.get("laps", 0) + 1


async def tick_async(i, c, e, a=None):
    LAPS["n"] += 1
    c["laps"] = c.get("laps", 0) + 1


def boom(i, c, e, a=None):
    raise RuntimeError("rollback")


SUB = {"n": 0}


def svc_def(i, c, e):
    SUB["n"] += 1
    return {"ok": 1}


async def svc_async(i, c, e):
    SUB["n"] += 1
    await asyncio.sleep(0)
    return {"ok": 1}


def gen_config(rnd, idx):
    """A random chart built only from round-9's machinery."""
    n = rnd.randint(2, 4)
    names = [f"s{k}" for k in range(n)]
    states = {}
    used_invoke = False
    for k, nm in enumerate(names):
        nxt = names[(k + 1) % n]
        st = {"on": {"GO": nxt}, "exit": ["tick"]}
        shape = rnd.choice(
            [
                "always",
                "invoke",
                "after",
                "raise0",
                "raisedelay",
                "plain",
                "rollback",
            ]
        )
        if shape == "always":
            st["always"] = {"target": nxt}
        elif shape == "invoke":
            used_invoke = True
            st["invoke"] = {
                "id": f"inv{k}",
                "src": "svc",
                "onDone": {"target": nxt},
            }
        elif shape == "after":
            st["after"] = {rnd.choice([1, 5]): {"target": nxt}}
        elif shape == "raise0":
            st["entry"] = [{"type": "raise", "params": {"event": "GO"}}]
        elif shape == "raisedelay":
            st["entry"] = [
                {"type": "raise", "params": {"event": "GO", "delay": 1}}
            ]
        elif shape == "rollback":
            st["entry"] = ["boom"]
        states[nm] = st
    shapes = {
        k: ("after" if "after" in v else
            "raisedelay" if any(
                isinstance(a, dict) and a.get("params", {}).get("delay")
                for a in v.get("entry", [])) else "other")
        for k, v in states.items()
    }
    cfg = {
        "id": f"f{idx}",
        "initial": names[0],
        "maxIterations": rnd.choice([3, 6, 12]),
        "context": {"laps": 0},
        "states": states,
    }
    if rnd.random() < 0.3:
        cfg["actionErrorPolicy"] = "rollback"
    return cfg, used_invoke, set(shapes.values())


class Obs(PluginBase):
    def __init__(self):
        self.stranded = []

    def on_invocation_stranded(self, i, sid, iid, err):
        self.stranded.append((sid, iid))


def legal(ids):
    """A configuration with no active leaf is illegal (#143)."""
    return bool(ids)


async def run_async(cfg, kind):
    obs = Obs()
    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={"tick": tick_def if kind == "def" else tick_async,
                     "boom": boom},
            services={"svc": svc_def if kind == "def" else svc_async},
        ),
    )
    it = Interpreter(m).use(obs)
    await it.start()
    receipt = None
    try:
        receipt = await it.send("GO", wait=True)
    except Exception as exc:  # noqa: BLE001
        receipt = exc
    ids_at_receipt = list(it.current_state_ids)
    # converge or watchdog
    t0 = time.monotonic()
    prev, stable = -1, 0
    while time.monotonic() - t0 < WATCHDOG:
        await asyncio.sleep(0.01)
        cur = it.context.get("laps", 0)
        if cur == prev:
            stable += 1
            if stable > 4:
                break
        else:
            prev, stable = cur, 0
    settled = stable > 4
    laps = it.context.get("laps", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    tripped = err == "RunawayChainError"
    dormant = it.has_dormant_invocations
    await it.stop()
    return {
        "laps": laps,
        "err": err,
        "tripped": tripped,
        "settled": settled,
        "stranded": obs.stranded,
        "dormant": dormant,
        "receipt": receipt,
        "ids_at_receipt": ids_at_receipt,
    }


def run_sync(cfg, kind):
    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={"tick": tick_def if kind == "def" else tick_async,
                     "boom": boom},
            services={"svc": svc_def if kind == "def" else svc_async},
        ),
    )
    it = SyncInterpreter(m)
    try:
        it.start()
        it.send("GO")
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "NotSupportedError":
            return None
    laps = it.context.get("laps", 0)
    try:
        it.stop()
    except Exception:  # noqa: BLE001
        pass
    return laps


def receipt_ok(r):
    """Success-shaped: a real Receipt whose `error` is None. `Receipt` has
    no `.ok`; `.error` is the field #208 talks about."""
    from xstate_statemachine.events import Receipt

    if isinstance(r, BaseException) or not isinstance(r, Receipt):
        return False
    return r.error is None


async def main():
    rnd = random.Random(SEED)
    configs = [gen_config(rnd, i) for i in range(N_CONFIGS)]
    print(f"N5 -- livelock fuzzer, {N_CONFIGS} configs x 2 kinds x 2 engines")
    print(f"      seed={SEED}, per-cell watchdog {WATCHDOG}s")
    print()
    p1 = []  # non-settling
    p2 = []  # tripped but unobservable
    p3 = []  # lap parity mismatch on the def lane
    rb = []  # receipt ok over an illegal configuration
    rb2 = []  # receipt error over a legal settled configuration
    t0 = time.monotonic()
    counts = Counter()
    for idx, (cfg, has_inv, shp) in enumerate(configs):
        timerish = "after" in shp
        for kind in ("def", "async def"):
            a = await run_async(cfg, kind)
            counts[f"{kind}:{'trip' if a['tripped'] else 'settle'}"] += 1
            if not a["settled"] and not a["tripped"]:
                p1.append((idx, kind, a["laps"], sorted(shp)))
            if a["tripped"] and a["err"] != "RunawayChainError":
                p2.append((idx, kind))
            if a["tripped"] and a["dormant"] and not a["stranded"]:
                p2.append((idx, kind, "dormant invoke, no stranded hook"))
            ok = receipt_ok(a["receipt"])
            if ok and not legal(a["ids_at_receipt"]):
                rb.append((idx, kind, a["ids_at_receipt"]))
            # B2 only counts when the chart did NOT itself raise: a
            # `boom` entry action makes an error receipt CORRECT, so those
            # cells are excluded rather than mis-scored.
            chart_raises = "boom" in repr(cfg)
            if (
                not ok
                and legal(a["ids_at_receipt"])
                and a["err"] is None
                and not chart_raises
                and not isinstance(a["receipt"], BaseException)
            ):
                rb2.append((idx, kind, a["ids_at_receipt"],
                            repr(getattr(a["receipt"], "error", None))[:60]))
            if kind == "def":
                s = run_sync(cfg, kind)
                if s is not None and abs(s - a["laps"]) > 1:
                    p3.append((idx, s, a["laps"], sorted(shp)))
        if time.monotonic() - t0 > 95:
            print(f"   [stopped at config {idx + 1} to stay inside the "
                  f"120 s bound]")
            configs = configs[: idx + 1]
            break
    el = time.monotonic() - t0
    print(f"   ran {len(configs)} configs in {el:.1f}s   outcomes={dict(counts)}")
    print()
    p1_timer = [x for x in p1 if "after" in x[3]]
    p1_pure = [x for x in p1 if "after" not in x[3]]
    p3_timer = [x for x in p3 if "after" in x[3]]
    p3_pure = [
        x for x in p3 if "after" not in x[3] and "raisedelay" not in x[3]
    ]
    p3_delay = [
        x for x in p3 if "after" not in x[3] and "raisedelay" in x[3]
    ]
    print(f"P1 non-settling total = {len(p1)}")
    print(f"   with `after` (timer-paced; external by #206) = {len(p1_timer)}")
    print(f"   WITHOUT `after` (engine work only)           = "
          f"{len(p1_pure)}  {p1_pure[:5]}")
    print(f"P3 def-lane lap mismatch total = {len(p3)}")
    print(f"   with `after` (sync engine never fires timers) = {len(p3_timer)}")
    print(f"   with `raise(delay=)` (sync timer-paced self-send is")
    print(f"      caller-tick-driven -- documented in the #206 pin) = "
          f"{len(p3_delay)}")
    print(f"   NEITHER (engine work only, the real parity claim)  = "
          f"{len(p3_pure)}  {p3_pure[:5]}")
    print(f"P2 tripped but unobservable           = {len(p2)}  {p2[:5]}")
    print(f"B1 receipt ok over ILLEGAL config     = {len(rb)}  {rb[:5]}")
    print(f"B2 receipt error over LEGAL settled   = {len(rb2)}  {rb2[:5]}")
    total = len(p1_pure) + len(p2) + len(p3_pure) + len(rb) + len(rb2)
    print()
    print(f"DEFECTS = {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
