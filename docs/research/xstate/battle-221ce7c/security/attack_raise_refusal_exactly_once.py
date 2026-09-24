"""New attack: loop-side RAISE refusal from send_threadsafe() under queue
load (#157 reopened / fixed this round) must fire on_event_dropped(reason=
"queue_full") EXACTLY ONCE per refusal -- not zero (the pre-fix bug: only
the unread future saw it) and not more than once (double-count would
corrupt shed-rate metrics an OMS adopter uses for backpressure alarms)."""
import sys, threading, time
sys.path.insert(0, "src")
from xstate_statemachine import (
    create_machine,
    MachineLogic,
    Interpreter,
    OverflowPolicy,
)

CONFIG = {
    "id": "m",
    "initial": "idle",
    "states": {"idle": {"on": {"PING": {"actions": ["noop"]}}}},
}


def noop(ctx, event):
    pass


class CountingPlugin:
    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interp, event, reason):
        self.drops.append(reason)


def main():
    import asyncio

    async def run():
        logic = MachineLogic(actions={"noop": noop})
        machine = create_machine(CONFIG, logic=logic)
        plugin = CountingPlugin()
        interp = Interpreter(
            machine,
            max_queue_size=1,
            overflow_policy=OverflowPolicy.RAISE,
        )
        interp.use(plugin)
        await interp.start()

        # Saturate the queue from many threads simultaneously so several
        # refusals happen concurrently on the loop side. send_threadsafe
        # must be called from a non-loop thread; calling it directly from
        # this coroutine (loop thread) would deadlock waiting on its own
        # run_coroutine_threadsafe result.
        futures = []
        lock = threading.Lock()

        def sender():
            fut = interp.send_threadsafe({"type": "PING"})
            with lock:
                futures.append(fut)

        threads = [threading.Thread(target=sender) for _ in range(200)]
        for t in threads:
            t.start()
        # Do NOT t.join() here -- this coroutine runs ON the event loop
        # thread; a blocking join would stall the loop and prevent it from
        # ever processing the queued sends, deadlocking everything.
        while any(t.is_alive() for t in threads):
            await asyncio.sleep(0.01)
        print(f"threads_done futures_collected={len(futures)}", flush=True)

        refused = 0
        for i, f in enumerate(futures):
            try:
                await asyncio.wrap_future(f)
            except Exception:
                refused += 1
            if i % 50 == 0:
                print(f"  ...{i} refused_so_far={refused}", flush=True)
        print(f"result_collection_done refused={refused}", flush=True)

        await asyncio.sleep(0.2)
        await interp.stop()

        queue_full_drops = plugin.drops.count("queue_full")
        print(f"refused_futures={refused} queue_full_hook_fires={queue_full_drops}")
        # Property: hook fires should equal number of RAISE refusals (exactly
        # once each) -- not zero, not double-counted.
        ok = queue_full_drops == refused and refused > 0
        print("OK: exactly-once queue_full observability" if ok
              else "FAIL: hook fire count does not match refusal count")

    asyncio.run(run())


if __name__ == "__main__":
    main()
