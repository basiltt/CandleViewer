"""m8 — D6-fuzz: `await send(..., wait=True)` never resolves on the async
engine after a self-targeting `after` deadline has fired under a low
`maxIterations`.

Source: F2 captured case out/b2_cap.json (config has
`m.a.a: after {19: "#m.a.a"}` — a delayed transition targeting the
compound state that owns it — and `maxIterations: 1`).

Sequence: start() -> sleep past the 19 ms deadline -> send("GO", wait=True)
never returns (10 s timeout). stop() still works, so the interpreter is
alive; it is the *receipt* that is never delivered. The caller of an OMS
`await send(...)` blocks for ever.

This script: (a) repeats the captured case N times to measure the rate,
(b) ablates the config to isolate the necessary ingredients,
(c) reports the sync-engine behaviour for parity.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, sys, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from m3_b2_replay import logic

HERE = os.path.dirname(os.path.abspath(__file__))
CAP = os.path.join(HERE, "out", "b2_cap.json")
TIMEOUT = 5.0


async def attempt(cfg, pre_sleep=0.022, ev="GO"):
    """Returns 'HANG' / 'ok' / '<Err>' for one start+sleep+send cycle."""
    it = Interpreter(create_machine(copy.deepcopy(cfg), logic=logic()),
                     strict=False)
    try:
        await asyncio.wait_for(it.start(), timeout=TIMEOUT)
    except Exception as exc:
        return f"start:{type(exc).__name__}"
    try:
        await asyncio.sleep(pre_sleep)
        await asyncio.wait_for(it.send(ev, wait=True), timeout=TIMEOUT)
        return "ok"
    except asyncio.TimeoutError:
        return "HANG"
    except Exception as exc:
        return type(exc).__name__
    finally:
        try:
            await asyncio.wait_for(it.stop(), timeout=TIMEOUT)
        except Exception:
            pass


def rate(cfg, trials, pre_sleep=0.022, label=""):
    out = {}
    for _ in range(trials):
        r = asyncio.run(attempt(cfg, pre_sleep))
        out[r] = out.get(r, 0) + 1
    print(f"  {label:44s} {out}", flush=True)
    return out.get("HANG", 0)


def sync_control(cfg, label=""):
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=logic()))
    t = time.time()
    try:
        it.start()
        time.sleep(0.022)
        it.send("GO")
        print(f"  {label:44s} sync ok in {time.time()-t:.2f}s "
              f"states={sorted(it.current_state_ids)} "
              f"ok={getattr(it, 'last_transition_ok', None)}", flush=True)
    except Exception as exc:
        print(f"  {label:44s} sync {type(exc).__name__} "
              f"in {time.time()-t:.2f}s", flush=True)


def main(trials=8):
    cap = json.load(open(CAP, encoding="utf-8"))
    cfg = cap["repro"]["config"]
    print("== captured case, async ==", flush=True)
    rate(cfg, trials, 0.022, "as captured (maxIterations=1, after 19ms)")
    rate(cfg, trials, 0.000, "no sleep (deadline not yet due)")
    sync_control(cfg, "as captured")

    print("== ablations (async, sleep past deadline) ==", flush=True)
    a = copy.deepcopy(cfg)
    a["maxIterations"] = 1000
    rate(a, trials, 0.022, "maxIterations=1000")

    b = copy.deepcopy(cfg)
    b["states"]["a"]["states"]["a"].pop("after", None)
    rate(b, trials, 0.022, "self-targeting `after` removed")

    c = copy.deepcopy(cfg)
    c["states"]["a"]["states"]["a"].pop("invoke", None)
    rate(c, trials, 0.022, "invoke removed")

    d = copy.deepcopy(cfg)
    d.pop("always", None)
    d["states"]["a"].pop("always", None)
    rate(d, trials, 0.022, "root+child `always` removed")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8))
