# -*- coding: utf-8 -*-
"""Round-9 drives on the catalogued B6 contract @ 19cb1f1.

STANDALONE: stdlib + xstate_statemachine only. The B6 chart is inlined
(trimmed to the rollback+onDone arm) so the script runs from any cwd.

D4  rollback + invoke.onDone storm  -> must trip at maxIterations + 3 on
    BOTH engines and BOTH service kinds, with RunawayChainError.stranded
    naming the invoke and on_invocation_stranded firing (#207, #209, #210).
D5  has_dormant_invocations / pending_invocations answer after the cut.

Usage:  python g9_drives.py [async|def]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any, Dict, List, Tuple

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.plugins import PluginBase

STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
RESULTS: Dict[str, Any] = {}


def rec(key: str, ok: bool, note: Any = "") -> bool:
    key = "[%s]%s" % (STYLE, key)
    RESULTS[key] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + key + ("  | " + json.dumps(note, default=str) if note else ""), flush=True)
    return bool(ok)


class Hooks(PluginBase):
    def __init__(self) -> None:
        self.stranded: List[Tuple[str, str]] = []
        self.errors: List[str] = []

    def on_invocation_stranded(self, interp, state_id, invoke_id, error):  # noqa: D102
        self.stranded.append((state_id, invoke_id))

    def on_error(self, interp, error, *a, **k):  # noqa: D102
        self.errors.append(type(error).__name__)


# --------------------------------------------------------------- the chart --
def cfg(limit: int, initial: str = "armed") -> Dict[str, Any]:
    """B6 `submitting_slice` arm: entry actions, invoke, onDone -> armed.

    `record_child` (the onDone action) raises under actionErrorPolicy
    "rollback", so the step is rolled back into `submitting_slice`, whose
    invoke re-arms -- the catalogued rollback+onDone storm.
    """
    return {
        "id": "twap",
        "actionErrorPolicy": "rollback",
        "onUnhandled": "defer",
        "guardErrorPolicy": "raise",
        "strictTargets": True,
        "strict": True,
        "maxIterations": limit,
        "initial": initial,
        "context": {"slices_done": 0},
        "states": {
            "armed": {"on": {"SLICE_DUE": {"target": "#twap.submitting_slice"}}},
            "submitting_slice": {
                "entry": ["bump_slices_done"],
                "invoke": {
                    "id": "slice",
                    "src": "submit_child",
                    "onDone": {
                        "target": "#twap.armed",
                        "actions": ["record_child"],
                    },
                    "onError": {"target": "#twap.failed"},
                },
            },
            "failed": {"type": "final"},
        },
    }


def logic(calls: List[str], style: str = None) -> MachineLogic:
    style = style or STYLE
    def submit_child_def(i, c, e):
        calls.append("submit_child")
        return {"child_id": "c1"}

    async def submit_child_async(i, c, e):
        calls.append("submit_child")
        return {"child_id": "c1"}

    def bump(i, c, e, a):
        c["slices_done"] = c["slices_done"] + 1

    def record_child(i, c, e, a):
        raise RuntimeError("record_child failed")

    return MachineLogic(
        actions={"bump_slices_done": bump, "record_child": record_child},
        services={
            "submit_child": submit_child_async if style == "async" else submit_child_def
        },
    )


async def _plateau(read, stable: int = 6, cap: float = 8.0) -> int:
    """Wait until `read()` stops moving for `stable` consecutive polls."""
    last, same, t0 = read(), 0, time.monotonic()
    while time.monotonic() - t0 < cap:
        await asyncio.sleep(0.05)
        cur = read()
        same = same + 1 if cur == last else 0
        last = cur
        if same >= stable:
            break
    return last


async def d4_async(limit: int, initial: str = "armed") -> Dict[str, Any]:
    calls: List[str] = []
    h = Hooks()
    i = Interpreter(create_machine(cfg(limit, initial), logic=logic(calls))).use(h)
    await i.start()
    if initial == "armed":
        await i.send("SLICE_DUE")
    n = await _plateau(lambda: len(calls))
    out = {
        "laps": n,
        "err": type(i.last_error).__name__ if i.last_error else None,
        "stranded_attr": list(getattr(i.last_error, "stranded", ()) or ()),
        "hook": [list(x) for x in h.stranded],
        "dormant": bool(i.has_dormant_invocations),
        "pending": [getattr(p, "invoke_id", str(p)) for p in i.pending_invocations()],
        "value": i.value,
    }
    await i.stop()
    return out


def d4_sync(limit: int, initial: str = "armed") -> Dict[str, Any]:
    calls: List[str] = []
    h = Hooks()
    # SyncInterpreter cannot run an `async def` service (NotSupportedError,
    # documented): the sync lane is `def` by construction in both passes.
    s = SyncInterpreter(create_machine(cfg(limit, initial), logic=logic(calls, "def"))).use(h)
    try:
        s.start()
        if initial == "armed":
            s.send("SLICE_DUE")
    except RunawayChainError:
        pass
    return {
        "laps": len(calls),
        "err": type(s.last_error).__name__ if s.last_error else None,
        "stranded_attr": list(getattr(s.last_error, "stranded", ()) or ()),
        "hook": [list(x) for x in h.stranded],
        "dormant": bool(s.has_dormant_invocations),
        "pending": [getattr(p, "invoke_id", str(p)) for p in s.pending_invocations()],
        "value": s.value,
    }


async def main() -> None:
    for limit in (4, 5, 8, 12):
        a = await d4_async(limit)
        sy = d4_sync(limit)
        exp = limit + 2  # event-entered: seed + limit+1 cut (no initial descent)
        rec("D4/limit=%d async laps == maxIterations+3" % limit, a["laps"] == exp,
            dict(expected=exp, **a))
        rec("D4/limit=%d sync laps == maxIterations+3" % limit, sy["laps"] == exp,
            dict(expected=exp, **sy))
        rec("D4/limit=%d lap parity async==sync (#209)" % limit,
            a["laps"] == sy["laps"], {"async": a["laps"], "sync": sy["laps"]})
        rec("D4/limit=%d RunawayChainError both engines" % limit,
            a["err"] == "RunawayChainError" == sy["err"],
            {"async": a["err"], "sync": sy["err"]})
        rec("D5/limit=%d stranded names 'slice' both engines (#207)" % limit,
            a["stranded_attr"] == ["slice"] and sy["stranded_attr"] == ["slice"],
            {"async": a["stranded_attr"], "sync": sy["stranded_attr"]})
        rec("D5/limit=%d on_invocation_stranded fired both engines" % limit,
            a["hook"] == [["twap.submitting_slice", "slice"]]
            and sy["hook"] == [["twap.submitting_slice", "slice"]],
            {"async": a["hook"], "sync": sy["hook"]})
        rec("D5/limit=%d has_dormant_invocations true, parked in submitting_slice" % limit,
            a["dormant"] and sy["dormant"]
            and a["value"] == sy["value"] == "submitting_slice",
            {"async": [a["dormant"], a["value"]], "sync": [sy["dormant"], sy["value"]]})

    # --- D6: the same storm with the invoke on the INITIAL state. Here the
    # initial descent is charged too, so the plateau is maxIterations + 3 --
    # the library's own #210 pin, reproduced on the catalogued B6 arm.
    for limit in (4, 5, 8, 12):
        a = await d4_async(limit, initial="submitting_slice")
        sy = d4_sync(limit, initial="submitting_slice")
        exp = limit + 3
        rec("D6/limit=%d async laps == maxIterations+3 (#210 shape)" % limit,
            a["laps"] == exp, dict(expected=exp, **a))
        rec("D6/limit=%d sync laps == maxIterations+3 (#210 shape)" % limit,
            sy["laps"] == exp, dict(expected=exp, **sy))
        rec("D6/limit=%d three-lane lap parity (#209)" % limit,
            a["laps"] == sy["laps"], {"async": a["laps"], "sync": sy["laps"]})
        rec("D6/limit=%d stranded + hook + dormant on both engines" % limit,
            a["stranded_attr"] == sy["stranded_attr"] == ["slice"]
            and a["hook"] == sy["hook"] == [["twap.submitting_slice", "slice"]]
            and a["dormant"] and sy["dormant"],
            {"async": [a["stranded_attr"], a["hook"], a["dormant"]],
             "sync": [sy["stranded_attr"], sy["hook"], sy["dormant"]]})

    path = "results/g9_drives.%s.json" % STYLE
    import pathlib
    p = pathlib.Path(__file__).parent / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(RESULTS, indent=1, default=str), encoding="utf-8")
    bad = [k for k, v in RESULTS.items() if not v["pass"]]
    print("\n--- %d checks, %d FAIL: %s" % (len(RESULTS), len(bad), bad), flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    asyncio.run(main())
