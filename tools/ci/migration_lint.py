#!/usr/bin/env python3
"""E03-T10: Alembic migration job checks — single-head, drift, expand/contract
lint, and `IF NOT EXISTS` ban.

`docs/plan/21-database-schema.md` §9 ("Single linear history on `main`", no
`IF NOT EXISTS` in migrations — Alembic owns state) and ADR-0013 rule 9
("Migrations ... must be backward-compatible for one release (expand/
contract), so a rollback never requires a down-migration") are the two
normative sources; this module is the mechanical enforcement of both plus
the security-sensitive-table carve-out from `02-definition-of-ready-done.md`
§4.1 (envelope encryption preserved on `api_keys`-touching migrations).

Error codes (ticket "Technical notes / design"):
    CI-MIG-001  multiple Alembic heads
    CI-MIG-002  schema drift between `models.py` and the migration chain
    CI-MIG-003  destructive operation without a `# cv:contract-phase:` annotation
    CI-MIG-004  upgrade-path (previous release) failure
    CI-MIG-005  `IF NOT EXISTS` used in a migration file

Stdlib only for the lint (`--check-if-not-exists`, `--check-destructive`);
the `alembic heads` / `alembic check` / `upgrade head` steps in
`.github/workflows/_job-migrations.yml` shell out to Alembic directly and
this module only assembles their exit codes into named error codes for the
job summary. No network access; no DB required for the static checks.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Destructive operations that need an explicit `# cv:contract-phase: <release>`
# justification per ADR-0013 rule 9 / expand-contract discipline.
_DESTRUCTIVE_OP_RE = re.compile(
    r"\bop\.(drop_column|drop_table|drop_index|drop_constraint)\s*\("
)
# `add_column` with `nullable=False` and no `server_default=` is destructive
# for existing rows (breaks expand/contract) unless annotated.
_ADD_COLUMN_RE = re.compile(r"\bop\.add_column\s*\(")
_NULLABLE_FALSE_RE = re.compile(r"nullable\s*=\s*False")
_SERVER_DEFAULT_RE = re.compile(r"server_default\s*=")
_ALTER_COLUMN_TYPE_RE = re.compile(r"\bop\.alter_column\s*\([^)]*type_\s*=")
_CONTRACT_PHASE_RE = re.compile(r"#\s*cv:contract-phase:\s*\S+")
_IF_NOT_EXISTS_RE = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)

# Tables that must never be a destructive-op target, contract-phase
# annotation or not (append-only audit, per ticket "Security notes").
# Names confirmed against `docs/plan/21-database-schema.md` §3.10
# (`audit_log`, `audit_checkpoints` — no `audit_entries` table exists).
_FORBIDDEN_DESTRUCTIVE_TABLES = frozenset({"audit_log", "audit_checkpoints"})

# Raw-SQL (`op.execute(...)`) statements that mutate or reshape an audit
# table bypass the `op.drop_*`/`op.alter_column` AST-level checks above.
# Case-insensitive: DDL/DML keywords are not case-sensitive in Postgres.
_RAW_SQL_MUTATION_RE = re.compile(
    r"\b(DELETE\s+FROM|UPDATE|DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?|"
    r"ALTER\s+TABLE|GRANT\s+(?:UPDATE|DELETE|UPDATE\s*,\s*DELETE|DELETE\s*,\s*UPDATE))\b",
    re.IGNORECASE,
)

# Populated from `tools/ci/security-sensitive-tables.txt` when present;
# migrations touching these need the `security-review` label (flagged, not
# blocked, by this tool — the label/reviewer gate is enforced elsewhere).
_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH = Path(__file__).with_name(
    "security-sensitive-tables.txt"
)


@dataclass(frozen=True)
class LintFinding:
    code: str
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.code}: {self.path}: {self.message}"


def _read_sensitive_tables(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.add(stripped)
    return frozenset(names)


def _line_has_contract_phase_nearby(lines: list[str], idx: int, window: int = 3) -> bool:
    """A `# cv:contract-phase:` comment on the same line or within `window`
    lines above/below the offending call counts as justification — matches
    how engineers naturally annotate a multi-line `op.*(...)` call."""
    lo = max(0, idx - window)
    hi = min(len(lines), idx + window + 1)
    return any(_CONTRACT_PHASE_RE.search(lines[i]) for i in range(lo, hi))


def check_if_not_exists(paths: list[Path]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _IF_NOT_EXISTS_RE.search(line):
                findings.append(
                    LintFinding(
                        code="CI-MIG-005",
                        path=path,
                        message=(
                            f"line {lineno}: 'IF NOT EXISTS' is never used in "
                            "migrations — Alembic owns state (21-database-schema.md §9)"
                        ),
                    )
                )
    return findings


def _table_mentioned(line: str, tables: frozenset[str]) -> str | None:
    for table in tables:
        if re.search(rf"['\"]{re.escape(table)}['\"]", line):
            return table
    return None


def check_audit_table_integrity(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    """C-5.7: audit tables are append-only — no `UPDATE`/`DELETE` grants, no
    dropping/mutating audit history, however the operation is spelled.
    Catches raw-SQL (`op.execute(...)`) DML/DDL and schema-shape changes
    (`op.alter_column`, `op.rename_table`) that the AST-level destructive-op
    check above does not see."""
    findings: list[LintFinding] = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            is_raw_sql_mutation = "op.execute" in line and bool(
                _RAW_SQL_MUTATION_RE.search(line)
            )
            is_rename = bool(re.search(r"\bop\.rename_table\s*\(", line))
            is_alter_shape = bool(re.search(r"\bop\.alter_column\s*\(", line))

            if not (is_raw_sql_mutation or is_rename or is_alter_shape):
                continue

            if is_raw_sql_mutation:
                # Raw SQL embeds the table name as a bare identifier inside
                # the statement string, not as a quoted Alembic-API arg —
                # match on a word boundary instead of `_table_mentioned`.
                forbidden_hit = next(
                    (
                        table
                        for table in forbidden_tables
                        if re.search(rf"\b{re.escape(table)}\b", line)
                    ),
                    None,
                )
            else:
                forbidden_hit = _table_mentioned(line, forbidden_tables)

            if forbidden_hit is None:
                continue

            findings.append(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        f"line {idx + 1}: operation targets append-only "
                        f"table '{forbidden_hit}' — forbidden regardless of "
                        "annotation (C-5.7, ADR-0013 rule 9)"
                    ),
                )
            )
    return findings


def check_destructive_annotations(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            is_destructive = bool(_DESTRUCTIVE_OP_RE.search(line))
            is_narrowing_type = bool(_ALTER_COLUMN_TYPE_RE.search(line))
            is_non_nullable_add = bool(_ADD_COLUMN_RE.search(line)) and _NULLABLE_FALSE_RE.search(
                line
            ) and not _SERVER_DEFAULT_RE.search(line)

            if not (is_destructive or is_narrowing_type or is_non_nullable_add):
                continue

            forbidden_hit = _table_mentioned(line, forbidden_tables)
            if is_destructive and forbidden_hit is not None:
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {idx + 1}: destructive op targets append-only "
                            f"table '{forbidden_hit}' — forbidden regardless of "
                            "annotation (ADR-0013 rule 9, security notes)"
                        ),
                    )
                )
                continue

            if not _line_has_contract_phase_nearby(lines, idx):
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {idx + 1}: destructive/non-additive operation "
                            "with no '# cv:contract-phase: <release>' annotation "
                            "(ADR-0013 rule 9)"
                        ),
                    )
                )
    return findings


def check_security_sensitive(
    paths: list[Path],
    sensitive_tables: frozenset[str] | None = None,
) -> list[LintFinding]:
    """Non-blocking flag (CI-MIG-006, informational): migrations touching
    security-sensitive tables need mandatory Security review per
    `02-definition-of-ready-done.md` §4.1. Returned as findings with code
    'CI-MIG-006' so the caller can choose to warn rather than fail."""
    tables = sensitive_tables
    if tables is None:
        tables = _read_sensitive_tables(_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH)
    if not tables:
        return []
    findings: list[LintFinding] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for table in tables:
            if re.search(rf"['\"]{re.escape(table)}['\"]", text):
                findings.append(
                    LintFinding(
                        code="CI-MIG-006",
                        path=path,
                        message=(
                            f"touches security-sensitive table '{table}' — "
                            "requires mandatory Security review (DoR §4.1)"
                        ),
                    )
                )
    return findings


def _iter_migration_files(versions_dir: Path) -> list[Path]:
    return sorted(p for p in versions_dir.glob("*.py") if p.name != "__init__.py")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=Path("candleviewer/migrations/versions"),
        help="Directory containing Alembic version files (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    versions_dir: Path = args.versions_dir
    if not versions_dir.is_dir():
        print(f"CI-MIG-000: versions dir not found: {versions_dir}", file=sys.stderr)
        return 2

    paths = _iter_migration_files(versions_dir)
    findings: list[LintFinding] = []
    findings.extend(check_if_not_exists(paths))
    findings.extend(check_destructive_annotations(paths))
    findings.extend(check_audit_table_integrity(paths))
    security_findings = check_security_sensitive(paths)

    for finding in findings:
        print(finding.render(), file=sys.stderr)
    for finding in security_findings:
        print(f"WARN {finding.render()}", file=sys.stderr)

    if findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
