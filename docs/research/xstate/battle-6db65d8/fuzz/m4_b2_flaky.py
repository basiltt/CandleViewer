"""m4 — is the F2 B2-illegal-configuration hit timing-dependent?

Replays the saved repro N times on the ASYNC engine, with the recorded
event script plus a longer script, and counts how often a compound state
is left with zero active children. The saved config contains `after`
timers, so the hypothesis under test is that an `after` deadline firing
concurrently with an invoke's onError tears the configuration.
"""
from __future__ import annotations
import asyncio, copy, json, os, sys, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
    XStateMachineError,
)
from m3_b2_replay import logic, legality

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.join(HERE, "out", "b2_repro.json")
SCRIPT = ["GO", "PING", "PONG", "X", "NEXT", "GO", "PING", "BACK", "DONE_IT"]


async def one(cfg, script, settle):
    m = create_machine(copy.deepcopy(cfg), logic=logic())
    it = Interpreter(m)
    worst = None
    try:
        await asyncio.wait_for(it.start(), timeout=10)
        for ev in script:
            try:
                await asyncio.wait_for(it.send(ev), timeout=10)
            except XStateMachineError:
                continue
            if settle:
                await asyncio.sleep(settle)
            leg = legality(it)
            if leg != "LEGAL" and worst is None:
                worst = (ev, leg, sorted(it.current_state_ids))
    except Exception as exc:
        worst = worst or ("<harness>", f"{type(exc).__name__}: {exc}", [])
    finally:
        try:
            await asyncio.wait_for(it.stop(), timeout=5)
        except Exception:
            pass
    return worst


async def main_async(cfg, n):
    for settle in (0.0, 0.002, 0.02):
        hits = {}
        for i in range(n):
            w = await one(cfg, SCRIPT, settle)
            if w:
                hits[w[1]] = hits.get(w[1], 0) + 1
        print(f"  async settle={settle:<6} runs={n} illegal={sum(hits.values())} "
              f"{dict(list(hits.items())[:4])}", flush=True)


def main_sync(cfg, n):
    hits = {}
    for i in range(n):
        try:
            it = SyncInterpreter(create_machine(copy.deepcopy(cfg),
                                                logic=logic()))
            it.start()
            for ev in SCRIPT:
                try:
                    it.send(ev)
                except XStateMachineError:
                    continue
                leg = legality(it)
                if leg != "LEGAL":
                    hits[leg] = hits.get(leg, 0) + 1
                    break
        except Exception as exc:
            hits[f"<{type(exc).__name__}>"] = hits.get(
                f"<{type(exc).__name__}>", 0) + 1
    print(f"  sync  runs={n} illegal={sum(hits.values())} "
          f"{dict(list(hits.items())[:4])}", flush=True)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    cfg = json.load(open(REPRO, encoding="utf-8"))["config"]
    main_sync(cfg, n)
    asyncio.run(main_async(cfg, n))
