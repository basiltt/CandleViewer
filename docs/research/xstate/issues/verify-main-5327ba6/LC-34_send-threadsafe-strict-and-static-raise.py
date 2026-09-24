"""LC-34 (GH #51) verification on xstate-statemachine main @ 5327ba6.

Acceptance criteria under test (per issue #51 + task "need"):

  1. `send_threadsafe()` applies `strict` AND `event_schemas`: an unknown
     event type raises `UnknownEventError`, and a payload a schema rejects
     raises `InvalidEventPayloadError` -- BOTH on the CALLING thread, BEFORE
     anything is enqueued (i.e. before `run_coroutine_threadsafe` is even
     invoked).
  2. Static (literal-string) `raise` targets are validated at BUILD time on
     `strict` machines, with a "Did you mean ...?" suggestion when a close
     match exists.
  3. A dynamic (callable) `raise` target is still only checked at RUNTIME
     (build succeeds even if the callable could in principle return an
     unknown event; the runtime `_check_strict` catches an actual bad value).

Exits 0 only if every criterion passes.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any, List, Tuple

from xstate_statemachine import (
    Interpreter,
    InvalidConfigError,
    InvalidEventPayloadError,
    MachineLogic,
    UnknownEventError,
    create_machine,
)

RESULTS: List[Tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


ORDER_CFG = {
    "id": "order",
    "strict": True,
    "initial": "pending",
    "context": {"n": 0},
    "states": {
        "pending": {
            "on": {
                "FILL": {"target": "filled", "actions": ["bump"]},
            },
        },
        "filled": {"type": "final"},
    },
}


def bump(interpreter, context, event, action_def):  # noqa: ANN001
    context["n"] += 1


def fill_schema(payload: dict) -> None:
    qty = payload.get("qty")
    if not isinstance(qty, (int, float)):
        raise ValueError("qty must be numeric")


async def check_send_threadsafe_strict_and_schema() -> None:
    machine = create_machine(
        ORDER_CFG,
        logic=MachineLogic(actions={"bump": bump}),
        event_schemas={"FILL": fill_schema},
    )
    interp = await Interpreter(machine).start()

    # -- 1a. unknown event type via send_threadsafe from ANOTHER thread ----
    errors: dict = {}

    def worker_unknown() -> None:
        try:
            interp.send_threadsafe("FILLL")
            errors["unknown"] = None
        except UnknownEventError as exc:
            errors["unknown"] = exc
        except Exception as exc:  # noqa: BLE001
            errors["unknown"] = exc

    t = threading.Thread(target=worker_unknown)
    t.start()
    t.join()

    record(
        "1a. send_threadsafe() raises UnknownEventError for an undeclared "
        "event type, on the calling (foreign) thread",
        isinstance(errors.get("unknown"), UnknownEventError),
        f"raised = {errors.get('unknown')!r}",
    )
    await asyncio.sleep(0.05)
    record(
        "1a-bis. the unknown event was never queued/processed (state "
        "unchanged, n unchanged)",
        interp.current_state_ids == {"order.pending"} and interp.context["n"] == 0,
        f"state = {sorted(interp.current_state_ids)}, n = {interp.context['n']}",
    )

    # -- 1b. schema-rejected payload via send_threadsafe --------------------
    def worker_bad_payload() -> None:
        try:
            interp.send_threadsafe("FILL", qty="not-a-number")
            errors["payload"] = None
        except InvalidEventPayloadError as exc:
            errors["payload"] = exc
        except Exception as exc:  # noqa: BLE001
            errors["payload"] = exc

    t2 = threading.Thread(target=worker_bad_payload)
    t2.start()
    t2.join()

    record(
        "1b. send_threadsafe() raises InvalidEventPayloadError for a "
        "schema-rejected payload, on the calling (foreign) thread",
        isinstance(errors.get("payload"), InvalidEventPayloadError),
        f"raised = {errors.get('payload')!r}",
    )
    await asyncio.sleep(0.05)
    record(
        "1b-bis. the bad-payload event was never queued/processed",
        interp.current_state_ids == {"order.pending"} and interp.context["n"] == 0,
        f"state = {sorted(interp.current_state_ids)}, n = {interp.context['n']}",
    )

    # -- 1c. a VALID send_threadsafe still works -----------------------------
    fut = interp.send_threadsafe("FILL", qty=100)
    await asyncio.wrap_future(fut)
    await asyncio.sleep(0.05)
    record(
        "1c. a valid send_threadsafe() still enqueues and processes normally",
        interp.current_state_ids == {"order.filled"} and interp.context["n"] == 1,
        f"state = {sorted(interp.current_state_ids)}, n = {interp.context['n']}",
    )
    await interp.stop()


def check_static_raise_validation_at_build_time() -> None:
    # A `raise` targeting an event NOT in the machine's declared descriptor
    # set, with a close match available, must fail at create_machine() time
    # on a strict machine, with a "Did you mean" suggestion.
    cfg = {
        "id": "raiser",
        "strict": True,
        "initial": "a",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "actions": [
                            {"type": "raise", "params": {"event": "DOEN"}}
                        ]
                    }
                },
            },
            "b": {},
        },
    }
    # Add a real declared event 'DONE' elsewhere so 'DOEN' has a close match.
    cfg["states"]["a"]["on"]["DONE"] = {"target": "b"}

    try:
        create_machine(cfg, logic=MachineLogic())
        err: Any = None
    except InvalidConfigError as exc:
        err = exc
    except Exception as exc:  # noqa: BLE001
        err = exc

    record(
        "2a. static `raise` target not in descriptor set fails at build "
        "time on a strict machine (InvalidConfigError)",
        isinstance(err, InvalidConfigError),
        f"raised = {err!r}",
    )
    msg = str(err) if err else ""
    record(
        "2b. build-time error suggests the close match ('Did you mean ...DONE...?')",
        "DONE" in msg and "mean" in msg.lower(),
        f"message = {msg!r}",
    )

    # A static raise target that IS declared must build fine.
    cfg_ok = {
        "id": "raiser_ok",
        "strict": True,
        "initial": "a",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "actions": [
                            {"type": "raise", "params": {"event": "DONE"}}
                        ]
                    },
                    "DONE": {"target": "b"},
                },
            },
            "b": {},
        },
    }
    try:
        create_machine(cfg_ok, logic=MachineLogic())
        ok_build_err = None
    except Exception as exc:  # noqa: BLE001
        ok_build_err = exc
    record(
        "2c. a static `raise` target that IS declared builds without error",
        ok_build_err is None,
        f"raised = {ok_build_err!r}",
    )


async def check_dynamic_raise_still_runtime_checked() -> None:
    # A dynamic (callable) raise target is NOT validated at build time
    # (cannot be, statically) but IS still checked at runtime under strict.
    cfg = {
        "id": "dyn_raiser",
        "strict": True,
        "initial": "a",
        # `raise`'s guardrail runs inside `_execute_actions`, whose failures
        # are routed through `_apply_action_error_policy`; the default
        # `"continue"` policy would contain the UnknownEventError as an
        # ordinary action error (logged, hooked, transition committed) and
        # leave nothing exceptional to observe from the caller's side. Using
        # `"fail"` here surfaces it as an observable error status -- it does
        # not change what strict mode validates, only how loudly the
        # resulting failure is reported.
        "actionErrorPolicy": "fail",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "actions": [
                            {
                                "type": "raise",
                                "params": {
                                    "event": lambda ctx_evt: "NOPE_TYPO"
                                },
                            }
                        ]
                    },
                    "DONE": {"target": "b"},
                },
            },
            "b": {},
        },
    }

    build_err = None
    try:
        machine = create_machine(cfg, logic=MachineLogic())
    except Exception as exc:  # noqa: BLE001
        build_err = exc
        machine = None

    record(
        "3a. a dynamic raise target does not fail at build time (cannot be "
        "statically validated)",
        build_err is None,
        f"build error = {build_err!r}",
    )

    if machine is not None:
        interp = await Interpreter(machine).start()
        # `send()` only enqueues; `wait=True` resolves after the macrostep
        # (and whatever action-error handling it triggered) has completed.
        await interp.send("GO", wait=True)
        runtime_err = interp.error
        cause = getattr(runtime_err, "__cause__", None)
        record(
            "3b. the dynamic raise's actual (unknown) event type is still "
            "caught at RUNTIME under strict (surfaces via interpreter.error, "
            "chained from an UnknownEventError naming the unknown event)",
            isinstance(cause, UnknownEventError) and "NOPE_TYPO" in str(cause),
            f"interp.status = {interp.status!r}, interp.error = {runtime_err!r}, "
            f"__cause__ = {cause!r}",
        )
        await interp.stop()


def main() -> int:
    asyncio.run(check_send_threadsafe_strict_and_schema())
    check_static_raise_validation_at_build_time()
    asyncio.run(check_dynamic_raise_still_runtime_checked())

    print()
    all_ok = all(ok for _, ok, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'OK ' if ok else 'XX '} {name}")
    print(f"\nRESULT: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
