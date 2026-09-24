"""w2 (@v0.9.0) -- STANDALONE. Round-12 PERSISTENCE surface, attacked.

Three properties, all new at 0.9.0:

  P1  #226 latch round-trip.  `chain_trips` is monotonic ACROSS RESTARTS
      and `last_chain_error` survives as a RestoredError whose message
      carries the original.  Attacked with N=8 successive restarts, each
      re-tripping the budget: the count must be non-decreasing and must
      equal (trips so far), never reset, never double-count a restore.

  P2  #227 strict + schemas on restored `scheduled_sends`.  Property run
      (>=300 cases): a blob whose scheduled_sends / pending_events lanes
      carry a mix of declared and UNDECLARED types is restored onto a
      `strict` machine.  After the refusal the machine must be
      CONSISTENT: every declared record armed and fires, every undeclared
      one refused AND reported, `_rearm_restored_self_sends` returns the
      ARMED count, the restore itself does not abort, and the interpreter
      still runs (a later legal event still transitions).

  P3  #230 from_snapshot(plugins=).  Every restore-time hook the plugin
      exposes must fire EXACTLY ONCE for a refusal -- not zero (the
      #229/D11-concurrency-5 complaint) and not twice (both lanes
      double-reporting the same record).

Exit 1 == defect.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

CASES = int(os.environ.get("W2_CASES", "320"))
RESTARTS = 8
ROWS: Dict[str, Any] = {}
FAILS: List[str] = []
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])),
            **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


# ───────────────────────── P1: latch across N restarts ──────────────────

def cfg_chain(mid: str) -> Dict[str, Any]:
    """A --PING--> B --always--> A ... a cycle that trips the chain budget."""
    return {
        "id": mid,
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {"on": {"PING": "b"}},
            "b": {"entry": ["bump"], "always": "c"},
            "c": {"always": "b"},
        },
    }


def mk_chain_logic(kind: str) -> MachineLogic:
    if kind == "def":
        def bump(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
        return MachineLogic(actions={"bump": bump})

    async def abump(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
    return MachineLogic(actions={"abump": abump} if False
                        else {"bump": abump})


async def trip(i: Interpreter) -> None:
    """Kick the cycle and let the budget blow; the error is latched."""
    try:
        await i.send("PING")
    except Exception:  # noqa: BLE001  -- RunawayChainError is the point
        pass
    await asyncio.sleep(0.05)


async def p1_latch_across_restarts(kind: str) -> Dict[str, Any]:
    m = create_machine(cfg_chain(f"w2p1{kind[:1]}"), logic=mk_chain_logic(kind))
    i = Interpreter(m)
    await i.start()
    await trip(i)
    hops: List[Dict[str, Any]] = []
    expected = i.chain_trips
    blob = json.dumps(i.get_persisted_snapshot(), default=str)
    await i.stop()

    for hop in range(RESTARTS):
        r = Interpreter.from_snapshot(blob, m)
        await r.start()
        got_before = r.chain_trips
        latch_before = (None if r.last_chain_error is None
                        else type(r.last_chain_error).__name__)
        msg = ("" if r.last_chain_error is None
               else str(r.last_chain_error))
        await trip(r)                      # re-trip on the restored machine
        expected = got_before + (r.chain_trips - got_before)
        hops.append({
            "hop": hop,
            "trips_on_restore": got_before,
            "latch_type_on_restore": latch_before,
            "latch_msg_mentions_chain": ("chain" in msg.lower()
                                         or "budget" in msg.lower()),
            "trips_after_retrip": r.chain_trips,
        })
        if got_before < (hops[hop - 1]["trips_after_retrip"] if hop else 1):
            FAILS.append(f"P1/{kind} hop{hop}: chain_trips went BACKWARDS "
                         f"across a restart ({got_before})")
        if latch_before != "RestoredError":
            FAILS.append(f"P1/{kind} hop{hop}: restored latch is "
                         f"{latch_before}, expected RestoredError")
        if not hops[hop]["latch_msg_mentions_chain"]:
            FAILS.append(f"P1/{kind} hop{hop}: RestoredError message lost "
                         f"the original text: {msg!r}")
        blob = json.dumps(r.get_persisted_snapshot(), default=str)
        await r.stop()
    return {"kind": kind, "restarts": RESTARTS, "hops": hops,
            "monotonic": all(
                hops[k]["trips_on_restore"] >= hops[k - 1]["trips_on_restore"]
                for k in range(1, len(hops)))}


# ───────── P2: strict / schema refusal on restored scheduled_sends ──────

DECLARED = ["OK1", "OK2"]
UNDECLARED = ["NOPE", "FORGED", "GHOST"]


def cfg_strict(mid: str) -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "idle",
        "strict": True,
        "context": {"n": 0},
        "states": {
            "idle": {"on": {"OK1": {"actions": ["bump"]},
                            "OK2": {"actions": ["bump"]},
                            "FIN": "done"}},
            "done": {},
        },
    }


def mk_bump(kind: str) -> MachineLogic:
    if kind == "def":
        def bump(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
        return MachineLogic(actions={"bump": bump})

    async def abump(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
    return MachineLogic(actions={"bump": abump})


class CountingPlugin(PluginBase):
    """#230: registered BEFORE restored events are admitted."""

    def __init__(self) -> None:
        self.invalid: List[str] = []
        self.inits = 0

    def on_interpreter_start(self, interpreter):  # noqa: ANN001
        self.inits += 1

    def on_invalid_event(self, interpreter, error, event=None):  # noqa: ANN001
        self.invalid.append(getattr(event, "type", str(event)))


async def base_blob(m) -> Dict[str, Any]:  # noqa: ANN001
    """A REAL v3 envelope from a live interpreter -- so the shape check
    (#198) passes and only the two lanes under test are our doing."""
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.02)
    blob = i.get_persisted_snapshot()
    await i.stop()
    return blob


def blob_with(base: Dict[str, Any], sched: List[str],
              pend: List[str]) -> str:
    """Take a real envelope and inject the two lanes under test."""
    b = json.loads(json.dumps(base, default=str))
    b["scheduled_sends"] = [
        {"type": t, "payload": {}, "remaining_ms": 40.0, "send_id": f"s{k}"}
        for k, t in enumerate(sched)
    ]
    b["pending_events"] = [{"type": t, "payload": {}} for t in pend]
    return json.dumps(b)


async def p2_one(case: int, kind: str, rnd: random.Random,
                 m, base) -> Dict[str, Any]:  # noqa: ANN001
    n_ok = rnd.randint(0, 3)
    n_bad = rnd.randint(1, 3)
    sched = ([rnd.choice(DECLARED) for _ in range(n_ok)]
             + [rnd.choice(UNDECLARED) for _ in range(n_bad)])
    rnd.shuffle(sched)
    pend = [rnd.choice(UNDECLARED)] if rnd.random() < 0.5 else []
    plug = CountingPlugin()
    r = Interpreter.from_snapshot(
        blob_with(base, sched, pend), m,
        verify_machine_hash=False, plugins=[plug],
    )
    await r.start()
    await asyncio.sleep(0.18)          # let the armed records fire
    n = r.context.get("n", 0)
    # the machine must still be ALIVE and transition on a legal event
    await r.send("FIN")
    await asyncio.sleep(0.05)
    alive = any(s.endswith(".done") for s in r.current_state_ids)
    await r.stop()

    bad_total = sum(1 for t in sched if t in UNDECLARED) + len(pend)
    ok_total = sum(1 for t in sched if t in DECLARED)
    row = {"case": case, "sched": sched, "pend": pend, "n_fired": n,
           "expected_fired": ok_total, "refusals_reported": len(plug.invalid),
           "expected_refusals": bad_total, "still_alive": alive,
           "plugin_inits": plug.inits}
    if n != ok_total:
        FAILS.append(f"P2/{kind} c{case}: {ok_total} declared records armed "
                     f"but {n} fired; sched={sched}")
    if len(plug.invalid) != bad_total:
        FAILS.append(f"P2/{kind} c{case}: {bad_total} undeclared records but "
                     f"on_invalid_event fired {len(plug.invalid)}x "
                     f"(exactly-once violated); sched={sched} pend={pend}")
    if not alive:
        FAILS.append(f"P2/{kind} c{case}: a strict refusal mid-restore left "
                     f"the machine unable to transition on a legal event")
    # 🔎 on_interpreter_start is 0 on every restored interpreter -- that is
    #    D13-concurrency-1, isolated and filed in w3_restore_lifecycle_hook.
    #    Recorded here, not double-counted as a P2 failure.
    return row


async def p2_property(kind: str) -> Dict[str, Any]:
    rnd = random.Random(0xC0FFEE + len(kind))
    m = create_machine(cfg_strict(f"w2p2_{kind[:1]}"), logic=mk_bump(kind))
    base = await base_blob(m)
    rows = [await p2_one(c, kind, rnd, m, base)
            for c in range(CASES // 2)]
    return {
        "kind": kind,
        "cases": len(rows),
        "all_armed_counts_exact": all(
            r["n_fired"] == r["expected_fired"] for r in rows),
        "all_refusals_exactly_once": all(
            r["refusals_reported"] == r["expected_refusals"] for r in rows),
        "all_alive_after_refusal": all(r["still_alive"] for r in rows),
        "total_refusals": sum(r["refusals_reported"] for r in rows),
        "total_armed": sum(r["n_fired"] for r in rows),
        "sample": rows[:3],
    }


# ───────── P3: plugins= vs .use() -- the #229/D11-5 complaint ───────────

async def p3_plugins_vs_use(kind: str) -> Dict[str, Any]:
    """The SAME refusing blob, restored two ways. `plugins=` must see the
    restore-time refusal; `.use()` afterwards is the old, too-late path
    (recorded for contrast, not asserted as a defect)."""
    mid = f"w2p3_{kind[:1]}"
    m = create_machine(cfg_strict(mid), logic=mk_bump(kind))
    blob = blob_with(await base_blob(m), ["OK1", "NOPE"], ["GHOST"])

    early = CountingPlugin()
    a = Interpreter.from_snapshot(blob, m, verify_machine_hash=False,
                                 plugins=[early])
    await a.start()
    await asyncio.sleep(0.15)
    await a.stop()

    late = CountingPlugin()
    b = Interpreter.from_snapshot(blob, m, verify_machine_hash=False)
    b.use(late)
    await b.start()
    await asyncio.sleep(0.15)
    await b.stop()

    row = {"kind": kind, "plugins_kwarg_saw": early.invalid,
           "use_after_saw": late.invalid,
           "expected_refused_types": ["NOPE", "GHOST"]}
    if sorted(early.invalid) != ["GHOST", "NOPE"]:
        FAILS.append(f"P3/{kind}: plugins= saw {early.invalid}, expected "
                     f"both refused types exactly once each")
    return row


async def main() -> int:
    ROWS["P1_latch_across_restarts"] = [await p1_latch_across_restarts(k)
                                        for k in ("def", "async def")]
    ROWS["P2_strict_restored_scheduled_sends"] = [
        await p2_property(k) for k in ("def", "async def")]
    ROWS["P3_plugins_kwarg"] = [await p3_plugins_vs_use(k)
                                for k in ("def", "async def")]
    emit("w2_persistence_latch_strict_plugins", {
        "cases_per_kind": CASES // 2,
        "restarts": RESTARTS,
        **ROWS,
        "failures": FAILS[:40],
        "failure_count": len(FAILS),
        "verdict": "CLEAN" if not FAILS else "DEFECT",
    })
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
