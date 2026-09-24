"""Independent re-verification of #147-#151 on main@cec108b.

Self-contained; does not import the library's own test file. Run with:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv-python> repro_147_151.py
"""
import asyncio
import sys
import time
import threading
import traceback

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    RootTargetError,
    InvalidConfigError,
)

RESULTS = {}


def report(name, ok, detail=""):
    RESULTS[name] = ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# ---------------------------------------------------------------------------
# #147 - root target rejected regardless of strict_targets
# ---------------------------------------------------------------------------
def check_147():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"GO": "#m"}}, "b": {}},
    }
    ok = True
    for strict in (True, False):
        try:
            create_machine(cfg, strict_targets=strict)
            ok = False
            print(f"  #147: strict_targets={strict} did NOT raise")
        except RootTargetError as e:
            if not isinstance(e, InvalidConfigError):
                ok = False
                print("  #147: RootTargetError not an InvalidConfigError")
        except Exception as e:
            ok = False
            print(f"  #147: strict_targets={strict} wrong exception {type(e)}")

    # genuinely unresolvable target must still only warn under strict_targets=False
    cfg2 = {
        "id": "m2",
        "initial": "a",
        "states": {"a": {"on": {"GO": "nowhere"}}},
    }
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            create_machine(cfg2, strict_targets=False)
        except Exception as e:
            ok = False
            print(f"  #147: unresolvable target raised instead of warn: {e}")
        if not any("unresolvable" in str(x.message) for x in w):
            ok = False
            print("  #147: no DeprecationWarning emitted for unresolvable target")

    report("#147", ok)


# ---------------------------------------------------------------------------
# #148 - cancel before the loop's first turn is published via done-callback
# ---------------------------------------------------------------------------
def check_148():
    cfg = {
        "id": "c",
        "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }

    def run_case(yield_first: bool):
        errors = {"n": 0}

        async def main():
            from xstate_statemachine.plugins import PluginBase

            class Spy(PluginBase):
                def on_error(self, i, e):
                    errors["n"] += 1

            i = Interpreter(create_machine(cfg)).use(Spy())
            await i.start()
            if yield_first:
                await asyncio.sleep(0)
            i._event_loop_task.cancel()
            await asyncio.sleep(0.05)
            r = await asyncio.wait_for(i.send("GO", wait=True), 2)
            out = (i.status, type(i.error).__name__, type(r.error).__name__)
            await i.stop()
            return out

        out = asyncio.run(main())
        return out, errors["n"]

    ok = True
    for yield_first in (False, True):
        try:
            (status, err, receipt_err), n = run_case(yield_first)
            if status != "error" or err != "RuntimeError" or receipt_err != "InterpreterStoppedError" or n != 1:
                ok = False
                print(f"  #148 yield_first={yield_first}: got {(status, err, receipt_err, n)}")
        except Exception:
            ok = False
            print(f"  #148 yield_first={yield_first}: exception\n{traceback.format_exc()}")
    report("#148", ok)


# ---------------------------------------------------------------------------
# #149 - plain-def services run off the event loop
# ---------------------------------------------------------------------------
def check_149():
    cfg = {
        "id": "s",
        "initial": "w",
        "states": {
            "w": {"invoke": {"id": "svc", "src": "slow", "onDone": "d"}},
            "d": {},
        },
    }

    def slow(i, c, e):
        time.sleep(0.3)
        return 1

    async def main():
        ticks = {"n": 0}

        async def ticker():
            while True:
                ticks["n"] += 1
                await asyncio.sleep(0.01)

        t = asyncio.ensure_future(ticker())
        t0 = time.monotonic()
        i = await Interpreter(
            create_machine(cfg, logic=MachineLogic(services={"slow": slow}))
        ).start()
        blocked = time.monotonic() - t0
        base = ticks["n"]
        deadline = time.monotonic() + 5.0
        while i.value != "d" and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        during = ticks["n"] - base
        t.cancel()
        v = i.value
        await i.stop()
        return blocked, during, v

    ok = True
    try:
        blocked, during, v = asyncio.run(main())
        if blocked >= 0.15:
            ok = False
            print(f"  #149: start() blocked {blocked:.3f}s (loop did not stay live)")
        if during < 10:
            ok = False
            print(f"  #149: ticker only advanced {during} times while service ran")
        if v != "d":
            ok = False
            print(f"  #149: final state {v!r} != 'd'")
    except Exception:
        ok = False
        print(f"  #149: exception\n{traceback.format_exc()}")
    report("#149", ok)


# ---------------------------------------------------------------------------
# #150 - send_threadsafe self-sends are budgeted (classified on caller thread)
# ---------------------------------------------------------------------------
def check_150():
    cfg = {
        "id": "spin",
        "initial": "a",
        "maxIterations": 20,
        "context": {},
        "states": {"a": {"on": {"T": {"actions": ["resend"]}}}},
    }

    def count(mode: str):
        seen = {"n": 0}

        async def resend(i, c, e, a):
            seen["n"] += 1
            if seen["n"] >= 60:
                return
            if mode == "flag":
                threading.Thread(
                    target=lambda: i.send_threadsafe("T", internal=True),
                    daemon=True,
                ).start()
            else:
                import contextvars

                ctx = contextvars.copy_context()
                threading.Thread(
                    target=lambda: ctx.run(i.send_threadsafe, "T"), daemon=True
                ).start()

        async def main():
            i = await Interpreter(
                create_machine(cfg, logic=MachineLogic(actions={"resend": resend}))
            ).start()
            await i.send("T")
            await asyncio.sleep(0.8)
            out = (
                seen["n"],
                type(i.last_error).__name__ if i.last_error else None,
                i.last_transition_ok,
            )
            await i.stop()
            return out

        return asyncio.run(main())

    ok = True
    try:
        for mode in ("flag", "ctx"):
            n, err, last_ok = count(mode)
            # must trip well before all 60 resends land (budget=20), and be flagged
            if n >= 55:
                ok = False
                print(f"  #150 mode={mode}: n={n} (self-send NOT charged to budget)")
            if err != "RunawayChainError":
                ok = False
                print(f"  #150 mode={mode}: last_error={err} (expected RunawayChainError)")
            if last_ok:
                ok = False
                print(f"  #150 mode={mode}: last_transition_ok True, expected False")
    except Exception:
        ok = False
        print(f"  #150: exception\n{traceback.format_exc()}")
    report("#150", ok)


# ---------------------------------------------------------------------------
# #151 - settle (`always`) budget is per macrostep, not per drain/batch
# ---------------------------------------------------------------------------
def check_151():
    def cfg(n=40, limit=50):
        states = {"idle": {"on": {"GO": "s0", "GO2": "u0"}}}
        for k in range(n):
            states[f"s{k}"] = {"always": f"s{k+1}"}
        states[f"s{n}"] = {"on": {"GO2": "u0"}}
        for k in range(n):
            states[f"u{k}"] = {"always": f"u{k+1}"}
        states[f"u{n}"] = {}
        return {"id": "L", "initial": "idle", "maxIterations": limit, "states": states}

    ok = True
    try:
        a = SyncInterpreter(create_machine(cfg())).start()
        a.send("GO")
        a.send("GO2")
        b = SyncInterpreter(create_machine(cfg())).start()
        b.send_events(["GO", "GO2"])
        if a.value != b.value:
            ok = False
            print(f"  #151: sequential value {a.value!r} != batch value {b.value!r}")
        if not b.last_transition_ok or b.last_error is not None:
            ok = False
            print(f"  #151: batch send_events tripped budget (last_transition_ok={b.last_transition_ok}, last_error={b.last_error})")
    except Exception:
        ok = False
        print(f"  #151: exception\n{traceback.format_exc()}")
    report("#151", ok)


if __name__ == "__main__":
    check_147()
    check_148()
    check_149()
    check_150()
    check_151()
    print()
    print("SUMMARY:", RESULTS)
    if not all(RESULTS.values()):
        sys.exit(1)
