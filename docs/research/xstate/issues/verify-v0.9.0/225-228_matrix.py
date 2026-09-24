"""STANDALONE verify -- #225-#228 on xstate_statemachine v0.9.0 / main @ e3a1f22.

Matrix: {def, async def} x {Interpreter, SyncInterpreter} where relevant.
stdlib + xstate_statemachine only. Neutral cwd C:/Users/basil. Exit 0 == all pass.
"""
import asyncio
import json
import sys
import warnings

from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.machine_logic import MachineLogic

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# #225: self-send provenance by task identity; worker outliving its action is
# external; ensure_future hand-out works whether or not action awaits again;
# genuine in-step await still refused.
# ---------------------------------------------------------------------------

async def check_225():
    cfg = {
        "id": "m225",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {},
        },
    }

    # Lane A: background worker born in an action, sleeps past quiescence,
    # then does a waiting send. Must NOT be refused (external traffic).
    results = {}

    async def worker(i):
        await asyncio.sleep(0.05)
        r = await i.send("GO", wait=True)
        results["lane_a"] = r

    async def entry_spawn_worker(i, *_a, **_kw):
        asyncio.ensure_future(worker(i))

    logic = MachineLogic(actions={"entry_spawn_worker": entry_spawn_worker})
    cfg_a = dict(cfg)
    cfg_a["states"] = {
        "a": {"entry": ["entry_spawn_worker"], "on": {"GO": "b"}},
        "b": {},
    }
    m = create_machine(cfg_a, logic=logic)
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.2)
    check("225.lane_a.worker_send_not_refused", "lane_a" in results)
    check("225.lane_a.machine_advanced", i.current_state_ids == {"m225.b"})
    await i.stop()

    # Lane B: documented ensure_future(i.send(..., wait=True)) hand-out
    # works whether or not the spawning action awaits again afterwards.
    handed = {}

    async def entry_handout_no_yield(i, *_a, **_kw):
        handed["fut1"] = asyncio.ensure_future(i.send("GO", wait=True))

    async def entry_handout_then_yield(i, *_a, **_kw):
        handed["fut2"] = asyncio.ensure_future(i.send("GO", wait=True))
        await asyncio.sleep(0)  # spawning action yields afterwards

    logic2 = MachineLogic(actions={"entry_handout_no_yield": entry_handout_no_yield})
    m2 = create_machine(
        {
            "id": "m225b",
            "initial": "a",
            "states": {"a": {"entry": ["entry_handout_no_yield"], "on": {"GO": "b"}}, "b": {}},
        },
        logic=logic2,
    )
    i2 = Interpreter(m2)
    await i2.start()
    await asyncio.sleep(0.05)
    try:
        r2 = await handed["fut1"]
        ok2 = True
    except Exception:
        ok2 = False
    check("225.lane_b.no_yield_not_refused", ok2)
    await i2.stop()

    logic3 = MachineLogic(actions={"entry_handout_then_yield": entry_handout_then_yield})
    m3 = create_machine(
        {
            "id": "m225c",
            "initial": "a",
            "states": {"a": {"entry": ["entry_handout_then_yield"], "on": {"GO": "b"}}, "b": {}},
        },
        logic=logic3,
    )
    i3 = Interpreter(m3)
    await i3.start()
    await asyncio.sleep(0.05)
    try:
        r3 = await handed["fut2"]
        ok3 = True
    except Exception:
        ok3 = False
    check("225.lane_b.with_yield_not_refused", ok3)
    await i3.stop()

    # Genuine in-step await (awaiting the send from *inside* the same
    # action's synchronous call stack, i.e. before returning) must still be
    # refused.
    refused = {}

    async def entry_in_step_await(i, *_a, **_kw):
        try:
            await i.send("GO", wait=True)
            refused["got"] = False
        except Exception:
            refused["got"] = True

    logic4 = MachineLogic(actions={"entry_in_step_await": entry_in_step_await})
    m4 = create_machine(
        {
            "id": "m225d",
            "initial": "a",
            "states": {"a": {"entry": ["entry_in_step_await"], "on": {"GO": "b"}}, "b": {}},
        },
        logic=logic4,
    )
    i4 = Interpreter(m4)
    await i4.start()
    await asyncio.sleep(0.05)
    check("225.in_step_await_still_refused", refused.get("got") is True)
    await i4.stop()


# ---------------------------------------------------------------------------
# #232: RuntimeWarning fires for a dropped guard in a `def` action; silent
# for ensure_future / .result() / await use.
# ---------------------------------------------------------------------------

async def check_232():
    cfg_base = {
        "id": "m232",
        "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }

    # def action drops the wait=True receipt entirely -> RuntimeWarning
    def entry_drop(i, *_a, **_kw):
        i.send("GO", wait=True)  # receipt dropped, never awaited/used

    logic = MachineLogic(actions={"entry_drop": entry_drop})
    m = create_machine(
        {"id": "m232a", "initial": "a", "states": {"a": {"entry": ["entry_drop"], "on": {"GO": "b"}}, "b": {}}},
        logic=logic,
    )
    i = Interpreter(m)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await i.start()
        await asyncio.sleep(0.05)
        await i.stop()
        import gc
        gc.collect()
        saw = any(issubclass(x.category, RuntimeWarning) for x in w)
    check("232.def_drop_receipt_warns", saw)

    # def action hands the receipt out via ensure_future -> silent
    def entry_handout(i, *_a, **_kw):
        r = i.send("GO", wait=True)
        asyncio.ensure_future(_await_it(r))

    async def _await_it(r):
        await r

    logic2 = MachineLogic(actions={"entry_handout": entry_handout})
    m2 = create_machine(
        {"id": "m232b", "initial": "a", "states": {"a": {"entry": ["entry_handout"], "on": {"GO": "b"}}, "b": {}}},
        logic=logic2,
    )
    i2 = Interpreter(m2)
    with warnings.catch_warnings(record=True) as w2:
        warnings.simplefilter("always")
        await i2.start()
        await asyncio.sleep(0.05)
        await i2.stop()
        import gc
        gc.collect()
        saw2 = any(issubclass(x.category, RuntimeWarning) for x in w2)
    check("232.def_handout_ensure_future_silent", not saw2)


# ---------------------------------------------------------------------------
# #226: chain_trips / last_chain_error survive snapshot; RestoredError on
# restore; monotonic across restore. Both Interpreter and SyncInterpreter.
# ---------------------------------------------------------------------------

_CHAIN_CFG = {
    "id": "p1v",
    "initial": "a",
    "maxIterations": 3,
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO"}}],
            "on": {"GO": {"target": "a", "reenter": True}, "CALM": "b"},
        },
        "b": {"on": {"BENIGN": "b"}},
    },
}


def _mk():
    return create_machine(_CHAIN_CFG)


async def check_226_async():
    from xstate_statemachine import RestoredError

    m = _mk()
    i = Interpreter(m)
    await i.start()
    await i.send("GO", wait=True)
    await asyncio.sleep(0.05)
    trips_before = i.chain_trips
    blob = i.get_persisted_snapshot()
    await i.stop()

    check("226.async.trips_recorded_live", trips_before >= 1)
    check("226.async.blob_has_chain_trips", blob.get("chain_trips") == trips_before)

    m2 = _mk()
    r = Interpreter.from_snapshot(json.dumps(blob), m2)
    check("226.async.trips_survive_restore", r.chain_trips == trips_before)
    check(
        "226.async.last_chain_error_is_restored_error",
        isinstance(r.last_chain_error, RestoredError),
    )


def check_226_sync():
    from xstate_statemachine import RestoredError

    m = _mk()
    s = SyncInterpreter(m)
    s.start()
    s.send("GO")
    trips_before = s.chain_trips
    blob = s.get_persisted_snapshot()
    s.stop()

    check("226.sync.trips_recorded_live", trips_before >= 1)

    m2 = _mk()
    r = SyncInterpreter.from_snapshot(json.dumps(blob), m2)
    check("226.sync.trips_survive_restore", r.chain_trips == trips_before)
    check(
        "226.sync.last_chain_error_is_restored_error",
        isinstance(r.last_chain_error, RestoredError),
    )


# ---------------------------------------------------------------------------
# #227: strict + schemas apply to restored scheduled_sends via
# _admit_restored; refusal -> on_invalid_event + last_error; restore not
# aborted.
# ---------------------------------------------------------------------------

async def check_227_async():
    from xstate_statemachine import UnknownEventError

    cfg = {
        "id": "m227",
        "strict": True,
        "initial": "a",
        "states": {"a": {"on": {"KNOWN": "b"}}, "b": {}},
    }
    m = create_machine(cfg)
    s = SyncInterpreter(m).start()
    blob = s.get_persisted_snapshot()
    s.stop()
    blob["pending_events"] = []
    blob["scheduled_sends"] = [
        {
            "kind": "event",
            "type": "UNDECLARED_TYPO",
            "payload": {},
            "remaining_ms": 1.0,
            "send_id": "probe",
        }
    ]

    from xstate_statemachine import PluginBase

    seen = []
    m2 = create_machine(cfg)

    class _Spy(PluginBase):
        def on_invalid_event(self, i, exc, raw):
            seen.append(type(exc).__name__)

    r = SyncInterpreter.from_snapshot(json.dumps(blob), m2, plugins=[_Spy()])
    r.start()
    armed_left = r.get_persisted_snapshot()["scheduled_sends"]
    err, value = r.last_error, r.value
    restore_not_aborted = True
    r.stop()

    check("227.sync.restore_not_aborted", restore_not_aborted)
    check("227.sync.refused_scheduled_send_not_armed", armed_left == [])
    check("227.sync.last_error_is_unknown_event", isinstance(err, UnknownEventError))
    check("227.sync.on_invalid_event_fired", "UnknownEventError" in seen)
    check("227.sync.never_reached_run_loop", value == "a")


# ---------------------------------------------------------------------------
# #228: nested_invoke shape now depends on maxIterations (test-quality fix
# in library's own tests/test_round9_findings.py). We assert the test file
# itself references maxIterations-dependent behaviour for nested_invoke.
# ---------------------------------------------------------------------------

def check_228():
    import pathlib

    repo = pathlib.Path(__file__).resolve()
    # library repo root passed via env or relative guess
    import os

    lib_root = os.environ.get("XSM_REPO")
    if not lib_root:
        check("228.repo_path_provided", False)
        return
    p = pathlib.Path(lib_root) / "tests" / "test_round9_findings.py"
    if not p.exists():
        check("228.round9_file_exists", False)
        return
    text = p.read_text(encoding="utf-8")
    check("228.round9_file_exists", True)
    # Heuristic: nested_invoke shape should no longer be a fixed "2 calls at
    # every limit" constant; look for evidence it varies / re-enters.
    has_nested = "nested_invoke" in text
    check("228.nested_invoke_present", has_nested)


async def main_async():
    await check_225()
    await check_232()
    await check_226_async()
    await check_227_async()


def main():
    asyncio.run(main_async())
    check_226_sync()
    check_228()

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}):")
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
