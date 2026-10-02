"""SR-047 runtime listener probe (E07-X02, #276).

Run by CI's `integration` job after it brings up the compose data stores
(`docker compose ... --profile core up -d postgres questdb`) and sets
`CV_LISTENER_PROBE=1`. Three independent checks on the *running* stack:

1. `docker compose ps` publishers: every published port is bound to 127.0.0.1.
2. Host sockets (`ss -ltnH`): each published port listens on loopback only —
   no `0.0.0.0`/`[::]`/`*` or routable-address listener for it on the runner.
3. Live probe: a `socket.connect` to 127.0.0.1:<port> succeeds (the service
   is really there, so (1)/(2) are not vacuous).

Without `CV_LISTENER_PROBE=1` (local, no docker) the test skips; with it set
an empty stack is a failure, never a skip.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPO = Path(__file__).resolve().parents[5]
_COMPOSE = _REPO / "infra" / "compose" / "docker-compose.yml"
_LOOPBACK = {"127.0.0.1", "::1"}


def _run(*argv: str) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout  # noqa: S603


def _publishers() -> list[tuple[str, str, int]]:
    docker = shutil.which("docker")
    assert docker is not None, "docker CLI required for the SR-047 probe"
    out = _run(docker, "compose", "-f", str(_COMPOSE), "ps", "--format", "json")
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    if len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    found: list[tuple[str, str, int]] = []
    for row in rows:
        for pub in row.get("Publishers") or []:
            if pub.get("PublishedPort"):
                found.append((row["Service"], str(pub["URL"]), int(pub["PublishedPort"])))
    return found


def _host_listeners(port: int) -> set[str]:
    ss = shutil.which("ss")
    assert ss is not None, "iproute2 `ss` required for the SR-047 probe"
    hosts: set[str] = set()
    for line in _run(ss, "-ltnH", f"sport = :{port}").splitlines():
        local = line.split()[3]
        hosts.add(local.rsplit(":", 1)[0].strip("[]"))
    return hosts


@pytest.mark.skipif(
    os.environ.get("CV_LISTENER_PROBE") != "1",
    reason="needs the running compose stack (CI integration job sets CV_LISTENER_PROBE=1)",
)
def test_sr047_running_stack_listens_on_loopback_only() -> None:
    pubs = _publishers()
    assert pubs, "no published ports found: the compose stack is not running"
    report: list[str] = []
    for service, url, port in pubs:
        assert url in _LOOPBACK, f"{service}: port {port} published on {url}"
        listeners = _host_listeners(port)
        assert listeners, f"{service}: nothing listening on host port {port}"
        assert listeners <= _LOOPBACK, f"{service}: port {port} listens on {sorted(listeners)}"
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        report.append(f"{service} {url}:{port} listeners={sorted(listeners)} connect=ok")
    print("SR-047 probe:\n" + "\n".join(report))
