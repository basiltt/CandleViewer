"""E50-T56: CV-C68 payload-only cv_re_mint + CV-LINT-REMINT."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from xstate_statemachine import is_system_event
from xstate_statemachine.events import _EngineDone, _EngineError

from candleviewer.statechart.gateway import ReMintForbidden, cv_re_mint

REPO = Path(__file__).resolve().parents[4]


def _lint() -> object:
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import lint_statecharts
    finally:
        sys.path.pop(0)
    return lint_statecharts


def _done() -> object:
    return _EngineDone("done.invoke.x", {"a": 1}, "x")


@pytest.mark.parametrize("field", ["type", "src", "bogus"])
def test_cv_re_mint_override_refused(field: str) -> None:
    with pytest.raises(ReMintForbidden):
        cv_re_mint(_done(), **{field: "X"})


def test_cv_re_mint_data_keeps_type_and_src() -> None:
    ev = _done()
    out = cv_re_mint(ev, data={"b": 2})
    assert out.type == ev.type
    assert out.src == ev.src
    assert out.data == {"b": 2}
    assert is_system_event(out)


def test_cv_re_mint_error_field_on_error_event() -> None:
    ev = _EngineError("error.platform.x", "boom", "x")
    out = cv_re_mint(ev, error="redacted")
    assert out.error == "redacted"
    assert (out.type, out.src) == (ev.type, ev.src)
    assert is_system_event(out)


def test_lint_remint_bans_bare_call_outside_gateway() -> None:
    lint = _lint()
    tree = ast.parse("events.re_mint(ev, data=1)")
    rules = [f.rule for f in lint.rule_remint("services/api/candleviewer/x.py", tree)]
    assert rules == ["CV-LINT-REMINT"]


def test_lint_remint_allows_gateway_but_not_type_override() -> None:
    lint = _lint()
    ok = ast.parse("events.re_mint(ev, data=1)")
    assert lint.rule_remint("a/gateway.py", ok) == []
    bad = ast.parse("events.re_mint(ev, type='X')")
    assert [f.rule for f in lint.rule_remint("a/gateway.py", bad)] == ["CV-LINT-REMINT"]


def test_real_gateway_passes_lint() -> None:
    lint = _lint()
    path = REPO / "services/api/candleviewer/statechart/gateway.py"
    assert lint.lint_python_file(path) == []
