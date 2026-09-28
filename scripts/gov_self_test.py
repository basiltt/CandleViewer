#!/usr/bin/env python3
"""E01-Q02 canary/self-test mode for the `governance` required-check job.

A checker that crashes (or is silently disabled) and still reports success
is worse than no check at all — a green tick that no longer checks anything.
This script builds a deliberately-broken fixture tree for each GOV-00n
checker in the governance job and asserts the checker's `main()` returns a
*non-zero* exit code against it. It also cross-checks the workflow file's
own step manifest against the set of checkers this script knows about, so
that removing a checker invocation from `.github/workflows/governance.yml`
without removing it here (or vice versa) is itself a caught defect.

Exit codes: 0 all checkers correctly failed against their broken fixture
(and the manifest matches), 1 at least one checker did NOT fail (or the
manifest is out of sync), 2 internal error.

Stdlib + PyYAML only (PyYAML already a governance-job dependency for GOV-004).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
GOVERNANCE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "governance.yml"

# The manifest this self-test compares itself against. Each entry names the
# GOV-00n code, a short label matched against a step `name:` in
# governance.yml (so a step rename without updating this list is caught),
# and a builder that returns (module, argv, broken-fixture describer).
CHECKER_MANIFEST = [
    {"code": "GOV-002", "step_name_contains": "Rule-reference"},
    {"code": "GOV-003", "step_name_contains": "Single-source-of-truth"},
    {"code": "GOV-001", "step_name_contains": "CODEOWNERS coverage"},
    {"code": "GOV-004a", "step_name_contains": "Issue form structural"},
    {"code": "GOV-004b", "step_name_contains": "Backlog validation"},
    {"code": "GOV-005", "step_name_contains": "Required-check reconciliation"},
]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "gov-self-test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "gov-self-test"], cwd=root, check=True)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _add_all(root: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _check_gov002(root: Path) -> tuple[object, list[str]]:
    """Broken fixture: a dangling C-x.y reference with no declaration."""
    module = _load_module("gov_self_test_check_rule_refs", SCRIPTS_DIR / "check_rule_refs.py")
    _init_repo(root)
    _write(root, "CONSTITUTION.md", "**C-1.1** Some rule text.\n")
    _write(root, "docs/note.md", "See C-99.9 for details (this id does not exist).\n")
    _add_all(root)
    return module, ["--repo-root", str(root)]


def _check_gov003(root: Path) -> tuple[object, list[str]]:
    """Broken fixture: 5 registry tokens restated verbatim outside their
    owner file, at/above the registry's threshold of 3."""
    module = _load_module("gov_self_test_check_sot_duplication", SCRIPTS_DIR / "check_sot_duplication.py")
    _init_repo(root)
    registry = {
        "registries": [
            {
                "id": "required-check-names",
                "owner_file": "CONSTITUTION.md",
                "owner_section": "9",
                "threshold": 3,
                "tokens": ["unit-backend", "unit-engine", "unit-frontend", "engine-bench", "pr-metadata"],
            }
        ]
    }
    registry_path = root / "scripts" / "sot-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    allowlist_path = root / "scripts" / "sot-allowlist.txt"
    allowlist_path.write_text("# empty\n", encoding="utf-8")
    _write(
        root,
        "CONTRIBUTING.md",
        "Required checks: unit-backend, unit-engine, unit-frontend, engine-bench, pr-metadata.\n",
    )
    _add_all(root)
    return module, [
        "--repo-root", str(root),
        "--registry", str(registry_path),
        "--allowlist", str(allowlist_path),
    ]


def _check_gov001(root: Path) -> tuple[object, list[str]]:
    """Broken fixture: a tracked path with no CODEOWNERS rule beyond the
    (absent) catch-all, on a CODEOWNERS file that declares no catch-all."""
    module = _load_module(
        "gov_self_test_check_codeowners_coverage", SCRIPTS_DIR / "check_codeowners_coverage.py"
    )
    _init_repo(root)
    _write(root, ".github/CODEOWNERS", "/docs/ @CandleViewer/docs\n")
    _write(root, "unowned_dir/file.txt", "orphaned, no rule matches this path\n")
    _add_all(root)
    return module, ["--repo-root", str(root)]


def _check_gov004a(root: Path) -> tuple[object, list[str]]:
    """Broken fixture: an issue form missing a required top-level key."""
    module = _load_module("gov_self_test_check_issue_forms", SCRIPTS_DIR / "check_issue_forms.py")
    _write(
        root,
        ".github/ISSUE_TEMPLATE/broken.yml",
        "description: missing the required 'name' and 'body' keys\n",
    )
    return module, ["--repo-root", str(root)]


def _check_gov004b(root: Path) -> tuple[object, list[str]]:
    """Broken fixture: malformed backlog JSON (must exit 2, not 1 — but any
    non-zero satisfies the canary's "still fails" contract)."""
    module = _load_module("gov_self_test_validate_backlog", SCRIPTS_DIR / "validate-backlog.py")
    schema_src = REPO_ROOT / "docs" / "plan" / "backlog" / "schema"
    schema_dest = root / "docs" / "plan" / "backlog" / "schema"
    schema_dest.mkdir(parents=True, exist_ok=True)
    for name in ("ticket.schema.json", "backlog-file.schema.json"):
        (schema_dest / name).write_text((schema_src / name).read_text(encoding="utf-8"), encoding="utf-8")
    _write(root, "docs/plan/backlog/E99.json", "{ this is not valid JSON ]\n")
    return module, ["--repo-root", str(root)]


def _check_gov005(root: Path) -> tuple[object, list[str]]:
    """Broken fixture: branch-protection.json requires a context with no
    matching workflow job and no CONSTITUTION §9 declaration."""
    module = _load_module(
        "gov_self_test_check_required_check_reconciliation",
        SCRIPTS_DIR / "check_required_check_reconciliation.py",
    )
    desired_state = {
        "required_status_checks": {"contexts": ["totally-invented-check"]},
        "x-pending-contexts": [],
    }
    desired_state_path = root / "branch-protection.json"
    desired_state_path.write_text(json.dumps(desired_state), encoding="utf-8")
    constitution_path = root / "CONSTITUTION.md"
    constitution_path.write_text(
        "| # | Check name | Description |\n|---|---|---|\n| 1 | `lint` | lint |\n",
        encoding="utf-8",
    )
    return module, [
        "--desired-state", str(desired_state_path),
        "--constitution", str(constitution_path),
        "--workflows-glob", str(root / "no-such-dir" / "*.yml"),
    ]


BROKEN_FIXTURE_BUILDERS = {
    "GOV-002": _check_gov002,
    "GOV-003": _check_gov003,
    "GOV-001": _check_gov001,
    "GOV-004a": _check_gov004a,
    "GOV-004b": _check_gov004b,
    "GOV-005": _check_gov005,
}


def check_manifest_matches_workflow(workflow_path: Path) -> list[str]:
    """The mutation-detection half of the canary: assert every entry in
    CHECKER_MANIFEST corresponds to a real `- name: ...` step in
    governance.yml, and that no checker step in the workflow is missing
    from the manifest. Catches "someone deleted a checker invocation from
    the workflow but nobody touched this file" and the reverse."""
    errors: list[str] = []
    try:
        text = workflow_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"{workflow_path} not found"]

    step_names = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().startswith("- name:")
    ]

    for entry in CHECKER_MANIFEST:
        needle = entry["step_name_contains"]
        if not any(needle in name for name in step_names):
            errors.append(
                f"manifest entry {entry['code']} expects a workflow step containing "
                f"'{needle}' but none was found in {workflow_path}"
            )

    known_needles = [e["step_name_contains"] for e in CHECKER_MANIFEST]
    checker_like_steps = [
        name
        for name in step_names
        if any(k in name for k in ("check", "Check", "GOV-0"))
        and "Install" not in name
        and "unit tests" not in name
        and "Relative-link" not in name
        and "canary self-test" not in name
        and "summary" not in name
        and "must pass" not in name
    ]
    for name in checker_like_steps:
        if not any(needle in name for needle in known_needles):
            errors.append(
                f"workflow step '{name}' looks like a governance checker but has no "
                "matching entry in scripts/gov_self_test.py's CHECKER_MANIFEST"
            )
    return errors


def run_self_test() -> int:
    failures: list[str] = []

    manifest_errors = check_manifest_matches_workflow(GOVERNANCE_WORKFLOW)
    for err in manifest_errors:
        print(f"gov-self-test manifest mismatch: {err}", file=sys.stderr)
    failures.extend(manifest_errors)

    for code, builder in BROKEN_FIXTURE_BUILDERS.items():
        with tempfile.TemporaryDirectory(prefix=f"gov-self-test-{code}-") as tmp:
            root = Path(tmp)
            try:
                module, argv = builder(root)
                exit_code = module.main(argv)
            except Exception as exc:  # noqa: BLE001 - a crash also proves "not silently 0"
                print(f"gov-self-test {code}: checker raised {exc!r} (acceptable, not 0)")
                continue
            if exit_code == 0:
                msg = f"gov-self-test {code}: checker exited 0 against a KNOWN-BROKEN fixture"
                print(msg, file=sys.stderr)
                failures.append(msg)
            else:
                print(f"gov-self-test {code}: correctly exited {exit_code} against broken fixture")

    if failures:
        print(f"gov-self-test: FAILED ({len(failures)} finding(s))", file=sys.stderr)
        return 1
    print("gov-self-test: all checkers correctly fail against known-broken fixtures")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        return run_self_test()
    except Exception as exc:  # noqa: BLE001
        print(f"gov-self-test internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
