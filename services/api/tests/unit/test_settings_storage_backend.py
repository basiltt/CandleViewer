"""`Settings.storage_backend` (E07-T01): the switch that lets the app
supervisor boot with `CV_STORAGE_BACKEND=fake` and no database containers
running (ticket acceptance criterion 1)."""

from __future__ import annotations

from candleviewer.settings import Settings


def test_storage_backend_defaults_to_fake() -> None:
    assert Settings().storage_backend == "fake"


def test_storage_backend_reads_from_env(monkeypatch: object) -> None:
    import os

    os.environ["CV_STORAGE_BACKEND"] = "real"
    try:
        assert Settings().storage_backend == "real"
    finally:
        del os.environ["CV_STORAGE_BACKEND"]
