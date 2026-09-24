# -*- coding: utf-8 -*-
"""R3 -- `guardErrorPolicy: "raise"` on a MULTI-CANDIDATE event.

INV-B8-b: `tightens_only` is deny-polarity; if it RAISES the amendment must
be blocked AND the failure must surface (a crashed guard is not a denial --
§1.3b). Observed in c2: `TIGHTEN_SL` in `protected` with a raising
`tightens_only` produced no exception at the caller, no interpreter error,
and no state change -- i.e. exactly the shape of a clean deny.

This probe separates two hypotheses:
  H1 the policy is ignored entirely;
  H2 the policy raises only when the guard is the LAST candidate / when the
     event would otherwise be unhandled, and `onUnhandled: "defer"` then
     absorbs the event, hiding the failure.
Controls: same machine with onUnhandled "error"; a single-candidate guard
(B6 `preflight_invalid` on an `always`); B10 `in_storm_window`.
"""
from __future__ import annotations

import asyncio
import copy
import json

import cvlib
from cvlib import Rig


async def probe(cfg, label, script, raising, *, post=None):
    rig = Rig(guard_values={"exchange_reports_sl": True,
                            "all_channels_ok": True},
              guard_raises=set(raising))
    _m, interp, plug, clock = cvlib.new_interp(cfg, rig)
    start_err = None
    try:
        await interp.start()
    except Exception as exc:  # noqa: BLE001
        start_err = type(exc).__name__ + ": " + str(exc)[:120]
    await asyncio.sleep(cvlib.SETTLE)
    sends = []
    for ev in script:
        try:
            r = await interp.send(ev, wait=True)
            sends.append((ev, "OK", getattr(r, "changed", None),
                          repr(getattr(r, "error", None))))
        except Exception as exc:  # noqa: BLE001
            sends.append((ev, type(exc).__name__, str(exc)[:120], None))
        await asyncio.sleep(cvlib.SETTLE * 2)
    out = {
        "label": label,
        "start_error": start_err,
        "sends": sends,
        "states": sorted(interp.current_state_ids),
        "status": interp.status,
        "interp.error": repr(interp.error),
        "deferred": interp.deferred_count,
        "unhandled": list(plug.unhandled),
        "dropped": list(plug.dropped),
        "guard_calls": [c for c in rig.calls if c.startswith("G:")],
    }
    try:
        await interp.stop()
    except Exception:  # noqa: BLE001
        pass
    return out


def set_unhandled(cfg, val):
    c = copy.deepcopy(cfg)
    c["onUnhandled"] = val
    return c


def strip_star(cfg):
    c = copy.deepcopy(cfg)

    def walk(n):
        (n.get("on") or {}).pop("*", None)
        for ch in (n.get("states") or {}).values():
            walk(ch)

    walk(c)
    return c


async def main():
    b8 = cvlib.load("B8")
    b6 = cvlib.load("B6")
    b10 = cvlib.load("B10")
    rows = []
    rows.append(await probe(b8, "B8 TIGHTEN_SL, raising tightens_only "
                                "(as-catalogued, onUnhandled=defer)",
                            ["POSITION_OPENED", "TIGHTEN_SL"],
                            ["tightens_only"]))
    rows.append(await probe(set_unhandled(strip_star(b8), "error"),
                            "B8 same, onUnhandled=error + '*' stripped",
                            ["POSITION_OPENED", "TIGHTEN_SL"],
                            ["tightens_only"]))
    rows.append(await probe(b8, "B8 control: raising exchange_reports_sl "
                                "(guard on an invoke onDone branch)",
                            ["POSITION_OPENED"], ["exchange_reports_sl"]))
    rows.append(await probe(b6, "B6 control: raising preflight_invalid "
                                "(guard on an `always` at start)",
                            [], ["preflight_invalid"]))
    rows.append(await probe(b10, "B10 control: raising in_storm_window "
                                 "(first of two `on` candidates)",
                            ["CONDITION_MET"], ["in_storm_window"]))
    print(json.dumps(rows, indent=2, default=str))


asyncio.run(main())
