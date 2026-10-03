"""Meta-tests for tools/a11y/gates.py (E47-T02): injected defect fails, clean passes."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import gates


def _report(impact: str = "serious") -> dict:
    return {
        "screens": {
            "SCR-060": {
                "violations": [
                    {
                        "id": "color-contrast",
                        "impact": impact,
                        "nodes": [{"target": ["#buy"]}],
                    }
                ]
            }
        }
    }


def test_axe_new_serious_violation_names_screen_rule_node() -> None:
    msgs = gates.check_axe(_report(), {"entries": []})
    assert len(msgs) == 1
    assert "SCR-060" in msgs[0] and "color-contrast" in msgs[0] and "#buy" in msgs[0]


def test_axe_moderate_ignored_and_baselined_allowed() -> None:
    assert gates.check_axe(_report("moderate"), {"entries": []}) == []
    base = {
        "entries": [
            {"fingerprint": "SCR-060|color-contrast|#buy", "finding": "A11Y-F001"}
        ]
    }
    assert gates.check_axe(_report(), base) == []


def test_baseline_entry_without_finding_id_is_rejected() -> None:
    assert gates.check_baseline_entries({"entries": [{"fingerprint": "x"}]})
    assert not gates.check_baseline_entries(
        {"entries": [{"fingerprint": "x", "finding": "A11Y-F2"}]}
    )


def test_lighthouse_below_floor_is_violation_but_missing_is_infra() -> None:
    assert gates.check_lighthouse({"SCR-020": 0.97}) == []
    assert "SCR-063" in gates.check_lighthouse({"SCR-063": 0.9})[0]
    with pytest.raises(gates.InfraError):
        gates.check_lighthouse({})
    with pytest.raises(gates.InfraError):
        gates.check_lighthouse({"SCR-020": None})


def test_flash_five_hz_fails_and_names_component() -> None:
    fps = 30
    strobe = [1.0 if (i // 3) % 2 == 0 else 0.0 for i in range(fps)]  # 5 Hz
    calm = [0.5] * fps
    msgs = gates.check_flash(
        {"fps": fps, "components": {"heatmap": calm, "bubbles": strobe}}
    )
    assert len(msgs) == 1 and "bubbles" in msgs[0]


def test_flash_empty_capture_is_infra() -> None:
    with pytest.raises(gates.InfraError):
        gates.check_flash({"fps": 30, "components": {}})


def test_keyboard_trap_and_mouse_events_fail() -> None:
    ok = {"mouseEvents": 0, "steps": [{"name": "submit order", "ok": True}]}
    assert gates.check_keyboard(ok) == []
    bad = {"mouseEvents": 2, "steps": [{"name": "switch symbol", "ok": False}]}
    assert len(gates.check_keyboard(bad)) == 2


def test_tree_snapshot_diff_reports_change(tmp_path: Path) -> None:
    snap, act = tmp_path / "s", tmp_path / "a"
    snap.mkdir()
    act.mkdir()
    (snap / "SCR-020.txt").write_text("main\n  heading 'Chart'\n", encoding="utf-8")
    (act / "SCR-020.txt").write_text("main\n", encoding="utf-8")
    msgs = gates.check_tree(str(snap), str(act))
    assert "SCR-020" in msgs[0] and "heading" in msgs[0]
    (act / "SCR-020.txt").write_text("main\n  heading 'Chart'\n", encoding="utf-8")
    assert gates.check_tree(str(snap), str(act)) == []


def test_cli_exit_codes_distinguish_violation_from_infra(tmp_path: Path) -> None:
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps(_report()), encoding="utf-8")
    base = tmp_path / "b.json"
    base.write_text('{"entries": []}', encoding="utf-8")
    assert (
        gates.main(["axe", str(rep), "--baseline", str(base)]) == gates.EXIT_VIOLATION
    )
    assert (
        gates.main(["axe", str(tmp_path / "nope.json"), "--baseline", str(base)])
        == gates.EXIT_INFRA
    )
    rep.write_text(json.dumps({"screens": {}}), encoding="utf-8")
    assert gates.main(["axe", str(rep), "--baseline", str(base)]) == gates.EXIT_OK


def test_break_glass_waives_infra_only_and_is_time_limited() -> None:
    now = dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc)
    soon = (now + dt.timedelta(hours=2)).isoformat()
    far = (now + dt.timedelta(days=3)).isoformat()
    assert gates.infra_waiver_active({"CV_A11Y_INFRA_WAIVER_UNTIL": soon}, now)
    assert not gates.infra_waiver_active({"CV_A11Y_INFRA_WAIVER_UNTIL": far}, now)
    assert not gates.infra_waiver_active({}, now)


def test_waiver_does_not_hide_violation(tmp_path: Path, monkeypatch) -> None:
    until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
    monkeypatch.setenv("CV_A11Y_INFRA_WAIVER_UNTIL", until)
    rep, base = tmp_path / "r.json", tmp_path / "b.json"
    rep.write_text(json.dumps(_report()), encoding="utf-8")
    base.write_text('{"entries": []}', encoding="utf-8")
    assert (
        gates.main(["axe", str(rep), "--baseline", str(base)]) == gates.EXIT_VIOLATION
    )
    assert (
        gates.main(["axe", str(tmp_path / "x.json"), "--baseline", str(base)])
        == gates.EXIT_OK
    )
