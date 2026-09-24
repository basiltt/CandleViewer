# -*- coding: utf-8 -*-
"""X7 -- #216 config-key fuzzer: top level AND nested state level.

STANDALONE. Neutral cwd.

#216 added `validate_top_level_keys` + `KNOWN_MACHINE_KEYS`: an unknown
TOP-LEVEL key warns (default) or raises under `strict_config=True` /
`"strictConfig": true`. This fuzzes:

  A  TOP-LEVEL misspellings of every policy key -> caught? hint correct?
  B  NESTED (inside a `states.<id>` node) misspellings -- DOCUMENT what
     happens. The changelog says "top-level"; a state node reads the same
     KNOWN_MACHINE_KEYS, so a misspelled `maxIteration` / `alwayz` /
     `invok` on a STATE is the same class of silent-default bug.
  C  strict_config bypass via the `x-` reserved prefix: can a REAL policy
     misspelling be smuggled as `x-strict`? (expected: yes, and inert --
     the point is whether `x-` can ever be READ as a policy.)
  D  `"strictConfig": true` in-config vs `strict_config=True` kwarg, and
     which wins when they disagree.
  E  the behavioural consequence: a machine with `Strict` instead of
     `strict` -- does the forged-event gate silently go away?
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import random

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

KIND = os.environ.get("XS_SVC", "async")

BASE = {
    "id": "cf",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": "b"}}, "b": {"type": "final"}},
}

POLICY_KEYS = [
    "actionErrorPolicy", "guardErrorPolicy", "onUnhandled", "maxIterations",
    "spawnBlockingTimeout", "strict", "strictTargets", "strictConfig",
]


def mutate(key, rnd):
    """One-character typo / case / plural mutation."""
    ops = []
    ops.append(key + "y")
    ops.append(key + "s")
    ops.append(key[0].upper() + key[1:])
    ops.append(key[:-1])
    ops.append(key.replace("o", "0", 1) if "o" in key else key + "_")
    ops.append(key.lower())
    return [o for o in ops if o != key]


def capture_warnings(fn):
    log = logging.getLogger("xstate_statemachine")
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.WARNING)
    old = log.level
    log.setLevel(logging.WARNING)
    log.addHandler(h)
    try:
        result, exc = None, None
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001
            exc = e
    finally:
        log.removeHandler(h)
        log.setLevel(old)
    return result, exc, buf.getvalue()


def part_a():
    print("=== A. TOP-LEVEL policy-key misspellings ===")
    rnd = random.Random(7)
    caught_warn = caught_strict = missed_warn = missed_strict = 0
    hint_ok = hint_bad = 0
    examples = []
    for key in POLICY_KEYS:
        for bad in mutate(key, rnd):
            cfg = json.loads(json.dumps(BASE))
            cfg[bad] = True
            _, exc, warn = capture_warnings(
                lambda c=cfg: create_machine(c, logic=MachineLogic())
            )
            w = bad in warn
            if w:
                caught_warn += 1
                if f"did you mean '{key}'" in warn:
                    hint_ok += 1
                else:
                    hint_bad += 1
                    if len(examples) < 6:
                        examples.append((bad, key, warn.strip()[-110:]))
            else:
                missed_warn += 1
                if len(examples) < 6:
                    examples.append((bad, key, "NO WARNING"))
            cfg2 = json.loads(json.dumps(BASE))
            cfg2[bad] = True
            _, exc2, _ = capture_warnings(
                lambda c=cfg2: create_machine(c, logic=MachineLogic(),
                                              strict_config=True)
            )
            if isinstance(exc2, InvalidConfigError):
                caught_strict += 1
            else:
                missed_strict += 1
    total = caught_warn + missed_warn
    print(f"   {total} mutations: warned={caught_warn} silent={missed_warn}")
    print(f"   strict_config=True raised={caught_strict} silent={missed_strict}")
    print(f"   hint named the right key: {hint_ok}/{caught_warn} "
          f"(wrong/absent hint: {hint_bad})")
    for e in examples:
        print(f"     {e[0]!r} (meant {e[1]!r}) -> {e[2]}")
    print(f"   VERDICT top-level = "
          f"{'PASS' if missed_warn == 0 and missed_strict == 0 else 'GAP'}")


def part_b():
    print("\n=== B. NESTED (state-node) misspellings -- documented ===")
    rnd = random.Random(11)
    silent = []
    for key in ["entry", "exit", "always", "invoke", "after", "on", "initial",
                "type", "onDone", "maxIterations"]:
        for bad in mutate(key, rnd)[:3]:
            cfg = json.loads(json.dumps(BASE))
            cfg["states"]["a"][bad] = (
                True if key in ("type", "initial", "maxIterations") else []
            )
            _, exc, warn = capture_warnings(
                lambda c=cfg: create_machine(c, logic=MachineLogic(),
                                             strict_config=True)
            )
            caught = isinstance(exc, InvalidConfigError) or bad in warn
            if not caught:
                silent.append(bad)
    print(f"   nested mutations tried = 30, silently accepted = {len(silent)}")
    print(f"   examples: {sorted(set(silent))[:12]}")
    print("   VERDICT nested = "
          f"{'CHECKED' if not silent else 'NOT CHECKED (#216 is top-level only)'}")


def part_c():
    print("\n=== C. `x-` reserved-prefix bypass ===")
    for k in ("x-strict", "x-maxIterations", "x-actionErrorPolicy"):
        cfg = json.loads(json.dumps(BASE))
        cfg[k] = True
        m, exc, warn = capture_warnings(
            lambda c=cfg: create_machine(c, logic=MachineLogic(),
                                         strict_config=True)
        )
        eff = None if m is None else (getattr(m, "strict", None),
                                      getattr(m, "max_iterations", None))
        print(f"   {k:22s}: exc={type(exc).__name__ if exc else None} "
              f"warn={'yes' if warn.strip() else 'no'} (strict,maxIter)={eff}")
    print("   NOTE: `x-` is accepted silently BY DESIGN and is never read as "
          "a policy -- a bypass of the WARNING, not of any policy.")


def part_d():
    print("\n=== D. in-config strictConfig vs the kwarg ===")
    for in_cfg, kwarg in ((True, None), (False, None), (None, True),
                          (True, False), (False, True)):
        cfg = json.loads(json.dumps(BASE))
        cfg["Strict"] = True  # the misspelling under test
        if in_cfg is not None:
            cfg["strictConfig"] = in_cfg
        kw = {} if kwarg is None else {"strict_config": kwarg}
        _, exc, warn = capture_warnings(
            lambda c=cfg, k=kw: create_machine(c, logic=MachineLogic(), **k)
        )
        print(f"   config.strictConfig={in_cfg!r:5s} kwarg={kwarg!r:5s} -> "
              f"{'RAISED' if exc else ('warned' if warn.strip() else 'SILENT')}")
    print("   (kwarg is None -> config wins; kwarg set -> kwarg wins)")


async def part_e():
    print("\n=== E. behavioural consequence of a silent `Strict` typo ===")
    from xstate_statemachine import Interpreter
    from xstate_statemachine.events import DoneEvent

    for key in ("strict", "Strict"):
        cfg = json.loads(json.dumps(BASE))
        cfg["id"] = "e" + key
        cfg[key] = True
        m, _, warn = capture_warnings(
            lambda c=cfg: create_machine(c, logic=MachineLogic())
        )
        i = Interpreter(m)
        await i.start()
        try:
            await i.send(DoneEvent(type="done.invoke.k", data=1, src="k"))
            refused = False
        except Exception:  # noqa: BLE001
            refused = True
        await i.stop()
        print(f"   {key!r:9s}: machine.strict={getattr(m, 'strict', '?')} "
              f"forged done.invoke refused={refused} "
              f"warned={'yes' if warn.strip() else 'NO'}")


async def main():
    print(f"X7 kind={KIND}")
    part_a()
    part_b()
    part_c()
    part_d()
    await part_e()


asyncio.run(main())
