# -*- coding: utf-8 -*-
"""battle-6db65d8 soak: chain_owed under concurrent never-completing coroutine
services + stop(); external priority sends at load during self-generated
chains (both service kinds); children_timeout with many slow children.
"""
from __future__ import annotations

import asyncio
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine


# --- Attack A: 100 concurrent never-completing coroutine services + stop() ---
A_CONFIG = {
    "id": "owed",
    "initial": "running",
    "context": {},
    "states": {
        "running": {
            "invoke": {"id": "s", "src": "never_done", "onDone": {"actions": []}},
            "on": {"POKE": {"actions": []}},
        },
    },
}


async def never_done(interp, ctx, event):  # noqa: ANN001
    await asyncio.sleep(9999)


async def attack_a_chain_owed_leak(n: int = 100) -> dict:
    t0 = time.perf_counter()
    interps = []
    for _ in range(n):
        logic = MachineLogic(actions={}, services={"never_done": never_done})
        machine = create_machine(dict(A_CONFIG), logic=logic)
        interp = Interpreter(machine)
        await interp.start()
        interps.append(interp)

    # poke each once (internal self-send-ish external event)
    for interp in interps:
        interp.send({"type": "POKE"})
    await asyncio.sleep(0.2)

    stop_results = []
    async def stop_one(interp):
        try:
            await asyncio.wait_for(interp.stop(drain=False, timeout=2.0), timeout=3.0)
            return True
        except asyncio.TimeoutError:
            return False

    stop_results = await asyncio.gather(*(stop_one(i) for i in interps))
    dt = time.perf_counter() - t0
    hangs = stop_results.count(False)
    return {"n": n, "hangs": hangs, "dt_s": round(dt, 3)}


# --- Attack B: external priority sends at 10k/s during self-gen chains ---
B_CONFIG = {
    "id": "prio",
    "initial": "a",
    "context": {"chain_bumps": 0, "ext_seen": 0},
    "states": {
        "a": {
            "always": [{"target": "b"}],
        },
        "b": {
            "entry": ["bump_chain"],
            "on": {
                "EXT": {"actions": ["mark_ext"]},
                "STOP_CHAIN": {"target": "done"},
            },
            "always": [
                {"target": "a", "cond": "still_going"},
            ],
        },
        "done": {"type": "final"},
    },
}


def bump_chain(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["chain_bumps"] = ctx.get("chain_bumps", 0) + 1


def mark_ext(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["ext_seen"] = ctx.get("ext_seen", 0) + 1


def still_going(ctx, event):  # noqa: ANN001
    return ctx.get("chain_bumps", 0) < 2000


async def attack_b_priority_no_drop(kind: str, n_ext: int = 3000) -> dict:
    logic = MachineLogic(
        actions={"bump_chain": bump_chain, "mark_ext": mark_ext},
        guards={"still_going": still_going},
        services={},
    )
    machine = create_machine(dict(B_CONFIG), logic=logic)
    dropped = []
    interp = Interpreter(machine, max_queue_size=200000)
    interp.on_event_dropped = lambda **kw: dropped.append(kw)  # type: ignore[assignment]
    await interp.start()

    t0 = time.perf_counter()
    receipts = []
    for i in range(n_ext):
        r = interp.send({"type": "EXT", "payload": {"i": i}}, priority=True)
        receipts.append(r)
    await asyncio.sleep(2.0)
    dt = time.perf_counter() - t0
    ext_seen = interp.context.get("ext_seen", 0)
    await interp.stop(drain=False, timeout=1.0)
    return {
        "kind": kind,
        "n_ext": n_ext,
        "ext_seen": ext_seen,
        "dropped": len(dropped),
        "dt_s": round(dt, 3),
        "rate_eps": round(n_ext / dt, 1) if dt else None,
    }


# --- Attack C: children_timeout with 50 slow children ---
def _child_cfg(delay: float) -> dict:
    return {
        "id": "child",
        "initial": "boot",
        "context": {},
        "states": {"boot": {"entry": ["slow_entry"], "on": {"PING": {"actions": []}}}},
    }


async def attack_c_children_timeout(n_children: int = 50) -> dict:
    async def slow_entry(interp, ctx, event, action_def):  # noqa: ANN001
        await asyncio.sleep(0.3)

    root_children = {}
    for i in range(n_children):
        root_children[f"c{i}"] = {"src": f"child_src_{i}"}

    root_cfg = {
        "id": "root",
        "initial": "run",
        "context": {},
        "states": {
            "run": {
                "invoke": [
                    {"id": f"c{i}", "src": f"child_src_{i}"} for i in range(n_children)
                ],
            },
        },
    }
    services = {}
    for i in range(n_children):
        child_machine_cfg = _child_cfg(0.3)
        child_logic = MachineLogic(actions={"slow_entry": slow_entry}, services={})
        services[f"child_src_{i}"] = create_machine(child_machine_cfg, logic=child_logic)

    logic = MachineLogic(actions={}, services=services)
    machine = create_machine(root_cfg, logic=logic)
    interp = Interpreter(machine)
    t0 = time.perf_counter()
    await interp.start(children_timeout=0.5)
    dt = time.perf_counter() - t0
    status = interp.status
    n_registered = len(getattr(interp, "children", {}) or {})
    await interp.stop(drain=False, timeout=2.0)
    return {
        "n_children": n_children,
        "start_dt_s": round(dt, 3),
        "status_after_start": str(status),
        "n_registered_children": n_registered,
        "bounded": dt < 3.0,
    }


async def main():
    print("=== Attack A: chain_owed leak under 100 never-completing coroutine services + stop() ===")
    ra = await attack_a_chain_owed_leak(100)
    print(ra)

    print("\n=== Attack B: external priority sends during self-generated chain (no drop) ===")
    rb1 = await attack_b_priority_no_drop("sync-chain-only")
    print(rb1)

    print("\n=== Attack C: children_timeout with 50 slow invoked children ===")
    rc = await attack_c_children_timeout(50)
    print(rc)

    print("\nSUMMARY:", {
        "A_hangs": ra["hangs"],
        "B_dropped": rb1["dropped"],
        "B_ext_seen_vs_sent": (rb1["ext_seen"], rb1["n_ext"]),
        "C_bounded": rc["bounded"],
    })


if __name__ == "__main__":
    asyncio.run(main())
