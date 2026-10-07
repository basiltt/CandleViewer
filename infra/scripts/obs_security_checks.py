#!/usr/bin/env python3
"""E04-X02: deployment-smoke security checks for the observability stack.

Scripted, offline checks (SR-124, SR-126, SR-142):
  * gitleaks config never allowlists infra/grafana|prometheus|alertmanager;
  * log/bundle directories are 0700 and files 0600 (POSIX);
  * CI workflows never upload log directories as artefacts;
  * no webhook token / URL secret is committed under infra/alertmanager.
Exit 0 = all pass; non-zero prints one line per violation.
"""

from __future__ import annotations

import re
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCANNED_INFRA = ("infra/grafana", "infra/prometheus", "infra/alertmanager")
_WEBHOOK_RE = re.compile(
    r"(hooks\.slack\.com/services/\w+/\w+/\w+|discord(?:app)?\.com/api/webhooks/\d+/[\w-]+"
    r"|api\.telegram\.org/bot\d+:[\w-]+|(?:routing_key|service_key|token)\s*:\s*[\"']?[A-Za-z0-9]{24,})"
)


def _fingerprint(value: str) -> str:
    """Non-reversible stand-in for a matched line: length only, never content."""
    return f"len={len(value)}"


def check_gitleaks_covers_infra(config_text: str) -> list[str]:
    """Violations if the gitleaks allowlist paths exempt any observability infra dir."""
    out: list[str] = []
    if "useDefault = true" not in config_text:
        out.append("gitleaks: [extend] useDefault = true missing")
    for lineno, line in enumerate(config_text.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        for d in SCANNED_INFRA + ("infra/",):
            if d in s and "'''" in s:
                out.append(f"gitleaks: allowlist exempts {d} (line {lineno}, {_fingerprint(s)})")
    return out


def check_modes(root: Path) -> list[str]:
    """Directories must be 0700, files 0600 (skipped on Windows)."""
    if sys.platform == "win32" or not root.exists():
        return []
    out: list[str] = []
    for p in [root, *root.rglob("*")]:
        mode = stat.S_IMODE(p.stat().st_mode)
        want = 0o700 if p.is_dir() else 0o600
        if mode & ~want:
            out.append(f"permissions: {p} is {mode:o}, want <= {want:o}")
    return out


def check_workflows_no_log_artifacts(workflows: Path) -> list[str]:
    out: list[str] = []
    for wf in sorted(workflows.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        for m in re.finditer(
            r"upload-artifact[\s\S]{0,400}?path:\s*(\|?[\s\S]{0,200}?)(?:\n\s*\n|\n\s*\w+:|$)", text
        ):
            if re.search(r"(^|[\s/*])(logs?|support-bundles?)(/|\s|$)", m.group(1)):
                out.append(f"{wf.name}: uploads a log/bundle directory as an artefact (SR-124)")
    return out


def check_alertmanager_webhook_literals(infra: Path) -> list[str]:
    out: list[str] = []
    base = infra / "alertmanager"
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_file() and p.suffix in {".yml", ".yaml", ".tmpl", ".json", ".env"}:
            for n, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if line.lstrip().startswith("#"):
                    continue
                if _WEBHOOK_RE.search(line):
                    out.append(
                        f"{p.relative_to(infra.parent)}:{n}: literal webhook URL or token (SR-126)"
                    )
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    violations = check_gitleaks_covers_infra((REPO / ".gitleaks.toml").read_text(encoding="utf-8"))
    violations += check_workflows_no_log_artifacts(REPO / ".github/workflows")
    violations += check_alertmanager_webhook_literals(REPO / "infra")
    for d in args:  # runtime log / bundle dirs supplied by the deploy smoke test
        violations += check_modes(Path(d))
    for v in violations:
        print(v)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
