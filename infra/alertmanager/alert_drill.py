#!/usr/bin/env python3
"""E04-T05 `make alert-drill`: fire/stop the SyntheticAlert condition end to end.

Writes the textfile-style gauge cv_synthetic_alert via the Prometheus
Pushgateway-compatible endpoint named by CV_ALERT_DRILL_PUSH_URL (private only).
`fire` sets it to 1 (rule SyntheticAlert pages after its 1m for-duration);
`stop` sets it to 0. No secrets are used or printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request


def build_request(url: str, value: int) -> urllib.request.Request:
    body = f"cv_synthetic_alert {value}\n".encode()
    return urllib.request.Request(
        url.rstrip("/")
        + "/metrics/job/alert_drill/env/"
        + os.environ.get("CV_ENV", "dev"),
        data=body,
        method="PUT",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["fire", "stop"])
    ns = p.parse_args(argv)
    url = os.environ.get("CV_ALERT_DRILL_PUSH_URL", "http://127.0.0.1:9091")
    if not url.startswith(("http://127.0.0.1", "http://localhost", "http://172.28.")):
        print("refusing non-private push url", file=sys.stderr)
        return 2
    req = build_request(url, 1 if ns.action == "fire" else 0)
    with urllib.request.urlopen(req, timeout=5) as r:
        print(f"alert-drill {ns.action}: HTTP {r.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
