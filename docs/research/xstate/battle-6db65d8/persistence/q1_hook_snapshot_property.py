# -*- coding: utf-8 -*-
"""Q1 -- snapshot from EVERY hook must be refused-or-legal, never torn.

Property over N randomly generated machines (nested compound + parallel
regions + after-timers + deferred replay).  A plugin takes
`get_persisted_snapshot()` from each of these windows:

  on_transition, on_action_execute, entry action of a nested state,
  exit action, inside a deferred replay, inside an after-timer callback.

Accept criteria for every attempt:
  * refused with SnapshotMidStepError  -> LEGAL
  * accepted                           -> must restore and be SELF-CONSISTENT:
        - status running => one leaf per region
        - round-trip byte-identical (canonical JSON, taken_at excluded)
        - context must match the machine's context at that instant
  * any other exception                -> RAW (defect)

Usage: q1_hook_snapshot_property.py [N=300] [SEED=7]
"""
from __future__ import annotations

import asyncio
import json
import random
import sys

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    XStateMachineError,
)
from xstate_statemachine.plugins import PluginBase

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 7


def gen_machine(rnd: random.Random, idx: int):
    """Random parallel machine: 2 regions, nested compound, timers."""
    regions = {}
    nreg = rnd.choice([2, 2, 3])
    alphabet = []
    for r in range(nreg):
        rid = f"r{r}"
        nstates = rnd.choice([2, 3])
        sts = {}
        for s in range(nstates):
            sid = f"s{s}"
            nxt = f"s{(s + 1) % nstates}"
            ev = f"E{r}{s}"
            alphabet.append(ev)
            node = {
                "on": {ev: {"target": nxt, "actions": [f"act_{rid}_{sid}"]}},
                "entry": [f"en_{rid}_{sid}"],
                "exit": [f"ex_{rid}_{sid}"],
            }
            if rnd.random() < 0.4:
                node["after"] = {50: {"target": nxt, "actions": ["tick"]}}
            if rnd.random() < 0.35:
                # nested compound child
                node["initial"] = "c0"
                node.pop("after", None)
                node["states"] = {
                    "c0": {
                        "on": {f"D{r}{s}": "c1"},
                        "entry": [f"en_{rid}_{sid}_c0"],
                    },
                    "c1": {"entry": [f"en_{rid}_{sid}_c1"]},
                }
                alphabet.append(f"D{r}{s}")
            sts[sid] = node
        regions[rid] = {"initial": "s0", "states": sts}
    cfg = {
        "id": f"g{idx}",
        "type": "parallel",
        "context": {"n": 0, "log": []},
        "onUnhandled": "defer" if rnd.random() < 0.5 else "ignore",
        "states": regions,
    }
    return cfg, sorted(set(alphabet))


def collect_actions(node, acc):
    for k in ("entry", "exit"):
        for a in node.get(k, []) or []:
            acc.add(a)
    for key in ("on", "after"):
        for _e, t in (node.get(key) or {}).items():
            for tr in t if isinstance(t, list) else [t]:
                if isinstance(tr, dict):
                    for a in tr.get("actions", []) or []:
                        acc.add(a)
    for ch in (node.get("states") or {}).values():
        collect_actions(ch, acc)


def build(cfg):
    """create_machine with a generated MachineLogic for every action name.

    Each action MUTATES context, so an accepted mid-action snapshot whose
    context predates the mutation is detectable as a tear.
    """
    from xstate_statemachine import MachineLogic

    names = set()
    collect_actions(cfg, names)

    def mk(nm):
        def _a(interp, ctx, event, action_def=None):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
            ctx.setdefault("log", []).append(nm)

        return _a

    logic = MachineLogic(actions={nm: mk(nm) for nm in names})
    return create_machine(json.loads(json.dumps(cfg)), logic=logic)


def canon(blob: dict) -> str:
    d = dict(blob)
    d.pop("taken_at", None)
    return json.dumps(d, sort_keys=True, default=str)


class Stats:
    def __init__(self):
        self.attempts = 0
        self.refused = 0
        self.accepted = 0
        self.torn = 0
        self.raw = 0
        self.mismatch = 0
        self.windows = {}
        self.raw_examples = []
        self.torn_examples = []
        self.torn_windows = {}


def region_legal(interp) -> bool:
    return interp._configuration_is_legal()


class SnapEverywhere(PluginBase):
    def __init__(self, st: Stats, cfg, logs):
        self.st = st
        self.cfg = cfg
        self.logs = logs
        self.started = False

    def _try(self, interp, window):
        st = self.st
        st.attempts += 1
        window = window if self.started else window + "@start"
        st.windows[window] = st.windows.get(window, 0) + 1
        ctx_at = json.dumps(interp.context, sort_keys=True, default=str)
        try:
            blob = interp.get_persisted_snapshot()
        except SnapshotMidStepError:
            st.refused += 1
            return
        except XStateMachineError as e:
            st.refused += 1
            self.logs.append(f"typed-refusal {window}: {type(e).__name__}")
            return
        except Exception as e:  # noqa: BLE001
            st.raw += 1
            if len(st.raw_examples) < 5:
                st.raw_examples.append(f"{window}: {type(e).__name__}: {e}")
            return
        st.accepted += 1
        # accepted: must be self-consistent
        try:
            machine = build(self.cfg)
            r = SyncInterpreter.from_snapshot(
                json.dumps(blob), machine, verify_machine_hash=False
            )
            if blob.get("status") == "running" and not region_legal(r):
                st.torn += 1
                st.torn_windows[window] = st.torn_windows.get(window, 0) + 1
                if len(st.torn_examples) < 5:
                    st.torn_examples.append(f"{window}: illegal cfg")
                return
            if canon(r.get_persisted_snapshot()) != canon(blob):
                st.mismatch += 1
                if len(st.torn_examples) < 5:
                    st.torn_examples.append(f"{window}: roundtrip mismatch")
                return
            if (
                json.dumps(blob.get("context"), sort_keys=True, default=str)
                != ctx_at
            ):
                st.torn += 1
                st.torn_windows[window] = st.torn_windows.get(window, 0) + 1
                if len(st.torn_examples) < 5:
                    st.torn_examples.append(
                        f"{window}: context drift vs live at snapshot time"
                    )
        except XStateMachineError as e:
            st.torn += 1
            st.torn_windows[window] = st.torn_windows.get(window, 0) + 1
            if len(st.torn_examples) < 5:
                st.torn_examples.append(
                    f"{window}: accepted blob fails restore: "
                    f"{type(e).__name__}: {e}"
                )

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        self._try(interp, "on_transition")

    def on_action_execute(self, interp, action):  # noqa: ANN001
        ty = getattr(action, "type", "")
        if ty.startswith("en_"):
            w = "entry_nested" if ty.count("_") > 3 else "entry"
        elif ty.startswith("ex_"):
            w = "exit"
        elif ty == "tick":
            w = "after_timer_action"
        else:
            w = "on_action"
        self._try(interp, w)

    def on_guard_evaluated(self, interp, guard, event, result):  # noqa: ANN001
        self._try(interp, "on_guard")

    def on_unhandled_event(self, interp, event, ids, disposition):  # noqa: ANN001
        self._try(interp, "deferred_or_unhandled")


async def run_one(cfg, alphabet, rnd, st, logs):
    machine = build(cfg)
    clock = SimulatedClock()
    interp = Interpreter(machine, clock=clock)
    plug = SnapEverywhere(st, cfg, logs)
    interp.use(plug)
    await interp.start()
    plug.started = True
    for _ in range(rnd.choice([4, 6, 8])):
        ev = rnd.choice(alphabet + ["NOPE"])
        try:
            await interp.send(ev, wait=True)
        except XStateMachineError:
            pass
        if rnd.random() < 0.4:
            await clock.increment(60)
    await interp.stop()


async def main():
    rnd = random.Random(SEED)
    st = Stats()
    logs = []
    for i in range(N):
        cfg, alphabet = gen_machine(rnd, i)
        try:
            await run_one(cfg, alphabet, rnd, st, logs)
        except Exception as e:  # noqa: BLE001
            import traceback
            logs.append(
                f"case {i} aborted: {type(e).__name__}: {e} | "
                + traceback.format_exc().replace("\n", " ~ ")
            )
    print(f"machines               : {N}  (seed {SEED})")
    print(f"snapshot attempts      : {st.attempts}")
    print(f"  refused (legal)      : {st.refused}")
    print(f"  accepted             : {st.accepted}")
    print(f"TORN / inconsistent    : {st.torn}   <- must be 0")
    print(f"round-trip mismatches  : {st.mismatch}   <- must be 0")
    print(f"RAW exceptions         : {st.raw}   <- must be 0")
    print("windows exercised      :")
    for k, v in sorted(st.windows.items()):
        print(f"    {k:24s} {v}")
    print("TORN by window       :", dict(sorted(st.torn_windows.items())))
    for x in st.torn_examples:
        print("  TORN EX:", x)
    for x in st.raw_examples:
        print("  RAW  EX:", x)
    for x in logs[:10]:
        print("  LOG:", x)
    ok = st.torn == 0 and st.raw == 0 and st.mismatch == 0
    print("VERDICT:", "PASS" if ok else "FAIL")


asyncio.run(main())
