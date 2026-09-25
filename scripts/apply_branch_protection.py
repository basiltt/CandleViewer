#!/usr/bin/env python3
"""GOV-005 support: idempotently apply .github/branch-protection.json to a
GitHub repository's `main` branch protection (CONSTITUTION.md C-9.1, C-10.1;
docs/plan/01-sdlc-and-branching.md §6.1, §7).

This script never runs automatically from a PR-triggered workflow (see the
break-glass runbook in CONTRIBUTING.md) — it is invoked manually by an admin
or via `workflow_dispatch` with an environment approval, using a credential
scoped to repository administration only.

Exit codes: 0 success / no-op, 1 desired-state validation failed or apply
failed, 2 internal error (network/auth not configured).
Stdlib only (urllib), so it runs before any package manager is scaffolded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_DESIRED_STATE_PATH = ".github/branch-protection.json"
API_BASE = "https://api.github.com"

# Keys that come from the desired-state file but are never sent to the
# GitHub REST API (either GOV-005-internal annotations or top-level
# metadata this script consumes itself, e.g. `branch`, `merge_queue`).
NON_API_KEYS = {"$comment", "$note_pending", "x-pending-contexts", "branch", "merge_queue"}

REQUIRED_TOP_LEVEL_KEYS = (
    "required_pull_request_reviews",
    "required_status_checks",
    "enforce_admins",
    "allow_force_pushes",
    "allow_deletions",
    "required_linear_history",
    "required_conversation_resolution",
)


class DesiredStateError(Exception):
    """Raised when the desired-state file fails validation."""


class ApplyError(Exception):
    """Raised when the GitHub API call fails."""


@dataclass(frozen=True)
class Diff:
    added: dict
    removed: dict
    changed: dict

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def render(self) -> str:
        lines = []
        for key, value in sorted(self.added.items()):
            lines.append(f"  + {key} = {json.dumps(value)}")
        for key, value in sorted(self.removed.items()):
            lines.append(f"  - {key} = {json.dumps(value)}")
        for key, (old, new) in sorted(self.changed.items()):
            lines.append(f"  ~ {key}: {json.dumps(old)} -> {json.dumps(new)}")
        return "\n".join(lines)


def load_desired_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise DesiredStateError(f"desired-state file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DesiredStateError(f"desired-state file is not valid JSON: {exc}") from exc
    validate_desired_state(data)
    return data


def validate_desired_state(data: dict) -> None:
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise DesiredStateError(
            f"desired-state file missing required key(s): {', '.join(missing)}"
        )
    rprr = data["required_pull_request_reviews"]
    if rprr.get("required_approving_review_count", 0) < 2:
        raise DesiredStateError(
            "required_approving_review_count must be >= 2 (CONSTITUTION.md C-10.1)"
        )
    if not rprr.get("require_code_owner_reviews"):
        raise DesiredStateError(
            "require_code_owner_reviews must be true (CONSTITUTION.md C-10.1)"
        )
    if data.get("enforce_admins") is not True:
        raise DesiredStateError(
            "enforce_admins must be true — there is no admin merge (CONSTITUTION.md C-9.1)"
        )
    if data.get("allow_force_pushes") is not False:
        raise DesiredStateError("allow_force_pushes must be false")
    if data.get("required_linear_history") is not True:
        raise DesiredStateError("required_linear_history must be true")
    contexts = data.get("required_status_checks", {}).get("contexts")
    if not isinstance(contexts, list):
        raise DesiredStateError("required_status_checks.contexts must be a list")
    pending = data.get("x-pending-contexts", [])
    if not isinstance(pending, list):
        raise DesiredStateError("x-pending-contexts must be a list when present")


def to_api_payload(desired: dict) -> dict:
    """Strip GOV-005-internal annotation keys, leaving exactly what the GitHub
    REST API's PUT .../branches/main/protection endpoint accepts."""
    return {k: v for k, v in desired.items() if k not in NON_API_KEYS}


def fetch_live_state(repo: str, token: str, branch: str = "main") -> dict:
    url = f"{API_BASE}/repos/{repo}/branches/{branch}/protection"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # No protection configured yet — treat as an empty live state.
            return {}
        raise ApplyError(f"GET {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {url} failed: {exc.reason}") from exc


def diff_state(live: dict, desired_payload: dict) -> Diff:
    """Shallow key-by-key diff. The live GitHub response nests values
    differently from the PUT body (e.g. `{"enabled": true}` wrappers), so
    callers should normalise both sides before calling this in production;
    for the purpose of this script (and its unit tests) both sides are
    compared as plain dicts of top-level keys."""
    added: dict = {}
    removed: dict = {}
    changed: dict = {}
    live_keys = set(live.keys())
    desired_keys = set(desired_payload.keys())
    for key in desired_keys - live_keys:
        added[key] = desired_payload[key]
    for key in live_keys - desired_keys:
        removed[key] = live[key]
    for key in live_keys & desired_keys:
        if live[key] != desired_payload[key]:
            changed[key] = (live[key], desired_payload[key])
    return Diff(added=added, removed=removed, changed=changed)


def apply_state(repo: str, token: str, payload: dict, branch: str = "main") -> None:
    url = f"{API_BASE}/repos/{repo}/branches/{branch}/protection"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            response.read()
    except urllib.error.HTTPError as exc:
        raise ApplyError(f"PUT {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"PUT {url} failed: {exc.reason}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired-state", default=DEFAULT_DESIRED_STATE_PATH)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--token-env",
        default="GH_BRANCH_PROTECTION_TOKEN",
        help="environment variable holding the repo-administration-scoped token",
    )
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the diff between live and desired state; change nothing",
    )
    args = parser.parse_args(argv)

    try:
        desired = load_desired_state(args.desired_state)
    except DesiredStateError as exc:
        print(f"apply-branch-protection: invalid desired state: {exc}", file=sys.stderr)
        return 1

    payload = to_api_payload(desired)

    if not args.repo:
        print("apply-branch-protection: --repo or $GITHUB_REPOSITORY required", file=sys.stderr)
        return 2
    token = os.environ.get(args.token_env)
    if not token:
        print(
            f"apply-branch-protection: token not found in ${args.token_env}",
            file=sys.stderr,
        )
        return 2

    try:
        live = fetch_live_state(args.repo, token, args.branch)
        diff = diff_state(live, payload)
        if diff.is_empty():
            print("apply-branch-protection: no changes — live state matches desired state")
            return 0
        print("apply-branch-protection: diff (live -> desired):")
        print(diff.render())
        if args.dry_run:
            print("apply-branch-protection: --dry-run set, not applying")
            return 0
        apply_state(args.repo, token, payload, args.branch)
        print("apply-branch-protection: applied")
        return 0
    except ApplyError as exc:
        print(f"apply-branch-protection: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
