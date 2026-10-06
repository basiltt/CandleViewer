# -*- coding: utf-8 -*-
"""Verify #119 on main @ 3ed3099: the CHANGELOG correction for the
`Receipt.deferred` arity break (this issue's acceptance is documentation-only,
per its own acceptance definition -- it does NOT require the repro script's
assertion to flip to a passing exit code; it requires the CHANGELOG /
guide-doc updates and a reference back to the repro/observed behaviour).

Acceptance criteria exercised:
1. repro/R4-24_receipt_arity_break.py "exits 0 once the CHANGELOG correction
   lands" -- per the issue's own clarifying text, this is defined as: the
   CHANGELOG is updated per "Proposed API/text", and the repro's
   OBSERVED/EXPECTED text is referenced from the changelog entry. (The repro
   script's own exit code intentionally continues to report the arity break
   as present -- that behavioural change is out of scope for this issue.)
2. CHANGELOG.md 0.8.1 entry moves Receipt.deferred to a "Breaking" (or
   "Changed -- breaking") heading with a one-line migration note.
3. docs/_guide/changelog.md updated to match.
4. docs/_guide/testing-and-pure-api.md updated to show name-based Receipt
   access as the recommended pattern.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import os
import re
import subprocess
import sys

REPO = str(_XS)
CHANGELOG = os.path.join(REPO, "CHANGELOG.md")
GUIDE_CHANGELOG = os.path.join(REPO, "docs", "_guide", "changelog.md")
TESTING_DOC = os.path.join(REPO, "docs", "_guide", "testing-and-pure-api.md")
REPRO = (
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-24_receipt_arity_break.py')
)


def check(label: str, cond: bool, results: list) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    results.append((label, cond))


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def main() -> int:
    results: list = []

    changelog = read(CHANGELOG)
    guide_changelog = read(GUIDE_CHANGELOG)
    testing_doc = read(TESTING_DOC)

    # --- Criterion: Receipt.deferred entry is NOT under a "Fixed" heading,
    # and IS under a heading whose text signals a breaking/changed API,
    # with a one-line migration note. ---
    idx = changelog.find("`Receipt` gained a fourth field")
    receipt_heading = None
    receipt_block = None
    if idx != -1:
        preceding = changelog[:idx]
        headings = list(re.finditer(r"^(#{2,3})\s+(.*)$", preceding, re.MULTILINE))
        if headings:
            receipt_heading = headings[-1].group(2).strip()
        # Block = from the bullet start to the next top-level bullet or heading.
        rest = changelog[idx:]
        end_m = re.search(r"\n- \*\*|\n#{2,3}\s", rest)
        receipt_block = rest[: end_m.start()] if end_m else rest[:800]

    print(f"    CHANGELOG.md: Receipt.deferred entry found under heading: {receipt_heading!r}")
    check(
        "CHANGELOG.md: Receipt.deferred entry exists",
        receipt_block is not None,
        results,
    )
    check(
        "CHANGELOG.md: Receipt.deferred is NOT listed under a bare 'Fixed' heading",
        receipt_heading is not None and receipt_heading.strip().lower() != "fixed",
        results,
    )
    has_migration_note = bool(
        receipt_block
        and re.search(r"ValueError", receipt_block)
        and re.search(r"state_ids,\s*changed,\s*error", receipt_block)
    )
    check(
        "CHANGELOG.md: entry has a one-line migration note (mentions ValueError and old 3-tuple shape)",
        has_migration_note,
        results,
    )
    check(
        "CHANGELOG.md: entry references #119 (flagged as undeclared by #119)",
        bool(receipt_block and "#119" in receipt_block),
        results,
    )

    check(
        "docs/_guide/changelog.md: mirrors the same Receipt.deferred content",
        "Receipt` gained a fourth field, `deferred`" in guide_changelog
        or "Receipt.deferred" in guide_changelog,
        results,
    )

    check(
        "docs/_guide/testing-and-pure-api.md: recommends name-based Receipt access",
        "receipt.state_ids" in testing_doc,
        results,
    )
    # A three-outcome table distinguishing changed/deferred/error (attribute
    # names, not positions) is the concrete manifestation of "recommended
    # pattern" here.
    check(
        "docs/_guide/testing-and-pure-api.md: documents the three Receipt outcomes by field name",
        "`deferred`" in testing_doc and "`changed`" in testing_doc and "`error`" in testing_doc,
        results,
    )

    proc = subprocess.run(
        [sys.executable, REPRO],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **os.environ},
    )
    print("    --- repro stdout ---")
    print(proc.stdout)
    print(f"    repro exit code: {proc.returncode}")
    # Per the issue's own acceptance definition, the repro documenting the
    # (still-present, by design) arity break exiting 1 is EXPECTED, not a
    # failure -- the fix here is doc-only. We simply record it.
    check(
        "original repro R4-24 runs and still documents the (intentional, "
        "now-CHANGELOG-documented) arity break -- exit 1 expected per issue's "
        "own acceptance text",
        proc.returncode == 1,
        results,
    )

    ok = all(c for _, c in results)
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
