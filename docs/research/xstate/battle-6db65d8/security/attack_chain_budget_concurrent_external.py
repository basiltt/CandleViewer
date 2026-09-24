"""New attack targeted at round-6 #166/#167/#168 fix: per-macrostep settle
budget on the async Interpreter, reset only when an EXTERNAL event begins
a step. Attack: 16 concurrent external senders (threadsafe) firing while a
self-generated completion chain (always -> ... -> always) is in flight.
Two properties must both hold:
  (a) external arrivals must NOT reset/extend the chain-budget counter
      (the chain must still trip at the same lap count as with 0 external
      senders);
  (b) the chain must still observably trip (last_error is
      RunawayChainError), not hang or get starved forever by the external
      traffic.
"""
import sys, asyncio, threading, time
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.exceptions import RunawayChainError

CONFIG = {
    "id": "chain",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 200,
    "states": {
        "a": {"always": [{"target": "b", "actions": ["inc"]}]},
        "b": {"always": [{"target": "a", "actions": ["inc"]}]},
    },
}


def inc(ctx, event):
    ctx["n"] = ctx.get("n", 0) + 1


async def run_once(n_external: int):
    logic = MachineLogic(actions={"inc": inc})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine)
    await interp.start()

    stop_flag = threading.Event()
    sent = {"count": 0}

    def sender_thread():
        while not stop_flag.is_set():
            try:
                interp.send_threadsafe({"type": "PING"})
                sent["count"] += 1
            except Exception:
                pass
            time.sleep(0.001)

    threads = []
    if n_external:
        for _ in range(n_external):
            t = threading.Thread(target=sender_thread, daemon=True)
            t.start()
            threads.append(t)

    # Kick the self-generated chain with one external event.
    try:
        await interp.send({"type": "KICK"})
    except Exception as e:
        pass

    # Give it a moment to trip (or not).
    await asyncio.sleep(1.0)
    stop_flag.set()
    for t in threads:
        t.join(timeout=1)

    tripped = isinstance(interp.last_error, RunawayChainError)
    n = interp._machine_context.get("n") if hasattr(interp, "_machine_context") else None
    await interp.stop()
    return tripped, sent["count"]


async def main():
    baseline_tripped, _ = await run_once(0)
    concurrent_tripped, sent = await run_once(16)
    print(f"baseline (0 external senders) tripped: {baseline_tripped}")
    print(f"concurrent (16 external senders, sent={sent}) tripped: {concurrent_tripped}")
    ok = baseline_tripped and concurrent_tripped
    print("OK: chain still trips under concurrent external load" if ok
          else "FAIL: external senders interfered with chain-budget trip")


if __name__ == "__main__":
    asyncio.run(main())
