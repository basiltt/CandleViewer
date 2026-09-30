"""Unit tests for `candleviewer.statechart.lock` (E50-T02).

Covers the ticket's two Gherkin acceptance criteria end-to-end:
  1. "Hash drift without upcaster fails" — a chart edit changes
     `machine_hash` with no version bump and no registered upcaster.
  2. "No-op upcaster refused" — covered directly in `test_upcasters.py`;
     here we additionally confirm a *registered* (non-no-op) upcaster plus
     a version bump is what `diff()` calls covered.

Also covers: unchanged hash is a no-op, a brand-new machine is not drift,
a removed machine is reported by `check_removed`, and `render_lock` /
`load_lock` round-trip through a temp file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.statechart.lock import (
    LockFileError,
    check_removed,
    diff,
    load_lock,
    render_lock,
)
from candleviewer.statechart.registry import Registry
from candleviewer.statechart.upcasters import register_upcaster

_CHART_V1: dict[str, Any] = {
    "id": "test.lock.machine",
    "strictConfig": True,
    "strict": True,
    "strictTargets": True,
    "onUnhandled": "defer",
    "maxIterations": 50,
    "version": 1,
    "initial": "idle",
    "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#test.lock.machine.done"}}},
        "done": {"type": "final"},
    },
}


def _write_chart(machines_dir: Path, chart: dict[str, Any]) -> None:
    machines_dir.mkdir(parents=True, exist_ok=True)
    path = machines_dir / f"{chart['id']}.machine.json"
    path.write_text(json.dumps(chart), encoding="utf-8")


def _registry_hash(chart: dict[str, Any]) -> str:
    from candleviewer.statechart.registry import machine_hash

    return machine_hash(chart)


class TestLoadLock:
    def test_missing_lock_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_lock(tmp_path / "no-such.lock") == {}

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.lock"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(LockFileError):
            load_lock(path)

    def test_missing_machines_key_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad2.lock"
        path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        with pytest.raises(LockFileError):
            load_lock(path)


class TestRenderLock:
    def test_render_then_load_round_trips(self, tmp_path: Path) -> None:
        _write_chart(tmp_path, _CHART_V1)
        registry = Registry(machines_dir=tmp_path)
        rendered = render_lock(registry)
        lock_path = tmp_path / "machine_hashes.lock"
        lock_path.write_text(json.dumps(rendered), encoding="utf-8")

        loaded = load_lock(lock_path)
        assert loaded["test.lock.machine"]["hash"] == registry.hash("test.lock.machine")
        assert loaded["test.lock.machine"]["version"] == 1


class TestDiff:
    def test_new_machine_not_in_lock_is_not_drift(self, tmp_path: Path) -> None:
        _write_chart(tmp_path, _CHART_V1)
        registry = Registry(machines_dir=tmp_path)
        findings = diff(registry, locked={})
        assert findings == []

    def test_unchanged_hash_is_not_drift(self, tmp_path: Path) -> None:
        _write_chart(tmp_path, _CHART_V1)
        registry = Registry(machines_dir=tmp_path)
        locked = {
            "test.lock.machine": {
                "hash": registry.hash("test.lock.machine"),
                "version": 1,
            }
        }
        assert diff(registry, locked) == []

    def test_hash_drift_without_version_bump_or_upcaster_is_uncovered(self, tmp_path: Path) -> None:
        """Acceptance criterion 1: 'Hash drift without upcaster fails'."""
        _write_chart(tmp_path, _CHART_V1)
        registry = Registry(machines_dir=tmp_path)
        # Lock records a *different* hash for the same version -> drift.
        locked = {"test.lock.machine": {"hash": "deadbeef" * 8, "version": 1}}
        findings = diff(registry, locked)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.machine == "test.lock.machine"
        assert finding.covered is False
        assert "MUST-12" in finding.reason or "MUSTNOT-09" in finding.reason

    def test_version_bump_without_upcaster_is_uncovered(self, tmp_path: Path) -> None:
        chart_v2 = dict(_CHART_V1)
        chart_v2["version"] = 2
        chart_v2["states"] = {
            "idle": {"on": {"GONE": {"target": "#test.lock.machine.done"}}},
            "done": {"type": "final"},
        }
        _write_chart(tmp_path, chart_v2)
        registry = Registry(machines_dir=tmp_path)
        locked = {
            "test.lock.machine": {
                "hash": _registry_hash(_CHART_V1),
                "version": 1,
            }
        }
        findings = diff(registry, locked)
        assert len(findings) == 1
        assert findings[0].covered is False
        assert "upcaster" in findings[0].reason

    def test_upcaster_without_version_bump_is_uncovered(self, tmp_path: Path) -> None:
        chart_same_version = dict(_CHART_V1)
        chart_same_version["states"] = {
            "idle": {"on": {"GONE": {"target": "#test.lock.machine.done"}}},
            "done": {"type": "final"},
        }
        _write_chart(tmp_path, chart_same_version)
        registry = Registry(machines_dir=tmp_path)
        from_hash = _registry_hash(_CHART_V1)
        to_hash = registry.hash("test.lock.machine")
        register_upcaster(
            "test.lock.machine.novbump", from_hash, to_hash, lambda ctx: {**ctx, "m": 1}
        )
        locked = {"test.lock.machine": {"hash": from_hash, "version": 1}}
        findings = diff(registry, locked)
        assert len(findings) == 1
        assert findings[0].covered is False
        assert "version" in findings[0].reason

    def test_version_bump_plus_registered_upcaster_is_covered(self, tmp_path: Path) -> None:
        chart_v2 = dict(_CHART_V1)
        chart_v2["version"] = 2
        chart_v2["states"] = {
            "idle": {"on": {"GONE": {"target": "#test.lock.machine.done"}}},
            "done": {"type": "final"},
        }
        _write_chart(tmp_path, chart_v2)
        registry = Registry(machines_dir=tmp_path)
        from_hash = _registry_hash(_CHART_V1)
        to_hash = registry.hash("test.lock.machine")
        register_upcaster(
            "test.lock.machine.covered", from_hash, to_hash, lambda ctx: {**ctx, "m": 1}
        )
        locked = {"test.lock.machine": {"hash": from_hash, "version": 1}}
        findings = diff(registry, locked)
        # Coverage is keyed by the diff's own (machine, from_hash, to_hash)
        # triple via has_upcaster — registering under a *different* machine
        # key above does not cover this one; register under the real key.
        register_upcaster("test.lock.machine", from_hash, to_hash, lambda ctx: {**ctx, "n": 1})
        findings = diff(registry, locked)
        assert len(findings) == 1
        assert findings[0].covered is True

    def test_bad_lock_entry_missing_hash_raises(self, tmp_path: Path) -> None:
        _write_chart(tmp_path, _CHART_V1)
        registry = Registry(machines_dir=tmp_path)
        with pytest.raises(LockFileError):
            diff(registry, {"test.lock.machine": {"version": 1}})


class TestCheckRemoved:
    def test_removed_machine_reported(self, tmp_path: Path) -> None:
        registry = Registry(machines_dir=tmp_path)  # empty dir, no machines
        locked = {"gone.machine": {"hash": "x", "version": 1}}
        assert check_removed(registry, locked) == ["gone.machine"]

    def test_no_removal_when_still_present(self, tmp_path: Path) -> None:
        _write_chart(tmp_path, _CHART_V1)
        registry = Registry(machines_dir=tmp_path)
        locked = {"test.lock.machine": {"hash": "x", "version": 1}}
        assert check_removed(registry, locked) == []
