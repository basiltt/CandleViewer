# -*- coding: utf-8 -*-
"""C1 -- build every contract machine (B6-B10) with stub logic.

Records InvalidConfigError / ImplementationMissingError / anything else at
`create_machine` time, plus a start() smoke on the async engine.
"""
from __future__ import annotations

import asyncio
import json
import traceback
import warnings

import cvlib
from cvlib import Rig

IDS = ["B6", "B7", "B8", "B9", "B10"]


async def main() -> None:
    report = {}
    for bid in IDS:
        cfg = cvlib.load(bid)
        rig = Rig()
        row = {"id": cfg.get("id"), "build": None, "start": None, "warnings": []}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                m = cvlib.build(cfg, rig)
                row["build"] = "OK"
                acts, guards, svcs = cvlib.collect_names(cfg)
                row["counts"] = {
                    "actions": len(acts),
                    "guards": len(guards),
                    "services": len(svcs),
                    "events": len(cvlib.declared_events(cfg)),
                }
                row["policies"] = {
                    "actionErrorPolicy": m.action_error_policy,
                    "onUnhandled": m.on_unhandled,
                    "guardErrorPolicy": m.guard_error_policy,
                    "strictTargets": m.strict_targets,
                    "strict": m.strict,
                    "spawnBlockingTimeout": m.spawn_blocking_timeout_ms,
                }
            except Exception as exc:  # noqa: BLE001
                row["build"] = type(exc).__name__ + ": " + str(exc)[:400]
                report[bid] = row
                continue
            row["warnings"] = [
                w0.category.__name__ + ": " + str(w0.message)[:200] for w0 in w
            ]
        try:
            _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
            await interp.start()
            await asyncio.sleep(0.05)
            row["start"] = {
                "states": sorted(interp.current_state_ids),
                "status": interp.status,
                "transitions": list(plug.transitions),
                "actions": list(plug.actions),
            }
            await interp.stop()
        except Exception as exc:  # noqa: BLE001
            row["start"] = type(exc).__name__ + ": " + str(exc)[:400]
            traceback.print_exc()
        report[bid] = row
    print(json.dumps(report, indent=2, default=str))


asyncio.run(main())
