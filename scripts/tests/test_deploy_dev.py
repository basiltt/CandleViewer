"""Unit tests for tools/ci/deploy_dev.py (E03-T09 dev/staging deploy).

No docker/network: `subprocess.run` and `urllib.request.urlopen` are
monkeypatched so these run fully offline (C-13.5 / AGENTS.md §8.7).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import deploy_dev as dd


@pytest.fixture()
def env_example(tmp_path: Path) -> Path:
    p = tmp_path / ".env.example"
    p.write_text(
        "CV_ENVIRONMENT=demo\nCV_FEED=synthetic\nCV_GIT_SHA=unknown\n", encoding="utf-8"
    )
    return p


def test_render_env_file_sets_digest_and_sha(tmp_path: Path, env_example: Path) -> None:
    out = tmp_path / ".env"
    dd.render_env_file(
        env_example, out, image_digest="sha256:" + "a" * 64, git_sha="abc1234"
    )
    text = out.read_text(encoding="utf-8")
    assert "CV_GIT_SHA=abc1234" in text
    assert "CV_IMAGE_DIGEST=sha256:" + "a" * 64 in text
    assert "CV_FEED=synthetic" in text


def test_verify_signature_raises_ci_dep_001_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="no matching signatures"),
    )
    with pytest.raises(dd.DeployError) as exc:
        dd.verify_signature("ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r")
    assert exc.value.code == "CI-DEP-001"


def test_verify_signature_passes_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    dd.verify_signature(
        "ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r"
    )  # no raise


def test_verify_signature_pins_identity_to_signer_workflow_and_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare `^https://github.com/{repo}/` prefix matches any workflow in the
    repo (including a PR-branch run). The regexp passed to `cosign verify`
    must pin `main.yml`'s job identity and an allowed ref for the target
    environment."""
    captured: dict = {}

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", fake_run)

    dd.verify_signature(
        "ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r", environment="dev"
    )
    idx = captured["cmd"].index("--certificate-identity-regexp")
    regexp = captured["cmd"][idx + 1]
    assert r"\.github/workflows/main\.yml" in regexp
    assert regexp.endswith(r"@(?:refs/heads/main)$")
    # A build on a PR branch or a different workflow must not match.
    import re as _re

    signer_main = "https://github.com/o/r/.github/workflows/main.yml@refs/heads/main"
    signer_pr = "https://github.com/o/r/.github/workflows/main.yml@refs/pull/9/merge"
    other_workflow = (
        "https://github.com/o/r/.github/workflows/deploy-dev.yml@refs/heads/main"
    )
    assert _re.match(regexp, signer_main)
    assert not _re.match(regexp, signer_pr)
    assert not _re.match(regexp, other_workflow)


def test_verify_signature_staging_also_allows_release_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(dd.subprocess, "run", fake_run)

    dd.verify_signature(
        "ghcr.io/o/img", "sha256:" + "a" * 64, repository="o/r", environment="staging"
    )
    idx = captured["cmd"].index("--certificate-identity-regexp")
    regexp = captured["cmd"][idx + 1]
    import re as _re

    signer_release = (
        "https://github.com/o/r/.github/workflows/main.yml@refs/heads/release/1.2"
    )
    assert _re.match(regexp, signer_release)


def test_smoke_test_matches_sha_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        calls["n"] += 1
        if "healthz" in url:
            return {"status": "ok", "git_sha": "abc1234"}
        return {"status": "ok"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)
    dd.smoke_test("http://x", "abc1234", timeout_s=5.0)
    assert calls["n"] == 2


def test_smoke_test_sha_mismatch_raises_ci_dep_003(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        if "healthz" in url:
            return {"status": "ok", "git_sha": "old-sha"}
        return {"status": "ok"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "new-sha", timeout_s=0.05)
    assert exc.value.code in {"CI-DEP-002", "CI-DEP-003"}


def test_smoke_test_never_ready_raises_ci_dep_002(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        return {"status": "starting"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)
    with pytest.raises(dd.DeployError) as exc:
        dd.smoke_test("http://x", "abc1234", timeout_s=0.05)
    assert exc.value.code == "CI-DEP-002"


def test_ledger_append_and_read_last_success(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s1",
            digest="sha256:" + "1" * 64,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s2",
            digest="sha256:" + "2" * 64,
            environment="dev",
            actor="ci",
            timestamp="2026-01-02T00:00:00Z",
            outcome="signature-verification-failed",
        ),
        ledger,
    )
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["outcome"] == "success"
    assert dd.read_last_success_digest("dev", ledger) == "sha256:" + "1" * 64
    assert dd.read_last_success_digest("staging", ledger) is None


def test_deploy_success_path_writes_success_ledger(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        return {"status": "ok", "git_sha": "abc1234"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "a" * 64,
        sha="abc1234",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=5.0,
        auto_rollback=False,
    )
    assert rc == 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "success"


def test_deploy_tampered_image_aborts_before_compose_up(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance scenario: unsigned/tampered image is refused, ledger records
    `signature-verification-failed`, and `docker compose up` is never called."""
    compose_up_called = {"n": 0}

    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad sig"),
    )

    def fake_compose_up(*a, **k):
        compose_up_called["n"] += 1

    monkeypatch.setattr(dd, "compose_up", fake_compose_up)
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="deadbee",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=5.0,
        auto_rollback=False,
    )
    assert rc == 1
    assert compose_up_called["n"] == 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "signature-verification-failed"


def test_deploy_failed_smoke_triggers_dev_auto_rollback(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance scenario: a failed smoke test marks the deployment failed
    and the previous digest is automatically restored (dev only)."""
    good_digest = "sha256:" + "1" * 64
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest=good_digest,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )

    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(dd, "compose_up", lambda *a, **k: None)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)

    call_count = {"n": 0}

    def fake_get_json(url: str, timeout_s: float = 3.0) -> dict:
        call_count["n"] += 1
        # Forward deploy never becomes ready -> CI-DEP-002; rollback's
        # readiness-only poll succeeds immediately.
        if "readyz" in url and call_count["n"] > 2:
            return {"status": "ok"}
        return {"status": "starting"}

    monkeypatch.setattr(dd, "_get_json", fake_get_json)

    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="bad-sha",
        environment="dev",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        auto_rollback=True,
    )
    assert rc == 1
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    outcomes = [r["outcome"] for r in rows]
    assert "smoke-failed" in outcomes
    assert "rolled-back" in outcomes
    rolled_back_row = next(r for r in rows if r["outcome"] == "rolled-back")
    assert rolled_back_row["digest"] == good_digest


def test_read_last_success_digest_missing_ledger_returns_none(tmp_path: Path) -> None:
    assert dd.read_last_success_digest("dev", tmp_path / "nope.jsonl") is None


def test_read_last_success_digest_skips_seed_and_blank_lines(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n"
        + json.dumps(
            {
                "sha": "seed-sha",
                "digest": "sha256:" + "9" * 64,
                "environment": "dev",
                "actor": "seed",
                "outcome": "success",
            }
        )
        + "\n\n"
        + json.dumps(
            {
                "sha": "real-sha",
                "digest": "sha256:" + "8" * 64,
                "environment": "dev",
                "actor": "ci",
                "outcome": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert dd.read_last_success_digest("dev", ledger) == "sha256:" + "8" * 64


def test_read_last_success_digest_before_line_excludes_later_entries(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s1",
            digest="sha256:" + "1" * 64,
            environment="dev",
            actor="ci",
            timestamp="t1",
            outcome="success",
        ),
        ledger,
    )
    dd.append_ledger(
        dd.LedgerEntry(
            sha="s2",
            digest="sha256:" + "2" * 64,
            environment="dev",
            actor="ci",
            timestamp="t2",
            outcome="success",
        ),
        ledger,
    )
    assert (
        dd.read_last_success_digest("dev", ledger, before_line=1)
        == "sha256:" + "1" * 64
    )


def test_compose_up_raises_ci_dep_002_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stderr="compose failed: port in use"
        ),
    )
    with pytest.raises(dd.DeployError) as exc:
        dd.compose_up(("infra/compose/docker-compose.yml",))
    assert exc.value.code == "CI-DEP-002"
    assert "port in use" in str(exc.value)


def test_auto_rollback_no_previous_digest_logs_and_returns(
    tmp_path: Path, env_example: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd._auto_rollback(
        environment="dev",
        actor="ci",
        repository="o/r",
        image_ref="ghcr.io/o/img",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=1.0,
        failed_digest="sha256:" + "b" * 64,
    )
    assert not ledger.exists() or ledger.read_text(encoding="utf-8") == ""
    assert "no previous known-good digest" in capsys.readouterr().err


def test_auto_rollback_signature_failure_records_smoke_failed(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    good_digest = "sha256:" + "1" * 64
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest=good_digest,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad sig"),
    )
    dd._auto_rollback(
        environment="dev",
        actor="ci",
        repository="o/r",
        image_ref="ghcr.io/o/img",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        failed_digest="sha256:" + "b" * 64,
    )
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "smoke-failed"
    assert "auto-rollback failed" in rows[-1]["detail"]


def test_auto_rollback_never_ready_raises_ci_dep_002(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    good_digest = "sha256:" + "1" * 64
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest=good_digest,
            environment="dev",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(dd, "compose_up", lambda *a, **k: None)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: {"status": "starting"})
    dd._auto_rollback(
        environment="dev",
        actor="ci",
        repository="o/r",
        image_ref="ghcr.io/o/img",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        failed_digest="sha256:" + "b" * 64,
    )
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "smoke-failed"
    assert "rollback smoke test did not become ready" in rows[-1]["detail"]


def test_main_success_returns_zero_and_defaults_auto_rollback_for_dev(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(
        dd, "_get_json", lambda *a, **k: {"status": "ok", "git_sha": "abc1234"}
    )
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.main(
        [
            "--image-ref",
            "ghcr.io/o/img",
            "--digest",
            "sha256:" + "a" * 64,
            "--sha",
            "abc1234",
            "--environment",
            "dev",
            "--actor",
            "ci",
            "--repository",
            "o/r",
            "--env-example",
            str(env_example),
            "--env-out",
            str(tmp_path / ".env"),
            "--compose-file",
            "infra/compose/docker-compose.yml",
            "--base-url",
            "http://x",
            "--ledger",
            str(ledger),
            "--smoke-timeout-s",
            "5.0",
        ]
    )
    assert rc == 0
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "success"


def test_main_no_auto_rollback_flag_disables_rollback_for_dev(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad sig"),
    )
    ledger = tmp_path / "ledger.jsonl"
    rc = dd.main(
        [
            "--image-ref",
            "ghcr.io/o/img",
            "--digest",
            "sha256:" + "b" * 64,
            "--sha",
            "bad-sha",
            "--environment",
            "dev",
            "--actor",
            "ci",
            "--repository",
            "o/r",
            "--env-example",
            str(env_example),
            "--env-out",
            str(tmp_path / ".env"),
            "--compose-file",
            "infra/compose/docker-compose.yml",
            "--base-url",
            "http://x",
            "--ledger",
            str(ledger),
            "--no-auto-rollback",
        ]
    )
    assert rc == 1
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["outcome"] == "signature-verification-failed"


def test_deploy_staging_never_auto_rolls_back(
    tmp_path: Path, env_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dd.append_ledger(
        dd.LedgerEntry(
            sha="prev-sha",
            digest="sha256:" + "1" * 64,
            environment="staging",
            actor="ci",
            timestamp="2026-01-01T00:00:00Z",
            outcome="success",
        ),
        ledger,
    )
    monkeypatch.setattr(
        dd.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="")
    )
    monkeypatch.setattr(dd, "compose_up", lambda *a, **k: None)
    monkeypatch.setattr(dd.time, "sleep", lambda _s: None)
    monkeypatch.setattr(dd, "_get_json", lambda *a, **k: {"status": "starting"})

    rc = dd.deploy(
        image_ref="ghcr.io/o/img",
        digest="sha256:" + "b" * 64,
        sha="bad-sha",
        environment="staging",
        actor="ci",
        repository="o/r",
        env_example=env_example,
        env_out=tmp_path / ".env",
        compose_files=("infra/compose/docker-compose.yml",),
        base_url="http://x",
        ledger_path=ledger,
        smoke_timeout_s=0.05,
        auto_rollback=False,
    )
    assert rc == 1
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()]
    assert all(r["outcome"] != "rolled-back" for r in rows)
