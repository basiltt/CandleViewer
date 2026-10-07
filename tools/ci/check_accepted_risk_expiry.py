"""Accepted-risk expiry enforcement (E49-T03, CONSTITUTION C-12.3, 32-risk-register.md §1.3).

Four sources are checked and the check FAILS when any expiry is on or before
`today` (same exclusive semantics as `security_gate.py` CI-SEC-004), and WARNS
when one falls inside the next `WARN_DAYS` days:

1. `security/accepted-risks.yaml` entries (`expires`, `approver`, `id`).
2. `Status **Accepted** (expires YYYY-MM-DD)` lines of every `### RSK-nnn` entry
   in `docs/plan/32-risk-register.md`.
3. In-source `nosemgrep: ... review=YYYY-MM-DD` suppressions (grammar and the
   `REVIEW_MAX_DAYS` cap shared with `suppressions.py`); a marker without `review=`
   fails. Files outside SCAN_SUFFIXES holding a marker are listed as "not scanned".

4. Exception rows (`| EX-nn | ... | approved-by | YYYY-MM-DD | ticket |`) of
   `docs/plan/04-security-program.md` §16.2 (exceptions not expressible as scanner findings).

An unparseable source is an error, never a skip: a skipped entry is exactly the
one that would hide an expired acceptance.

Usage: python tools/ci/check_accepted_risk_expiry.py [--today YYYY-MM-DD]
       [--fail-on-warn] [--report PATH] [--root DIR]
Exit: 0 ok (warnings allowed) | 1 expired/unparseable | 2 warnings with --fail-on-warn.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.suppressions import REVIEW_MAX_DAYS, field, parse_nosemgrep

WARN_DAYS = 30
REGISTER = Path("docs/plan/32-risk-register.md")
SECURITY_PLAN = Path("docs/plan/04-security-program.md")
EX_ROW_RE = re.compile(r"^\|\s*(?P<id>EX-\d+)\s*\|")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YAML_PATH = Path("security/accepted-risks.yaml")
SCAN_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs")
# Gate self-tests and rule fixtures quote the marker as test data, not as an acceptance.
SKIP_PREFIXES = ("scripts/tests/", "tests/ci-gates/", ".semgrep/", "docs/")
MARKER_RE = re.compile(r"(?:#|//|--)[ 	]*nosemgrep:")
HEADING_RE = re.compile(r"^### (RSK-\d+)\b")
STATUS_RE = re.compile(r"Status \*\*(?P<s>[^*]+)\*\*(?P<rest>.*)$")
OWNER_RE = re.compile(r"Owner \*\*(?P<o>[^*]+)\*\*")
EXPIRES_RE = re.compile(r"\(expires (?P<d>[^)]*)\)")


@dataclass(frozen=True)
class Item:
    source: str  # yaml | register | in-source
    ident: str
    owner: str
    expires: date
    where: str


@dataclass
class Result:
    items: list[Item]
    errors: list[str]
    not_scanned: list[str] = dataclass_field(default_factory=list)

    def classify(self, today: date) -> tuple[list[str], list[str]]:
        """(failures, warnings) as human-readable lines."""
        fails = list(self.errors)
        warns: list[str] = []
        for it in sorted(self.items, key=lambda i: (i.expires, i.ident)):
            left = (it.expires - today).days
            tag = f"[{it.source}] {it.ident} owner={it.owner} expires={it.expires} ({it.where})"
            if left <= 0:
                fails.append(f"EXPIRED {tag}: elapsed {-left} day(s)")
            elif it.source == "in-source" and left > REVIEW_MAX_DAYS:
                fails.append(
                    f"TOO-FAR [in-source] {tag}: {left} days ahead, cap is {REVIEW_MAX_DAYS}"
                )
            elif left < WARN_DAYS:
                warns.append(f"WARN {tag}: {left} day(s) left")
        return fails, warns


def _to_date(raw: object) -> date | None:
    if isinstance(raw, datetime):
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def parse_yaml(path: Path) -> Result:
    res = Result([], [])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = data["entries"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        res.errors.append(f"UNPARSEABLE {path}: {exc}")
        return res
    for i, e in enumerate(entries or []):
        ident = (
            str(e.get("id", f"<entry {i}>")) if isinstance(e, dict) else f"<entry {i}>"
        )
        if not isinstance(e, dict):
            res.errors.append(f"UNPARSEABLE {path}: entry {i} is not a mapping")
            continue
        exp = _to_date(e.get("expires"))
        owner = str(e.get("approver") or "").strip()
        if exp is None:
            res.errors.append(
                f"MISSING-EXPIRY [yaml] {ident}: 'expires' absent or not YYYY-MM-DD"
            )
            continue
        if not owner:
            res.errors.append(f"MISSING-OWNER [yaml] {ident}: 'approver' absent")
            continue
        res.items.append(Item("yaml", ident, owner, exp, YAML_PATH.as_posix()))
    return res


def parse_register(path: Path) -> Result:
    res = Result([], [])
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        res.errors.append(f"UNPARSEABLE {path}: {exc}")
        return res
    entries = 0
    for n, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        entries += 1
        rid = m.group(1)
        meta = next((x for x in lines[n + 1 : n + 6] if x.startswith("`Risk:")), None)
        st = STATUS_RE.search(meta) if meta else None
        if meta is None or st is None:
            res.errors.append(
                f"UNPARSEABLE [register] {rid}: no `Risk:` line with a Status"
            )
            continue
        if not st.group("s").strip().lower().startswith("accepted"):
            continue
        owner_m = OWNER_RE.search(meta)
        exp_m = EXPIRES_RE.search(st.group("rest"))
        exp = _to_date(exp_m.group("d").strip()) if exp_m else None
        if owner_m is None:
            res.errors.append(f"MISSING-OWNER [register] {rid}: Accepted but no Owner")
        elif exp is None:
            res.errors.append(
                f"MISSING-EXPIRY [register] {rid}: Accepted without a valid '(expires YYYY-MM-DD)'"
            )
        else:
            res.items.append(
                Item(
                    "register",
                    rid,
                    owner_m.group("o"),
                    exp,
                    f"{REGISTER.as_posix()}:{n + 1}",
                )
            )
    if entries == 0:
        res.errors.append(f"UNPARSEABLE {path}: no '### RSK-nnn' entries found")
    return res


def parse_exceptions(path: Path) -> Result:
    """`EX-nn` rows: approver = cell before the expiry, expiry = the ISO-date cell."""
    res = Result([], [])
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        res.errors.append(f"UNPARSEABLE {path}: {exc}")
        return res
    for n, line in enumerate(lines, 1):
        m = EX_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        idx = next((i for i, c in enumerate(cells) if ISO_RE.match(c)), None)
        exp = _to_date(cells[idx]) if idx is not None else None
        owner = re.sub(r"[*]", "", cells[idx - 1]).strip() if idx else ""
        where = f"{SECURITY_PLAN.as_posix()}:{n}"
        if exp is None:
            res.errors.append(
                f"MISSING-EXPIRY [exception] {m.group('id')}: no YYYY-MM-DD cell"
            )
        elif not owner:
            res.errors.append(
                f"MISSING-OWNER [exception] {m.group('id')}: no approver cell"
            )
        else:
            res.items.append(Item("exception", m.group("id"), owner[:60], exp, where))
    return res


def _tracked_files(root: Path) -> list[Path]:
    """All tracked files (callers filter by suffix)."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        files = [root / p for p in out]
    except (OSError, subprocess.CalledProcessError):
        files = [
            p
            for p in root.rglob("*")
            if "node_modules" not in p.parts and ".venv" not in p.parts
        ]
    return [p for p in files if p.is_file()]


def _has_marker(path: Path) -> bool:
    try:
        if path.stat().st_size > 1_000_000:
            return False
        return "nosemgrep:" in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def parse_in_source(root: Path, covered: frozenset[str] = frozenset()) -> Result:
    res = Result([], [])
    for path in _tracked_files(root):
        if path.name == "check_accepted_risk_expiry.py":
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix not in SCAN_SUFFIXES:
            if not rel.startswith(SKIP_PREFIXES) and _has_marker(path):
                res.not_scanned.append(rel)
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            marker = MARKER_RE.search(line)
            if (
                marker is None
                or marker.start()
                and line[: marker.start()].count('"') % 2
            ):
                continue  # no marker, or the marker text sits inside a string literal
            rel = path.relative_to(root).as_posix()
            if rel.startswith(SKIP_PREFIXES):
                continue
            for mk in parse_nosemgrep(line):
                raw = field(mk.rest, "review")
                # a comment-only marker suppresses the next line, so the finding id may use n+1
                lines_ok = (
                    (n, n + 1) if line.lstrip().startswith(("--", "#", "//")) else (n,)
                )
                if (
                    raw is None
                    and any(  # prose after the rule parses as extra rule tokens
                        f"semgrep.{r}:{rel}:{k}" in covered
                        for r in mk.rules
                        for k in lines_ok
                    )
                ):
                    continue  # un-fielded marker covered by a live accepted-risks.yaml entry
                if raw is None:
                    res.errors.append(
                        f"MISSING-REVIEW [in-source] {rel}:{n}: no review= (CI-SEC-006 grammar)"
                    )
                    continue
                exp = _to_date(raw)
                owner = field(mk.rest, "owner") or ""
                where = f"{rel}:{n}"
                if exp is None:
                    res.errors.append(
                        f"MISSING-EXPIRY [in-source] {where}: review={raw!r} invalid"
                    )
                elif not owner:
                    res.errors.append(f"MISSING-OWNER [in-source] {where}: no owner=")
                else:
                    res.items.append(
                        Item("in-source", ",".join(mk.rules), owner, exp, where)
                    )
    return res


def run(root: Path, today: date) -> tuple[Result, list[str], list[str]]:
    yaml_res = parse_yaml(root / YAML_PATH)
    covered = frozenset(i.ident for i in yaml_res.items if i.expires > today)
    parts = [
        yaml_res,
        parse_register(root / REGISTER),
        parse_exceptions(root / SECURITY_PLAN),
        parse_in_source(root, covered),
    ]
    merged = Result(
        [i for p in parts for i in p.items],
        [e for p in parts for e in p.errors],
        [x for p in parts for x in p.not_scanned],
    )
    seen: set[tuple[str, str]] = set()
    for it in merged.items:
        if it.source in ("yaml", "register", "exception"):
            if (it.source, it.ident) in seen:
                merged.errors.append(
                    f"DUPLICATE-ID [{it.source}] {it.ident}: appears twice"
                )
            seen.add((it.source, it.ident))
    fails, warns = merged.classify(today)
    return merged, fails, warns


def render_report(res: Result, fails: list[str], warns: list[str], today: date) -> str:
    by: dict[str, int] = {}
    for it in res.items:
        by[it.source] = by.get(it.source, 0) + 1
    out = [f"# Accepted-risk expiry report ({today.isoformat()})", ""]
    out.append(
        "Checked: "
        + (", ".join(f"{k}={v}" for k, v in sorted(by.items())) or "nothing")
    )
    out += ["", f"## Failures ({len(fails)})"]
    out += [f"- {x}" for x in fails] or ["- none"]
    out += ["", f"## Expiring within {WARN_DAYS} days ({len(warns)})"]
    out += [f"- {x}" for x in warns] or ["- none"]
    out += ["", f"## Not scanned ({len(res.not_scanned)})"]
    out += [f"- {x} (unscanned file type)" for x in res.not_scanned] or ["- none"]
    out += [
        "",
        (
            "Re-decide (re-accept with rationale+trigger / mitigate / escalate / retire); "
            "never bare-extend. Register: docs/plan/32-risk-register.md §1.3."
        ),
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--today", help="ISO date override (tests); default today UTC")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument(
        "--fail-on-warn", action="store_true", help="exit 2 if only warnings"
    )
    ap.add_argument("--report", type=Path, help="write a markdown report here")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else datetime.now(UTC).date()
    res, fails, warns = run(args.root, today)
    for line in [*fails, *warns]:
        print(line)
    print(
        f"accepted-risk expiry: {len(res.items)} checked, {len(fails)} failing, "
        f"{len(warns)} warning(s), {len(res.not_scanned)} file(s) not scanned"
    )
    if args.report:
        args.report.write_text(
            render_report(res, fails, warns, today), encoding="utf-8"
        )
    if fails:
        return 1
    return 2 if (warns and args.fail_on_warn) else 0


if __name__ == "__main__":
    sys.exit(main())
