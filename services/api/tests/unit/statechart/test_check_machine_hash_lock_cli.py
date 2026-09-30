"""tests/unit/statechart/test_check_machine_hash_lock_cli.py (E50-T02).

Exercises `tools/statechart/check_machine_hash_lock.py`'s CLI surface
end-to-end against `tmp_path` machine-JSON fixtures (`--write` then a
clean diff, an uncovered-drift failure, a removed-machine failure, and a
malformed-lock internal error).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.statechart import check_machine_hash_lock as gate  # noqa: E402

_CHART: dict[str, Any] = {
    "id": "test.cli.machine",
    "strictConfig": True,
    "strict": True,
    "strictTargets": True,
    "onUnhandled": "defer",
    "maxIterations": 50,
    "version": 1,
    "initial": "idle",
    "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#test.cli.machine.done"}}},
        "done": {"type": "final"},
    },
}


def _write_chart(machines_dir: Path, chart: dict[str, Any]) -> None:
    machines_dir.mkdir(parents=True, exist_ok=True)
    (machines_dir / f"{chart['id']}.machine.json").write_text(json.dumps(chart), encoding="utf-8")


@pytest.fixture()
def machines_dir(tmp_path: Path) -> Path:
    d = tmp_path / "machines"
    _write_chart(d, _CHART)
    return d


def test_write_then_clean_diff_exits_zero(machines_dir: Path) -> None:
    lock_path = machines_dir / "machine_hashes.lock"

    write_code = gate.main(
        ["--write", "--machines-dir", str(machines_dir), "--lock-path", str(lock_path)]
    )
    assert write_code == 0
    assert lock_path.exists()

    diff_code = gate.main(["--machines-dir", str(machines_dir), "--lock-path", str(lock_path)])
    assert diff_code == 0


def test_uncovered_drift_exits_one(machines_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lock_path = machines_dir / "machine_hashes.lock"
    lock_path.write_text(
        json.dumps({"machines": {"test.cli.machine": {"hash": "x" * 64, "version": 1}}}),
        encoding="utf-8",
    )

    code = gate.main(["--machines-dir", str(machines_dir), "--lock-path", str(lock_path)])
    assert code == 1
    err = capsys.readouterr().err
    assert "test.cli.machine" in err


def test_removed_machine_exits_one_unless_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_dir = tmp_path / "empty-machines"
    empty_dir.mkdir()
    lock_path = empty_dir / "machine_hashes.lock"
    lock_path.write_text(
        json.dumps({"machines": {"gone.machine": {"hash": "y" * 64, "version": 1}}}),
        encoding="utf-8",
    )

    code = gate.main(["--machines-dir", str(empty_dir), "--lock-path", str(lock_path)])
    assert code == 1
    assert "gone.machine" in capsys.readouterr().err

    allowed_code = gate.main(
        [
            "--machines-dir",
            str(empty_dir),
            "--lock-path",
            str(lock_path),
            "--allow-removed",
        ]
    )
    assert allowed_code == 0


def test_malformed_lock_file_exits_two(machines_dir: Path) -> None:
    lock_path = machines_dir / "machine_hashes.lock"
    lock_path.write_text("{not json", encoding="utf-8")

    code = gate.main(["--machines-dir", str(machines_dir), "--lock-path", str(lock_path)])
    assert code == 2
