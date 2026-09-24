"""G1 -- v0.9.0 persistence attacks: #226 latch round-trip, #227 strict on
restored scheduled_sends, #230 from_snapshot(plugins=).

A: chain-trip latch across N restarts -- count monotonic, RestoredError
   message intact, clear_chain_error() does not rewind.
B: property >=300 -- a strict machine restoring a scheduled_sends blob with
   a mix of declared/undeclared types: every undeclared record refused,
   every declared one armed, the machine left consistent and usable.
C: from_snapshot(plugins=...) receives every restore-time hook exactly once.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import random
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SimulatedClock,
    create_machine,
)

N = int(os.environ.get("N_CASES", "320"))
SEED = int(os.environ.get("SEED", "20260923"))
DEFECTS = []


def noop(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def noop_async(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


TRIP = {
    "id": "trip",
    "initial": "a",
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO"}}],
            "on": {
                "GO": {
                    "actions": [{"type": "raise", "params": {"event": "GO"}}]
                },
                "BENIGN": {"actions": ["noop"]},
            },
        }
    },
}


async def part_a(kind, restarts=6):
    """Latch survives N restarts; count monotonic; message intact."""
    lg = MachineLogic(actions={"noop": noop if kind == "def" else noop_async})
    m = create_machine(json.loads(json.dumps(TRIP)), logic=lg)
    it = Interpreter(m)
    await it.start()
    await asyncio.sleep(0.2)
    seq = [(it.chain_trips, str(it.last_chain_error or "")[:40])]
    blob = it.get_snapshot()
    await it.stop()
    msg0 = str(it.last_chain_error)

    for r in range(restarts):
        cur = Interpreter.from_snapshot(blob, m)
        t = cur.chain_trips
        err = cur.last_chain_error
        seq.append((t, type(err).__name__))
        if t != seq[0][0]:
            DEFECTS.append(
                f"A/{kind} restart{r}: chain_trips={t} != {seq[0][0]}"
            )
        if err is None:
            DEFECTS.append(f"A/{kind} restart{r}: last_chain_error lost")
        elif type(err).__name__ != "RestoredError":
            DEFECTS.append(
                f"A/{kind} restart{r}: latched error is "
                f"{type(err).__name__}, expected RestoredError"
            )
        elif "RunawayChain" not in str(err) and "chain" not in str(err).lower():
            DEFECTS.append(
                f"A/{kind} restart{r}: RestoredError message lost the "
                f"original text: {str(err)[:80]!r}"
            )
        blob = cur.get_snapshot()

    # clear on a restored one, then re-persist: counter must NOT rewind
    last = Interpreter.from_snapshot(blob, m)
    before = last.chain_trips
    last.clear_chain_error()
    after = last.chain_trips
    cleared_err = last.last_chain_error
    blob2 = last.get_snapshot()
    again = Interpreter.from_snapshot(blob2, m)
    if after != before:
        DEFECTS.append(
            f"A/{kind}: clear_chain_error rewound the counter "
            f"{before} -> {after}"
        )
    if cleared_err is not None:
        DEFECTS.append(f"A/{kind}: clear_chain_error left {cleared_err!r}")
    if again.chain_trips != before:
        DEFECTS.append(
            f"A/{kind}: post-clear re-persist lost the count "
            f"{before} -> {again.chain_trips}"
        )
    print(
        f"  A/{kind:9s} seq={seq} | clear: trips {before}->{after} "
        f"err={type(cleared_err).__name__} | re-persist trips="
        f"{again.chain_trips} | msg0={msg0[:46]!r}"
    )


DECLARED = ["D0", "D1", "D2"]
UNDECLARED = ["U0", "U1", "ZZ", "done.invoke.ghost"]


def strict_cfg(idx):
    return {
        "id": f"g1b_{idx}",
        "strict": True,
        "initial": "armed",
        "context": {"seen": []},
        "states": {
            "armed": {
                "on": {t: {"actions": ["mark"]} for t in DECLARED},
            }
        },
    }


def mark(i, c, e, a=None):
    c.setdefault("seen", []).append(e.type)


async def mark_async(i, c, e, a=None):
    c.setdefault("seen", []).append(e.type)


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []
        self.starts = 0
        self.events = []
        self.transitions = 0
        self.errors = []

    def on_interpreter_start(self, interpreter):
        self.starts += 1

    def on_event_received(self, interpreter, event):
        self.events.append(getattr(event, "type", str(event)))

    def on_transition(self, interpreter, from_s, to_s, event):
        self.transitions += 1

    def on_invalid_event(self, interpreter, error, event=None):
        self.invalid.append(
            (type(error).__name__, getattr(event, "type", None))
        )

    def on_error(self, interpreter, error, *a, **k):
        self.errors.append(type(error).__name__)


async def case_b(idx, rnd, kind):
    """Build a blob whose scheduled_sends mixes declared + undeclared."""
    cfg = strict_cfg(idx)
    lg = MachineLogic(actions={"mark": mark if kind == "def" else mark_async})
    m = create_machine(cfg, logic=lg)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    blob = json.loads(it.get_snapshot())
    await it.stop()

    ok_types = rnd.sample(DECLARED, rnd.randint(1, 3))
    bad_types = rnd.sample(UNDECLARED, rnd.randint(1, 3))
    recs = []
    for t in ok_types + bad_types:
        recs.append({"type": t, "payload": {}, "remaining_ms": 1.0})
    rnd.shuffle(recs)
    blob["scheduled_sends"] = recs
    s = json.dumps(blob)

    spy = Spy()
    tag = f"[B/{idx}/{kind}]"
    try:
        r = Interpreter.from_snapshot(
            s, m, clock=SimulatedClock(), plugins=[spy]
        )
    except Exception as exc:  # restore must not abort
        DEFECTS.append(f"{tag} restore aborted: {type(exc).__name__}: {exc}")
        return
    await r.start()
    await asyncio.sleep(0)
    inc = r.clock.increment(5.0)
    if inc is not None and hasattr(inc, "__await__"):
        await inc
    for _ in range(6):
        await asyncio.sleep(0)
    seen = r.context.get("seen") or []
    # P1: no undeclared type may be delivered
    leaked = [t for t in seen if t in bad_types]
    if leaked:
        DEFECTS.append(f"{tag} undeclared restored sends delivered: {leaked}")
    # P2: every declared record must fire exactly once
    for t in ok_types:
        if seen.count(t) != 1:
            DEFECTS.append(
                f"{tag} declared {t} fired {seen.count(t)}x (expected 1)"
            )
    # P3: the refusal must be reported, once per refused record
    if len(spy.invalid) != len(bad_types):
        DEFECTS.append(
            f"{tag} on_invalid_event fired {len(spy.invalid)}x for "
            f"{len(bad_types)} refused records: {spy.invalid}"
        )
    # P4: machine still consistent and usable after the partial refusal
    if r.status != "running":
        DEFECTS.append(f"{tag} status={r.status} after partial refusal")
    n_before = len(r.context.get("seen") or [])
    await r.send(DECLARED[0])
    await asyncio.sleep(0)
    if len(r.context.get("seen") or []) != n_before + 1:
        DEFECTS.append(f"{tag} machine unusable after partial refusal")
    # P5: re-persisting must not resurrect a refused record
    left = json.loads(r.get_snapshot()).get("scheduled_sends") or []
    if any(rec["type"] in bad_types for rec in left):
        DEFECTS.append(f"{tag} refused record survived re-persist: {left}")
    await r.stop()


async def part_c(kind):
    """plugins= receives every restore-time hook exactly once."""
    cfg = strict_cfg(9000)
    lg = MachineLogic(actions={"mark": mark if kind == "def" else mark_async})
    m = create_machine(cfg, logic=lg)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    blob = json.loads(it.get_snapshot())
    await it.stop()
    blob["scheduled_sends"] = [
        {"type": "U0", "payload": {}, "remaining_ms": 1.0}
    ]
    blob["pending_events"] = [{"type": "U1", "payload": {}}]
    spy = Spy()
    r = Interpreter.from_snapshot(
        json.dumps(blob), m, clock=SimulatedClock(), plugins=[spy]
    )
    pre_start_invalid = list(spy.invalid)
    await r.start()
    await asyncio.sleep(0)
    post = list(spy.invalid)
    print(
        f"  C/{kind:9s} invalid@from_snapshot={pre_start_invalid} "
        f"invalid@post-start={post} starts={spy.starts} "
        f"errors={spy.errors} last_error={type(r.last_error).__name__}"
    )
    types = [t for _, t in post]
    for want in ("U0", "U1"):
        if types.count(want) != 1:
            DEFECTS.append(
                f"C/{kind}: on_invalid_event for {want} fired "
                f"{types.count(want)}x (expected exactly 1): {post}"
            )
    if spy.starts != 1:
        DEFECTS.append(
            f"C/{kind}: on_interpreter_start fired {spy.starts}x"
        )
    # also: the same plugin passed via .use() after the fact must not
    # double-register
    spy2 = Spy()
    r2 = Interpreter.from_snapshot(
        json.dumps(blob), m, clock=SimulatedClock(), plugins=[spy2]
    )
    r2.use(spy2)
    await r2.start()
    await asyncio.sleep(0)
    if len(spy2.invalid) > 4:
        DEFECTS.append(
            f"C/{kind}: plugins= + .use() of the SAME object multiplied "
            f"hooks: {spy2.invalid}"
        )
    print(f"  C/{kind:9s} plugins=+use(same) invalid={spy2.invalid}")
    await r.stop()
    await r2.stop()


async def main():
    print("G1 -- persistence: #226 latch restarts, #227 strict on restored")
    print("      scheduled_sends (property), #230 plugins= hooks\n")
    print("A -- chain-trip latch across 6 restarts")
    for kind in ("def", "async def"):
        await part_a(kind)
    print(f"\nB -- strict refusal of restored scheduled_sends ({N} x 2 kinds)")
    for kind in ("def", "async def"):
        rnd = random.Random(SEED)
        for i in range(N):
            await case_b(i, rnd, kind)
        print(f"  B/{kind:9s} {N} cases done, defects so far = {len(DEFECTS)}")
    print("\nC -- from_snapshot(plugins=) hook delivery")
    for kind in ("def", "async def"):
        await part_c(kind)
    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS[:40]:
        print("   -", d)
    return 1 if DEFECTS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
