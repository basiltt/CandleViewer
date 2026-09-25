#!/usr/bin/env python3
"""GOV-003: detect restatement of a C-16.5 owned single-source-of-truth list
outside its owner file (CONSTITUTION.md C-16.5).

Fingerprint-based (not fuzzy): each registry entry in scripts/sot-registry.json
defines an owner file/section, a threshold, and a small set of exact literal
tokens. If >= threshold of those tokens appear verbatim in a tracked file that
is not the owner file, that file is flagged as a duplication.

Exit codes: 0 clean, 1 violations found, 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

SCANNED_SUFFIXES = (".md", ".yaml", ".yml")


@dataclass(frozen=True)
class Registry:
    id: str
    owner_file: str
    owner_section: str
    threshold: int
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Violation:
    path: str
    registry_id: str
    owner_file: str
    owner_section: str
    matched_tokens: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        return (
            f"GOV-003 {self.path} restates {len(self.matched_tokens)} "
            f"tokens owned by {self.owner_file} section {self.owner_section} "
            f"(registry={self.registry_id}): {', '.join(self.matched_tokens)}"
        )


class InternalError(Exception):
    pass


def git_tracked_files(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def load_registries(registry_path: str) -> list[Registry]:
    with open(registry_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [
        Registry(
            id=r["id"],
            owner_file=r["owner_file"],
            owner_section=r["owner_section"],
            threshold=int(r["threshold"]),
            tokens=tuple(r["tokens"]),
        )
        for r in data["registries"]
    ]


def load_allowlist(allowlist_path: str) -> set[tuple[str, str, str]]:
    allowed: set[tuple[str, str, str]] = set()
    if not os.path.exists(allowlist_path):
        return allowed
    with open(allowlist_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split(":", 2)
            if len(parts) == 3:
                allowed.add((parts[0], parts[1], parts[2]))
    return allowed


def find_violations(
    repo_root: str,
    registries: list[Registry],
    allowlist: set[tuple[str, str, str]],
) -> list[Violation]:
    violations: list[Violation] = []
    for rel_path in git_tracked_files(repo_root):
        if not rel_path.endswith(SCANNED_SUFFIXES):
            continue
        abs_path = os.path.join(repo_root, rel_path)
        norm_path = rel_path.replace(os.sep, "/")
        try:
            with open(abs_path, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise InternalError(f"cannot read {rel_path}: {exc}") from exc

        for reg in registries:
            if norm_path == reg.owner_file:
                continue
            matched = tuple(
                tok
                for tok in reg.tokens
                if tok in text and (norm_path, reg.id, tok) not in allowlist
            )
            if len(matched) >= reg.threshold:
                violations.append(
                    Violation(
                        path=norm_path,
                        registry_id=reg.id,
                        owner_file=reg.owner_file,
                        owner_section=reg.owner_section,
                        matched_tokens=matched,
                    )
                )
    return violations


def emit(violations: list[Violation], as_json: bool, github_actions: bool) -> None:
    if as_json:
        payload = [
            {
                "code": "GOV-003",
                "path": v.path,
                "registry": v.registry_id,
                "owner_file": v.owner_file,
                "owner_section": v.owner_section,
                "matched_tokens": list(v.matched_tokens),
            }
            for v in violations
        ]
        print(json.dumps(payload, indent=2))
        return
    for v in violations:
        print(v.render())
        if github_actions:
            print(
                f"::error file={v.path}::GOV-003 duplicates list owned by "
                f"{v.owner_file} section {v.owner_section}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--registry",
        default=None,
        help="path to sot-registry.json (default: scripts/sot-registry.json)",
    )
    parser.add_argument(
        "--allowlist",
        default=None,
        help="path to sot-allowlist.txt (default: scripts/sot-allowlist.txt)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    scripts_dir = os.path.join(repo_root, "scripts")
    registry_path = args.registry or os.path.join(scripts_dir, "sot-registry.json")
    allowlist_path = args.allowlist or os.path.join(scripts_dir, "sot-allowlist.txt")

    try:
        registries = load_registries(registry_path)
        allowlist = load_allowlist(allowlist_path)
        violations = find_violations(repo_root, registries, allowlist)
    except (InternalError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"GOV-003 internal error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"GOV-003 internal error: git ls-files failed: {exc}", file=sys.stderr)
        return 2

    github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    emit(violations, args.json, github_actions)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
