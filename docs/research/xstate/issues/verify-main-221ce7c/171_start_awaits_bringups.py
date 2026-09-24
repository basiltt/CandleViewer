# -*- coding: utf-8 -*-
"""Verify #171 on main @ 221ce7c: await Interpreter.start() returns with the
initial configuration's invoked children (MachineNode actors) registered,
matching SyncInterpreter.start(). A plain-def service still runs off the
loop (#149) and is NOT awaited by start(), only its bring-up bookkeeping is
irrelevant for plain callables (they have no actor registration step).

Criteria:
 1. A MachineNode child invoked from the INITIAL entry set is present in
    `_actors` immediately after `await start()` returns (async), matching
    sync's actor presence right after `start()`.
 2. `sendTo` to that child immediately after start() resolves (no
    'unresolved_target' drop), on the async engine.
 3. A plain-def service invoked from the initial entry set: start() returns
    without blocking on its result (still #149 -- loop stays live / start()
    is fast), but the machine still reaches the done state shortly after,
    i.e. ordering/semantics unaffected by the #171 fix.
"""
import asyncio
import sys
import time

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

CHILD_CFG = {"id": "kid", "initial": "s", "states": {"s": {}}}

PARALLEL_CFG = {
    "id": "par",
    "type": "parallel",
    "states": {
        "region": {
            "initial": "a",
            "states": {"a": {"invoke": {"id": "par:kid", "src": "kid_machine"}}},
        },
        "other": {"initial": "x", "states": {"x": {}}},
    },
}


def kid_bridge_logic():
    child = create_machine(CHILD_CFG)
    return MachineLogic(services={"kid_machine": child})


PLAIN_SVC_CFG = {
    "id": "plain",
    "initial": "running",
    "states": {
        "running": {"invoke": {"id": "kid", "src": "plain_svc", "onDone": {"target": "done"}}},
        "done": {"type": "final"},
    },
}


def plain_svc(interpreter, context, event):
    return {"ok": True}


def main():
    ok = True

    # --- Criterion 1 & 2: async actor bring-up ---
    async def check_actor_bringup():
        m = create_machine(PARALLEL_CFG, logic=kid_bridge_logic())
        i = Interpreter(m)
        await i.start()
        actors_present = any("kid" in k for k in i._actors)
        # sendTo immediately after start
        dropped = []

        class Sink:
            def on_event_dropped(self, interpreter, event, reason):
                dropped.append(reason)

            def __getattr__(self, item):
                def _noop(*a, **k):
                    return None
                return _noop

        i._plugins.append(Sink())
        actor_key = next((k for k in i._actors if "kid" in k), None)
        if actor_key is not None:
            i.send("POKE", target=actor_key)
        else:
            i.send("POKE", target="kid")
        await asyncio.sleep(0.02)
        await i.stop()
        return actors_present, dropped

    actors_present, dropped = asyncio.run(check_actor_bringup())
    print(f"async actors present right after start(): {actors_present}")
    print(f"async drops after immediate sendTo: {dropped}")
    c1 = actors_present is True
    print(f"[1] child actor registered by start() returns: {c1}")
    ok &= c1
    c2 = "unresolved_target" not in dropped
    print(f"[2] sendTo does not drop unresolved_target: {c2}")
    ok &= c2

    # sync control: actor also present right after start()
    m_sync = create_machine(PARALLEL_CFG, logic=kid_bridge_logic())
    s = SyncInterpreter(m_sync)
    s.start()
    sync_actors_present = any("kid" in k for k in s._actors)
    print(f"sync actors present right after start(): {sync_actors_present}")
    ok &= sync_actors_present

    # --- Criterion 3: plain-def service still off-loop (#149 preserved) ---
    async def check_plain_service():
        m = create_machine(PLAIN_SVC_CFG, logic=MachineLogic(services={"plain_svc": plain_svc}))
        i = Interpreter(m)
        t0 = time.monotonic()
        await i.start()
        t_start = (time.monotonic() - t0) * 1000
        deadline = time.monotonic() + 1.0
        while "plain.done" not in i.current_state_ids and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
        reached = "plain.done" in i.current_state_ids
        await i.stop()
        return t_start, reached

    t_start_ms, reached_done = asyncio.run(check_plain_service())
    print(f"start() took {t_start_ms:.2f} ms for plain-service machine; reached done: {reached_done}")
    c3 = t_start_ms < 200 and reached_done
    print(f"[3] start() stays fast (#149 preserved) and done is reached: {c3}")
    ok &= c3

    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
