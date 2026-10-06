"""tests/unit/statechart/test_xstate_gate_env_skip.py (#1928, E50-C17 #579).

The xstate nightly gate must be environment-independent:

* ``docs/research/xstate/gate/_paths.py`` resolves the upstream source tree
  from ``XSTATE_SRC`` -> the CI ``_upstream`` checkout -> a local ``_ref``
  checkout (only if it exists), never a hard-coded home directory;
* a check script that needs an upstream dev venv it cannot find exits 77,
  which ``run_gate.classify_exit`` records as ``SKIP-ENV`` ("skipped
  (environment)"), and ``tools/statechart/nightly_gate.py`` never counts it
  as a regression (nor as a fix).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GATE_DIR = _REPO_ROOT / "docs" / "research" / "xstate" / "gate"
for _p in (_REPO_ROOT, _GATE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# These live outside the `candleviewer` package (docs/research + tools), so they
# are loaded dynamically; mypy sees them as plain ModuleType handles.
_paths: ModuleType = importlib.import_module("_paths")
run_gate: ModuleType = importlib.import_module("run_gate")
nightly_gate: ModuleType = importlib.import_module("tools.statechart.nightly_gate")


def test_classify_exit_zero_is_pass() -> None:
    assert run_gate.classify_exit(0, "", "real FAIL")[0] == run_gate.PASS


def test_classify_exit_one_is_fail_with_given_detail() -> None:
    assert run_gate.classify_exit(1, "", "real FAIL") == (run_gate.FAIL, "real FAIL")


def test_classify_exit_skip_env_code_is_skipped_environment() -> None:
    out = "noise\nskipped (environment): requires the upstream dev venv X\n"
    status, detail = run_gate.classify_exit(_paths.SKIP_ENV_EXIT, out, "real FAIL")
    assert status == run_gate.SKIP_ENV
    assert detail.startswith("skipped (environment)")


def test_classify_exit_skip_env_reason_is_the_skip_line_not_trailing_noise() -> None:
    out = "skipped (environment): requires the upstream dev venv X\nlater log line\n"
    _, detail = run_gate.classify_exit(_paths.SKIP_ENV_EXIT, out, "real FAIL")
    assert detail == "skipped (environment): requires the upstream dev venv X"


def test_classify_exit_other_code_is_error() -> None:
    status, detail = run_gate.classify_exit(2, "FileNotFoundError: x", "real FAIL")
    assert status == run_gate.ERROR
    assert "exit 2" in detail


def test_skip_env_status_string_agrees_between_gate_and_verdict() -> None:
    assert run_gate.SKIP_ENV == nightly_gate.SKIP_ENV


def _result(*checks: tuple[str, str, str]) -> dict[str, Any]:
    return {"checks": [{"kind": k, "id": i, "status": s} for k, i, s in checks]}


def test_nightly_gate_skip_env_is_not_a_regression() -> None:
    baseline = _result(("verifyM3", "142", "PASS"))
    result = _result(("verifyM3", "142", "SKIP-ENV"))
    assert nightly_gate.regressions(result, baseline) == []
    assert nightly_gate.skipped_env(result) == ["verifyM3:142"]


def test_nightly_gate_skip_env_is_not_counted_as_fixed() -> None:
    baseline = _result(("verifyM", "LC-52", "FAIL"))
    result = _result(("verifyM", "LC-52", "SKIP-ENV"))
    assert nightly_gate.fixed(result, baseline) == []


def test_nightly_gate_real_fail_is_still_a_regression() -> None:
    baseline = _result(("verify", "LC-39", "PASS"))
    result = _result(("verify", "LC-39", "FAIL"))
    assert nightly_gate.regressions(result, baseline) == ["verify:LC-39"]


def test_render_lists_skipped_environment_section() -> None:
    report = nightly_gate.render(
        mode="pinned",
        date="2026-10-07",
        result={},
        new=[],
        gone=[],
        bench_ok=None,
        p99=None,
        threshold=100.0,
        skipped=["verifyM3:142"],
    )
    assert "Skipped (environment)" in report
    assert "- verifyM3:142" in report
    assert "**GREEN**" in report


def test_resolve_xstate_src_env_var_wins(tmp_path: Path) -> None:
    ci, ref = tmp_path / "ci", tmp_path / "ref"
    ci.mkdir()
    ref.mkdir()
    got = _paths.resolve_xstate_src({"XSTATE_SRC": str(tmp_path / "x")}, ci, ref)
    assert got == tmp_path / "x"


def test_resolve_xstate_src_prefers_ci_upstream(tmp_path: Path) -> None:
    ci, ref = tmp_path / "ci", tmp_path / "ref"
    ci.mkdir()
    ref.mkdir()
    assert _paths.resolve_xstate_src({}, ci, ref) == ci


def test_resolve_xstate_src_local_ref_only_when_present(tmp_path: Path) -> None:
    ci, ref = tmp_path / "ci", tmp_path / "ref"
    assert _paths.resolve_xstate_src({}, ci, ref) == ci
    ref.mkdir()
    assert _paths.resolve_xstate_src({}, ci, ref) == ref


def test_ci_upstream_default_matches_workflow_checkout_path() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "xstate-nightly.yml").read_text(
        encoding="utf-8"
    )
    assert "path: _upstream" in workflow
    assert _paths.CI_UPSTREAM == _REPO_ROOT / "_upstream"


def test_upstream_dev_python_missing_venv_exits_skip_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _paths.upstream_dev_python(".venv-main", tmp_path)
    assert exc.value.code == _paths.SKIP_ENV_EXIT
    assert "skipped (environment)" in capsys.readouterr().out


def test_upstream_dev_python_finds_posix_layout(tmp_path: Path) -> None:
    py = tmp_path / ".venv-main" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    assert _paths.upstream_dev_python(".venv-main", tmp_path) == str(py)


def test_no_gate_script_hard_codes_a_home_directory() -> None:
    xs = _REPO_ROOT / "docs" / "research" / "xstate"
    scripts = [*xs.glob("issues/**/*.py"), xs / "bench" / "bench_c_timers_v2.py"]
    offenders = []
    for script in scripts:
        for n, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if ('"C:' in code or "'C:" in code) and "Users" in code:
                offenders.append(f"{script.relative_to(xs)}:{n}")
    assert offenders == []
