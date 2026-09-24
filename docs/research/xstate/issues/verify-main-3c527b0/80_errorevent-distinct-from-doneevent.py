"""Verify #80 (fixed by PR #83, commit 3c527b0): ErrorEvent(type, error, src)
for service/child failures; DoneEvent only for success; .data deprecated.

Criteria exercised:
  1. isinstance ErrorEvent for service failure
  2. .error is the actual exception instance
  3. .src is the failing invoke id
  4. DoneEvent never carries an exception (never used for failure)
  5. .data on ErrorEvent warns DeprecationWarning but still aliases .error
  6. onError target works (transition taken)
  7. child-actor (machine) failure also delivers ErrorEvent
  8. sync engine parity (SyncInterpreter delivers ErrorEvent too)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import warnings
from typing import Any, List

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    ErrorEvent,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.events import DoneEvent  # noqa: E402

RESULTS: List[tuple] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


async def crit_async_service_failure() -> None:
    seen: List[Any] = []

    async def failing(i, c, e):
        raise ValueError("boom")

    cfg = {
        "id": "svc",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "src": "failing",
                    "id": "failing",
                    "onError": {"target": "b", "actions": "note"},
                }
            },
            "b": {},
        },
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"note": lambda i, c, e, a: seen.append(e)},
                services={"failing": failing},
            ),
        )
    ).start()
    await asyncio.sleep(0.05)
    state = set(i.current_state_ids)
    await i.stop()

    ok_isinstance = len(seen) == 1 and isinstance(seen[0], ErrorEvent)
    check("isinstance_ErrorEvent", ok_isinstance, f"seen={seen}")
    if ok_isinstance:
        ev = seen[0]
        check("error_is_the_exception", isinstance(ev.error, ValueError) and str(ev.error) == "boom", f"error={ev.error!r}")
        check("src_is_failing_invoke_id", ev.src == "failing", f"src={ev.src}")
        check("not_isinstance_DoneEvent", not isinstance(ev, DoneEvent), "")
    check("onError_target_taken", state == {"svc.b"}, f"state={state}")


async def crit_done_never_carries_exception() -> None:
    async def ok_svc(i, c, e):
        return "result"

    cfg = {
        "id": "svc",
        "initial": "a",
        "states": {"a": {"invoke": {"src": "ok", "id": "ok", "onDone": "b"}}, "b": {}},
    }
    seen: List[Any] = []
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(services={"ok": ok_svc}),
        )
    ).use(
        type(
            "P",
            (),
            {"on_service_done": lambda self, interp, inv, result: seen.append(result)},
        )()
    ).start()
    await asyncio.sleep(0.05)
    await i.stop()
    check(
        "done_event_success_path_no_exception",
        seen == ["result"],
        f"seen={seen}",
    )


def crit_data_alias_deprecated() -> None:
    ev = ErrorEvent("error.platform.x", ValueError("v"), "x")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        alias = ev.data
    check("data_alias_is_error", alias is ev.error, f"alias={alias!r}")
    check(
        "data_access_warns_DeprecationWarning",
        any(x.category is DeprecationWarning for x in w),
        f"warnings={[str(x.category) for x in w]}",
    )


async def crit_child_machine_failure_error_event() -> None:
    seen: List[Any] = []
    bad = {
        "id": "bad",
        "initial": "s",
        "actionErrorPolicy": "fail",
        "states": {"s": {"entry": ["boom"]}},
    }

    def boom(i, c, e, a):
        raise RuntimeError("child exploded")

    cfg = {
        "id": "p",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"src": "kid", "onError": {"target": "c", "actions": "note"}},
            },
            "c": {},
        },
    }
    kid = create_machine(bad, logic=MachineLogic(actions={"boom": boom}))
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"note": lambda i, c, e, a: seen.append(e)},
                services={"kid": kid},
            ),
        )
    ).start()
    await asyncio.sleep(0.05)
    state = set(i.current_state_ids)
    await i.stop()
    ok = state == {"p.c"} and len(seen) == 1 and isinstance(seen[0], ErrorEvent)
    check(
        "child_machine_failure_delivers_error_event",
        ok,
        f"state={state} seen={seen}",
    )
    if ok:
        check("child_error_wraps_exception", isinstance(seen[0].error, Exception), f"error={seen[0].error!r}")


def crit_sync_engine_parity() -> None:
    seen: List[Any] = []

    def failing(i, c, e):
        raise ValueError("sync boom")

    cfg = {
        "id": "svc",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {
                    "src": "failing",
                    "id": "failing",
                    "onError": {"target": "b", "actions": "note"},
                }
            },
            "b": {},
        },
    }
    i = SyncInterpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={"note": lambda i, c, e, a: seen.append(e)},
                services={"failing": failing},
            ),
        )
    ).start()
    i.tick()
    state = set(i.current_state_ids)
    i.stop()
    ok = len(seen) == 1 and isinstance(seen[0], ErrorEvent)
    check(
        "sync_engine_delivers_error_event",
        ok,
        f"state={state} seen={seen}",
    )
    if ok:
        check(
            "sync_engine_error_is_exception_and_state_transitioned",
            isinstance(seen[0].error, ValueError) and state == {"svc.b"},
            f"error={seen[0].error!r} state={state}",
        )


async def main() -> int:
    await crit_async_service_failure()
    await crit_done_never_carries_exception()
    crit_data_alias_deprecated()
    await crit_child_machine_failure_error_event()
    crit_sync_engine_parity()

    print("\n=== SUMMARY ===")
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}: {name} -- {detail}")
    overall = all(ok for _, ok, _ in RESULTS)
    print("\nOVERALL:", "ALL CRITERIA PASS" if overall else "SOME CRITERIA FAILED")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
