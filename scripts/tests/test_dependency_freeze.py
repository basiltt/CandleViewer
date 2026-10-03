"""E43-T05: freeze invariants (SR-130, SR-134, SR-156)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_accepted_risks_are_time_boxed_and_never_critical() -> None:
    doc = yaml.safe_load((ROOT / "security/accepted-risks.yaml").read_text(encoding="utf-8"))
    for e in doc["entries"]:
        assert e["severity"] != "CRITICAL", e["id"]
        exp = (
            e["expires"]
            if isinstance(e["expires"], dt.date)
            else dt.date.fromisoformat(e["expires"])
        )
        assert exp <= dt.date(2027, 3, 25), e["id"]
        assert e["approver"] == "basiltt"


def test_tar_override_pinned_past_critical_advisory() -> None:
    assert 'tar: ">=7.5.21"' in (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")


def test_vitest_not_on_vulnerable_major() -> None:
    for pkg in list(ROOT.glob("apps/*/package.json")) + list(ROOT.glob("packages/*/package.json")):
        dev = json.loads(pkg.read_text(encoding="utf-8")).get("devDependencies", {})
        for name in ("vitest", "@vitest/coverage-v8"):
            if name in dev:
                assert dev[name] == "^3.2.6", (pkg, name)


def test_dependabot_sla_labels_present() -> None:
    text = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert "sla/48h" in text and "sla/7d" in text


def test_unpinned_action_rule_and_fixture_exist() -> None:
    assert (ROOT / ".semgrep/cv-unpinned-action.yml").is_file()
    assert (ROOT / ".semgrep/tests/cv-unpinned-action.yml").is_file()


def test_known_vulnerable_dependency_without_exception_fails_gate() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.security_gate import Finding, evaluate_findings, load_accepted_risks

    risks = load_accepted_risks(ROOT / "security/accepted-risks.yaml")
    f = Finding(
        tool="pip-audit",
        finding_id="GHSA-fixture-0000",
        severity="HIGH",
        package="fixture-vuln",
        detail="known vulnerable fixture",
    )
    result = evaluate_findings([f], risks, run_date=dt.date(2026, 10, 3))
    assert result.blocked and result.code == "CI-SEC-001"


def test_prohibited_licence_fails_gate_with_real_allowlist() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.security_gate import (
        LicenseFinding,
        evaluate_licenses,
        load_license_allowlist,
    )

    allow = load_license_allowlist(ROOT / "tools/ci/licenses-allowlist.json")
    prohibited = allow["prohibited"]["licenses"][0]
    dep = LicenseFinding(package="fixture-prohibited", version="1.0.0", license=prohibited)
    result = evaluate_licenses([dep], allow, risks=[], run_date=dt.date(2026, 10, 3))
    assert result.blocked and result.code == "CI-SEC-002"


def test_prohibited_licence_message_names_package_and_licence() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.security_gate import (
        LicenseFinding,
        evaluate_licenses,
        load_license_allowlist,
    )

    allow = load_license_allowlist(ROOT / "tools/ci/licenses-allowlist.json")
    prohibited = allow["prohibited"]["licenses"][0]
    dep = LicenseFinding(package="fixture-prohibited", version="1.0.0", license=prohibited)
    result = evaluate_licenses([dep], allow, risks=[], run_date=dt.date(2026, 10, 3))
    text = "\n".join(result.messages)
    assert "fixture-prohibited" in text and prohibited in text


def test_api_image_is_digest_pinned_and_non_root() -> None:
    """Static non-root check (the runtime probe is tools/ci/check_image_non_root.py, needs docker)."""
    lines = (ROOT / "infra/images/Dockerfile.api").read_text(encoding="utf-8").splitlines()
    froms = [x for x in lines if x.strip().upper().startswith("FROM ")]
    assert froms and all("@sha256:" in x for x in froms)
    users = [x.split()[1] for x in lines if x.strip().upper().startswith("USER ")]
    assert users and users[-1].split(":")[0] not in ("0", "root")


def test_frozen_lockfiles_are_integrity_pinned() -> None:
    """Frozen installs are byte-identical only if every entry carries a hash."""
    import re

    pnpm = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert pnpm.count("resolution: {integrity: sha512-") > 100
    assert not re.search(r"resolution: \{tarball:", pnpm)
    uv = (ROOT / "services/api/uv.lock").read_text(encoding="utf-8")
    assert uv.count('hash = "sha256:') > 50


def test_freeze_manifest_lock_hashes_match_committed_lockfiles() -> None:
    import hashlib

    lines = (ROOT / "security/freeze-manifest.sha256").read_text(encoding="utf-8").splitlines()
    got = {name: digest for digest, name in (ln.split("  ", 1) for ln in lines)}
    assert set(got) == {"pnpm-lock.yaml", "uv.lock", "pnpm-graph", "uv-graph"}
    for name, path in (("pnpm-lock.yaml", "pnpm-lock.yaml"), ("uv.lock", "services/api/uv.lock")):
        data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == got[name], name


def test_freeze_manifest_pnpm_graph_normalisation_drops_paths() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.check_freeze_manifest import normalise_pnpm_graph

    a = normalise_pnpm_graph([{"name": "x", "path": "C:/a", "dependencies": {"y": {"path": "/b"}}}])
    b = normalise_pnpm_graph(
        [{"name": "x", "path": "/home/c", "dependencies": {"y": {"path": "/d"}}}]
    )
    assert a == b


def test_freeze_manifest_pnpm_graph_hash_equal_for_windows_and_linux_inputs() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.ci.check_freeze_manifest import canonical_json, normalise_pnpm_graph

    win = [
        {
            "name": "x",
            "path": "C:/a",
            "z": 1,
            "a": "dir" + chr(92) + "sub" + chr(13) + chr(10) + "l",
            "b": [2, 1],
        }
    ]
    lin = [{"b": [1, 2], "a": "dir/sub" + chr(10) + "l", "z": 1, "path": "/home/c", "name": "x"}]
    assert canonical_json(normalise_pnpm_graph(win)) == canonical_json(normalise_pnpm_graph(lin))


def test_electron_toolchain_past_high_advisories() -> None:
    dev = json.loads((ROOT / "apps/desktop/package.json").read_text(encoding="utf-8"))[
        "devDependencies"
    ]
    assert dev["electron"] == "^41.10.7"
    assert dev["electron-builder"] == "^26.15.3"
