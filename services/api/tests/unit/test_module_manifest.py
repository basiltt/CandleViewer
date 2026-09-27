"""Module-manifest test (E02-T05 acceptance criterion 1).

Given the module tree, when a reviewer compares it to `CONSTITUTION.md`
Sec.3, all 24 module paths must exist with the exact names M1..M24 map to,
asserted programmatically against `tests/module_manifest.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_SERVICES_API_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _SERVICES_API_ROOT / "tests" / "module_manifest.json"
_MANIFEST = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", _MANIFEST["modules"], ids=lambda e: e["id"])
def test_module_path_exists(entry: dict[str, str]) -> None:
    target = _SERVICES_API_ROOT / entry["path"]
    assert target.exists(), f"{entry['id']} ({entry['name']}) missing at {entry['path']}"


def test_manifest_covers_all_24_constitution_modules() -> None:
    # M23 is split into two paths (api, ws) in CONSTITUTION.md's own table,
    # so the manifest has 25 entries for 24 modules.
    ids = {entry["id"] for entry in _MANIFEST["modules"]}
    assert len(ids) == 25


@pytest.mark.parametrize(
    "package_dir",
    [
        entry["path"]
        for entry in _MANIFEST["modules"]
        if entry["id"] not in {"M1"}
    ],
)
def test_module_has_public_surface_files(package_dir: str) -> None:
    root = _SERVICES_API_ROOT / package_dir
    for filename in ("__init__.py", "service.py", "models.py", "errors.py"):
        assert (root / filename).exists(), f"{package_dir} missing {filename}"
