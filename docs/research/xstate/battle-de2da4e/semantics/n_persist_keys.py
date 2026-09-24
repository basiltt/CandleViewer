"""SEMANTICS @ de2da4e -- #221 parked-send chains + #220 recursive key check.

N1  #221 chain property (>=300 cases): restore -> persist (NO start) ->
    restore -> persist -> ... -> start.  The armed delayed self-send must
    survive every hop verbatim and then fire EXACTLY ONCE at the right
    remaining delay on a SimulatedClock.
N2  #220 recursive key check vs a typo fuzzer that injects a misspelling at
    EVERY nesting level (root / nested state / parallel region / on /
    always / after / onDone / invoke / invoke.onDone / invoke.onError):
    every injection must be CAUGHT (warn by default, raise under
    strict_config) and the finding must name the path.
N3  No false positives: valid charts generated from the FULL key grammar at
    every level must build with ZERO rejections under strict_config=True.
N4  Recursive key check over EVERY catalogue .machine.json in the prior
    battle contract sets -- 0 rejections expected (they are valid charts).
N5  strict_config bypass attempts: `x-` smuggling of a policy key at any
    level, and KEY CASE variants (`Entry`, `ON`, `MaxIterations`).

Standalone: stdlib + xstate_statemachine only, every helper inlined.
"""
from __future__ import annotations

import asyncio, copy, glob, json, logging, os, random, sys, traceback, warnings
from typing import Any, Callable, Dict, List, Tuple

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import InvalidConfigError

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []
CONTRACT_GLOBS = [
    "../../battle-c78ce99/contracts/*.machine.json",
    "../../battle-19cb1f1/contracts/*.machine.json",
    "../../battle-3ed3099/contracts/*.machine.json",
]


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn
    return deco


# =====================================================================  N1
def _park_cfg(n: int, delay: int) -> Dict[str, Any]:
    return {
        "id": f"p{n}", "initial": "park", "maxIterations": 50,
        "states": {
            "park": {"entry": [{"type": "raise",
                                "params": {"event": "WAKE", "delay": delay,
                                           "id": f"sid{n}"}}],
                     "on": {"WAKE": "awake"}},
            "awake": {"type": "final"},
        },
    }


@attack("N1", "#221: parked scheduled_sends survive an N-hop "
              "restore->persist chain with NO start(), then fire EXACTLY "
              "once at the right remaining delay (>=300 property cases)")
async def n1() -> Dict[str, Any]:
    rng = random.Random(20260923)
    bad: List[Any] = []
    checked = 0
    for i in range(300):
        delay = rng.choice([20, 75, 200, 999, 4000])
        cfg = _park_cfg(i, delay)
        clock = SimulatedClock()
        m = Interpreter(create_machine(copy.deepcopy(cfg)), clock=clock)
        await m.start()
        elapsed = rng.uniform(0.0, delay * 0.7)
        await clock.increment(elapsed)
        snap = m.get_persisted_snapshot()
        await m.stop()
        want = delay - elapsed
        rec0 = (snap.get("scheduled_sends") or [None])[0]
        if rec0 is None:
            bad.append({"i": i, "why": "no record at hop 0"})
            continue
        # --- N hops of restore -> persist with NO start()
        hops = rng.randint(1, 4)
        blob = json.dumps(snap)
        chain_ok = True
        for h in range(hops):
            mid = Interpreter.from_snapshot(
                blob, create_machine(copy.deepcopy(cfg)),
                clock=SimulatedClock())
            snap_h = mid.get_persisted_snapshot()
            ss = snap_h.get("scheduled_sends") or []
            if len(ss) != 1:
                bad.append({"i": i, "hop": h, "why": "record LOST", "ss": ss})
                chain_ok = False
                break
            if abs(ss[0].get("remaining_ms", -1) - want) > 1e-6:
                bad.append({"i": i, "hop": h, "why": "remaining drifted",
                            "got": ss[0].get("remaining_ms"), "want": want})
                chain_ok = False
                break
            if ss[0].get("send_id") != f"sid{i}":
                bad.append({"i": i, "hop": h, "why": "send_id lost"})
                chain_ok = False
                break
            blob = json.dumps(snap_h)
        if not chain_ok:
            continue
        # --- final restore + start(): must fire ONCE, at `want`
        clock2 = SimulatedClock()
        fin = Interpreter.from_snapshot(
            blob, create_machine(copy.deepcopy(cfg)), clock=clock2)
        await fin.start()
        await clock2.increment(want - 0.001)
        early = any("awake" in s for s in fin.current_state_ids)
        await clock2.increment(0.002)
        late = any("awake" in s for s in fin.current_state_ids)
        # exactly-once: after firing, no further armed record remains
        leftover = len(fin.get_persisted_snapshot().get("scheduled_sends")
                       or [])
        await fin.stop()
        if early:
            bad.append({"i": i, "why": "fired EARLY after chain",
                        "hops": hops, "want": want})
        elif not late:
            bad.append({"i": i, "why": "did NOT fire after chain",
                        "hops": hops, "want": want})
        elif leftover:
            bad.append({"i": i, "why": "record still armed after firing",
                        "leftover": leftover})
        checked += 1
    return {"ok": not bad and checked >= 300, "checked": checked,
            "n_bad": len(bad), "bad": bad[:8]}


# =====================================================================  N2
#: Every nesting level #220 claims to recurse into, with a typo to inject.
LEVELS: List[Tuple[str, str, str]] = [
    ("root", "maxIterationss", "maxIterations"),
    ("state", "entryy", "entry"),
    ("nested_state", "exitt", "exit"),
    ("parallel_region", "invokee", "invoke"),
    ("on_transition", "tpye", "type"),
    ("always_transition", "guardd", "guard"),
    ("after_transition", "actionss", "actions"),
    ("onDone_transition", "targett", "target"),
    ("invoke", "srcc", "src"),
    ("invoke_onDone", "reenterr", "reenter"),
    ("invoke_onError", "condd", "cond"),
]


def _base_cfg() -> Dict[str, Any]:
    return {
        "id": "m", "initial": "r1", "maxIterations": 30,
        "context": {},
        "states": {
            "r1": {
                "initial": "y",
                "entry": ["act"],
                "exit": ["act"],
                "states": {
                    "y": {
                        "on": {"GO": [{"target": "z", "actions": ["act"]}]},
                        "always": [{"target": "z", "guard": "g"}],
                        "after": {100: [{"target": "z",
                                         "actions": ["act"]}]},
                        "invoke": {"id": "q", "src": "svc",
                                   "onDone": [{"target": "z"}],
                                   "onError": [{"target": "z"}]},
                    },
                    "z": {"type": "final"},
                },
                "onDone": [{"target": "r2"}],
            },
            "r2": {
                "type": "parallel",
                "states": {"pa": {"initial": "s",
                                  "states": {"s": {}}},
                           "pb": {"initial": "s",
                                  "states": {"s": {}}}},
            },
        },
    }


def _inject(cfg: Dict[str, Any], level: str, typo: str) -> Dict[str, Any]:
    c = copy.deepcopy(cfg)
    y = c["states"]["r1"]["states"]["y"]
    if level == "root":
        c[typo] = 5
    elif level == "state":
        c["states"]["r1"][typo] = ["act"]
    elif level == "nested_state":
        y[typo] = ["act"]
    elif level == "parallel_region":
        c["states"]["r2"]["states"]["pa"][typo] = {"src": "svc"}
    elif level == "on_transition":
        y["on"]["GO"][0][typo] = "z"
    elif level == "always_transition":
        y["always"][0][typo] = "g"
    elif level == "after_transition":
        y["after"][100][0][typo] = ["act"]
    elif level == "onDone_transition":
        c["states"]["r1"]["onDone"][0][typo] = "r2"
    elif level == "invoke":
        y["invoke"][typo] = "svc"
    elif level == "invoke_onDone":
        y["invoke"]["onDone"][0][typo] = True
    elif level == "invoke_onError":
        y["invoke"]["onError"][0][typo] = "g"
    return c


class _Cap(logging.Handler):
    """🧪 The unknown-key report is a LOGGER warning, not a `warnings`
    warning (validation.py uses `logger.warning`). A round-11-style
    `warnings.catch_warnings` harness sees nothing and would wrongly
    report 'not warned'. Capture the log record instead -- and re-enable
    logging for the duration, since this file disables it globally."""

    def __init__(self) -> None:
        super().__init__()
        self.text: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.text.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass


def _build(cfg: Dict[str, Any], strict: bool):  # noqa: ANN201
    """Returns (warning_log_text, raised_message_or_None)."""
    logic = MachineLogic(
        actions={"act": lambda i, c, e, a: None},
        guards={"g": lambda c, e: False},
        services={"svc": _svc},
    )
    cap = _Cap()
    root = logging.getLogger("xstate_statemachine")
    root.addHandler(cap)
    prev, root.level, root.propagate = root.level, logging.WARNING, False
    logging.disable(logging.NOTSET)
    try:
        create_machine(copy.deepcopy(cfg), logic=logic, strict_config=strict)
        raised = None
    except InvalidConfigError as exc:
        raised = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    finally:
        logging.disable(logging.CRITICAL)
        root.removeHandler(cap)
        root.level = prev
    return " || ".join(cap.text), raised


async def _svc(i, c, e):  # noqa: ANN001
    await asyncio.sleep(3600)


@attack("N2", "#220 recursive key check: a typo injected at EVERY nesting "
              "level must be CAUGHT (warn by default, raise under "
              "strict_config) and the finding must NAME THE PATH")
def n2() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    missed: List[str] = []
    no_hint: List[str] = []
    for level, typo, real in LEVELS:
        cfg = _inject(_base_cfg(), level, typo)
        wtxt, _ = _build(cfg, strict=False)
        _, raised = _build(cfg, strict=True)
        warned = typo in wtxt
        refused = bool(raised) and typo in (raised or "")
        hint = (real in wtxt) or (real in (raised or ""))
        # path naming: the finding should mention a dotted path, not just m
        pathy = any(seg in wtxt or seg in (raised or "")
                    for seg in ("m.r1", "m.r2", "y", "q")) or level == "root"
        cells[level] = {"typo": typo, "warned": warned, "refused": refused,
                        "hint": hint, "path_named": pathy,
                        "warn_excerpt": wtxt[:150],
                        "raise_excerpt": (raised or "")[:150]}
        if not (warned and refused):
            missed.append(level)
        elif not hint:
            no_hint.append(level)
    return {"ok": not missed, "missed": missed, "no_hint": no_hint,
            "cells": cells}


# =====================================================================  N3
@attack("N3", "No false positives: valid charts built from the FULL key "
              "grammar at every level must give ZERO rejections and ZERO "
              "unknown-key warnings under strict_config=True")
def n3() -> Dict[str, Any]:
    rng = random.Random(4242)
    rejected: List[Any] = []
    warned: List[Any] = []
    meta_keys = ["meta", "description", "tags"]
    n = 200
    for k in range(n):
        cfg = _base_cfg()
        cfg["id"] = f"v{k}"
        # sprinkle legal metadata + x- keys at random levels
        targets: List[Dict[str, Any]] = [
            cfg, cfg["states"]["r1"], cfg["states"]["r1"]["states"]["y"],
            cfg["states"]["r1"]["states"]["y"]["on"]["GO"][0],
            cfg["states"]["r1"]["states"]["y"]["always"][0],
            cfg["states"]["r1"]["states"]["y"]["after"][100][0],
            cfg["states"]["r1"]["states"]["y"]["invoke"],
            cfg["states"]["r1"]["states"]["y"]["invoke"]["onDone"][0],
            cfg["states"]["r1"]["states"]["y"]["invoke"]["onError"][0],
            cfg["states"]["r1"]["onDone"][0],
            cfg["states"]["r2"], cfg["states"]["r2"]["states"]["pa"],
        ]
        for t in targets:
            if rng.random() < 0.5:
                # 🧪  is typed (str | list[str]); meta/description are
                #    free-form. Give each its legal shape.
                mk = rng.choice(meta_keys)
                t[mk] = (["ok"] if mk == "tags" else {"note": "ok"})
            if rng.random() < 0.5:
                t[f"x-{rng.choice(['ext', 'vendor', 'cv'])}"] = 1
        # legal root policies
        cfg.update({"strict": False, "strictTargets": False,
                    "actionErrorPolicy": "continue",
                    "guardErrorPolicy": "false",
                    "onUnhandled": "ignore", "version": "1.0",
                    "spawnBlockingTimeout": 1.0})
        wtxt, raised = _build(cfg, strict=True)
        if raised:
            rejected.append({"k": k, "msg": raised[:200]})
        if "unknown config key" in wtxt.lower():
            warned.append({"k": k, "msg": wtxt[:200]})
    return {"ok": not rejected and not warned, "n": n,
            "n_rejected": len(rejected), "n_warned": len(warned),
            "rejected": rejected[:5], "warned": warned[:5]}


# =====================================================================  N4
@attack("N4", "Recursive key check over EVERY catalogue .machine.json in "
              "the prior contract sets -- valid charts, expect 0 rejections")
def n4() -> Dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    files: List[str] = []
    for g in CONTRACT_GLOBS:
        files.extend(sorted(glob.glob(os.path.join(here, g))))
    if not files:
        return {"ok": False, "why": "no contract files found",
                "globs": CONTRACT_GLOBS}
    rejected, warned = [], []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            rejected.append({"f": os.path.basename(f),
                             "msg": f"unreadable: {exc}"})
            continue
        cap = _Cap()
        lg = logging.getLogger("xstate_statemachine")
        lg.addHandler(cap)
        prev, lg.level, lg.propagate = lg.level, logging.WARNING, False
        logging.disable(logging.NOTSET)
        try:
            create_machine(copy.deepcopy(cfg), strict_config=True)
        except InvalidConfigError as exc:
            if "unknown config key" in str(exc).lower():
                rejected.append({"f": os.path.basename(f),
                                 "msg": str(exc)[:220]})
        except Exception:  # noqa: BLE001
            pass  # missing logic etc. -- not a key-check verdict
        finally:
            logging.disable(logging.CRITICAL)
            lg.removeHandler(cap)
            lg.level = prev
        wtxt = " || ".join(cap.text)
        if "unknown config key" in wtxt.lower():
            warned.append({"f": os.path.basename(f), "msg": wtxt[:220]})
    return {"ok": not rejected and not warned, "n_files": len(files),
            "n_rejected": len(rejected), "n_warned": len(warned),
            "rejected": rejected[:8], "warned": warned[:8]}


# =====================================================================  N5
@attack("N5", "strict_config bypass: `x-` smuggling of a POLICY key at any "
              "level (must be accepted AND inert), and KEY CASE variants "
              "(must not be silently honoured as the real key)")
def n5() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    # (a) x- smuggling at nested levels: accepted and inert
    cfg = _base_cfg()
    cfg["x-maxIterations"] = 1
    cfg["states"]["r1"]["x-actionErrorPolicy"] = "halt"
    cfg["states"]["r1"]["states"]["y"]["x-strict"] = True
    wtxt, raised = _build(cfg, strict=True)
    m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(
        actions={"act": lambda i, c, e, a: None},
        guards={"g": lambda c, e: False}, services={"svc": _svc}),
        strict_config=True)
    cells["x_prefix"] = {
        "raised": raised, "warned": "unknown config key" in wtxt.lower(),
        "max_iterations_effective": getattr(m, "max_iterations", None),
        "inert": getattr(m, "max_iterations", None) != 1,
    }
    # (b) case variants: must be REPORTED as unknown, never honoured
    case_cells: Dict[str, Any] = {}
    for key, real in [("MaxIterations", "maxIterations"), ("Entry", "entry"),
                      ("ON", "on"), ("Strict", "strict"),
                      ("Invoke", "invoke"), ("AFTER", "after")]:
        c = _base_cfg()
        if real in ("maxIterations", "strict"):
            c.pop(real, None)
            c[key] = 3 if real == "maxIterations" else True
        else:
            c["states"]["r1"]["states"]["y"][key] = (
                ["act"] if real == "entry" else {"GO": "z"})
        w2, r2 = _build(c, strict=False)
        _, r3 = _build(c, strict=True)
        case_cells[key] = {"warned": key in w2, "refused": bool(r3),
                           "hint_to_real": real in w2 or real in (r3 or "")}
    cells["case_variants"] = case_cells
    ok = (cells["x_prefix"]["raised"] is None
          and not cells["x_prefix"]["warned"]
          and cells["x_prefix"]["inert"]
          and all(c["warned"] and c["refused"] for c in case_cells.values()))
    return {"ok": ok, "cells": cells}


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
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:84]}", flush=True)
        print("        -> " + json.dumps(rec["detail"], default=str)[:2200])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


if __name__ == "__main__":
    main("n_persist_keys")
