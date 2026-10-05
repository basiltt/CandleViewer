"""E08-T06 "Every alert has a runbook entry": ingestion alerts <-> docs/ops/ingestion.md.

Both directions: every alert in infra/prometheus/alerts/ingestion.yml has an
anchored section in the runbook, and every `alert-*` anchor in the runbook
names an alert that exists.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "infra" / "prometheus" / "alerts" / "ingestion.yml"
RUNBOOK = ROOT / "docs" / "ops" / "ingestion.md"
#: Ticket "Alert rules" bullets -> the rule that implements each.
REQUIRED = {
    "topic staleness": "IngestionTopicStale",
    "book resync rate": "IngestionBookResyncRateHigh",
    "unrecovered trade gap": "IngestionTradeGapUnrecovered",
    "rate-limit headroom exhausted": "IngestionRateLimitHeadroomExhausted",
    "queue-full on never-drop": "IngestionNeverDropQueueFull",
    "stopped reporting (meta)": "IngestionStoppedReporting",
}


def _rules(path: Path = RULES) -> list[dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [r for g in doc["groups"] for r in g["rules"] if "alert" in r]


def cross_check(rules: list[dict[str, Any]], runbook: str) -> list[str]:
    errs: list[str] = []
    anchors = set(re.findall(r'<a id="alert-([a-z0-9]+)"></a>', runbook))
    names = {r["alert"].lower(): r["alert"] for r in rules}
    for low, name in sorted(names.items()):
        if low not in anchors:
            errs.append(f"alert {name} has no runbook entry")
        elif f"## {name}" not in runbook:
            errs.append(f"runbook entry for {name} has no '## {name}' heading")
    for a in sorted(anchors - set(names)):
        errs.append(f"runbook entry alert-{a} describes an alert that does not exist")
    return errs


def test_ingestion_alerts_and_runbook_match_both_ways() -> None:
    assert cross_check(_rules(), RUNBOOK.read_text(encoding="utf-8")) == []


def test_cross_check_flags_missing_entry_and_orphan_entry() -> None:
    rules = [{"alert": "IngestionTopicStale"}, {"alert": "NewAlert"}]
    text = '<a id="alert-ingestiontopicstale"></a>\n## IngestionTopicStale\n<a id="alert-ghost"></a>'
    assert cross_check(rules, text) == [
        "alert NewAlert has no runbook entry",
        "runbook entry alert-ghost describes an alert that does not exist",
    ]


def test_every_ticket_alert_class_is_implemented() -> None:
    names = {r["alert"] for r in _rules()}
    assert set(REQUIRED.values()) <= names


def test_each_entry_lists_three_first_actions() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for r in _rules():
        section = text.split(f"## {r['alert']}", 1)[1].split("\n## ", 1)[0]
        steps = re.findall(r"^\d\. ", section, re.MULTILINE)
        assert len(steps) == 3, r["alert"]


def test_alert_text_is_complete_sentences_and_no_identifiers() -> None:
    for r in _rules():
        summary = r["annotations"]["summary"]
        assert summary[0].isupper() and summary.rstrip().endswith("."), r["alert"]
        assert "uid" not in r["expr"] and "uid" not in summary.lower()


def test_ingestion_rules_pass_the_runbook_link_gate() -> None:
    spec = importlib.util.spec_from_file_location(
        "check_alert_rules", ROOT / "infra" / "alertmanager" / "check_alert_rules.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.check() == []
