"""Tests for tools/ci/turbo-affected-packages.mjs (E03-T04 follow-up).

The pure `affectedDirectories()` parser is exercised through node so the
manifest the JS lanes upload always matches what coverage_gate.py reads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ci" / "turbo-affected-packages.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not installed"
)


def _affected(dry_run: dict[str, object]) -> list[str]:
    js = (
        "import('"
        + SCRIPT.resolve().as_uri()
        + "').then(m => { let d=''; process.stdin.on('data', c => d += c);"
        " process.stdin.on('end', () => console.log(JSON.stringify(m.affectedDirectories(JSON.parse(d))))); })"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", js],
        input=json.dumps(dry_run),
        capture_output=True,
        text=True,
        check=True,
    )
    result: list[str] = json.loads(out.stdout.strip().splitlines()[-1])
    return result


def test_only_test_cov_tasks_are_listed_with_forward_slashes() -> None:
    dry_run = {
        "tasks": [
            {
                "package": "@candleviewer/chart-engine",
                "directory": "packages\\chart-engine",
                "task": "test:cov",
            },
            {
                "package": "@candleviewer/config",
                "directory": "packages\\config",
                "task": "build",
            },
            {
                "package": "@candleviewer/protocol",
                "directory": "packages/protocol",
                "task": "test:cov",
            },
        ]
    }
    assert _affected(dry_run) == ["packages/chart-engine", "packages/protocol"]


def test_no_scheduled_tasks_yields_empty_manifest() -> None:
    assert _affected({"tasks": []}) == []
    assert _affected({}) == []


def test_cli_without_separator_exits_2(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["node", str(SCRIPT), str(tmp_path / "out.txt")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "usage" in proc.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
