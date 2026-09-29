#!/usr/bin/env python3
"""CI-PROT-004: verify every branch-protection bypass actor is registered in
`.github/rulesets/bypass-register.md` with a non-expired review date
(CONSTITUTION.md C-9.1, C-10.1; `docs/plan/01-sdlc-and-branching.md` §7-§8;
E03-T13).

The register is a markdown table; this checker parses its `| Actor | ... |
Review date |` rows and fails when:
  * the file is missing or has no parsed rows (CI-PROT-004: empty register);
  * a row's review date is in the past relative to `--today` (default:
    today's UTC date) — a stale bypass grant is a finding, not silently
    renewed;
  * a row's review date is more than one quarter (`MAX_REVIEW_HORIZON_DAYS`)
    beyond `--today` — the register's own rule 2 caps review dates at one
    quarter out so a far-future date (e.g. `2099-01-01`) can never stand in
    as a permanent, un-reviewed bypass;
  * a row's review date cannot be parsed as `YYYY-MM-DD`.

This script does not (and cannot, without a repo-administration-scoped
token) enumerate live GitHub bypass actors; reconciling the register against
live reality is a manual review step noted in the register's own rules
section. What this script guarantees is that the register itself stays
internally honest over time.

Exit codes: 0 clean, 1 finding(s), 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

DEFAULT_REGISTER_PATH = ".github/rulesets/bypass-register.md"

# Rule 2 in the register: "no more than one quarter (13 sprints) out". One
# sprint is a week (docs/plan/01-sdlc-and-branching.md), so 13 sprints is
# 13*7 = 91 days; a review date beyond that horizon is a finding, not a
# permanent bypass hiding behind a far-future date such as 2099-01-01.
MAX_REVIEW_HORIZON_DAYS = 13 * 7

# A markdown table data row: | actor | scope | justification | review date |
ROW_RE = re.compile(r"^\|(?!---)(.+)\|\s*$")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class RegisterError(Exception):
    """Raised for unreadable/malformed register files (exit 2)."""


def load_rows(path: str) -> list[list[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError as exc:
        raise RegisterError(f"file not found: {path}") from exc

    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        stripped = line.rstrip("\n")
        if stripped.strip().startswith("| Actor"):
            in_table = True
            continue
        if in_table:
            text = stripped.strip()
            if not text:
                # A table is allowed to be split by a blank line (e.g. a
                # header row followed by a blank separator before the data
                # rows resume); skip it rather than silently ending the
                # table and dropping every row after it.
                continue
            if text.startswith("|---"):
                # The tight `|---|---|` separator row: ROW_RE's negative
                # lookahead rejects it outright (it would otherwise be
                # treated as "end of table"), so skip it explicitly here.
                continue
            match = ROW_RE.match(text)
            if not match:
                # A genuine non-table line (prose, next heading, etc.) ends
                # the table.
                break
            cells = [c.strip() for c in match.group(1).split("|")]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                # The header/body separator row, possibly widened with
                # alignment colons/extra dashes/spaces by a markdown
                # formatter (`| --- | --- |` or wider) — not a data row.
                continue
            rows.append(cells)
    return rows


def check_rows(rows: list[list[str]], today: dt.date) -> list[str]:
    errors: list[str] = []
    if not rows:
        errors.append(
            "CI-PROT-004: bypass register has no rows — every bypass actor must be named"
        )
        return errors

    for row in rows:
        if len(row) < 4:
            errors.append(f"CI-PROT-004: malformed row (expected >=4 cells): {row!r}")
            continue
        actor, _scope, _justification, review_date_cell = row[0], row[1], row[2], row[3]
        date_match = DATE_RE.search(review_date_cell)
        if not date_match:
            errors.append(
                f"CI-PROT-004: row for {actor!r} has no parseable review date: {review_date_cell!r}"
            )
            continue
        review_date = dt.date.fromisoformat(date_match.group(1))
        if review_date < today:
            errors.append(
                f"CI-PROT-004: bypass register row for {actor!r} is stale "
                f"(review date {review_date.isoformat()} has passed as of {today.isoformat()})"
            )
            continue
        horizon = today + dt.timedelta(days=MAX_REVIEW_HORIZON_DAYS)
        if review_date > horizon:
            errors.append(
                f"CI-PROT-004: bypass register row for {actor!r} has a review date "
                f"{review_date.isoformat()} more than one quarter "
                f"({MAX_REVIEW_HORIZON_DAYS} days) beyond {today.isoformat()} — "
                "a far-future date cannot be used as a permanent bypass (rule 2)"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", default=DEFAULT_REGISTER_PATH)
    parser.add_argument(
        "--today",
        default=None,
        help="override 'today' as YYYY-MM-DD (for deterministic tests); defaults to UTC today",
    )
    args = parser.parse_args(argv)

    today = (
        dt.date.fromisoformat(args.today)
        if args.today
        else dt.datetime.now(dt.timezone.utc).date()
    )

    try:
        rows = load_rows(args.register)
        errors = check_rows(rows, today)
    except RegisterError as exc:
        print(f"check-bypass-register: {exc}", file=sys.stderr)
        return 2

    if not errors:
        print("check-bypass-register: clean")
        return 0

    for err in errors:
        print(err, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
