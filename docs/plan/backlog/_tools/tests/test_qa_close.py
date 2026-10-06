"""Subprocess-level tests for qa_close.py: gate wiring and --force-owner. No network.

qa_close.py is copied into a temp dir next to stub `publish_board`, `done_gate`, `set_status` modules and
a fake `gh` launcher, so the real script runs unchanged but nothing real is called.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
QA_PASS = {"body": "QA verification — VERDICT: PASS", "createdAt": "2026-10-01"}

FAKE_GH = r"""import json, os, sys
a = sys.argv[1:]
d = os.environ["FAKE_DIR"]
if a[:2] == ["api", "user"]:
    print(os.environ.get("FAKE_LOGIN", "agent"))
elif a[:2] == ["issue", "view"]:
    print(open(os.path.join(d, "issue.json"), encoding="utf-8").read())
else:
    open(os.path.join(d, "gh_calls.log"), "a").write(" ".join(a) + chr(10))
"""


def setup(
    tmp: Path, gate_rc: int, comments: list[dict[str, str]], state: str = "OPEN"
) -> Path:
    shutil.copy(TOOLS / "qa_close.py", tmp / "qa_close.py")
    (tmp / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
    if os.name == "nt":
        launcher = tmp / "gh.cmd"
        launcher.write_text(
            f'@"{sys.executable}" "%~dp0fake_gh.py" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = tmp / "gh"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_gh.py" "$@"\n'
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    (tmp / "publish_board.py").write_text(
        f'GH = r"{launcher}"\nREPO = "o/r"\n', encoding="utf-8"
    )
    (tmp / "done_gate.py").write_text(
        f'print("gate says no")\nraise SystemExit({gate_rc})\n', encoding="utf-8"
    )
    (tmp / "set_status.py").write_text(
        "import os, sys\n"
        'open(os.path.join(os.environ["FAKE_DIR"], "set_status.log"), "a", encoding="utf-8").write(" | ".join(sys.argv[1:]) + chr(10))\n',
        encoding="utf-8",
    )
    (tmp / "issue.json").write_text(
        json.dumps({"comments": comments, "state": state}), encoding="utf-8"
    )
    return tmp


def run(
    tmp: Path, *args: str, login: str = "agent"
) -> subprocess.CompletedProcess[str]:
    env = dict(
        os.environ,
        FAKE_DIR=str(tmp),
        FAKE_LOGIN=login,
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
    )
    return subprocess.run(
        [sys.executable, str(tmp / "qa_close.py"), "K-1", "7", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def status_log(tmp: Path) -> str:
    p = tmp / "set_status.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_refuses_when_gate_exits_1(tmp_path: Path) -> None:
    setup(tmp_path, 1, [QA_PASS])
    r = run(tmp_path)
    assert (
        r.returncode == 1
        and "done-gate failed" in r.stdout
        and "gate says no" in r.stdout
    )
    assert status_log(tmp_path) == ""


def test_closes_when_gate_exits_0(tmp_path: Path) -> None:
    setup(tmp_path, 0, [QA_PASS])
    r = run(tmp_path)
    assert r.returncode == 0 and "DONE" in r.stdout
    assert "K-1 | Done" in status_log(
        tmp_path
    ) and "Done-gate (DoD evidence) PASS" in status_log(tmp_path)


def test_gate_error_exit_2_also_blocks(tmp_path: Path) -> None:
    setup(tmp_path, 2, [QA_PASS])
    assert run(tmp_path).returncode == 1 and status_log(tmp_path) == ""


def test_force_owner_by_owner_logs_reason(tmp_path: Path) -> None:
    setup(tmp_path, 1, [QA_PASS])
    r = run(tmp_path, "--force-owner", "boxes", "not", "ticked", login="basiltt")
    assert r.returncode == 0
    assert "OVERRIDDEN by owner (--force-owner): boxes not ticked" in status_log(
        tmp_path
    )


def test_force_owner_refused_for_non_owner(tmp_path: Path) -> None:
    setup(tmp_path, 1, [QA_PASS])
    r = run(tmp_path, "--force-owner", "because", login="agent")
    assert r.returncode == 1 and "refused" in r.stdout and status_log(tmp_path) == ""


def test_force_owner_requires_reason(tmp_path: Path) -> None:
    setup(tmp_path, 1, [QA_PASS])
    r = run(tmp_path, "--force-owner", login="basiltt")
    assert r.returncode == 1 and status_log(tmp_path) == ""


def test_force_owner_does_not_bypass_missing_qa_pass(tmp_path: Path) -> None:
    setup(tmp_path, 0, [])
    r = run(tmp_path, "--force-owner", "why", login="basiltt")
    assert r.returncode == 1 and status_log(tmp_path) == ""
