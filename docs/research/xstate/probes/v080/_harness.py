"""Tiny result harness shared by the v0.8.0 adversarial probes.

Each probe file defines checks that append (id, title, ok, detail) and
prints a table. Exit code 0 always: these probes REPORT, the doc judges.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable, List, Tuple

Result = Tuple[str, str, bool, str]


class Probe:
    def __init__(self, name: str) -> None:
        self.name = name
        self.results: List[Result] = []

    def check(self, pid: str, title: str, ok: bool, detail: Any = "") -> None:
        self.results.append((pid, title, bool(ok), str(detail)))

    def record_exc(self, pid: str, title: str, exc: BaseException) -> None:
        self.results.append(
            (pid, title, False, f"{type(exc).__name__}: {exc}")
        )

    def run(self, pid: str, title: str, fn: Callable[[], Tuple[bool, Any]]):
        try:
            ok, detail = fn()
            self.check(pid, title, ok, detail)
        except Exception as exc:  # noqa: BLE001
            self.record_exc(pid, title, exc)
            traceback.print_exc()

    def report(self) -> None:
        print(f"\n=== {self.name} ===")
        width = max((len(r[1]) for r in self.results), default=10)
        for pid, title, ok, detail in self.results:
            flag = "PASS" if ok else "FAIL"
            print(f"[{flag}] {pid:<8} {title:<{width}}  {detail}")
        bad = [r for r in self.results if not r[2]]
        print(f"--- {len(self.results) - len(bad)}/{len(self.results)} pass")
