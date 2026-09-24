"""m9 — D6-fuzz-1 MINIMAL repro (8 lines of config).

`await Interpreter.send(EV, wait=True)` never resolves when the event
re-enters a compound state whose `always` descends into a child that
carries an `invoke`, after the first invoke has already completed.

  * 100 % reproducible, no timing race beyond "the first invoke finished".
  * Unaffected by `maxIterations` (1 and 1000 both hang).
  * `stop()` still returns, so the interpreter is alive: it is the receipt
    that is never delivered.
  * The SYNC engine on the same config returns normally — a parity break.

Both ingredients are necessary (ablated in m8 and below): remove the
`always` or remove the `invoke` and the send resolves.
"""
from __future__ import annotations
import asyncio, copy, logging, sys, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
)

TIMEOUT = 5.0

CFG = {
    "id": "m", "initial": "a",
    "on": {"GO": {"target": "#m.a", "internal": True}},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m.a.a", "guard": "g"},
            "states": {"a": {"invoke": {"id": "i", "src": "svc"}}},
        },
    },
}


def logic():
    return MachineLogic(
        actions={}, guards={"g": lambda c, e: True},
        services={"svc": lambda i, c, e: {"ok": 1}},
    )


async def probe(cfg, label, settle=0.02):
    it = Interpreter(create_machine(copy.deepcopy(cfg), logic=logic()),
                     strict=False)
    await asyncio.wait_for(it.start(), timeout=TIMEOUT)
    await asyncio.sleep(settle)
    t = time.time()
    try:
        await asyncio.wait_for(it.send("GO", wait=True), timeout=TIMEOUT)
        out = f"resolved in {time.time()-t:.2f}s states={sorted(it.current_state_ids)}"
    except asyncio.TimeoutError:
        out = f"HANG (no receipt after {TIMEOUT}s)"
    except Exception as exc:
        out = f"{type(exc).__name__}: {exc}"
    alive = it.status
    try:
        await asyncio.wait_for(it.stop(), timeout=TIMEOUT)
        stopped = "stop() ok"
    except Exception as exc:
        stopped = f"stop() {type(exc).__name__}"
    print(f"  async {label:38s} {out}  status={alive} {stopped}", flush=True)
    return out.startswith("HANG")


def probe_sync(cfg, label, settle=0.02):
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=logic()))
    it.start()
    time.sleep(settle)
    t = time.time()
    try:
        it.send("GO")
        print(f"  sync  {label:38s} returned in {time.time()-t:.2f}s "
              f"states={sorted(it.current_state_ids)} "
              f"ok={getattr(it, 'last_transition_ok', None)} "
              f"err={type(getattr(it, 'last_error', None)).__name__}",
              flush=True)
    except Exception as exc:
        print(f"  sync  {label:38s} {type(exc).__name__}: {exc}", flush=True)


def main():
    hangs = 0
    print("== minimal config ==", flush=True)
    for mi in (1, 1000):
        c = copy.deepcopy(CFG)
        c["maxIterations"] = mi
        hangs += asyncio.run(probe(c, f"maxIterations={mi}"))
    probe_sync(CFG, "baseline")

    print("== necessity ablations (async) ==", flush=True)
    a = copy.deepcopy(CFG)
    a["states"]["a"].pop("always")
    asyncio.run(probe(a, "always removed"))
    b = copy.deepcopy(CFG)
    b["states"]["a"]["states"]["a"].pop("invoke")
    asyncio.run(probe(b, "invoke removed"))
    c = copy.deepcopy(CFG)
    c["on"]["GO"]["internal"] = False
    hangs += asyncio.run(probe(c, "external (non-internal) GO"))
    d = copy.deepcopy(CFG)
    asyncio.run(probe(d, "no settle (invoke still running)", settle=0.0))

    print(f"\nHANGS: {hangs}")
    return 1 if hangs else 0


if __name__ == "__main__":
    sys.exit(main())
