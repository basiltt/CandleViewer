"""Unit tests for tools/ci/check_image_non_root.py (SR-131, CI-IMG-002).

Uses monkeypatched subprocess.run (no docker daemon in the unit test lane;
docker is exercised for real only inside main.yml's build job).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_image_non_root as mod


def _fake_run(config_user: str, probe_uid: str):
    def run(cmd, capture_output, text, check):
        if "inspect" in cmd:
            return SimpleNamespace(returncode=0, stdout=f'"{config_user}"\n', stderr="")
        if "run" in cmd:
            return SimpleNamespace(returncode=0, stdout=f"{probe_uid}\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    return run


def test_check_non_root_true_for_non_root_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("10001", "10001"))
    ok, detail = mod.check_non_root("candleviewer-api:ci")
    assert ok is True
    assert "10001" in detail


def test_check_non_root_false_for_empty_config_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("", "0"))
    ok, detail = mod.check_non_root("candleviewer-api:ci")
    assert ok is False
    assert "root" in detail


def test_check_non_root_false_for_root_config_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("root", "0"))
    ok, _detail = mod.check_non_root("candleviewer-api:ci")
    assert ok is False


def test_check_non_root_false_when_live_probe_returns_uid_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("10001", "0"))
    ok, detail = mod.check_non_root("candleviewer-api:ci")
    assert ok is False
    assert "uid 0" in detail


def test_main_exits_1_on_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("", "0"))
    assert mod.main(["--image", "candleviewer-api:ci"]) == 1


def test_main_exits_0_on_non_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("10001", "10001"))
    assert mod.main(["--image", "candleviewer-api:ci"]) == 0


def test_main_exits_2_when_docker_inspect_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(cmd, capture_output, text, check):
        return SimpleNamespace(returncode=1, stdout="", stderr="no such image")

    monkeypatch.setattr(subprocess, "run", run)
    assert mod.main(["--image", "missing:ci"]) == 2
