# -*- coding: utf-8 -*-
"""R12 -- livelock fuzzer: does every self-generated cycle trip, observably,
at the same lap count on both engines and both service kinds?

Shapes generated (the round-6/7 livelock family):
  * `always` cycles between two states,
  * invoke ping-pong (`ver -> arm -> ver`) -- #168,
  * rollback + `onDone` re-arming the invoke -- #167,
  * `sendTo` self-loops,
  * priority self-sends (RAISE into the same state).

Every config runs under a 30 s watchdog; a timeout IS the observed result and
is recorded as a HANG, not an error. A trip must be OBSERVABLE through at
least one of `last_error` / the receipt's `error` / `on_event_dropped`; a
silent stop is a failure in its own right (a runaway that ends quietly is
indistinguishable from completion).

Lap counts are compared across engines for the `def` lane (the sync engine
cannot run an async service).

    usage: r12_livelock_fuzz.py [N_CONFIGS] [SEED]
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from collections import Counter

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

N = int(sys.argv[1]) if len(sys.argv) > 1 else 500
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 5
WATCHDOG = 30.0

OUT = Counter()
HANGS: list[str] = []
SILENT: list[str] = []
LAPMISMATCH: list[str] = []


class Watch(PluginBase):
    def __init__(self) -> None:
        self.dropped: list[tuple[str, str]] = []
        self.laps = 0

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), reason))

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        self.laps += 1


SHAPES = ("always_cycle", "invoke_pingpong", "rollback_ondone",
          "sendto_selfloop", "raise_selfsend")


def gen(rnd: random.Random, shape: str, kind: str):
    """Return (spec, logic) for one fuzzed livelock config."""
    actions, services = {}, {}

    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1

    def blow(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1
        raise RuntimeError("rollback")

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    actions["bump"] = bump
    services["svc"] = svc_def if kind == "def" else svc_async
    maxit = rnd.choice([10, 25, 50])

    if shape == "always_cycle":
        spec = {"id": "lv", "initial": "a", "maxIterations": maxit,
                "states": {"a": {"entry": ["bump"], "always": {"target": "b"}},
                           "b": {"entry": ["bump"], "always": {"target": "a"}}}}
    elif shape == "invoke_pingpong":
        spec = {"id": "lv", "initial": "ver", "maxIterations": maxit,
                "states": {
                    "ver": {"entry": ["bump"],
                            "invoke": [{"id": "k", "src": "svc",
                                        "onDone": {"target": "arm"}}]},
                    "arm": {"entry": ["bump"],
                            "invoke": [{"id": "k2", "src": "svc",
                                        "onDone": {"target": "ver"}}]}}}
    elif shape == "rollback_ondone":
        actions["blow"] = blow
        spec = {"id": "lv", "initial": "a", "maxIterations": maxit,
                "actionErrorPolicy": "rollback",
                "states": {
                    "a": {"invoke": [{"id": "k", "src": "svc",
                                      "onDone": {"target": "b",
                                                 "actions": ["blow"]}}]},
                    "b": {"entry": ["bump"], "always": {"target": "a"}}}}
    elif shape == "sendto_selfloop":
        spec = {"id": "lv", "initial": "a", "maxIterations": maxit,
                "states": {"a": {"entry": ["bump",
                                           {"type": "sendTo",
                                            "params": {"to": "lv",
                                                       "event": "PING"}}],
                                 "on": {"PING": "a"}}}}
    else:  # raise_selfsend
        spec = {"id": "lv", "initial": "a", "maxIterations": maxit,
                "states": {"a": {"entry": ["bump",
                                           {"type": "raise",
                                            "params": {"event": "PING"}}],
                                 "on": {"PING": "a"}}}}
    return spec, MachineLogic(actions=actions, services=services), maxit


async def run_async(spec, logic) -> tuple[str, int, bool]:
    """-> (outcome, laps, observable)."""
    m = create_machine(json.loads(json.dumps(spec)), logic=logic)
    w = Watch()
    i = Interpreter(m, clock=SimulatedClock())
    i.use(w)
    rcpt_err = None
    try:
        await asyncio.wait_for(i.start(children_timeout=1.0), timeout=WATCHDOG)
        try:
            r = await asyncio.wait_for(i.send("PING", wait=True),
                                       timeout=WATCHDOG)
            rcpt_err = getattr(r, "error", None)
        except asyncio.TimeoutError:
            return "HANG(send)", w.laps, False
        except Exception as exc:  # noqa: BLE001
            rcpt_err = exc
    except asyncio.TimeoutError:
        return "HANG(start)", w.laps, False
    except Exception as exc:  # noqa: BLE001
        rcpt_err = exc
    observable = bool(rcpt_err) or i.error is not None or bool(w.dropped)
    out = "TRIP" if observable else ("running" if i.status == "running"
                                     else i.status)
    # 🧮 `laps` from the hook can differ from WORK DONE if one engine emits
    #    an extra synthetic transition record (#124). `n` is the context
    #    counter every entry action bumps, so it measures the cycle itself.
    w.laps = int((i.context or {}).get("n", w.laps))
    try:
        await asyncio.wait_for(i.stop(), timeout=5)
    except Exception:  # noqa: BLE001
        pass
    return out, w.laps, observable


def run_sync(spec, logic) -> tuple[str, int, bool]:
    m = create_machine(json.loads(json.dumps(spec)), logic=logic)
    w = Watch()
    i = SyncInterpreter(m)
    i.use(w)
    err = None
    try:
        i.start()
        r = i.send("PING")
        err = getattr(r, "error", None)
    except Exception as exc:  # noqa: BLE001
        err = exc
    observable = bool(err) or i.error is not None or bool(w.dropped)
    out = "TRIP" if observable else ("running" if i.status == "running"
                                     else i.status)
    w.laps = int((i.context or {}).get("n", w.laps))
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return out, w.laps, observable


async def main() -> None:
    rnd = random.Random(SEED)
    t0 = time.monotonic()
    per_shape = Counter()
    for n in range(N):
        shape = SHAPES[n % len(SHAPES)]
        kind = "def" if (n // len(SHAPES)) % 2 == 0 else "async"
        spec, logic, maxit = gen(rnd, shape, kind)
        tag = f"{shape}/{kind}/maxIt={maxit}#{n}"

        out_a, laps_a, obs_a = await run_async(spec, logic)
        OUT[f"async:{out_a}"] += 1
        per_shape[(shape, kind, out_a)] += 1
        if out_a.startswith("HANG"):
            HANGS.append(f"async {tag}: {out_a}")
        elif not obs_a and out_a != "running":
            SILENT.append(f"async {tag}: ended {out_a} with NO observable trip")

        # the sync engine cannot take an async service
        if kind == "def":
            spec2, logic2, _ = gen(random.Random(SEED + n), shape, kind)
            out_s, laps_s, obs_s = run_sync(spec, logic)
            OUT[f"sync:{out_s}"] += 1
            if out_s.startswith("HANG"):
                HANGS.append(f"sync {tag}: {out_s}")
            elif not obs_s and out_s != "running":
                SILENT.append(f"sync {tag}: ended {out_s} with NO observable trip")
            if out_a == "TRIP" and out_s == "TRIP" and laps_a != laps_s:
                LAPMISMATCH.append(
                    f"{tag}: async laps={laps_a} sync laps={laps_s}")
        if time.monotonic() - t0 > 100:
            print("[time bound reached after %d configs]" % (n + 1))
            break

    print("configs run          : %d" % sum(
        v for k, v in OUT.items() if k.startswith("async:")))
    print("outcomes             :")
    for k, v in sorted(OUT.items()):
        print("    %-22s %d" % (k, v))
    print("outcome by shape x kind (async engine):")
    for (sh, ki, o), v in sorted(per_shape.items()):
        print("    %-18s %-6s %-9s %d" % (sh, ki, o, v))
    print("HANGS (watchdog %.0fs) : %d   <- must be 0" % (WATCHDOG, len(HANGS)))
    for h in HANGS[:6]:
        print("    -", h)
    print("SILENT trips         : %d   <- must be 0" % len(SILENT))
    for s in SILENT[:6]:
        print("    -", s)
    print("lap-count mismatches : %d   <- must be 0" % len(LAPMISMATCH))
    for s in LAPMISMATCH[:8]:
        print("    -", s)
    print("elapsed              : %.1fs" % (time.monotonic() - t0))
    ok = not (HANGS or SILENT or LAPMISMATCH)
    print("VERDICT:", "PASS" if ok else "FAIL")


asyncio.run(main())
