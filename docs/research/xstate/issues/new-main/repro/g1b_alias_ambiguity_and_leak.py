"""G1b/G10b — the ambiguity guard and the registry-mutation leak.

CHANGELOG (Changed): "Registering two *different* callables whose names
differ only by case or separators (`fetch_data` and `fetchData`) for a name
the machine requires now raises `InvalidConfigError` at build time instead of
silently picking one."

G1b  Which spellings of the required name actually trigger the guard?
G10b Does the alias written back into the caller's MachineLogic registry
     mask the guard for a SECOND machine built from the same logic object?
"""

from __future__ import annotations

import warnings

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

warnings.simplefilter("ignore", DeprecationWarning)


def tag(t):
    def fn(i, c, e, a):
        c["hit"] = t

    return fn


def cfg(name, mid):
    return {
        "id": mid,
        "initial": "a",
        "context": {"hit": None},
        "states": {"a": {"on": {"GO": {"actions": [name]}}}},
    }


def attempt(required, registry, mid, logic=None):
    lg = logic or MachineLogic(actions=dict(registry))
    try:
        create_machine(cfg(required, mid), logic=lg)
        return "BUILT"
    except InvalidConfigError:
        return "InvalidConfigError"


print("=== G1b: both 'fetch_data' and 'fetchData' registered (DIFFERENT fns) ===")
for i, required in enumerate(["fetchData", "fetch_data", "fetch-data", "FetchData", "FETCHDATA"]):
    reg = {"fetch_data": tag("snake"), "fetchData": tag("camel")}
    print(f"  config requires {required!r:16} -> {attempt(required, reg, f'g{i}')}")

print(
    "\n  => the guard fires only when the required name matches NEITHER\n"
    "     registered spelling exactly. The documented example itself --\n"
    "     a camelCase JSON config naming 'fetchData' with both spellings\n"
    "     registered -- is silently resolved to the exact key."
)

print("\n=== G10b: alias write-back leaks into the caller's registry ===")
logic = MachineLogic(actions={"fetch_data": tag("snake")})
print("  registry before build 1 :", sorted(logic.actions))
create_machine(cfg("fetchData", "m1"), logic=logic)
print("  registry after  build 1 :", sorted(logic.actions), " <- 'fetchData' was never registered by the caller")

# The caller now adds the real camelCase implementation for a second machine.
logic.actions["fetchData"] = tag("camel-different")
r = attempt("fetch_data", None, "m2", logic=logic)
print("  build 2 requiring 'fetch_data' with BOTH now present ->", r)
print(
    "\n  => `resolve_aliases` mutates the MachineLogic the caller owns. A\n"
    "     logic object shared across machines (the documented\n"
    "     `logic_modules` / module-level-logic pattern) accumulates alias\n"
    "     keys from every machine built against it, and those synthetic\n"
    "     'exact' keys then take precedence over -- and suppress the\n"
    "     ambiguity guard for -- the next machine."
)

assert attempt("fetchData", {"fetch_data": tag("s"), "fetchData": tag("c")}, "x") == "BUILT"
assert attempt("fetch-data", {"fetch_data": tag("s"), "fetchData": tag("c")}, "y") == "InvalidConfigError"
print("\nCONFIRMED both.")
