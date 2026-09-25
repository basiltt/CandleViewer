#!/usr/bin/env python3
"""GOV-004: structural validator for .github/ISSUE_TEMPLATE/*.yml issue forms.

Validates each form against the subset of GitHub's issue-forms schema this repo relies
on (required top-level keys, allowed `type` values per body item, required `id`/`label`
on every field, dropdown `options` non-empty). Not a full JSON-Schema replacement for
GitHub's schema, but catches the silent-breakage class named in E01-T05's test plan:
a malformed form silently disappearing from the "New issue" chooser.

Exit codes: 0 clean, 1 violations found, 2 internal error (e.g. missing directory).
Stdlib + PyYAML only.
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

ALLOWED_BODY_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
REQUIRED_TOP_KEYS = {"name", "description", "body"}


class ValidationError(Exception):
    pass


def validate_form(path: str, doc: dict) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_TOP_KEYS - doc.keys()
    if missing:
        errors.append(f"{path}: missing top-level key(s) {sorted(missing)}")
    body = doc.get("body")
    if not isinstance(body, list) or not body:
        errors.append(f"{path}: 'body' must be a non-empty list")
        return errors
    for i, item in enumerate(body):
        if not isinstance(item, dict):
            errors.append(f"{path}: body[{i}] is not a mapping")
            continue
        item_type = item.get("type")
        if item_type not in ALLOWED_BODY_TYPES:
            errors.append(f"{path}: body[{i}] has disallowed type {item_type!r}")
            continue
        if item_type == "markdown":
            continue
        if "id" not in item:
            errors.append(f"{path}: body[{i}] (type={item_type}) missing 'id'")
        attrs = item.get("attributes", {})
        if not isinstance(attrs, dict) or "label" not in attrs:
            errors.append(f"{path}: body[{i}] (id={item.get('id')}) missing attributes.label")
        if item_type == "dropdown":
            options = attrs.get("options") if isinstance(attrs, dict) else None
            if not options:
                errors.append(f"{path}: body[{i}] (id={item.get('id')}) dropdown has no options")
    return errors


def validate_config(path: str, doc: dict) -> list[str]:
    errors: list[str] = []
    if "blank_issues_enabled" not in doc:
        errors.append(f"{path}: missing 'blank_issues_enabled'")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=os.getcwd())
    args = parser.parse_args(argv)

    template_dir = os.path.join(args.repo_root, ".github", "ISSUE_TEMPLATE")
    if not os.path.isdir(template_dir):
        print(f"error: {template_dir} not found", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    for name in sorted(os.listdir(template_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(template_dir, name)
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        if name == "config.yml":
            all_errors.extend(validate_config(path, doc))
        else:
            all_errors.extend(validate_form(path, doc))

    if all_errors:
        for e in all_errors:
            print(e, file=sys.stderr)
        return 1
    print("OK: all issue forms structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
