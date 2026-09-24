# -*- coding: utf-8 -*-
"""Verify #116 on main @ 3ed3099: SyncInterpreter and Interpreter, given the
identical machine and identical zero-gap (GO, CANCEL) x10 event script,
produce the identical final context.

Acceptance criteria exercised:
1. Both engines produce identical final context for the (GO, CANCEL)x10 script.
2/3. Equivalent to tests/test_round4_findings.py::
     TestPlainSyncInvokeTimingParity::test_go_cancel_script_agrees (re-run here).
4. repro/R4-21_sync_async_invoke_timing_divergence.py exits 0.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

CFG = {
    "id": "d8",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": "busy"}},
        "busy": {
            "invoke": {
                "id": "s",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}

REPRO = (
    r"C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer\docs"
    r"\research\xstate\issues\post-5e07ba8\new\repro"
    r"\R4-21_sync_async_invoke_timing_divergence.py"
)


def _bump(key):
    def action(interp, ctx, event, action_def=None):
        ctx[key] += 1

    return action


def _logic():
    return MachineLogic(
        actions={"ok": _bump("ok"), "cancel": _bump("cancel")},
        services={"work": lambda i, c, e: 1},
    )


def check(label: str, cond: bool, results: list) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    results.append((label, cond))


async def run_async():
    i = await Interpreter(create_machine(CFG, logic=_logic())).start()
    for _ in range(10):
        await i.send("GO")
        await i.send("CANCEL")
    for _ in range(200):
        await asyncio.sleep(0)
    out = dict(i.context)
    await i.stop()
    return out


def main() -> int:
    results: list = []

    s = SyncInterpreter(create_machine(CFG, logic=_logic()))
    s.start()
    for _ in range(10):
        s.send("GO")
        s.send("CANCEL")
    sync_ctx = dict(s.context)
    s.stop()

    async_ctx = asyncio.run(run_async())

    print(f"    sync_ctx={sync_ctx}")
    print(f"    async_ctx={async_ctx}")

    check("sync and async contexts are identical", sync_ctx == async_ctx, results)
    check("expected result is {'ok': 10, 'cancel': 0}", sync_ctx == {"ok": 10, "cancel": 0}, results)

    proc = subprocess.run(
        [sys.executable, REPRO],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **os.environ},
    )
    print("    --- repro stdout ---")
    print(proc.stdout)
    check("original repro R4-21 exits 0", proc.returncode == 0, results)

    ok = all(c for _, c in results)
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
