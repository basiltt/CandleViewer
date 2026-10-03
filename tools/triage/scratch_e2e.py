"""Scratch e2e (E49-T01): run DoR triage on a disposable issue; opt-in, never run by CI.

Usage: GH_TOKEN=... GITHUB_REPOSITORY=owner/repo python -m tools.triage.scratch_e2e
Creates one `[scratch]` issue, runs `dor`, asserts the needs-dor label, closes it with a
marker comment. Nothing is deleted.
"""

from __future__ import annotations

import os
import sys

from tools.triage import run

MARKER = "scratch-e2e: disposable issue, closed by tools/triage/scratch_e2e.py"


def main() -> int:
    api = run.GhApi(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    issue = api.call(
        "POST",
        "/issues",
        {"title": "[scratch] triage e2e", "body": "scratch", "labels": ["type/bug"]},
    )
    n = int(issue["number"])
    try:
        if run.main(["dor", "--number", str(n)]) != 0:
            print("FAIL: dor exited non-zero", file=sys.stderr)
            return 1
        labels = {x["name"] for x in api.call("GET", f"/issues/{n}")["labels"]}
        comments = api.call("GET", f"/issues/{n}/comments") or []
        ok = "needs-dor" in labels and len(comments) >= 1
        print(f"scratch #{n}: labels={sorted(labels)} comments={len(comments)} ok={ok}")
        return 0 if ok else 1
    finally:
        api.call("POST", f"/issues/{n}/comments", {"body": MARKER})
        api.call(
            "PATCH", f"/issues/{n}", {"state": "closed", "state_reason": "not_planned"}
        )


if __name__ == "__main__":
    sys.exit(main())
