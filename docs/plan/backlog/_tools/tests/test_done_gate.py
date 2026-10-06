"""Unit tests for done_gate.py — no network; `gh` is injected."""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import done_gate as dg

QA_PASS = {
    "body": "QA verification — VERDICT: PASS",
    "createdAt": "2026-10-01",
    "author": {"login": "qa"},
}
PENPOT = "https://design.penpot.app/#/workspace?team-id=t&file-id=f&page-id=p"


def owner(body: str) -> dict[str, Any]:
    return {"body": body, "createdAt": "2026-10-02", "author": {"login": "basiltt"}}


def ticket(
    dod: list[str], labels: list[str] | None = None, kind: str = "Task"
) -> dict[str, Any]:
    body = "## Definition of Done\n" + "\n".join(dod) + "\n\n## Dependencies\n"
    return {"key": "T-1", "kind": kind, "labels": labels or [], "body": body}


def issue(
    comments: list[dict[str, Any]], labels: list[str] | None = None
) -> dict[str, Any]:
    return {
        "body": "",
        "comments": comments,
        "labels": [{"name": n} for n in labels or []],
    }


def rules(res: dict[str, Any]) -> list[str]:
    return [f["rule"] for f in res["failures"]]


def test_qa_missing_fails_and_present_passes() -> None:
    assert rules(dg.evaluate(ticket(["- [x] done"]), issue([]), [])) == ["qa"]
    assert dg.evaluate(ticket(["- [x] done"]), issue([QA_PASS]), [])["ok"]


def test_qa_latest_fail_verdict_fails() -> None:
    late = {"body": "QA re-verification — VERDICT: FAIL", "createdAt": "2026-10-03"}
    assert "qa" in rules(dg.evaluate(ticket([]), issue([QA_PASS, late]), []))


def test_design_absent_then_present() -> None:
    t = ticket(["- [x] spec"], ["type/design"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["design"] * 3
    c = [QA_PASS, owner(f"approved. {PENPOT} img/scr-1.png")]
    assert dg.evaluate(t, issue(c), [])["ok"]


def test_design_merged_pr_counts_as_approval() -> None:
    pr = {"body": f"{PENPOT} ![x](a/img/x.png)", "mergedAt": "2026-10-02", "files": []}
    assert dg.evaluate(ticket([], ["type/design"]), issue([QA_PASS]), [pr])["ok"]


def test_perf_needs_number_or_exception() -> None:
    t = ticket(["- [x] p95 frame time recorded"], ["perf"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["perf"]
    pr = {"body": "p95 frame time 11.2 ms", "reviews": [], "comments": []}
    assert dg.evaluate(t, issue([QA_PASS]), [pr])["ok"]
    exc = owner("exception per #1778: DoD 1 waived, no reference hardware")
    res = dg.evaluate(t, issue([QA_PASS, exc]), [])
    assert res["ok"] and res["waived"]


def test_security_requires_approve_verdict() -> None:
    t = ticket([], ["security-review"])
    bad = {
        "body": "",
        "reviews": [{"body": "Security review — VERDICT: REQUEST_CHANGES"}],
    }
    ok = {"body": "", "reviews": [{"body": "Security review — VERDICT: APPROVE"}]}
    assert rules(dg.evaluate(t, issue([QA_PASS]), [bad])) == ["security"]
    assert dg.evaluate(t, issue([QA_PASS]), [ok])["ok"]


def test_ui_requires_a11y_evidence() -> None:
    t = ticket([], ["a11y"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["a11y"]
    pr = {"body": "axe: 0 serious/critical", "reviews": [], "comments": []}
    assert dg.evaluate(t, issue([QA_PASS]), [pr])["ok"]


def test_unchecked_box_fails_unless_specifically_waived() -> None:
    t = ticket(["- [x] a", "- [ ] second thing"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["dod"]
    exc = owner("waived #1778 — DoD 2 deferred to E37-Q04")
    assert dg.evaluate(t, issue([QA_PASS, exc]), [])["ok"]


def test_blanket_waiver_is_ignored() -> None:
    t = ticket(["- [ ] second thing"])
    res = dg.evaluate(
        t, issue([QA_PASS, owner("exception: waived everything #1778")]), []
    )
    assert rules(res) == ["dod"] and res["blanket_waivers_ignored"]


def test_waiver_by_non_owner_or_without_ref_ignored() -> None:
    t = ticket(["- [ ] second thing"])
    other = {"body": "waived #1778 DoD 1", "author": {"login": "agent"}}
    noref = owner("waived DoD 1")
    assert rules(dg.evaluate(t, issue([QA_PASS, other, noref]), [])) == ["dod"]


def test_waiver_by_quoted_fragment() -> None:
    t = ticket(["- [ ] Charters C2/C3 executed with session notes"])
    exc = owner('exception #1778: "Charters C2/C3 executed" deferred')
    assert dg.evaluate(t, issue([QA_PASS, exc]), [])["ok"]


# --- member-issue regressions -------------------------------------------------


def test_regress_1829_hardware_waived_but_inline_vs_worker_not() -> None:
    t = ticket(
        [
            "- [ ] Sweep completed across all listed environments (or gaps recorded)",
            "- [ ] Worker-vs-inline behavioural-equivalence result recorded",
        ],
        ["qa"],
    )
    exc = owner("exception #1778: DoD 1 hardware/browser sweep waived")
    res = dg.evaluate(t, issue([QA_PASS, exc]), [])
    assert not res["ok"]
    assert [f["item"] for f in res["failures"]] == [2]


def test_regress_1462_design_without_penpot_or_png() -> None:
    t = ticket(["- [x] hi-fi published"], ["type/design", "a11y"])
    res = dg.evaluate(t, issue([QA_PASS, owner("approved")]), [])
    details = " ".join(f["detail"] for f in res["failures"])
    assert "Penpot" in details and "PNG" in details


def test_regress_1803_spike_measurement_not_run() -> None:
    t = ticket(
        ["- [x] benchmark table published for 60 s runs"], ["perf"], kind="Spike"
    )
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["perf"]


def test_regress_1830_missing_qa_signoff_contribution() -> None:
    t = ticket(["- [ ] QA sign-off comment posted; findings handed over"], ["qa"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["dod"]


def test_run_gate_with_fake_gh_filters_prs_and_renders() -> None:
    def fake(args: list[str]) -> Any:
        if args[0] == "issue":
            return issue([QA_PASS])
        return [
            {"number": 1, "body": "Closes #5", "reviews": [], "comments": []},
            {
                "number": 2,
                "body": "unrelated #5 mention",
                "reviews": [],
                "comments": [],
            },
        ]

    prs = dg.fetch("5", fake)[1]
    assert [p["number"] for p in prs] == [1]
    out = dg.render(
        {
            "key": "K",
            "issue": 5,
            "ok": False,
            "waived": [],
            "blanket_waivers_ignored": [],
            "failures": [{"rule": "qa", "item": None, "detail": "x"}],
        }
    )
    assert out.startswith("K #5: FAIL")
