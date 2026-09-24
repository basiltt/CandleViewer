"""Verify #91 on main@3ed3099: alias-ambiguity guard for both directions.

Criteria (from CHANGELOG [Unreleased]/Fixed and issue #91 body):
1. Registry side (original 3c527b0 fix, reconfirmed): registering two
   DIFFERENT callables as 'fetch_data' and 'fetchData', with config
   requiring the EXACT key 'fetchData' (the documented example) -> BUILDS,
   and fires a UserWarning naming both spellings (exact key wins by design,
   but shadowing is flagged).
2. Requiring the other exact key 'fetch_data' -> BUILDS + warns too.
3. Requiring a non-exact colliding spelling ('fetch-data', 'FetchData') ->
   still raises InvalidConfigError (unchanged ambiguity behaviour).
4. NEW in this round (CHANGELOG: "two *config* names that normalise equal
   and resolve to one callable warn (#91)"): config requires two distinct
   names (e.g. 'store_user' and 'storeUser') that both resolve to the SAME
   single registered callable -> UserWarning naming both config names.
5. Single spelling required, single callable registered -> no warning.

Exit 0 iff all pass.
"""
import sys
import warnings

from xstate_statemachine import InvalidConfigError, MachineLogic, create_machine

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def fetch_data(i, c, e, a):
    pass


def fetchData(i, c, e, a):
    pass


# 1: exact key 'fetchData' required, both spellings registered as DIFFERENT callables
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    try:
        create_machine(
            {"id": "m", "initial": "a", "states": {"a": {"entry": ["fetchData"]}}},
            logic=MachineLogic(actions={"fetch_data": fetch_data, "fetchData": fetchData}),
        )
        built = True
    except InvalidConfigError as ex:
        built = False
    msgs = [str(x.message) for x in w if x.category is UserWarning]
check(
    "1 exact-key documented example builds",
    built,
)
check(
    "1 warns naming both spellings",
    any("fetch_data" in m and "fetchData" in m for m in msgs),
    msgs,
)

# 2: exact key 'fetch_data' required
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    try:
        create_machine(
            {"id": "m2", "initial": "a", "states": {"a": {"entry": ["fetch_data"]}}},
            logic=MachineLogic(actions={"fetch_data": fetch_data, "fetchData": fetchData}),
        )
        built2 = True
    except InvalidConfigError:
        built2 = False
    msgs2 = [str(x.message) for x in w if x.category is UserWarning]
check("2 other exact key builds", built2)
check("2 warns naming both spellings", any("fetch_data" in m and "fetchData" in m for m in msgs2), msgs2)

# 3: non-exact colliding spelling still raises InvalidConfigError
raised = False
try:
    create_machine(
        {"id": "m3", "initial": "a", "states": {"a": {"entry": ["fetch-data"]}}},
        logic=MachineLogic(actions={"fetch_data": fetch_data, "fetchData": fetchData}),
    )
except InvalidConfigError:
    raised = True
check("3 non-exact collision still raises InvalidConfigError", raised)

# 4: two distinct CONFIG names collapsing to ONE registered callable -> warn
def store(i, c, e, a):
    pass


with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    create_machine(
        {"id": "m4", "initial": "a", "states": {"a": {"entry": ["store_user", "storeUser"]}}},
        logic=MachineLogic(actions={"store_user": store}),
    )
    msgs4 = [str(x.message) for x in w if x.category is UserWarning]
check(
    "4 two config names -> one impl warns",
    any("store_user" in m and "storeUser" in m for m in msgs4),
    msgs4,
)

# 5: single spelling, single callable -> no warning
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    create_machine(
        {"id": "m5", "initial": "a", "states": {"a": {"entry": ["storeUser"]}}},
        logic=MachineLogic(actions={"store_user": store}),
    )
    msgs5 = [str(x.message) for x in w if x.category is UserWarning and "differ only" in str(x.message)]
check("5 single spelling -> no ambiguity warning", len(msgs5) == 0, msgs5)

ok = True
for name, passed, detail in results:
    print(f"{'PASS' if passed else 'FAIL'}: {name}  {detail if not passed else ''}")
    ok = ok and passed

sys.exit(0 if ok else 1)
