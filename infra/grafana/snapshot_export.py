"""Nightly Grafana dashboard snapshot export (ADR-0014 mitigation, E04-S01).

Writes each dashboard's JSON model to a local artefact directory (default
``artifacts/grafana-snapshots/<date>``). Local only: never uploaded from CI.
Credentials come from the environment (GF_SECURITY_ADMIN_USER/PASSWORD), never code.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

Fetch = Callable[[str], dict]


def _http_fetch(base: str) -> Callable[[str], dict]:
    user = os.environ["GF_SECURITY_ADMIN_USER"]
    pw = os.environ["GF_SECURITY_ADMIN_PASSWORD"]
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()

    def get(path: str) -> dict:
        req = urllib.request.Request(
            base + path, headers={"Authorization": f"Basic {tok}"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    return get


def export(fetch: Fetch, out_root: Path, today: dt.date) -> list[Path]:
    out = out_root / today.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for hit in fetch("/api/search?tag=candleviewer"):
        model = fetch(f"/api/dashboards/uid/{hit['uid']}")["dashboard"]
        for volatile in ("id", "version"):
            model.pop(volatile, None)
        p = out / f"{hit['uid']}.json"
        p.write_text(
            json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(p)
    return written


if __name__ == "__main__":
    base_url = os.environ.get("GRAFANA_URL", "http://127.0.0.1:3001")
    root = Path(os.environ.get("CV_SNAPSHOT_DIR", "artifacts/grafana-snapshots"))
    for f in export(_http_fetch(base_url), root, dt.datetime.now(dt.UTC).date()):
        print(f)
