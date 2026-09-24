"""SEMANTICS @ 19cb1f1 -- SCXML matrices, determinism, security.

S1  SCXML §6.1 `statesToInvoke` matrix (#204): a state entered AND exited
    within one macrostep never submits its service, via four exit routes --
    `always` roll-forward, `actionErrorPolicy: "rollback"`, a parallel
    sibling reaching `final`, and a history re-entry -- on both engines and
    both service kinds.
S2  `after`-provenance matrix (#203): only an engine-minted `AfterEvent`
    drives an `after` transition; public class / import path / `type(held)`
    / `_replace` / pickle / snapshot `"engine": true` sweep.
S3  50x identical-trace determinism, both engines, both kinds, including
    stranded reports; plus a PYTHONHASHSEED sweep in child processes.
S4  Receipt 6-way matrix including a step that stranded an invocation.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import pickle
import subprocess
import sys
import traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    AfterEvent,
    Event,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.events import is_system_event, restore_event
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

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
            rec["detail"] = {
                "exc": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc()[-1500:],
            }
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:4} {a['title'][:92]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1400])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


class Trace(PluginBase):
    def __init__(self) -> None:
        self.seq: List[Any] = []

    def on_transition(self, i, frm, to, ev):  # noqa: ANN001
        self.seq.append(("t", tuple(sorted(to))))

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.seq.append(("drop", getattr(e, "type", None), r))

    def on_invocation_stranded(self, i, sid, iid, err):  # noqa: ANN001
        self.seq.append(("stranded", sid, iid))


# =========================================================================
# S1 -- SCXML 6.1 `statesToInvoke` matrix (#204)
# =========================================================================
ROUTES: Dict[str, Dict[str, Any]] = {
    # roll FORWARD: an `always` exits the invoking state in the same step
    "always": {
        "id": "m", "initial": "a",
        "states": {
            "a": {"on": {"GO": "inv"}},
            "inv": {
                "invoke": {"src": "svc", "id": "s1", "onDone": "d"},
                "always": {"target": "z"},
            },
            "z": {}, "d": {},
        },
    },
    # roll BACK: a failing entry action under `rollback` undoes the entry
    "rollback": {
        "id": "m", "initial": "a", "actionErrorPolicy": "rollback",
        "states": {
            "a": {"on": {"GO": "inv"}},
            "inv": {
                "entry": "boom",
                "invoke": {"src": "svc", "id": "s1", "onDone": "d"},
            },
            "d": {},
        },
    },
    # a PARALLEL sibling reaching `final` completes the region and exits
    "parallel_final": {
        "id": "m", "initial": "a",
        "states": {
            "a": {"on": {"GO": "p"}},
            "p": {
                "type": "parallel",
                "onDone": "z",
                "states": {
                    "r1": {
                        "initial": "x",
                        "states": {
                            "x": {
                                "invoke": {"src": "svc", "id": "s1",
                                           "onDone": "f"},
                                "always": {"target": "f"},
                            },
                            "f": {"type": "final"},
                        },
                    },
                    "r2": {
                        "initial": "y",
                        "states": {
                            "y": {"always": {"target": "g"}},
                            "g": {"type": "final"},
                        },
                    },
                },
            },
            "z": {},
        },
    },
    # HISTORY re-entry that immediately rolls forward out again
    "history": {
        "id": "m", "initial": "a",
        "states": {
            "a": {"on": {"GO": "p"}},
            "p": {
                "initial": "h",
                "states": {
                    "h": {"type": "history", "history": "shallow"},
                    "x": {
                        "invoke": {"src": "svc", "id": "s1", "onDone": "y"},
                        "always": {"target": "y"},
                    },
                    "y": {},
                },
                "on": {"BACK": "a"},
            },
        },
    },
}


@attack("S1", "SCXML 6.1 statesToInvoke matrix: a state entered AND exited "
              "in one macrostep NEVER submits its service -- always / "
              "rollback / parallel-sibling-final / history, both engines, "
              "both kinds")
async def s1() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for route, cfg in ROUTES.items():
        for kind in ("plain", "async"):
            hit = {"n": 0}

            def svc(i, c, e):  # noqa: ANN001
                hit["n"] += 1
                return 1

            async def svca(i, c, e):  # noqa: ANN001
                hit["n"] += 1
                await asyncio.sleep(0)
                return 1

            def boom(i, c, e, a):  # noqa: ANN001
                raise RuntimeError("entry failed")

            async def boom_a(i, c, e, a):  # noqa: ANN001
                raise RuntimeError("entry failed")

            lg = MachineLogic(
                services={"svc": svca if kind == "async" else svc},
                actions={"boom": boom_a if kind == "async" else boom},
            )
            # async engine
            it = await Interpreter(
                create_machine(copy.deepcopy(cfg), logic=lg)
            ).start()
            try:
                await it.send("GO")
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.15)
            a_state = sorted(it.current_state_ids)
            a_hits = hit["n"]
            await it.stop()
            # sync engine
            hit["n"] = 0
            s = SyncInterpreter(
                create_machine(copy.deepcopy(cfg), logic=lg)
            )
            s.start()
            try:
                s.send("GO")
            except Exception:  # noqa: BLE001
                pass
            s_state = sorted(s.current_state_ids)
            s_hits = hit["n"]
            s.stop()
            cells[f"{route}/{kind}"] = {
                "async_engine": {"submitted": a_hits, "state": a_state},
                "sync_engine": {"submitted": s_hits, "state": s_state},
            }
    bad = [
        k
        for k, v in cells.items()
        if v["async_engine"]["submitted"] or v["sync_engine"]["submitted"]
    ]
    return {"ok": not bad, "service_submitted_despite_same_step_exit": bad,
            "cells": cells}


# =========================================================================
# S2 -- `after`-provenance forgery matrix (#203)
# =========================================================================
AFTER_M = {
    "id": "t",
    "strict": True,
    "initial": "a",
    "states": {
        "a": {"after": {60000: {"target": "b"}}, "on": {"E": "b"}},
        "b": {},
    },
}


@attack("S2", "after-provenance matrix (#203): only a genuinely "
              "engine-minted-in-this-process AfterEvent fires a 60 s timer "
              "-- public class / import path / type(held) / _replace / "
              "pickle / deepcopy / snapshot flag")
async def s2() -> Dict[str, Any]:
    from xstate_statemachine import events as _ev

    TYPE = "after.60000.t.a"
    genuine = _ev.engine_after(TYPE, None, None)
    surfaces: Dict[str, Any] = {
        "public_AfterEvent": AfterEvent(TYPE, None, None),
        "private_import_path": _ev._EngineAfter(TYPE, None, None),
        "type_of_held_instance": type(genuine)(TYPE, None, None),
        "replace_of_genuine": genuine._replace(type=TYPE),
        "pickle_roundtrip_of_genuine": pickle.loads(pickle.dumps(genuine)),
        "deepcopy_of_genuine": copy.deepcopy(genuine),
        "restore_engine_true": restore_event(
            {"kind": "after", "type": TYPE, "engine": True}
        ),
        "restore_no_flag": restore_event({"kind": "after", "type": TYPE}),
    }
    flags = {k: is_system_event(v) for k, v in surfaces.items()}
    # End-to-end: does each surface actually FIRE the 60 s transition?
    fired: Dict[str, Any] = {}
    for name, ev in surfaces.items():
        it = await Interpreter(
            create_machine(copy.deepcopy(AFTER_M))
        ).start()
        try:
            await it.send(ev)
        except Exception as exc:  # noqa: BLE001
            fired[name] = f"refused:{type(exc).__name__}"
            await it.stop()
            continue
        await asyncio.sleep(0.05)
        fired[name] = "t.b" in it.current_state_ids
        await it.stop()
    # A surface reached WITHOUT holding an engine instance must not fire.
    cold = ("public_AfterEvent", "private_import_path", "restore_no_flag")
    forged_fired = [k for k in cold if fired.get(k) is True]
    # Surfaces reached only by holding a genuine instance (copying is the
    # legitimate case, #138) or by writing a trusted snapshot record.
    warm_fired = [
        k
        for k in surfaces
        if k not in cold and fired.get(k) is True
    ]
    return {
        "ok": not forged_fired,
        "cold_surfaces_that_fired_60s_timer": forged_fired,
        "warm_or_trusted_surfaces_that_fired": warm_fired,
        "is_system_event": flags,
        "fired": fired,
    }


# =========================================================================
# S3 -- 50x identical traces, both engines, both kinds, incl. stranded
# =========================================================================
DET = {
    "id": "r",
    "initial": "w",
    "maxIterations": 6,
    "states": {
        "w": {"on": {"GO": "a"}},
        "a": {"invoke": {"src": "svc", "id": "sa", "onDone": "b"}},
        "b": {"invoke": {"src": "svc", "id": "sb", "onDone": "a"}},
    },
}


@attack("S3", "50x identical traces (transitions + drops + stranded) on both "
              "engines and both kinds; plus a PYTHONHASHSEED sweep")
async def s3() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        def svc(i, c, e):  # noqa: ANN001
            return 1

        async def svca(i, c, e):  # noqa: ANN001
            await asyncio.sleep(0)
            return 1

        lg = MachineLogic(services={"svc": svca if kind == "async" else svc})
        traces = set()
        for _ in range(50):
            t = Trace()
            it = await Interpreter(
                create_machine(copy.deepcopy(DET), logic=lg)
            ).use(t).start()
            await it.send("GO")
            await asyncio.sleep(0.9)
            traces.add(json.dumps(t.seq, default=str))
            await it.stop()
        out[f"async_engine/{kind}"] = {
            "distinct_traces": len(traces),
            "sample": json.loads(sorted(traces)[0])[-3:],
        }
    # sync engine (plain def only)
    def svc(i, c, e):  # noqa: ANN001
        return 1

    lg = MachineLogic(services={"svc": svc})
    straces = set()
    for _ in range(50):
        t = Trace()
        s = SyncInterpreter(
            create_machine(copy.deepcopy(DET), logic=lg)
        ).use(t)
        s.start()
        try:
            s.send("GO")
        except Exception:  # noqa: BLE001
            pass
        straces.add(json.dumps(t.seq, default=str))
        s.stop()
    out["sync_engine/plain"] = {
        "distinct_traces": len(straces),
        "sample": json.loads(sorted(straces)[0])[-3:],
    }
    # PYTHONHASHSEED sweep in child processes
    child = (
        "import asyncio,copy,json,logging;"
        "logging.disable(logging.CRITICAL);"
        "from xstate_statemachine import *;"
        "from xstate_statemachine.plugins import PluginBase;"
        f"DET={DET!r};"
        "seq=[]\n"
        "class T(PluginBase):\n"
        "    def on_transition(s,i,f,t,e): seq.append(('t',tuple(sorted(t))))\n"
        "    def on_event_dropped(s,i,e,r): seq.append(('d',e.type,r))\n"
        "    def on_invocation_stranded(s,i,a,b,c): seq.append(('s',a,b))\n"
        "async def go():\n"
        "    lg=MachineLogic(services={'svc':lambda i,c,e:1})\n"
        "    it=await Interpreter(create_machine(copy.deepcopy(DET),"
        "logic=lg)).use(T()).start()\n"
        "    await it.send('GO'); await asyncio.sleep(0.9); await it.stop()\n"
        "asyncio.run(go()); print(json.dumps(seq))\n"
    )
    seeds, hash_traces = ["0", "1", "12345", "99999"], set()
    for sd in seeds:
        env = dict(os.environ, PYTHONHASHSEED=sd, PYTHONIOENCODING="utf-8")
        p = subprocess.run(
            [sys.executable, "-c", child], capture_output=True,
            text=True, env=env, timeout=60,
        )
        hash_traces.add(p.stdout.strip().splitlines()[-1] if p.stdout else
                        f"ERR:{p.stderr[-200:]}")
    out["hashseed_sweep"] = {
        "seeds": seeds,
        "distinct_traces": len(hash_traces),
    }
    ok = all(
        v["distinct_traces"] == 1
        for k, v in out.items()
        if "distinct_traces" in v
    )
    return {"ok": ok, "cells": out}


# =========================================================================
# S4 -- receipt 6-way matrix, including a step that STRANDED an invocation
# =========================================================================
RCPT = {
    "id": "q",
    "initial": "a",
    "maxIterations": 6,
    "states": {
        "a": {
            "on": {
                "OK": "b",
                "DENY": {"target": "b", "cond": "never"},
                "BOOM": {"target": "b", "actions": "boom"},
                "STRAND": "inv",
            }
        },
        "b": {},
        "inv": {"invoke": {"src": "svc", "id": "si", "onDone": "inv2"}},
        "inv2": {"invoke": {"src": "svc", "id": "si2", "onDone": "inv"}},
    },
}


@attack("S4", "Receipt 6-way matrix: clean / no-handler / guard-denied / "
              "action-raised / stopped / STRANDED-by-chain-cut, both kinds")
async def s4() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        def svc(i, c, e):  # noqa: ANN001
            return 1

        async def svca(i, c, e):  # noqa: ANN001
            await asyncio.sleep(0)
            return 1

        def boom(i, c, e, a):  # noqa: ANN001
            raise RuntimeError("boom")

        async def boom_a(i, c, e, a):  # noqa: ANN001
            raise RuntimeError("boom")

        lg = MachineLogic(
            services={"svc": svca if kind == "async" else svc},
            actions={"boom": boom_a if kind == "async" else boom},
            guards={"never": lambda c, e: False},
        )
        for case, ev in (
            ("clean", "OK"),
            ("no_handler", "NOPE"),
            ("guard_denied", "DENY"),
            ("action_raised", "BOOM"),
            ("stranded", "STRAND"),
        ):
            t = Trace()
            it = await Interpreter(
                create_machine(copy.deepcopy(RCPT), logic=lg)
            ).use(t).start()
            try:
                r = await it.send(ev, wait=True)
                rec = {
                    "state_ids": sorted(r.state_ids),
                    "changed": r.changed,
                    "error": type(r.error).__name__ if r.error else None,
                    "deferred": r.deferred,
                    "denied": r.denied,
                }
            except Exception as exc:  # noqa: BLE001
                rec = {"raised": f"{type(exc).__name__}: {exc}"[:120]}
            await asyncio.sleep(0.6)
            rec["stranded_hook"] = [
                x for x in t.seq if x[0] == "stranded"
            ]
            rec["dormant"] = it.has_dormant_invocations
            rec["last_error"] = (
                type(it.last_error).__name__ if it.last_error else None
            )
            rec["err_stranded"] = list(
                getattr(it.last_error, "stranded", ()) or ()
            )
            cells[f"{case}/{kind}"] = rec
            await it.stop()
        # stopped-interpreter receipt
        it = await Interpreter(
            create_machine(copy.deepcopy(RCPT), logic=lg)
        ).start()
        await it.stop()
        try:
            r = await it.send("OK", wait=True)
            cells[f"stopped/{kind}"] = {
                "error": type(r.error).__name__ if r.error else None,
                "changed": r.changed,
            }
        except Exception as exc:  # noqa: BLE001
            cells[f"stopped/{kind}"] = {
                "raised": f"{type(exc).__name__}"
            }
    bad = []
    for k, v in cells.items():
        case = k.split("/")[0]
        if case == "clean" and (v.get("error") or not v.get("changed")):
            bad.append((k, "clean step not success-shaped"))
        if case == "guard_denied" and not v.get("denied"):
            bad.append((k, "denied flag missing"))
        if case == "no_handler" and (v.get("denied") or v.get("changed")):
            bad.append((k, "no-handler receipt mislabelled"))
        if case == "action_raised" and not v.get("error"):
            bad.append((k, "action failure not on receipt"))
        if case == "stranded" and not (
            v.get("stranded_hook") and v.get("err_stranded")
        ):
            bad.append((k, "stranded not reported"))
        if case == "stopped" and not (v.get("error") or v.get("raised")):
            bad.append((k, "stopped interpreter reported ok"))
    return {"ok": not bad, "violations": bad, "cells": cells}


if __name__ == "__main__":
    main("s_semantics_sec")
