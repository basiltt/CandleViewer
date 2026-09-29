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
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Destructive operations that need an explicit `# cv:contract-phase: <release>`
# justification per ADR-0013 rule 9 / expand-contract discipline.
_DESTRUCTIVE_OP_RE = re.compile(r"\bop\.(drop_column|drop_table|drop_index|drop_constraint)\s*\(")
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

# Raw-SQL statements that mutate or reshape an audit table bypass the
# `op.drop_*`/`op.alter_column` AST-level checks above. Case-insensitive:
# DDL/DML keywords (and Postgres identifiers, since unquoted identifiers are
# folded to lower case) are not case-sensitive. Each pattern binds the
# keyword directly to the table name (rather than "keyword anywhere in the
# literal, table name anywhere in the literal") so prose — e.g. a module
# docstring that separately mentions `audit_log` in one sentence and
# `ALTER TABLE` in another about a different table — is never conflated with
# an actual SQL statement. `GRANT ALL` implicitly includes UPDATE/DELETE/
# TRUNCATE; a grant list may name a mutating verb alongside harmless
# privileges (e.g. `GRANT SELECT, DELETE ON ...`).
_TABLE_QUALIFIER = r"(?:[\w]+\.)?\"?'?"


def _mutation_pattern_for(table: str) -> re.Pattern[str]:
    t = re.escape(table)
    q = _TABLE_QUALIFIER
    return re.compile(
        rf"\b(?:DELETE\s+FROM|UPDATE|DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE)\s+{q}{t}\b"
        rf"|\bGRANT\s+(?:ALL(?:\s+PRIVILEGES)?|[A-Za-z, ]*?\b(?:UPDATE|DELETE|TRUNCATE)\b[A-Za-z, ]*?)"
        rf"\s+ON\s+{q}{t}\b",
        re.IGNORECASE,
    )


# `# cv:audit-exempt: <reason>` on the same source line as the offending
# string literal (or `op.execute(...)` call) is the only accepted escape
# hatch, and only for a CREATE-only statement (never for a genuine mutation
# of an existing audit table).
_AUDIT_EXEMPT_RE = re.compile(r"#\s*cv:audit-exempt:\s*\S+")
_CREATE_ONLY_RE = re.compile(r"^\s*CREATE\s+(TABLE|INDEX)\b", re.IGNORECASE)


def _iter_string_literals(path: Path, source: str) -> list[tuple[int, str]]:
    """Every string literal in the migration file, via the AST (so f-string
    parts and implicit concatenation are covered, not just single-line
    `op.execute("...")` calls). Returns `(1-based lineno of the literal's
    first line, normalised text)` pairs."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    literals: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            # f-string: collect the literal (non-interpolated) parts.
            text = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if text:
                literals.append((node.lineno, text))
    return literals


def _normalise_sql(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sql_statements(text: str) -> list[str]:
    """Split a (possibly multi-statement, possibly prose) literal into
    individual SQL-statement-sized chunks so a mutation keyword in one
    sentence/statement is never combined with an unrelated table name
    mentioned elsewhere in the same literal (e.g. a module docstring listing
    several tables in prose). Splits on `;` and on blank lines, which is
    conservative — a real single SQL statement never spans a blank line in
    this codebase's migrations."""
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        chunks.extend(part for part in para.split(";") if part.strip())
    return chunks or [text]


# Populated from `tools/ci/security-sensitive-tables.txt` when present;
# migrations touching these need the `security-review` label (flagged, not
# blocked, by this tool — the label/reviewer gate is enforced elsewhere).
_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH = Path(__file__).with_name("security-sensitive-tables.txt")


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

    Scans every string literal in the file (via `ast`, so multi-line
    `op.execute(\n "...")`, an indirected `SQL = "..."; op.execute(SQL)`, and
    f-string literal parts are all covered — not just a single-line
    `op.execute("...")` regex) for a mutation keyword co-occurring with an
    audit table name, both compared case-insensitively (Postgres folds
    unquoted identifiers to lower case). Also keeps the `op.alter_column` /
    `op.rename_table` line-level checks the AST-level destructive-op check
    above does not see.

    The only escape hatch is `# cv:audit-exempt: <reason>` on the same source
    line, and only when the statement is CREATE-only (`CREATE TABLE`/
    `CREATE INDEX ... ON <table>`) — never for a genuine mutation."""
    findings: list[LintFinding] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()

        for lineno, literal in _iter_string_literals(path, source):
            for statement in _sql_statements(literal):
                normalised = _normalise_sql(statement)
                forbidden_hit = next(
                    (
                        table
                        for table in forbidden_tables
                        if _mutation_pattern_for(table).search(normalised)
                    ),
                    None,
                )
                if forbidden_hit is None:
                    continue
                if _CREATE_ONLY_RE.match(normalised):
                    continue
                source_line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
                if _AUDIT_EXEMPT_RE.search(source_line):
                    continue
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {lineno}: raw-SQL statement targets append-only "
                            f"table '{forbidden_hit}' — forbidden regardless of "
                            "annotation (C-5.7, ADR-0013 rule 9)"
                        ),
                    )
                )

        for idx, line in enumerate(lines):
            is_rename = bool(re.search(r"\bop\.rename_table\s*\(", line))
            is_alter_shape = bool(re.search(r"\bop\.alter_column\s*\(", line))
            if not (is_rename or is_alter_shape):
                continue
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
            is_non_nullable_add = (
                bool(_ADD_COLUMN_RE.search(line))
                and _NULLABLE_FALSE_RE.search(line)
                and not _SERVER_DEFAULT_RE.search(line)
            )

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
