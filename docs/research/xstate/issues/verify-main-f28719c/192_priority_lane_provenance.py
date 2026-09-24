# -*- coding: utf-8 -*-
"""Verify #192 on f28719c: priority lane charges AND sheds by provenance,
not FIFO position. Matrix: {def, async def} x {issuer external, issuer
action} x {chain idle, chain tripped}. Standalone. Watchdog-protected.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

WATCHDOG_S = 25.0
MAX_ITER = 15


def build(kind: str):
    def sync_svc(i, c, e):
        return 1

    async def async_svc(i, c, e):
        return 1

    svc = async_svc if kind == "async def" else sync_svc

    def self_send_action(i, c, e, a):
        # action-issued priority self-send: charged (#192)
        asyncio.ensure_future(i.send("SELF", priority=True))

    cfg = {
        "id": "m192",
        "initial": "a",
        "context": {"laps": 0},
        "maxIterations": MAX_ITER,
        "states": {
            "a": {
                "invoke": {"id": "s", "src": "svc", "onDone": {"actions": ["bump"]}},
                "on": {
                    "SELF": {"actions": ["bump", "self_send"]},
                    "EXT": {"actions": ["mark_ext"]},
                },
            }
        },
    }

    def bump(i, c, e, a):
        c["laps"] = c.get("laps", 0) + 1

    def mark_ext(i, c, e, a):
        c["ext_applied"] = c.get("ext_applied", 0) + 1

    m = create_machine(
        cfg,
        logic=MachineLogic(
            services={"svc": svc},
            actions={"bump": bump, "self_send": self_send_action, "mark_ext": mark_ext},
        ),
    )
    return m


async def cell_charged_when_self_issued(kind: str) -> dict:
    """An action-issued priority self-send IS charged: chain trips."""
    drops = {"chain_budget": 0}

    class Drops:
        def on_event_dropped(self, interp, event, reason):
            drops[reason] = drops.get(reason, 0) + 1

        def on_service_start(self, *a, **k):
            pass

        def on_service_done(self, *a, **k):
            pass

        def on_service_error(self, *a, **k):
            pass

        def on_interpreter_start(self, *a, **k):
            pass

        def on_transition(self, *a, **k):
            pass

    from xstate_statemachine import PluginBase

    class DropsPlugin(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            drops[reason] = drops.get(reason, 0) + 1

    m = build(kind)
    it = Interpreter(m)
    it.use(DropsPlugin())
    await it.start()
    await it.send("SELF", priority=True, wait=True)
    await asyncio.sleep(0.3)
    await it.stop()
    return {"kind": kind, "chain_budget_drops": drops.get("chain_budget", 0), "tripped": drops.get("chain_budget", 0) > 0}


async def cell_external_survives_trip(kind: str) -> dict:
    """An external priority send at the head when an unrelated self-generated
    chain trips is delivered, not shed."""
    from xstate_statemachine import PluginBase

    drops = {}

    class DropsPlugin(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            drops[reason] = drops.get(reason, 0) + 1
            drops.setdefault("types", []).append((event.type, reason))

    cfg = {
        "id": "m192b",
        "initial": "a",
        "context": {},
        "maxIterations": 10,
        "states": {
            "a": {
                "invoke": {"id": "s", "src": "loop_svc", "onDone": {"actions": ["reinvoke"]}},
                "on": {"EXT": {"actions": ["mark_ext"]}},
            }
        },
    }

    calls = {"n": 0}

    async def loop_svc(i, c, e):
        return 1

    def reinvoke(i, c, e, a):
        # keep re-triggering self-generated completions to trip the budget
        asyncio.ensure_future(i.send("REARM"))

    ext_applied = {"n": 0}

    def mark_ext(i, c, e, a):
        ext_applied["n"] += 1

    m = create_machine(
        cfg,
        logic=MachineLogic(
            services={"loop_svc": loop_svc},
            actions={"reinvoke": reinvoke, "mark_ext": mark_ext},
        ),
    )
    it = Interpreter(m)
    it.use(DropsPlugin())
    await it.start()
    # Fire many external priority sends while the self-generated chain runs
    for _ in range(200):
        await it.send("EXT", priority=True)
    await asyncio.sleep(0.5)
    await it.stop()
    ext_drops = sum(1 for t, r in drops.get("types", []) if t == "EXT" and r == "chain_budget")
    return {
        "kind": kind,
        "ext_applied": ext_applied["n"],
        "ext_dropped_as_chain_budget": ext_drops,
        "ok": ext_drops == 0,
    }


async def main() -> int:
    results = []
    for kind in ("def", "async def"):
        r1 = await asyncio.wait_for(cell_charged_when_self_issued(kind), WATCHDOG_S)
        results.append(("issuer=action,chain=idle->tripped", r1))
        r2 = await asyncio.wait_for(cell_external_survives_trip(kind), WATCHDOG_S)
        results.append(("issuer=external,chain=tripped", r2))
    for label, r in results:
        print(label, r)
    ok = all(
        (r.get("tripped") if "tripped" in r else r.get("ok"))
        for _, r in results
    )
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
