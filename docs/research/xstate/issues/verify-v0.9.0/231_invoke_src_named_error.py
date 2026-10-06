"""Verify #231 on v0.9.0/main: inline-dict invoke.src -> named InvalidConfigError.

STANDALONE: stdlib + xstate_statemachine only. Neutral cwd C:/Users/basil.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys

sys.path.insert(
    0,
    str(_XS / 'src'),
)
from xstate_statemachine import create_machine, MachineLogic, InvalidConfigError  # noqa: E402

CLEAN = {
    "id": "m", "initial": "a",
    "states": {"a": {"invoke": {"id": "kid", "src": {
        "id": "kid", "initial": "k", "states": {"k": {}},
    }}}},
}
TYPO = {
    "id": "m", "initial": "a",
    "states": {"a": {"invoke": {"id": "kid", "src": {
        "id": "kid", "initial": "k", "states": {"k": {"entyr": ["nope"]}},
    }}}},
}

failures = []


def check(label, cfg, strict):
    try:
        create_machine(cfg, logic=MachineLogic(), strict_config=strict)
        return f"{label} strict={strict} -> built OK (unexpected)", False
    except InvalidConfigError as exc:
        msg = str(exc)
        ok = "src" in msg and ("must be a service name" in msg)
        return f"{label} strict={strict} -> InvalidConfigError: {msg[:70]}", ok
    except TypeError as exc:
        return f"{label} strict={strict} -> TypeError (NOT FIXED): {exc}", False
    except Exception as exc:  # noqa: BLE001
        return f"{label} strict={strict} -> {type(exc).__name__}: {exc}", False


for label, cfg, strict in [
    ("inline dict src, no typo", CLEAN, False),
    ("inline dict src, no typo", CLEAN, True),
    ("inline dict src, with typo", TYPO, True),
]:
    line, ok = check(label, cfg, strict)
    print(line)
    if not ok:
        failures.append(line)

# Acceptance: named InvalidConfigError under strict_config True; and per repro's
# expected behaviour, strict_config=False variant produces a warning-class
# diagnostic in the same voice rather than TypeError. Our fix raises hard
# error unconditionally per source comment ("whatever strict_config says").
# Confirm state path + invoke id present too.
try:
    create_machine(CLEAN, logic=MachineLogic(), strict_config=True)
except InvalidConfigError as exc:
    msg = str(exc)
    named_ok = "m.a" in msg and "kid" in msg
    print("path+id named in message:", named_ok)
    if not named_ok:
        failures.append("message missing state path or invoke id")

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
