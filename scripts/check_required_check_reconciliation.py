#!/usr/bin/env python3
"""GOV-005 support: reconcile the required-check names embedded in
.github/branch-protection.json (`required_status_checks.contexts` and
`x-pending-contexts`) against CONSTITUTION.md §9 (the single source of truth
for check names, C-16.5) and, once E03 creates them, the job names declared
in .github/workflows/*.yml.

Every name in the desired-state file must exist verbatim in the §9 table.
Every §9 check name must appear in either `contexts` (already required) or
`x-pending-contexts` (not yet required) — this closes the gap where a check
is renamed and its "required" status silently evaporates.

Exit codes: 0 clean, 1 mismatch found, 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys

DEFAULT_DESIRED_STATE_PATH = ".github/branch-protection.json"
DEFAULT_CONSTITUTION_PATH = "CONSTITUTION.md"
DEFAULT_WORKFLOWS_GLOB = ".github/workflows/*.yml"

# Bootstrap-only contexts that are legitimately required in `contexts` before
# all 20 CONSTITUTION.md §9 checks exist (E03), but are not themselves one of
# the 20 permanent names. `governance` (E01-Q02's governance regression pack)
# is the only one authorised for phase 1 of E01-T08's rollout; it must be
# retired from this set once E03 lands the full check suite.
BOOTSTRAP_ONLY_CONTEXTS = frozenset({"governance"})

# Matches a row of the §9 table: "| 1 | `lint` | ... |"
CHECK_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*`([a-z0-9-]+)`\s*\|")
JOB_NAME_RE = re.compile(r"^\s{0,2}([a-zA-Z0-9_-]+):\s*$")


class ReconciliationError(Exception):
    pass


def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise ReconciliationError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReconciliationError(f"{path} is not valid JSON: {exc}") from exc


def load_constitution_check_names(path: str) -> list[str]:
    names: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            in_table = False
            for line in fh:
                if line.strip().startswith("| # | Check name"):
                    in_table = True
                    continue
                if in_table:
                    if not line.strip().startswith("|"):
                        break
                    match = CHECK_ROW_RE.match(line.strip())
                    if match:
                        names.append(match.group(1))
    except FileNotFoundError as exc:
        raise ReconciliationError(f"file not found: {path}") from exc
    if not names:
        raise ReconciliationError(
            f"no §9 check rows found in {path} — table heading may have moved"
        )
    return names


def load_workflow_job_names(workflows_glob: str) -> set[str]:
    """Best-effort extraction of top-level job ids from workflow YAML files,
    without a YAML dependency (stdlib only). Returns an empty set when no
    workflow files exist yet (pre-E03), which callers treat as "not yet
    checkable" rather than a mismatch."""
    job_names: set[str] = set()
    for wf_path in sorted(glob.glob(workflows_glob)):
        with open(wf_path, encoding="utf-8") as fh:
            lines = fh.readlines()
        in_jobs = False
        jobs_indent = None
        for line in lines:
            stripped = line.rstrip("\n")
            if stripped.strip() == "jobs:":
                in_jobs = True
                jobs_indent = len(stripped) - len(stripped.lstrip(" "))
                continue
            if not in_jobs:
                continue
            if not stripped.strip():
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            if indent <= jobs_indent:
                # dedented past the jobs: block
                in_jobs = False
                continue
            if indent == jobs_indent + 2:
                match = re.match(r"^([a-zA-Z0-9_-]+):\s*$", stripped.strip())
                if match:
                    job_names.add(match.group(1))
    return job_names


def reconcile(
    desired_state: dict, constitution_names: list[str], workflow_job_names: set[str]
) -> list[str]:
    errors: list[str] = []
    constitution_set = set(constitution_names)
    contexts = set(desired_state.get("required_status_checks", {}).get("contexts", []))
    pending = set(desired_state.get("x-pending-contexts", []))

    for name in sorted(contexts | pending):
        if name not in constitution_set and name not in BOOTSTRAP_ONLY_CONTEXTS:
            errors.append(
                f"'{name}' in branch-protection.json is not a §9 check name in CONSTITUTION.md"
            )

    for name in sorted(constitution_set):
        if name not in contexts and name not in pending:
            errors.append(
                f"§9 check '{name}' is missing from both required_status_checks.contexts "
                "and x-pending-contexts in branch-protection.json"
            )

    overlap = contexts & pending
    for name in sorted(overlap):
        errors.append(f"'{name}' appears in both contexts and x-pending-contexts (pick one)")

    if workflow_job_names:
        for name in sorted(contexts):
            if name not in workflow_job_names:
                errors.append(
                    f"'{name}' is required on main but no job named '{name}' exists in "
                    ".github/workflows/*.yml"
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired-state", default=DEFAULT_DESIRED_STATE_PATH)
    parser.add_argument("--constitution", default=DEFAULT_CONSTITUTION_PATH)
    parser.add_argument("--workflows-glob", default=DEFAULT_WORKFLOWS_GLOB)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        desired_state = load_json(args.desired_state)
        constitution_names = load_constitution_check_names(args.constitution)
        workflow_job_names = load_workflow_job_names(args.workflows_glob)
        errors = reconcile(desired_state, constitution_names, workflow_job_names)
    except ReconciliationError as exc:
        print(f"check-required-check-reconciliation: {exc}", file=sys.stderr)
        return 2

    if not errors:
        if not args.json:
            print("check-required-check-reconciliation: clean")
        else:
            print("[]")
        return 0

    if args.json:
        print(json.dumps([{"code": "GOV-005", "message": e} for e in errors], indent=2))
    else:
        for e in errors:
            print(f"GOV-005 {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
