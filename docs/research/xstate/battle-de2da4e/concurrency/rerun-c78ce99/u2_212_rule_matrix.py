"""u2 (@c78ce99) -- STANDALONE. #212 rule matrix (SUPERSEDES #206).

New oracle:
  * a `raise(delay=D>0)` self ping-pong is a TIMER pair -- must run
    indefinitely, never RunawayChainError, beats bounded by the clock;
  * a zero-delay `raise` cycle must still trip at maxIterations;
  * a MIXED chain (k zero-delay raises per beat, then a delayed raise)
    must still trip when k > maxIterations;
  * parity with the `after:` rule on the same shape.

Cells x both engines x both action kinds (def / async def entry action).
Delays are MILLISECONDS (the `raise` params contract).

Run: python u2_212_rule_matrix.py   (exit 1 == oracle violated)
"""
from __future__ import annotations

import asyncio, copy, json, os, sys, time
from typing import Any, Dict, List

from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, RunawayChainError, PluginBase)


class Watch(PluginBase):
    """A trip is NOT raised out of start(); it is reported via
    `on_event_dropped(reason='chain_budget')` + `last_error` (#77)."""

    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.drops.append(reason)

LIMIT = 8
RUN_S = 1.2


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def raise_act(delay_ms=None):
    p: Dict[str, Any] = {"event": "PING"}
    if delay_ms is not None:
        p["delay"] = delay_ms
    return {"type": "raise", "params": p}


def cfg_pingpong(delay_ms, extra_zero=0):
    entry = [raise_act(None) for _ in range(extra_zero)] + [raise_act(delay_ms)]
    return {
        "id": "u2", "initial": "a", "maxIterations": LIMIT, "context": {"n": 0},
        "states": {
            "a": {"entry": entry, "on": {"PING": "b"}, "exit": ["tick"]},
            "b": {"entry": entry, "on": {"PING": "a"}, "exit": ["tick"]},
        },
    }


def cfg_after(delay_ms):
    return {
        "id": "u2f", "initial": "a", "maxIterations": LIMIT, "context": {"n": 0},
        "states": {
            "a": {"after": {delay_ms: "b"}, "exit": ["tick"]},
            "b": {"after": {delay_ms: "a"}, "exit": ["tick"]},
        },
    }


def logic(kind):
    if kind == "def":
        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
    return MachineLogic(actions={"tick": atick})


async def run_async(cfg, kind) -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    errs: List[str] = []
    w = Watch()
    interp = Interpreter(m)
    interp.use(w)
    t0 = time.perf_counter()
    try:
        await interp.start()
        await asyncio.sleep(RUN_S)
    except RunawayChainError as exc:
        errs.append(f"RunawayChainError: {exc}")
    beats = interp.context.get("n", 0)
    err = interp.error
    if err is not None:
        errs.append(f"{type(err).__name__}: {err}")
    le = interp.last_error
    if le is not None:
        errs.append(f"last_error={type(le).__name__}: {le}")
    status = interp.status
    try:
        await interp.stop()
    except Exception:
        pass
    return {"engine": "async", "kind": kind, "beats": beats, "status": status,
            "errors": errs, "chain_drops": w.drops.count("chain_budget"),
            "wall": round(time.perf_counter() - t0, 3)}


def run_sync(cfg, kind) -> Dict[str, Any]:
    if kind == "async def":
        return {"engine": "sync", "kind": kind, "unsupported": True}
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    errs: List[str] = []
    w = Watch()
    interp = SyncInterpreter(m)
    interp.use(w)
    t0 = time.perf_counter()
    try:
        interp.start()
        end = time.perf_counter() + RUN_S
        while time.perf_counter() < end:
            interp.tick()
            time.sleep(0.001)
    except RunawayChainError as exc:
        errs.append(f"RunawayChainError: {exc}")
    beats = interp.context.get("n", 0)
    if interp.error is not None:
        errs.append(f"{type(interp.error).__name__}: {interp.error}")
    le = interp.last_error
    if le is not None:
        errs.append(f"last_error={type(le).__name__}: {le}")
    status = interp.status
    try:
        interp.stop()
    except Exception:
        pass
    return {"engine": "sync", "kind": kind, "beats": beats, "status": status,
            "errors": errs, "chain_drops": w.drops.count("chain_budget"),
            "wall": round(time.perf_counter() - t0, 3)}


CASES = [
    # name,                  cfg,                         must_trip, min_beats
    ("delay_1ms_pingpong",   cfg_pingpong(1),             False, 10),
    ("delay_10ms_pingpong",  cfg_pingpong(10),            False, 5),
    ("after_1ms_parity",     cfg_after(1),                False, 10),
    ("zero_delay_cycle",     cfg_pingpong(None),          True,  0),
    ("mixed_zero_plus_delay", cfg_pingpong(1, extra_zero=LIMIT + 3), True, 0),
]


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for name, cfg, must_trip, min_beats in CASES:
        for kind in ("def", "async def"):
            r = await run_async(cfg, kind)
            r["case"] = name
            rows.append(r)
        r = run_sync(cfg, "def")
        r["case"] = name
        rows.append(r)

    bad: List[str] = []
    for r in rows:
        if r.get("unsupported"):
            continue
        case = r["case"]
        must_trip, min_beats = next((t, b) for n, _c, t, b in CASES if n == case)
        tripped = bool(r.get("chain_drops")) or any("Runaway" in e for e in r["errors"])
        tag = f"{case}/{r['engine']}/{r['kind']}"
        if must_trip and not tripped:
            bad.append(f"{tag}: expected RunawayChainError, got none (beats={r['beats']})")
        if not must_trip:
            if tripped:
                bad.append(f"{tag}: SUPERSEDED-RULE VIOLATION -- delayed cycle tripped")
            elif r["beats"] < min_beats:
                bad.append(f"{tag}: periodic process died at {r['beats']} beats (< {min_beats})")
        r["tripped"] = tripped
    emit("u2_212_rule_matrix", {"limit": LIMIT, "run_s": RUN_S,
                                "rows": rows, "violations": bad,
                                "verdict": "DEFECT" if bad else "CLEAN"})
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
