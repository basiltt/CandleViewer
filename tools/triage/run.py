#!/usr/bin/env python3
"""CLI wiring for the triage workflows. Decision logic lives in sibling modules; only
`GhApi` touches the network. Errors: E_TRIAGE_API, E_TRIAGE_FIELD_MISSING,
E_TRIAGE_RATE_LIMITED. The token is read from the environment and never logged."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from tools.triage import dor, guard, sla

DOR_MARKER = "<!-- triage:dor -->"
SWEEP_MARKER = "<!-- triage:sweep -->"


class TriageError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def with_retry(
    fn: Callable[[], Any],
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry with exponential backoff; raise (never swallow) after the last attempt."""
    for i in range(attempts):
        try:
            return fn()
        except urllib.error.HTTPError as exc:
            if i == attempts - 1:
                code = (
                    "E_TRIAGE_RATE_LIMITED"
                    if exc.code in (403, 429)
                    else "E_TRIAGE_API"
                )
                raise TriageError(code, f"HTTP {exc.code}") from exc
            sleep(2**i)
        except urllib.error.URLError as exc:
            if i == attempts - 1:
                raise TriageError("E_TRIAGE_API", "unreachable") from exc
            sleep(2**i)


class GhApi:
    def __init__(self, repo: str, token: str) -> None:
        self.repo, self._token = repo, token

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        def go() -> Any:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{self.repo}{path}",
                data=json.dumps(body).encode() if body is not None else None,
                method=method,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None

        return with_retry(go)

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        """Projects v2 GraphQL call; GraphQL-level errors surface as E_TRIAGE_*."""

        def go() -> Any:
            req = urllib.request.Request(
                "https://api.github.com/graphql",
                data=json.dumps({"query": query, "variables": variables}).encode(),
                method="POST",
                headers={"Authorization": f"Bearer {self._token}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())

        out = with_retry(go)
        if out.get("errors"):
            msg = str(out["errors"][0].get("message", "graphql error"))
            code = (
                "E_TRIAGE_RATE_LIMITED"
                if "rate limit" in msg.lower()
                else "E_TRIAGE_API"
            )
            raise TriageError(code, msg)
        return out["data"]


PROJECT_FIELDS_QUERY = (
    "query($id:ID!){node(id:$id){... on ProjectV2{fields(first:50){nodes{"
    "... on ProjectV2FieldCommon{name}}}}}}"
)


def check_project_fields(
    api: GhApi, project_id: str, need: tuple[str, ...] = ("Severity", "Status")
) -> None:
    """Fail loudly (E_TRIAGE_FIELD_MISSING) if the board lacks a field we rely on."""
    data = api.graphql(PROJECT_FIELDS_QUERY, {"id": project_id})
    node = data.get("node") or {}
    names = {n.get("name") for n in node.get("fields", {}).get("nodes", []) if n}
    missing = [f for f in need if f not in names]
    if missing:
        raise TriageError("E_TRIAGE_FIELD_MISSING", ", ".join(missing))


def dor_decision(issue: dict[str, Any]) -> dict[str, Any]:
    labels = [x["name"] for x in issue.get("labels", [])]
    if "type/bug" not in labels:
        return {"skip": True}
    body = issue.get("body") or ""
    missing = dor.missing_fields(body)
    hits = dor.scan_secrets(body)
    lines: list[str] = []
    if missing:
        lines.append(
            "Bug DoR (02-definition-of-ready-done.md §6.1) is incomplete. Missing fields:"
        )
        lines += [f"- {m}" for m in missing]
    if hits:
        lines.append(
            f"Possible secret(s) detected ({', '.join(hits)}). Body redacted; rotate any real credential."
        )
    return {
        "skip": False,
        "needs_dor": bool(missing),
        "comment": (DOR_MARKER + "\n" + "\n".join(lines)) if lines else None,
        "redacted_body": dor.redact(body) if hits else None,
    }


def cmd_dor(api: GhApi, number: int) -> int:
    issue = api.call("GET", f"/issues/{number}")
    d = dor_decision(issue)
    if d["skip"]:
        return 0
    labels = [x["name"] for x in issue.get("labels", [])]
    if d["needs_dor"] and "needs-dor" not in labels:
        api.call("POST", f"/issues/{number}/labels", {"labels": ["needs-dor"]})
    elif not d["needs_dor"] and "needs-dor" in labels:
        api.call("DELETE", f"/issues/{number}/labels/needs-dor")
    if d["redacted_body"]:
        api.call("PATCH", f"/issues/{number}", {"body": d["redacted_body"]})
    comments = api.call("GET", f"/issues/{number}/comments?per_page=100") or []
    mine = next((c for c in comments if DOR_MARKER in c["body"]), None)
    if d["comment"] and not (mine and mine["body"] == d["comment"]):
        if mine:
            api.call("PATCH", f"/issues/comments/{mine['id']}", {"body": d["comment"]})
        else:
            api.call("POST", f"/issues/{number}/comments", {"body": d["comment"]})
    return 0  # never auto-closes


def sla_labels(
    issue: dict[str, Any], now: datetime, cal: sla.Calendar
) -> tuple[str, str | None]:
    """Return (state, severity); triaged issues (label `triaged`) are never flagged."""
    labels = [x["name"] for x in issue.get("labels", [])]
    if "triaged" in labels or "type/bug" not in labels:
        return "ok", None
    sev = dor.severity_of(issue.get("body") or "", labels)
    if sev is None:
        return "ok", None
    opened = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
    return sla.classify(sev, opened, now, cal), sev


def digest(rows: list[tuple[int, str, str]]) -> str:
    out = [f"Defect triage digest: {len(rows)} bug(s) need attention"]
    out += [f"- #{n} {sev} {state.upper()}" for n, sev, state in rows]
    return "\n".join(out)  # plain text, no colour-only meaning


def cmd_sla(
    api: GhApi, cal: sla.Calendar, webhook: str | None, project_id: str | None = None
) -> int:
    if project_id:
        check_project_fields(api, project_id)
    now = datetime.now(timezone.utc)
    rows: list[tuple[int, str, str]] = []
    page = 1
    while True:
        batch = (
            api.call(
                "GET", f"/issues?state=open&labels=type/bug&per_page=100&page={page}"
            )
            or []
        )
        for issue in batch:
            state, sev = sla_labels(issue, now, cal)
            if state == "ok" or sev is None:
                continue
            have = {x["name"] for x in issue["labels"]}
            if state not in have:
                api.call(
                    "POST", f"/issues/{issue['number']}/labels", {"labels": [state]}
                )
            if state == "sla-breached" and "sla-at-risk" in have:
                api.call("DELETE", f"/issues/{issue['number']}/labels/sla-at-risk")
            rows.append((issue["number"], sev, state))
        if len(batch) < 100:
            break
        page += 1
    if webhook and rows:
        req = urllib.request.Request(
            webhook,
            data=json.dumps({"text": digest(rows)}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with_retry(lambda: urllib.request.urlopen(req, timeout=30).close())
    print(digest(rows))
    return 0


def _exempt_reason(body: str) -> str:
    return dor.parse_sections(body).get("Cosmetic exemption reason", "")


def closing_issues(pr_body: str) -> list[int]:
    pat = r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)"
    return sorted({int(m) for m in re.findall(pat, pr_body or "")})


def cmd_guard(api: GhApi, pr: int) -> int:
    """Fail unless every Bug closed by this PR is guarded by a test change."""
    pr_obj = api.call("GET", f"/pulls/{pr}")
    files: list[str] = []
    page = 1
    while True:
        batch = api.call("GET", f"/pulls/{pr}/files?per_page=100&page={page}") or []
        files += [f["filename"] for f in batch]
        if len(batch) < 100:
            break
        page += 1
    failed = False
    for n in closing_issues(pr_obj.get("body") or ""):
        issue = api.call("GET", f"/issues/{n}")
        labels = [x["name"] for x in issue.get("labels", [])]
        if "type/bug" not in labels:
            continue
        result = guard.evaluate(files, labels, _exempt_reason(issue.get("body") or ""))
        print(f"#{n}: {'PASS' if result.ok else 'FAIL'} - {result.reason}")
        failed |= not result.ok
    return 1 if failed else 0


def sweep_actions(issue: dict[str, Any]) -> dict[str, Any]:
    """One-time re-grade of an existing open bug against §11.3 / §6.1 (pure)."""
    labels = [x["name"] for x in issue.get("labels", [])]
    body = issue.get("body") or ""
    missing = dor.missing_fields(body)
    sev = dor.severity_of(body, labels)
    if sev is None and "Severity" not in missing:
        missing.append("Severity")
    owner = (issue.get("assignee") or {}).get("login") or (issue.get("user") or {}).get(
        "login"
    )
    add: list[str] = []
    if missing and "needs-dor" not in labels:
        add.append("needs-dor")
    if sev is None and "needs-severity" not in labels:
        add.append("needs-severity")
    comment = None
    if missing:
        comment = (
            f"{SWEEP_MARKER}\nOne-time debt sweep: this bug fails the Bug DoR "
            f"(02-definition-of-ready-done.md §6.1). Owner to complete: @{owner}. Missing:\n"
            + "\n".join(f"- {m}" for m in missing)
        )
    return {
        "severity": sev,
        "missing": missing,
        "owner": owner,
        "add": add,
        "comment": comment,
    }


def cmd_sweep(api: GhApi, dry_run: bool = False) -> int:
    graded = flagged = 0
    page = 1
    while True:
        batch = (
            api.call(
                "GET", f"/issues?state=open&labels=type/bug&per_page=100&page={page}"
            )
            or []
        )
        for issue in batch:
            if "pull_request" in issue:
                continue
            a = sweep_actions(issue)
            graded += 1
            n = issue["number"]
            if a["missing"]:
                flagged += 1
            print(
                f"#{n}: severity={a['severity'] or 'UNSET'} missing={len(a['missing'])}"
            )
            if dry_run:
                continue
            if a["add"]:
                api.call("POST", f"/issues/{n}/labels", {"labels": a["add"]})
            if a["comment"]:
                comments = api.call("GET", f"/issues/{n}/comments?per_page=100") or []
                if not any(SWEEP_MARKER in c["body"] for c in comments):
                    api.call("POST", f"/issues/{n}/comments", {"body": a["comment"]})
        if len(batch) < 100:
            break
        page += 1
    print(f"Sweep: graded {graded} open bug(s); {flagged} fail DoR")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["dor", "sla", "guard", "sweep"])
    p.add_argument("--number", type=int)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    token, repo = (
        os.environ.get("GH_TOKEN", ""),
        os.environ.get("GITHUB_REPOSITORY", ""),
    )
    if not token or not repo or (a.cmd in ("dor", "guard") and a.number is None):
        print(
            "E_TRIAGE_FIELD_MISSING: GH_TOKEN, GITHUB_REPOSITORY or --number",
            file=sys.stderr,
        )
        return 2
    api = GhApi(repo, token)
    try:
        if a.cmd == "dor":
            return cmd_dor(api, a.number)
        if a.cmd == "sweep":
            return cmd_sweep(api, a.dry_run)
        if a.cmd == "guard":
            return cmd_guard(api, a.number)
        cal = sla.load_calendar(
            os.environ.get("TRIAGE_CALENDAR_PATH", "tools/triage/calendar.yml")
        )
        return cmd_sla(
            api,
            cal,
            os.environ.get("TRIAGE_DIGEST_WEBHOOK"),
            os.environ.get("TRIAGE_PROJECT_ID"),
        )
    except TriageError as exc:
        print(str(exc), file=sys.stderr)  # alert, never silent
        hook = os.environ.get("TRIAGE_DIGEST_WEBHOOK")
        if hook:  # surface the error code in the digest channel too
            try:
                req = urllib.request.Request(
                    hook,
                    data=json.dumps({"text": f"Defect triage failed: {exc}"}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=30).close()
            except (urllib.error.URLError, OSError):
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
