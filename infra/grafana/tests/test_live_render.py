"""AC1/AC2/AC4 live check: a real Grafana file-provisions all dashboards (read-only, restart-stable),
and every panel query, run through Grafana's datasource proxy against a stub Prometheus
(provisioned cv-prometheus -> prometheus:9090, resolved to the stub via --add-host in CI), returns data frames; units/thresholds are asserted per panel.

CI integration lane starts Grafana (image pinned in infra/compose/docker-compose.yml) and sets
GRAFANA_URL. Locally it is skipped; under CI (CI=true) a missing GRAFANA_URL is a failure.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
URL = os.environ.get("GRAFANA_URL")
G = Path(__file__).resolve().parents[1]
DASHBOARDS = sorted((G / "dashboards").glob("*.json"))


def _call(path: str, body: dict | None = None) -> dict:
    user = os.environ.get("GF_SECURITY_ADMIN_USER", "admin")
    tok = base64.b64encode(
        f"{user}:{os.environ['GF_SECURITY_ADMIN_PASSWORD']}".encode()
    ).decode()
    req = urllib.request.Request(
        (URL or "") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {tok}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        assert r.status == 200
        return json.load(r)


def test_grafana_url_present_in_ci() -> None:
    if os.environ.get("CI") == "true":
        assert URL, "GRAFANA_URL must be set by the integration lane"


def _wait_healthy() -> None:
    for _ in range(40):
        try:
            with urllib.request.urlopen(URL + "/api/health", timeout=3) as r:  # type: ignore[operator]
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise AssertionError("Grafana not healthy")


@pytest.mark.skipif(not URL, reason="GRAFANA_URL unset: needs a running Grafana")
@pytest.mark.parametrize("dash", DASHBOARDS, ids=lambda p: p.stem)
def test_dashboard_is_file_provisioned_with_all_panels(dash: Path) -> None:
    """AC1: loaded by file provisioning (no manual import), bound to cv-prometheus."""
    model = json.loads(dash.read_text("utf-8"))
    got = _call(f"/api/dashboards/uid/{model['uid']}")
    assert got["meta"]["provisioned"] is True
    assert len(got["dashboard"]["panels"]) == len(model["panels"])
    ds = _call("/api/datasources/uid/cv-prometheus")
    assert ds["type"] == "prometheus"


@pytest.mark.skipif(not URL, reason="GRAFANA_URL unset: needs a running Grafana")
def test_ui_edit_rejected_and_reverted_on_restart() -> None:
    """AC4: a save is refused, and after a Grafana restart the repo JSON is what is served."""
    dash = DASHBOARDS[0]
    model = json.loads(dash.read_text("utf-8"))
    edited = dict(model, title="EDITED-IN-UI")
    try:
        _call("/api/dashboards/db", {"dashboard": edited, "overwrite": True, "folderUid": ""})
        rejected = False
    except urllib.error.HTTPError as e:
        rejected = e.code in (400, 412)
    assert rejected, "editing a provisioned dashboard must be refused"
    container = os.environ.get("GRAFANA_CONTAINER")
    if container:
        subprocess.run(["docker", "restart", container], check=True, timeout=120)
        _wait_healthy()
    got = _call(f"/api/dashboards/uid/{model['uid']}")
    assert got["dashboard"]["title"] == model["title"]
    assert got["meta"]["provisioned"] is True


PROM_PORT = int(os.environ.get("PROM_STUB_PORT", "9090"))
SEEN: list[str] = []


class _Prom(BaseHTTPRequestHandler):
    def _reply(self) -> None:
        from urllib.parse import parse_qs, urlparse

        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if self.command == "POST":
            n = int(self.headers.get("Content-Length", 0))
            qs = parse_qs(self.rfile.read(n).decode())
        SEEN.append(qs.get("query", [""])[0])
        now = time.time()
        if u.path.endswith("query_range"):
            data = {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"env": "ci"},
                        "values": [[now - 60 + i * 15, "0.5"] for i in range(5)],
                    }
                ],
            }
        else:
            data = {
                "resultType": "vector",
                "result": [{"metric": {"env": "ci"}, "value": [now, "0.5"]}],
            }
        body = json.dumps({"status": "success", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _reply

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture(scope="module")
def prom_datasource():  # type: ignore[no-untyped-def]
    srv = ThreadingHTTPServer(("127.0.0.1", PROM_PORT), _Prom)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield
    srv.shutdown()


def _panels(model: dict) -> list[dict]:
    return [p for p in model["panels"] if p["type"] != "row"]


@pytest.mark.skipif(not URL, reason="GRAFANA_URL unset: needs a running Grafana")
@pytest.mark.parametrize("dash", DASHBOARDS, ids=lambda p: p.stem)
def test_every_panel_query_returns_data_with_units_and_thresholds(
    dash: Path, prom_datasource: None
) -> None:
    model = json.loads(dash.read_text("utf-8"))
    for p in _panels(model):
        if p["type"] == "text":
            continue
        d = p["fieldConfig"]["defaults"]
        assert d.get("unit"), f"{p['title']}: no unit"
        assert d.get("thresholds", {}).get("steps"), f"{p['title']}: no thresholds"
        queries = []
        for i, t in enumerate(p["targets"]):
            queries.append(
                {
                    "refId": t.get("refId", chr(65 + i)),
                    "datasource": {"type": "prometheus", "uid": "cv-prometheus"},
                    "expr": t["expr"].replace("$env", "ci"),
                    "range": True,
                    "intervalMs": 15000,
                    "maxDataPoints": 100,
                }
            )
        res = _call(
            "/api/ds/query", {"queries": queries, "from": "now-5m", "to": "now"}
        )["results"]
        for ref, r in res.items():
            assert not r.get("error"), f"{p['title']}[{ref}]: {r.get('error')}"
            assert r.get("frames"), f"{p['title']}[{ref}]: no data frames"
    assert not any("cv:" in q for q in SEEN), "panel queries depend on recording rules"
