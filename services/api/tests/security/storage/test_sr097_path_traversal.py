"""SR-097 path-traversal / symlink-escape matrix (E07-X02).

Asserts at the filesystem layer with spies on open/scandir/listdir and on the
DuckDB read, not merely on the returned error: a control that raises after
touching the target has still leaked.
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import Any

import pytest

from candleviewer.storage.cold import parquet_repository as pr
from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.parquet_repository import ParquetColdTierRepository
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold._helpers import FakeHotSource, day_range, trades_table

BAD_SYMBOLS = [
    "../outside",
    "..",
    "../../etc/passwd",
    "/etc/passwd",
    r"C:\Windows\win.ini",
    "\\\\host\\share",
    "%2e%2e%2f",
    "..%2f..%2f",
    "BTC/../../x",
    "BTC\x00",
    ".hidden",
    "",
]


class FsSpy:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.touched: list[str] = []
        real_open, real_scandir, real_listdir = builtins.open, os.scandir, os.listdir

        def _open(file: Any, *a: Any, **k: Any) -> Any:
            self.touched.append(os.fspath(file) if not isinstance(file, int) else str(file))
            return real_open(file, *a, **k)

        def _scandir(path: Any = ".") -> Any:
            self.touched.append(os.fspath(path))
            return real_scandir(path)

        def _listdir(path: Any = ".") -> Any:
            self.touched.append(os.fspath(path))
            return real_listdir(path)

        monkeypatch.setattr(builtins, "open", _open)
        monkeypatch.setattr(os, "scandir", _scandir)
        monkeypatch.setattr(os, "listdir", _listdir)

        def _read_rows(files: list[str], *_: Any) -> list[dict[str, Any]]:
            self.touched.extend(files)
            return []

        monkeypatch.setattr(pr, "_read_rows", _read_rows)

    def outside(self, root: Path, canary: Path) -> list[str]:
        r = str(root.resolve())
        return [t for t in self.touched if str(canary) in t or not os.path.abspath(t).startswith(r)]


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, Path, ParquetColdTierRepository]:
    root = tmp_path / "cold"
    root.mkdir()
    canary = tmp_path / "outside"
    canary.mkdir()
    (canary / "secret.txt").write_text("x")
    repo = ParquetColdTierRepository(DatasetRegistry(root), FakeHotSource(trades_table(2)))
    return root, canary, repo


@pytest.mark.parametrize("symbol", BAD_SYMBOLS)
async def test_sr097_hostile_symbol_refused_with_no_fs_access_outside_root(
    symbol: str, env: tuple[Path, Path, ParquetColdTierRepository], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, _canary, repo = env
    spy = FsSpy(monkeypatch)
    with pytest.raises(DatasetNotRegistered):
        await repo.query(symbol, StreamKind.TRADES, day_range())
    assert spy.touched == []


async def test_sr097_unregistered_dataset_id_refused(
    env: tuple[Path, Path, ParquetColdTierRepository], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, canary, repo = env
    spy = FsSpy(monkeypatch)
    with pytest.raises((DatasetNotRegistered, ValueError, AttributeError)):
        await repo.query("BTCUSDT", "../../etc", day_range())  # type: ignore[arg-type]
    assert spy.outside(root, canary) == []


async def test_sr097_symlinked_partition_dir_is_refused_and_never_read(
    env: tuple[Path, Path, ParquetColdTierRepository], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, canary, repo = env
    link = root / "trades" / "symbol=BTCUSDT"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(canary, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform/privilege level")
    spy = FsSpy(monkeypatch)
    with pytest.raises(DatasetNotRegistered):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert spy.outside(root, canary) == []
    assert not any("secret.txt" in t for t in spy.touched)


def test_sr097_registry_has_no_path_accepting_api() -> None:
    import inspect

    sig = inspect.signature(ParquetColdTierRepository.query)
    assert list(sig.parameters) == ["self", "symbol", "stream", "rng"]
