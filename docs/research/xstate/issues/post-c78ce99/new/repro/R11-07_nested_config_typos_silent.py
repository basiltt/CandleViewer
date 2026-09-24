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
