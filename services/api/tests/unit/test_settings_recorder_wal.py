"""E16-T03: `CV_RECORDER_WAL_DIR` validation (SR-097 pattern; it is mkdir'd with parents)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings


def _settings(tmp_path: Path, wal: str) -> Settings:
    return Settings(parquet_root=str(tmp_path / "parquet"), recorder_wal_dir=wal)


def test_default_wal_dir_is_inside_the_data_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path, "")
    assert Path(s.recorder_wal_dir) == (tmp_path / "recorder-wal").resolve()


def test_absolute_dir_inside_the_data_dir_is_accepted(tmp_path: Path) -> None:
    assert Path(_settings(tmp_path, str(tmp_path / "w")).recorder_wal_dir).name == "w"


@pytest.mark.parametrize(
    ("wal", "message"),
    [
        ("relative/wal", "absolute"),
        ("{root}/x/../../etc", "'..'"),
        ("{outside}", "inside the data dir"),
        ("{root}", "inside the data dir"),
    ],
)
def test_unsafe_wal_dir_is_refused(tmp_path: Path, wal: str, message: str) -> None:
    outside = tmp_path.parent / "elsewhere"
    with pytest.raises(ValidationError, match=message):
        _settings(tmp_path, wal.format(root=tmp_path, outside=outside))


def test_symlinked_wal_dir_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path / "target", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this host")
    with pytest.raises(ValidationError, match="symlink"):
        _settings(tmp_path, str(link))
