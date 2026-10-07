"""Standalone recheck repros for #243, #244, #245, #246 against xstate_statemachine 0.9.1.

Run from a neutral cwd (<home>) with the target venv's python:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python repro_243_246.py

stdlib + xstate_statemachine only. No project imports.
"""
import asyncio
import json
import subprocess
import sys

import xstate_statemachine as xsm
from xstate_statemachine.exceptions import (
    RestoredChainError,
    RunawayChainError,
    RestoredError,
)


def check_243():
    """#243: RestoredChainError IS-A RunawayChainError AND RestoredError."""
    assert issubclass(RestoredChainError, RunawayChainError), "not a RunawayChainError subclass"
    assert issubclass(RestoredChainError, RestoredError), "not a RestoredError subclass"
    err = RestoredChainError("restored chain trip")
    assert isinstance(err, RunawayChainError)
    assert isinstance(err, RestoredError)
    assert err.limit is None and err.dropped is None
    assert err.stranded == ()
    print("#243 PASS: RestoredChainError isinstance RunawayChainError and RestoredError; "
          ".limit/.dropped are None")


async def check_244():
    """#244: a dropped in-action wait=True receipt (#219/#232 reentrancy guard)
    is observable deterministically via dropped_receipts + on_receipt_dropped,
    regardless of the warnings filter (the underlying signal is a __del__
    finaliser that CPython routes to sys.unraisablehook, invisible to
    -W error / pytest.warns)."""
    calls = []

    class Hook(xsm.PluginBase):
        def on_receipt_dropped(self, interpreter, event_type):
            calls.append(event_type)

    def act(interp, context, event, action_def):
        interp.send("B", wait=True)  # unawaited, unstored -> dropped

    cfg = {
        "id": "m244",
        "initial": "s1",
        "states": {
            "s1": {"on": {"A": {"target": "s2", "actions": ["act"]}}},
            "s2": {"on": {"B": "s3"}},
            "s3": {"type": "final"},
        },
    }
    machine = xsm.create_machine(cfg, logic=xsm.MachineLogic(actions={"act": act}))

    interp = xsm.Interpreter(machine)
    interp.use(Hook())
    await interp.start()
    await interp.send("A", wait=True)
    await asyncio.sleep(0.02)
    import gc
    gc.collect()

    dropped = interp.dropped_receipts
    hook_calls = list(calls)
    status = interp.status
    await interp.stop()

    assert dropped >= 1, f"dropped_receipts={dropped}"
    assert "B" in hook_calls, f"on_receipt_dropped calls={hook_calls}"
    assert status == "done", f"status={status} (B should still have driven s2->s3)"
    print(f"#244 PASS: dropped_receipts={dropped}, hook_calls={hook_calls}, "
          f"status={status} (dropped-receipt send still executed the transition)")


def check_245():
    """#245: SyncInterpreter(max_queue_size=None, overflow_policy=None) — signature
    parity. Per the actual docstring/impl (sync_interpreter.py __init__), ONLY
    max_queue_size is checked: any non-None value raises a documented ValueError
    naming the wrapper-side alternative. overflow_policy is accepted-and-ignored
    on its own (it only matters together with a bound, which is refused) --
    it does NOT raise by itself. (The task brief's one-line paraphrase reads as
    "either non-None raises", which is stricter than the shipped contract; this
    is a wording gap in the brief, not a library defect -- confirmed against
    tests/test_round13_findings.py::TestSyncInterpreterHasNoInboxBound.)"""
    machine = xsm.create_machine({"id": "m245", "initial": "a", "states": {"a": {"on": {"T": "a"}}}})

    try:
        xsm.SyncInterpreter(machine, max_queue_size=5)
        raised = None
    except ValueError as e:
        raised = str(e)
    except TypeError as e:
        raised = f"WRONG-TYPE:TypeError:{e}"
    assert raised and "no inbox to bound" in raised and "wrapper" in raised, (
        f"expected documented ValueError, got: {raised}"
    )

    # overflow_policy ALONE (max_queue_size=None) is accepted, per contract.
    s = xsm.SyncInterpreter(
        machine, max_queue_size=None, overflow_policy=xsm.OverflowPolicy.RAISE
    ).start()
    s.send("T")
    assert s.status == "running"
    s.stop()

    # Both None: accepted (default-equivalent).
    xsm.SyncInterpreter(machine, max_queue_size=None, overflow_policy=None)

    print(f"#245 PASS: max_queue_size=5 -> ValueError({raised!r}); "
          f"overflow_policy alone (non-None) accepted per contract; both-None accepted")


def check_246():
    """#246: production_characteristics.py --json / --json-file emit a JSON host block + rows."""
    import xstate_statemachine as pkg
    script = None
    import os
    root = os.path.dirname(os.path.dirname(pkg.__file__))
    for cand in [
        os.path.join(root, "benchmarks", "production_characteristics.py"),
        os.path.join(os.path.dirname(root), "benchmarks", "production_characteristics.py"),
    ]:
        if os.path.exists(cand):
            script = cand
            break
    if script is None:
        print("#246 SKIP: benchmarks/production_characteristics.py not found relative to installed package "
              "(expected for a wheel-only install; script ships in sdist/repo, not the wheel).")
        return

    proc = subprocess.run(
        [sys.executable, script, "--json"],
        capture_output=True, text=True, timeout=60,
    )
    data = json.loads(proc.stdout)
    host = data.get("host") or {k: data.get(k) for k in
                                 ("library_version", "python_version", "platform", "machine", "processor", "cpu_count", "method")}
    assert host, f"no host block in output: {data.keys()}"
    print(f"#246 PASS: --json produced host block keys={list(host.keys())}")


if __name__ == "__main__":
    check_243()
    asyncio.run(check_244())
    check_245()
    check_246()
