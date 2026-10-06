"""Single grammar for justified in-source scanner suppressions.

Shared by `tools/ci/check_auth_semgrep.py` (auth-package suppressions) and
`tools/ci/security_gate.py` (CI-SEC-006) so the two gates cannot drift
(04-security-program.md §12.2). Canonical form, one comment:

    <marker>: <rule-id>[,<rule-id>...] reason=<token> owner=@<handle>[/<team>] review=YYYY-MM-DD

Fields may be separated by whitespace or `;`. `reason` is one token (use
hyphens). `review` must be today or later and at most `REVIEW_MAX_DAYS` ahead:
a far-future date is a permanent exception in disguise, so it blocks too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

REVIEW_MAX_DAYS = 180
FIELDS = ("reason", "owner", "review")
OWNER_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?$")
_RULE_TOKEN = r"(?![\w.-]*=)[\w.-]+"
NOSEMGREP_RE = re.compile(
    rf"nosemgrep:[ \t]*(?P<rules>{_RULE_TOKEN}(?:[ \t,]+{_RULE_TOKEN})*)(?P<rest>[^\n]*)"
)
COMMENT_ONLY_RE = re.compile(r"^\s*(?:#|//)")


def field(text: str, name: str) -> str | None:
    """Value of `name=` in `text` (first occurrence), else None."""
    m = re.search(rf"(?<![\w-]){name}=([^\s;]+)", text)
    return m.group(1) if m else None


@dataclass(frozen=True)
class Nosemgrep:
    rules: tuple[str, ...]
    rest: str


def parse_nosemgrep(text: str) -> list[Nosemgrep]:
    """Every `nosemgrep:` marker in `text` with its exact rule-id list."""
    return [
        Nosemgrep(tuple(t for t in re.split(r"[\s,]+", m.group("rules")) if t), m.group("rest"))
        for m in NOSEMGREP_RE.finditer(text)
    ]


def rule_matches(rule_id: str, listed: tuple[str, ...]) -> bool:
    """Exact membership: the full id or its last dotted segment, never a prefix."""
    return rule_id in listed or rule_id.rsplit(".", 1)[-1] in listed


def field_problems(text: str, today: date, max_days: int = REVIEW_MAX_DAYS) -> list[str]:
    """Reasons `text` is not a valid justification; [] if it is."""
    missing = [k for k in FIELDS if not field(text, k)]
    if missing:
        return [f"suppression missing {', '.join(missing)}"]
    problems: list[str] = []
    owner = field(text, "owner") or ""
    if not OWNER_RE.match(owner):
        problems.append(f"suppression owner {owner!r} is not @<handle> or @<org>/<team>")
    try:
        due = date.fromisoformat(field(text, "review") or "")
    except ValueError:
        return [*problems, "suppression review date is not YYYY-MM-DD"]
    if due < today:
        problems.append(f"suppression review date {due} has expired")
    elif due > today + timedelta(days=max_days):
        problems.append(
            f"CI-SEC-006 expiry too far: review date {due} is more than {max_days} days ahead"
        )
    return problems
