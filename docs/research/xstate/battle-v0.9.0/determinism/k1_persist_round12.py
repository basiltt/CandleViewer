"""
STANDALONE. New attacks vs v0.9.0/main (round-12 fixes #225-#235), DETERMINISM
track. Property tests:
  (a) chain_trips monotonic across N restarts; RestoredError message intact.
  (b) scheduled_sends strict refusal mid-restore leaves a consistent machine
      (repeat as a property over many random payload shapes).
  (c) plugins= receives every restore-time on_invalid_event hook exactly once.

Run: python k1_persist_round12.py
"""
import asyncio
import json
import random

from xstate_statemachine import (
    create_machine,
    Interpreter,
    MachineLogic,
    PluginBase,
)

CFG = {
    "id": "chainy",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "GO": {
                    "target": "a",
                    "actions": [
                        "bump",
                        {"type": "raise", "params": {"event": "GO"}},
                    ],
                },
                "TYPED": {"target": "a", "actions": ["bump"]},
            }
        }
    },
}


def bump(interpreter, ctx, event, action_def=None):
    ctx["n"] = ctx.get("n", 0) + 1


LOGIC = MachineLogic(actions={"bump": bump})
MACHINE = create_machine(CFG, logic=LOGIC)


async def force_chain_trip(i: Interpreter):
    # A single GO re-raises GO from its own action -- a genuine self-chain
    # that trips the chain budget (RunawayChainError) inside one macrostep.
    before = i.chain_trips
    i.send("GO")
    for _ in range(200):
        await asyncio.sleep(0)
        if i.chain_trips > before:
            break


async def test_a():
    i = await Interpreter(MACHINE).start()
    await force_chain_trip(i)
    trips_before = i.chain_trips
    had_latch = i.last_chain_error is not None
    d = i.get_persisted_snapshot()
    assert d.get("chain_trips") == trips_before, (d.get("chain_trips"), trips_before)
    if had_latch:
        assert isinstance(d.get("last_chain_error"), str) and d["last_chain_error"]

    cur = json.dumps(d)
    last_trips = trips_before
    for n in range(3):
        i2 = Interpreter.from_snapshot(cur, MACHINE)
        assert i2.chain_trips == last_trips, (n, i2.chain_trips, last_trips)
        if had_latch:
            assert i2.last_chain_error is not None
            assert str(i2.last_chain_error) == d.get("last_chain_error")
            from xstate_statemachine.exceptions import RestoredError
            assert isinstance(i2.last_chain_error, RestoredError)
        await i2.start()
        await force_chain_trip(i2)
        assert i2.chain_trips >= last_trips
        last_trips = i2.chain_trips
        cur = json.dumps(i2.get_persisted_snapshot())
        await i2.stop()
    print("A: chain_trips/RestoredError round-trip OK, final trips=", last_trips)


class CountingPlugin(PluginBase):
    def __init__(self):
        self.invalid_count = 0

    def on_invalid_event(self, interpreter, event, error):
        self.invalid_count += 1


async def test_b_and_c(trials=40):
    rnd = random.Random(7)
    strict_cfg = dict(CFG)
    strict_cfg["strict"] = True
    strict_machine = create_machine(strict_cfg, logic=LOGIC)

    for t in range(trials):
        i = await Interpreter(strict_machine).start()
        i.send("TYPED")
        await asyncio.sleep(0)
        snap = i.get_persisted_snapshot()
        # Inject a strict-illegal scheduled_send record + a mix of legal
        # pending_events, varying shapes across trials.
        bad = {
            "type": "NOT_A_REAL_TYPE_%d" % rnd.randint(0, 999),
            "delay_ms": rnd.choice([0, 1, 100]),
        }
        good = {
            "type": "GO",
            "delay_ms": rnd.choice([0, 5]),
        }
        snap["scheduled_sends"] = rnd.sample([bad, good, bad, good], k=rnd.randint(1, 4))
        payload = json.dumps(snap)

        plugin = CountingPlugin()
        i2 = Interpreter.from_snapshot(payload, strict_machine, plugins=[plugin])
        await i2.start()
        # Property: machine ends up in a legal, running configuration
        # regardless of how many scheduled_sends were refused.
        assert i2._configuration_is_legal() or i2.status != "running"
        bad_count = sum(1 for r in snap["scheduled_sends"] if r is bad)
        assert plugin.invalid_count == bad_count, (t, plugin.invalid_count, bad_count, snap["scheduled_sends"])
        await i2.stop()
        await i.stop()
    print(f"B/C: {trials} trials — strict refusal leaves consistent machine, plugin hook fires exactly once per bad record")


async def main():
    await test_a()
    await test_b_and_c()
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
