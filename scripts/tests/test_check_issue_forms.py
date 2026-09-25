"""Schema-shape tests for scripts/check_issue_forms.py (GOV-004)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "check_issue_forms.py")


def _run(repo_root: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, "--repo-root", repo_root],
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_issue_forms_pass() -> None:
    result = _run(REPO_ROOT)
    assert result.returncode == 0, result.stderr


def test_missing_template_dir_is_internal_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(tmp)
        assert result.returncode == 2


def test_malformed_form_is_flagged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        template_dir = os.path.join(tmp, ".github", "ISSUE_TEMPLATE")
        os.makedirs(template_dir)
        with open(os.path.join(template_dir, "broken.yml"), "w", encoding="utf-8") as f:
            f.write(
                "name: Broken\n"
                "description: missing body\n"
            )
        result = _run(tmp)
        assert result.returncode == 1
        assert "body" in result.stderr


def test_dropdown_without_options_is_flagged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        template_dir = os.path.join(tmp, ".github", "ISSUE_TEMPLATE")
        os.makedirs(template_dir)
        with open(os.path.join(template_dir, "broken.yml"), "w", encoding="utf-8") as f:
            f.write(
                "name: Broken\n"
                "description: d\n"
                "body:\n"
                "  - type: dropdown\n"
                "    id: x\n"
                "    attributes:\n"
                "      label: X\n"
            )
        result = _run(tmp)
        assert result.returncode == 1
        assert "no options" in result.stderr
