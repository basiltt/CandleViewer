"""Unit tests for tools/ci/quality_gates.py (E02-T10 threshold-guard, C-9.4).

Covers: decrease (fails), increase (passes), unchanged (passes), missing
package in new file (ignored -- not this guard's job), decrease with an
amendment key (passes), brand-new file (no base to compare -- passes),
bundleSize.limitBytes ceiling semantics (a smaller limit is a tightening).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.quality_gates import diff_thresholds


def _cfg(services_lines: float, apps_web_lines: float | None = None, amendment: str | None = None):
    apps_web = {"lines": apps_web_lines if apps_web_lines is not None else 80.0, "branches": 70.0}
    if amendment:
        apps_web["amendment"] = amendment
    return {
        "coverage": {
            "services/api": {"lines": services_lines, "branches": 75.0},
            "apps/web": apps_web,
        },
        "bundleSize": {
            "apps/web": {"limitBytes": 8_388_608, "gzip": True, "regressionPct": 5.0},
        },
    }


def test_decrease_without_amendment_fails() -> None:
    old = _cfg(85.0)
    new = _cfg(80.0)
    violations = diff_thresholds(old, new)
    assert any("services/api" in v and "C-9.4" in v for v in violations)


def test_increase_passes() -> None:
    old = _cfg(85.0)
    new = _cfg(90.0)
    assert diff_thresholds(old, new) == []


def test_unchanged_passes() -> None:
    old = _cfg(85.0)
    new = _cfg(85.0)
    assert diff_thresholds(old, new) == []


def test_decrease_with_amendment_passes() -> None:
    old = _cfg(85.0, apps_web_lines=80.0)
    new = _cfg(85.0, apps_web_lines=70.0, amendment="C-16 amendment #7")
    assert diff_thresholds(old, new) == []


def test_missing_package_in_new_file_is_ignored() -> None:
    old = _cfg(85.0)
    new = {"coverage": {"apps/web": {"lines": 80.0, "branches": 70.0}}, "bundleSize": {}}
    assert diff_thresholds(old, new) == []


def test_brand_new_file_has_no_base_to_compare() -> None:
    new = _cfg(85.0)
    assert diff_thresholds(None, new) == []


def test_bundle_size_limit_ceiling_shrink_is_a_tightening_not_a_violation() -> None:
    old = _cfg(85.0)
    new = _cfg(85.0)
    new["bundleSize"]["apps/web"]["limitBytes"] = 4_000_000
    assert diff_thresholds(old, new) == []


def test_bundle_size_limit_growth_without_amendment_fails() -> None:
    old = _cfg(85.0)
    new = _cfg(85.0)
    new["bundleSize"]["apps/web"]["limitBytes"] = 20_000_000
    violations = diff_thresholds(old, new)
    assert any("limitBytes" in v for v in violations)
