"""Ad-hoc: recompute BENCH-1 (order submit->ack p95) with actionErrorPolicy=
"rollback" armed on the OMS machine, i.e. the CV-mandated config
(17-reeval-0.8.0-verdict.md s.4). Not part of the checked-in bench_h suite;
written only to answer the '>=3.0x headroom with rollback armed' question in
this gate's task brief. Reuses common.py's OMS_CONFIG/logic verbatim, only
adding the policy flag.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter, MachineLogic, create_machine


def oms_machine_rollback():
    cfg = copy.deepcopy(common.OMS_CONFIG)
    cfg["actionErrorPolicy"] = "rollback"
    return create_machine(
        json.loads(json.dumps(cfg)), logic=MachineLogic(**common.OMS_LOGIC_KW)
    )


async def budget_submit_ack_rollback(background: int, samples: int) -> Dict[str, Any]:
    bg = [Interpreter(oms_machine_rollback()) for _ in range(background)]
    await asyncio.gather(*(i.start() for i in bg))

    stop = asyncio.Event()
    cycle = common.oms_event_cycle(10)

    async def churn(i: Any) -> None:
        while not stop.is_set():
            for e in cycle:
                if stop.is_set():
                    return
                await i.send(e)
            await asyncio.sleep(0.005)

    tasks = [asyncio.create_task(churn(i)) for i in bg]
    await asyncio.sleep(0.2)

    full_ms: List[float] = []
    for _ in range(samples):
        interp = await Interpreter(oms_machine_rollback()).start()
        t0 = time.perf_counter()
        await interp.send({"type": "SUBMIT", "qty": 1000.0})
        while "order.submitted" not in interp.current_state_ids:
            await asyncio.sleep(0)
        await interp.send({"type": "ACK", "order_id": "x"})
        while "order.open" not in interp.current_state_ids:
            await asyncio.sleep(0)
        t2 = time.perf_counter()
        full_ms.append((t2 - t0) * 1000)
        await interp.stop()

    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.gather(*(i.stop() for i in bg))

    p95 = common.pct(full_ms, 95)
    return {
        "background_order_machines": background,
        "samples": samples,
        "submit_to_open_total_ms": common.summarize(full_ms),
        "budget_ms": 300,
        "p95_total_ms": p95,
        "within_budget": p95 < 300,
        "budget_headroom_x": 300 / max(p95, 1e-9),
    }


async def main() -> None:
    out = await budget_submit_ack_rollback(500, 200)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
