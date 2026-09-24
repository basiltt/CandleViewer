"""Verify #99 on main@3ed3099: SyncInterpreter delivers onError for a failed
invoked child machine, with parity to the async engine, on both:
(a) parent has an onError handler -> transitions there
(b) parent has NO onError handler -> unhandled child failure fails the parent
    (status='error', error set) instead of parking forever in the invoking
    state with status='running', error=None.

Also checks the async engine for the same two scenarios (parity claim in
CHANGELOG: "an unhandled invoked-child failure fails the parent on both
(#99)").
"""
import asyncio
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def boom(i, c, e, a):
    raise ValueError("child boom")


BAD = {
    "id": "bad",
    "initial": "s",
    "actionErrorPolicy": "fail",
    "states": {"s": {"entry": ["boom"]}},
}


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 15))


# --- (a) parent WITH onError handler ---
PARENT_HANDLED = {
    "id": "p",
    "initial": "w",
    "states": {
        "w": {"invoke": {"src": "kid", "id": "kid", "onError": "failed"}},
        "failed": {},
    },
}


def logic_handled():
    return MachineLogic(
        services={"kid": create_machine(BAD, logic=MachineLogic(actions={"boom": boom}))}
    )


s = SyncInterpreter(create_machine(PARENT_HANDLED, logic=logic_handled()))
s.start()
for _ in range(100):
    if "p.failed" in s.current_state_ids or s.status != "running":
        break
    s.tick()
    time.sleep(0.01)
check("(a) sync: handled onError -> p.failed", "p.failed" in s.current_state_ids, s.current_state_ids)


async def main_handled():
    i = await Interpreter(create_machine(PARENT_HANDLED, logic=logic_handled())).start()
    await asyncio.sleep(0.2)
    st = set(i.current_state_ids)
    try:
        await asyncio.wait_for(i.stop(), 2)
    except Exception:
        pass
    return st


a_state = _run(main_handled())
check("(a) async: handled onError -> p.failed", "p.failed" in a_state, a_state)

# --- (b) parent WITHOUT onError handler ---
PARENT_UNHANDLED = {
    "id": "p2",
    "initial": "w",
    "states": {"w": {"invoke": {"src": "kid", "id": "kid"}}},
}


def logic_unhandled():
    return MachineLogic(
        services={"kid": create_machine(BAD, logic=MachineLogic(actions={"boom": boom}))}
    )


s2 = SyncInterpreter(create_machine(PARENT_UNHANDLED, logic=logic_unhandled()))
s2.start()
for _ in range(100):
    if s2.status == "error":
        break
    s2.tick()
    time.sleep(0.01)
check("(b) sync: unhandled child failure -> parent status=error", s2.status == "error", s2.status)
check("(b) sync: parent.error set", s2.error is not None, s2.error)


async def main_unhandled():
    i = await Interpreter(create_machine(PARENT_UNHANDLED, logic=logic_unhandled())).start()
    await asyncio.sleep(0.2)
    out = (i.status, i.error)
    try:
        await asyncio.wait_for(i.stop(), 2)
    except Exception:
        pass
    return out


a_status, a_err = _run(main_unhandled())
check("(b) async: unhandled child failure -> parent status=error", a_status == "error", a_status)
check("(b) async: parent.error set", a_err is not None, a_err)

ok = True
for name, passed, detail in results:
    print(f"{'PASS' if passed else 'FAIL'}: {name}  {detail if not passed else ''}")
    ok = ok and passed

sys.exit(0 if ok else 1)
