"""Parser-contract tests (E01-T05 test plan): the rendered-body contract that E01-T07's
board-automation guards depend on.

- Each `.github/ISSUE_TEMPLATE/*.yml` form validates structurally (GOV-004).
- Rendering a form's `label` values as `### <Label>` headings must be parsable, including
  the "_No response_" placeholder GitHub substitutes for an unanswered optional field.
"""

from __future__ import annotations

import os
import re

import pytest
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATE_DIR = os.path.join(REPO_ROOT, ".github", "ISSUE_TEMPLATE")


def _load_form(name: str) -> dict:
    with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _field_labels(doc: dict) -> list[str]:
    return [
        item["attributes"]["label"]
        for item in doc["body"]
        if item.get("type") != "markdown"
    ]


def _render_body(doc: dict, answers: dict[str, str]) -> str:
    """Emulate GitHub's issue-forms rendering: each non-markdown field becomes
    `### <label>` followed by the answer, or the literal `_No response_` placeholder
    when the field was optional and left blank."""
    lines: list[str] = []
    for item in doc["body"]:
        if item.get("type") == "markdown":
            continue
        label = item["attributes"]["label"]
        field_id = item["id"]
        answer = answers.get(field_id, "_No response_")
        lines.append(f"### {label}")
        lines.append("")
        lines.append(answer)
        lines.append("")
    return "\n".join(lines)


def _find_section(body: str, heading: str) -> str | None:
    """Locate a `### <heading>` section and return its content, or None if the heading
    is absent. Mirrors the absent-vs-empty contract in docs/design/E01/E01-D01.md §5."""
    pattern = re.compile(
        rf"^### {re.escape(heading)}\n\n(.*?)(?=\n### |\Z)", re.DOTALL | re.MULTILINE
    )
    m = pattern.search(body)
    if m is None:
        return None
    return m.group(1).strip()


ALL_FORMS = ["epic.yml", "story.yml", "task.yml", "spike.yml", "bug_report.yml", "chore.yml"]


@pytest.mark.parametrize("form_name", ALL_FORMS)
def test_form_labels_render_as_stable_headings(form_name: str) -> None:
    doc = _load_form(form_name)
    labels = _field_labels(doc)
    assert labels, f"{form_name} has no answerable fields"
    body = _render_body(doc, {})
    for label in labels:
        assert _find_section(body, label) is not None, (
            f"{form_name}: heading '### {label}' not found in rendered body"
        )


@pytest.mark.parametrize("form_name", ALL_FORMS)
def test_unanswered_optional_field_renders_no_response(form_name: str) -> None:
    doc = _load_form(form_name)
    optional_ids = [
        item["id"]
        for item in doc["body"]
        if item.get("type") != "markdown"
        and not item.get("validations", {}).get("required", False)
    ]
    if not optional_ids:
        pytest.skip(f"{form_name} has no optional fields")
    body = _render_body(doc, {})
    label_by_id = {
        item["id"]: item["attributes"]["label"]
        for item in doc["body"]
        if item.get("type") != "markdown"
    }
    for field_id in optional_ids:
        section = _find_section(body, label_by_id[field_id])
        assert section == "_No response_"


def test_missing_heading_is_distinguishable_from_empty_heading() -> None:
    body_missing = "### Acceptance criteria\n\nfilled in\n"
    body_present_empty = "### Acceptance criteria\n\n\n### Test plan\n\nfilled in\n"
    assert _find_section(body_missing, "Test plan") is None
    assert _find_section(body_present_empty, "Acceptance criteria") == ""


def test_na_literal_token_is_case_sensitive_per_e01_d01_section5() -> None:
    # docs/design/E01/E01-D01.md §5: the parser treats "N/A" case-sensitively.
    body = "### Test plan\n\nN/A\n"
    section = _find_section(body, "Test plan")
    assert section == "N/A"
    assert section != "n/a"
    assert section != "NA"
