"""QA #1668: event writer, WS publisher, real probes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from candleviewer.bus.models import Topic
from candleviewer.health_wiring import (
    HealthSystemPublisher,
    PgSystemEventWriter,
    register_real_probes,
)
from candleviewer.observability.health_probes import (
    ComponentState,
    HealthRegistry,
    SystemEvent,
)


class _Session:
    def __init__(self, log: list[Any]) -> None:
        self.log = log

    async def execute(self, stmt: Any) -> None:
        self.log.append(stmt)


class _Uow:
    def __init__(self, log: list[Any], fail: bool = False) -> None:
        self.session = _Session(log)
        self.committed = False
        self._fail = fail

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *a: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _Repo:
    def __init__(self, fail: bool = False) -> None:
        self.log: list[Any] = []
        self.fail = fail
        self.uows: list[_Uow] = []

    def unit_of_work(self) -> _Uow:
        if self.fail:
            raise OSError("down")
        u = _Uow(self.log)
        self.uows.append(u)
        return u


class _Bus:
    def __init__(self) -> None:
        self.sent: list[tuple[Topic, Any]] = []

    async def publish(self, topic: Topic, event: Any) -> None:
        self.sent.append((topic, event))


async def test_writer_inserts_and_commits() -> None:
    repo = _Repo()
    await PgSystemEventWriter(repo).write(
        SystemEvent("db", "health_degraded", "error", "postgres healthy -> down", {"a": "b"})
    )
    assert len(repo.log) == 1 and repo.uows[0].committed


async def test_transition_writes_event_and_publishes_snapshot() -> None:
    repo, bus = _Repo(), _Bus()
    reg = HealthRegistry(
        events=PgSystemEventWriter(repo),
        on_snapshot=HealthSystemPublisher(bus, "demo"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    state = {"s": ComponentState.HEALTHY}

    class P:
        name = "bybit_public_ws"
        timeout = 1.0

        async def check(self):  # type: ignore[no-untyped-def]  # nested probe stub; protocol-typed at registration
            from candleviewer.observability.health_probes import ProbeResult

            return ProbeResult(state["s"])

    reg.register(P())
    await reg.refresh()
    assert repo.log == []
    state["s"] = ComponentState.DOWN
    await reg.refresh()
    state["s"] = ComponentState.HEALTHY
    await reg.refresh()
    assert len(repo.log) == 2
    assert len(bus.sent) == 3
    topic, payload = bus.sent[1]
    assert topic.domain == "system"
    assert payload["kind"] == "health" and payload["health"] == "down"
    assert payload["exchange"]["public_ws"] == "down"  # type: ignore[index]  # payload is dict[str, object]; test narrows by key


async def test_real_probes_replace_placeholders_and_report_failure(tmp_path: Any) -> None:
    reg = HealthRegistry()
    reg.register_placeholders()
    register_real_probes(
        reg,
        pg_repo=_Repo(fail=True),
        questdb_host="127.0.0.1",
        questdb_port=1,
        parquet_root=str(tmp_path),
        disk_path=str(tmp_path),
    )
    snap = await reg.refresh()
    st = {c.name: c.state for c in snap.components}
    assert st["postgres"] is ComponentState.DOWN
    assert st["questdb"] is ComponentState.DOWN
    assert st["parquet_store"] is ComponentState.HEALTHY
    assert st["disk"] in (ComponentState.HEALTHY, ComponentState.WARNING, ComponentState.DOWN)
    assert st["oms"] is ComponentState.NOT_DEPLOYED


async def test_disk_probe_uses_absolute_path(tmp_path: Any) -> None:
    reg = HealthRegistry()
    register_real_probes(
        reg,
        pg_repo=object(),  # type: ignore[arg-type]  # unused by the disk probe under test
        questdb_host="127.0.0.1",
        questdb_port=1,
        parquet_root=str(tmp_path),
        disk_path=".",
    )
    await reg.refresh()
    disk = next(c for c in reg.snapshot().components if c.name == "disk")
    assert disk.state is not ComponentState.DOWN
