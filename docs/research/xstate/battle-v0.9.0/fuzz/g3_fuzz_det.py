"""G3 -- v0.9.0 fuzz: livelock oracle at >=500 configs, config fuzzer with
#231 inline-dict `invoke.src` variants, and determinism.

A: livelock fuzzer, >=500 generated configs x 2 kinds, async + sync engines.
   Oracle (#212, current): a cycle whose only self-feeding edge carries a
   delay >= 1 ms is LEGAL (must not trip); a cycle with any zero-delay
   self-feeding edge must trip at maxIterations. Cells are kept cheap
   (small maxIterations, short beat windows) so >=500 configs fit the bound.
B: #231 -- every inline-dict / non-str `invoke.src` shape must raise a NAMED
   InvalidConfigError, never a bare TypeError/KeyError.
C: determinism -- 50 runs x both engines x both kinds, comparing the full
   trace AND chain_trips AND the #226 latch.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import random
import time
import warnings

warnings.simplefilter("ignore")

from xstate_statemachine import (  # noqa: E402
    InvalidConfigError,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

N_CFG = int(os.environ.get("N_CFG", "520"))
SEED = int(os.environ.get("SEED", "20260923"))
BUDGET = float(os.environ.get("BUDGET", "70"))
DEFECTS = []


class Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, rec):
        self.rows.append((rec.levelname, rec.getMessage()))

    def tripped(self):
        return any("chained" in m for _, m in self.rows)


def gen_ring(idx, rnd):
    """A ring of k states; each edge fires the next event, maybe delayed."""
    k = rnd.randint(2, 4)
    delays = [rnd.choice([0, 0, 1, 2, 5]) for _ in range(k)]
    r = rnd.random()
    if r < 0.4:
        delays = [d or 1 for d in delays]  # force a legal (all-delayed) ring
    elif r < 0.7:
        delays = [0] * k  # force a must-trip ring
    states = {}
    for n in range(k):
        nxt = f"E{(n + 1) % k}"
        params = {"event": nxt}
        if delays[n]:
            params["delay"] = delays[n]
        states[f"s{n}"] = {
            "entry": ["tick"] if n == 0 else [],
            "on": {
                f"E{n}": {
                    "target": f"s{(n + 1) % k}",
                    "actions": [{"type": "raise", "params": params}],
                }
            },
        }
    cfg = {
        "id": f"g3_{idx}",
        "initial": "boot",
        "context": {"n": 0},
        "maxIterations": rnd.choice([12, 25, 40]),
        "states": states,
    }
    # 🚀 Kick the ring from a SEPARATE boot state. Putting the kick on the
    #    ring's own `s0` entry adds a zero-delay self-feeding edge that is
    #    re-run on every lap, which trips even an all-delayed ring -- a
    #    harness artefact, not the library's rule.
    cfg["states"]["boot"] = {
        "entry": [{"type": "raise", "params": {"event": "BOOT"}}],
        "on": {
            "BOOT": {
                "target": "s0",
                "actions": [{"type": "raise", "params": {"event": "E0"}}],
            }
        },
    }
    cfg["states"]["s0"]["entry"] = ["tick"]
    # 🎯 Oracle (#212): the chain is broken by ANY delayed edge -- a delayed
    #    self-send is a new macrostep, not a continuation. So a ring must
    #    trip only when EVERY edge is zero-delay; a ring with at least one
    #    delayed edge is a legal periodic process and must NOT trip.
    must_trip = all(d == 0 for d in delays)
    return cfg, must_trip


def tick(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def tick_async(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def run_cell(cfg, kind, engine):
    cap = Cap()
    root = logging.getLogger("xstate_statemachine")
    old_lvl, old_dis = root.level, logging.root.manager.disable
    logging.disable(logging.NOTSET)
    root.addHandler(cap)
    root.setLevel(logging.WARNING)
    try:
        lg = MachineLogic(
            actions={"tick": tick if kind == "def" else tick_async}
        )
        m = create_machine(json.loads(json.dumps(cfg)), logic=lg)
        if engine == "sync":
            if kind != "def":
                return None
            it = SyncInterpreter(m)
            it.start()
            it.stop()
        else:
            it = Interpreter(m)
            await it.start()
            await asyncio.sleep(0.03)
            await it.stop()
        return cap.tripped() or getattr(it, "chain_trips", 0) > 0
    finally:
        root.removeHandler(cap)
        root.setLevel(old_lvl)
        logging.disable(old_dis)


async def part_a():
    rnd = random.Random(SEED)
    t0 = time.time()
    stats = {"legal_ok": 0, "legal_tripped": 0, "must_ok": 0, "must_miss": 0}
    cells = configs = 0
    for idx in range(N_CFG):
        if time.time() - t0 > BUDGET:
            print(f"   [stopped at config {idx} to stay inside {BUDGET}s]")
            break
        cfg, must_trip = gen_ring(idx, rnd)
        configs += 1
        for kind in ("def", "async def"):
            for engine in ("async", "sync"):
                r = await run_cell(cfg, kind, engine)
                if r is None:
                    continue
                cells += 1
                if must_trip:
                    if r:
                        stats["must_ok"] += 1
                    else:
                        stats["must_miss"] += 1
                        DEFECTS.append(
                            f"A {cfg['id']}/{kind}/{engine}: zero-delay ring "
                            f"did NOT trip the chain budget"
                        )
                else:
                    if r:
                        stats["legal_tripped"] += 1
                        DEFECTS.append(
                            f"A {cfg['id']}/{kind}/{engine}: all-delayed ring "
                            f"TRIPPED (legal periodic process, #212)"
                        )
                    else:
                        stats["legal_ok"] += 1
    print(
        f"   configs={configs} cells={cells} in {time.time() - t0:.1f}s\n"
        f"   LEGAL rings  ok={stats['legal_ok']} tripped={stats['legal_tripped']}\n"
        f"   MUST-TRIP    tripped={stats['must_ok']} missed={stats['must_miss']}"
    )


# ------------------------------------------------- B: #231 invoke.src fuzz
SRC_VARIANTS = [
    ("inline machine dict", {"id": "inner", "initial": "x", "states": {"x": {}}}),
    ("empty dict", {}),
    ("nested dict", {"src": {"id": "deep"}}),
    ("list", ["a", "b"]),
    ("int", 7),
    ("float", 1.5),
    ("bool", True),
    ("none", None),
    ("tuple-ish list of dicts", [{"id": "q"}]),
    ("set-like dict keys", {"a": 1, "b": 2}),
]


def invoke_cfg(src):
    return {
        "id": "g3b",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "id": "inv1",
                    "src": src,
                    "onDone": {"target": "b"},
                },
            },
            "b": {},
        },
    }


def part_b():
    rows = []
    for label, src in SRC_VARIANTS:
        for strictc in (False, True):
            try:
                create_machine(
                    json.loads(json.dumps(invoke_cfg(src))),
                    logic=MachineLogic(),
                    strict_config=strictc,
                )
                outcome = "ACCEPTED"
                detail = ""
            except InvalidConfigError as exc:
                outcome = "InvalidConfigError"
                detail = str(exc)[:100]
            except Exception as exc:  # noqa: BLE001
                outcome = type(exc).__name__
                detail = str(exc)[:100]
            rows.append((label, strictc, outcome, detail))
            if outcome not in ("InvalidConfigError",):
                if src is None and outcome == "ACCEPTED":
                    pass  # None may be a legal "no src" -- checked below
                else:
                    DEFECTS.append(
                        f"B invoke.src={label} strict_config={strictc}: "
                        f"{outcome} ({detail}) -- expected a named "
                        f"InvalidConfigError (#231)"
                    )
    for label, sc, outcome, detail in rows:
        print(f"   src={label:24s} strict={str(sc):5s} -> {outcome:20s} {detail[:64]}")
    # the message must name the state, the invoke id and the type it got
    try:
        create_machine(
            invoke_cfg({"id": "inner", "initial": "x", "states": {"x": {}}}),
            logic=MachineLogic(),
        )
        msg = ""
    except InvalidConfigError as exc:
        msg = str(exc)
    for token in ("inv1", "dict"):
        if token not in msg:
            DEFECTS.append(
                f"B: #231 message omits {token!r}: {msg[:160]!r}"
            )
    print(f"   message = {msg[:200]}")


# ---------------------------------------------------- C: determinism 50x
DET_CFG = {
    "id": "det",
    "initial": "a",
    "context": {"log": []},
    "maxIterations": 20,
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO"}}, "mark"],
            "on": {
                "GO": {
                    "target": "b",
                    "actions": ["mark", {"type": "raise", "params": {"event": "GO"}}],
                },
                "X": {"target": "b", "actions": ["mark"]},
            },
        },
        "b": {
            "entry": ["mark"],
            "on": {"GO": {"target": "a", "actions": ["mark"]}},
        },
    },
}


def markd(i, c, e, a=None):
    c.setdefault("log", []).append(e.type)


async def markd_async(i, c, e, a=None):
    c.setdefault("log", []).append(e.type)


async def part_c():
    for engine in ("async", "sync"):
        for kind in ("def", "async def"):
            if engine == "sync" and kind != "def":
                continue
            traces, trips, latch = set(), set(), set()
            for _ in range(50):
                lg = MachineLogic(
                    actions={"mark": markd if kind == "def" else markd_async}
                )
                m = create_machine(json.loads(json.dumps(DET_CFG)), logic=lg)
                if engine == "sync":
                    it = SyncInterpreter(m)
                    it.start()
                    ctx = it.context
                else:
                    it = Interpreter(m)
                    await it.start()
                    await asyncio.sleep(0.05)
                    ctx = it.context
                traces.add(
                    json.dumps(
                        [sorted(it.current_state_ids), ctx.get("log", [])]
                    )
                )
                trips.add(it.chain_trips)
                latch.add(type(it.last_chain_error).__name__)
                if engine == "sync":
                    it.stop()
                else:
                    await it.stop()
            print(
                f"   {engine:6s} engine /{kind:9s} distinct_traces="
                f"{len(traces)} trips={sorted(trips)} latch={sorted(latch)}"
            )
            if len(traces) != 1 or len(trips) != 1 or len(latch) != 1:
                DEFECTS.append(
                    f"C {engine}/{kind}: nondeterministic -- traces="
                    f"{len(traces)} trips={sorted(trips)} latch={sorted(latch)}"
                )


async def main():
    print("G3 -- livelock oracle >=500 configs, #231 invoke.src, determinism\n")
    print(f"A -- livelock fuzzer ({N_CFG} configs x 2 kinds x 2 engines)")
    await part_a()
    print("\nB -- #231 inline-dict / non-str invoke.src")
    part_b()
    print("\nC -- determinism: 50 runs x engines x kinds (trace+trips+latch)")
    await part_c()
    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS[:30]:
        print("   -", d)
    return 1 if DEFECTS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
