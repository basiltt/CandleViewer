"""Tests for tools/statechart/event_coverage.py (E50-T05, MUST-10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.statechart.event_coverage import (
    check,
    load_descriptors,
    main,
    scan_source,
)

CHART = {"id": "order", "on": {"KILL": {}}, "states": {"a": {"on": {"ORDER_FILLED": {}}}}}


def _machines(tmp_path: Path) -> Path:
    d = tmp_path / "machines"
    d.mkdir()
    (d / "B01.order.machine.json").write_text(json.dumps(CHART), encoding="utf-8")
    return d


def test_descriptors_collect_nested_events(tmp_path: Path) -> None:
    assert load_descriptors(_machines(tmp_path)) == {"order": {"KILL", "ORDER_FILLED"}}


def test_unknown_event_fails_naming_the_site(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    src = "async def f(gw):\n    await gw.send('order:1', 'ORDER_FILED')\n"
    findings = check(scan_source(src, "svc/x.py"), desc)
    assert len(findings) == 1
    assert "svc/x.py:2" in findings[0] and "ORDER_FILED" in findings[0]


def test_known_event_forms_pass(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    src = (
        "gw.send('order', 'ORDER_FILLED')\n"
        "gw.send('order:2', {'type': 'KILL'})\n"
        "gw.send_threadsafe('order', Event('KILL'))\n"
    )
    assert check(scan_source(src, "x.py"), desc) == []


def test_unknown_machine_and_dynamic_event(tmp_path: Path) -> None:
    desc = load_descriptors(_machines(tmp_path))
    src = "gw.send('ghost', 'KILL')\ngw.send('order', name)\n"
    findings = check(scan_source(src, "x.py"), desc)
    assert len(findings) == 1 and "unknown machine 'ghost'" in findings[0]


def test_main_exit_codes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    m = _machines(tmp_path)
    scan = tmp_path / "src"
    scan.mkdir()
    (scan / "ok.py").write_text("gw.send('order', 'KILL')\n", encoding="utf-8")
    assert main(["--machines", str(m), "--scan", str(scan)]) == 0
    (scan / "bad.py").write_text("gw.send('order', 'ORDER_FILED')\n", encoding="utf-8")
    assert main(["--machines", str(m), "--scan", str(scan)]) == 1
    assert "bad.py:1" in capsys.readouterr().out
    assert main(["--machines", str(tmp_path / "nope"), "--scan", str(scan)]) == 2


def test_real_repo_is_clean() -> None:
    assert main([]) == 0
