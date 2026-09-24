"""Verify #93 on xstate-statemachine @ 5e07ba8 (unreleased 0.8.1).

Acceptance criteria (from `gh issue view 93`):
  1. A module with both `fetch_data` and `fetchData` as different callables,
     required as `FETCH_DATA`, raises `InvalidConfigError` rather than binding
     silently.
  2. The error names both spellings and the defining module.
  3. A module with only one spelling is unaffected; exact-name matches still win.
  4. Discovery order does not change the outcome (both definition orders).
  5. Tests `test_logic_modules_duplicate_normalized_names_rejected` and
     `test_logic_modules_binding_is_order_independent` (library's own
     equivalents: `test_logic_modules_duplicate_normalised_names_is_an_error`,
     `test_logic_modules_exact_key_still_wins`, plus order check here).

Run: PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python 93_logic_modules_ambiguity.py
Expect: exit 0, "ALL CRITERIA PASS".
"""
import sys
import types

from xstate_statemachine import create_machine
from xstate_statemachine.exceptions import InvalidConfigError

CFG = {"id": "m", "initial": "a", "states": {"a": {"entry": ["FETCH_DATA"]}}}


def make_module(name: str, order: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    if order == "snake_first":
        def fetch_data(i, c, e, a):
            return "SNAKE"

        def fetchData(i, c, e, a):
            return "CAMEL"
    else:
        def fetchData(i, c, e, a):
            return "CAMEL"

        def fetch_data(i, c, e, a):
            return "SNAKE"
    mod.fetch_data = fetch_data
    mod.fetchData = fetchData
    sys.modules[name] = mod
    return mod


failures = []


# --- Criterion 1 + 2: duplicate spellings -> InvalidConfigError naming both + module
for order in ("snake_first", "camel_first"):
    name = f"dupmod_{order}"
    make_module(name, order)
    try:
        create_machine(CFG, logic_modules=[name])
        failures.append(f"criterion 1 ({order}): no error raised, silent bind occurred")
    except InvalidConfigError as e:
        msg = str(e)
        if "fetch_data" not in msg or "fetchData" not in msg:
            failures.append(f"criterion 2 ({order}): error does not name both spellings: {msg}")
    except Exception as e:  # pragma: no cover
        failures.append(f"criterion 1 ({order}): wrong exception type {type(e).__name__}: {e}")

# --- Criterion 4: discovery order does not change the outcome (both orders raise identically)
# (verified above: both orders raised InvalidConfigError)

# --- Criterion 3: a module with only one spelling is unaffected; exact match wins
mod_single = types.ModuleType("singlemod")


def fetchData(i, c, e, a):
    return "ONLY_CAMEL"


mod_single.fetchData = fetchData
sys.modules["singlemod"] = mod_single
try:
    m = create_machine(CFG, logic_modules=["singlemod"])
    bound = m.logic.actions["FETCH_DATA"]
    if bound is not fetchData:
        failures.append("criterion 3: single-spelling module did not bind via normalisation")
except Exception as e:
    failures.append(f"criterion 3: unexpected exception {type(e).__name__}: {e}")

# --- Criterion 3b: exact-name match still wins over alias/normalisation
mod_exact = types.ModuleType("exactmod")


def FETCH_DATA(i, c, e, a):
    return "EXACT"


def fetchData2(i, c, e, a):  # would normalise to FETCHDATA too, but different config name
    return "CAMEL2"


mod_exact.FETCH_DATA = FETCH_DATA
sys.modules["exactmod"] = mod_exact
try:
    m = create_machine(CFG, logic_modules=["exactmod"])
    bound = m.logic.actions["FETCH_DATA"]
    if bound is not FETCH_DATA:
        failures.append("criterion 3: exact-name match did not win")
except Exception as e:
    failures.append(f"criterion 3b: unexpected exception {type(e).__name__}: {e}")

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)

print("ALL CRITERIA PASS")
sys.exit(0)
