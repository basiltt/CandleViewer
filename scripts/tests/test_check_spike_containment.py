"""Unit tests for tools/ci/check_spike_containment.py (E06-X02).

Exercises the ticket's own Gherkin scenarios:
  - "Prototype code cannot reach main" (path-existence check, CI-SPIKE-001)
  - "The harness does not depend on the prototype" (import-boundary check,
    CI-SPIKE-002)
No network, no real git state — everything is built under `tmp_path`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_spike_containment as gate


def test_clean_tree_with_no_spike_path_passes(tmp_path: Path, capsys) -> None:
    (tmp_path / "packages/chart-engine/src").mkdir(parents=True)
    (tmp_path / "packages/chart-engine/src/index.ts").write_text(
        "export const x = 1;\n", encoding="utf-8"
    )

    assert gate.find_spike_paths(tmp_path) == []
    assert gate.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_spike_directory_present_fails_with_ci_spike_001(
    tmp_path: Path, capsys
) -> None:
    spike_dir = tmp_path / "packages/chart-engine/spike"
    spike_dir.mkdir(parents=True)
    (spike_dir / "prototype.ts").write_text("export const p = 1;\n", encoding="utf-8")

    hits = gate.find_spike_paths(tmp_path)
    assert hits == ["packages/chart-engine/spike/"]

    assert gate.main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "CI-SPIKE-001" in err
    assert "packages/chart-engine/spike/" in err
    assert "promoted-vs-throwaway" in err or "promoted" in err


def test_missing_spike_directory_has_no_hits(tmp_path: Path) -> None:
    (tmp_path / "packages/chart-engine").mkdir(parents=True)
    assert gate.find_spike_paths(tmp_path) == []


def test_harness_importing_spike_path_fails_with_ci_spike_002(
    tmp_path: Path, capsys
) -> None:
    spike_dir = tmp_path / "packages/chart-engine/spike"
    spike_dir.mkdir(parents=True)
    (spike_dir / "prototype.mjs").write_text(
        "export const proto = 1;\n", encoding="utf-8"
    )

    harness_dir = tmp_path / "packages/chart-engine/bench"
    harness_dir.mkdir(parents=True)
    (harness_dir / "runner.mjs").write_text(
        "import { proto } from '../spike/prototype.mjs';\nexport { proto };\n",
        encoding="utf-8",
    )

    violations = gate.find_harness_imports_of_spike(tmp_path)
    assert violations == [
        "packages/chart-engine/bench/runner.mjs -> ../spike/prototype.mjs"
    ]

    assert gate.main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "CI-SPIKE-001" in err  # spike dir itself is flagged first


def test_harness_import_violation_reported_when_no_spike_dir_present(
    tmp_path: Path, capsys
) -> None:
    # A harness file can reference a spike-shaped relative import even if the
    # spike directory has already been removed from this checkout (e.g. a
    # stale import left behind after archival) — the boundary check still
    # fires on the import text itself, independent of path existence.
    harness_dir = tmp_path / "packages/chart-engine/bench"
    harness_dir.mkdir(parents=True)
    (harness_dir / "runner.mjs").write_text(
        "import { proto } from '../spike/prototype.mjs';\nexport { proto };\n",
        encoding="utf-8",
    )

    assert gate.find_spike_paths(tmp_path) == []
    violations = gate.find_harness_imports_of_spike(tmp_path)
    assert violations == [
        "packages/chart-engine/bench/runner.mjs -> ../spike/prototype.mjs"
    ]

    assert gate.main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "CI-SPIKE-002" in err
    assert "../spike/prototype.mjs" in err


def test_harness_file_under_spike_marker_is_not_flagged_as_importer(
    tmp_path: Path,
) -> None:
    # A file that itself lives under the spike marker is spike code, not "the
    # harness importing the spike" — it must not double-count in the
    # import-boundary scan (it is already caught by find_spike_paths).
    spike_dir = tmp_path / "packages/chart-engine/spike"
    spike_dir.mkdir(parents=True)
    (spike_dir / "self.mjs").write_text(
        "import { helper } from './helper.mjs';\nexport { helper };\n",
        encoding="utf-8",
    )
    (spike_dir / "helper.mjs").write_text(
        "export const helper = 1;\n", encoding="utf-8"
    )

    # HARNESS_PATH_ROOTS does not include the spike dir, so no harness files
    # are scanned here at all — but exercise the guard directly for clarity.
    assert gate.find_harness_imports_of_spike(tmp_path) == []


def test_nonexistent_root_returns_exit_code_2(capsys) -> None:
    assert gate.main(["--root", "/definitely/does/not/exist/xyz"]) == 2
    err = capsys.readouterr().err
    assert "does not exist" in err
