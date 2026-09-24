"""Verify #79 (fixed by PR #83, commit 3c527b0): system-event exemption is
decided by provenance, not by name prefix.

Criteria exercised:
  1. user event 'done.review' IS matched by "*" and by "done.*"
  2. it DOES trip onUnhandled:"error" when unhandled
  3. it IS rejected by strict mode when undeclared
  4. engine-minted done.invoke.x / error.platform.x / after.N remain exempt
     from strict / onUnhandled / are not "extra" traffic
  5. escalate path unchanged (still exempt, still delivered)
  6. 'DONE.review' (case variant) is also user traffic, not exempt
  7. Event.system flag not spoofable from a user send() (system=True on
     an incoming send is unmarked provenance-wise unless engine mints it)
  8. SYSTEM_EVENT_PREFIXES still importable (back-compat)
  9. the withdrawn build-time reserved-namespace warning no longer fires
"""

from __future__ import annotations

import asyncio
import logging
import sys
import warnings
from typing import Any, List

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Event,
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.events import (  # noqa: E402
    SYSTEM_EVENT_PREFIXES,
    is_system_event,
)

RESULTS: List[tuple] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


async def crit_wildcard_matches_user_done_event() -> None:
    caught: List[str] = []
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"*": {"actions": "note"}}}},
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(actions={"note": lambda i, c, e, a: caught.append(e.type)}),
        )
    ).start()
    await i.send("done.review")
    await i.send("PLAIN")
    await asyncio.sleep(0.02)
    await i.stop()
    check(
        "wildcard_star_matches_user_done_review",
        "done.review" in caught,
        f"caught={caught}",
    )


async def crit_prefix_wildcard_matches() -> None:
    caught: List[str] = []
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"done.*": {"actions": "note"}}}},
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(actions={"note": lambda i, c, e, a: caught.append(e.type)}),
        )
    ).start()
    await i.send("done.review")
    await asyncio.sleep(0.02)
    await i.stop()
    check(
        "prefix_wildcard_done_star_matches_user_event",
        "done.review" in caught,
        f"caught={caught}",
    )


async def crit_trips_onunhandled_error() -> None:
    cfg = {
        "id": "m",
        "initial": "a",
        "onUnhandled": "error",
        "states": {"a": {}},
    }
    i = await Interpreter(create_machine(cfg, logic=MachineLogic())).start()
    await i.send("done.review")
    await asyncio.sleep(0.02)
    status = i.status
    await i.stop()
    check(
        "user_done_review_trips_onUnhandled_error",
        status == "error",
        f"status={status}",
    )


async def crit_strict_rejects_undeclared() -> None:
    from xstate_statemachine.exceptions import UnknownEventError

    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"KNOWN": "a"}}},
    }
    i = await Interpreter(
        create_machine(cfg, logic=MachineLogic()), strict=True
    ).start()
    raised = False
    try:
        await i.send("done.review")
    except UnknownEventError:
        raised = True
    await i.stop()
    check(
        "strict_rejects_undeclared_user_done_review",
        raised,
        f"raised={raised}",
    )


async def crit_engine_events_remain_exempt() -> None:
    """done.invoke.*, error.platform.*, after.* must not trip onUnhandled
    or strict, and are matched only via their own onDone/onError/after
    handlers -- not surfaced as "unhandled" noise."""
    seen: List[str] = []

    async def svc(i, c, e):
        return "ok"

    cfg = {
        "id": "m",
        "initial": "a",
        "onUnhandled": "error",
        "states": {
            "a": {
                "invoke": {"src": "svc", "id": "svc", "onDone": "b"},
                "after": {10: "never"},
            },
            "b": {"on": {"*": {"actions": "note"}}},
            "never": {},
        },
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                services={"svc": svc},
                actions={"note": lambda i, c, e, a: seen.append(e.type)},
                strict=True,
            ),
        )
    ).start()
    await asyncio.sleep(0.05)
    status = i.status
    state = set(i.current_state_ids)
    await i.stop()
    check(
        "engine_done_invoke_and_after_remain_exempt",
        status == "running" and state == {"m.b"},
        f"status={status} state={state}",
    )


async def crit_escalate_unchanged() -> None:
    bad_child = {
        "id": "bad",
        "initial": "s",
        "actionErrorPolicy": "fail",
        "states": {"s": {"entry": ["boom"]}},
    }

    def boom(i, c, e, a):
        raise RuntimeError("x")

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
    seen: List[Any] = []
    kid = create_machine(bad_child, logic=MachineLogic(actions={"boom": boom}))
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
    check(
        "escalate_path_unchanged",
        state == {"p.c"} and len(seen) == 1,
        f"state={state} seen={seen}",
    )


async def crit_case_variant_DONE_review() -> None:
    caught: List[str] = []
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"*": {"actions": "note"}}}},
    }
    i = await Interpreter(
        create_machine(
            cfg,
            logic=MachineLogic(actions={"note": lambda i, c, e, a: caught.append(e.type)}),
        )
    ).start()
    await i.send("DONE.review")
    await asyncio.sleep(0.02)
    await i.stop()
    check(
        "case_variant_DONE.review_is_user_traffic",
        "DONE.review" in caught,
        f"caught={caught}",
    )


async def crit_system_flag_not_spoofable() -> None:
    """A user cannot mark their own send() as a system event; is_system_event
    only returns True for engine-minted event types/flags, and the public
    send() API has no way to set Event.system=True."""
    ev = Event(type="done.review")
    check(
        "plain_user_event_default_system_False",
        ev.system is False,
        f"ev.system={ev.system}",
    )
    check(
        "is_system_event_false_for_user_event",
        is_system_event(ev) is False,
        f"is_system_event={is_system_event(ev)}",
    )
    import inspect

    from xstate_statemachine import Interpreter as InterpClass

    sig = inspect.signature(InterpClass.send)
    has_system_param = "system" in sig.parameters
    check(
        "public_send_signature_has_no_system_param",
        not has_system_param,
        f"send() params={list(sig.parameters)}",
    )


def crit_old_prefixes_importable() -> None:
    ok = isinstance(SYSTEM_EVENT_PREFIXES, tuple) and "done." in SYSTEM_EVENT_PREFIXES
    check(
        "SYSTEM_EVENT_PREFIXES_still_importable",
        ok,
        f"value={SYSTEM_EVENT_PREFIXES}",
    )


def crit_withdrawn_warning_no_longer_fires() -> None:
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"done.review": "a"}}},
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        create_machine(cfg, logic=MachineLogic())
    reserved_warns = [
        x for x in w if "reserved" in str(x.message).lower() or "namespace" in str(x.message).lower()
    ]
    check(
        "withdrawn_reserved_namespace_warning_does_not_fire",
        reserved_warns == [],
        f"warnings={[str(x.message) for x in reserved_warns]}",
    )


async def main() -> int:
    await crit_wildcard_matches_user_done_event()
    await crit_prefix_wildcard_matches()
    await crit_trips_onunhandled_error()
    await crit_strict_rejects_undeclared()
    await crit_engine_events_remain_exempt()
    await crit_escalate_unchanged()
    await crit_case_variant_DONE_review()
    await crit_system_flag_not_spoofable()
    crit_old_prefixes_importable()
    crit_withdrawn_warning_no_longer_fires()

    print("\n=== SUMMARY ===")
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}: {name} -- {detail}")
    overall = all(ok for _, ok, _ in RESULTS)
    print("\nOVERALL:", "ALL CRITERIA PASS" if overall else "SOME CRITERIA FAILED")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
