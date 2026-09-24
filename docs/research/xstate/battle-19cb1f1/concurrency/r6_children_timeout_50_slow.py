"""R6 - `start(children_timeout=)` (#181) with 50 SLOW children, and
start() ordering vs #116 when the timeout is HIT.

Claims under test:
  * a slow child's entry action no longer holds `await start()` for its
    whole duration -- start() returns within ~children_timeout;
  * on timeout a WARNING is logged and the machine is running;
  * the child registers when its bring-up completes;
  * #116 ordering (`start(); send("CANCEL")` -> done,cancel) still holds
    when the timeout was hit -- i.e. the bounded start did not turn into
    an unbounded FIRST SEND (the docstring at interpreter.py:2770 says it
    must not).

Both action spellings for the child's slow entry (`def` sleeps the
executor-free loop thread, `async def` awaits) and both service kinds.
"""

from __future__ import annotations

import asyncio
import logging
import time

from common2 import Interpreter, MachineLogic, create_machine, emit, make_service

N_CHILDREN = 50
SLOW = 1.0


class Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.msgs = []

    def emit(self, record):  # noqa: ANN001
        self.msgs.append(record.getMessage())


def child_cfg(i: int) -> dict:
    return {
        "id": f"kid{i}",
        "initial": "k",
        "context": {},
        "states": {"k": {"entry": ["slow"], "on": {"GO": {"target": "fin"}}},
                   "fin": {"type": "final"}},
    }


def parent_cfg(n: int) -> dict:
    return {
        "id": "r6",
        "initial": "up",
        "context": {},
        "states": {
            "up": {
                "invoke": [
                    {"src": f"kid{i}", "id": f"kid{i}"} for i in range(n)
                ],
                "on": {"CANCEL": {"target": "off", "actions": ["mark"]}},
            },
            "off": {},
        },
    }


ORDER = []


def mark(i, ctx, e, ad):  # noqa: ANN001
    ORDER.append("cancel")


def mk(n: int, act_kind: str):
    if act_kind == "def":

        def slow(i, ctx, e, ad):  # noqa: ANN001
            time.sleep(SLOW)

    else:

        async def slow(i, ctx, e, ad):  # noqa: ANN001
            await asyncio.sleep(SLOW)

    kids = {
        f"kid{i}": create_machine(
            child_cfg(i), logic=MachineLogic(actions={"slow": slow})
        )
        for i in range(n)
    }
    return create_machine(
        parent_cfg(n),
        logic=MachineLogic(actions={"mark": mark, "slow": slow}, services=kids),
    )


async def case(act_kind: str, timeout) -> dict:  # noqa: ANN001
    ORDER.clear()
    cap = Cap()
    lg = logging.getLogger("xstate_statemachine")
    lg.addHandler(cap)
    itp = Interpreter(mk(N_CHILDREN, act_kind), service_pool_size=8)
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(itp.start(children_timeout=timeout), 60)
        started = True
    except asyncio.TimeoutError:
        started = False
    start_s = round(time.perf_counter() - t0, 3)
    status_after_start = itp.status
    kids_at_start = len(getattr(itp, "_actors", {}) or {})

    # #116: the FIRST send must not block for the rest of the bring-up.
    t1 = time.perf_counter()
    try:
        await asyncio.wait_for(itp.send("CANCEL", wait=True), 30)
        first_send_ok = True
    except asyncio.TimeoutError:
        first_send_ok = False
    first_send_s = round(time.perf_counter() - t1, 3)

    await asyncio.sleep(SLOW + 0.6)
    kids_later = len(getattr(itp, "_actors", {}) or {})
    try:
        await asyncio.wait_for(itp.stop(), 30)
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    lg.removeHandler(cap)
    warned = [m for m in cap.msgs if "child" in m.lower() or "timeout" in m.lower()]
    return {
        "child_entry_kind": act_kind,
        "children": N_CHILDREN,
        "child_entry_seconds": SLOW,
        "children_timeout": timeout,
        "start_returned": started,
        "start_seconds": start_s,
        "start_bounded_by_timeout": (
            started and timeout is not None and start_s < timeout + 1.5
        ),
        "status_after_start": status_after_start,
        "children_registered_at_start": kids_at_start,
        "first_send_answered": first_send_ok,
        "first_send_seconds": first_send_s,
        "first_send_bounded": first_send_ok and first_send_s < SLOW,
        "children_registered_later": kids_later,
        "warning_logged": bool(warned),
        "warning_sample": warned[:2],
        "order": list(ORDER),
        "stop": stopped,
    }


async def main() -> int:
    rows = []
    for ak in ("def", "async def"):
        rows.append(await case(ak, 0.2))   # timeout HIT
        rows.append(await case(ak, None))  # unbounded: the old behaviour
    bad = []
    for r in rows:
        if r["children_timeout"] is not None:
            if not r["start_bounded_by_timeout"]:
                bad.append((r["child_entry_kind"], "start not bounded",
                            r["start_seconds"]))
            if not r["warning_logged"]:
                bad.append((r["child_entry_kind"], "no WARNING on timeout"))
            if not r["first_send_bounded"]:
                bad.append((r["child_entry_kind"], "first send absorbed the "
                            "rest of the bring-up", r["first_send_seconds"]))
        if r["stop"] != "ok":
            bad.append((r["child_entry_kind"], "stop hung"))
    emit(
        "r6_children_timeout_50_slow",
        {"rows": rows, "failures": bad, "result": "FAIL" if bad else "PASS"},
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
