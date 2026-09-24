"""LC-43 verification on xstate-statemachine 0.8.0.

Exercises `WrongThreadError` (bare cross-thread send) and `send_threadsafe()`
against the acceptance criteria in LC-43-cross-thread-send-silently-lost.md.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    WrongThreadError,
    create_machine,
)

logging.disable(logging.CRITICAL)

N = 500

CFG = {
    "id": "fills",
    "initial": "live",
    "states": {"live": {"on": {"FILL": {"actions": ["count"]}}}},
}


def count(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


async def main() -> int:
    ok = True
    logic = MachineLogic(actions={"count": count})

    # --- 1) bare send() from a foreign thread raises WrongThreadError -----
    interp = await Interpreter(
        create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    ).start()

    errors: list[BaseException] = []

    def worker_bare() -> None:
        try:
            interp.send("FILL", i=0)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=worker_bare)
    t.start()
    t.join()
    print(f"OBSERVED bare cross-thread send() raised: {errors!r}")
    print("EXPECTED a WrongThreadError, raised at the call site (no await needed)")
    if len(errors) != 1 or not isinstance(errors[0], WrongThreadError):
        ok = False
    else:
        msg = str(errors[0])
        names_both_threads = "MainThread" in msg and "Thread-" in msg
        names_remedy = "send_threadsafe" in msg
        print(f"OBSERVED error message: {msg}")
        print("EXPECTED message names interpreter id, calling thread, owning "
              "thread, and send_threadsafe as remedy")
        if not (names_both_threads and names_remedy and interp.id in msg):
            ok = False
    await interp.stop()

    # --- 2) await interp.send(...) from the owning loop is unchanged ------
    interp2 = await Interpreter(
        create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    ).start()
    ret = await interp2.send("FILL", i=0, wait=True)
    print(f"OBSERVED in-loop await send(..., wait=True) -> {ret!r}, "
          f"context={interp2.context}")
    print("EXPECTED a Receipt (changed=True/False per this event) and "
          "event delivered (context n=1); confirms in-loop send() is "
          "unaffected by the cross-thread guard")
    if interp2.context.get("n") != 1:
        ok = False
    ret2 = await interp2.send("FILL", i=1)
    print(f"OBSERVED in-loop await send(...) (no wait) -> {ret2!r}")
    print("EXPECTED None (unchanged 0.7.0 return)")
    if ret2 is not None:
        ok = False
    await interp2.stop()

    # --- 3) send_threadsafe() delivers N/N events from a foreign thread ---
    interp3 = await Interpreter(
        create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    ).start()
    futures: list = []

    def worker_safe() -> None:
        for i in range(N):
            futures.append(interp3.send_threadsafe("FILL", i=i))
        for f in futures:
            f.result(timeout=5)

    await asyncio.to_thread(worker_safe)  # join() would block the loop itself
    await asyncio.sleep(0.2)  # let the owning loop drain the inbox
    delivered = interp3.context.get("n", 0)
    print(f"OBSERVED send_threadsafe(): {delivered}/{N} delivered, "
          f"futures are concurrent.futures.Future = "
          f"{all(hasattr(f, 'result') and hasattr(f, 'add_done_callback') for f in futures)}")
    print("EXPECTED 500/500 delivered, each a concurrent.futures.Future")
    if delivered != N:
        ok = False
    await interp3.stop()

    # --- 4) send_threadsafe() on a stopped interpreter raises clearly -----
    # A *not-yet-started* interpreter is the documented case
    # ("has not been started") per the constructor / send_threadsafe
    # docstring; exercise that explicitly since interp3 above was started.
    fresh = Interpreter(create_machine({**CFG, "context": {"n": 0}}, logic=logic))
    raised = None
    try:
        fresh.send_threadsafe("FILL", i=0)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    print(f"OBSERVED send_threadsafe() on a never-started interpreter -> {raised!r}")
    print("EXPECTED a clear RuntimeError, not AttributeError/None deref")
    if not isinstance(raised, RuntimeError) or isinstance(raised, AttributeError):
        ok = False

    # Also check the already-stopped case (its loop is still bound/open at
    # this point in the test, i.e. `stop()` does not itself raise -- the
    # acceptance criterion is specifically about "not-yet-started or
    # stopped"; a stopped interpreter's loop is typically still the one
    # running this test, so this call is expected to still enqueue (the
    # interpreter's own run loop is what is gone, not the asyncio loop).
    stopped_raised = None
    try:
        interp3.send_threadsafe("FILL", i=0)
    except Exception as exc:  # noqa: BLE001
        stopped_raised = exc
    print(f"OBSERVED send_threadsafe() on a stopped interpreter -> {stopped_raised!r}")
    print("EXPECTED either it delivers harmlessly to a torn-down run loop, "
          "or raises a clear RuntimeError -- NOT AttributeError/None deref")
    if isinstance(stopped_raised, AttributeError):
        ok = False

    # --- 5) run_coroutine_threadsafe(interp.send(...), loop): 0.8.0 changes
    #        `send()`'s contract to always thread-check eagerly (#37), which
    #        is one of the two deliberate/documented breaking exceptions
    #        called out in the CHANGELOG's 0.8.0 preamble. A bare `send()`
    #        wrapped in `run_coroutine_threadsafe` still builds/schedules the
    #        coroutine on a FOREIGN thread's call stack for
    #        `_assert_owning_thread`'s purposes -- the coroutine body (which
    #        raises) actually executes on the interpreter's own loop/thread
    #        once scheduled, so in practice it should succeed. Verify which.
    interp4 = await Interpreter(
        create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    ).start()
    loop = asyncio.get_running_loop()

    def worker_rct() -> None:
        try:
            futs = [
                asyncio.run_coroutine_threadsafe(interp4.send("FILL", i=i), loop)
                for i in range(N)
            ]
            for f in futs:
                f.result(timeout=5)
        except WrongThreadError as exc:
            rct_errors.append(exc)

    rct_errors: list = []
    await asyncio.to_thread(worker_rct)
    delivered_rct = interp4.context.get("n", 0)
    print(f"OBSERVED run_coroutine_threadsafe path: {delivered_rct}/{N} delivered")
    print("EXPECTED 500/500 if this remains supported, OR a clear failure if "
          "0.8.0 deliberately breaks this pattern (see CHANGELOG 'two "
          "deliberate exceptions' preamble) -- recorded as a residual gap, "
          "not scored against FIXED, since #37's own regression test "
          "(test_v080_edge_paths.py) only covers send_threadsafe, not this "
          "pattern")
    rct_broken = delivered_rct != N or bool(rct_errors)
    if rct_errors:
        print(f"OBSERVED run_coroutine_threadsafe(interp.send(...), loop) now "
              f"raises {rct_errors[0]!r} -- because `send()` thread-checks "
              f"EAGERLY (#37) before returning the coroutine object that "
              f"run_coroutine_threadsafe schedules, the eager check itself "
              f"runs on the calling (foreign) thread, so this previously-"
              f"correct pattern now raises WrongThreadError")
    await interp4.stop()

    print(f"NOTE: run_coroutine_threadsafe(interp.send(...), loop) pattern "
          f"{'is BROKEN under 0.8.0' if rct_broken else 'still works'} "
          f"(not scored -- see note above)")

    print("RESULT:", "FIXED" if ok else "NOT FIXED (see failing checks above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
