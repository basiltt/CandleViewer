"""Unit tests for tools/ci/collect_licenses.py (E03-T07)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.collect_licenses import from_license_checker, from_pip_licenses, main


def test_from_pip_licenses_normalises_rows() -> None:
    rows = [{"Name": "requests", "Version": "2.31.0", "License": "Apache-2.0"}]
    out = from_pip_licenses(rows)
    assert out == [{"package": "requests", "version": "2.31.0", "license": "Apache-2.0"}]


def test_from_license_checker_normalises_scoped_package_at_version() -> None:
    doc = {"@candleviewer/ui@1.0.0": {"licenses": "MIT"}}
    out = from_license_checker(doc)
    assert out == [{"package": "@candleviewer/ui", "version": "1.0.0", "license": "MIT"}]


def test_from_license_checker_handles_list_of_licenses() -> None:
    doc = {"dual-lib@2.0.0": {"licenses": ["MIT", "Apache-2.0"]}}
    out = from_license_checker(doc)
    assert out[0]["license"] == "MIT"


def test_main_combines_both_sources(tmp_path: Path) -> None:
    pip_path = tmp_path / "pip.json"
    pip_path.write_text(
        json.dumps([{"Name": "black", "Version": "24.0", "License": "MIT"}]), encoding="utf-8"
    )
    npm_path = tmp_path / "npm.json"
    npm_path.write_text(json.dumps({"left-pad@1.0.0": {"licenses": "WTFPL"}}), encoding="utf-8")
    out_path = tmp_path / "combined.json"

    rc = main(
        [
            "--pip-licenses",
            str(pip_path),
            "--license-checker",
            str(npm_path),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    combined = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(combined) == 2
    assert {"package": "black", "version": "24.0", "license": "MIT"} in combined


def test_main_with_only_pip_source(tmp_path: Path) -> None:
    pip_path = tmp_path / "pip.json"
    pip_path.write_text(json.dumps([]), encoding="utf-8")
    out_path = tmp_path / "combined.json"
    rc = main(["--pip-licenses", str(pip_path), "--out", str(out_path)])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == []
