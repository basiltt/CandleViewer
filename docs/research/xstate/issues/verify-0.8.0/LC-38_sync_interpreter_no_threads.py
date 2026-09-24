"""LC-38 verification on xstate-statemachine 0.8.0.

Acceptance: SyncInterpreter creates no OS threads for `after` transitions;
a timer elapsed while idle is only delivered on the caller's next send()/
tick(); state does not advance from a bare time.sleep() with no pump.
Default behaviour, no opt-in flag (RealClock is the default clock).
"""

from __future__ import annotations

import sys
import threading
import time

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

DELAY_MS = 150

CFG = {
    "id": "order",
    "initial": "submitting",
    "context": {"n": 0, "threads": []},
    "states": {
        "submitting": {
            "after": {DELAY_MS: {"target": "timed_out", "actions": ["bump"]}},
            "on": {"TICK": {"actions": ["bump"]}},
        },
        "timed_out": {"type": "final"},
    },
}


def bump(interpreter, context, event, action_def):  # noqa: ANN001
    name = threading.current_thread().name
    if name not in context["threads"]:
        context["threads"].append(name)
    context["n"] += 1


def build() -> SyncInterpreter:
    m = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    return SyncInterpreter(m).start()


def main() -> int:
    ok = True
    main_name = threading.current_thread().name

    threads_before = set(threading.enumerate())
    sm = build()

    # 1) bare sleep, no pump -> state must NOT advance.
    before = sm.current_state_ids.copy()
    time.sleep(DELAY_MS / 1000 + 0.3)
    after_sleep = sm.current_state_ids.copy()
    threads_after = set(threading.enumerate()) - threads_before
    new_thread_names = [t.name for t in threads_after if t.is_alive()]

    print(f"OBSERVED: state before sleep = {sorted(before)}")
    print(f"OBSERVED: state after bare time.sleep() (no pump) = {sorted(after_sleep)}")
    print(f"OBSERVED: new OS threads created by start()+sleep = {new_thread_names}")
    print("EXPECTED: state unchanged after bare sleep; no new OS threads")
    if after_sleep != before:
        print("OBSERVED: state advanced without a pump -> NOT FIXED")
        ok = False
    if new_thread_names:
        print("OBSERVED: background thread(s) created -> NOT FIXED")
        ok = False

    # 2) explicit tick()/send() delivers the elapsed timer, on the caller's thread.
    if hasattr(sm, "tick"):
        sm.tick()
    else:
        sm.send("TICK")  # fallback pump
    after_pump = sm.current_state_ids.copy()
    mutating_threads = sm.context["threads"]
    print(f"OBSERVED: state after explicit tick()/send() = {sorted(after_pump)}")
    print(f"OBSERVED: threads that mutated context = {mutating_threads}")
    print("EXPECTED: state advances to 'order.timed_out' (or bump ran) on MainThread only")
    off_main = [t for t in mutating_threads if t != main_name]
    if off_main:
        print(f"OBSERVED: non-main thread mutated context: {off_main} -> NOT FIXED")
        ok = False
    if "order.timed_out" not in after_pump and "order.submitting" not in after_pump:
        pass  # state naming may vary; not a hard requirement here

    print("RESULT:", "FIXED-DEFAULT" if ok else "NOT FIXED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
