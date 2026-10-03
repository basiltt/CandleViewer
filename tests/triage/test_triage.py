"""E49-T01 unit tests: SLA clock, DoR parser, regression guard, CLI decisions. No network."""

from __future__ import annotations

import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tools.triage import dor, guard, run, sla

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "triage"
CAL = sla.load_calendar(FIX / "calendar.yml")
LON = ZoneInfo("Europe/London")


def at(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=LON)


# 2026-10-02 is a Friday.
def test_deadline_p0_friday_1700_falls_next_monday_morning() -> None:
    assert sla.deadline(at(2026, 10, 2, 17), 120, CAL) == at(2026, 10, 5, 11)


def test_deadline_p0_mid_afternoon_spills_to_next_morning() -> None:
    assert sla.deadline(at(2026, 10, 1, 16), 120, CAL) == at(2026, 10, 2, 10)


def test_business_minutes_exclude_weekend() -> None:
    assert sla.business_minutes_between(at(2026, 10, 2, 16), at(2026, 10, 5, 10), CAL) == 120


def test_opened_outside_hours_starts_clock_at_open() -> None:
    assert sla.business_minutes_between(at(2026, 10, 3, 12), at(2026, 10, 5, 9, 30), CAL) == 30


def test_holiday_is_skipped() -> None:
    cal = sla.calendar_from_dict({"timezone": "Europe/London", "holidays": ["2026-10-05"]})
    assert sla.deadline(at(2026, 10, 2, 17), 60, cal) == at(2026, 10, 6, 10)


def test_dst_boundary_uses_local_wall_clock() -> None:
    # UK clocks go back 2026-10-25 (Sunday); Fri->Mon is still one 8h working day.
    assert sla.business_minutes_between(at(2026, 10, 23, 9), at(2026, 10, 26, 9), CAL) == 480


def test_p1_at_risk_at_75_percent_then_breached() -> None:
    opened = at(2026, 10, 1, 9)
    assert sla.classify("P1", opened, at(2026, 10, 1, 14, 59), CAL) == "ok"
    assert sla.classify("P1", opened, at(2026, 10, 1, 15), CAL) == "sla-at-risk"
    assert sla.classify("P1", opened, at(2026, 10, 1, 17), CAL) == "sla-at-risk"
    assert sla.classify("P1", opened, at(2026, 10, 2, 9, 1), CAL) == "sla-breached"


@pytest.mark.parametrize(("sev", "minutes"), [("P0", 120), ("P1", 480), ("P2", 1440), ("P3", 2400)])
def test_window_minutes(sev: str, minutes: int) -> None:
    assert sla.window_minutes(sev, CAL) == minutes


def test_now_before_open_is_zero() -> None:
    assert sla.business_minutes_between(at(2026, 10, 1, 12), at(2026, 10, 1, 9), CAL) == 0


def _body(name: str) -> str:
    return (FIX / "issues" / name).read_text(encoding="utf-8")


def test_dor_complete_has_no_missing_fields() -> None:
    assert dor.missing_fields(_body("complete.md")) == []


def test_dor_no_repro_names_exactly_repro() -> None:
    assert dor.missing_fields(_body("no_repro.md")) == ["Reproduction steps"]


@pytest.mark.parametrize("field", dor.REQUIRED_FIELDS)
def test_dor_each_field_missing_individually(field: str) -> None:
    sections = dor.parse_sections(_body("complete.md"))
    sections.pop(field)
    rebuilt = "\n".join(f"### {k}\n\n{v}\n" for k, v in sections.items())
    assert dor.missing_fields(rebuilt) == [field]


def test_dor_non_template_body_misses_everything() -> None:
    assert dor.missing_fields("it is broken") == dor.REQUIRED_FIELDS


def test_dor_extra_sections_ignored() -> None:
    assert dor.missing_fields(_body("complete.md") + "\n### Notes\n\nextra\n") == []


def test_dor_no_response_placeholder_is_missing() -> None:
    body = "### Reproduction steps\n\n_No response_\n"
    assert "Reproduction steps" in dor.missing_fields(body)


def test_secret_scan_flags_and_redacts_without_echo() -> None:
    body = "token: " + "ghp_" + "a" * 30 + "\nfine"
    assert dor.scan_secrets(body) == ["github-token", "key-assignment"]
    assert "ghp_" not in dor.redact(body)


def test_secret_scan_clean_body() -> None:
    assert dor.scan_secrets(_body("complete.md")) == []


def test_guard_source_only_fails_and_names_requirement() -> None:
    r = guard.evaluate(["services/api/x.py"], ["type/bug"])
    assert not r.ok and "regression test" in r.reason


@pytest.mark.parametrize(
    "path",
    ["services/api/tests/test_x.py", "apps/web/src/a.test.tsx", "tests/triage/t.py", "x_test.py"],
)
def test_guard_test_file_passes(path: str) -> None:
    assert guard.evaluate(["src/a.py", path], ["type/bug"]).ok


def test_guard_docs_only_fails() -> None:
    assert not guard.evaluate(["docs/a.md"], ["type/bug"]).ok


def test_guard_exempt_needs_reason() -> None:
    assert not guard.evaluate(["a.py"], ["p3-cosmetic-exempt"]).ok
    assert guard.evaluate(["a.py"], ["p3-cosmetic-exempt"], "typo in tooltip").ok


def test_closing_issue_parse() -> None:
    assert run.closing_issues("Closes #5, fixes #7\nresolved #5") == [5, 7]


def test_dor_decision_incomplete_comments_fields() -> None:
    d = run.dor_decision({"labels": [{"name": "type/bug"}], "body": _body("no_repro.md")})
    assert d["needs_dor"] and "Reproduction steps" in d["comment"]


def test_dor_decision_skips_non_bug() -> None:
    assert run.dor_decision({"labels": [{"name": "type/task"}], "body": ""}) == {"skip": True}


def test_sla_labels_skips_triaged() -> None:
    issue = {
        "labels": [{"name": "type/bug"}, {"name": "triaged"}, {"name": "priority/p1-high"}],
        "created_at": "2026-09-01T09:00:00Z",
        "body": "",
    }
    assert run.sla_labels(issue, at(2026, 10, 1, 9), CAL) == ("ok", None)


def test_sla_labels_breached_p1() -> None:
    issue = {
        "labels": [{"name": "type/bug"}, {"name": "priority/p1-high"}],
        "created_at": "2026-09-28T08:00:00Z",
        "body": "",
    }
    assert run.sla_labels(issue, at(2026, 10, 1, 9), CAL) == ("sla-breached", "P1")


def test_digest_plain_text() -> None:
    assert run.digest([(3, "P1", "sla-at-risk")]).endswith("- #3 P1 SLA-AT-RISK")


def test_retry_then_alert_when_api_unavailable() -> None:
    calls: list[float] = []

    def boom() -> None:
        raise urllib.error.URLError("down")

    with pytest.raises(run.TriageError) as ei:
        run.with_retry(boom, attempts=3, sleep=calls.append)
    assert ei.value.code == "E_TRIAGE_API" and calls == [1, 2]


def test_retry_rate_limited_code() -> None:
    def limited() -> None:
        raise urllib.error.HTTPError("u", 429, "x", {}, None)  # type: ignore[arg-type]

    with pytest.raises(run.TriageError) as ei:
        run.with_retry(limited, attempts=2, sleep=lambda _s: None)
    assert ei.value.code == "E_TRIAGE_RATE_LIMITED"


def test_main_missing_config_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert run.main(["sla"]) == 2


class FakeApi:
    def __init__(self, issue: dict, comments: list | None = None) -> None:
        self.issue, self.comments, self.calls = issue, comments or [], []

    def call(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path))
        if method == "GET" and path.endswith("/comments?per_page=100"):
            return self.comments
        if method == "GET":
            return self.issue
        return None


def test_cmd_dor_labels_then_clears() -> None:
    api = FakeApi({"labels": [{"name": "type/bug"}], "body": _body("no_repro.md")})
    run.cmd_dor(api, 1)  # type: ignore[arg-type]
    assert ("POST", "/issues/1/labels") in api.calls and ("POST", "/issues/1/comments") in api.calls
    ok = FakeApi(
        {"labels": [{"name": "type/bug"}, {"name": "needs-dor"}], "body": _body("complete.md")}
    )
    run.cmd_dor(ok, 1)  # type: ignore[arg-type]
    assert ("DELETE", "/issues/1/labels/needs-dor") in ok.calls


class RouteApi:
    """Routes GETs by path prefix; records mutations."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes, self.calls = routes, []

    def call(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path))
        if method != "GET":
            return None
        for prefix, value in self.routes.items():
            if path.startswith(prefix):
                return value
        return None


def test_cmd_sla_labels_breached_and_removes_at_risk(capsys: pytest.CaptureFixture[str]) -> None:
    issue = {
        "number": 9,
        "labels": [{"name": "type/bug"}, {"name": "priority/p0-critical"}, {"name": "sla-at-risk"}],
        "created_at": "2020-01-06T09:00:00Z",
        "body": "",
    }
    api = RouteApi({"/issues?state=open": [issue]})
    assert run.cmd_sla(api, CAL, None) == 0  # type: ignore[arg-type]
    assert ("POST", "/issues/9/labels") in api.calls
    assert ("DELETE", "/issues/9/labels/sla-at-risk") in api.calls
    assert "#9 P0 SLA-BREACHED" in capsys.readouterr().out


def test_cmd_guard_fails_source_only_and_passes_with_test() -> None:
    bug = {"labels": [{"name": "type/bug"}], "body": ""}
    pr = {"body": "Closes #4"}
    bad = RouteApi({"/pulls/1/files": [{"filename": "src/a.py"}], "/pulls/1": pr, "/issues/4": bug})
    assert run.cmd_guard(bad, 1) == 1  # type: ignore[arg-type]
    good = RouteApi(
        {"/pulls/1/files": [{"filename": "tests/test_a.py"}], "/pulls/1": pr, "/issues/4": bug}
    )
    assert run.cmd_guard(good, 1) == 0  # type: ignore[arg-type]


def test_cmd_guard_ignores_non_bug_issue() -> None:
    api = RouteApi(
        {
            "/pulls/1/files": [{"filename": "src/a.py"}],
            "/pulls/1": {"body": "Closes #4"},
            "/issues/4": {"labels": [{"name": "type/task"}]},
        }
    )
    assert run.cmd_guard(api, 1) == 0  # type: ignore[arg-type]


def test_exempt_label_with_reason_in_issue_body_passes() -> None:
    bug = {
        "labels": [{"name": "type/bug"}, {"name": "p3-cosmetic-exempt"}],
        "body": "### Cosmetic exemption reason\n\ntooltip typo\n",
    }
    api = RouteApi(
        {
            "/pulls/1/files": [{"filename": "src/a.py"}],
            "/pulls/1": {"body": "Closes #4"},
            "/issues/4": bug,
        }
    )
    assert run.cmd_guard(api, 1) == 0  # type: ignore[arg-type]


def test_cmd_dor_updates_existing_comment_and_redacts() -> None:
    body = _body("no_repro.md") + "\npassword: " + "x" * 20
    c = [{"id": 5, "body": run.DOR_MARKER + "\nold"}]
    api = FakeApi({"labels": [{"name": "type/bug"}], "body": body}, comments=c)
    run.cmd_dor(api, 2)  # type: ignore[arg-type]
    assert ("PATCH", "/issues/2") in api.calls and ("PATCH", "/issues/comments/5") in api.calls


def test_main_runs_guard_with_stubbed_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(run, "cmd_guard", lambda _a, _n: 0)
    assert run.main(["guard", "--number", "3"]) == 0


def test_main_api_failure_alerts_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")

    def boom(*_a: object) -> int:
        raise run.TriageError("E_TRIAGE_API", "x")

    monkeypatch.setattr(run, "cmd_dor", boom)
    assert run.main(["dor", "--number", "3"]) == 1
