"""infra/scripts/lint_compose.py — E02-T08 compose-lint gate.

Enforces the three acceptance criteria that are checkable by static
inspection of the compose YAML, without needing Docker installed:

1. Every published host port is bound to ``127.0.0.1`` — never ``0.0.0.0``
   or a bare ``"<port>:<port>"`` form (trust boundary B2,
   ``docs/plan/20-architecture.md`` Sec.2.2).
2. Every image reference is pinned by digest (``name@sha256:<64 hex>``) —
   a bare tag (including ``:latest``) fails, citing the supply-chain control
   from the E02 STRIDE model (``docs/plan/security/E02-threat-model.md`` R4).
3. Every service defines a ``healthcheck``.

Run as a script (``python infra/scripts/lint_compose.py``) or imported by
``infra/scripts/tests/test_lint_compose.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_PORT_TOKEN = r"(?:\d+|\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\})"
_LOOPBACK_PORT_RE = re.compile(rf"^127\.0\.0\.1:{_PORT_TOKEN}:{_PORT_TOKEN}(/(tcp|udp))?$")


class ComposeLintError(Exception):
    """Raised with every violation found, joined into one message."""


def _services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return compose.get("services", {}) or {}


def check_port_bindings(compose: dict[str, Any]) -> list[str]:
    """Every `ports:` entry must be an explicit `127.0.0.1:<port>:<port>` string."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        for port in service.get("ports", []) or []:
            if not isinstance(port, str) or not _LOOPBACK_PORT_RE.match(port):
                errors.append(
                    f"service '{name}': port binding {port!r} is not explicitly bound to "
                    "127.0.0.1 (B2, docs/plan/20-architecture.md Sec.2.2)"
                )
    return errors


def check_image_digests(compose: dict[str, Any]) -> list[str]:
    """Every `image:` must be pinned by digest, not a mutable tag."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        image = service.get("image")
        if image is None:
            continue
        if not _DIGEST_RE.match(image):
            errors.append(
                f"service '{name}': image {image!r} is not pinned by sha256 digest "
                "(supply-chain control, docs/plan/security/E02-threat-model.md R4)"
            )
    return errors


def check_healthchecks(compose: dict[str, Any]) -> list[str]:
    """Every service must declare a `healthcheck:` block."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        if "healthcheck" not in service:
            errors.append(f"service '{name}': missing healthcheck block")
    return errors


def lint(compose_path: Path) -> list[str]:
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    errors += check_port_bindings(compose)
    errors += check_image_digests(compose)
    errors += check_healthchecks(compose)
    return errors


def main(argv: list[str] | None = None) -> int:
    path = Path(argv[0]) if argv else Path(__file__).parent.parent / "compose" / "docker-compose.yml"
    errors = lint(path)
    if errors:
        for error in errors:
            print(f"lint_compose: {error}", file=sys.stderr)
        return 1
    print("lint_compose: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
