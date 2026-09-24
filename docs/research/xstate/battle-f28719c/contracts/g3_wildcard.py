# -*- coding: utf-8 -*-
"""The A3 scaffolding `"*"` handler is NOT 'dead but harmless' (E50-T09):
a bare `"*"` descriptor makes EVERY event name known, so `strict` is a no-op
for the whole machine."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter, UnknownEventError
from xstate_statemachine.clock import SimulatedClock

H._REG.clear()

WILDCARD_OWNERS = {"B12": "buffering", "B13": "subscribing"}


@scenario("STAR-1", "strict", "which contracts carry the A3 wildcard?")
def which():
    out = {}
    for b in ("B11", "B12", "B13", "B14", "B15"):
        cfg = H.load(b)
        hits = []

        def walk(node, path):
            if "*" in (node.get("on") or {}):
                hits.append(path)
            for k, v in (node.get("states") or {}).items():
                walk(v, path + "." + k)
        walk(cfg, cfg["id"])
        out[b] = {"wildcard_states": hits, "known_events": sorted(
            H.build(cfg, H.Stub(cfg)).known_events)[:12]}
    return {"ok": True, "per_machine": out}


@scenario("STAR-2", "strict", "wildcard makes is_known_event() true for any garbage")
def known():
    out = {}
    for b in ("B11", "B12", "B13", "B14", "B15"):
        cfg = H.load(b)
        m = H.build(cfg, H.Stub(cfg))
        out[b] = {
            "has_star": "*" in m.known_events,
            "TYPO_known": m.is_known_event("TYPO_XYZ", user_sent=True),
            "onUnhandled": cfg["onUnhandled"],
        }
    # strict is meaningful only where there is no "*"
    broken = [b for b, v in out.items() if v["has_star"] and v["TYPO_known"]]
    return {"ok": not broken, "per_machine": out, "strict_defeated_in": broken}


@scenario("STAR-3", "strict", "removing the A3 wildcard restores strict on B13")
async def restore():
    cfg = H.load("B13")
    del cfg["states"]["subscribing"]["on"]["*"]
    st = H.Stub(cfg, guard_vals={"is_private": False,
                                 "connection_budget_exhausted": False})
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    await it.start()
    await it.send("CONNECT", wait=True)
    await quiesce(it)
    res = {}
    for name in ("NOT_A_REAL_EVENT", "after.party", "done.invoke.bogus"):
        try:
            await it.send(name, wait=True)
            res[name] = "ACCEPTED (strict still defeated)"
        except UnknownEventError as e:
            res[name] = "UnknownEventError (strict works)"
        except Exception as e:
            res[name] = "%s" % type(e).__name__
    await it.stop()
    return {"ok": all("UnknownEventError" in v for v in res.values()),
            "results": res,
            "finding": ("with the dead A3 `*` handler deleted, strict=true "
                        "behaves as the catalogue says it should")}


if __name__ == "__main__":
    sys.exit(run_all("wildcard"))
