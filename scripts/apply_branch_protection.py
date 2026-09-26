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
    REST API's PUT .../branches/main/protection endpoint accepts.

    `restrictions` is a required key on that endpoint (null is a valid value,
    meaning "no push-access restriction beyond protection itself"); the
    desired-state file does not model per-actor push restrictions today, so
    this always sends `null` unless the file explicitly sets one."""
    payload = {k: v for k, v in desired.items() if k not in NON_API_KEYS}
    payload.setdefault("restrictions", desired.get("restrictions", None))
    return payload


def fetch_live_state(repo: str, token: str, branch: str = "main") -> dict:
    """Fetch and normalise (see `_normalise_live_state`) the live protection
    state so callers can diff it directly against a `to_api_payload` result."""
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
            return _normalise_live_state(json.loads(response.read()))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # No protection configured yet — treat as an empty live state.
            return {}
        raise ApplyError(f"GET {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {url} failed: {exc.reason}") from exc


# Top-level keys the GET .../protection response wraps as `{"enabled": bool}`
# (or, for `required_pull_request_reviews`/`required_status_checks`, embeds
# extra read-only fields such as `url`/`contexts_url`/`checks`) that the PUT
# body does not accept in that shape. Mapped here so the live response can be
# normalised into the same flat shape as the desired-state payload before
# diffing — otherwise every key differs on every run and re-apply is never a
# no-op (AC4).
_BOOL_WRAPPED_KEYS = (
    "enforce_admins",
    "allow_force_pushes",
    "allow_deletions",
    "required_linear_history",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
)

# Read-only fields GitHub adds to nested objects in the GET response that
# never appear in (and are rejected or ignored by) the PUT body.
_NESTED_READONLY_KEYS = {"url", "contexts_url", "checks", "users_url", "teams_url", "apps_url"}


# Top-level fields GitHub adds to the GET response that are pure metadata
# about the response itself, never part of any desired state and never
# accepted by the PUT body.
_TOP_LEVEL_READONLY_KEYS = {"url"}


def _normalise_live_state(live: dict) -> dict:
    """Reshape a raw GET .../branches/{branch}/protection response into the
    flat shape the PUT body (and this repo's desired-state file) uses, so
    `diff_state` compares like with like."""
    normalised: dict = {}
    for key, value in live.items():
        if key in _TOP_LEVEL_READONLY_KEYS:
            continue
        if key in _BOOL_WRAPPED_KEYS and isinstance(value, dict) and "enabled" in value:
            normalised[key] = value["enabled"]
        elif isinstance(value, dict):
            normalised[key] = {
                k: v for k, v in value.items() if k not in _NESTED_READONLY_KEYS
            }
        else:
            normalised[key] = value
    return normalised


def diff_state(live: dict, desired_payload: dict) -> Diff:
    """Shallow key-by-key diff between the (already-normalised) live state
    and the desired PUT payload. Callers reading from the real GitHub API
    MUST pass `live` through `_normalise_live_state` first — `fetch_live_state`
    does this for them; the two are kept separate only so unit tests can
    exercise the diff logic directly against hand-built flat dicts."""
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


# --- Merge queue (repository rulesets API) -----------------------------
#
# The GitHub merge queue is not part of classic branch protection; it is
# configured as a repository ruleset (`target: branch`) carrying a
# `merge_queue` rule whose `parameters` mirror this file's `merge_queue`
# block. `NON_API_KEYS` still excludes `merge_queue` from the protection PUT
# body — it is applied and drift-checked separately via the functions below.
MERGE_QUEUE_RULESET_NAME = "candleviewer-main-merge-queue"


def _merge_queue_rule_params(desired: dict, branch: str) -> dict | None:
    mq = desired.get("merge_queue")
    if not mq:
        return None
    return {
        "name": MERGE_QUEUE_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": [f"refs/heads/{branch}"], "exclude": []}},
        "rules": [{"type": "merge_queue", "parameters": dict(mq)}],
    }


def fetch_merge_queue_ruleset(repo: str, token: str) -> dict:
    """Return the live merge-queue ruleset's rule parameters, or `{}` if no
    ruleset with `MERGE_QUEUE_RULESET_NAME` exists yet."""
    url = f"{API_BASE}/repos/{repo}/rulesets?includes_parents=false"
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
            summaries = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ApplyError(f"GET {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {url} failed: {exc.reason}") from exc

    match = next((r for r in summaries if r.get("name") == MERGE_QUEUE_RULESET_NAME), None)
    if match is None:
        return {}
    detail_url = f"{API_BASE}/repos/{repo}/rulesets/{match['id']}"
    detail_request = urllib.request.Request(
        detail_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(detail_request, timeout=30) as response:  # noqa: S310
            detail = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ApplyError(f"GET {detail_url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {detail_url} failed: {exc.reason}") from exc

    for rule in detail.get("rules", []):
        if rule.get("type") == "merge_queue":
            return dict(rule.get("parameters", {}))
    return {}


def diff_merge_queue(live_params: dict, desired: dict) -> Diff:
    """Diff the live merge-queue rule parameters against `desired["merge_queue"]`."""
    return diff_state(live_params, dict(desired.get("merge_queue") or {}))


def _fetch_merge_queue_ruleset_id(repo: str, token: str) -> int | None:
    url = f"{API_BASE}/repos/{repo}/rulesets?includes_parents=false"
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
            summaries = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ApplyError(f"GET {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {url} failed: {exc.reason}") from exc
    match = next((r for r in summaries if r.get("name") == MERGE_QUEUE_RULESET_NAME), None)
    return match["id"] if match else None


def apply_merge_queue_ruleset(repo: str, token: str, desired: dict, branch: str = "main") -> None:
    """Idempotently create-or-update the merge-queue ruleset: POST to create
    it the first time, PUT to update it on subsequent applies (a bare POST
    on every run would fail with a duplicate-name conflict)."""
    body_dict = _merge_queue_rule_params(desired, branch)
    if body_dict is None:
        return
    existing_id = _fetch_merge_queue_ruleset_id(repo, token)
    if existing_id is None:
        url = f"{API_BASE}/repos/{repo}/rulesets"
        method = "POST"
    else:
        url = f"{API_BASE}/repos/{repo}/rulesets/{existing_id}"
        method = "PUT"
    body = json.dumps(body_dict).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
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
        raise ApplyError(f"{method} {url} (merge queue ruleset) failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"{method} {url} (merge queue ruleset) failed: {exc.reason}") from exc


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

        mq_diff = Diff(added={}, removed={}, changed={})
        if desired.get("merge_queue"):
            mq_live = fetch_merge_queue_ruleset(args.repo, token)
            mq_diff = diff_merge_queue(mq_live, desired)

        if diff.is_empty() and mq_diff.is_empty():
            print("apply-branch-protection: no changes — live state matches desired state")
            return 0
        if not diff.is_empty():
            print("apply-branch-protection: protection diff (live -> desired):")
            print(diff.render())
        if not mq_diff.is_empty():
            print("apply-branch-protection: merge-queue ruleset diff (live -> desired):")
            print(mq_diff.render())
        if args.dry_run:
            print("apply-branch-protection: --dry-run set, not applying")
            return 0
        if not diff.is_empty():
            apply_state(args.repo, token, payload, args.branch)
        if not mq_diff.is_empty():
            apply_merge_queue_ruleset(args.repo, token, desired, args.branch)
        print("apply-branch-protection: applied")
        return 0
    except ApplyError as exc:
        print(f"apply-branch-protection: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
