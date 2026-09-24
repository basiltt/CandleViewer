"""Verify #104 on main@3ed3099: OverflowPolicy.BLOCK enqueues eagerly (does
not silently drop a fire-and-forget send() when the inbox has room).

Criteria:
1. A fire-and-forget `i.send("T")` (result NOT awaited) under BLOCK policy,
   with room in the inbox, IS delivered -- two unawaited sends both run
   their action.
2. No RuntimeWarning "coroutine ... was never awaited" is raised in the
   process of doing this (the old bug returned an un-started coroutine).
3. When the inbox genuinely has no room, BLOCK still awaits/blocks (i.e.
   the fix didn't remove real backpressure) -- send(..., wait=True) to a
   full queue eventually completes only once room frees up / or a stopped
   machine refuses. We check the documented refusal-when-stopped path
   still works under BLOCK.
4. `on_event_dropped` is NOT fired for the room-available fire-and-forget
   case (nothing was actually dropped).
"""
import asyncio
import sys
import warnings

from xstate_statemachine import Interpreter, MachineLogic, OverflowPolicy, PluginBase, create_machine

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def _bump(key):
    return lambda i, c, e, a: c.__setitem__(key, c[key] + 1)


class _Drops(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((event.type, reason))


CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"T": {"actions": "inc"}}}},
}


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 15))


async def main1():
    d = _Drops()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        i = Interpreter(
            create_machine(CFG, logic=MachineLogic(actions={"inc": _bump("n")})),
            max_queue_size=10,
            overflow_policy=OverflowPolicy.BLOCK,
        )
        i.use(d)
        await i.start()
        i.send("T")  # fire-and-forget, NOT awaited
        i.send("T")  # fire-and-forget, NOT awaited
        await asyncio.sleep(0.1)
        n = i.context["n"]
        await i.stop()
    rt_warnings = [str(x.message) for x in w if issubclass(x.category, RuntimeWarning) and "never awaited" in str(x.message)]
    return n, rt_warnings, d.dropped


n, rt_warnings, dropped = _run(main1())
check("1 both fire-and-forget sends delivered (n==2)", n == 2, n)
check("2 no 'never awaited' RuntimeWarning", len(rt_warnings) == 0, rt_warnings)
check("4 on_event_dropped not fired", len(dropped) == 0, dropped)

# 3: stopped machine still refuses under BLOCK (documented in test suite)
CFG2 = {"id": "m2", "initial": "a", "states": {"a": {"on": {"T": "a"}}}}


async def main2():
    i = Interpreter(create_machine(CFG2), max_queue_size=1, overflow_policy=OverflowPolicy.BLOCK)
    await i.start()
    await i.stop()
    r = await asyncio.wait_for(i.send("T", wait=True), 2)
    return r.error is not None


refused = _run(main2())
check("3 stopped machine still refuses under BLOCK", refused)

ok = True
for name, passed, detail in results:
    print(f"{'PASS' if passed else 'FAIL'}: {name}  {detail if not passed else ''}")
    ok = ok and passed

sys.exit(0 if ok else 1)
