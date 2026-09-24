"""Verify #215 (engine-work lap parity) and #216 (unknown top-level keys)
on main @ c78ce99.

Standalone: stdlib + xstate_statemachine only. Run from neutral cwd.
Exit 0 = all cells pass.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import warnings

from xstate_statemachine import (
    InvalidConfigError,
    Interpreter,
    MachineLogic,
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)

LIMITS = list(range(1, 26))
FAIL = []


def _cfg(mi: int) -> dict:
    return {
        "id": "w",
        "initial": "a",
        "maxIterations": mi,
        "states": {
            "a": {
                "entry": [
                    {"type": "raise", "params": {"event": "GO"}},
                    "tick",
                ],
                "on": {"GO": "b"},
            },
            "b": {"always": "a", "entry": ["tick"]},
        },
    }


def check_215():
    print("=== #215: engine-work-only lap parity, limits 1-25 ===")
    for mi in LIMITS:
        n = [0]

        def bump(i, c):
            n[0] += 1

        s = SyncInterpreter(
            create_machine(
                json.loads(json.dumps(_cfg(mi))),
                logic=MachineLogic(actions={"tick": lambda i, c, e, a: bump(i, c)}),
            )
        ).start()
        sync_n = n[0]
        sync_tripped = isinstance(s.last_error, RunawayChainError)

        async def run_async(kind):
            n[0] = 0

            def body(i, c):
                bump(i, c)

            if kind == "def":
                act = lambda i, c, e, a: body(i, c)
            else:
                async def act(i, c, e, a):
                    await asyncio.sleep(0)
                    body(i, c)

            i = await Interpreter(
                create_machine(
                    json.loads(json.dumps(_cfg(mi))),
                    logic=MachineLogic(actions={"tick": act}),
                )
            ).start()
            await asyncio.sleep(0.3)
            out = (n[0], type(i.last_error))
            await i.stop()
            return out

        results = {}
        for kind in ("def", "async def"):
            async_n, err_type = asyncio.run(run_async(kind))
            results[kind] = (async_n, err_type is RunawayChainError)

        ok = sync_tripped and all(
            results[k][0] == sync_n and results[k][1] for k in results
        )
        if not ok:
            FAIL.append(
                f"#215 mi={mi}: sync_n={sync_n} sync_trip={sync_tripped} "
                f"async={results}"
            )
        print(
            f"  mi={mi:2d}  sync_n={sync_n} trip={sync_tripped}  "
            f"async_def={results['def']}  async_async={results['async def']}"
        )


BASE = {"id": "m", "initial": "a", "states": {"a": {}}}

TYPOS = [
    ("actionErrorPolicyy", "action_error_policy", "rollback"),
    ("Strict", "strict", True),
    ("maxIteration", "max_iterations", 42),
    ("onUnhandledEvent", "on_unhandled", "error"),
]


def check_216():
    print("=== #216: unknown top-level keys ===")
    logs = []

    class H(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())

    handler = H()
    logging.getLogger("xstate_statemachine").addHandler(handler)
    logging.getLogger("xstate_statemachine").setLevel(logging.WARNING)

    for typo, attr, val in TYPOS:
        cfg = dict(BASE)
        cfg[typo] = val
        logs.clear()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())
        hinted = any(typo in msg and "did you mean" in msg for msg in logs)
        if not hinted:
            FAIL.append(f"#216 warn missing hint for {typo}: logs={logs}")
        print(f"  {typo:<24} warned_with_hint={hinted}")

    # strict_config=True raises
    cfg = dict(BASE)
    cfg["actionErrorPolicyy"] = "rollback"
    try:
        create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic(), strict_config=True)
        FAIL.append("#216 strict_config=True did not raise")
        print("  strict_config=True -> did NOT raise (FAIL)")
    except InvalidConfigError:
        print("  strict_config=True -> InvalidConfigError (OK)")

    # "strictConfig": true in config raises
    cfg2 = dict(BASE)
    cfg2["actionErrorPolicyy"] = "rollback"
    cfg2["strictConfig"] = True
    try:
        create_machine(json.loads(json.dumps(cfg2)), logic=MachineLogic())
        FAIL.append("#216 config-level strictConfig=true did not raise")
        print("  config strictConfig:true -> did NOT raise (FAIL)")
    except InvalidConfigError:
        print("  config strictConfig:true -> InvalidConfigError (OK)")

    # accepted keys: x-, meta, description, tags, version
    cfg3 = dict(BASE)
    cfg3.update(
        {
            "x-custom": 1,
            "meta": {"a": 1},
            "description": "d",
            "tags": ["t"],
            "version": "1.0",
        }
    )
    logs.clear()
    try:
        create_machine(json.loads(json.dumps(cfg3)), logic=MachineLogic(), strict_config=True)
        ok = not logs
        print(f"  reserved/meta keys accepted, no warnings: {ok}")
        if not ok:
            FAIL.append(f"#216 reserved keys triggered warnings: {logs}")
    except InvalidConfigError as e:
        FAIL.append(f"#216 reserved keys raised unexpectedly: {e}")
        print(f"  reserved/meta keys -> unexpected raise: {e}")

    logging.getLogger("xstate_statemachine").removeHandler(handler)


def main() -> int:
    check_215()
    check_216()
    print()
    if FAIL:
        print(f"FAIL ({len(FAIL)}):")
        for f in FAIL:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
