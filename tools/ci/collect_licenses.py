#!/usr/bin/env python3
"""E03-T07: normalise `pip-licenses` (Python) and `license-checker` (npm)
output into one JSON array `[{package, version, license}, ...]` for
`tools/ci/security_gate.py --tool license-scan` to evaluate against
`tools/ci/licenses-allowlist.json`.

Usage:
    collect_licenses.py --pip-licenses pip.json --license-checker npm.json \
        --out combined.json

Either source may be omitted (e.g. a PR touching only `apps/web` has no
Python dependency change) — an omitted source contributes zero entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"CI-SEC-005: unreadable/invalid JSON at {path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def from_pip_licenses(doc: object) -> list[dict[str, str]]:
    """`pip-licenses --format=json` rows: {"Name", "Version", "License"}."""
    if not isinstance(doc, list):
        raise SystemExit("CI-SEC-005: pip-licenses output must be a JSON array")
    return [
        {
            "package": row["Name"],
            "version": row.get("Version", ""),
            "license": row.get("License", "UNKNOWN"),
        }
        for row in doc
    ]


def from_license_checker(doc: object) -> list[dict[str, str]]:
    """`license-checker --json` rows keyed `name@version`: {"licenses": ...}."""
    if not isinstance(doc, dict):
        raise SystemExit("CI-SEC-005: license-checker output must be a JSON object")
    out: list[dict[str, str]] = []
    for key, meta in doc.items():
        if "@" in key:
            name, _, version = key.rpartition("@")
        else:
            name, version = key, ""
        licenses = meta.get("licenses", "UNKNOWN")
        # license-checker may report a list ("MIT OR Apache-2.0"-style) or a
        # single string; normalise to the first token conservatively — a
        # dual-license package only needs one licence in the allowlist.
        license_ = licenses[0] if isinstance(licenses, list) else str(licenses)
        out.append({"package": name, "version": version, "license": license_})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pip-licenses", type=Path, default=None)
    parser.add_argument("--license-checker", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    combined: list[dict[str, str]] = []
    if args.pip_licenses is not None:
        combined.extend(from_pip_licenses(_load_json(args.pip_licenses)))
    if args.license_checker is not None:
        combined.extend(from_license_checker(_load_json(args.license_checker)))

    args.out.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"collect_licenses: wrote {len(combined)} entries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
