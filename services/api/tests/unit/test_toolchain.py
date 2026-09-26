"""Canary tests proving the toolchain baseline works (E02-T02).

Given a clean clone and `uv sync --frozen`, these assert: the interpreter is
>=3.12, the `candleviewer` package imports, and settings load with defaults.
"""

from __future__ import annotations

import sys

from candleviewer import __version__
from candleviewer.settings import Settings, get_settings


def test_toolchain_interpreter_is_at_least_3_12() -> None:
    assert sys.version_info[:2] >= (3, 12)


def test_toolchain_package_imports() -> None:
    assert __version__ == "0.1.0"


def test_toolchain_settings_load_with_defaults() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.environment == "dev"
