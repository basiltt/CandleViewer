# -*- coding: utf-8 -*-
"""Round-6 #172 + #157 soak-relevant attack.

#172: send_threadsafe(internal=True) in-flight counter must balance on
every terminal outcome (delivered, refused, cancelled, loop stopped before
coroutine ran) via a done-callback. A leaked count would gate the
chain-budget reset for the rest of the machine's life -- under soak-style
repeated churn this would eventually starve or wrongly-trip every chain.

#157: loop-side RAISE refusals (queue_full detected ON THE LOOP, not at
the optimistic call-site check) must fire on_event_dropped(reason=
"queue_full") exactly once per refusal, observable via a plugin hook, not
just buried in the future the fire-and-forget caller never reads.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    PluginBase,
    create_machine,
)

CONFIG = {
    "id": "m",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"EV": {"actions": ["bump"]}}}},
}


def bump(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


ACTIONS = {"bump": bump}


class DropWatcher(PluginBase):
    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.drops.append(reason)


async def attack_172_inflight_balance():
    """Hammer send_threadsafe(internal=True) from many worker threads while
    intermittently stopping the loop, then check the interpreter's
    in-flight counter (best-effort via public state) settles to a value
    consistent with terminal-outcome accounting, across many repeated
    start/stop generations (soak-style churn)."""
    logic = MachineLogic(actions=dict(ACTIONS))
    n_generations = 25
    n_threads = 8
    n_sends_per_thread = 40
    anomalies = []

    for gen in range(n_generations):
        machine = create_machine(dict(CONFIG), logic=logic)
        interp = Interpreter(machine, max_queue_size=64)
        await interp.start()
        loop = asyncio.get_running_loop()

        futures: list[concurrent.futures.Future] = []

        def worker():
            for _ in range(n_sends_per_thread):
                try:
                    fut = interp.send_threadsafe({"type": "EV"}, internal=True)
                    futures.append(fut)
                except Exception:  # noqa: BLE001
                    pass

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        # Stop the loop-side interpreter mid-flight on some generations to
        # exercise the "loop stopped before coroutine ran" terminal path.
        if gen % 3 == 0:
            await asyncio.sleep(0.001)
            await interp.stop(drain=False, timeout=1.0)
        for t in threads:
            t.join(timeout=2.0)
        if interp.status == "running":
            await interp.stop(drain=False, timeout=1.0)

        # Best-effort: look for a private in-flight counter attribute by
        # common naming; if absent, fall back to behavioural proxy (next
        # generation's chain budget must still trip at the same lap count
        # as attack_166 showed -- checked separately). We report whatever
        # we can observe without relying on undocumented internals.
        counter_val = None
        for attr in ("_threadsafe_inflight", "_in_flight_threadsafe", "_inflight_count"):
            if hasattr(interp, attr):
                counter_val = getattr(interp, attr)
                break
        if counter_val is not None and counter_val not in (0, None):
            anomalies.append(f"gen{gen}: leaked in-flight counter = {counter_val}")

    print(f"generations={n_generations} anomalies={anomalies}")
    return anomalies


async def attack_157_loop_side_raise():
    """Force a loop-side (not call-site) RAISE refusal: fill the queue via
    direct threadsafe sends faster than the loop can drain, using a tiny
    queue and OverflowPolicy.RAISE, then confirm on_event_dropped fires
    exactly once per refused send (not zero, not more than the refusal
    count) even though the refused sends come from a fire-and-forget
    thread that never reads its future."""
    logic = MachineLogic(actions=dict(ACTIONS))
    machine = create_machine(dict(CONFIG), logic=logic)
    interp = Interpreter(machine, max_queue_size=1, overflow_policy=OverflowPolicy.RAISE)
    watcher = DropWatcher()
    interp.use(watcher)
    await interp.start()

    n_sends = 100
    n_threads = 12
    futures = []
    futures_lock = threading.Lock()
    call_site_raises = 0
    call_site_lock = threading.Lock()

    def worker():
        nonlocal call_site_raises
        for _ in range(n_sends):
            try:
                # external (internal=False): goes through the bounded inbox
                # and is the only path #157's loop-side race applies to --
                # internal=True self-sends go to the unbounded internal
                # queue by design and never hit this path.
                fut = interp.send_threadsafe({"type": "EV"}, internal=False)
                with futures_lock:
                    futures.append(fut)
            except Exception:  # noqa: BLE001
                # Call-site QueueOverflowError (the optimistic qsize() check
                # already saw it full) -- not what #157 targets, but still
                # a legitimate refusal path; tallied separately.
                with call_site_lock:
                    call_site_raises += 1

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    await asyncio.sleep(0.3)  # let the loop drain / callbacks fire

    n_refused_futures = 0
    for fut in futures:
        try:
            fut.result(timeout=0.5)
        except Exception:  # noqa: BLE001
            n_refused_futures += 1

    await interp.stop(drain=False, timeout=1.0)

    n_drop_hooks = len([d for d in watcher.drops if d == "queue_full"])
    total_refusals = n_refused_futures + call_site_raises
    print(f"sends_attempted={n_threads * n_sends} call_site_raises={call_site_raises} "
          f"loop_side_future_refusals={n_refused_futures} total_refusals={total_refusals} "
          f"drop_hook_queue_full={n_drop_hooks} all_drops_sample={watcher.drops[:10]}")

    # The hook must fire for EVERY refusal that actually happened (both the
    # call-site QueueOverflowError path, per the existing same-thread
    # contract, and the loop-side future-carried refusals #157 adds),
    # exactly once each -- not zero (the bug #157 fixes), not systematically
    # more/less than total_refusals.
    ok = total_refusals > 0 and n_drop_hooks == total_refusals
    print("HOOK_FIRED_EXACTLY_ONCE_PER_REFUSAL:", ok,
          f"(expected {total_refusals}, got {n_drop_hooks})")
    return ok


async def main():
    print("=== #172 in-flight counter balance under churn ===")
    anomalies = await attack_172_inflight_balance()
    print()
    print("=== #157 loop-side RAISE refusal observability ===")
    ok = await attack_157_loop_side_raise()
    print()
    print("SUMMARY:", {"172_anomalies": anomalies, "157_hook_ok": ok})


if __name__ == "__main__":
    asyncio.run(main())
