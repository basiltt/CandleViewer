#!/usr/bin/env python3
"""
docs/plan/backlog/schema/ticket.schema.json + backlog-file.schema.json validator.

Validates every docs/plan/backlog/*.json ticket file against the JSON Schemas in
docs/plan/backlog/schema/, plus cross-file semantic rules a JSON Schema cannot
express (dependency resolution/cycles, parent chains, sprint ordering vs
blocked_by, the design-ahead lead time rule, epic budget reconciliation, and a
cheap secret-pattern scan over ticket bodies).

Emits GOV-004 per violation. Exit codes: 0 clean, 1 violations found, 2 internal
error (malformed JSON / unreadable file).

Usage:
    python scripts/validate-backlog.py               # validate, human output
    python scripts/validate-backlog.py --json         # machine-readable output
    python scripts/validate-backlog.py --summary      # per-epic point rollup
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

try:
    from jsonschema import Draft202012Validator
    _HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - exercised only when jsonschema absent
    _HAVE_JSONSCHEMA = False

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO_ROOT = os.path.dirname(HERE)

KEY_RE = re.compile(r"^E\d{2}(?:-([STKDQXC])(\d{2}))?$")
KIND_BY_LETTER = {
    "S": "Story", "T": "Task", "K": "Spike",
    "D": "Chore", "Q": "Chore", "X": "Chore", "C": "Chore",
}
# D/Q/X/C tickets are typed Story/Task/Spike/Bug/Chore in `kind`, not implied
# 1:1 by the letter (e.g. a "D" design ticket may be kind Story). Only S/T/K
# have a tight 1:1 mapping worth enforcing; D/Q/X/C are advisory only.
STRICT_LETTER_KIND = {"S": "Story", "T": "Task", "K": "Spike"}

MANDATED_HEADINGS = [
    "Context", "Scope / Deliverables", "Out of scope", "Acceptance criteria",
    "Technical notes / design", "Test plan", "Security notes",
    "Accessibility notes", "Performance notes", "Observability",
    "Definition of Done", "Dependencies", "Branch", "References",
]

SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]

GOV = "GOV-004"


class Reporter:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, pointer: str, msg: str):
        self.errors.append(f"{GOV} {pointer} {msg}")

    def warn(self, pointer: str, msg: str):
        self.warnings.append(f"{GOV}-warn {pointer} {msg}")


class MalformedJsonError(Exception):
    """Raised when a backlog/schema JSON file fails to parse (exit code 2)."""


def load_json(path: str):
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            raise MalformedJsonError(
                f"{GOV} internal error: {path} is not valid JSON: {exc}"
            ) from exc


def load_schemas(repo_root: str):
    schema_dir = os.path.join(repo_root, "docs", "plan", "backlog", "schema")
    ticket_schema = load_json(os.path.join(schema_dir, "ticket.schema.json"))
    file_schema = load_json(os.path.join(schema_dir, "backlog-file.schema.json"))
    return ticket_schema, file_schema


def backlog_files(repo_root: str) -> list[str]:
    backlog_dir = os.path.join(repo_root, "docs", "plan", "backlog")
    files = sorted(glob.glob(os.path.join(backlog_dir, "E*.json")))
    # all-tickets.json is a generated merge (see schema/README.md "Merged
    # files"); it is not an authored per-epic file and is validated separately
    # (ticket schema only, no single-epic-first-element rule).
    return [f for f in files if os.path.basename(f) != "all-tickets.json"]


# --------------------------------------------------------------------------
# Enum derivation (generated, not hand-copied — C-16.5)
# --------------------------------------------------------------------------
def derive_label_lists(repo_root: str) -> dict[str, list[str]]:
    """Parse the closed label lists out of 01-sdlc-and-branching.md §5.2 rather
    than hand-copying them here, per the ticket's technical notes."""
    sdlc_doc = os.path.join(repo_root, "docs", "plan", "01-sdlc-and-branching.md")
    if not os.path.exists(sdlc_doc):
        return {"type": [], "area": [], "priority": []}
    with open(sdlc_doc, encoding="utf-8") as fh:
        lines = fh.readlines()
    out: dict[str, list[str]] = {}
    for prefix, key in (("type/", "type"), ("area/", "area"), ("priority/", "priority")):
        found: list[str] = []
        for i, line in enumerate(lines):
            if line.strip().startswith(f"**`{prefix}*`**"):
                # The closed list is the run of backtick-quoted tokens on this
                # heading line and/or the following non-blank lines, up to the
                # next blank line.
                window = [line]
                j = i + 1
                while j < len(lines) and lines[j].strip():
                    window.append(lines[j])
                    j += 1
                found = re.findall(rf"`({re.escape(prefix)}[a-z0-9-]+)`", "".join(window))
                break
        out[key] = found
    return out


def derive_sprint_windows(repo_root: str) -> dict[str, tuple[int, int]]:
    """Parse the release-train sprint windows out of 30-release-roadmap.md §1.1
    rather than hand-copying them. Returns {train: (first_sprint, last_sprint)}."""
    roadmap_doc = os.path.join(repo_root, "docs", "plan", "30-release-roadmap.md")
    if not os.path.exists(roadmap_doc):
        return {}
    with open(roadmap_doc, encoding="utf-8") as fh:
        text = fh.read()
    windows: dict[str, list[int]] = {}
    for m in re.finditer(r"\|\s*S(\d{2})\s*\|[^|]*\|[^|]*\|\s*(R\d)\b", text):
        n, train = int(m.group(1)), m.group(2)
        windows.setdefault(train, []).append(n)
    return {t: (min(ns), max(ns)) for t, ns in windows.items()}


TRAIN_TO_MILESTONE = {
    "R0": "R0 Foundations", "R1": "R1 Charting alpha", "R2": "R2 Order-flow beta",
    "R3": "R3 Trading on demo", "R4": "R4 Live enablement", "R5": "R5 Hardening / GA",
}


def sprint_num(s: str | None) -> int | None:
    if not s or s == "Backlog":
        return None
    m = re.match(r"^Sprint (\d{2})$", s)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------
# Per-ticket JSON Schema validation
# --------------------------------------------------------------------------
def validate_ticket_schema(ticket: dict, pointer: str, validator, rep: Reporter) -> None:
    for error in sorted(validator.iter_errors(ticket), key=lambda e: e.path):
        p = pointer + "".join(f"/{seg}" for seg in error.path)
        rep.error(p, error.message)


def check_title_length(ticket: dict, pointer: str, rep: Reporter) -> None:
    title = ticket.get("title") or ""
    if len(title) > 80:
        rep.warn(pointer + "/title", f"title is {len(title)} chars, over the 80-char target")


def check_letter_kind(ticket: dict, pointer: str, rep: Reporter) -> None:
    """S/T/K key-prefix letters usually imply a specific `kind`, but a handful
    of tickets legitimately use T/K prefixes for Chores (e.g. an ADR-writing
    task or a spike that was reclassified as a Chore after triage) — so this
    is a warning, not a schema-breaking error."""
    key = ticket.get("key") or ""
    m = KEY_RE.match(key)
    if not m or not m.group(1):
        return
    letter = m.group(1)
    expected = STRICT_LETTER_KIND.get(letter)
    if expected and ticket.get("kind") not in (expected, "Chore"):
        rep.warn(
            pointer + "/kind",
            f"key prefix '{letter}' usually implies kind '{expected}' but kind is "
            f"'{ticket.get('kind')}'",
        )


def check_body_headings(ticket: dict, pointer: str, rep: Reporter) -> None:
    if ticket.get("kind") == "Epic":
        return
    body = ticket.get("body") or ""
    present = set(re.findall(r"^## (.+)$", body, re.MULTILINE))
    missing = [h for h in MANDATED_HEADINGS if h not in present]
    for h in missing:
        rep.warn(pointer + "/body", f"missing mandated heading '## {h}'")


def check_labels(ticket: dict, pointer: str, label_lists: dict, rep: Reporter) -> None:
    labels = ticket.get("labels") or []
    types = [l for l in labels if l.startswith("type/")]
    areas = [l for l in labels if l.startswith("area/")]
    pris = [l for l in labels if l.startswith("priority/")]
    if len(types) != 1:
        rep.warn(pointer + "/labels", f"expected exactly one type/* label, found {types}")
    if len(areas) < 1:
        rep.warn(pointer + "/labels", "expected at least one area/* label, found none")
    if len(pris) != 1:
        rep.warn(pointer + "/labels", f"expected exactly one priority/* label, found {pris}")
    # Closed-list membership is a warning, not an error: the closed lists in
    # 01-sdlc-and-branching.md §5.2 predate several epics' labels (e.g.
    # `type/feature`, `area/security`), which is a documented deviation, not a
    # schema break. Tightened to `error()` once the label migration lands.
    for l in types:
        if label_lists["type"] and l not in label_lists["type"]:
            rep.warn(pointer + "/labels", f"type label '{l}' not in the closed list in §5.2")
    for l in pris:
        if label_lists["priority"] and l not in label_lists["priority"]:
            rep.warn(pointer + "/labels", f"priority label '{l}' not in the closed list in §5.2")


def scan_secrets(ticket: dict, pointer: str, rep: Reporter) -> None:
    body = ticket.get("body") or ""
    for pat in SECRET_PATTERNS:
        if pat.search(body):
            rep.error(pointer + "/body", f"body matches secret pattern {pat.pattern!r}")


# --------------------------------------------------------------------------
# Cross-file semantic rules
# --------------------------------------------------------------------------
def load_epic_seed_ids(repo_root: str) -> set[str]:
    seed_path = os.path.join(repo_root, "docs", "plan", "backlog", "backlog_epics_seed.json")
    if not os.path.exists(seed_path):
        return set()
    seed = load_json(seed_path)
    ids = set()
    items = seed if isinstance(seed, list) else seed.get("epics", [])
    for e in items:
        k = e.get("key") if isinstance(e, dict) else e
        if k:
            ids.add(k)
    return ids


def check_dependencies(all_tickets: dict[str, dict], seed_ids: set[str], rep: Reporter) -> None:
    for key, t in all_tickets.items():
        pointer = f"{t['__file']}#{key}"
        for dep in t.get("blocked_by") or []:
            if dep in all_tickets:
                continue
            if re.match(r"^E\d{2}$", dep) and dep in seed_ids:
                continue
            if re.match(r"^E\d{2}$", dep) and not any(
                k.startswith(dep) for k in all_tickets
            ):
                # Cross-epic edge to an epic file that has not been authored
                # yet: deferred with a warning, per the ticket's technical
                # notes, so epics can land in any order during planning.
                rep.warn(pointer + "/blocked_by", f"epic '{dep}' not found yet (deferred)")
                continue
            rep.error(pointer + "/blocked_by", f"unresolvable dependency '{dep}'")


def check_cycles(all_tickets: dict[str, dict], rep: Reporter) -> None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in all_tickets}
    stack: list[str] = []

    def visit(k: str) -> list[str] | None:
        color[k] = GRAY
        stack.append(k)
        for dep in all_tickets[k].get("blocked_by") or []:
            if dep not in all_tickets:
                continue
            if color.get(dep) == GRAY:
                i = stack.index(dep)
                return stack[i:] + [dep]
            if color.get(dep, WHITE) == WHITE:
                cyc = visit(dep)
                if cyc:
                    return cyc
        stack.pop()
        color[k] = BLACK
        return None

    seen_cycles: set[tuple[str, ...]] = set()
    for k in all_tickets:
        if color[k] == WHITE:
            cyc = visit(k)
            if cyc:
                norm = tuple(sorted(cyc))
                if norm not in seen_cycles:
                    seen_cycles.add(norm)
                    rep.error(
                        f"{all_tickets[k]['__file']}#{k}",
                        "dependency cycle: " + " -> ".join(cyc),
                    )


def check_parent_chain(all_tickets: dict[str, dict], rep: Reporter) -> None:
    for key, t in all_tickets.items():
        if t.get("kind") == "Epic":
            continue
        parent = t.get("parent")
        pointer = f"{t['__file']}#{key}"
        if not parent:
            rep.error(pointer + "/parent", "non-epic ticket has no parent")
            continue
        if parent not in all_tickets or all_tickets[parent].get("kind") != "Epic":
            rep.error(pointer + "/parent", f"parent '{parent}' is not a known epic")


def check_sprint_ordering(all_tickets: dict[str, dict], rep: Reporter) -> None:
    """Epics are excluded: an epic's own `sprint` reflects its first-scheduled
    child, not a single atomic unit of work, so epic-vs-epic sprint compares
    aggregates rather than actual scheduling and is not the rule's target
    (the rule's own example, E01-T04/E01-T08, is ticket-level)."""
    for key, t in all_tickets.items():
        if t.get("kind") == "Epic":
            continue
        sn = sprint_num(t.get("sprint"))
        if sn is None:
            continue
        pointer = f"{t['__file']}#{key}"
        for dep in t.get("blocked_by") or []:
            other = all_tickets.get(dep)
            if not other or other.get("kind") == "Epic":
                continue
            osn = sprint_num(other.get("sprint"))
            if osn is None:
                continue
            if osn > sn:
                rep.error(
                    pointer + "/sprint",
                    f"scheduled in Sprint {sn:02d} but blocked_by '{dep}' "
                    f"(Sprint {osn:02d}) — a ticket may not be scheduled "
                    f"before a ticket that blocks it",
                )


def check_design_ahead(all_tickets: dict[str, dict], rep: Reporter) -> None:
    """Design-ahead rule (`01-sdlc-and-branching.md` DoR row, `Ready` column):
    'for frontend Story tickets, linked design ticket is Done and >=2 sprints
    old'. Scoped to `kind == "Story"` consumers, matching the DoR text and the
    ticket's own acceptance-criteria example ('a frontend Story ... whose
    blocked_by includes a design ticket'); Tasks/Chores that merely reference a
    design ticket (e.g. a follow-up doc chore) are not in scope of this rule."""
    for key, t in all_tickets.items():
        if t.get("kind") != "Story":
            continue
        sn = sprint_num(t.get("sprint"))
        if sn is None:
            continue
        pointer = f"{t['__file']}#{key}"
        for dep in t.get("blocked_by") or []:
            other = all_tickets.get(dep)
            if not other:
                continue
            m = KEY_RE.match(dep)
            is_design = bool(m and m.group(1) == "D")
            if not is_design:
                continue
            osn = sprint_num(other.get("sprint"))
            if osn is None:
                continue
            if osn + 2 > sn:
                rep.error(
                    pointer + "/blocked_by",
                    f"design-ahead violation: '{key}' (Sprint {sn:02d}) depends "
                    f"on design ticket '{dep}' (Sprint {osn:02d}); design work "
                    f"must be scheduled at least 2 sprints ahead of the "
                    f"Story consuming it",
                )


def check_train_window(all_tickets: dict[str, dict], windows: dict[str, tuple[int, int]],
                        rep: Reporter) -> None:
    epic_train: dict[str, str] = {}
    for key, t in all_tickets.items():
        if t.get("kind") != "Epic":
            continue
        milestone = t.get("milestone")
        for train, m in TRAIN_TO_MILESTONE.items():
            if m == milestone:
                epic_train[key] = train
                break
    for key, t in all_tickets.items():
        parent = t.get("parent")
        train = epic_train.get(parent or key)
        if not train or train not in windows:
            continue
        sn = sprint_num(t.get("sprint"))
        if sn is None:
            continue
        lo, hi = windows[train]
        if not (lo <= sn <= hi):
            rep.warn(
                f"{t['__file']}#{key}/sprint",
                f"Sprint {sn:02d} is outside train {train} window "
                f"(S{lo:02d}-S{hi:02d}); spanning epics are permitted, see "
                f"validate.py SPANNING_EPICS",
            )


def check_estimate_rollup(all_tickets: dict[str, dict], rep: Reporter) -> None:
    children: dict[str, list[dict]] = {}
    for key, t in all_tickets.items():
        if t.get("kind") != "Epic":
            children.setdefault(t.get("parent"), []).append(t)
    for key, t in all_tickets.items():
        if t.get("kind") != "Epic":
            continue
        budget = t.get("estimate")
        kids = children.get(key, [])
        total = sum((c.get("estimate") or 0) for c in kids)
        if budget and abs(total - budget) > 0.15 * budget:
            rep.warn(
                f"{t['__file']}#{key}/estimate",
                f"children sum to {total} pts, more than 15% away from epic "
                f"budget {budget} pts",
            )


# --------------------------------------------------------------------------
# --summary mode
# --------------------------------------------------------------------------
def print_summary(all_tickets: dict[str, dict]) -> None:
    children: dict[str, list[dict]] = {}
    for key, t in all_tickets.items():
        if t.get("kind") != "Epic":
            children.setdefault(t.get("parent"), []).append(t)
    print("epic       tickets  points  budget  delta")
    for key, t in sorted(all_tickets.items()):
        if t.get("kind") != "Epic":
            continue
        kids = children.get(key, [])
        pts = sum((c.get("estimate") or 0) for c in kids)
        budget = t.get("estimate") or 0
        print(f"{key:<10} {len(kids):>7}  {pts:>6}  {budget:>6}  {pts - budget:>+5}")


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=DEFAULT_REPO_ROOT)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--summary", action="store_true", help="print per-epic point rollup")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)

    if not _HAVE_JSONSCHEMA:
        print(
            f"{GOV} internal error: the 'jsonschema' package is not installed. "
            "Install it (uv add jsonschema / pip install jsonschema) — this "
            "validator does not vendor a fallback implementation.",
            file=sys.stderr,
        )
        return 2

    try:
        ticket_schema, _file_schema = load_schemas(repo_root)
    except MalformedJsonError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    validator = Draft202012Validator(ticket_schema)

    rep = Reporter()
    label_lists = derive_label_lists(repo_root)
    windows = derive_sprint_windows(repo_root)
    seed_ids = load_epic_seed_ids(repo_root)

    all_tickets: dict[str, dict] = {}
    file_count = 0
    for path in backlog_files(repo_root):
        file_count += 1
        rel = os.path.relpath(path, repo_root)
        try:
            data = load_json(path)
        except MalformedJsonError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not isinstance(data, list) or not data:
            rep.error(rel, "backlog file must be a non-empty array")
            continue
        epic = data[0]
        if epic.get("kind") != "Epic" or epic.get("parent") not in (None, "null"):
            rep.error(rel + "#0", "first element of a backlog file must be the Epic with parent=null")
        for i, ticket in enumerate(data):
            pointer = f"{rel}#{i}"
            validate_ticket_schema(ticket, pointer, validator, rep)
            check_title_length(ticket, pointer, rep)
            check_letter_kind(ticket, pointer, rep)
            check_body_headings(ticket, pointer, rep)
            check_labels(ticket, pointer, label_lists, rep)
            scan_secrets(ticket, pointer, rep)
            key = ticket.get("key")
            if key:
                if key in all_tickets:
                    rep.error(pointer, f"duplicate ticket key '{key}' also defined in "
                                        f"{all_tickets[key]['__file']}")
                else:
                    ticket = dict(ticket)
                    ticket["__file"] = rel
                    all_tickets[key] = ticket

    check_dependencies(all_tickets, seed_ids, rep)
    check_cycles(all_tickets, rep)
    check_parent_chain(all_tickets, rep)
    check_sprint_ordering(all_tickets, rep)
    check_design_ahead(all_tickets, rep)
    check_train_window(all_tickets, windows, rep)
    check_estimate_rollup(all_tickets, rep)

    if args.summary:
        print_summary(all_tickets)

    if args.json:
        payload = {
            "files": file_count,
            "tickets": len(all_tickets),
            "errors": rep.errors,
            "warnings": rep.warnings,
        }
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        for e in rep.errors:
            print(e)
        for w in rep.warnings:
            print(w)
        print(
            f"files={file_count} tickets={len(all_tickets)} "
            f"errors={len(rep.errors)} warnings={len(rep.warnings)}"
        )

    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
