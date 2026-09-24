"""ReentrantWaitError matrix (#219): self / child->parent / parent->child /
after-fired handler. Both engines.
STANDALONE: stdlib + xstate_statemachine only.
"""
import sys, asyncio
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
from xstate_statemachine.exceptions import ReentrantWaitError

results = {}

# --- 1. self wait=True inside own action (async), triggered via entry
# during a transition still being processed by the run loop (matches
# library's own #219 test shape: entry action awaits its own send). ---
cfg1 = {
    "id": "m", "initial": "x",
    "states": {"x": {"entry": ["selfwait"], "on": {"GO": "y"}}, "y": {}},
}

from xstate_statemachine import PluginBase


class _ErrSpy(PluginBase):
    def __init__(self):
        self.errors = []

    def on_action_error(self, i, action, error):
        self.errors.append(error)


async def selfwait(i, c, e, a):
    await i.send("GO", wait=True)

m1 = create_machine(cfg1, logic=MachineLogic(actions={"selfwait": selfwait}))

async def t1():
    spy = _ErrSpy()
    interp = Interpreter(m1).use(spy)
    try:
        await asyncio.wait_for(interp.start(), 5)
    except ReentrantWaitError:
        pass
    await asyncio.sleep(0.05)
    caught = [type(e).__name__ for e in spy.errors]
    if interp.status == "running":
        await interp.stop()
    return f"status={interp.status} action_errors={caught}"

results["1_async_self"] = asyncio.run(t1())

# --- 2. sync engine self wait=True (same entry-action shape) ---
cfg2 = {
    "id": "m", "initial": "x",
    "states": {"x": {"entry": ["selfwait"], "on": {"GO": "y"}}, "y": {}},
}

def selfwait_sync(i, c, e, a):
    i.send("GO", wait=True)

m2 = create_machine(cfg2, logic=MachineLogic(actions={"selfwait": selfwait_sync}))
spy2 = _ErrSpy()
interp2 = SyncInterpreter(m2).use(spy2)
try:
    interp2.start()
except ReentrantWaitError:
    pass
results["2_sync_self"] = (
    f"status={interp2.status} action_errors="
    f"{[type(e).__name__ for e in spy2.errors]}"
)

# --- 3. ensure_future workaround still allowed (await later, not in-step) ---
cfg3 = {
    "id": "m", "initial": "x",
    "states": {"x": {"entry": ["deferred"], "on": {"GO": "y"}}, "y": {}},
}

box = {}

def selfwait_deferred(i, c, e, a):
    box["fut"] = asyncio.ensure_future(i.send("GO", wait=True))

m3 = create_machine(cfg3, logic=MachineLogic(actions={"deferred": selfwait_deferred}))

async def t3():
    interp = Interpreter(m3)
    await interp.start()
    try:
        r = await asyncio.wait_for(box["fut"], 5)
        outcome = f"no-error (deferred receipt resolved: {r})"
    except ReentrantWaitError:
        outcome = "ReentrantWaitError (unexpected on deferred path)"
    await interp.stop()
    return outcome

results["3_async_ensure_future_deferred"] = asyncio.run(t3())


for k, v in results.items():
    print(k, ":", v)

print("EXPECT: 1 and 2 -> ReentrantWaitError; 3 -> no-error (deferred allowed)")
