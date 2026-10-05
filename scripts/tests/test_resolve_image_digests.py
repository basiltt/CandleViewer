"""Unit tests for tools/ci/resolve_image_digests.py (#1857). Fake registry; no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.resolve_image_digests import is_placeholder, main, split_repo

REAL = "sha256:" + "0123456789abcdef" * 2 + "fedcba9876543210" * 2
REAL2 = "sha256:a1b2c3d4e5f60718293a4b5c6d7e8f901f2e3d4c5b6a798897a6b5c4d3e2f101"
PLACEHOLDER = "sha256:" + "ab12cd34" * 8


class FakeRegistry:
    def __init__(self, tags: dict[tuple[str, str], str]) -> None:
        self.tags = tags

    def digest(self, repo: str, tag: str) -> str | None:
        return self.tags.get((repo, tag))

    def exists(self, repo: str, digest: str) -> bool:
        return digest in self.tags.values()


def _tree(tmp_path: Path, digest: str) -> Path:
    (tmp_path / "infra" / "compose").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    f = tmp_path / "infra" / "compose" / "docker-compose.yml"
    f.write_text(
        f"services:\n  db:\n    image: postgres:16.4@{digest}\n", encoding="utf-8"
    )
    return f


def test_is_placeholder_flags_fabricated_patterns() -> None:
    assert is_placeholder("0" * 64)
    assert is_placeholder("ab12cd34" * 8)
    assert is_placeholder("c0ffee" + "deadbeef" + "1234567890abcdef" * 3 + "12")
    assert not is_placeholder(REAL2.removeprefix("sha256:"))


def test_split_repo_defaults() -> None:
    assert split_repo("postgres") == ("registry-1.docker.io", "library/postgres")
    assert split_repo("grafana/grafana") == ("registry-1.docker.io", "grafana/grafana")
    assert split_repo("ghcr.io/zaproxy/zaproxy") == ("ghcr.io", "zaproxy/zaproxy")


def test_check_fails_on_placeholder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, PLACEHOLDER)
    rc = main(["--check", "--root", str(tmp_path)], FakeRegistry({}))
    assert rc == 1
    assert "placeholder" in capsys.readouterr().err


def test_check_fails_on_unknown_digest(tmp_path: Path) -> None:
    _tree(tmp_path, REAL2)
    assert main(["--check", "--root", str(tmp_path)], FakeRegistry({})) == 1


def test_check_passes_on_known_digest(tmp_path: Path) -> None:
    _tree(tmp_path, REAL2)
    reg = FakeRegistry({("postgres", "16.4"): REAL2})
    assert main(["--check", "--root", str(tmp_path)], reg) == 0


def test_resolve_rewrites_placeholder_in_place(tmp_path: Path) -> None:
    f = _tree(tmp_path, PLACEHOLDER)
    reg = FakeRegistry({("postgres", "16.4"): REAL2})
    assert main(["--root", str(tmp_path)], reg) == 0
    assert f.read_text(encoding="utf-8").strip().endswith(f"postgres:16.4@{REAL2}")
    assert main(["--check", "--root", str(tmp_path)], reg) == 0


def test_resolve_leaves_unpublished_tag_untouched(tmp_path: Path) -> None:
    f = _tree(tmp_path, PLACEHOLDER)
    before = f.read_text(encoding="utf-8")
    assert main(["--root", str(tmp_path)], FakeRegistry({})) == 0
    assert f.read_text(encoding="utf-8") == before


def test_resolve_keeps_real_pin_even_if_tag_moved(tmp_path: Path) -> None:
    f = _tree(tmp_path, REAL2)
    reg = FakeRegistry({("postgres", "16.4"): REAL, ("postgres", "old"): REAL2})
    main(["--root", str(tmp_path)], reg)
    assert REAL2 in f.read_text(encoding="utf-8")
