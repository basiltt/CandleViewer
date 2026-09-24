"""N2 - #105: the self-send gate must be per-task, not "the loop is busy".

#105 changed the `maxIterations` charge from "an event arrived while a step
was in flight" to "the event was issued from one of THIS interpreter's
actions", tracked per task. Attack it from the three shapes that can produce
a send concurrent with an in-flight step:

  A  external `asyncio.create_task` producer sending during a long action
  B  an OS thread using `send_threadsafe` during a long action
  C  an invoked child actor sending to the parent during a long action

None of these are self-sends. If any of them is charged to the chain budget,
a modest `maxIterations` (here 8) plus more than 8 concurrent external
producers trips `RunawayChainError` -- which is the defect shape.

Control D: a genuine action-issued self-send chain MUST still be charged
(otherwise #105 traded a false positive for a missing guard).
"""

from __future__ import annotations

import asyncio
import threading

from common import Accountant, emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

MAXIT = 8
N_PRODUCERS = 24

BASE = {
    "id": "gate",
    "initial": "idle",
    "context": {"n": 0, "slow": 0},
    "maxIterations": MAXIT,
    "states": {
        "idle": {
            "on": {
                "SLOW": {"actions": ["slow_action"]},
                "PING": {"actions": ["bump"]},
            }
        }
    },
}

GATE: dict = {}


async def slow_action(i, ctx, e, a):  # noqa: ANN001
    ctx["slow"] += 1
    GATE["in_action"].set()
    await GATE["release"].wait()


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def mk(cfg=None):
    return create_machine(
        cfg or BASE,
        logic=MachineLogic(actions={"slow_action": slow_action, "bump": bump}),
    )


def _chain_drops(acc: Accountant):
    return [d for d in acc.dropped if d[1] == "chain_budget"]


async def scenario_a() -> dict:
    GATE["in_action"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    acc = Accountant()
    interp = Interpreter(mk())
    interp.use(acc)
    await interp.start()

    async def _slow():
        await interp.send("SLOW")

    t = asyncio.create_task(_slow())
    await asyncio.wait_for(GATE["in_action"].wait(), 5)

    async def producer(k):
        await interp.send("PING")

    ps = [asyncio.create_task(producer(k)) for k in range(N_PRODUCERS)]
    await asyncio.sleep(0.05)
    GATE["release"].set()
    await asyncio.gather(t, *ps, return_exceptions=True)
    await asyncio.sleep(0.2)
    out = {
        "producers": N_PRODUCERS,
        "context_n": interp.context["n"],
        "chain_budget_drops": len(_chain_drops(acc)),
        "last_transition_ok": interp.last_transition_ok,
        "last_error": repr(interp.last_error),
    }
    await interp.stop()
    out["pass"] = out["chain_budget_drops"] == 0 and out["context_n"] == N_PRODUCERS
    return out


async def scenario_b() -> dict:
    GATE["in_action"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    acc = Accountant()
    interp = Interpreter(mk())
    interp.use(acc)
    await interp.start()
    loop = asyncio.get_running_loop()

    async def _slow():
        await interp.send("SLOW")

    t = asyncio.create_task(_slow())
    await asyncio.wait_for(GATE["in_action"].wait(), 5)

    def worker():
        interp.send_threadsafe("PING")

    threads = [threading.Thread(target=worker) for _ in range(N_PRODUCERS)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(5)
    await asyncio.sleep(0.05)
    GATE["release"].set()
    await asyncio.gather(t, return_exceptions=True)
    await asyncio.sleep(0.3)
    out = {
        "producers": N_PRODUCERS,
        "context_n": interp.context["n"],
        "chain_budget_drops": len(_chain_drops(acc)),
        "last_error": repr(interp.last_error),
    }
    await interp.stop()
    out["pass"] = out["chain_budget_drops"] == 0 and out["context_n"] == N_PRODUCERS
    return out


CHILD = {
    "id": "child",
    "initial": "go",
    "states": {"go": {"type": "final"}},
}

PARENT = {
    "id": "parent",
    "initial": "idle",
    "context": {"n": 0, "slow": 0},
    "maxIterations": MAXIT,
    "states": {
        "idle": {
            "on": {
                "SLOW": {"actions": ["slow_action"]},
                "PING": {"actions": ["bump"]},
                "SPAWN": {"actions": [{"type": "spawn_kid"}]},
            }
        }
    },
}


async def scenario_c() -> dict:
    """Child-actor -> parent sends during a parent action."""
    GATE["in_action"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    acc = Accountant()
    interp = Interpreter(mk())
    interp.use(acc)
    await interp.start()

    async def _slow():
        await interp.send("SLOW")

    t = asyncio.create_task(_slow())
    await asyncio.wait_for(GATE["in_action"].wait(), 5)

    # Stand in for N child actors: N independent tasks, each its own task
    # identity, each sending to the parent (exactly the observable shape a
    # spawned actor's forward/sendTo has).
    async def kid(k):
        for _ in range(3):
            await interp.send("PING")
            await asyncio.sleep(0)

    kids = [asyncio.create_task(kid(k)) for k in range(N_PRODUCERS)]
    await asyncio.sleep(0.05)
    GATE["release"].set()
    await asyncio.gather(t, *kids, return_exceptions=True)
    await asyncio.sleep(0.3)
    out = {
        "producers": N_PRODUCERS * 3,
        "context_n": interp.context["n"],
        "chain_budget_drops": len(_chain_drops(acc)),
        "last_error": repr(interp.last_error),
    }
    await interp.stop()
    out["pass"] = (
        out["chain_budget_drops"] == 0 and out["context_n"] == N_PRODUCERS * 3
    )
    return out


SELF = {
    "id": "selfsend",
    "initial": "idle",
    "context": {"n": 0},
    "maxIterations": MAXIT,
    "states": {"idle": {"on": {"GO": {"actions": ["reraise"]}}}},
}


async def scenario_d() -> dict:
    """CONTROL: action-issued self-send chain must STILL be budgeted."""
    acc = Accountant()
    hits = {"n": 0}

    async def reraise(i, ctx, e, a):  # noqa: ANN001
        hits["n"] += 1
        ctx["n"] += 1
        await i.send("GO")

    interp = Interpreter(
        create_machine(SELF, logic=MachineLogic(actions={"reraise": reraise}))
    )
    interp.use(acc)
    await interp.start()
    try:
        await asyncio.wait_for(interp.send("GO", wait=True), 10)
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.2)
    out = {
        "self_send_action_runs": hits["n"],
        "maxIterations": MAXIT,
        "chain_budget_drops": len(_chain_drops(acc)),
        "last_transition_ok": interp.last_transition_ok,
        "last_error": repr(interp.last_error),
    }
    await interp.stop()
    # Budget must bite: bounded runs AND an attributable trip.
    out["pass"] = hits["n"] <= MAXIT + 2 and (
        out["chain_budget_drops"] > 0 or "Runaway" in out["last_error"]
    )
    return out


async def main() -> int:
    res = {
        "a_create_task_producers": await scenario_a(),
        "b_send_threadsafe_threads": await scenario_b(),
        "c_child_actor_tasks": await scenario_c(),
        "d_control_real_self_send": await scenario_d(),
    }
    ok = all(v["pass"] for v in res.values())
    emit("n2_per_task_gate", {**res, "result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
