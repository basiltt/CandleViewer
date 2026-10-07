"""Verify #232 on v0.9.0/main: RuntimeWarning fires for dropped guard
(sync def action calling send(wait=True) and dropping result); silent for
ensure_future/.result()/await (matrix across def/async def and
Interpreter/SyncInterpreter where relevant).

STANDALONE: stdlib + xstate_statemachine only. Neutral cwd <home>.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, asyncio, warnings

sys.path.insert(
    0,
    str(_XS / 'src'),
)
from xstate_statemachine import create_machine, MachineLogic, Interpreter  # noqa: E402

failures = []


def build(action_impl):
    cfg = {
        "id": "m", "initial": "s1", "actionErrorPolicy": "rollback",
        "states": {
            "s1": {"on": {"A": {"target": "s2", "actions": ["my_action"]}}},
            "s2": {"on": {"B": "s3"}},
            "s3": {"type": "final"},
        },
    }
    return create_machine(cfg, logic=MachineLogic(actions={"my_action": action_impl}))


async def case_def_dropped():
    """def action, send(wait=True) result dropped -> RuntimeWarning."""
    result = {}

    def my_action(interp, context, event, action_def):
        r = interp.send("B", wait=True)
        result["obj"] = r

    m = build(my_action)
    i = Interpreter(m)
    await i.start()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.send("A", wait=True)
        del result["obj"]
        import gc
        gc.collect()
        fired = any(issubclass(x.category, RuntimeWarning) for x in w)
    print("def action, dropped guard -> RuntimeWarning fired:", fired)
    if not fired:
        failures.append("def action dropped guard did not warn (#232)")


async def case_def_ensure_future():
    """def action cannot use ensure_future (no coroutine) - not applicable;
    but def action can pass the guard object nowhere useful. Test instead:
    def action that IGNORES via explicit del immediately (still same as above).
    Also test wait=False (fire-and-forget) -> no warning expected."""
    def my_action(interp, context, event, action_def):
        interp.send("B", wait=False)

    m = build(my_action)
    i = Interpreter(m)
    await i.start()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.send("A", wait=True)
        fired = any(issubclass(x.category, RuntimeWarning) for x in w)
    print("def action, wait=False -> RuntimeWarning fired (should be False):", fired)
    if fired:
        failures.append("def action wait=False unexpectedly warned")


async def case_async_ensure_future():
    """async def action: ensure_future(send(wait=True)) then awaited
    elsewhere -> silent (no warning), per #225/#232."""
    receipts = {}

    async def helper(interp):
        r = await interp.send("B", wait=True)
        receipts["got"] = r

    async def my_action(interp, context, event, action_def):
        asyncio.ensure_future(helper(interp))

    m = build(my_action)
    i = Interpreter(m)
    await i.start()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.send("A", wait=True)
        await asyncio.sleep(0.05)
        fired = any(issubclass(x.category, RuntimeWarning) for x in w)
    print("async action, ensure_future+awaited -> RuntimeWarning fired (should be False):", fired,
          "receipt got:", "got" in receipts)
    if fired:
        failures.append("async ensure_future path unexpectedly warned (#225/#232)")


async def case_async_result():
    """async def action: uses .result() on a future-like guard -- silent."""
    # Using ensure_future + .result() pattern after done
    done = {}

    async def helper(interp):
        fut = asyncio.ensure_future(interp.send("B", wait=True))
        await fut
        done["r"] = fut.result()

    async def my_action(interp, context, event, action_def):
        asyncio.ensure_future(helper(interp))

    m = build(my_action)
    i = Interpreter(m)
    await i.start()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.send("A", wait=True)
        await asyncio.sleep(0.05)
        fired = any(issubclass(x.category, RuntimeWarning) for x in w)
    print("async action, .result() pattern -> RuntimeWarning fired (should be False):", fired)
    if fired:
        failures.append("async .result() path unexpectedly warned")


async def case_async_await():
    """async def action awaits send(wait=True) directly within same task ->
    ReentrantWaitError (not a RuntimeWarning) since in-step self-await is
    still refused."""
    from xstate_statemachine.exceptions import ReentrantWaitError

    raised = {}

    async def my_action(interp, context, event, action_def):
        try:
            await interp.send("B", wait=True)
        except ReentrantWaitError as exc:
            raised["exc"] = exc

    m = build(my_action)
    i = Interpreter(m)
    await i.start()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.send("A", wait=True)
        fired = any(issubclass(x.category, RuntimeWarning) for x in w)
    print("async action, in-step await -> ReentrantWaitError raised:", "exc" in raised,
          "RuntimeWarning fired (should be False):", fired)
    if "exc" not in raised:
        failures.append("in-step self-await no longer refused (#225)")
    if fired:
        failures.append("in-step self-await path unexpectedly ALSO warned")


asyncio.run(case_def_dropped())
asyncio.run(case_def_ensure_future())
asyncio.run(case_async_ensure_future())
asyncio.run(case_async_result())
asyncio.run(case_async_await())

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
