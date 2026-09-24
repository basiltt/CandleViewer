# -*- coding: utf-8 -*-
"""R1 -- the inline `"*": {"actions": ["defer"]}` scaffolding SWALLOWS events.

Catalogue 28 §1.3b (E50-T09) asserts the A3 scaffolding is "dead but
harmless": *"with `onUnhandled: 'defer'` set, the runtime holds the event
before any `*` handler is consulted, so the inline handler never fires."*

This probe tests that claim directly on B6 `submitting_slice`, which carries
both the machine-level `onUnhandled: "defer"` and the inline `"*"` handler.

Result decides: OUR-CONTRACT defect (scaffolding must be stripped) vs
LIBRARY defect (defer policy should out-rank `*`).
"""
from __future__ import annotations

import asyncio
import copy
import json

import cvlib
from cvlib import Rig


async def run(cfg, label):
    rig = Rig(service_mode={"submit_child": "gate"})
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    await interp.start()
    await asyncio.sleep(cvlib.SETTLE)
    await interp.send("SLICE_DUE")
    await asyncio.sleep(cvlib.SETTLE)
    mid = sorted(interp.current_state_ids)
    r = await interp.send("USER_PAUSE", wait=True)
    await asyncio.sleep(cvlib.SETTLE)
    out = {
        "label": label,
        "mid": mid,
        "deferred_count": interp.deferred_count,
        "receipt": {
            "changed": getattr(r, "changed", None),
            "deferred": getattr(r, "deferred", None),
            "error": repr(getattr(r, "error", None)),
        },
        "unhandled_hook": list(plug.unhandled),
        "dropped_hook": list(plug.dropped),
        "star_defer_action_ran": rig.calls.count("A:defer"),
    }
    rig.gate("submit_child").set()
    await asyncio.sleep(cvlib.SETTLE * 4)
    out["after"] = sorted(interp.current_state_ids)
    await interp.stop()
    return out


def strip_star(cfg):
    c = copy.deepcopy(cfg)

    def walk(n):
        on = n.get("on") or {}
        on.pop("*", None)
        for ch in (n.get("states") or {}).values():
            walk(ch)

    walk(c)
    return c


async def main():
    cfg = cvlib.load("B6")
    asis = await run(cfg, "as-catalogued (inline '*' defer scaffolding)")
    stripped = await run(strip_star(cfg), "scaffolding stripped (E50-T09)")
    print(json.dumps([asis, stripped], indent=2))
    print()
    print("VERDICT: inline '*' consumed the event:",
          asis["after"] != stripped["after"])
    print("  as-is    ->", asis["after"], "deferred:", asis["deferred_count"])
    print("  stripped ->", stripped["after"], "deferred:",
          stripped["deferred_count"])


asyncio.run(main())
