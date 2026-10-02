"""E07-X02: the DAST probe refuses non-loopback targets and flags leaks (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dast_storage_probe as probe  # noqa: E402


def test_refuses_non_loopback_target() -> None:
    assert probe.run("http://example.com")


def test_flags_200_on_traversal_and_passes_on_refusal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(probe, "_get", lambda url: (200, b"root:x:0:0"))
    assert probe.run("http://127.0.0.1:8000")
    monkeypatch.setattr(probe, "_get", lambda url: (404, b""))
    assert probe.run("http://127.0.0.1:8000") == []
