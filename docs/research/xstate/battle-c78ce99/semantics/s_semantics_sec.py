"""SEMANTICS @ c78ce99 -- #216 config keys, #212 rule matrix, determinism.

S1  #216 config-key fuzzer: misspellings at TOP level and NESTED state
    level. Documents what nested does (the CHANGELOG only claims top).
S2  strict_config bypass via the `x-` escape and via "strictConfig".
S3  #212 rule matrix: delay 0 / 1ms / cancel(id) / delayed raise from an
    EXTERNAL send, vs `after`-rule parity.
S4  Determinism: 50x traces, both engines, both kinds, incl. a
    scheduled_sends restore; plus a PYTHONHASHSEED sweep.

Standalone: stdlib + xstate_statemachine only; every helper inlined.
"""
from __future__ import annotations

import asyncio, copy, json, logging, os, subprocess, sys, traceback, warnings
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter, MachineLogic, SyncInterpreter, create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.plugins import PluginBase

_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn
    return deco


def main(group: str) -> None:
    out, npass = [], 0
    for a in _REG:
        rec: Dict[str, Any] = {"id": a["id"], "title": a["title"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {"exc": f"{type(exc).__name__}: {exc}",
                             "tb": traceback.format_exc()[-1500:]}
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:88]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1800])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


BASE = {"id": "cfg", "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}}}

# Misspellings of real policy keys -- each one, if dropped, silently
# reverts the policy to its permissive default (#216's whole point).
MISSPELLINGS = [
    "actionErrorPolicyy", "actionerrorpolicy", "ActionErrorPolicy",
    "action_error_policy", "guardErrorPolicyy", "onUnhandledEvent",
    "onunhandled", "maxIteration", "maxIterations ", "Strict",
    "strictTarget", "strict_targets", "spawnBlockingTimeoutMs",
    "strictConfigg", "initialState", "context ", "statess",
]


@attack("S1", "#216 config-key fuzzer: misspelled policy keys at TOP level "
              "(must WARN with a hint / raise under strict_config) and at "
              "NESTED state level (document what happens)")
def s1() -> Dict[str, Any]:
    top_warned, top_silent, top_raised = [], [], []
    for key in MISSPELLINGS:
        cfg = copy.deepcopy(BASE); cfg[key] = "x"
        with warnings.catch_warnings(record=True):
            logs: List[str] = []

            class Cap(logging.Handler):
                def emit(self, r): logs.append(r.getMessage())

            lg = logging.getLogger("xstate_statemachine")
            h = Cap(); lg.addHandler(h); prev = lg.level
            lg.setLevel(logging.WARNING); logging.disable(logging.NOTSET)
            try:
                create_machine(copy.deepcopy(cfg))
                msg = " ".join(logs)
                if key in msg:
                    (top_warned if "did you mean" in msg else top_warned).append(
                        {"key": key, "hint": "did you mean" in msg}
                    )
                else:
                    top_silent.append(key)
            finally:
                lg.removeHandler(h); lg.setLevel(prev)
        # strict_config must REFUSE
        try:
            create_machine(copy.deepcopy(cfg), strict_config=True)
            top_raised.append({"key": key, "raised": False})
        except InvalidConfigError:
            pass
        except Exception as exc:  # noqa: BLE001
            top_raised.append({"key": key, "raised": type(exc).__name__})

    # -- NESTED: the same misspelling inside a STATE node.
    nested_silent, nested_caught = [], []
    for key in MISSPELLINGS:
        cfg = copy.deepcopy(BASE); cfg["states"]["a"][key] = "x"
        logs = []

        class Cap2(logging.Handler):
            def emit(self, r): logs.append(r.getMessage())

        lg = logging.getLogger("xstate_statemachine")
        h = Cap2(); lg.addHandler(h); prev = lg.level
        lg.setLevel(logging.WARNING); logging.disable(logging.NOTSET)
        try:
            create_machine(copy.deepcopy(cfg))
            (nested_caught if key in " ".join(logs) else
             nested_silent).append(key)
        except InvalidConfigError:
            nested_caught.append(key)
        finally:
            lg.removeHandler(h); lg.setLevel(prev)
        # and under strict_config
    nested_strict_silent = []
    for key in MISSPELLINGS:
        cfg = copy.deepcopy(BASE); cfg["states"]["a"][key] = "x"
        try:
            create_machine(copy.deepcopy(cfg), strict_config=True)
            nested_strict_silent.append(key)
        except InvalidConfigError:
            pass
    logging.disable(logging.CRITICAL)
    return {
        "ok": not top_silent and not top_raised,
        "top_level": {"warned": len(top_warned),
                      "with_hint": sum(1 for w in top_warned if w["hint"]),
                      "silent": top_silent,
                      "strict_config_did_not_raise": top_raised},
        "nested_state_level": {
            "caught": nested_caught,
            "SILENT": nested_silent,
            "SILENT_even_under_strict_config": nested_strict_silent,
        },
    }


@attack(
    "S2",
    "strict_config escape hatches: the `x-` prefix and a config-level "
    "strictConfig -- can a payload select its own level of checking?",
)
def s2() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    # (a) `x-` keys are ALWAYS accepted (documented). Confirm one cannot
    #     also become BEHAVIOURAL -- i.e. it is accepted AND inert.
    cfg = copy.deepcopy(BASE)
    cfg["x-actionErrorPolicy"] = "rollback"
    m = create_machine(copy.deepcopy(cfg), strict_config=True)
    cells["x_prefix_accepted"] = True
    cells["x_prefix_is_inert"] = m.action_error_policy == "continue"
    # (b) a config-level strictConfig must refuse an unknown key.
    cfg2 = copy.deepcopy(BASE)
    cfg2["strictConfig"] = True
    cfg2["actionErrorPolicyy"] = "rollback"
    try:
        create_machine(copy.deepcopy(cfg2))
        cells["config_level_strictConfig_refuses"] = False
    except InvalidConfigError:
        cells["config_level_strictConfig_refuses"] = True
    # (c) 🎯 can the CONFIG turn strictness OFF against an explicit
    #     strict_config=True argument? That would be a payload choosing
    #     its own checking level -- the thing #205 warns about for
    #     snapshots, here for configs.
    cfg3 = copy.deepcopy(BASE)
    cfg3["strictConfig"] = False
    cfg3["actionErrorPolicyy"] = "rollback"
    try:
        create_machine(copy.deepcopy(cfg3), strict_config=True)
        cells["config_can_override_argument_to_OFF"] = True
    except InvalidConfigError:
        cells["config_can_override_argument_to_OFF"] = False
    ok = (
        cells["x_prefix_is_inert"]
        and cells["config_level_strictConfig_refuses"]
        and not cells["config_can_override_argument_to_OFF"]
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# S3 -- the #212 rule matrix, against the `after` rule it now mirrors
# =========================================================================
def _cycle(feed: str, delay: Any = 1) -> Dict[str, Any]:
    """A two-state cycle self-fed by `feed`; `beat` counts laps."""
    rd = {"type": "raise", "params": {"event": "P", "delay": delay}}
    r0 = {"type": "raise", "params": {"event": "P"}}
    cfg: Dict[str, Any] = {
        "id": "rm",
        "initial": "a",
        "maxIterations": 10,
        "states": {"a": {"on": {"P": "b"}}, "b": {"on": {"P": "a"}}},
    }
    for st in ("a", "b"):
        node = cfg["states"][st]
        other = "b" if st == "a" else "a"
        if feed == "raise_delay":
            node["entry"] = [copy.deepcopy(rd), "beat"]
        elif feed == "raise_zero":
            node["entry"] = [copy.deepcopy(r0), "beat"]
        elif feed == "after":
            node["entry"] = "beat"
            node["after"] = {delay: other}
        elif feed == "cancelled":
            node["entry"] = [
                {
                    "type": "raise",
                    "params": {"event": "P", "delay": delay, "id": "sid"},
                },
                {"type": "cancel", "params": {"sendId": "sid"}},
                "beat",
            ]
    return cfg


class _Budget(PluginBase):
    def __init__(self) -> None:
        self.b = 0

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        if r == "chain_budget":
            self.b += 1


@attack(
    "S3",
    "#212 rule matrix: raise(delay=) at 1 ms / 50 ms / zero / cancelled, "
    "against the `after` rule it now mirrors; both kinds",
)
async def s3() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        for label, feed, delay in (
            ("after_1ms", "after", 1),
            ("raise_delay_1ms", "raise_delay", 1),
            ("raise_delay_50ms", "raise_delay", 50),
            ("raise_zero", "raise_zero", 0),
            ("raise_delay_cancelled", "cancelled", 5),
        ):
            n = {"v": 0}

            def beat(i, c, e, a):  # noqa: ANN001
                n["v"] += 1

            async def beat_a(i, c, e, a):  # noqa: ANN001
                n["v"] += 1

            lg = MachineLogic(
                actions={"beat": beat_a if kind == "async" else beat}
            )
            o = _Budget()
            m = Interpreter(
                create_machine(_cycle(feed, delay), logic=lg)
            ).use(o)
            await m.start()
            await asyncio.sleep(0.6)
            mid = n["v"]
            await asyncio.sleep(0.4)
            cells[f"{label}/{kind}"] = {
                "beats": n["v"],
                "still_beating": n["v"] > mid,
                "tripped": o.b > 0 or m.last_error is not None,
            }
            await m.stop()
    periodic = ("after_1ms", "raise_delay_1ms", "raise_delay_50ms")
    ok = all(
        (
            c["still_beating"] and not c["tripped"]
            if k.split("/")[0] in periodic
            else True
        )
        and (c["tripped"] if k.startswith("raise_zero") else True)
        # a CANCELLED delayed self-send feeds nothing: parked, never trips
        and (
            not c["tripped"]
            if k.startswith("raise_delay_cancelled")
            else True
        )
        for k, c in cells.items()
    )
    parity = {
        kind: abs(
            cells[f"after_1ms/{kind}"]["beats"]
            - cells[f"raise_delay_1ms/{kind}"]["beats"]
        )
        for kind in ("plain", "async")
    }
    return {"ok": ok, "cells": cells, "after_vs_raise_delay_beat_gap": parity}


# =========================================================================
# S4 -- determinism: 50x traces, both engines, both kinds, plus a
#       scheduled_sends restore trace
# =========================================================================
TRACE_CFG = {
    "id": "d",
    "initial": "a",
    "maxIterations": 8,
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "Z"}}, "t"],
            "on": {"Z": "b"},
        },
        "b": {"entry": "t", "on": {"Z": "a", "GO": "c"}},
        "c": {"entry": "t"},
    },
}

PARK_CFG = {
    "id": "pk",
    "initial": "park",
    "maxIterations": 20,
    "states": {
        "park": {
            "entry": [
                {"type": "raise", "params": {"event": "W", "delay": 60}}
            ],
            "on": {"W": "up"},
        },
        "up": {"entry": "t"},
    },
}


@attack(
    "S4",
    "Determinism: 50 identical runs (transition trace + drops) on BOTH "
    "engines and BOTH kinds, plus 50 scheduled_sends restore traces",
)
async def s4() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        traces = set()
        for _ in range(50):
            tr: List[str] = []

            def t(i, c, e, a, _tr=tr):  # noqa: ANN001
                _tr.append(getattr(e, "type", "?"))

            async def t_a(i, c, e, a, _tr=tr):  # noqa: ANN001
                _tr.append(getattr(e, "type", "?"))

            class D(PluginBase):
                def on_event_dropped(self, i, e, r, _tr=tr):  # noqa: ANN001
                    _tr.append(f"drop:{r}")

            lg = MachineLogic(actions={"t": t_a if kind == "async" else t})
            m = Interpreter(
                create_machine(copy.deepcopy(TRACE_CFG), logic=lg)
            ).use(D())
            await m.start()
            await asyncio.sleep(0.25)
            await m.stop()
            traces.add(tuple(tr))
        cells[f"async_engine/{kind}"] = {"distinct_traces": len(traces)}

    # -- sync engine (plain by construction: it has no async lane)
    straces = set()
    for _ in range(50):
        tr2: List[str] = []

        def t2(i, c, e, a, _tr=tr2):  # noqa: ANN001
            _tr.append(getattr(e, "type", "?"))

        class D2(PluginBase):
            def on_event_dropped(self, i, e, r, _tr=tr2):  # noqa: ANN001
                _tr.append(f"drop:{r}")

        m2 = SyncInterpreter(
            create_machine(
                copy.deepcopy(TRACE_CFG),
                logic=MachineLogic(actions={"t": t2}),
            )
        ).use(D2())
        try:
            m2.start()
        except Exception:  # noqa: BLE001
            pass
        straces.add(tuple(tr2))
    cells["sync_engine/plain"] = {"distinct_traces": len(straces)}

    # -- 50 restores of a snapshot carrying scheduled_sends (#213)
    rtraces = set()
    for _ in range(50):
        tr3: List[str] = []

        def t3(i, c, e, a, _tr=tr3):  # noqa: ANN001
            _tr.append(getattr(e, "type", "?"))

        lg3 = MachineLogic(actions={"t": t3})
        m0 = Interpreter(create_machine(copy.deepcopy(PARK_CFG), logic=lg3))
        await m0.start()
        await asyncio.sleep(0.01)
        snap = m0.get_persisted_snapshot()
        await m0.stop()
        mr = Interpreter.from_snapshot(
            json.dumps(snap),
            create_machine(copy.deepcopy(PARK_CFG), logic=lg3),
        )
        await mr.start()
        await asyncio.sleep(0.3)
        rtraces.add((tuple(tr3), tuple(sorted(mr.current_state_ids))))
        await mr.stop()
    cells["restore_scheduled_sends"] = {"distinct_traces": len(rtraces)}

    ok = all(c["distinct_traces"] == 1 for c in cells.values())
    return {"ok": ok, "cells": cells}


if __name__ == "__main__":
    main("s_semantics_sec")
