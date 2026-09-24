# -----------------------------------------------------------------------------
# bench_j_policies.py -- cost of 0.8.0 opt-in policies on bench_a's workload
# -----------------------------------------------------------------------------
"""Re-run bench_a_throughput's `burst_50000` shape with the new 0.8.0
per-machine policies turned on, to see whether opting into them costs
throughput versus the 0.7.x-compatible defaults measured in bench_a.

Variants:
  * baseline           : actionErrorPolicy unset (default "continue"),
                         onUnhandled unset (default "ignore") -- same as
                         bench_a's burst_50000.
  * rollback           : actionErrorPolicy="rollback" (no actions actually
                         raise in this workload, so this measures the
                         overhead of the rollback machinery being *armed*,
                         not of rollback actually firing).
  * defer              : onUnhandled="defer" (all events in the OMS cycle
                         are handled, so this measures the overhead of the
                         defer bookkeeping being *armed*, not of anything
                         actually being deferred).
  * rollback_and_defer : both policies set together.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

import common
from xstate_statemachine import Interpreter, MachineLogic, create_machine

WARMUP = 2_000
N = 50_000


def _oms_machine_with_policies(**policy_kwargs: Any):
    """Build the OMS machine with extra top-level policy keys merged in."""
    cfg = json.loads(json.dumps(common.OMS_CONFIG))
    cfg.update(policy_kwargs)
    return create_machine(cfg, logic=MachineLogic(**common.OMS_LOGIC_KW))


async def _drain(interp: Any, target: int, timeout: float = 120.0) -> None:
    deadline = time.perf_counter() + timeout
    while interp.context["events"] < target:
        if time.perf_counter() > deadline:
            raise TimeoutError(f"drain timeout at {interp.context['events']}/{target}")
        await asyncio.sleep(0)


async def _bench_burst(machine_factory, n: int) -> Dict[str, Any]:
    interp = await Interpreter(machine_factory()).start()
    events = common.oms_event_cycle(n)
    base = interp.context["events"]

    t0 = time.perf_counter()
    for e in events:
        await interp.send(e)
    await _drain(interp, base + n)
    t1 = time.perf_counter()

    await interp.stop()
    return {
        "events": n,
        "total_s": t1 - t0,
        "events_per_sec": n / (t1 - t0),
        "us_per_event": (t1 - t0) / n * 1e6,
    }


async def main() -> None:
    common.report("machine_specs", common.machine_specs())

    variants = {
        "baseline": {},
        "rollback": {"actionErrorPolicy": "rollback"},
        "defer": {"onUnhandled": "defer"},
        "rollback_and_defer": {
            "actionErrorPolicy": "rollback",
            "onUnhandled": "defer",
        },
    }

    # warm up
    await _bench_burst(lambda: _oms_machine_with_policies(), WARMUP)

    results: Dict[str, Any] = {}
    for name, policy_kwargs in variants.items():
        results[name] = await _bench_burst(
            lambda pk=policy_kwargs: _oms_machine_with_policies(**pk), N
        )

    baseline_eps = results["baseline"]["events_per_sec"]
    for name, r in results.items():
        r["vs_baseline_x"] = round(r["events_per_sec"] / baseline_eps, 4)

    common.report("j_policy_throughput_burst_50000", results)


if __name__ == "__main__":
    asyncio.run(main())
