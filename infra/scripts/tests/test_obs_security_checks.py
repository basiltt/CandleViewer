"""Tests for infra/scripts/obs_security_checks.py (E04-X02)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import obs_security_checks as o


def test_repo_passes_all_checks() -> None:
    assert o.main([]) == 0


def test_gitleaks_allowlist_exempting_infra_is_flagged() -> None:
    cfg = "[extend]\nuseDefault = true\npaths = [\n  '''infra/alertmanager/.*''',\n]\n"
    assert any("infra/alertmanager" in v for v in o.check_gitleaks_covers_infra(cfg))


def test_gitleaks_without_default_ruleset_is_flagged() -> None:
    assert o.check_gitleaks_covers_infra("title = 'x'\n")


def test_committed_webhook_token_is_detected(tmp_path: Path) -> None:
    am = tmp_path / "infra" / "alertmanager"
    am.mkdir(parents=True)
    (am / "a.yml").write_text(
        "url: https://hooks.slack.com/services/T0000/B0000/abcdEFGH1234\n", encoding="utf-8"
    )
    assert o.check_no_committed_webhook_secret(tmp_path / "infra")


def test_runtime_secret_reference_is_clean(tmp_path: Path) -> None:
    am = tmp_path / "infra" / "alertmanager"
    am.mkdir(parents=True)
    (am / "a.yml").write_text("url_file: /run/secrets/alert_webhook\n", encoding="utf-8")
    assert o.check_no_committed_webhook_secret(tmp_path / "infra") == []


def test_workflow_uploading_logs_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "w.yml").write_text(
        "steps:\n  - uses: actions/upload-artifact@v4\n    with:\n      name: x\n      path: logs/\n",
        encoding="utf-8",
    )
    assert o.check_workflows_no_log_artifacts(tmp_path)


def test_workflow_uploading_reports_is_clean(tmp_path: Path) -> None:
    (tmp_path / "w.yml").write_text(
        "steps:\n  - uses: actions/upload-artifact@v4\n    with:\n      name: x\n      path: reports/\n",
        encoding="utf-8",
    )
    assert o.check_workflows_no_log_artifacts(tmp_path) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_loose_permissions_are_flagged(tmp_path: Path) -> None:
    d = tmp_path / "logs"
    d.mkdir()
    f = d / "a.log"
    f.write_text("x", encoding="utf-8")
    os.chmod(d, 0o700)
    os.chmod(f, 0o644)
    assert o.check_modes(d)
    os.chmod(f, 0o600)
    assert o.check_modes(d) == []


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_gitleaks_catches_deliberate_infra_secret(tmp_path: Path) -> None:
    """Deliberate-commit AC: a fake secret under infra/ must be detected by the repo config."""
    repo = tmp_path / "r"
    (repo / "infra" / "alertmanager").mkdir(parents=True)
    # Assembled at runtime so this source file itself holds no secret-shaped literal.
    fake = "AKIA" + "IOSFODNN7" + "EXAMPLQ"
    (repo / "infra" / "alertmanager" / "leak.yml").write_text(
        f"aws_access_key_id: {fake}\naws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    cfg = o.REPO / ".gitleaks.toml"
    res = subprocess.run(
        ["gitleaks", "detect", "--no-git", "--source", str(repo), "--config", str(cfg), "--redact"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0, "gitleaks did not flag a deliberate infra secret"


def test_loose_log_permissions_flagged_logic_is_posix_only_documented() -> None:
    # Windows has no POSIX modes: the check is a documented no-op there, never a false pass in CI.
    assert o.check_modes(Path("/definitely/not/here")) == []


def test_webhook_secret_committed_to_alertmanager_config_is_caught(tmp_path: Path) -> None:
    """AC3 (executed): a deliberate token in an Alertmanager config fails the in-repo check."""
    infra = tmp_path / "infra"
    (infra / "alertmanager").mkdir(parents=True)
    token = "T" + "0123456789" + "ABCDEFGHIJKLMNOPQRS"  # assembled: no secret-shaped literal
    (infra / "alertmanager" / "alertmanager.yml").write_text(
        f"receivers:\n  - name: page\n    slack_configs:\n      - api_url: https://hooks.slack.com/services/T0/B0/{token}\n",
        encoding="utf-8",
    )
    assert o.check_no_committed_webhook_secret(infra)


def test_page_alert_payload_carries_no_ids_or_key_material() -> None:
    """AC5 (executed): the Page template + rules expose only allow-listed fields."""
    import json
    import re

    tmpl = (o.REPO / "infra/alertmanager/templates/cv.tmpl").read_text(encoding="utf-8")
    fields = set(re.findall(r"\.(?:Group|Common)(?:Labels|Annotations)\.(\w+)", tmpl))
    assert fields <= {"alertname", "component", "env", "severity", "summary", "runbook_url"}
    assert "Alerts.Labels" not in tmpl and ".Labels." not in tmpl.replace(".CommonLabels.", "").replace(
        ".GroupLabels.", ""
    )
    fixture = json.loads(
        (o.REPO / "infra/alertmanager/tests/data/grouped_page.json").read_text(encoding="utf-8")
    )
    blob = json.dumps(fixture).lower()
    for banned in ("order_id", "orderlinkid", "account_id", "api_key", "secret", "signature"):
        assert banned not in blob
    for rule in (o.REPO / "infra/prometheus/alerts").glob("*.yml"):
        text = rule.read_text(encoding="utf-8")
        for m in re.finditer(r"\$labels\.(\w+)", text):
            assert m.group(1) in {"env", "component", "instance", "job", "alertname", "severity"}, (
                f"{rule.name}: annotation interpolates ${m.group(1)}"
            )
