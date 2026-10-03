"""E49-T01 unit tests: SLA clock, DoR parser, regression guard, CLI decisions. No network."""

from __future__ import annotations

import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Self
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
    assert (
        sla.business_minutes_between(at(2026, 10, 2, 16), at(2026, 10, 5, 10), CAL)
        == 120
    )


def test_opened_outside_hours_starts_clock_at_open() -> None:
    assert (
        sla.business_minutes_between(at(2026, 10, 3, 12), at(2026, 10, 5, 9, 30), CAL)
        == 30
    )


def test_holiday_is_skipped() -> None:
    cal = sla.calendar_from_dict(
        {"timezone": "Europe/London", "holidays": ["2026-10-05"]}
    )
    assert sla.deadline(at(2026, 10, 2, 17), 60, cal) == at(2026, 10, 6, 10)


def test_dst_boundary_uses_local_wall_clock() -> None:
    # UK clocks go back 2026-10-25 (Sunday); Fri->Mon is still one 8h working day.
    assert (
        sla.business_minutes_between(at(2026, 10, 23, 9), at(2026, 10, 26, 9), CAL)
        == 480
    )


def test_p1_at_risk_at_75_percent_then_breached() -> None:
    opened = at(2026, 10, 1, 9)
    assert sla.classify("P1", opened, at(2026, 10, 1, 14, 59), CAL) == "ok"
    assert sla.classify("P1", opened, at(2026, 10, 1, 15), CAL) == "sla-at-risk"
    assert sla.classify("P1", opened, at(2026, 10, 1, 17), CAL) == "sla-at-risk"
    assert sla.classify("P1", opened, at(2026, 10, 2, 9, 1), CAL) == "sla-breached"


@pytest.mark.parametrize(
    ("sev", "minutes"), [("P0", 120), ("P1", 480), ("P2", 1440), ("P3", 2400)]
)
def test_window_minutes(sev: str, minutes: int) -> None:
    assert sla.window_minutes(sev, CAL) == minutes


def test_now_before_open_is_zero() -> None:
    assert (
        sla.business_minutes_between(at(2026, 10, 1, 12), at(2026, 10, 1, 9), CAL) == 0
    )


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
    [
        "services/api/tests/test_x.py",
        "apps/web/src/a.test.tsx",
        "tests/triage/t.py",
        "x_test.py",
    ],
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
    d = run.dor_decision(
        {"labels": [{"name": "type/bug"}], "body": _body("no_repro.md")}
    )
    assert d["needs_dor"] and "Reproduction steps" in d["comment"]


def test_dor_decision_skips_non_bug() -> None:
    assert run.dor_decision({"labels": [{"name": "type/task"}], "body": ""}) == {
        "skip": True
    }


def test_sla_labels_skips_triaged() -> None:
    issue = {
        "labels": [
            {"name": "type/bug"},
            {"name": "triaged"},
            {"name": "priority/p1-high"},
        ],
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
    assert ("POST", "/issues/1/labels") in api.calls and (
        "POST",
        "/issues/1/comments",
    ) in api.calls
    ok = FakeApi(
        {
            "labels": [{"name": "type/bug"}, {"name": "needs-dor"}],
            "body": _body("complete.md"),
        }
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


def test_cmd_sla_labels_breached_and_removes_at_risk(
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = {
        "number": 9,
        "labels": [
            {"name": "type/bug"},
            {"name": "priority/p0-critical"},
            {"name": "sla-at-risk"},
        ],
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
    bad = RouteApi(
        {"/pulls/1/files": [{"filename": "src/a.py"}], "/pulls/1": pr, "/issues/4": bug}
    )
    assert run.cmd_guard(bad, 1) == 1  # type: ignore[arg-type]
    good = RouteApi(
        {
            "/pulls/1/files": [{"filename": "tests/test_a.py"}],
            "/pulls/1": pr,
            "/issues/4": bug,
        }
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
    assert ("PATCH", "/issues/2") in api.calls and (
        "PATCH",
        "/issues/comments/5",
    ) in api.calls


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


def test_sweep_flags_failing_bug_with_owner_and_unset_severity() -> None:
    issue = {"labels": [{"name": "type/bug"}], "body": "", "user": {"login": "rep"}}
    a = run.sweep_actions(issue)
    assert (
        a["owner"] == "rep" and "needs-dor" in a["add"] and "needs-severity" in a["add"]
    )
    assert "@rep" in a["comment"]


def test_sweep_passes_complete_bug_and_prefers_assignee() -> None:
    issue = {
        "labels": [{"name": "type/bug"}, {"name": "priority/p2"}],
        "body": _body("complete.md"),
        "assignee": {"login": "dev"},
        "user": {"login": "rep"},
    }
    a = run.sweep_actions(issue)
    assert a["comment"] is None and a["add"] == [] and a["severity"] == "P2"


def test_cmd_sweep_labels_and_comments_once(capsys: pytest.CaptureFixture[str]) -> None:
    issue = {
        "number": 5,
        "labels": [{"name": "type/bug"}],
        "body": "",
        "user": {"login": "r"},
    }
    api = RouteApi({"/issues?state=open": [issue]})
    assert run.cmd_sweep(api) == 0  # type: ignore[arg-type]
    assert ("POST", "/issues/5/labels") in api.calls and (
        "POST",
        "/issues/5/comments",
    ) in api.calls
    assert "graded 1" in capsys.readouterr().out
    dry = RouteApi({"/issues?state=open": [issue]})
    run.cmd_sweep(dry, dry_run=True)  # type: ignore[arg-type]
    assert not [c for c in dry.calls if c[0] != "GET"]


def test_cmd_guard_exempt_label_with_reason_passes() -> None:
    bug = {
        "labels": [{"name": "type/bug"}, {"name": "p3-cosmetic-exempt"}],
        "body": "### Cosmetic exemption reason\n\npixel nudge only",
    }
    api = RouteApi(
        {
            "/pulls/1/files": [{"filename": "src/a.py"}],
            "/pulls/1": {"body": "Closes #4"},
            "/issues/4": bug,
        }
    )
    assert run.cmd_guard(api, 1) == 0  # type: ignore[arg-type]


def test_with_retry_succeeds_after_transient_error() -> None:
    n = {"i": 0}

    def fn() -> str:
        n["i"] += 1
        if n["i"] < 2:
            raise urllib.error.URLError("x")
        return "ok"

    assert run.with_retry(fn, sleep=lambda _s: None) == "ok"


# --- through the real urlopen layer (stubbed transport) ----------------------
import io
import json as _json

_GQL = "https://api.github.com/graphql"
_ISSUES = "https://api.github.com/repos/o/r/issues?state=open&labels=type/bug&per_page=100&page=1"
_HOOK = "https://hook.example/x"


class _Resp(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *a: object) -> None:
        self.close()


def _fake(routes: dict[str, object], seen: list[tuple[str, bytes]]):  # type: ignore[no-untyped-def]
    def op(req, timeout=0):  # type: ignore[no-untyped-def]
        seen.append((req.full_url, req.data or b""))
        r = routes[req.full_url]
        if isinstance(r, Exception):
            raise r
        return _Resp(_json.dumps(r).encode())

    return op


def _http(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "m", {}, None)  # type: ignore[arg-type]


def test_graphql_project_fields_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, bytes]] = []
    nodes = [{"name": "Severity"}, {"name": "Status"}, {}]
    data = {"data": {"node": {"fields": {"nodes": nodes}}}}
    monkeypatch.setattr(run.urllib.request, "urlopen", _fake({_GQL: data}, seen))
    run.check_project_fields(run.GhApi("o/r", "t"), "PVT_1")
    assert b"PVT_1" in seen[0][1]


def test_graphql_missing_field_raises_field_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = {"data": {"node": {"fields": {"nodes": [{"name": "Status"}]}}}}
    monkeypatch.setattr(run.urllib.request, "urlopen", _fake({_GQL: data}, []))
    with pytest.raises(run.TriageError) as e:
        run.check_project_fields(run.GhApi("o/r", "t"), "PVT_1")
    assert e.value.code == "E_TRIAGE_FIELD_MISSING" and "Severity" in str(e.value)


@pytest.mark.parametrize(
    ("msg", "code"),
    [("API rate limit exceeded", "E_TRIAGE_RATE_LIMITED"), ("boom", "E_TRIAGE_API")],
)
def test_graphql_error_payload_maps_codes(
    monkeypatch: pytest.MonkeyPatch, msg: str, code: str
) -> None:
    payload = {"errors": [{"message": msg}]}
    monkeypatch.setattr(run.urllib.request, "urlopen", _fake({_GQL: payload}, []))
    with pytest.raises(run.TriageError) as e:
        run.GhApi("o/r", "t").graphql("q", {})
    assert e.value.code == code


def test_http_429_after_retries_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run.time, "sleep", lambda _s: None)
    url = "https://api.github.com/repos/o/r/issues/1"
    monkeypatch.setattr(run.urllib.request, "urlopen", _fake({url: _http(429)}, []))
    with pytest.raises(run.TriageError) as e:
        run.GhApi("o/r", "t").call("GET", "/issues/1")
    assert e.value.code == "E_TRIAGE_RATE_LIMITED"


def test_digest_webhook_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, bytes]] = []
    issue = {
        "number": 7,
        "created_at": "2020-01-01T09:00:00Z",
        "labels": [{"name": "type/bug"}, {"name": "priority/p0"}],
        "body": "",
    }
    routes = {
        _ISSUES: [issue],
        "https://api.github.com/repos/o/r/issues/7/labels": [],
        _HOOK: {},
    }
    monkeypatch.setattr(run.urllib.request, "urlopen", _fake(routes, seen))
    assert run.cmd_sla(run.GhApi("o/r", "t"), CAL, _HOOK) == 0
    hook = [d for u, d in seen if u == _HOOK]
    assert hook and "#7" in _json.loads(hook[0])["text"]


def test_main_error_code_posted_to_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, bytes]] = []
    monkeypatch.setattr(run.time, "sleep", lambda _s: None)
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("TRIAGE_DIGEST_WEBHOOK", _HOOK)
    monkeypatch.setattr(
        run.urllib.request, "urlopen", _fake({_ISSUES: _http(500), _HOOK: {}}, seen)
    )
    assert run.main(["sla"]) == 1
    assert any(b"E_TRIAGE_API" in d for u, d in seen if u == _HOOK)
