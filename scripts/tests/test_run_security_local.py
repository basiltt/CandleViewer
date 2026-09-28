"""Unit tests for tools/ci/run_security_local.py (E02-X02).

Focus: the aggregation/reporting logic and the "unrunnable tool is SKIPPED,
never silently treated as clean" behaviour required by the ticket. Actual
scanner invocation is exercised via monkeypatched `shutil.which` /
`subprocess.run` -- no real semgrep/bandit/gitleaks/pnpm process is spawned,
so this suite needs no network and no installed scanners.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.run_security_local import (
    ToolResult,
    main,
    run_bandit,
    run_gitleaks,
    run_license_check,
    run_npm_audit,
    run_pip_audit,
    run_semgrep,
)


def test_run_semgrep_skips_when_binary_missing(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_semgrep(tmp_path)
    assert result.status == "SKIPPED"
    assert "semgrep" in result.name
    assert "not installed" in result.detail


def test_run_bandit_skips_when_binary_missing(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_bandit(tmp_path)
    assert result.status == "SKIPPED"
    assert "bandit" in result.detail


def test_run_pip_audit_skips_when_uv_missing(tmp_path: Path) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/bin/pip-audit" if name == "pip-audit" else None

    with patch("tools.ci.run_security_local._which", side_effect=fake_which):
        result = run_pip_audit(tmp_path)
    assert result.status == "SKIPPED"
    assert "uv" in result.detail


def test_run_npm_audit_skips_when_pnpm_missing(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_npm_audit(tmp_path)
    assert result.status == "SKIPPED"


def test_run_gitleaks_skips_when_no_binary_and_no_docker(tmp_path: Path) -> None:
    with patch("tools.ci.run_security_local._which", return_value=None):
        result = run_gitleaks(tmp_path)
    assert result.status == "SKIPPED"
    assert "not run: no docker" in result.detail


def test_run_license_check_skips_when_venv_missing(tmp_path: Path) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/bin/pnpm" if name == "pnpm" else None

    with patch("tools.ci.run_security_local._which", side_effect=fake_which):
        result = run_license_check(tmp_path)
    assert result.status == "SKIPPED"
    assert ".venv" in result.detail


def test_main_returns_zero_when_all_tools_skipped() -> None:
    skip = ToolResult("stub", "SKIPPED", "not installed")
    with patch("tools.ci.run_security_local.run_semgrep", return_value=skip), patch(
        "tools.ci.run_security_local.run_bandit", return_value=skip
    ), patch("tools.ci.run_security_local.run_pip_audit", return_value=skip), patch(
        "tools.ci.run_security_local.run_npm_audit", return_value=skip
    ), patch(
        "tools.ci.run_security_local.run_gitleaks", return_value=skip
    ), patch(
        "tools.ci.run_security_local.run_license_check", return_value=skip
    ):
        assert main([]) == 0


def test_main_returns_nonzero_when_any_tool_fails() -> None:
    ok = ToolResult("stub-ok", "PASS")
    bad = ToolResult("stub-bad", "FAIL", "CI-SEC-001: blocking finding")
    with patch("tools.ci.run_security_local.run_semgrep", return_value=bad), patch(
        "tools.ci.run_security_local.run_bandit", return_value=ok
    ), patch("tools.ci.run_security_local.run_pip_audit", return_value=ok), patch(
        "tools.ci.run_security_local.run_npm_audit", return_value=ok
    ), patch(
        "tools.ci.run_security_local.run_gitleaks", return_value=ok
    ), patch(
        "tools.ci.run_security_local.run_license_check", return_value=ok
    ):
        assert main([]) == 1
