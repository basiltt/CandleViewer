"""Done-gate: fail when a ticket's DoD evidence artefacts are absent (cluster dod-evidence-gap, #1859).

Usage: python docs/plan/backlog/_tools/done_gate.py <KEY> <issue#> [--json]
Exit 0 = every required evidence kind present (or specifically waived), 1 = gaps (named), 2 = usage/lookup error.

Evidence rules (C-11.2, docs/design/README.md, C-10.4):
  qa        every ticket: a `QA verification ... VERDICT: PASS` comment (latest verdict wins)
  design    label type/design: owner `approved` comment or merged PR, Penpot link, PNG exports
  perf      label perf / DoD lines naming a measurement: a number+unit near the metric in PR/issue text
  security  security label: `Security review ... VERDICT: APPROVE` on the PR
  a11y      UI tickets: axe report / Storybook link
  dod       every unchecked `- [ ]` DoD line must be ticked or waived
Waivers: an OWNER comment matching `exception|waived` + `#1778` waives only the item it names
(`DoD 4`, `AC 2`, `item 3`, `evidence:perf`, or a quoted fragment of the DoD line). Blanket waivers are ignored.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "basiltt/CandleViewer"
OWNER = "basiltt"
WAIVER_REF = "#1778"
GhFn = Callable[[list[str]], Any]

PENPOT_RE = re.compile(
    r"https://design\.penpot\.app/#/workspace\?[^\s)]*file-id=[^\s)]+", re.IGNORECASE
)
PNG_RE = re.compile(r"\.png\b", re.IGNORECASE)
QA_RE = re.compile(
    r"QA (?:re-)?verification[^\n]*VERDICT:\s*(PASS|FAIL)", re.IGNORECASE
)
SEC_RE = re.compile(
    r"Security review[^\n]*VERDICT:\s*(APPROVE|REQUEST_CHANGES|BLOCK)", re.IGNORECASE
)
A11Y_RE = re.compile(r"\baxe\b|storybook|a11y (?:report|evidence)", re.IGNORECASE)
APPROVED_RE = re.compile(r"\bapproved?\b", re.IGNORECASE)
UNIT = r"(?:ms|µs|us|ns|fps|hz|mb|kb|gb|%|s|/s|msg/s|ops/s|bytes?)"
NUM_RE = re.compile(rf"\d[\d.,]*\s*{UNIT}\b", re.IGNORECASE)
METRIC_WORDS = [
    "p50",
    "p95",
    "p99",
    "fps",
    "latency",
    "throughput",
    "memory",
    "frame",
    "time",
    "benchmark",
    "bench",
    "duration",
    "overhead",
    "heap",
    "rss",
    "cpu",
    "fan-out",
    "jitter",
]
UI_AREAS = ("area/charting-ui", "area/design-system", "area/frontend-platform")


def gh_json(args: list[str]) -> Any:
    r = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "null")


def load_ticket(key: str) -> dict[str, Any]:
    path = os.path.join(HERE, "..", "all-tickets.json")
    with open(path, encoding="utf-8") as fh:
        for t in json.load(fh):
            if t["key"] == key:
                return dict(t)
    raise KeyError(key)


def dod_lines(body: str) -> list[tuple[int, bool, str]]:
    """(1-based index, checked, text) for checklist lines of the Definition of Done section."""
    m = re.search(
        r"^##\s+Definition of Done\s*$(.*?)(?=^##\s|\Z)",
        body or "",
        re.MULTILINE | re.DOTALL,
    )
    out: list[tuple[int, bool, str]] = []
    for ln in (m.group(1) if m else "").splitlines():
        c = re.match(r"\s*[-*]\s*\[( |x|X)\]\s*(.+)", ln)
        if c:
            out.append((len(out) + 1, c.group(1) != " ", c.group(2).strip()))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse_waivers(
    comments: list[dict[str, Any]], dod: list[tuple[int, bool, str]], owner: str = OWNER
) -> tuple[set[int], set[str], list[str]]:
    """Return (waived DoD indexes, waived evidence kinds, ignored blanket waiver notes)."""
    items: set[int] = set()
    kinds: set[str] = set()
    blanket: list[str] = []
    for c in comments:
        body = c.get("body") or ""
        author = (c.get("author") or {}).get("login", "")
        if (
            author != owner
            or WAIVER_REF not in body
            or not re.search(r"exception|waived", body, re.IGNORECASE)
        ):
            continue
        blk = re.search(r"exception:\s*\n?(.*)", body, re.IGNORECASE | re.DOTALL)
        segs = (blk.group(1) if blk else body).splitlines()
        hit = False
        for seg in segs:
            for n in re.findall(r"\b(?:DoD|AC|item)\s*#?(\d+)", seg, re.IGNORECASE):
                items.add(int(n))
                hit = True
            for k in re.findall(r"evidence:(\w+)", seg, re.IGNORECASE):
                kinds.add(k.lower())
                hit = True
            for q in re.findall(r"[\"`“]([^\"`”]{8,})[\"`”]", seg):
                for idx, _, text in dod:
                    if _norm(q) in _norm(text):
                        items.add(idx)
                        hit = True
        if not hit:
            blanket.append(body.strip().splitlines()[0][:80] if body.strip() else "")
    return items, kinds, blanket


def _text_of(issue: dict[str, Any], prs: list[dict[str, Any]]) -> str:
    parts = [issue.get("body") or ""]
    parts += [c.get("body") or "" for c in issue.get("comments", [])]
    for p in prs:
        parts.append(p.get("body") or "")
        parts += [c.get("body") or "" for c in p.get("comments", [])]
        parts += [r.get("body") or "" for r in p.get("reviews", [])]
    return "\n".join(parts)


def has_measurement(line: str, text: str) -> bool:
    words = [w for w in METRIC_WORDS if w in line.lower()]
    if not words:
        return bool(NUM_RE.search(text))
    for w in words:
        for m in re.finditer(re.escape(w), text, re.IGNORECASE):
            if NUM_RE.search(text[max(0, m.start() - 80) : m.end() + 80]):
                return True
    return False


def evaluate(
    ticket: dict[str, Any],
    issue: dict[str, Any],
    prs: list[dict[str, Any]],
    owner: str = OWNER,
) -> dict[str, Any]:
    labels = set(ticket.get("labels", [])) | {
        x["name"] for x in issue.get("labels", [])
    }
    body = issue.get("body") or ticket.get("body") or ""
    dod = dod_lines(body) or dod_lines(ticket.get("body", ""))
    comments = issue.get("comments", [])
    w_items, w_kinds, blanket = parse_waivers(comments, dod, owner)
    text = _text_of(issue, prs)
    fails: list[dict[str, Any]] = []
    waived: list[str] = []

    def need(kind: str, ok: bool, detail: str, item: int | None = None) -> None:
        if ok:
            return
        if kind in w_kinds or (item is not None and item in w_items):
            waived.append(f"{kind}" + (f" DoD#{item}" if item else ""))
            return
        fails.append({"rule": kind, "item": item, "detail": detail})

    verdicts = sorted(
        (c.get("createdAt", ""), m.group(1).upper())
        for c in comments
        for m in [QA_RE.search(c.get("body") or "")]
        if m
    )
    need(
        "qa",
        bool(verdicts) and verdicts[-1][1] == "PASS",
        "no `QA verification — VERDICT: PASS` comment",
    )

    if "type/design" in labels or ticket.get("kind") == "Design":
        merged = any(p.get("mergedAt") for p in prs)
        appr = any(
            (c.get("author") or {}).get("login") == owner
            and APPROVED_RE.search(c.get("body") or "")
            for c in comments
        )
        need(
            "design", appr or merged, "no owner `approved` comment or merged design PR"
        )
        need(
            "design",
            bool(PENPOT_RE.search(text)),
            "no Penpot page link (docs/design/README.md)",
        )
        pngs = bool(PNG_RE.search(text)) or any(
            PNG_RE.search(f.get("path", "")) for p in prs for f in p.get("files", [])
        )
        need("design", pngs, "no PNG exports committed/embedded")

    perf_lines = [
        (i, t)
        for i, _, t in dod
        if NUM_RE.search(t) or any(w in t.lower() for w in METRIC_WORDS)
    ]
    for i, t in perf_lines if ("perf" in labels or perf_lines) else []:
        need(
            "perf", has_measurement(t, text), f"no numeric measurement for: {t[:70]}", i
        )

    if any("security" in x for x in labels):
        approved = any(
            (m := SEC_RE.search(r.get("body") or ""))
            and m.group(1).upper() == "APPROVE"
            for p in prs
            for r in [*p.get("reviews", []), *p.get("comments", [])]
        )
        need("security", approved, "no `Security review … VERDICT: APPROVE` on the PR")

    if "a11y" in labels or any(x in labels for x in UI_AREAS):
        need("a11y", bool(A11Y_RE.search(text)), "no axe report / Storybook link")

    for i, checked, t in dod:
        if not checked:
            need("dod", False, f"unchecked DoD box: {t[:80]}", i)

    return {
        "ok": not fails,
        "failures": fails,
        "waived": waived,
        "blanket_waivers_ignored": blanket,
    }


def fetch(issue_no: str, gh: GhFn) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issue = gh(
        ["issue", "view", issue_no, "-R", REPO, "--json", "body,comments,labels,state"]
    )
    prs = gh(
        [
            "pr",
            "list",
            "-R",
            REPO,
            "--state",
            "all",
            "--search",
            f"#{issue_no} in:body",
            "--limit",
            "20",
            "--json",
            "number,body,files,reviews,comments,mergedAt",
        ]
    )
    # keep only PRs that actually close this issue
    pat = re.compile(rf"(?:closes|fixes|resolves)\s+#{issue_no}\b", re.IGNORECASE)
    return issue, [p for p in prs or [] if pat.search(p.get("body") or "")]


def run_gate(
    key: str, issue_no: str, gh: GhFn = gh_json, owner: str = OWNER
) -> dict[str, Any]:
    issue, prs = fetch(issue_no, gh)
    res = evaluate(load_ticket(key), issue, prs, owner)
    res.update(key=key, issue=int(issue_no))
    return res


def render(res: dict[str, Any]) -> str:
    head = f"{res['key']} #{res['issue']}: {'PASS' if res['ok'] else 'FAIL'}"
    lines = [head]
    lines += [
        f"  - [{f['rule']}]{' DoD#' + str(f['item']) if f['item'] else ''} {f['detail']}"
        for f in res["failures"]
    ]
    lines += [f"  ~ waived (#1778): {w}" for w in res["waived"]]
    lines += [
        f"  ! blanket waiver ignored: {b}" for b in res["blanket_waivers_ignored"]
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 2
    try:
        res = run_gate(args[0], args[1])
    except (KeyError, RuntimeError) as e:
        print(f"done_gate error: {e}", file=sys.stderr)
        return 2
    print(
        json.dumps(res, indent=2, ensure_ascii=False)
        if "--json" in argv
        else render(res)
    )
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
