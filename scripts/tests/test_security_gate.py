"""Unit tests for tools/ci/security_gate.py (E03-T07).

Exercises the five Gherkin acceptance scenarios plus the underlying
severity-normalisation / accepted-risk-expiry logic, over fixture SARIF/JSON
outputs synthesised in-test (no network, no real scanner invocation).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.security_gate import (
    AcceptedRisk,
    Finding,
    LicenseFinding,
    SecurityGateError,
    evaluate_findings,
    evaluate_licenses,
    load_accepted_risks,
    load_license_allowlist,
    main,
    parse_gitleaks,
    parse_npm_audit,
    parse_pip_audit,
    parse_sarif,
)


def _write_yaml(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "accepted-risks.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _write_json(tmp_path: Path, name: str, data: object) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# Scenario: A planted synthetic secret blocks the merge
# --------------------------------------------------------------------------


def test_gitleaks_finding_always_blocks_even_with_no_accepted_risks(tmp_path: Path) -> None:
    risks_path = _write_yaml(tmp_path, {"entries": []})
    risks = load_accepted_risks(risks_path)
    findings = [
        Finding(tool="gitleaks", finding_id="aws-key:app.py:10", severity="CRITICAL", detail="x")
    ]
    result = evaluate_findings(findings, risks, run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-001"


def test_gitleaks_finding_cannot_be_accepted_even_if_entry_present(tmp_path: Path) -> None:
    # load_accepted_risks rejects a gitleaks entry outright (CI-SEC-005) —
    # the register itself refuses to hold one.
    risks_path = _write_yaml(
        tmp_path,
        {
            "entries": [
                {
                    "id": "aws-key:app.py:10",
                    "tool": "gitleaks",
                    "severity": "CRITICAL",
                    "reason": "test",
                    "approver": "sec",
                    "expires": "2099-01-01",
                }
            ]
        },
    )
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


def test_parse_gitleaks_report_never_reprints_secret_value(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "gitleaks.json",
        [{"RuleID": "generic-api-key", "File": "app.py", "StartLine": 5, "Secret": "REDACTED"}],
    )
    findings = parse_gitleaks(report)
    assert len(findings) == 1
    assert findings[0].severity == "CRITICAL"
    assert "REDACTED" not in findings[0].detail
    assert "generic-api-key" in findings[0].finding_id


# --------------------------------------------------------------------------
# Scenario: A prohibited licence fails the build
# --------------------------------------------------------------------------


def test_prohibited_license_fails_naming_package_license_and_sr136(tmp_path: Path) -> None:
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        json.dumps(
            {
                "allowed": ["MIT"],
                "needs_approval": {"licenses": ["LGPL-3.0-only"]},
                "prohibited": {"licenses": ["AGPL-3.0-only"]},
                "dev_only_exceptions": {"packages": []},
                "unknown_license_policy": "fail",
            }
        ),
        encoding="utf-8",
    )
    allowlist = load_license_allowlist(allowlist_path)
    deps = [LicenseFinding(package="evil-dep", version="1.0.0", license="AGPL-3.0-only")]
    result = evaluate_licenses(deps, allowlist, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-002"
    assert any("evil-dep" in m and "AGPL-3.0-only" in m and "SR-136" in m for m in result.messages)


def test_unknown_license_fails_closed(tmp_path: Path) -> None:
    allowlist = {
        "allowed": ["MIT"],
        "needs_approval": {"licenses": []},
        "prohibited": {"licenses": []},
        "dev_only_exceptions": {"packages": []},
        "unknown_license_policy": "fail",
    }
    deps = [LicenseFinding(package="mystery-dep", version="2.0.0", license="Some-Weird-License")]
    result = evaluate_licenses(deps, allowlist, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-002"


def test_lgpl_needs_approval_blocks_without_accepted_risk() -> None:
    allowlist = {
        "allowed": [],
        "needs_approval": {"licenses": ["LGPL-3.0-only"]},
        "prohibited": {"licenses": []},
        "dev_only_exceptions": {"packages": []},
        "unknown_license_policy": "fail",
    }
    deps = [LicenseFinding(package="lgpl-dep", version="1.0.0", license="LGPL-3.0-only")]
    result = evaluate_licenses(deps, allowlist, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-003"


def test_lgpl_needs_approval_passes_with_unexpired_accepted_risk() -> None:
    allowlist = {
        "allowed": [],
        "needs_approval": {"licenses": ["LGPL-3.0-only"]},
        "prohibited": {"licenses": []},
        "dev_only_exceptions": {"packages": []},
        "unknown_license_policy": "fail",
    }
    deps = [LicenseFinding(package="lgpl-dep", version="1.0.0", license="LGPL-3.0-only")]
    risks = [
        AcceptedRisk(
            finding_id="license:lgpl-dep@1.0.0",
            tool="license-scan",
            severity="MEDIUM",
            reason="owner approved LGPL for this tool",
            approver="basiltt",
            expires=date(2099, 1, 1),
        )
    ]
    result = evaluate_licenses(deps, allowlist, risks=risks, run_date=date(2026, 1, 1))
    assert not result.blocked


# --------------------------------------------------------------------------
# Scenario: A High-severity dependency advisory blocks
# --------------------------------------------------------------------------


def test_pip_audit_high_severity_with_no_accepted_risk_blocks(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "pip-audit.json",
        {
            "dependencies": [
                {
                    "name": "vulnerable-pkg",
                    "version": "1.2.3",
                    "vulns": [
                        {
                            "id": "GHSA-xxxx",
                            "severity": "HIGH",
                            "description": "remote code execution",
                        }
                    ],
                }
            ]
        },
    )
    findings = parse_pip_audit(report)
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert result.code == "CI-SEC-001"


def test_pip_audit_unscored_advisory_treated_as_high_fail_closed(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "pip-audit.json",
        {"dependencies": [{"name": "p", "version": "1", "vulns": [{"id": "GHSA-yyyy"}]}]},
    )
    findings = parse_pip_audit(report)
    assert findings[0].severity == "HIGH"


def test_npm_audit_high_severity_blocks(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "npm-audit.json",
        {"vulnerabilities": {"left-pad": {"severity": "high", "via": [{"source": "GHSA-zzzz"}]}}},
    )
    findings = parse_npm_audit(report)
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked


def test_low_severity_finding_does_not_block(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "pip-audit.json",
        {
            "dependencies": [
                {"name": "p", "version": "1", "vulns": [{"id": "X", "severity": "LOW"}]}
            ]
        },
    )
    findings = parse_pip_audit(report)
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert not result.blocked


# --------------------------------------------------------------------------
# Scenario: An expired accepted risk re-blocks
# --------------------------------------------------------------------------


def test_expired_accepted_risk_reblocks_on_run_date(tmp_path: Path) -> None:
    risks_path = _write_yaml(
        tmp_path,
        {
            "entries": [
                {
                    "id": "GHSA-xxxx",
                    "tool": "pip-audit",
                    "severity": "HIGH",
                    "reason": "temporary — fix in progress",
                    "approver": "basiltt",
                    "expires": "2026-09-27",
                }
            ]
        },
    )
    risks = load_accepted_risks(risks_path)
    findings = [Finding(tool="pip-audit", finding_id="GHSA-xxxx", severity="HIGH", detail="x")]

    # On the expiry date itself the entry no longer protects (exclusive expiry).
    result = evaluate_findings(findings, risks, run_date=date(2026, 9, 27))
    assert result.blocked
    assert result.code == "CI-SEC-004"
    assert any("accepted risk expired" in m for m in result.messages)

    # The day before, it still protects.
    result_before = evaluate_findings(findings, risks, run_date=date(2026, 9, 26))
    assert not result_before.blocked


def test_unexpired_accepted_risk_does_not_block() -> None:
    risks = [
        AcceptedRisk(
            finding_id="GHSA-aaaa",
            tool="pip-audit",
            severity="HIGH",
            reason="vendor patch pending",
            approver="basiltt",
            expires=date(2099, 1, 1),
        )
    ]
    findings = [Finding(tool="pip-audit", finding_id="GHSA-aaaa", severity="HIGH", detail="x")]
    result = evaluate_findings(findings, risks, run_date=date(2026, 1, 1))
    assert not result.blocked


def test_accepted_risks_register_rejects_critical_severity_entry(tmp_path: Path) -> None:
    risks_path = _write_yaml(
        tmp_path,
        {
            "entries": [
                {
                    "id": "GHSA-crit",
                    "tool": "pip-audit",
                    "severity": "CRITICAL",
                    "reason": "test",
                    "approver": "basiltt",
                    "expires": "2099-01-01",
                }
            ]
        },
    )
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


# --------------------------------------------------------------------------
# Scenario: A Semgrep custom rule catches an unpinned action
# --------------------------------------------------------------------------


def _sarif_doc(rule_id: str, level: str = "error", severity: float | None = None) -> dict:
    props = {"security-severity": str(severity)} if severity is not None else {}
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "semgrep"}},
                "results": [
                    {
                        "ruleId": rule_id,
                        "level": level,
                        "message": {"text": f"{rule_id} violated"},
                        "properties": props,
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": ".github/workflows/pr.yml"},
                                    "region": {"startLine": 12},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_semgrep_cv_unpinned_action_rule_blocks_referencing_sr132(tmp_path: Path) -> None:
    report = _write_json(tmp_path, "semgrep.sarif", _sarif_doc("cv-unpinned-action"))
    findings = parse_sarif(report, "semgrep")
    assert findings[0].severity == "HIGH"
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert result.blocked
    assert any("cv-unpinned-action" in m for m in result.messages)


def test_sarif_security_severity_maps_to_critical_bucket(tmp_path: Path) -> None:
    report = _write_json(tmp_path, "codeql.sarif", _sarif_doc("py/sql-injection", severity=9.5))
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "CRITICAL"


def test_sarif_warning_level_maps_to_medium_and_does_not_block(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path, "semgrep.sarif", _sarif_doc("some-warning-rule", level="warning")
    )
    findings = parse_sarif(report, "semgrep")
    assert findings[0].severity == "MEDIUM"
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 1, 1))
    assert not result.blocked


# --------------------------------------------------------------------------
# Regression (ci/e03-codeql-job-fix): CodeQL puts `security-severity` and the
# default `level` on the rule descriptor, not the result. Reading the result
# alone downgraded every CodeQL High to MEDIUM, so PRs #1715/#1691 passed
# `security / codeql` while GitHub's CodeQL check reported a High alert.
# --------------------------------------------------------------------------


def _codeql_sarif_doc(
    rule_id: str,
    *,
    security_severity: str | None,
    rule_level: str = "error",
    result_level: str | None = None,
    via_extension: bool = False,
    use_rule_ref: bool = False,
) -> dict:
    rule = {
        "id": rule_id,
        "defaultConfiguration": {"level": rule_level},
        "properties": {"security-severity": security_severity}
        if security_severity is not None
        else {},
    }
    result: dict = {
        "ruleId": rule_id,
        "message": {"text": "This expression logs sensitive data as clear text."},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "infra/scripts/obs_security_checks.py"},
                    "region": {"startLine": 94},
                }
            }
        ],
    }
    if result_level is not None:
        result["level"] = result_level
    tool: dict = {"driver": {"name": "CodeQL", "rules": [] if via_extension else [rule]}}
    if via_extension:
        tool["extensions"] = [{"name": "codeql/python-queries", "rules": [rule]}]
        if use_rule_ref:
            result["rule"] = {"id": rule_id, "toolComponent": {"index": 1}, "index": 0}
    elif use_rule_ref:
        result["rule"] = {"id": rule_id, "index": 0}
    return {"version": "2.1.0", "runs": [{"tool": tool, "results": [result]}]}


def test_codeql_rule_level_security_severity_high_blocks(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc("py/clear-text-logging-sensitive-data", security_severity="7.5"),
    )
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "HIGH"
    assert (
        findings[0].finding_id
        == "py/clear-text-logging-sensitive-data:infra/scripts/obs_security_checks.py:94"
    )
    result = evaluate_findings(findings, risks=[], run_date=date(2026, 10, 3))
    assert result.blocked
    assert result.code == "CI-SEC-001"


def test_codeql_rule_in_extension_pack_resolved_by_rule_reference(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc(
            "js/tainted-format-string",
            security_severity="7.3",
            via_extension=True,
            use_rule_ref=True,
        ),
    )
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "HIGH"


def test_codeql_result_without_level_falls_back_to_rule_default_level(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc("py/some-non-security-rule", security_severity=None, rule_level="error"),
    )
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "HIGH"


def test_sarif_result_level_security_severity_still_takes_precedence(tmp_path: Path) -> None:
    doc = _codeql_sarif_doc("py/x", security_severity="9.5", result_level="warning")
    doc["runs"][0]["results"][0]["properties"] = {"security-severity": "3.0"}
    report = _write_json(tmp_path, "codeql.sarif", doc)
    findings = parse_sarif(report, "codeql")
    assert findings[0].severity == "LOW"


def test_codeql_high_with_matching_accepted_risk_does_not_block(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "codeql.sarif",
        _codeql_sarif_doc("py/clear-text-logging-sensitive-data", security_severity="7.5"),
    )
    findings = parse_sarif(report, "codeql")
    risk = AcceptedRisk(
        finding_id=findings[0].finding_id,
        tool="codeql",
        severity="HIGH",
        reason="test",
        approver="basiltt",
        expires=date(2027, 1, 1),
    )
    result = evaluate_findings(findings, risks=[risk], run_date=date(2026, 10, 3))
    assert not result.blocked


# --------------------------------------------------------------------------
# Scanner infrastructure failure (CI-SEC-005) never passes as clean
# --------------------------------------------------------------------------


def test_malformed_sarif_raises_ci_sec_005_not_treated_as_clean(tmp_path: Path) -> None:
    bad = tmp_path / "broken.sarif"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SecurityGateError) as exc_info:
        parse_sarif(bad, "codeql")
    assert exc_info.value.code == "CI-SEC-005"


def test_missing_accepted_risks_file_raises_ci_sec_005(tmp_path: Path) -> None:
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(tmp_path / "does-not-exist.yaml")
    assert exc_info.value.code == "CI-SEC-005"


def test_malformed_accepted_risks_entry_raises_ci_sec_005(tmp_path: Path) -> None:
    risks_path = _write_yaml(tmp_path, {"entries": [{"id": "x", "tool": "bandit"}]})
    with pytest.raises(SecurityGateError) as exc_info:
        load_accepted_risks(risks_path)
    assert exc_info.value.code == "CI-SEC-005"


# --------------------------------------------------------------------------
# CLI entrypoint
# --------------------------------------------------------------------------


def test_main_cli_blocks_on_gitleaks_finding(tmp_path: Path) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(
        tmp_path, "gitleaks.json", [{"RuleID": "generic-api-key", "File": "a.py", "StartLine": 1}]
    )
    rc = main(
        [
            "--tool",
            "gitleaks",
            "--report",
            str(report),
            "--accepted-risks",
            str(risks),
            "--run-date",
            "2026-01-01",
        ]
    )
    assert rc == 1


def test_main_cli_ok_on_clean_report(tmp_path: Path) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(tmp_path, "gitleaks.json", [])
    rc = main(
        [
            "--tool",
            "gitleaks",
            "--report",
            str(report),
            "--accepted-risks",
            str(risks),
            "--run-date",
            "2026-01-01",
        ]
    )
    assert rc == 0


def test_npm_audit_ghsa_url_becomes_finding_id(tmp_path: Path) -> None:
    report = _write_json(
        tmp_path,
        "npm-audit.json",
        {
            "vulnerabilities": {
                "braces": {
                    "severity": "high",
                    "via": [
                        {
                            "source": 1098094,
                            "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
                        }
                    ],
                }
            }
        },
    )
    assert parse_npm_audit(report)[0].finding_id == "GHSA-vfj7-8cjw-p6xm"


def test_repo_register_accepts_the_two_ghsa_exceptions_with_approver_and_expiry() -> None:
    register = Path(__file__).resolve().parents[2] / "security" / "accepted-risks.yaml"
    risks = {r.finding_id: r for r in load_accepted_risks(register)}
    ids = ["GHSA-ch52-4w7c-c8xp", "GHSA-vfj7-8cjw-p6xm"]
    findings = []
    for gid in ids:
        assert risks[gid].approver and risks[gid].expires
        findings.append(Finding(tool="npm-audit", finding_id=gid, severity="HIGH", package="x"))
    result = evaluate_findings(findings, list(risks.values()), run_date=date(2026, 10, 3))
    assert not result.blocked
    late = evaluate_findings(findings, list(risks.values()), run_date=date(2027, 1, 1))
    assert late.blocked


def test_gitleaks_block_message_cites_ir02(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    risks = _write_yaml(tmp_path, {"entries": []})
    report = _write_json(
        tmp_path, "gitleaks.json", [{"RuleID": "generic-api-key", "File": "a.py", "StartLine": 1}]
    )
    rc = main(["--tool", "gitleaks", "--report", str(report), "--accepted-risks", str(risks)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "IR-02" in err and "docs/ci-runbook.md" in err


def test_gitleaks_negative_proof_fake_secret_fixture_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A planted, clearly fake DUMMYKEY_ vector run through real gitleaks -> gate blocks."""
    import shutil
    import subprocess

    exe = shutil.which("gitleaks")
    if exe is None:
        pytest.skip("gitleaks binary not installed (CI runs the pinned container instead)")
    (tmp_path / "leak.txt").write_text("token = DUMMYKEY_ABCDEFGHIJKLMNOP\n", encoding="utf-8")
    (tmp_path / "cfg.toml").write_text(
        '[[rules]]\nid = "dummy-test-vector"\ndescription = "fake test vector"\n'
        "regex = '''DUMMYKEY_[A-Z]{16}'''\n",
        encoding="utf-8",
    )
    rep = tmp_path / "gl.json"
    subprocess.run(
        [exe, "detect", "--no-git", "--source", str(tmp_path), "--config", str(tmp_path / "cfg.toml"),
         "--redact", "-f", "json", "-r", str(rep)],
        check=False,
        capture_output=True,
    )
    risks = _write_yaml(tmp_path, {"entries": []})
    rc = main(["--tool", "gitleaks", "--report", str(rep), "--accepted-risks", str(risks)])
    assert rc == 1
    assert "IR-02" in capsys.readouterr().err
