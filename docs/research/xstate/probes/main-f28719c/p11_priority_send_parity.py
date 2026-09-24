"""P11 (STANDALONE): #192 parity -- is an action-issued
`send(priority=True)` charged identically to a `raise` on BOTH engines?

Async: an action-issued priority send now goes through `_deliver_priority`
with `engine_completion=True`, i.e. it is CHARGED but lands on the priority
lane, AHEAD of the internal queue's `raise` semantics.

Sync: `priority` is accepted and ignored.

The probe runs the same self-feeding chart three ways -- `raise`,
action-issued `send(priority=True)` (async), and the sync engine -- and
compares the lap count at which each trips. Both action spellings are run
as `def` and `async def`.

Exit 1 if the trip laps disagree.
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic,
)

LIMIT = 10

CFG = {
    "id": "m",
    "initial": "a",
    "maxIterations": LIMIT,
    "states": {
        "a": {"entry": ["lap", "feed"], "on": {"GO": "b"}},
        "b": {"entry": ["lap", "feed"], "on": {"GO": "a"}},
    },
}

RAISE_CFG = json.loads(json.dumps(CFG))
for s in RAISE_CFG["states"].values():
    s["entry"] = ["lap", {"type": "raise", "params": {"event": "GO"}}]


def make(mode, kind):
    laps = {"n": 0}

    def lap(i, c, e, adef=None):
        laps["n"] += 1

    async def alap(i, c, e, adef=None):
        laps["n"] += 1

    def feed(i, c, e, adef=None):
        i.send("GO", priority=True)

    async def afeed(i, c, e, adef=None):
        await i.send("GO", priority=True)

    def sfeed(i, c, e, adef=None):
        i.send("GO", priority=True)

    acts = {
        "lap": alap if kind == "async def" else lap,
        "feed": (afeed if kind == "async def" else feed) if mode != "sync" else sfeed,
    }
    cfg = RAISE_CFG if mode == "raise" else CFG
    return laps, create_machine(json.loads(json.dumps(cfg)),
                                logic=MachineLogic(actions=acts))


async def run_async(mode, kind):
    laps, m = make(mode, kind)
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(1.0)
    await i.stop()
    return laps["n"]


def run_sync(mode, kind):
    laps, m = make("sync" if mode != "raise" else "raise", kind)
    i = SyncInterpreter(m)
    try:
        i.start()
    except Exception as exc:  # RunawayChainError surfaces to the caller
        print("   sync raised:", type(exc).__name__)
    finally:
        try:
            i.stop()
        except Exception:
            pass
    return laps["n"]


async def main():
    rows = []
    for kind in ("def", "async def"):
        r = await run_async("raise", kind)
        p = await run_async("priority", kind)
        s = run_sync("priority", kind)
        rows.append((kind, r, p, s))
    return rows


bad = 0
for kind, r, p, s in asyncio.run(asyncio.wait_for(main(), 40.0)):
    print(f"{kind:>9}: async raise laps={r}  async priority-send laps={p}  sync priority-send laps={s}")
    # the sync engine rejects `async def` actions by design (NotSupportedError)
    if r != p or (kind == "def" and s != r):
        bad = 1
print("VERDICT:", "LAP PARITY BROKEN" if bad else "parity holds (ok)")
sys.exit(bad)
