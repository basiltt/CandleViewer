"""Unit tests for tools/ci/check_action_pins.py (SR-132).

Covers: pinned SHA passes, tag fails, pull_request_target fails, comment
lines are ignored, local/docker refs are exempt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_action_pins import check_file, main

PINNED_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_check_file_pinned_sha_passes(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "ok.yml",
        f"""\
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA} # v4.2.2
""",
    )
    assert check_file(wf) == []


def test_check_file_floating_tag_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "bad.yml",
        """\
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
""",
    )
    violations = check_file(wf)
    assert len(violations) == 1
    assert "not a 40-hex commit SHA" in violations[0].reason


def test_check_file_no_ref_at_all_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "noref.yml",
        """\
jobs:
  build:
    steps:
      - uses: actions/checkout
""",
    )
    violations = check_file(wf)
    assert len(violations) == 1
    assert "no @ref" in violations[0].reason


def test_check_file_pull_request_target_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "prt.yml",
        f"""\
on:
  pull_request_target:
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    violations = check_file(wf)
    assert any("pull_request_target" in v.reason for v in violations)


def test_check_file_comment_lines_ignored(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "commented.yml",
        f"""\
jobs:
  build:
    steps:
      # - uses: actions/checkout@v4
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    assert check_file(wf) == []


def test_check_file_local_ref_exempt(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "local.yml",
        """\
jobs:
  build:
    steps:
      - uses: ./.github/actions/local-thing
""",
    )
    assert check_file(wf) == []


def test_check_file_docker_ref_with_digest_passes(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "docker_ok.yml",
        """\
jobs:
  build:
    steps:
      - uses: docker://alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
""",
    )
    assert check_file(wf) == []


def test_check_file_docker_ref_floating_tag_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "docker_bad.yml",
        """\
jobs:
  build:
    steps:
      - uses: docker://alpine:3.19
""",
    )
    violations = check_file(wf)
    assert len(violations) == 1
    assert "sha256" in violations[0].reason


def test_check_file_pull_request_target_inline_scalar_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "prt_inline.yml",
        f"""\
on: pull_request_target
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    violations = check_file(wf)
    assert any("pull_request_target" in v.reason for v in violations)


def test_check_file_pull_request_target_inline_list_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "prt_list.yml",
        f"""\
on: [push, pull_request_target]
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    violations = check_file(wf)
    assert any("pull_request_target" in v.reason for v in violations)


def test_check_file_pull_request_target_as_substring_not_flagged(tmp_path: Path) -> None:
    # A job step that merely mentions the trigger name in an unrelated
    # `run:` line must not trip the check — only the `on:` trigger block does.
    wf = _write(
        tmp_path,
        "mention.yml",
        f"""\
on:
  push:
jobs:
  build:
    steps:
      - run: echo "not a pull_request_target trigger"
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    assert check_file(wf) == []


def test_main_exits_1_on_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wf = _write(tmp_path, "bad.yml", "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n")
    rc = main([str(wf)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "CI-GATE-003" in captured.err


def test_main_exits_0_on_clean_dir(tmp_path: Path) -> None:
    _write(tmp_path, "ok.yml", f"jobs:\n  build:\n    steps:\n      - uses: actions/checkout@{PINNED_SHA}\n")
    rc = main([str(tmp_path)])
    assert rc == 0


def test_main_exits_2_on_missing_path() -> None:
    rc = main(["/no/such/path/at/all"])
    assert rc == 2
