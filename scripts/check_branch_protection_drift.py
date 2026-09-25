#!/usr/bin/env python3
"""GOV-005: detect drift between live GitHub branch protection on `main` and
the desired state in .github/branch-protection.json (CONSTITUTION.md C-9.1;
docs/plan/01-sdlc-and-branching.md §6.1).

Run ad hoc, or by the weekly `governance-drift` schedule. Any difference is
reported as a GOV-005 finding; the caller (workflow) opens a
`priority/p1-high` `security`-labelled issue for each one.

Exit codes: 0 no drift, 1 drift found, 2 internal error (network/auth/file).
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys

from apply_branch_protection import (
    ApplyError,
    DesiredStateError,
    diff_state,
    fetch_live_state,
    load_desired_state,
    to_api_payload,
)

DEFAULT_DESIRED_STATE_PATH = ".github/branch-protection.json"


def render_findings(diff, as_json: bool) -> str:
    if as_json:
        findings = []
        for key, value in diff.added.items():
            findings.append({"code": "GOV-005", "kind": "missing_on_live", "key": key, "desired": value})
        for key, value in diff.removed.items():
            findings.append({"code": "GOV-005", "kind": "unexpected_on_live", "key": key, "live": value})
        for key, (old, new) in diff.changed.items():
            findings.append(
                {"code": "GOV-005", "kind": "changed", "key": key, "live": old, "desired": new}
            )
        return json.dumps(findings, indent=2)
    return "GOV-005 branch protection drift detected:\n" + diff.render()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired-state", default=DEFAULT_DESIRED_STATE_PATH)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--token-env", default="GH_BRANCH_PROTECTION_TOKEN")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import os

    try:
        desired = load_desired_state(args.desired_state)
    except DesiredStateError as exc:
        print(f"check-branch-protection-drift: invalid desired state: {exc}", file=sys.stderr)
        return 2

    token = os.environ.get(args.token_env)
    if not token:
        print(
            f"check-branch-protection-drift: token not found in ${args.token_env}",
            file=sys.stderr,
        )
        return 2

    payload = to_api_payload(desired)
    try:
        live = fetch_live_state(args.repo, token, args.branch)
    except ApplyError as exc:
        print(f"check-branch-protection-drift: {exc}", file=sys.stderr)
        return 2

    diff = diff_state(live, payload)
    if diff.is_empty():
        if not args.json:
            print("check-branch-protection-drift: no drift")
        else:
            print("[]")
        return 0

    print(render_findings(diff, args.json))
    return 1


if __name__ == "__main__":
    sys.exit(main())
