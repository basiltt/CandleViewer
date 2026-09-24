"""LC-39 verification on xstate-statemachine 0.8.0.

LC-39 is a DOCUMENTATION-gap issue, not a code defect: the original repro
is explicitly retained as a benchmark that exits 1 "by design" per its own
acceptance criteria, since single-loop-per-process throughput is correct,
unavoidable asyncio behaviour. What must be checked is whether the
documentation gap has been closed: a Performance/Production-Characteristics
guide page exists, states the single-event-loop / per-process-budget fact,
carries a measured scaling table, and is linked from the README.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(
    r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine"
)


def main() -> int:
    ok = True

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    perf_page = REPO / "docs" / "_guide" / "production-characteristics.md"
    interpreters_page = REPO / "docs" / "_guide" / "interpreters.md"

    print(f"OBSERVED: production-characteristics guide page exists = {perf_page.exists()}")
    print("EXPECTED: True")
    if not perf_page.exists():
        ok = False

    page_text = perf_page.read_text(encoding="utf-8") if perf_page.exists() else ""

    mentions_single_loop = bool(
        re.search(r"one asyncio event loop on one OS thread", page_text)
    )
    mentions_per_process_budget = "per-process budget" in page_text
    has_table = "ev/s" in page_text and "|" in page_text

    print(f"OBSERVED: page states single event loop / one OS thread = {mentions_single_loop}")
    print(f"OBSERVED: page states 'per-process budget' framing = {mentions_per_process_budget}")
    print(f"OBSERVED: page contains a measured scaling table = {has_table}")
    print("EXPECTED: all True")
    if not (mentions_single_loop and mentions_per_process_budget and has_table):
        ok = False

    readme_links = "production-characteristics" in readme
    interpreters_links = "production-characteristics" in interpreters_page.read_text(
        encoding="utf-8"
    ) if interpreters_page.exists() else False

    print(f"OBSERVED: README links to production-characteristics = {readme_links}")
    print(f"OBSERVED: interpreters guide links to production-characteristics = {interpreters_links}")
    print("EXPECTED: README (or a docstring/guide it references) links to the page")
    if not readme_links:
        ok = False

    print(
        "RESULT:",
        "FIXED-DEFAULT (docs gap closed; underlying throughput behaviour is unchanged by design)"
        if ok
        else "NOT FIXED (docs gap remains)",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
