"""Unit tests for scripts/check_codeowners_coverage.py (GOV-001)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_codeowners_coverage


def _init_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)


def _write(repo_root: Path, rel_path: str, content: str) -> Path:
    path = repo_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _add_all(repo_root: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)


BASE_HEADER = (
    "# CODEOWNERS\n"
    "#\n"
    "# Teams:\n"
    "#   @Org/architecture - architects\n"
    "#   @Org/backend - backend\n"
    "\n"
)

# Appended after every test's own rules so it always wins as "later rule" and
# keeps the harness's own support file (.github/CODEOWNERS itself) from
# tripping the catch-all check. Marked `# future:` since not every fixture
# repo writes a scripts/ file.
HARNESS_TAIL = (
    "/.github/                    @Org/architecture\n"
    "# future: only present when a test writes scripts/*\n"
    "/scripts/                    @Org/architecture\n"
)


def test_every_path_deliberately_owned_exits_zero(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER
        + "*                 @Org/architecture\n"
        + "/docs/            @Org/architecture\n"
        + "/services/        @Org/backend\n"
        + HARNESS_TAIL,
    )
    _write(tmp_path, "docs/note.md", "hello\n")
    _write(tmp_path, "services/api/app.py", "print(1)\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_unowned_path_falls_through_to_catch_all(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER + "*                 @Org/architecture\n" + "/docs/            @Org/architecture\n",
    )
    _write(tmp_path, "docs/note.md", "hello\n")
    _write(tmp_path, "services/newthing/main.py", "print(1)\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "GOV-001" in out
    assert "services/newthing/main.py" in out
    assert "catch-all" in out


def test_dead_rule_is_caught(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER
        + "*                          @Org/architecture\n"
        + "/docs/                     @Org/architecture\n"
        + "/packages/typo-name/       @Org/architecture\n",
    )
    _write(tmp_path, "docs/note.md", "hello\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "dead rule" in out
    assert "/packages/typo-name/" in out


def test_future_marked_dead_rule_does_not_fail(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER
        + "*                          @Org/architecture\n"
        + "/docs/                     @Org/architecture\n"
        + "# future: E02 scaffolding\n"
        + "/packages/chart-engine/    @Org/architecture\n"
        + HARNESS_TAIL,
    )
    _write(tmp_path, "docs/note.md", "hello\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_later_rule_wins_over_earlier_general_rule(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER
        + "*                             @Org/architecture\n"
        + "/docs/                        @Org/architecture\n"
        + "/docs/plan/backlog/           @Org/backend\n",
    )
    _write(tmp_path, "docs/plan/backlog/E01.json", "{}\n")
    _add_all(tmp_path)

    _, results = check_codeowners_coverage.check(str(tmp_path))
    match = next(r for r in results if r.path == "docs/plan/backlog/E01.json")
    assert match.rule is not None
    assert match.rule.owners == ("@Org/backend",)


def test_unknown_owner_is_flagged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER
        + "*                 @Org/architecture\n"
        + "/docs/            @typo-not-declared\n"
        + HARNESS_TAIL,
    )
    _write(tmp_path, "docs/note.md", "hello\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "@typo-not-declared" in out
    assert "not in the declared team list" in out


def test_allowlisted_path_does_not_fail_on_catch_all(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER + "*                 @Org/architecture\n" + HARNESS_TAIL,
    )
    _write(tmp_path, "LICENSE", "MIT\n")
    _write(
        tmp_path,
        "scripts/codeowners-allowlist.txt",
        "LICENSE\n# reason: legal boilerplate, no meaningful owner.\n",
    )
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    assert exit_code == 0


def test_allowlist_entry_without_reason_is_internal_error(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER + "*                 @Org/architecture\n" + HARNESS_TAIL,
    )
    _write(tmp_path, "LICENSE", "MIT\n")
    _write(tmp_path, "scripts/codeowners-allowlist.txt", "LICENSE\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    assert exit_code == 2


def test_json_output_is_structured(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER + "*                 @Org/architecture\n" + HARNESS_TAIL,
    )
    _write(tmp_path, "services/foo.py", "print(1)\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 1
    import json

    payload = json.loads(out)
    assert payload["catch_all"][0]["path"] == "services/foo.py"


def test_report_mode_lists_every_path_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER + "*                 @Org/architecture\n",
    )
    _write(tmp_path, "services/foo.py", "print(1)\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path), "--report"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "services/foo.py" in out


def test_rule_with_no_owners_is_internal_error(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write(
        tmp_path,
        ".github/CODEOWNERS",
        BASE_HEADER + "*                 @Org/architecture\n" + "/docs/\n",
    )
    _write(tmp_path, "docs/note.md", "hello\n")
    _add_all(tmp_path)

    exit_code = check_codeowners_coverage.main(["--repo-root", str(tmp_path)])
    assert exit_code == 2


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("/docs/", "docs/note.md", True),
        ("/docs/", "other/docs/note.md", False),
        ("docs/", "other/docs/note.md", True),
        ("*.md", "a/b/c.md", True),
        ("**/tokens/", "packages/ui/src/tokens/x.json", True),
        ("/apps/web/", "apps/web/src/index.ts", True),
        ("/apps/web/", "apps/desktop/src/index.ts", False),
    ],
)
def test_pattern_matches_matrix(pattern: str, path: str, expected: bool) -> None:
    assert check_codeowners_coverage.pattern_matches(pattern, path) is expected
