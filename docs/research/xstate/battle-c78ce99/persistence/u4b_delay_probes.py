# -*- coding: utf-8 -*-
"""U4b -- two focused probes split out of U4.

STANDALONE (stdlib + xstate_statemachine).  Run from any cwd.

P1  Is `send(..., delay=D)` actually delayed?  Measure the wall-clock gap
    between the send and the transition it causes, for a self-send (from an
    action) and an external send (from outside), D = 0.3 s.

P2  When the #206 delayed self-cycle is cut at `maxIterations`, HOW is the
    cut observable?  U4 saw the cycle stop at `maxIterations + 2` laps with
    `status=running` and `error=None` -- bounded, but with no exception.
    This probe subscribes every relevant hook (`on_event_dropped`,
    `on_invocation_stranded`) and captures the ERROR log, to establish
    whether the cut is announced at all.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")


def _svc():
    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return svc_def if KIND == "def" else svc_async


# --------------------------------------------------------------- P1 --------
SPEC1 = {
    "id": "d1",
    "initial": "a",
    "context": {"t_send": 0.0, "t_arrive": 0.0},
    "states": {
        "a": {"on": {"PONG": {"target": "b", "actions": ["stamp"]}}},
        "b": {},
    },
}


async def p1() -> list:
    print("=== P1 is send(delay=0.3) actually delayed? ===")
    fails = []
    loop = asyncio.get_running_loop()

    for origin in ("self (from an entry action)", "external (from outside)"):
        marks = {}

        def stamp(i, c, e, a):  # noqa: ANN001
            marks["arrive"] = loop.time()

        def kick(i, c, e, a):  # noqa: ANN001
            marks["send"] = loop.time()
            i.send("PONG", delay=0.3)

        spec = json.loads(json.dumps(SPEC1))
        if origin.startswith("self"):
            spec["states"]["a"]["entry"] = ["kick"]

        m = create_machine(spec, logic=MachineLogic(
            actions={"stamp": stamp, "kick": kick},
            services={"svc": _svc()}))
        i = Interpreter(m)
        await i.start()
        if origin.startswith("external"):
            marks["send"] = loop.time()
            i.send("PONG", delay=0.3)
        await asyncio.sleep(0.8)
        gap = marks.get("arrive", 0) - marks.get("send", 0)
        st = sorted(i.current_state_ids)
        print(f"   {origin:<28} states={st} gap={gap*1000:7.1f} ms "
              f"(expected ~300 ms)")
        if "arrive" not in marks:
            fails.append(f"P1 {origin}: the delayed send never arrived")
        elif gap < 0.25:
            fails.append(
                f"P1 {origin}: delay=0.3 fired after only {gap*1000:.1f} ms "
                f"-- the delay is not honoured")
        await i.stop()
    return fails


# --------------------------------------------------------------- P2 --------
SPEC2 = {
    "id": "cut",
    "maxIterations": 12,
    "initial": "a",
    "context": {"laps": 0},
    "states": {
        "a": {"entry": ["ping"], "on": {"PONG": "b"}},
        "b": {"entry": ["ping"], "on": {"PONG": "a"}},
    },
}

# Control: the SAME cycle with delay=0 (a plain `raise`), which #206 says
# must trip at the same lap (+/- 1).
SPEC2_ZERO = json.loads(json.dumps(SPEC2))


class Hooks(PluginBase):
    def __init__(self) -> None:
        self.dropped = []
        self.stranded = []

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), str(reason)))

    def on_invocation_stranded(self, interp, state_id, invoke_id, error):  # noqa: ANN001,E501
        self.stranded.append((state_id, invoke_id))


async def _run_cycle(delay_s: float) -> tuple:
    h = Hooks()
    logbuf = io.StringIO()
    handler = logging.StreamHandler(logbuf)
    handler.setLevel(logging.ERROR)
    root = logging.getLogger("xstate_statemachine")
    root.addHandler(handler)

    def ping(i, c, e, a):  # noqa: ANN001
        c["laps"] = c.get("laps", 0) + 1
        if delay_s:
            i.send("PONG", delay=delay_s)
        else:
            i.send("PONG")

    m = create_machine(json.loads(json.dumps(SPEC2)), logic=MachineLogic(
        actions={"ping": ping}, services={"svc": _svc()}))
    i = Interpreter(m)
    i.use(h)
    await i.start()

    loop = asyncio.get_running_loop()
    end = loop.time() + 10.0
    last = -1
    verdict = "HANG"
    while loop.time() < end:
        if getattr(i, "status", "") in ("error", "stopped", "done"):
            verdict = "RAISED" if i.status == "error" else str(i.status)
            break
        cur = i.context.get("laps", 0)
        if cur == last:
            await asyncio.sleep(0.08)
            if i.context.get("laps", 0) == cur:
                verdict = "BOUNDED-SILENT"
                break
        last = cur
        await asyncio.sleep(0.02)

    laps = i.context.get("laps", 0)
    err = type(i.error).__name__ if getattr(i, "error", None) else None
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    root.removeHandler(handler)
    return verdict, laps, err, h.dropped, logbuf.getvalue().strip()


async def p2() -> list:
    print("\n=== P2 how is the #206 delayed cycle's cut announced? ===")
    fails = []
    rows = {}
    for label, d in (("delay=0 (plain raise)", 0.0),
                     ("delay=1 ms (#206)", 0.001)):
        verdict, laps, err, dropped, logtxt = await _run_cycle(d)
        rows[label] = laps
        print(f"   {label:<24} {verdict:<15} laps={laps:<4} error={err}")
        print(f"        on_event_dropped: {dropped[:3]}"
              f"{' ...' if len(dropped) > 3 else ''}  (n={len(dropped)})")
        print(f"        ERROR log: {logtxt.splitlines()[:1] or 'none'}")
        if verdict == "HANG":
            fails.append(f"P2 {label}: the cycle never terminated (HANG)")
        if verdict == "BOUNDED-SILENT" and not dropped and not logtxt:
            fails.append(
                f"P2 {label}: the chain cut is SILENT -- bounded at "
                f"{laps} laps with no exception, no on_event_dropped and "
                f"no ERROR log")

    a, b = rows.get("delay=0 (plain raise)"), rows.get("delay=1 ms (#206)")
    if a is not None and b is not None:
        print(f"\n   lap parity: delay=0 -> {a} laps, delay=1 ms -> {b} laps "
              f"(#206 promises equality +/- 1)")
        if abs(a - b) > 1:
            fails.append(
                f"P2 lap parity: delay=0 tripped at {a} laps but delay=1 ms "
                f"at {b} -- more than +/-1 apart")
    return fails


async def main() -> None:
    print(f"=== U4b delayed-send probes [{KIND}] ===")
    fails = await p1()
    fails += await p2()
    print()
    print("FAILURES:", fails or "none")
    print("VERDICT:", "FAIL" if fails else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
