"""SR-047 / SR-048 bind assertions (E07-X02): compose files + startup self-check."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from candleviewer.net.binding_check import BindingSelfCheck

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "infra" / "scripts"))
from lint_compose import check_port_bindings  # noqa: E402

COMPOSE_FILES = [
    *sorted((REPO / "infra" / "compose").glob("docker-compose*.yml")),
    REPO / "infra" / "docker-compose.dev.yml",
]
DATA_STORES = ("postgres", "questdb", "minio")


@pytest.mark.parametrize("path", [p for p in COMPOSE_FILES if p.exists()], ids=lambda p: p.name)
def test_sr047_048_committed_compose_publishes_loopback_only(path: Path) -> None:
    compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert check_port_bindings(compose) == []


@pytest.mark.parametrize(
    "port", ["0.0.0.0:5432:5432", "5432:5432", "9000:9000", ":::9000", "[::]:9000:9000"]
)
def test_sr047_048_negative_control_wildcard_publish_is_flagged(port: str) -> None:
    compose = {"services": {name: {"ports": [port]} for name in DATA_STORES}}
    errors = check_port_bindings(compose)
    assert len(errors) == len(DATA_STORES)
    assert all("127.0.0.1" in e for e in errors)


def test_sr047_048_questdb_console_never_published_off_loopback() -> None:
    for path in COMPOSE_FILES:
        if not path.exists():
            continue
        svc = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services", {})
        for port in (svc.get("questdb") or {}).get("ports", []) or []:
            assert str(port).startswith("127.0.0.1:"), f"SR-048 violated in {path.name}: {port}"


@pytest.mark.parametrize("addr", ["0.0.0.0:5432", "[::]:9000", "192.168.1.5:8812"])
def test_sr047_startup_self_check_refuses_non_loopback_data_store_bind(addr: str) -> None:
    result = BindingSelfCheck(address_enumerator=lambda: [addr]).run()
    assert result.safe is False


def test_sr047_startup_self_check_accepts_loopback() -> None:
    result = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:5432", "[::1]:9000"]).run()
    assert result.safe is True
