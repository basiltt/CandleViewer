"""E47-K01: the checked-in example findings file validates against the finding-record schema."""

import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

A11Y = Path(__file__).resolve().parents[2] / "docs" / "plan" / "a11y"


def _load(name: str) -> dict:
    return json.loads((A11Y / name).read_text(encoding="utf-8"))


def test_example_findings_file_validates_against_schema() -> None:
    jsonschema.validate(_load("findings.example.json"), _load("finding-record.schema.json"))


def test_finding_with_invalid_wcag_level_is_rejected() -> None:
    doc = copy.deepcopy(_load("findings.example.json"))
    doc["findings"][0]["level"] = "AAA"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, _load("finding-record.schema.json"))


def test_finding_missing_required_field_is_rejected() -> None:
    doc = copy.deepcopy(_load("findings.example.json"))
    del doc["findings"][0]["owningTicket"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, _load("finding-record.schema.json"))
