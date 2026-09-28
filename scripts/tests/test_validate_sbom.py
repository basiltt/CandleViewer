"""Unit tests for tools/ci/validate_sbom.py (SR-133, CI-IMG-005)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.validate_sbom import main, validate

VALID_SBOM = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "components": [{"type": "library", "name": "fastapi", "version": "0.115.0"}],
}


def test_validate_accepts_well_formed_document() -> None:
    assert validate(VALID_SBOM) == []


def test_validate_rejects_missing_top_level_field() -> None:
    doc = {k: v for k, v in VALID_SBOM.items() if k != "components"}
    problems = validate(doc)
    assert any("missing required field" in p for p in problems)


def test_validate_rejects_wrong_bom_format() -> None:
    doc = {**VALID_SBOM, "bomFormat": "SPDX"}
    problems = validate(doc)
    assert any("bomFormat" in p for p in problems)


def test_validate_rejects_non_1x_spec_version() -> None:
    doc = {**VALID_SBOM, "specVersion": "2.0"}
    problems = validate(doc)
    assert any("specVersion" in p for p in problems)


def test_validate_rejects_component_missing_name() -> None:
    doc = {**VALID_SBOM, "components": [{"type": "library"}]}
    problems = validate(doc)
    assert any("name" in p for p in problems)


def test_main_exits_0_for_valid_sbom(tmp_path: Path) -> None:
    p = tmp_path / "sbom.json"
    p.write_text(json.dumps(VALID_SBOM), encoding="utf-8")
    assert main(["--sbom", str(p)]) == 0


def test_main_exits_1_for_invalid_sbom(tmp_path: Path) -> None:
    p = tmp_path / "sbom.json"
    p.write_text(json.dumps({"bomFormat": "CycloneDX"}), encoding="utf-8")
    assert main(["--sbom", str(p)]) == 1


def test_main_exits_2_for_missing_file(tmp_path: Path) -> None:
    assert main(["--sbom", str(tmp_path / "nope.json")]) == 2


def test_main_exits_2_for_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "sbom.json"
    p.write_text("{not json", encoding="utf-8")
    assert main(["--sbom", str(p)]) == 2
