# -*- coding: utf-8 -*-
"""C8 -- produce the corrected catalogue copies and prove they fix the
OUR-CONTRACT defects.

Defect CD-01 (catalogue): the inline A3 scaffolding
`"on": {"*": {"actions": ["defer"]}}` is NOT "dead but harmless" as
§1.3b/E50-T09 asserts. It is a live wildcard handler that MATCHES first, so
(i) the event is consumed by a no-op user action instead of being held by
`onUnhandled: "defer"`, and (ii) `"*" in machine.known_events` makes EVERY
event name known, silently disabling `strict: true`.

This script writes `<B>.fixed.machine.json` with the scaffolding stripped
(the E50-T09 edit) and re-runs the two failing checks against both copies,
emitting the diff for the catalogue log.
"""
from __future__ import annotations

import asyncio
import copy
import difflib
import json
import pathlib

import cvlib
from cvlib import Rig

HERE = pathlib.Path(__file__).parent
IDS = ["B6", "B7", "B8", "B9", "B10"]


def strip_star(cfg):
    c = copy.deepcopy(cfg)
    removed = []

    def walk(n, path):
        on = n.get("on")
        if isinstance(on, dict) and "*" in on:
            removed.append(path + ".on['*'] = " + json.dumps(on["*"]))
            del on["*"]
            if not on:
                n.pop("on")
        for name, ch in (n.get("states") or {}).items():
            walk(ch, path + "." + name)

    walk(c, c.get("id", "?"))
    return c, removed


async def check(cfg, label):
    """The two checks CD-01 breaks."""
    out = {"label": label}
    rig = Rig()
    m = cvlib.build(cfg, rig)
    out["known_events_has_star"] = "*" in m.known_events

    # strict rejection
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    try:
        await interp.send("TOTALLY_UNDECLARED_EVENT", wait=True)
        out["strict_rejects_typo"] = False
    except Exception as exc:  # noqa: BLE001
        out["strict_rejects_typo"] = type(exc).__name__ == "UnknownEventError"
    await interp.stop()
    return out


async def b6_defer(cfg, label):
    rig = Rig(service_mode={"submit_child": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    await interp.send("SLICE_DUE")
    await asyncio.sleep(cvlib.SETTLE)
    await interp.send("USER_PAUSE")
    await asyncio.sleep(cvlib.SETTLE)
    dc = interp.deferred_count
    rig.gate("submit_child").set()
    await asyncio.sleep(cvlib.SETTLE * 4)
    st = sorted(interp.current_state_ids)
    await interp.stop()
    return {"label": label, "deferred_at_hold": dc, "final": st,
            "event_survived": st == ["twap.paused"]}


async def main():
    report = {"diffs": {}, "before": [], "after": []}
    for bid in IDS:
        raw = json.loads(
            (HERE / (bid + ".machine.json")).read_text(encoding="utf-8")
        )
        fixed, removed = strip_star(raw)
        if removed:
            (HERE / (bid + ".fixed.machine.json")).write_text(
                json.dumps(fixed, indent=2), encoding="utf-8"
            )
            d = list(difflib.unified_diff(
                json.dumps(raw, indent=2).splitlines(),
                json.dumps(fixed, indent=2).splitlines(),
                fromfile=bid + ".machine.json (catalogue)",
                tofile=bid + ".fixed.machine.json (E50-T09 applied)",
                lineterm="", n=2,
            ))
            report["diffs"][bid] = {"removed": removed, "diff": d}
        else:
            report["diffs"][bid] = {"removed": [], "diff": []}

    for bid in IDS:
        raw = json.loads(
            (HERE / (bid + ".machine.json")).read_text(encoding="utf-8")
        )
        fixed, _ = strip_star(raw)
        report["before"].append(await check(raw, bid + " as-catalogued"))
        report["after"].append(await check(fixed, bid + " fixed"))

    raw6 = json.loads(
        (HERE / "B6.machine.json").read_text(encoding="utf-8")
    )
    f6, _ = strip_star(raw6)
    report["b6_defer_before"] = await b6_defer(raw6, "as-catalogued")
    report["b6_defer_after"] = await b6_defer(f6, "fixed")

    print(json.dumps(report, indent=2))


asyncio.run(main())
