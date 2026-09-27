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


# Map the licence *names* tooling emits (PyPI trove classifiers, free-text
# METADATA `License:` fields, npm `licenses`) onto SPDX identifiers, which is
# what tools/ci/licenses-allowlist.json is written in. Unrecognised names pass
# through unchanged so the gate's unknown-licence policy still applies.
_SPDX_ALIASES: dict[str, str] = {
    "mit license": "MIT",
    "mit": "MIT",
    "bsd license": "BSD-3-Clause",
    "bsd": "BSD-3-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "modified bsd license": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd 2-clause license": "BSD-2-Clause",
    "bsd 3-clause license": "BSD-3-Clause",
    "bsd 2-clause": "BSD-2-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "the mit license": "MIT",
    "mit-0": "MIT-0",
    "apache 2": "Apache-2.0",
    "simplified bsd license": "BSD-2-Clause",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "isc license (iscl)": "ISC",
    "isc license": "ISC",
    "isc": "ISC",
    "python software foundation license": "PSF-2.0",
    "psf-2.0": "PSF-2.0",
    "psfl": "PSF-2.0",
    "psf": "PSF-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "mpl-2.0": "MPL-2.0",
    "the unlicense (unlicense)": "Unlicense",
    "unlicense": "Unlicense",
    "cc0 1.0 universal (cc0 1.0) public domain dedication": "CC0-1.0",
    "cc0-1.0": "CC0-1.0",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.1-or-later",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
    "gnu general public license v3 (gplv3)": "GPL-3.0-only",
    "gnu general public license v2 (gplv2)": "GPL-2.0-only",
    "gnu affero general public license v3": "AGPL-3.0-only",
}


# Permissive licences whose conjunction is no stricter than either alone.
_CONJUNCTION_SAFE = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "0BSD",
        "Zlib",
        "PSF-2.0",
        "PSF",
        "Unlicense",
        "CC0-1.0",
    }
)


def normalise_license(raw: str) -> str:
    """Return an SPDX id for a licence name where one is known.

    pip-licenses joins multiple classifiers with "; " — every part is mapped and
    the first *allowlist-friendly* (non-GPL) id wins, mirroring the npm rule that
    a dual-licensed package needs only one acceptable licence.
    """
    # "A AND B" (conjunctive SPDX) means the package is under *both*; every part
    # must be acceptable, so keep the conjunction intact for the gate when any
    # part is outside the plain allow-list — otherwise collapse to the parts.
    if " AND " in raw:
        parts_and = [
            _SPDX_ALIASES.get(p.strip().lower(), p.strip()) for p in raw.split(" AND ")
        ]
        return (
            parts_and[0]
            if all(p in _CONJUNCTION_SAFE for p in parts_and)
            else " AND ".join(parts_and)
        )
    parts = [p.strip() for p in raw.replace(" OR ", ";").split(";") if p.strip()]
    mapped = [_SPDX_ALIASES.get(p.lower(), p) for p in parts] or ["UNKNOWN"]
    for m in mapped:
        if not m.upper().startswith(("GPL", "AGPL", "LGPL")):
            return m
    return mapped[0]


def from_pip_licenses(doc: object) -> list[dict[str, str]]:
    """`pip-licenses --format=json` rows: {"Name", "Version", "License"}."""
    if not isinstance(doc, list):
        raise SystemExit("CI-SEC-005: pip-licenses output must be a JSON array")
    return [
        {
            "package": row["Name"],
            "version": row.get("Version", ""),
            "license": normalise_license(_pip_license(row)),
        }
        for row in doc
    ]


def _pip_license(row: dict[str, object]) -> str:
    """Prefer PEP 639 `License-Expression` (pip-licenses >= 5 emits it as
    "License-Expression"); fall back to classifier/METADATA `License`; treat the
    literal "UNKNOWN" placeholder as absent so the classifier column is used."""
    for key in ("License-Expression", "License"):
        val = str(row.get(key, "") or "").strip()
        if val and val.upper() != "UNKNOWN":
            return val
    return "UNKNOWN"


def from_installed_python_env() -> list[dict[str, str]]:
    """Read licences from the *current* interpreter's installed distributions via
    importlib.metadata: PEP 639 ``License-Expression`` first, then the free-text
    ``License`` field, then trove classifiers. pip-licenses 5.x ignores
    License-Expression, so urllib3/uvicorn/websockets reported UNKNOWN. Run with
    the project venv's interpreter (``uv run`` / ``services/api/.venv/bin/python``)."""
    import importlib.metadata as md

    out: list[dict[str, str]] = []
    for dist in md.distributions():
        meta = dist.metadata
        name = meta.get("Name") or dist.name
        if str(name).lower().startswith("candleviewer"):
            continue  # first-party workspace package (UNLICENSED/proprietary), not a dependency
        expr = (meta.get("License-Expression") or "").strip()
        lic = expr or (meta.get("License") or "").strip()
        # A "License" field longer than ~80 chars is pasted licence text, not a name.
        if not lic or lic.upper() == "UNKNOWN" or len(lic) > 80:
            classifiers = [
                c
                for c in (meta.get_all("Classifier") or [])
                if c.startswith("License ::")
            ]
            lic = (
                "; ".join(c.rsplit("::", 1)[-1].strip() for c in classifiers)
                or "UNKNOWN"
            )
        out.append(
            {
                "package": name,
                "version": dist.version,
                "license": normalise_license(lic),
            }
        )
    return out


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
        out.append(
            {
                "package": name,
                "version": version,
                "license": normalise_license(license_),
            }
        )
    return out


def from_pnpm_licenses(doc: object) -> list[dict[str, str]]:
    """`pnpm licenses list --json` shape: {"<licence>": [{"name", "versions": [...], ...}]}."""
    if not isinstance(doc, dict):
        raise SystemExit("CI-SEC-005: pnpm licenses output must be a JSON object")
    out: list[dict[str, str]] = []
    for lic, pkgs in doc.items():
        for meta in pkgs or []:
            for ver in meta.get("versions") or [""]:
                out.append(
                    {
                        "package": meta.get("name", "?"),
                        "version": ver,
                        "license": normalise_license(str(lic)),
                    }
                )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pip-licenses", type=Path, default=None)
    parser.add_argument("--license-checker", type=Path, default=None)
    parser.add_argument("--pnpm-licenses", type=Path, default=None)
    parser.add_argument(
        "--python-env",
        action="store_true",
        help="collect from the running interpreter's installed distributions (importlib.metadata)",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    combined: list[dict[str, str]] = []
    if args.python_env:
        combined.extend(from_installed_python_env())
    if args.pip_licenses is not None:
        combined.extend(from_pip_licenses(_load_json(args.pip_licenses)))
    if args.license_checker is not None:
        combined.extend(from_license_checker(_load_json(args.license_checker)))
    if args.pnpm_licenses is not None:
        combined.extend(from_pnpm_licenses(_load_json(args.pnpm_licenses)))

    args.out.write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"collect_licenses: wrote {len(combined)} entries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
