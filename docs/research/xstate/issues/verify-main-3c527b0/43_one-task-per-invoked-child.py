"""Verify #43 (fixed by PR #83, commit 3c527b0): one asyncio task per
invoked child; push-based completion; no idle polling; onDone latency
sub-2ms; children stopped on state exit.

Acceptance criteria exercised (from the GH issue):
  1. Invoking 50 children adds <= 1 task/child over a 0-child baseline.
  2. With 20 idle children, no periodic timer callbacks fire over 200ms.
  3. onDone latency < 2ms median over 50 reps.
  4. Existing onError semantics unchanged (child fails -> error.platform.<id>).
  5. Child completing during start still fires onDone exactly once.
  6. Actor cancelled cleanly on parent state exit; no leaked task/child.

Exit 0 if every criterion passes, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import sys
import time
from typing import Any, Dict, List

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    ErrorEvent,
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine import interpreter as interp_mod  # noqa: E402

RESULTS: List[tuple] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


IDLE_CHILD: Dict[str, Any] = {
    "id": "kid",
    "initial": "waiting",
    "states": {"waiting": {"on": {"FINISH": "done"}}, "done": {"type": "final"}},
}


def parent_cfg(n: int) -> Dict[str, Any]:
    return {
        "id": "book",
        "initial": "running",
        "states": {
            "running": {
                "invoke": [{"id": f"leg{i}", "src": "leg"} for i in range(n)]
            }
        },
    }


async def crit_no_poll_attr() -> None:
    ok = not hasattr(interp_mod, "_ACTOR_POLL_INTERVAL")
    check(
        "no_more_ACTOR_POLL_INTERVAL",
        ok,
        "attribute removed from interpreter module" if ok else "still present",
    )


async def crit_one_task_per_child() -> None:
    machine0 = create_machine(
        parent_cfg(0), logic=MachineLogic(services={"leg": create_machine(IDLE_CHILD)})
    )
    base_i = await Interpreter(machine0).start()
    await asyncio.sleep(0.02)
    baseline = len(asyncio.all_tasks())
    await base_i.stop()
    await asyncio.sleep(0.02)

    machine50 = create_machine(
        parent_cfg(50), logic=MachineLogic(services={"leg": create_machine(IDLE_CHILD)})
    )
    p = await Interpreter(machine50).start()
    await asyncio.sleep(0.05)
    with_children = len(asyncio.all_tasks())
    delta = with_children - baseline
    await p.stop()
    check(
        "50_children_adds_le_51_tasks",
        delta <= 51,
        f"delta={delta} (budget children+1=51)",
    )


async def crit_no_idle_polling() -> None:
    machine = create_machine(
        parent_cfg(20), logic=MachineLogic(services={"leg": create_machine(IDLE_CHILD)})
    )
    p = await Interpreter(machine).start()
    await asyncio.sleep(0.05)
    loop = asyncio.get_running_loop()
    scheduled = []
    orig = loop.call_later

    def spy(delay, cb, *a, **kw):
        scheduled.append(delay)
        return orig(delay, cb, *a, **kw)

    loop.call_later = spy  # type: ignore[method-assign]
    try:
        await asyncio.sleep(0.2)
    finally:
        loop.call_later = orig  # type: ignore[method-assign]
    await p.stop()
    stray = [d for d in scheduled if d != 0.2]
    check(
        "no_timer_callbacks_while_idle",
        stray == [],
        f"stray call_later delays={stray}",
    )


async def crit_ondone_latency() -> None:
    cfg = {
        "id": "p",
        "type": "parallel",
        "context": {"done": 0},
        "states": {
            "r0": {
                "initial": "run",
                "states": {
                    "run": {
                        "invoke": {
                            "src": "kid",
                            "id": "kid0",
                            "onDone": {"target": "ok", "actions": "bump"},
                        }
                    },
                    "ok": {"type": "final"},
                },
            }
        },
    }

    async def one() -> float:
        machine = create_machine(
            cfg,
            logic=MachineLogic(
                actions={"bump": lambda i, c, e, a: c.__setitem__("done", c["done"] + 1)},
                services={"kid": create_machine(IDLE_CHILD)},
            ),
        )
        p = await Interpreter(machine).start()
        await asyncio.sleep(0.01)
        kid = next(iter(p._actors.values()))
        t0 = time.perf_counter()
        await kid.send("FINISH")
        for _ in range(2000):
            if p.context["done"] == 1:
                break
            await asyncio.sleep(0)
        dt = (time.perf_counter() - t0) * 1000
        await p.stop()
        return dt

    samples = [await one() for _ in range(50)]
    med = statistics.median(samples)
    check("ondone_latency_median_lt_2ms", med < 2.0, f"median={med:.3f}ms")


async def crit_onerror_unchanged() -> None:
    seen: List[Any] = []

    async def failing(i, c, e):
        raise ValueError("boom")

    cfg = {
        "id": "svc",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "src": "failing",
                    "id": "failing",
                    "onError": {"target": "b", "actions": "note"},
                }
            },
            "b": {},
        },
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"note": lambda i, c, e, a: seen.append(e)},
                services={"failing": failing},
            ),
        )
    ).start()
    await asyncio.sleep(0.05)
    await i.stop()
    ok = len(seen) == 1 and isinstance(seen[0], ErrorEvent)
    check(
        "child_error_still_fires_on_error",
        ok,
        f"seen={seen}",
    )


async def crit_completes_during_start_fires_once() -> None:
    ALREADY_DONE_CHILD = {
        "id": "kid",
        "initial": "done",
        "states": {"done": {"type": "final"}},
    }
    calls: List[int] = []
    cfg = {
        "id": "p",
        "initial": "a",
        "context": {"done": 0},
        "states": {
            "a": {
                "invoke": {
                    "src": "kid",
                    "id": "kid",
                    "onDone": {"target": "b", "actions": "bump"},
                }
            },
            "b": {},
        },
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"bump": lambda i, c, e, a: calls.append(1)},
                services={"kid": create_machine(ALREADY_DONE_CHILD)},
            ),
        )
    ).start()
    await asyncio.sleep(0.05)
    state = set(i.current_state_ids)
    await i.stop()
    check(
        "child_completing_during_start_fires_once",
        state == {"p.b"} and len(calls) == 1,
        f"state={state} calls={len(calls)}",
    )


async def crit_cancel_on_state_exit() -> None:
    cfg = {
        "id": "p",
        "initial": "a",
        "context": {"done": 0},
        "states": {
            "a": {
                "invoke": {"src": "kid", "id": "kid", "onDone": {"actions": "bump"}},
                "on": {"LEAVE": "b"},
            },
            "b": {},
        },
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"bump": lambda i, c, e, a: c.__setitem__("done", c["done"] + 1)},
                services={"leg": create_machine(IDLE_CHILD), "kid": create_machine(IDLE_CHILD)},
            ),
        )
    ).start()
    await i.send("LEAVE")
    await asyncio.sleep(0.05)
    live = [a for a in i._actors.values() if a.status == "running"]
    state = set(i.current_state_ids)
    done = i.context["done"]
    await i.stop()
    check(
        "actor_cancelled_on_parent_state_exit",
        state == {"p.b"} and done == 0 and len(live) == 0,
        f"state={state} done={done} live={len(live)}",
    )


async def main() -> int:
    await crit_no_poll_attr()
    await crit_one_task_per_child()
    await crit_no_idle_polling()
    await crit_ondone_latency()
    await crit_onerror_unchanged()
    await crit_completes_during_start_fires_once()
    await crit_cancel_on_state_exit()

    print("\n=== SUMMARY ===")
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}: {name} -- {detail}")
    overall = all(ok for _, ok, _ in RESULTS)
    print("\nOVERALL:", "ALL CRITERIA PASS" if overall else "SOME CRITERIA FAILED")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
