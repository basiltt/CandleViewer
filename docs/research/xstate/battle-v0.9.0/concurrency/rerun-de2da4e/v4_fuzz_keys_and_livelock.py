"""v4 (@de2da4e) -- STANDALONE. #220 recursive key check: fuzz at EVERY
nesting level, false-positive test on generated VALID grammar, and
strict_config bypass attempts.

F1  Typo fuzzer: inject one mutated key at a chosen nesting level --
    root / nested state / deep nested state / parallel region / `on`
    transition body / `after` transition body / `always` body / `onDone`
    body / invoke body / invoke onDone body. Under strict_config=True
    EVERY injection must be refused, and the finding must NAME THE PATH.
F2  False-positive test: generate valid charts from the full key grammar
    (KNOWN_ROOT/STATE/TRANSITION/INVOKE key sets, every key at every
    legal position) and assert 0 rejections under strict_config=True.
F3  Livelock fuzzer: >=500 configs x kinds x engines under the #212
    rule, two-sided oracle (consecutive zero-delay hops vs maxIterations).
S1  strict_config bypass attempts: `x-` prefix smuggling a policy key,
    key CASE variants (`Strict`, `STRICT`, `strictconfig`), unicode
    look-alikes, whitespace padding. A smuggled key must either be
    REFUSED or be INERT -- it must never take effect silently.

Run: python v4_fuzz_keys_and_livelock.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import sys
import time
from typing import Any, Dict, List, Tuple

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    InvalidConfigError,
    UnknownEventError,
)
from xstate_statemachine.validation import (
    KNOWN_INVOKE_KEYS,
    KNOWN_ROOT_KEYS,
    KNOWN_STATE_KEYS,
    KNOWN_TRANSITION_KEYS,
)

FAILS: List[str] = []
OUT: Dict[str, Any] = {}
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {
        "probe": name,
        "py": ".".join(map(str, sys.version_info[:3])),
        **data,
    }
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


class WarnTrap(logging.Handler):
    """Capture library WARNINGs so 'warned but not refused' is visible."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.msgs: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        self.msgs.append(record.getMessage())


def build(cfg: Dict[str, Any], strict_config: bool) -> Tuple[str, str]:
    """Return (outcome, message). outcome in ACCEPTED / REFUSED / ERROR."""
    trap = WarnTrap()
    root = logging.getLogger("xstate_statemachine")
    root.addHandler(trap)
    prev = root.level
    root.setLevel(logging.WARNING)
    try:
        create_machine(copy.deepcopy(cfg), logic=MachineLogic(),
                       strict_config=strict_config)
        warned = [m for m in trap.msgs if "unknown config key" in m]
        return ("ACCEPTED", warned[0] if warned else "")
    except InvalidConfigError as exc:
        return ("REFUSED", str(exc))
    except Exception as exc:  # noqa: BLE001
        return ("ERROR", type(exc).__name__ + ": " + str(exc)[:200])
    finally:
        root.removeHandler(trap)
        root.setLevel(prev)


# ── F1: one chart with EVERY nesting level the checker claims to cover ──
def host_chart() -> Dict[str, Any]:
    return {
        "id": "m",
        "initial": "r1",
        "context": {"n": 0},
        "states": {
            "r1": {
                "initial": "x",
                "on": {"E": {"target": "r2", "actions": ["noop"]}},
                "after": {"50": {"target": "r2"}},
                "always": [{"target": "r2", "guard": "never"}],
                "invoke": {
                    "id": "svc",
                    "src": "work",
                    "onDone": {"target": "r2"},
                    "onError": {"target": "r2"},
                },
                "states": {
                    "x": {
                        "on": {"F": {"target": "y"}},
                        "states": {},
                    },
                    "y": {"type": "final"},
                },
                "onDone": {"target": "r2"},
            },
            "r2": {
                "type": "parallel",
                "states": {
                    "p1": {"initial": "a", "states": {"a": {}}},
                    "p2": {"initial": "b", "states": {"b": {}}},
                },
            },
        },
    }


#: (label, path-to-the-dict-the-typo-goes-in) as a list of navigation steps
INJECTION_SITES: List[Tuple[str, List[Any]]] = [
    ("root", []),
    ("state", ["states", "r1"]),
    ("deep_state", ["states", "r1", "states", "x"]),
    ("parallel_region", ["states", "r2", "states", "p1"]),
    ("parallel_child", ["states", "r2", "states", "p1", "states", "a"]),
    ("on_transition", ["states", "r1", "on", "E"]),
    ("after_transition", ["states", "r1", "after", "50"]),
    ("always_transition", ["states", "r1", "always", 0]),
    ("onDone_transition", ["states", "r1", "onDone"]),
    ("invoke", ["states", "r1", "invoke"]),
    ("invoke_onDone", ["states", "r1", "invoke", "onDone"]),
    ("invoke_onError", ["states", "r1", "invoke", "onError"]),
]

MUTATIONS = [
    lambda k: k + "y",
    lambda k: k + "s",
    lambda k: k[:-1] if len(k) > 3 else k + "z",
    lambda k: k.capitalize(),
    lambda k: k.upper(),
    lambda k: k[:1] + k[2:] if len(k) > 3 else k + "q",
]

SITE_KEYS = {
    "root": sorted(KNOWN_ROOT_KEYS),
    "state": sorted(KNOWN_STATE_KEYS),
    "deep_state": sorted(KNOWN_STATE_KEYS),
    "parallel_region": sorted(KNOWN_STATE_KEYS),
    "parallel_child": sorted(KNOWN_STATE_KEYS),
    "on_transition": sorted(KNOWN_TRANSITION_KEYS),
    "after_transition": sorted(KNOWN_TRANSITION_KEYS),
    "always_transition": sorted(KNOWN_TRANSITION_KEYS),
    "onDone_transition": sorted(KNOWN_TRANSITION_KEYS),
    "invoke": sorted(KNOWN_INVOKE_KEYS),
    "invoke_onDone": sorted(KNOWN_TRANSITION_KEYS),
    "invoke_onError": sorted(KNOWN_TRANSITION_KEYS),
}


def navigate(cfg: Dict[str, Any], steps: List[Any]) -> Any:
    node: Any = cfg
    for s in steps:
        node = node[s]
    return node


def f1_nesting_fuzz(trials_per_site: int = 25) -> Dict[str, Any]:
    rnd = random.Random(4242)
    per_site: Dict[str, Dict[str, Any]] = {}
    missed_all: List[Dict[str, str]] = []
    unpathed: List[Dict[str, str]] = []
    total = 0
    for label, steps in INJECTION_SITES:
        keys = SITE_KEYS[label]
        caught = warned_only = missed = 0
        pathed = 0
        for _ in range(trials_per_site):
            base = rnd.choice(keys)
            bad = rnd.choice(MUTATIONS)(base)
            if bad in keys or bad.startswith("x-"):
                bad = base + "__zz"
            cfg = host_chart()
            navigate(cfg, steps)[bad] = (
                ["noop"] if label.endswith("state") or label == "root" else "r2"
            )
            total += 1
            outcome, msg = build(cfg, strict_config=True)
            if outcome == "REFUSED" and bad in msg:
                caught += 1
                # #220 promises a PATH-NAMED finding, not just the key
                if label == "root" or ("m." in msg or " on[" in msg
                                       or " after[" in msg or " always" in msg
                                       or " invoke[" in msg or " onDone" in msg
                                       or " onError" in msg):
                    pathed += 1
                else:
                    unpathed.append({"site": label, "key": bad,
                                     "msg": msg[:200]})
            else:
                w_outcome, w_msg = build(cfg, strict_config=False)
                if w_outcome == "ACCEPTED" and bad in w_msg:
                    warned_only += 1
                else:
                    missed += 1
                missed_all.append({"site": label, "key": bad,
                                   "strict_outcome": outcome,
                                   "msg": msg[:200]})
        per_site[label] = {"trials": trials_per_site, "caught": caught,
                           "path_named": pathed, "warned_only": warned_only,
                           "missed": missed}
    out = {"sites": len(INJECTION_SITES), "total_trials": total,
           "per_site": per_site, "missed_sample": missed_all[:8],
           "unpathed_sample": unpathed[:5]}
    bad_sites = [k for k, v in per_site.items() if v["caught"] != v["trials"]]
    if bad_sites:
        FAILS.append(f"F1: sites not fully caught under strict_config: "
                     f"{bad_sites}")
    if unpathed:
        FAILS.append(f"F1: {len(unpathed)} findings did not name the path")
    return out


# ── F2: generated VALID grammar -- 0 rejections allowed ──────────────
def valid_value(key: str, rnd: random.Random) -> Any:
    """A legal value for each known key, at a position where it is legal."""
    return {
        "id": "gid",
        "initial": "a",
        "states": {"a": {}, "b": {"type": "final"}},
        # 🧷 a node WITH children may not be atomic/final
        "type": "compound",
        "output": {"k": 1},
        "on": {"E": {"target": "b"}},
        "entry": ["noop"],
        "exit": ["noop"],
        "after": {"100": {"target": "b"}},
        "always": [{"target": "b", "guard": "never"}],
        "invoke": {"id": "s", "src": "work", "onDone": {"target": "b"}},
        "onDone": {"target": "b"},
        "history": "shallow",
        "target": "a",
        "meta": {"m": 1},
        "description": "d",
        "tags": ["t"],
        "context": {"n": 0},
        "version": "1.0.0",
        # 🧷 legal ENUM values (a bad value is a different check; this
        #    probe must isolate the KEY check)
        "actionErrorPolicy": rnd.choice(["continue", "rollback", "fail"]),
        "guardErrorPolicy": rnd.choice(["false", "true", "raise"]),
        "onUnhandled": rnd.choice(["ignore", "defer", "error"]),
        "maxIterations": 25,
        "spawnBlockingTimeout": 5.0,
        "strict": False,
        "strictTargets": True,
        "strictConfig": False,
    }.get(key, {"m": 1})


def f2_valid_grammar(trials: int = 120) -> Dict[str, Any]:
    """Build charts that use every root/state/transition/invoke key at a
    legal position and assert strict_config accepts them all."""
    rnd = random.Random(99)
    rejections: List[Dict[str, str]] = []
    other: List[Dict[str, str]] = []
    accepted = 0
    root_keys = sorted(KNOWN_ROOT_KEYS - {"states", "initial", "id"})
    state_keys = sorted(KNOWN_STATE_KEYS - {"states", "initial", "id",
                                            "history", "target"})
    tkeys = sorted(KNOWN_TRANSITION_KEYS - {"target"})
    ikeys = sorted(KNOWN_INVOKE_KEYS - {"onDone", "onError"})
    for t in range(trials):
        cfg: Dict[str, Any] = {
            "id": f"g{t}", "initial": "a",
            "states": {"a": {}, "b": {"type": "final"}},
        }
        for k in rnd.sample(root_keys, k=rnd.randint(1, len(root_keys))):
            cfg[k] = valid_value(k, rnd)
        cfg.setdefault("states", {"a": {}, "b": {"type": "final"}})
        cfg["initial"] = "a"
        st = cfg["states"]["a"]
        for k in rnd.sample(state_keys, k=rnd.randint(1, len(state_keys))):
            st[k] = valid_value(k, rnd)
        # a transition body carrying every legal transition key
        tbody: Dict[str, Any] = {"target": "b"}
        for k in rnd.sample(tkeys, k=rnd.randint(1, len(tkeys))):
            tbody[k] = {"actions": ["noop"], "guard": "never",
                        "cond": "never", "internal": True, "reenter": True,
                        "meta": {"m": 1}, "description": "d",
                        "tags": ["t"]}.get(k, True)
        st["on"] = {"E": tbody}
        ibody: Dict[str, Any] = {"id": "s", "src": "work"}
        for k in rnd.sample(ikeys, k=rnd.randint(1, len(ikeys))):
            ibody[k] = {"id": "s", "src": "work", "input": {"i": 1},
                        "systemId": "sys", "meta": {"m": 1},
                        "description": "d", "tags": ["t"]}.get(k, "work")
        ibody["onDone"] = {"target": "b", "actions": ["noop"]}
        ibody["onError"] = {"target": "b", "actions": ["noop"]}
        st["invoke"] = ibody
        outcome, msg = build(cfg, strict_config=True)
        if outcome == "ACCEPTED":
            accepted += 1
        elif outcome == "REFUSED" and "unknown config key" in msg:
            rejections.append({"trial": str(t), "msg": msg[:300]})
        else:
            other.append({"trial": str(t), "msg": msg[:200]})
    out = {"trials": trials, "accepted": accepted,
           "key_check_false_positives": len(rejections),
           "false_positive_sample": rejections[:5],
           "other_build_errors": len(other), "other_sample": other[:3]}
    if rejections:
        FAILS.append(f"F2: {len(rejections)}/{trials} VALID generated charts "
                     f"rejected by the key check (false positives)")
    return out


# ── S1: strict_config bypass attempts ────────────────────────────────
def s1_bypass() -> Dict[str, Any]:
    """A smuggled policy key must be REFUSED or INERT -- never silently
    effective. `strict` is the probe: with strict=True an undeclared
    event is refused, so 'did it take effect' is directly observable."""
    rows: List[Dict[str, Any]] = []

    def base() -> Dict[str, Any]:
        return {
            "id": "s1", "initial": "a",
            "states": {"a": {"on": {"REAL": "b"}}, "b": {}},
        }

    variants = [
        ("x-strict", True, "x- prefix smuggling a policy key"),
        ("x-maxIterations", 1, "x- prefix smuggling maxIterations"),
        ("Strict", True, "case variant: capitalised"),
        ("STRICT", True, "case variant: upper"),
        ("strictconfig", True, "case variant: lowercased strictConfig"),
        ("strict ", True, "trailing whitespace"),
        (" strict", True, "leading whitespace"),
        ("strıct", True, "unicode look-alike (dotless i)"),
        ("ѕtrict", True, "unicode look-alike (cyrillic es)"),
        ("meta", {"strict": True}, "policy nested under the accepted meta key"),
    ]
    for key, value, why in variants:
        cfg = base()
        cfg[key] = value
        outcome, msg = build(cfg, strict_config=True)
        # did the smuggled `strict` actually take effect?
        took_effect = None
        if outcome == "ACCEPTED":
            try:
                m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(),
                                   strict_config=True)
                i = SyncInterpreter(m)
                i.start()
                # 🧷 `strict: True` RAISES UnknownEventError at the call
                #    site (base_interpreter._check_strict). So "the policy
                #    took effect" == the send raised.
                try:
                    i.send("UNDECLARED_EVENT")
                    took_effect = False
                except UnknownEventError:
                    took_effect = True
                try:
                    i.stop()
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                took_effect = f"probe error: {type(exc).__name__}"
        row = {"key": key, "why": why, "strict_config_outcome": outcome,
               "smuggled_policy_took_effect": took_effect,
               "msg": msg[:160]}
        rows.append(row)
        if outcome == "ACCEPTED" and took_effect is True:
            FAILS.append(f"S1: '{key}' was ACCEPTED under strict_config AND "
                         f"took effect as a policy -- bypass")
    # control: the real key, correctly spelled, DOES take effect
    cfg = base()
    cfg["strict"] = True
    outcome, _ = build(cfg, strict_config=True)
    control_effect = None
    if outcome == "ACCEPTED":
        m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(),
                           strict_config=True)
        i = SyncInterpreter(m)
        i.start()
        try:
            i.send("UNDECLARED_EVENT")
            control_effect = False
        except UnknownEventError:
            control_effect = True
        try:
            i.stop()
        except Exception:  # noqa: BLE001
            pass
    if control_effect is not True:
        FAILS.append("S1: CONTROL failed -- a correctly spelled 'strict': "
                     "True did not take effect; the oracle is blind")
    return {"variants": rows, "control_real_strict_took_effect": control_effect}



# ── F3: livelock fuzzer, ported verbatim from the round-11 u6 probe ──
#    Same two-sided #212 oracle (longest run of CONSECUTIVE zero-delay
#    hops vs maxIterations). Extended here with the #222 assertion: a
#    periodic cycle must leave `chain_trips` at 0, and a must-trip cell
#    must leave it > 0 with `last_chain_error` LATCHED.
LIMIT = 6
RUN_S = 0.1
MIN_BEATS = 3
N_SHAPES = 90


class Drops(PluginBase):
    def __init__(self):
        self.chain = 0

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        if reason == "chain_budget":
            self.chain += 1


def logic(kind):
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def gen_shape(rng):
    """A 2..4 state self-feeding cycle. Each hop's raise carries a delay
    drawn from [None, 1, 2, 5, 10] ms; None == zero-delay."""
    n = rng.randint(2, 4)
    # 🎲 One shape in four is forced ALL zero-delay so the oracle is
    #    two-sided: the fuzzer must produce must-trip cells as well as
    #    must-not-trip ones (a 2..4-hop cycle rarely reaches a zero run
    #    > maxIterations by chance).
    if rng.random() < 0.25:
        delays = [None] * n
    else:
        delays = [rng.choice([None, 1, 1, 2, 5, 10]) for _ in range(n)]
    states: Dict[str, Any] = {}
    for k in range(n):
        nxt = f"s{(k + 1) % n}"
        params: Dict[str, Any] = {"event": "GO"}
        if delays[k] is not None:
            params["delay"] = delays[k]
        states[f"s{k}"] = {
            "entry": [{"type": "raise", "params": params}],
            "on": {"GO": nxt},
            "exit": ["tick"],
        }
    cfg = {"id": "v4f3", "initial": "s0", "maxIterations": LIMIT,
           "context": {"n": 0}, "states": states}
    all_delayed = all(d is not None for d in delays)
    # 🔗 #212: the longest run of CONSECUTIVE zero-delay hops around the
    #    cycle is the work the machine feeds itself within one step.
    if all_delayed:
        run = 0
    elif all(d is None for d in delays):
        run = 10 ** 6          # unbroken zero-delay cycle
    else:
        doubled = delays + delays
        run = best = 0
        for d in doubled:
            run = run + 1 if d is None else 0
            best = max(best, run)
        run = best
    return cfg, delays, all_delayed, run


async def run_async(cfg, kind) -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    d = Drops()
    i = Interpreter(m)
    i.use(d)
    hung = False
    try:
        await asyncio.wait_for(i.start(), timeout=3.0)
        await asyncio.sleep(RUN_S)
    except asyncio.TimeoutError:
        hung = True
    except Exception as exc:  # noqa: BLE001
        return {"engine": "async", "kind": kind, "raised": repr(exc),
                "tripped": True, "beats": 0, "hung": False}
    beats = i.context.get("n", 0)
    tripped = bool(d.chain) or i.last_error is not None
    trips = getattr(i, "chain_trips", None)          # #222
    latched = i.last_chain_error is not None         # #222
    try:
        await asyncio.wait_for(i.stop(), timeout=3.0)
    except Exception:
        pass
    return {"engine": "async", "kind": kind, "beats": beats,
            "tripped": tripped, "chain_drops": d.chain, "hung": hung,
            "chain_trips": trips, "latched": latched}


def run_sync(cfg, kind) -> Dict[str, Any]:
    if kind == "async def":
        return {"engine": "sync", "kind": kind, "unsupported": True}
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    d = Drops()
    i = SyncInterpreter(m)
    i.use(d)
    try:
        i.start()
        end = time.perf_counter() + RUN_S
        while time.perf_counter() < end:
            i.tick()
            time.sleep(0.001)
    except Exception as exc:  # noqa: BLE001
        return {"engine": "sync", "kind": kind, "raised": repr(exc),
                "tripped": True, "beats": 0, "hung": False}
    beats = i.context.get("n", 0)
    tripped = bool(d.chain) or i.last_error is not None
    trips = getattr(i, "chain_trips", None)          # #222
    latched = i.last_chain_error is not None         # #222
    try:
        i.stop()
    except Exception:
        pass
    return {"engine": "sync", "kind": kind, "beats": beats,
            "tripped": tripped, "chain_drops": d.chain, "hung": False,
            "chain_trips": trips, "latched": latched}


async def f3_fuzz(seed) -> Dict[str, Any]:
    rng = random.Random(seed)
    cells = 0
    viols: List[Dict[str, Any]] = []
    hangs = 0
    legal_periodic = 0
    must_trip_cells = 0
    for s in range(N_SHAPES):
        cfg, delays, all_delayed, zrun = gen_shape(rng)
        rows = []
        for kind in ("def", "async def"):
            rows.append(await run_async(cfg, kind))
        rows.append(run_sync(cfg, "def"))
        for r in rows:
            if r.get("unsupported"):
                continue
            cells += 1
            if r.get("hung"):
                hangs += 1
                viols.append({"shape": s, "delays": delays, "why": "HANG",
                              **r})
                continue
            must_trip = zrun > LIMIT
            if must_trip:
                must_trip_cells += 1
            if not must_trip:
                legal_periodic += 1
                if r["tripped"]:
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": "periodic cycle TRIPPED "
                                         "(violates the #212 rule)", **r})
                elif r.get("chain_trips"):
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": "periodic cycle recorded "
                                         "chain_trips > 0 (#222)", **r})
                elif r["beats"] < MIN_BEATS:
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": f"periodic process ran only "
                                         f"{r['beats']} beats", **r})
            else:
                if r["tripped"] and not (r.get("chain_trips") and r.get("latched")):
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": "tripped but chain_trips/"
                                         "last_chain_error not set (#222)",
                                  **r})
                if not r["tripped"]:
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": f"{zrun} consecutive zero-delay "
                                         f"hops (> maxIterations={LIMIT}) "
                                         f"did NOT trip", **r})
    return {"seed": seed, "shapes": N_SHAPES, "cells": cells,
            "must_trip_cells": must_trip_cells,
            "periodic_cells": legal_periodic, "hangs": hangs,
            "violations": len(viols), "violation_sample": viols[:6]}



async def main() -> int:
    OUT["F1_nesting_fuzz"] = f1_nesting_fuzz(25)
    OUT["F2_valid_grammar_false_positives"] = f2_valid_grammar(120)
    OUT["S1_strict_config_bypass"] = s1_bypass()
    shards = []
    total_cells = total_viol = 0
    for seed in (70251, 70252):
        r = await f3_fuzz(seed)
        shards.append(r)
        total_cells += r["cells"]
        total_viol += r["violations"]
    OUT["F3_livelock_fuzz"] = {"shards": shards, "total_cells": total_cells,
                               "total_violations": total_viol}
    if total_viol:
        FAILS.append(f"F3: {total_viol}/{total_cells} livelock cells violated "
                     f"the #212/#222 oracle")
    if total_cells < 500:
        FAILS.append(f"F3: only {total_cells} cells (brief requires >=500)")
    OUT["failures"] = FAILS
    OUT["verdict"] = "DEFECT" if FAILS else "CLEAN"
    emit("v4_fuzz_keys_and_livelock", OUT)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
