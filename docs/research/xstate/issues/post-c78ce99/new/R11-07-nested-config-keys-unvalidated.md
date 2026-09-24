# #216 validates the root config only: a misspelled key *inside a state* is silently dropped, with no raise and no warning, even under `strict_config=True`

**Severity:** Medium
**Build:** `main` @ `c78ce99` (merge of PR #217, `fix/0.8.1-round10`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory.
**r11:** R11-07 · **Labels:** bug, severity/medium, area/validation, config, dx

---

## Summary

**The top-level half of #216 is flawless** — we could not break it in 47/47, 120/120 or 200/200 mutation runs, and the did-you-mean hint named the right key every time. This report is purely about its **scope**.

`validation.py::validate_top_level_keys` iterates `for k in config` — the **root dict only** — and is invoked once from `factory.py`. But `KNOWN_MACHINE_KEYS` is overwhelmingly a list of **state-level** names: `entry`, `exit`, `on`, `after`, `always`, `invoke`, `onDone`, `initial`, `type`, `states`. Those keys do their work *inside each state node*, where nothing checks them — `StateNode.__init__` reads the keys it knows via plain `.get()` and silently ignores the rest.

So the list of known keys is mostly a list of names that are never validated where they are actually used.

## Observed

```
CONTROL -- a ROOT-level typo, which #216 handles correctly:
  strict_config=True  -> built=False exc=InvalidConfigError
  root check live: True

DEFECT -- the same class of typo one level down, INSIDE a state:
  typo                  built   exc       warnings
  entry -> entyr        True    None      0
  exit -> exti          True    None      0
  on -> onn             True    None      0
  after -> afer         True    None      0
  always -> alwyas      True    None      0
  invoke -> invoek      True    None      0
  onDone -> onDoen      True    None      0

Behavioural consequence of {'entyr': [...], 'onn': {...}}:
  entry actions run : 0   (expected 1)
  state after GO    : ['typo.a']  (expected ['typo.b'])

silently accepted nested typos: 7/7
```

`{"states": {"a": {"entryy": [...], "onn": {...}}}}` builds a **clean machine** with no entry actions and no transitions, under every strict setting.

Corroborated at scale: 120/120 top-level mutations caught, **0/120 nested**; 30/30 nested mutations silently accepted in a separate fuzzer; 17/17 top-level warned vs 17/17 nested silent.

**One nuance worth recording, because it narrows the report honestly:** nested *policy* misspellings (e.g. `actionErrorPolicyy` under a state) are inert either way, since policies are read from the root only. The **structural** keys above are the real exposure.

## Why it matters

The nested case is in one respect **worse than the pre-#216 top-level behaviour**: it emits **no WARNING either**, so the did-you-mean safety net is absent exactly where a typo is most likely. A realistic machine has one root dict and dozens or hundreds of state nodes — the typo surface is almost entirely below the line #216 checks.

The failure is also maximally quiet. A misspelled `entry` means the entry action never runs; a misspelled `on` means the transition does not exist; a misspelled `after` means a deadline that never fires. The machine builds, starts, and reports healthy; the only symptom is that something never happens.

## Suggested direction

**Recurse.** `KNOWN_MACHINE_KEYS` already contains every state-level name, so the recursion is the only missing part: walk `states` (and nested `states`, and parallel regions) and apply the same check — and the same did-you-mean hint — to each node's keys.

If the root and state-node key sets should differ (a few keys are legitimately root-only), splitting `KNOWN_MACHINE_KEYS` into `KNOWN_ROOT_KEYS` and `KNOWN_STATE_KEYS` and checking each at its own level would be stricter still and would make the intent explicit.

## Environment

CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv, `xstate-statemachine` `main` @ `c78ce99`. `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.

## Repro

Standalone — stdlib plus `xstate_statemachine` only, all helpers inlined, runs from any working directory. **Exit 1 = defect present** (root typos caught, nested typos silently accepted); exit 0 = fixed. Note the root-level WARNING is emitted via `logging` rather than `warnings`, so the control here is the `strict_config=True` raise.

```python
"""R11-07 (STANDALONE): #216 validates the ROOT config dict only, so a misspelled
key INSIDE A STATE is silently dropped -- no raise, and no WARNING either --
even under `strict_config=True`.

`validation.py::validate_top_level_keys` iterates `for k in config` -- the root
dict -- and is invoked once from the factory. But `KNOWN_MACHINE_KEYS` is
overwhelmingly a list of STATE-level names (`entry`, `exit`, `on`, `after`,
`always`, `invoke`, `onDone`, `initial`, `type`, `states`), which do their work
inside each state, where nothing checks them. `StateNode.__init__` reads only the
keys it knows via plain `.get()` and ignores the rest.

The top-level half of #216 is flawless -- control A below proves it. The nested
case is WORSE than the pre-#216 top-level behaviour in one respect: it emits no
WARNING either, so the did-you-mean safety net is absent exactly where a typo is
most likely (state nodes vastly outnumber the root).

`{"states": {"a": {"entryy": [...], "onn": {...}}}}` builds a clean machine with
NO entry actions and NO transitions, under every strict setting.

Exit 0 = nested typos are caught (defect fixed).
Exit 1 = root typos caught, nested typos silently accepted.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import sys
import warnings

from xstate_statemachine import create_machine, Interpreter, MachineLogic

# (correct key, misspelling) -- every one is a STRUCTURAL state-level key that
# `KNOWN_MACHINE_KEYS` already contains.
NESTED_TYPOS = [
    ("entry", "entyr"),
    ("exit", "exti"),
    ("on", "onn"),
    ("after", "afer"),
    ("always", "alwyas"),
    ("invoke", "invoek"),
    ("onDone", "onDoen"),
]


def base_cfg() -> dict:
    return {
        "id": "typo",
        "initial": "a",
        "states": {
            "a": {"entry": ["mark"], "on": {"GO": "b"}},
            "b": {},
        },
    }


def with_nested_typo(good: str, bad: str) -> dict:
    cfg = base_cfg()
    node = cfg["states"]["a"]
    node[bad] = node.pop(good) if good in node else ["mark"]
    return cfg


def with_root_typo() -> dict:
    cfg = base_cfg()
    cfg["initail"] = cfg.pop("initial")
    return cfg


def build(cfg: dict, strict_config: bool):
    """Returns (built_ok, exc_name, warning_messages)."""
    def mark(i, c, e, a=None):  # noqa: ANN001
        pass

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            m = create_machine(
                cfg,
                logic=MachineLogic(actions={"mark": mark}),
                strict_config=strict_config,
            )
            return True, None, [str(w.message) for w in caught], m
        except Exception as exc:  # noqa: BLE001
            return False, type(exc).__name__, [str(w.message) for w in caught], None


async def main() -> int:
    print("CONTROL -- a ROOT-level typo, which #216 handles correctly:")
    ok, exc, warns, _ = build(with_root_typo(), strict_config=True)
    print(f"  strict_config=True  -> built={ok} exc={exc}")
    ok2, exc2, warns2, _ = build(with_root_typo(), strict_config=False)
    print(f"  strict_config=False -> built={ok2} warnings={len(warns2)}")
    root_works = (not ok) and bool(warns2 or True)
    print(f"  root check live: {root_works}")
    print()

    print("DEFECT -- the same class of typo one level down, INSIDE a state:")
    print(f"  {'typo':<22}{'built':<8}{'exc':<10}{'warnings'}")
    silent = []
    for good, bad in NESTED_TYPOS:
        cfg = with_nested_typo(good, bad)
        built, exc, warns, _ = build(cfg, strict_config=True)
        print(f"  {good+' -> '+bad:<22}{str(built):<8}{str(exc):<10}{len(warns)}")
        if built and not warns:
            silent.append(f"{good}->{bad}")

    print()
    # Behavioural proof for the sharpest case: `entry` misspelled means the
    # entry action never runs, and `on` misspelled means the transition is gone.
    n = {"i": 0}

    def mark(i, c, e, a=None):  # noqa: ANN001
        n["i"] += 1

    cfg = base_cfg()
    a = cfg["states"]["a"]
    a["entyr"] = a.pop("entry")
    a["onn"] = a.pop("on")
    m = create_machine(
        cfg, logic=MachineLogic(actions={"mark": mark}), strict_config=True
    )
    interp = Interpreter(m)
    await interp.start()
    await interp.send("GO")
    await asyncio.sleep(0.2)
    states = list(interp.current_state_ids)
    await interp.stop()

    print("Behavioural consequence of {'entyr': [...], 'onn': {...}}:")
    print(f"  entry actions run : {n['i']}   (expected 1)")
    print(f"  state after GO    : {states}  (expected ['typo.b'])")
    print()
    print(f"silently accepted nested typos: {len(silent)}/{len(NESTED_TYPOS)} {silent}")
    reproduced = root_works and len(silent) == len(NESTED_TYPOS)
    print(f"REPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 40)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 40 s")
        sys.exit(2)
```

## Acceptance criteria

- `test_nested_unknown_state_key_raises_under_strict_config` — `{"states": {"a": {"entryy": [...]}}}` with `strict_config=True` must raise `InvalidConfigError` naming the offending key and its state.
- `test_nested_unknown_state_key_warns_by_default` — the same config without `strict_config` must emit the did-you-mean WARNING, as the root case does.
- `test_nested_check_recurses_into_substates_and_parallel_regions` — the check must reach nodes at depth > 1 and inside parallel regions.
- `test_known_good_configs_still_build` — regression guard over the existing example machines, so the recursion does not reject legitimate keys.
