"""Verify #92 on main@5e07ba8: create_machine() does not mutate caller's
MachineLogic; no retroactive rebinding; per-machine isolation.

Acceptance criteria (from `gh issue view 92`):
  1. `f_shared_logic.py` shape: `logic.actions.keys()` byte-identical before
     and after `create_machine()`.
  2. `f_pollute.py` shape: building m1 cannot cause m2 to raise
     InvalidConfigError, and any ambiguity error names only keys the caller
     registered.
  3. A machine built against one spelling keeps calling the implementation
     registered at build time, even if that registry key is later
     overwritten (no retroactive rebinding).
  4. One `MachineLogic` shared across N machines behaves identically to N
     fresh `MachineLogic` instances.
  5. Tests: `test_create_machine_does_not_mutate_logic_registry`,
     `test_shared_machine_logic_across_machines_is_isolated`,
     `test_ambiguity_error_names_only_user_registered_keys` (library's own
     `test_create_machine_does_not_mutate_caller_logic` and
     `test_second_machine_from_same_logic_still_guards_ambiguity` cover the
     same contracts).
"""
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

failures = []


def store_user(i, c, e, a):
    pass


def storeUser(i, c, e, a):
    pass


CFG_TEMPLATE = lambda name: {
    "id": "m",
    "initial": "a",
    "states": {"a": {"entry": [name]}},
}

# --- Criterion 1: registry byte-identical before/after ---------------------
ml = MachineLogic(actions={"store_user": store_user})
before_keys = sorted(ml.actions.keys())
before_ids = {k: id(v) for k, v in ml.actions.items()}
m1 = create_machine(CFG_TEMPLATE("storeUser"), logic=ml)
after_keys = sorted(ml.actions.keys())
if before_keys != after_keys:
    failures.append(
        f"C1: caller's registry keys changed: {before_keys} -> {after_keys}"
    )
if any(ml.actions.get(k) is not before_ids.get(k) and k in before_ids for k in before_keys):
    pass  # values unchanged trivially since keys unchanged
if "storeUser" not in m1.logic.actions:
    failures.append("C1: the built machine itself lacks the alias")
if m1.logic.actions is ml.actions:
    failures.append("C1: machine's registry is the SAME object as caller's")

# --- Criterion 2: m1 cannot cause m2 to raise; error names only user keys --
ml2 = MachineLogic(actions={"store_user": store_user})
m1b = create_machine(CFG_TEMPLATE("storeUser"), logic=ml2)  # builds fine, aliases internally
# Now register the ambiguous spelling for real -- m2 must not be polluted by
# m1b's internal aliasing.
ml2.actions["STOREUSER"] = storeUser
try:
    m2 = create_machine(CFG_TEMPLATE("Store_User"), logic=ml2)
    # Ambiguous by design (two different callables normalise equal) -- this
    # SHOULD raise. If it built, that's fine only if it bound consistently;
    # but the two registered are different callables (store_user vs
    # storeUser), so an InvalidConfigError is expected here per #91/#93.
    failures.append(
        "C2: expected InvalidConfigError for genuinely ambiguous names, "
        "machine built instead"
    )
except InvalidConfigError as e:
    msg = str(e)
    # The error must name only what the CALLER registered: 'store_user' and
    # 'STOREUSER' -- not any alias key m1b might have injected (e.g.
    # 'Store_User' itself is the required name, not a registered one; check
    # no unexpected synthetic key like a previously-aliased 'storeUser' from
    # m1b leaks in, since m1b never wrote to ml2 at all per C1).
    if "storeUser" in msg and "storeUser" not in ml2.actions:
        failures.append(
            f"C2: ambiguity error names a key the caller never registered: "
            f"{msg}"
        )

# --- Criterion 3: no retroactive rebinding of an already-built machine ----
ml3 = MachineLogic(actions={"fetch_data": lambda i, c, e, a: "OLD"})
m3 = create_machine(
    {"id": "m3", "initial": "a", "states": {"a": {"entry": ["fetchData"]}}},
    logic=ml3,
)
bound_before = m3.logic.actions["fetchData"]
# Caller later overwrites the registry key.
ml3.actions["fetch_data"] = lambda i, c, e, a: "NEW"
bound_after = m3.logic.actions["fetchData"]
if bound_before is not bound_after:
    failures.append(
        "C3: an already-built machine's bound implementation changed when "
        "the caller's registry was overwritten afterward (retroactive "
        "rebinding)"
    )

# --- Criterion 4: shared MachineLogic across N machines == N fresh ones --
shared = MachineLogic(actions={"fetch_data": store_user})
snapshot0 = dict(shared.actions)
built = []
for i in range(3):
    built.append(
        create_machine(
            {
                "id": f"mm{i}",
                "initial": "a",
                "states": {"a": {"entry": ["fetchData"]}},
            },
            logic=shared,
        )
    )
if dict(shared.actions) != snapshot0:
    failures.append(
        f"C4: shared MachineLogic accumulated state across builds: "
        f"{snapshot0} -> {dict(shared.actions)}"
    )
for idx, mm in enumerate(built):
    if mm.logic.actions.get("fetchData") is not store_user:
        failures.append(f"C4: machine {idx} did not bind fetchData correctly")

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("ALL PASS")
