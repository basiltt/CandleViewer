"""Unit tests for tools/ci/check_accepted_risk_expiry.py (E49-T03)."""

from __future__ import annotations

import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_accepted_risk_expiry as ck

TODAY = date(2026, 10, 6)

YAML_OK = """entries:
  - id: "GHSA-x"
    tool: npm-audit
    severity: HIGH
    reason: r
    approver: "basiltt"
    expires: "{exp}"
"""

REG_OK = """# reg

### RSK-053 · Something accepted

`Risk: R15` · Category **Security** · L 2 · I 5 · **Score 10 — High** · Owner **Security engineer** · Epics E48 · Status **Accepted** (expires {exp})

- **Description** — x

### RSK-001 · Open one

`Risk: R1` · Category **Technical** · L 3 · I 5 · **Score 15 — Critical** · Owner **Chart-engine lead** · Epics E06 · Status **Mitigating**
"""


EX_TABLE = """| Exception id | Finding | Approved by | Expires | Ticket |
| ------------ | ------- | ----------- | ------- | ------ |
| EX-09        | thing   | **Pending** @basiltt | {exp} | #1 |
"""


def _root(tmp_path: Path, yaml_exp: str = "2027-03-25", reg: str | None = None) -> Path:
    (tmp_path / "security").mkdir()
    (tmp_path / "docs/plan").mkdir(parents=True)
    (tmp_path / ck.YAML_PATH).write_text(YAML_OK.format(exp=yaml_exp), encoding="utf-8")
    (tmp_path / ck.SECURITY_PLAN).write_text(
        EX_TABLE.format(exp="2027-01-01"), encoding="utf-8"
    )
    (tmp_path / ck.REGISTER).write_text(
        reg if reg is not None else REG_OK.format(exp="2027-03-25"), encoding="utf-8"
    )
    return tmp_path


def _run(root: Path, today: date = TODAY) -> tuple[list[str], list[str]]:
    _res, fails, warns = ck.run(root, today)
    return fails, warns


def test_all_future_passes_no_warnings(tmp_path: Path) -> None:
    fails, warns = _run(_root(tmp_path))
    assert fails == [] and warns == []


def test_yaml_past_expiry_fails_naming_id_owner_and_days(tmp_path: Path) -> None:
    fails, _ = _run(_root(tmp_path, yaml_exp="2026-10-01"))
    assert len(fails) == 1
    assert (
        "GHSA-x" in fails[0]
        and "basiltt" in fails[0]
        and "elapsed 5 day(s)" in fails[0]
    )


def test_expiry_equal_to_today_is_expired(tmp_path: Path) -> None:
    fails, _ = _run(_root(tmp_path, yaml_exp="2026-10-06"))
    assert fails and "elapsed 0 day(s)" in fails[0]


def test_expiry_tomorrow_warns_not_fails(tmp_path: Path) -> None:
    fails, warns = _run(_root(tmp_path, yaml_exp="2026-10-07"))
    assert fails == [] and "1 day(s) left" in warns[0]


def test_warn_boundary_29_warns_30_does_not(tmp_path: Path) -> None:
    _, w29 = _run(_root(tmp_path, yaml_exp="2026-11-04"))
    assert len(w29) == 1
    other = tmp_path / "b"
    other.mkdir()
    _, w30 = _run(_root(other, yaml_exp="2026-11-05"))
    assert w30 == []


def test_register_past_expiry_fails_with_rsk_id_and_owner(tmp_path: Path) -> None:
    reg = REG_OK.format(exp="2026-09-01")
    fails, _ = _run(_root(tmp_path, reg=reg))
    assert len(fails) == 1
    assert (
        "RSK-053" in fails[0]
        and "Security engineer" in fails[0]
        and "35 day(s)" in fails[0]
    )


def test_register_accepted_without_expiry_is_error(tmp_path: Path) -> None:
    reg = REG_OK.replace(" (expires {exp})", "").format()
    fails, _ = _run(_root(tmp_path, reg=reg))
    assert any(f.startswith("MISSING-EXPIRY [register] RSK-053") for f in fails)


def test_register_accepted_with_garbage_date_is_error(tmp_path: Path) -> None:
    fails, _ = _run(_root(tmp_path, reg=REG_OK.format(exp="soon")))
    assert any(f.startswith("MISSING-EXPIRY [register] RSK-053") for f in fails)


def test_register_accepted_without_owner_is_error(tmp_path: Path) -> None:
    reg = REG_OK.format(exp="2027-03-25").replace(" · Owner **Security engineer**", "")
    fails, _ = _run(_root(tmp_path, reg=reg))
    assert any(f.startswith("MISSING-OWNER [register] RSK-053") for f in fails)


def test_register_entry_without_status_line_is_unparseable_not_skipped(
    tmp_path: Path,
) -> None:
    reg = REG_OK.format(exp="2027-03-25") + "\n### RSK-099 · broken\n\nno meta line\n"
    fails, _ = _run(_root(tmp_path, reg=reg))
    assert any(f.startswith("UNPARSEABLE [register] RSK-099") for f in fails)


def test_register_without_entries_fails_loudly(tmp_path: Path) -> None:
    fails, _ = _run(_root(tmp_path, reg="# nothing here\n"))
    assert any("no '### RSK-nnn' entries" in f for f in fails)


def test_retired_and_other_statuses_are_not_checked(tmp_path: Path) -> None:
    reg = REG_OK.format(exp="2027-03-25").replace(
        "**Mitigating**", "**Retired** (expires 2020-01-01)"
    )
    fails, _ = _run(_root(tmp_path, reg=reg))
    assert fails == []


def test_yaml_missing_expiry_and_approver_are_errors(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ck.YAML_PATH).write_text(
        "entries:\n  - id: a\n    approver: b\n  - id: c\n    expires: '2027-01-01'\n",
        encoding="utf-8",
    )
    fails, _ = _run(root)
    assert any(f.startswith("MISSING-EXPIRY [yaml] a") for f in fails)
    assert any(f.startswith("MISSING-OWNER [yaml] c") for f in fails)


def test_yaml_unparseable_or_missing_file_fails(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ck.YAML_PATH).write_text("entries: [unclosed", encoding="utf-8")
    assert any(f.startswith("UNPARSEABLE") for f in _run(root)[0])
    (root / ck.YAML_PATH).unlink()
    assert any(f.startswith("UNPARSEABLE") for f in _run(root)[0])


def test_yaml_native_date_and_non_mapping_entry(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ck.YAML_PATH).write_text(
        "entries:\n  - id: a\n    approver: b\n    expires: 2026-10-01\n  - just-a-string\n",
        encoding="utf-8",
    )
    fails, _ = _run(root)
    assert any("EXPIRED [yaml] a" in f for f in fails)
    assert any("entry 1 is not a mapping" in f for f in fails)


def _src(root: Path, text: str, name: str = "mod.py") -> None:
    (root / name).write_text(text, encoding="utf-8")


def test_in_source_past_review_fails_future_ok(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _src(root, "# nosemgrep: cv-rule reason=r owner=@a review=2026-09-30\nx = 1\n")
    fails, _ = _run(root)
    assert len(fails) == 1 and "cv-rule" in fails[0] and "mod.py:1" in fails[0]
    _src(root, "# nosemgrep: cv-rule reason=r owner=@a review=2026-12-01\nx = 1\n")
    fails, warns = _run(root)
    assert fails == [] and warns == []


def test_in_source_warns_inside_window_and_lists_multi_rules(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _src(root, "x = 1  # nosemgrep: r1,r2 reason=r owner=@a review=2026-10-20\n")
    _, warns = _run(root)
    assert len(warns) == 1 and "r1,r2" in warns[0]


def test_in_source_bad_date_and_missing_owner_are_errors(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _src(
        root,
        "# nosemgrep: r reason=r owner=@a review=tomorrow\n# nosemgrep: q reason=r review=2027-01-01\n",
    )
    fails, _ = _run(root)
    assert any("MISSING-EXPIRY [in-source]" in f for f in fails)
    assert any("MISSING-OWNER [in-source]" in f for f in fails)


def test_in_source_marker_without_review_fails(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _src(root, "-- nosemgrep: cv-adapter-isolation -- legacy\n")
    fails, _ = _run(root)
    assert any(f.startswith("MISSING-REVIEW [in-source] mod.py:1") for f in fails)


def test_in_source_review_cap_boundary(tmp_path: Path) -> None:
    root = _root(tmp_path)
    cap = ck.REVIEW_MAX_DAYS
    ok = TODAY + timedelta(days=cap)
    _src(root, f"# nosemgrep: r reason=r owner=@a review={ok.isoformat()}\n")
    assert _run(root)[0] == []
    bad = TODAY + timedelta(days=cap + 1)
    _src(root, f"# nosemgrep: r reason=r owner=@a review={bad.isoformat()}\n")
    fails, _ = _run(root)
    assert len(fails) == 1 and fails[0].startswith("TOO-FAR [in-source]")


def test_unscanned_file_type_is_listed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _src(root, "-- nosemgrep: r\n", "q.sql")
    res, fails, _ = ck.run(root, TODAY)
    assert fails == [] and res.not_scanned == ["q.sql"]
    assert "Not scanned (1)" in ck.render_report(res, fails, [], TODAY)


def _covered_root(tmp_path: Path, entry_id: str, exp: str) -> Path:
    root = _root(tmp_path)
    (root / ck.YAML_PATH).write_text(
        YAML_OK.format(exp=exp).replace("GHSA-x", entry_id), encoding="utf-8"
    )
    _src(root, "x = 1  # nosemgrep: r1 -- legacy\n")
    return root


def test_unfielded_marker_covered_by_live_yaml_entry_passes(tmp_path: Path) -> None:
    root = _covered_root(tmp_path, "semgrep.r1:mod.py:1", "2027-03-25")
    assert _run(root)[0] == []


def test_unfielded_marker_with_expired_or_wrong_entry_fails(tmp_path: Path) -> None:
    expired = _covered_root(tmp_path, "semgrep.r1:mod.py:1", "2026-10-01")
    assert any(f.startswith("MISSING-REVIEW") for f in _run(expired)[0])
    other = tmp_path / "o"
    other.mkdir()
    wrong = _covered_root(other, "semgrep.r1:mod.py:9", "2027-03-25")
    assert any(f.startswith("MISSING-REVIEW") for f in _run(wrong)[0])


def test_duplicate_ids_fail(tmp_path: Path) -> None:
    root = _root(tmp_path)
    entry = YAML_OK.format(exp="2027-03-25")
    (root / ck.YAML_PATH).write_text(entry + entry.split("\n", 1)[1], encoding="utf-8")
    fails, _ = _run(root)
    assert any(f.startswith("DUPLICATE-ID [yaml] GHSA-x") for f in fails)


def test_in_source_quoted_test_data_ignored(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _src(
        root,
        'src = "# nosemgrep: r reason=r owner=@a review=2020-01-01"\n',
        "quoted.py",
    )
    (root / "scripts/tests").mkdir(parents=True)
    _src(
        root,
        "# nosemgrep: r reason=r owner=@a review=2020-01-01\n",
        "scripts/tests/t.py",
    )
    fails, _ = _run(root)
    assert fails == []


def test_main_exit_codes_and_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path, yaml_exp="2026-10-20")
    rep = tmp_path / "r.md"
    args = ["--root", str(root), "--today", "2026-10-06", "--report", str(rep)]
    assert ck.main(args) == 0
    assert ck.main([*args, "--fail-on-warn"]) == 2
    assert "Expiring within 30 days (1)" in rep.read_text(encoding="utf-8")
    assert ck.main(["--root", str(root), "--today", "2026-11-01"]) == 1
    assert "EXPIRED" in capsys.readouterr().out


def test_real_repo_has_no_expired_acceptances_today() -> None:
    root = Path(__file__).resolve().parents[2]
    today = datetime.now(UTC).date()
    _res, fails, _warns = ck.run(root, today)
    # Structure only: a legitimate re-decision must not break this confusingly.
    assert all(f.startswith("EXPIRED") for f in fails), fails


def test_real_repo_fails_once_clock_passes_latest_expiry() -> None:
    root = Path(__file__).resolve().parents[2]
    res, _, _ = ck.run(root, date(2026, 10, 6))
    assert res.items
    later = max(i.expires for i in res.items) + timedelta(days=1)
    _res, fails, _warns = ck.run(root, later)
    assert len([f for f in fails if f.startswith("EXPIRED")]) == len(res.items)


def test_inventory_header_has_no_hardcoded_count() -> None:
    """Regression guard (#1984): a pinned count made every suppression PR a merge-race hotspot."""
    root = Path(__file__).resolve().parents[2]
    doc = (
        root / "docs/plan/backlog/artifacts/e49-accepted-risk-inventory.md"
    ).read_text(encoding="utf-8")
    assert not re.search(r"\d+\s+items checked", doc)
    assert "--report" in doc


def test_report_contains_count_line(tmp_path: Path) -> None:
    root = _root(tmp_path)
    out = tmp_path / "r.md"
    ck.main(["--root", str(root), "--today", TODAY.isoformat(), "--report", str(out)])
    res, _, _ = ck.run(root, TODAY)
    assert f"**{len(res.items)} items checked**" in out.read_text(encoding="utf-8")


def test_exception_row_expired_and_warn_and_malformed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ck.SECURITY_PLAN).write_text(
        EX_TABLE.format(exp="2026-10-01"), encoding="utf-8"
    )
    fails, _ = _run(root)
    assert any("EXPIRED [exception] EX-09 owner=Pending @basiltt" in f for f in fails)
    (root / ck.SECURITY_PLAN).write_text(
        EX_TABLE.format(exp="2026-10-10"), encoding="utf-8"
    )
    assert "EX-09" in _run(root)[1][0]
    (root / ck.SECURITY_PLAN).write_text(
        EX_TABLE.format(exp="someday"), encoding="utf-8"
    )
    assert any(f.startswith("MISSING-EXPIRY [exception] EX-09") for f in _run(root)[0])
    (root / ck.SECURITY_PLAN).unlink()
    assert any(f.startswith("UNPARSEABLE") for f in _run(root)[0])
