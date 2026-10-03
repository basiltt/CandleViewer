"""Regression-guard classifier: a Bug may close as completed only with a test change."""

from __future__ import annotations

import re
from dataclasses import dataclass

EXEMPT_LABEL = "p3-cosmetic-exempt"
_TEST = re.compile(
    r"(^|/)(tests?|__tests__|e2e)/|(^|/)test_[^/]+\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$"
)


def is_test_file(path: str) -> bool:
    return bool(_TEST.search(path.replace("\\", "/")))


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str


def evaluate(
    changed_files: list[str], labels: list[str], exempt_reason: str = ""
) -> GuardResult:
    if EXEMPT_LABEL in labels:
        if exempt_reason.strip():
            return GuardResult(True, "exempt: " + exempt_reason.strip())
        return GuardResult(
            False, f"label {EXEMPT_LABEL} requires a stated reason in the issue"
        )
    if any(is_test_file(f) for f in changed_files):
        return GuardResult(True, "test file changed")
    return GuardResult(
        False,
        "closing a Bug requires a regression test (03-testing-strategy.md §11.3): "
        f"add a test file change or apply {EXEMPT_LABEL} with a reason",
    )
