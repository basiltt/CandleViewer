"""tests/lint_statecharts/test_kill_frozen_exception.py — #1650.

CV-LINT-KILL-ANCESTOR §1.3c SL-protection exception (owner decision #1778
item X): a chart may satisfy C-04 with a non-terminal KILL target named
`frozen` only when tagged `meta["cv:slProtection"] = true`, and that `frozen`
state may not invoke, time out, nest, or leave except on a recovery arm.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import lint_statecharts as lint

B08 = (
    REPO_ROOT / "services/api/candleviewer/statechart/machines/B08.position_protection.machine.json"
)


def _chart(tagged: bool = True) -> dict[str, Any]:
    chart: dict[str, Any] = {
        "id": "position_protection",
        "strictConfig": True,
        "onUnhandled": "defer",
        "maxIterations": 500,
        "on": {"KILL": {"target": "#position_protection.frozen"}},
        "initial": "working",
        "states": {
            "working": {"invoke": {"id": "w", "src": "svc", "onDone": {"target": "#position_protection.frozen"}}},
            "frozen": {"entry": ["audit_kill"], "on": {"LOOSEN_SL": {"actions": ["audit"]}}},
        },
    }
    if tagged:
        chart["meta"] = {"cv:slProtection": True}
    return chart


def _kill(findings: list[lint.Finding]) -> list[lint.Finding]:
    return [f for f in findings if f.rule == "CV-LINT-KILL-ANCESTOR"]


def test_kill_frozen_tagged_chart_passes() -> None:
    assert _kill(lint.rule_kill_ancestor("x.json", _chart())) == []


def test_kill_frozen_untagged_chart_is_rejected() -> None:
    found = _kill(lint.rule_kill_ancestor("x.json", _chart(tagged=False)))
    assert len(found) == 1
    assert "cv:slProtection" in found[0].message


def test_kill_frozen_tag_false_is_rejected() -> None:
    chart = _chart()
    chart["meta"] = {"cv:slProtection": "true"}  # not the boolean true
    assert len(_kill(lint.rule_kill_ancestor("x.json", chart))) == 1


def test_kill_frozen_with_invoke_is_rejected() -> None:
    chart = _chart()
    chart["states"]["frozen"]["invoke"] = {"id": "c", "src": "cancel_sl"}
    assert any("invoke" in f.message for f in _kill(lint.rule_kill_ancestor("x.json", chart)))


def test_kill_frozen_leaving_on_amend_is_rejected() -> None:
    chart = _chart()
    chart["states"]["frozen"]["on"]["TIGHTEN_SL"] = {"target": "#position_protection.working"}
    found = _kill(lint.rule_kill_ancestor("x.json", chart))
    assert any("TIGHTEN_SL" in f.message for f in found)


def test_kill_frozen_recovery_arm_is_allowed() -> None:
    chart = _chart()
    chart["states"]["frozen"]["on"]["RECONCILED"] = {"target": "#position_protection.working"}
    assert _kill(lint.rule_kill_ancestor("x.json", chart)) == []


def test_kill_frozen_committed_b08_passes_and_untagged_copy_fails() -> None:
    chart = json.loads(B08.read_text(encoding="utf-8"))
    assert chart["meta"]["cv:slProtection"] is True
    assert _kill(lint.rule_kill_ancestor(str(B08), chart)) == []
    untagged = copy.deepcopy(chart)
    del untagged["meta"]
    assert len(_kill(lint.rule_kill_ancestor(str(B08), untagged))) == 1
    # KILL in the `sl` region is audit-only: no attach path is ever abandoned.
    assert "target" not in chart["states"]["sl"]["on"]["KILL"]


# --- review #2133: the two synthetic evasions + allowlist ---------------------------


def test_kill_untagged_copy_with_paused_is_rejected() -> None:
    """Evasion 1: untagged B8 copy whose KILL lands in a renamed non-final state."""
    chart = json.loads(B08.read_text(encoding="utf-8"))
    del chart["meta"]
    lock = chart["states"]["amend_lock"]["states"]
    lock["paused"] = lock.pop("frozen")
    lock["open"]["on"]["KILL"]["target"] = "#position_protection.amend_lock.paused"
    found = _kill(lint.rule_kill_ancestor(str(B08), chart))
    assert any("not a final state" in f.message for f in found)


def test_kill_tagged_chart_pointing_elsewhere_is_rejected() -> None:
    """Evasion 2: tagged + allowlisted chart whose KILL targets a non-`frozen` state."""
    chart = json.loads(B08.read_text(encoding="utf-8"))
    chart["states"]["amend_lock"]["states"]["open"]["on"]["KILL"][
        "target"
    ] = "#position_protection.sl.protected"
    found = _kill(lint.rule_kill_ancestor(str(B08), chart))
    assert any("'#position_protection.sl.protected'" in f.message for f in found)


def test_kill_tagged_frozen_on_non_allowlisted_chart_is_rejected() -> None:
    chart = _chart()
    chart["id"] = "trade_group"
    chart["on"]["KILL"]["target"] = "#trade_group.frozen"
    chart["states"]["working"]["invoke"]["onDone"]["target"] = "#trade_group.frozen"
    assert len(_kill(lint.rule_kill_ancestor("x.json", chart))) == 1


def test_kill_final_target_needs_no_exception() -> None:
    chart = _chart(tagged=False)
    chart["id"] = "anything"
    chart["on"]["KILL"]["target"] = "#anything.frozen"
    chart["states"]["working"]["invoke"]["onDone"]["target"] = "#anything.frozen"
    chart["states"]["frozen"] = {"type": "final"}
    assert _kill(lint.rule_kill_ancestor("x.json", chart)) == []
