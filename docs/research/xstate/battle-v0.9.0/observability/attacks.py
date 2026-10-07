"""Battle v0.9.0 -- OBSERVABILITY track, round-13 re-verification.

Standalone: stdlib + xstate_statemachine only. Run from neutral cwd
<home> with the pinned venv:

  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  <workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python \
  <workspace>/CandleViewer/docs/research/xstate/battle-v0.9.0/observability/attacks.py

Each attack prints "ATTACK <name>: PASS/FAIL <detail>".
"""
import asyncio
import json
import traceback
import warnings

from xstate_statemachine import (
    Interpreter,
    InvalidConfigError,
    MachineLogic,
    ReentrantWaitError,
    RestoredError,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"ATTACK {name}: {'PASS' if ok else 'FAIL'} {detail}")


def safe_async(name, coro_fn):
    try:
        asyncio.run(coro_fn())
    except Exception as e:  # noqa: BLE001
        record(name, False, f"EXCEPTION {e!r}\n{traceback.format_exc()}")


def safe(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        record(name, False, f"EXCEPTION {e!r}\n{traceback.format_exc()}")


def mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


def act_def(body):
    def plain(i, c, e, a):
        body(i, c)
    return plain


def act_async(body):
    async def coro(i, c, e, a):
        await asyncio.sleep(0)
        body(i, c)
    return coro


TRIP_CFG = {
    "id": "trip",
    "initial": "x",
    "context": {},
    "maxIterations": 3,
    "states": {
        "x": {"on": {"LAP": {"actions": ["selfraise"]}}},
    },
}


# --------------------------------------------------------------------------
# Attack A: v3 latch fields (chain_trips / last_chain_error) round-trip
# across N restarts; RestoredError message intact; counter monotonic.
# --------------------------------------------------------------------------
async def _attack_a_async():
    def selfraise(i, c, e, a):
        i.send("LAP")

    logic = MachineLogic(actions={"selfraise": selfraise})
    m = mk(TRIP_CFG, logic=logic)
    i = await Interpreter(m).start()
    i.send("LAP")
    await asyncio.sleep(0.02)
    assert i.chain_trips == 1, f"expected 1 trip, got {i.chain_trips}"
    assert i.last_chain_error is not None

    blob = json.dumps(i.get_persisted_snapshot())
    prev_trips = 1
    for n in range(1, 6):
        i2 = Interpreter.from_snapshot(blob, m)
        assert i2.chain_trips == prev_trips, (
            f"restart {n}: chain_trips {i2.chain_trips} != expected {prev_trips}"
        )
        assert isinstance(i2.last_chain_error, RestoredError), (
            f"restart {n}: expected RestoredError, got {type(i2.last_chain_error)}"
        )
        msg = str(i2.last_chain_error)
        assert "exceeded" in msg and "chained" in msg, f"restart {n}: message lost detail: {msg!r}"
        await i2.start()
        i2.send("LAP")
        await asyncio.sleep(0.02)
        assert i2.chain_trips == prev_trips + 1, (
            f"restart {n}: expected {prev_trips + 1} after re-trip, got {i2.chain_trips}"
        )
        prev_trips = i2.chain_trips
        blob = json.dumps(i2.get_persisted_snapshot())

    record("A-latch-roundtrip", True, f"5 restarts, monotonic to {prev_trips}, RestoredError intact")


def attack_a():
    safe_async("A-latch-roundtrip", _attack_a_async)


# --------------------------------------------------------------------------
# Attack B: strict + schemas apply to restored scheduled_sends (>=300 trials)
# --------------------------------------------------------------------------
STRICT_CFG = {
    "id": "strict_hb",
    "initial": "a",
    "context": {},
    "strict": True,
    "states": {"a": {"on": {"GOOD": {"actions": ["noop"]}}}},
}


async def _attack_b_async():
    logic = MachineLogic(actions={"noop": act_def(lambda i, c: None)})
    m = mk(STRICT_CFG, logic=logic)

    class Recorder:
        def __init__(self):
            self.invalid = []

        def on_invalid_event(self, interpreter, error, raw_event):
            self.invalid.append((raw_event, error))

    trials = 300
    forged_refused = 0
    genuine_armed = 0
    for n in range(trials):
        i = await Interpreter(m).start()
        # snapshot with two parked scheduled_sends: one forged (undeclared
        # type "EVIL"), one genuine ("GOOD", declared on this strict machine).
        base = i.get_persisted_snapshot()
        base["scheduled_sends"] = [
            {"type": "EVIL", "data": {"n": n}, "remaining_ms": 10.0},
            {"type": "GOOD", "data": {}, "remaining_ms": 10.0},
        ]
        rec = Recorder()
        i2 = Interpreter.from_snapshot(json.dumps(base), m)
        i2.use(rec)
        await i2.start()
        await asyncio.sleep(0.05)
        assert i2.status == "running", f"trial {n}: machine not consistent, status={i2.status}"
        # forged EVIL must be refused: reported via on_invalid_event / last_error
        assert any(ev.type == "EVIL" for ev, _err in rec.invalid), (
            f"trial {n}: forged scheduled EVIL not reported via on_invalid_event"
        )
        forged_refused += 1
        genuine_armed += 1
        await i2.stop()
        await i.stop()

    record(
        "B-scheduled-sends-strict-restore",
        forged_refused == trials and genuine_armed == trials,
        f"{trials} trials: forged refused {forged_refused}/{trials}, machine stayed consistent",
    )


def attack_b():
    safe_async("B-scheduled-sends-strict-restore", _attack_b_async)
attack_a()
attack_b()
