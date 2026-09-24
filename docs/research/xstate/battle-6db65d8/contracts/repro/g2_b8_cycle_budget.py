# -*- coding: utf-8 -*-
"""R7/G2 -- why the B8 `naked` <-> `verifying` invoke cycle escapes the #168
chain budget on 221ce7c while the minimal two-state cycle (g1) trips.

Instruments `_raise_depth` / `_chain_tripped` per lap on the real B8 contract
and on progressively reduced variants, to isolate which structural feature of
B8 resets the chain.
"""
from __future__ import annotations

import asyncio
import json
import time

import cvlib
from cvlib import Rig


async def probe(budget: float = 3.0, max_iter: int | None = 40) -> dict:
    cfg = json.loads(json.dumps(cvlib.load("B8")))
    if max_iter is not None:
        cfg["maxIterations"] = max_iter
    rig = Rig(guard_values={"exchange_reports_sl": False})
    _m, interp, plug, _clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(0.05)
    await interp.send("POSITION_OPENED")
    t0 = time.monotonic()
    depths = []
    while time.monotonic() - t0 < budget:
        await asyncio.sleep(0.02)
        depths.append(
            (
                interp._raise_depth,
                interp._chain_tripped,
                len(interp._priority_queue),
                interp._processing,
            )
        )
        if not interp.last_transition_ok:
            break
    laps = rig.calls.count("S:attach_fallback_sl")
    out = {
        "maxIterations": cfg.get("maxIterations"),
        "elapsed_s": round(time.monotonic() - t0, 2),
        "laps": laps,
        "tripped": not interp.last_transition_ok,
        "last_error": type(interp.last_error).__name__
        if interp.last_error
        else None,
        "dropped": plug.dropped[:3],
        "raise_depth_samples": depths[:12],
        "max_depth_seen": max((d[0] for d in depths), default=None),
        "states": sorted(interp.current_state_ids),
    }
    await interp.stop()
    return out


async def main() -> None:
    res = {"B8_maxIter40": await probe(3.0, 40), "B8_default": await probe(3.0, None)}
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/g2_b8_cycle_budget.json", "w"), indent=1)


if __name__ == "__main__":
    import logging

    logging.disable(logging.ERROR)
    asyncio.run(main())
