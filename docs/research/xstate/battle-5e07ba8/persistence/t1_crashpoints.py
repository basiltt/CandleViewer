# -*- coding: utf-8 -*-
"""T1 - exhaustive differential: every crash point of a fixed sequence.

For a handful of hand-picked event sequences, crash after each k in
0..len(seq) and compare the resumed outcome with the uninterrupted run.
"""
from __future__ import annotations

import asyncio
import json
import sys

from harness import Outcome, run_interrupted, run_plain

SEQS = {
    "happy": [
        {"type": "SUBMIT", "payload": {"qty": 7}},
        {"type": "RISK_OK"},
        {"type": "FILL", "payload": {"n": 2}},
        {"type": "FILL", "payload": {"n": 3}},
        {"type": "DONE"},
    ],
    "timers": [
        {"type": "SUBMIT", "payload": {"qty": 5}},
        {"type": "RISK_OK"},
        {"type": "__TICK__", "ms": 31000},
        {"type": "RETRY"},
        {"type": "FILL", "payload": {"n": 1}},
    ],
    "defer": [
        {"type": "FILL", "payload": {"n": 1}},
        {"type": "RISK_OK"},
        {"type": "SUBMIT", "payload": {"qty": 4}},
        {"type": "DONE"},
    ],
    "cancel": [
        {"type": "SUBMIT", "payload": {"qty": 9}},
        {"type": "RISK_OK"},
        {"type": "CANCEL"},
        {"type": "CANCEL_OK"},
    ],
}


def diff(a: Outcome, b: Outcome) -> list[str]:
    out = []
    for f in ("states", "context", "actions", "status", "error"):
        va, vb = getattr(a, f), getattr(b, f)
        if va != vb:
            out.append(f"{f}: plain={va!r} restored={vb!r}")
    return out


async def main() -> int:
    restart = "--restart" in sys.argv
    bad = 0
    total = 0
    for name, seq in SEQS.items():
        plain = await run_plain(seq)
        for k in range(len(seq) + 1):
            total += 1
            res, _ = await run_interrupted(
                seq, k, restart_services=restart
            )
            d = diff(plain, res)
            if d:
                bad += 1
                print(f"DIVERGENCE {name} k={k}")
                for line in d:
                    print("   ", line)
    print(f"\n{total - bad}/{total} crash points match "
          f"(restart_services={restart})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
