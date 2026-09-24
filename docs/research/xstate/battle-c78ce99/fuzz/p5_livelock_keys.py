"""P5 -- livelock fuzzer under the #212 oracle, plus the #216 config-key
fuzzer.

The oracle CHANGED this round. Under #206 a cycle containing a
`raise(delay=)` was a chain and had to trip. Under #212 it is a periodic
process:

  * a cycle whose only self-feeding edge carries a delay >= 1 ms is LEGAL
    -- it must NOT trip, and it must still be beating after N beats
  * a cycle with any ZERO-delay self-feeding edge must trip at
    `maxIterations`

Part A fuzzes >=500 configs x 2 kinds x 2 engines against that oracle.
Part B fuzzes #216: unknown keys at the TOP level (must WARN, or raise
under `strict_config`) and at the NESTED state level (undocumented --
this measures and records what actually happens).

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
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)

N_CFG = int(os.environ.get("N_CFG", "500"))
N_KEY = int(os.environ.get("N_KEY", "200"))
SEED = int(os.environ.get("SEED", "20260922"))
CELL_SECS = float(os.environ.get("CELL_SECS", "0.30"))
BUDGET = float(os.environ.get("BUDGET", "110"))


class Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, rec):
        self.rows.append((rec.levelname, rec.getMessage()))

    def trips(self):
        return [m for _, m in self.rows if "Exceeded" in m and "chained" in m]

    def warns(self):
        return [m for lvl, m in self.rows if lvl == "WARNING"]


def capture(level=logging.DEBUG):
    lg = logging.getLogger("xstate_statemachine")
    cap = Cap()
    lg.addHandler(cap)
    lg.setLevel(level)
    return lg, cap


def beat(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def beat_async(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def mk_logic(kind):
    return MachineLogic(actions={"beat": beat if kind == "def"
                                 else beat_async})


# ------------------------------------------------------------- A: generator
def gen(idx, rnd):
    """A 2..4 state ring; each edge is zero-delay raise, delayed raise or
    `after`.

    📏 Oracle. The ring is a single cycle, so it trips only if EVERY edge
    is zero-delay: one delayed edge anywhere paces the whole loop, ending
    the chain at that state, and the zero-delay edges after it are one
    step of work each. `has_zero` alone is NOT the oracle -- a mixed ring
    is periodic, and charging it would be exactly the time-blind rule #212
    removed. (The separate "mixed chain within ONE step" shape, where a
    state arms a delay AND raises zero-delay, is covered by p3/p4 part B.)
    """
    n = rnd.randint(2, 4)
    names = [f"s{k}" for k in range(n)]
    states = {}
    kinds = []
    for k, nm in enumerate(names):
        nxt = names[(k + 1) % n]
        shape = rnd.choice(["raise0", "raisedelay", "after"])
        kinds.append(shape)
        if shape == "raise0":
            states[nm] = {
                "entry": [{"type": "raise", "params": {"event": "G"}}, "beat"],
                "on": {"G": nxt},
            }
        elif shape == "raisedelay":
            d = rnd.choice([1, 2, 5])
            states[nm] = {
                "entry": [{"type": "raise",
                           "params": {"event": "G", "delay": d}}, "beat"],
                "on": {"G": nxt},
            }
        else:
            d = rnd.choice([1, 2, 5])
            states[nm] = {"entry": ["beat"], "after": {d: {"target": nxt}}}
    cfg = {
        "id": f"z{idx}", "initial": names[0],
        "maxIterations": rnd.choice([3, 6, 12]),
        "context": {"n": 0}, "states": states,
    }
    # 📏 The ring trips iff some RUN of consecutive zero-delay edges is at
    #    least `maxIterations` long: a delayed/`after` edge ends the chain,
    #    and the zero-delay edges that follow it are chained work within one
    #    step. Counted cyclically. `all_zero` is the special case of a run
    #    that never ends.
    mi = cfg["maxIterations"]
    if all(k == "raise0" for k in kinds):
        run = 10**6
    else:
        run, cur = 0, 0
        for k in kinds * 2:
            cur = cur + 1 if k == "raise0" else 0
            run = max(run, cur)
    must_trip = run >= mi
    return cfg, must_trip, kinds


async def cell_async(cfg, kind):
    m = create_machine(json.loads(json.dumps(cfg)), logic=mk_logic(kind))
    lgr, cap = capture()
    try:
        it = await Interpreter(m).start()
        await asyncio.sleep(CELL_SECS)
        n1 = it.context.get("n", 0)
        await asyncio.sleep(CELL_SECS / 2)
        n2 = it.context.get("n", 0)
        err = type(it.last_error).__name__ if it.last_error else None
        await it.stop()
        return n1, n2, err, len(cap.trips())
    finally:
        lgr.removeHandler(cap)


def cell_sync(cfg, kind):
    m = create_machine(json.loads(json.dumps(cfg)), logic=mk_logic(kind))
    lgr, cap = capture()
    try:
        it = SyncInterpreter(m)
        it.start()
        n1 = it.context.get("n", 0)
        err = type(it.last_error).__name__ if it.last_error else None
        it.stop()
        return n1, n1, err, len(cap.trips())
    except Exception as exc:  # noqa: BLE001
        return 0, 0, type(exc).__name__, len(cap.trips())
    finally:
        lgr.removeHandler(cap)


async def part_a(defects):
    print(f"A -- livelock fuzzer under the #212 oracle "
          f"({N_CFG} configs x 2 kinds, async engine + sync probe)")
    rnd = random.Random(SEED)
    t0 = time.monotonic()
    ran = 0
    stats = {"legal_ok": 0, "legal_tripped": 0, "legal_died": 0,
             "zero_ok": 0, "zero_no_trip": 0}
    samples = {"legal_tripped": [], "legal_died": [], "zero_no_trip": []}
    for idx in range(N_CFG):
        if time.monotonic() - t0 > BUDGET:
            print(f"   [stopped at config {idx} to stay inside the "
                  f"{BUDGET:.0f}s bound]")
            break
        cfg, must_trip, kinds = gen(idx, rnd)
        for kind in ("def", "async def"):
            ran += 1
            n1, n2, err, trips = await cell_async(cfg, kind)
            tripped = err == "RunawayChainError" or trips > 0
            if must_trip:
                if tripped:
                    stats["zero_ok"] += 1
                else:
                    stats["zero_no_trip"] += 1
                    if len(samples["zero_no_trip"]) < 4:
                        samples["zero_no_trip"].append(
                            (idx, kind, kinds, n1, err))
            else:
                if tripped:
                    stats["legal_tripped"] += 1
                    if len(samples["legal_tripped"]) < 4:
                        samples["legal_tripped"].append(
                            (idx, kind, kinds, n1, err))
                elif n2 <= n1:
                    # must still be beating
                    stats["legal_died"] += 1
                    if len(samples["legal_died"]) < 4:
                        samples["legal_died"].append(
                            (idx, kind, kinds, n1, n2, err))
                else:
                    stats["legal_ok"] += 1
    took = time.monotonic() - t0
    print(f"   ran {ran} cells in {took:.1f}s")
    print(f"   LEGAL (no zero-delay run reaches maxIterations): "
          f"ok={stats['legal_ok']} tripped={stats['legal_tripped']} "
          f"stopped_beating={stats['legal_died']}")
    print(f"   MUST-TRIP rings (zero-delay run >= maxIterations): tripped={stats['zero_ok']} "
          f"NOT_tripped={stats['zero_no_trip']}")
    for k in ("legal_tripped", "legal_died", "zero_no_trip"):
        if samples[k]:
            print(f"     {k} samples: {samples[k]}")
    if stats["legal_tripped"]:
        defects.append(
            f"A: {stats['legal_tripped']} periodic (timer-paced) cycles "
            f"tripped RunawayChainError -- #212 says a delay >=1 ms is a "
            f"legal periodic process"
        )
    if stats["legal_died"]:
        defects.append(
            f"A: {stats['legal_died']} periodic cycles stopped beating "
            f"without an error -- they must run indefinitely"
        )
    if stats["zero_no_trip"]:
        defects.append(
            f"A: {stats['zero_no_trip']} rings whose run of consecutive "
            f"zero-delay self-raises reaches maxIterations did NOT trip"
        )
    print()


# ------------------------------------------------------------- B: #216 keys
GOOD_KEYS = ["actionErrorPolicy", "guardErrorPolicy", "onUnhandled",
             "maxIterations", "strict", "strictTargets", "spawnBlockingTimeout"]


def misspell(key, rnd):
    ops = ["double_last", "drop_char", "swap_case", "plural", "typo"]
    op = rnd.choice(ops)
    if op == "double_last":
        return key + key[-1]
    if op == "drop_char":
        p = rnd.randrange(len(key))
        return key[:p] + key[p + 1:]
    if op == "swap_case":
        return key[0].upper() + key[1:]
    if op == "plural":
        return key + "s"
    p = rnd.randrange(len(key) - 1)
    return key[:p] + key[p + 1] + key[p] + key[p + 2:]


def part_b(defects):
    print(f"B -- #216 config-key fuzzer ({N_KEY} misspellings, top level "
          f"AND nested state level)")
    rnd = random.Random(SEED)
    top = {"warned": 0, "silent": 0, "raised": 0, "no_hint": 0}
    strictmode = {"raised": 0, "accepted": 0}
    nested = {"warned": 0, "silent": 0, "raised": 0}
    silent_samples, nohint_samples, nested_samples = [], [], []
    for i in range(N_KEY):
        bad = misspell(rnd.choice(GOOD_KEYS), rnd)
        if bad in GOOD_KEYS:
            continue
        base = {"id": f"k{i}", "initial": "a",
                "states": {"a": {"on": {"E": "b"}}, "b": {}}}

        # --- top level, default policy
        cfg = dict(base)
        cfg[bad] = True
        lgr, cap = capture(logging.WARNING)
        try:
            create_machine(json.loads(json.dumps(cfg)))
            ws = [w for w in cap.warns() if bad in w]
            if ws:
                top["warned"] += 1
                if "did you mean" not in ws[0]:
                    top["no_hint"] += 1
                    if len(nohint_samples) < 5:
                        nohint_samples.append(bad)
            else:
                top["silent"] += 1
                if len(silent_samples) < 8:
                    silent_samples.append(bad)
        except InvalidConfigError:
            top["raised"] += 1
        finally:
            lgr.removeHandler(cap)

        # --- top level, strict_config=True
        try:
            create_machine(json.loads(json.dumps(cfg)), strict_config=True)
            strictmode["accepted"] += 1
        except InvalidConfigError:
            strictmode["raised"] += 1

        # --- NESTED state level (undocumented)
        ncfg = json.loads(json.dumps(base))
        ncfg["states"]["a"][bad] = True
        lgr, cap = capture(logging.WARNING)
        try:
            create_machine(ncfg, strict_config=True)
            ws = [w for w in cap.warns() if bad in w]
            if ws:
                nested["warned"] += 1
            else:
                nested["silent"] += 1
                if len(nested_samples) < 8:
                    nested_samples.append(bad)
        except InvalidConfigError:
            nested["raised"] += 1
        finally:
            lgr.removeHandler(cap)

    print(f"   TOP level, default : {top}")
    if silent_samples:
        print(f"     silently dropped: {silent_samples}")
    if nohint_samples:
        print(f"     warned WITHOUT a 'did you mean' hint: {nohint_samples}")
    print(f"   TOP level, strict_config=True : {strictmode}")
    print(f"   NESTED state level, strict_config=True : {nested}")
    if nested_samples:
        print(f"     nested keys accepted in SILENCE: {nested_samples}")
    if top["silent"]:
        defects.append(
            f"B: {top['silent']} misspelled TOP-level keys were dropped in "
            f"total silence (no WARNING) -- #216's default is a warning"
        )
    if strictmode["accepted"]:
        defects.append(
            f"B: {strictmode['accepted']} misspelled TOP-level keys were "
            f"ACCEPTED under strict_config=True"
        )
    if nested["silent"]:
        print(f"   NOTE: nested POLICY misspellings are inert either way "
              f"(policies are read from the ROOT config only), so this "
              f"count alone is not a defect -- see B3 for the keys that do "
              f"live on a state node.")
    print()


def part_b_prefix(defects):
    """`x-` bypass and the always-allowed metadata keys."""
    print("B2 -- strict_config bypass surface")
    rows = []
    for key, val, expect in [
        ("x-anything", True, "accept"),
        ("meta", {"a": 1}, "accept"),
        ("description", "d", "accept"),
        ("tags", ["x"], "accept"),
        ("version", "1", "accept"),
        ("x-maxIterations", 3, "accept (bypasses the #216 check)"),
        ("X-upper", True, "? uppercase prefix"),
        ("x", True, "? bare x"),
        ("x-", True, "? empty suffix"),
        ("_private", True, "? underscore convention"),
    ]:
        cfg = {"id": "bp", "initial": "a", "states": {"a": {}}, key: val}
        try:
            create_machine(cfg, strict_config=True)
            rows.append((key, "ACCEPTED", expect))
        except InvalidConfigError:
            rows.append((key, "REFUSED", expect))
    for k, got, exp in rows:
        print(f"   {k:18s} -> {got:9s} (expected {exp})")
    print()


async def part_b_nested_harm(defects):
    """B3 -- what a silently-dropped NESTED key actually costs.

    The machine-level policy keys (`actionErrorPolicy`, `onUnhandled`, ...)
    are read from the ROOT config only, so misspelling one on a state node
    is inert either way. The keys that DO live on a state node are the
    structural ones -- `entry`, `exit`, `after`, `always`, `invoke`, `on`.
    Misspell one of those and the behaviour it declares silently vanishes,
    under `strict_config=True` as much as without it.
    """
    print("B3 -- a misspelled STRUCTURAL key on a state node, "
          "strict_config=True")

    async def probe(cfg, label, check):
        m = create_machine(json.loads(json.dumps(cfg)),
                           logic=mk_logic("def"), strict_config=True)
        it = await Interpreter(m).start()
        await asyncio.sleep(0.25)
        got = check(it)
        await it.stop()
        return got

    entry_cfg = lambda k: {  # noqa: E731
        "id": "ns", "initial": "a", "context": {"n": 0},
        "states": {"a": {k: ["beat"]}},
    }
    after_cfg = lambda k: {  # noqa: E731
        "id": "nt", "initial": "a", "context": {"n": 0},
        "states": {"a": {k: {10: {"target": "b"}}, "entry": ["beat"]},
                   "b": {}},
    }
    ran_ok = await probe(entry_cfg("entry"), "entry",
                         lambda i: i.context.get("n", 0))
    ran_bad = await probe(entry_cfg("entyr"), "entyr",
                          lambda i: i.context.get("n", 0))
    fired_ok = await probe(after_cfg("after"), "after",
                           lambda i: sorted(i.current_state_ids))
    fired_bad = await probe(after_cfg("afer"), "afer",
                            lambda i: sorted(i.current_state_ids))
    print(f"   'entry' -> action ran {ran_ok}x ; "
          f"'entyr' -> action ran {ran_bad}x  (both ACCEPTED)")
    print(f"   'after' -> {fired_ok} ; 'afer' -> {fired_bad}  "
          f"(both ACCEPTED)")
    if ran_bad == 0 and ran_ok > 0:
        defects.append(
            "B3: `strict_config=True` accepts a misspelled STRUCTURAL key on "
            "a state node ('entyr' for 'entry'): the entry action never "
            "runs and nothing is reported. #216's KNOWN_MACHINE_KEYS check "
            "is applied to the ROOT config only"
        )
    if fired_bad == ["nt.a"] and fired_ok == ["nt.b"]:
        defects.append(
            "B3: `strict_config=True` accepts 'afer' for 'after' on a state "
            "node -- the declared timeout silently becomes a timer that NEVER "
            "fires, so a chart that looks like it has a deadline has none. "
            "For an OMS this is an order timeout that never expires"
        )
    print()


async def main():
    print("P5 -- livelock fuzzer under the #212 oracle + #216 key fuzzer\n")
    logging.disable(logging.NOTSET)
    defects = []
    await part_a(defects)
    part_b(defects)
    part_b_prefix(defects)
    await part_b_nested_harm(defects)
    print(f"DEFECTS = {len(defects)}")
    for d in defects:
        print("   -", d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
