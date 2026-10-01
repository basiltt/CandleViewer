"""Generate the six provisioned Grafana dashboards (E04-S01, ADR-0014 section 3).

The committed JSON in ``infra/grafana/dashboards`` is the reviewed artefact; this
generator keeps it deterministic (no volatile ``id``/``version``). Re-run with
``python infra/grafana/generate_dashboards.py`` after editing panels.
Thresholds come from docs/plan/06-performance-and-load-standard.md section 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DS = {"type": "prometheus", "uid": "cv-prometheus"}
OUT = Path(__file__).resolve().parent / "dashboards"
E = 'env="$env"'
# Colour-blind-safe palette (Okabe-Ito): blue ok / orange warn / vermillion bad.
# State is always also shown as a numeric stat value, never colour alone.
OK, WARN, BAD = "#0072B2", "#E69F00", "#D55E00"
RI = "$__rate_interval"


def _th(warn: float | None, bad: float | None) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [{"color": OK, "value": None}]
    if warn is not None:
        steps.append({"color": WARN, "value": warn})
    if bad is not None:
        steps.append({"color": BAD, "value": bad})
    return {"mode": "absolute", "steps": steps}


class Board:
    def __init__(self, uid: str, title: str, tags: list[str]) -> None:
        self.uid, self.title, self.tags = uid, title, tags
        self.panels: list[dict[str, Any]] = []
        self.y = 0
        self.x = 0
        self._id = 0
        self._id += 1
        self.panels.append(
            {
                "id": self._id,
                "type": "text",
                "title": "Environment",
                "gridPos": {"h": 3, "w": 24, "x": 0, "y": 0},
                "options": {
                    "mode": "markdown",
                    "content": f"## {title} - env = **$env**",
                },
            }
        )
        self.y = 3

    def row(self, title: str) -> None:
        self.flush()
        self._id += 1
        self.panels.append(
            {
                "id": self._id,
                "type": "row",
                "title": title,
                "collapsed": False,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y},
                "panels": [],
            }
        )
        self.y += 1

    def _add(
        self,
        kind: str,
        title: str,
        expr: str,
        unit: str,
        w: int,
        h: int,
        warn: float | None,
        bad: float | None,
        legend: str,
    ) -> dict[str, Any]:
        self._id += 1
        p: dict[str, Any] = {
            "id": self._id,
            "type": kind,
            "title": title,
            "datasource": DS,
            "gridPos": {"h": h, "w": w, "x": self.x, "y": self.y},
            "maxDataPoints": 500,
            "fieldConfig": {
                "defaults": {"unit": unit, "thresholds": _th(warn, bad)},
                "overrides": [],
            },
            "targets": [
                {"refId": "A", "datasource": DS, "expr": expr, "legendFormat": legend}
            ],
        }
        self.panels.append(p)
        self.x += w
        if self.x >= 24:
            self.x, self.y = 0, self.y + h
        return p

    def ts(
        self,
        title: str,
        expr: str,
        unit: str,
        warn: float | None = None,
        bad: float | None = None,
        legend: str = "",
    ) -> None:
        self._add("timeseries", title, expr, unit, 12, 7, warn, bad, legend)

    def stat(
        self,
        title: str,
        expr: str,
        unit: str,
        warn: float | None = None,
        bad: float | None = None,
        legend: str = "",
    ) -> None:
        p = self._add("stat", title, expr, unit, 6, 4, warn, bad, legend)
        p["options"] = {
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value_and_name",
        }

    def flush(self) -> None:
        if self.x:
            self.x, self.y = 0, self.y + 7

    def build(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "tags": ["candleviewer", *self.tags],
            "schemaVersion": 39,
            "editable": False,
            "timezone": "utc",
            "refresh": "30s",
            "time": {"from": "now-1h", "to": "now"},
            "annotations": {
                "list": [
                    {
                        "name": "Deploys",
                        "enable": True,
                        "datasource": DS,
                        "expr": f"changes(build_info{{{E}}}[{RI}]) > 0",
                        "titleFormat": "deploy",
                        "tagKeys": "version,commit",
                        "iconColor": OK,
                    }
                ]
            },
            "templating": {
                "list": [
                    {
                        "name": "env",
                        "label": "env",
                        "type": "query",
                        "datasource": DS,
                        "query": {
                            "query": "label_values(build_info, env)",
                            "refId": "env",
                        },
                        "refresh": 2,
                        "sort": 1,
                        "includeAll": False,
                        "multi": False,
                        "current": {"text": "demo", "value": "demo"},
                    }
                ]
            },
            "panels": self.panels,
        }


def q(m: str, by: str = "", pct: str = "0.95") -> str:
    g = f"le, {by}" if by else "le"
    return f"histogram_quantile({pct}, sum by ({g}) (rate({m}_bucket{{{E}}}[{RI}])))"


def rate(m: str, by: str = "", extra: str = "") -> str:
    inner = f"rate({m}{{{E}{extra}}}[{RI}])"
    return f"sum by ({by}) ({inner})" if by else inner


def system() -> Board:
    b = Board("cv-system-health", "CV / System health", ["system"])
    b.row("Getting worse? (SLO burn)")
    b.stat(
        "Loop lag p99 (budget 50 ms)",
        q("event_loop_lag_seconds", pct="0.99"),
        "s",
        0.05,
        0.1,
    )
    over = (
        f'1 - (sum(rate(event_loop_lag_seconds_bucket{{{E},le="0.1"}}[{RI}])) / '
        f"sum(rate(event_loop_lag_seconds_count{{{E}}}[{RI}])))"
    )
    b.stat("Loop lag > 100 ms fraction", over, "percentunit", 0.01, 0.05)
    b.row("Runtime")
    b.ts("Event loop lag p99", q("event_loop_lag_seconds", pct="0.99"), "s", 0.05, 0.1)
    b.ts("CPU", f"rate(process_cpu_seconds_total{{{E}}}[{RI}])", "percentunit")
    b.ts("RAM (RSS)", f"process_resident_memory_bytes{{{E}}}", "bytes")
    b.ts(
        "WS connection state (1=up)",
        f"ws_connection_state{{{E}}}",
        "short",
        legend="{{socket}}",
    )
    b.ts("Topic staleness", f"topic_staleness_seconds{{{E}}}", "s", 5, 15, "{{topic}}")
    b.ts(
        "Ingest queue depth", f"ingest_queue_depth{{{E}}}", "short", legend="{{stage}}"
    )
    b.row("Component health and observability stack")
    b.ts(
        "health_component_state (0=ok, higher=worse)",
        f"health_component_state{{{E}}}",
        "short",
        1,
        2,
        "{{component}}",
    )
    b.ts("Build info", f"build_info{{{E}}}", "short", legend="{{version}} {{commit}}")
    b.ts(
        "Prometheus rule group duration",
        "prometheus_rule_group_last_duration_seconds",
        "s",
    )
    b.ts(
        "Alertmanager failed notifications",
        f"rate(alertmanager_notifications_failed_total[{RI}])",
        "ops",
        0.0001,
        0.01,
    )
    b.ts("Watchdog alert state", 'ALERTS{alertname="Watchdog"}', "short")
    b.flush()
    return b


def market() -> Board:
    b = Board("cv-market-data", "CV / Market data", ["market"])
    b.row("Ingestion")
    b.ts(
        "Messages/s per topic",
        rate("ws_messages_total", "topic"),
        "ops",
        legend="{{topic}}",
    )
    b.ts("WS bytes/s", rate("ws_message_bytes_total"), "Bps")
    b.ts(
        "Book resyncs/s",
        rate("book_resync_total", "symbol, reason"),
        "ops",
        0.05,
        0.2,
        "{{symbol}} {{reason}}",
    )
    b.ts(
        "Engine process p95 (per engine)",
        q("engine_process_seconds", "engine"),
        "s",
        0.005,
        0.01,
        "{{engine}}",
    )
    b.ts(
        "WS fan-out latency p99 (budget 20 ms)",
        q("ws_fanout_latency_seconds", pct="0.99"),
        "s",
        0.02,
        0.05,
    )
    b.ts(
        "Ingest queue depth", f"ingest_queue_depth{{{E}}}", "short", legend="{{stage}}"
    )
    b.flush()
    return b


def trading() -> Board:
    b = Board("cv-trading", "CV / Trading", ["trading"])
    b.row("Execution (populates when E29 lands)")
    b.ts(
        "Order submit p99 (budget 500 ms)",
        q("order_submit_seconds", "transport", "0.99"),
        "s",
        0.4,
        0.5,
        "{{transport}}",
    )
    b.ts("Orders/s by state", rate("orders_total", "state"), "ops", legend="{{state}}")
    b.ts(
        "Reject rate",
        rate("orders_total", "state", ',state=~"rejected.*"'),
        "ops",
        legend="{{state}}",
    )
    b.ts("Rate-limit rejects/s", rate("oms_rate_reject_total"), "ops", 0.01, 0.1)
    b.ts(
        "Exchange rate remaining",
        f"bybit_rate_remaining{{{E}}}",
        "short",
        legend="{{endpoint_group}}",
    )
    b.stat(
        "Unknown orders (page > 0 for 60 s)",
        f"oms_unknown_orders{{{E}}}",
        "short",
        1,
        1,
    )
    b.stat(
        "Naked-position alerts (page > 0)",
        f"increase(naked_position_alerts_total{{{E}}}[$__range])",
        "short",
        1,
        1,
    )
    b.flush()
    return b


def rules() -> Board:
    b = Board("cv-rules", "CV / Rules", ["rules"])
    b.row("Rule engine")
    b.ts("Evaluations/s", rate("rule_evaluations_total"), "ops")
    b.ts(
        "Fires/s per rule",
        rate("rule_fires_total", "rule_id"),
        "ops",
        legend="{{rule_id}}",
    )
    b.ts("Auto-disarms/s", rate("rule_autodisarm_total"), "ops", 0.0001, 0.001)
    b.ts(
        "Circuit-breaker trips/s",
        rate("rule_circuit_breaker_trips_total"),
        "ops",
        0.0001,
        0.001,
    )
    b.flush()
    return b


def storage() -> Board:
    b = Board("cv-storage", "CV / Storage", ["storage"])
    b.row("Recorder and stores")
    b.ts(
        "Recorded rows/s",
        rate("recorder_rows_total", "stream"),
        "ops",
        legend="{{stream}}",
    )
    b.ts("Recorder spill bytes", f"recorder_spill_bytes{{{E}}}", "bytes")
    b.ts(
        "Disk used ratio (warn 80 %, page 95 %)",
        f"disk_used_ratio{{{E}}}",
        "percentunit",
        0.8,
        0.95,
    )
    b.ts("QuestDB write p95", q("questdb_write_seconds"), "s", 0.05, 0.25)
    b.ts("Postgres pool in use", f"pg_pool_in_use{{{E}}}", "short")
    b.ts("Postgres query p95", q("pg_query_seconds"), "s", 0.05, 0.25)
    b.flush()
    return b


def frontend() -> Board:
    b = Board("cv-frontend", "CV / Frontend", ["frontend"])
    b.row("Getting worse? (SLO burn)")
    b.stat("Frame time p95 (budget 16 ms)", q("fe_frame_time_ms"), "ms", 16, 33)
    # Budget-ratio stats computed directly from catalogue histograms (no recording-rule
    # dependency): >1 means the p95 is over its budget.
    b.stat(
        "WS decode p95 / budget (2 ms)", f"{q('fe_ws_decode_ms')} / 2", "short", 1, 2.5
    )
    b.stat(
        "Frame time p95 / budget (16 ms)",
        f"{q('fe_frame_time_ms')} / 16",
        "short",
        1,
        2,
    )
    b.row("Rendering")
    b.ts("Frame time p95", q("fe_frame_time_ms"), "ms", 16, 33)
    b.ts("Dropped frames/s", rate("fe_dropped_frames_total"), "ops", 1, 5)
    b.ts("WS decode p95", q("fe_ws_decode_ms"), "ms", 2, 5)
    b.ts("GPU memory", f"fe_gpu_memory_mb{{{E}}}", "decmbytes")
    b.flush()
    return b


BOARDS = {
    "system-health": system,
    "market-data": market,
    "trading": trading,
    "rules": rules,
    "storage": storage,
    "frontend": frontend,
}


def render() -> dict[str, str]:
    return {
        f"{n}.json": json.dumps(fn().build(), indent=2, sort_keys=True) + "\n"
        for n, fn in BOARDS.items()
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, text in render().items():
        (OUT / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
