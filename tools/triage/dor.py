"""Bug DoR validation (docs/plan/02-definition-of-ready-done.md §6.1) + secret scan."""

from __future__ import annotations

import re

# Issue-form section headings (must match .github/ISSUE_TEMPLATE/bug_report.yml labels).
REQUIRED_FIELDS = [
    "Reproduction steps",
    "Environment",
    "Symbol and account context",
    "Expected behavior",
    "Actual behavior",
    "Severity",
    "Root cause hypothesis",
    "Test layer that should have caught it",
    "Originating Story/Epic",
]
_EMPTY = {"", "_no response_", "n/a", "none", "todo", "tbd", "-"}
_HEADING = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)

SECRET_PATTERNS = {
    "github-token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "api-key": re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "key-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+_\-]{16,}"
    ),
}


def parse_sections(body: str) -> dict[str, str]:
    body = body or ""
    marks = list(_HEADING.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(1).strip()] = body[m.end() : end].strip()
    return out


def missing_fields(body: str) -> list[str]:
    sections = parse_sections(body)
    return [n for n in REQUIRED_FIELDS if sections.get(n, "").strip().lower() in _EMPTY]


def scan_secrets(body: str) -> list[str]:
    """Names of secret patterns hit (never the matched text)."""
    return sorted(n for n, rx in SECRET_PATTERNS.items() if rx.search(body or ""))


def redact(body: str) -> str:
    for rx in SECRET_PATTERNS.values():
        body = rx.sub("[REDACTED]", body)
    return body


def severity_of(body: str, labels: list[str]) -> str | None:
    for lab in labels:
        m = re.fullmatch(r"priority/p([0-3])(?:-.*)?", lab)
        if m:
            return f"P{m.group(1)}"
    m = re.search(r"\bP([0-3])\b", parse_sections(body).get("Severity", ""))
    return f"P{m.group(1)}" if m else None
