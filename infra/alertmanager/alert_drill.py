#!/usr/bin/env python3
"""E04-T05 `make alert-drill`: fire/stop the SyntheticAlert condition end to end.

Writes the textfile-style gauge cv_synthetic_alert via the Prometheus
Pushgateway-compatible endpoint named by CV_ALERT_DRILL_PUSH_URL (private only).
`fire` sets it to 1 (rule SyntheticAlert pages after its 1m for-duration);
`stop` sets it to 0. No secrets are used or printed.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
import urllib.parse
import urllib.request

_LOOPBACK_NAMES = {"localhost"}
# RFC1918 + Tailscale CGNAT (100.64.0.0/10) + loopback; compose cv-internal is 172.28.0.0/24.
_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
    )
)


def is_private_url(url: str) -> bool:
    """Exact host check (no prefix matching): http(s), no userinfo, private host only."""
    try:
        parts = urllib.parse.urlsplit(url)
        _ = parts.port  # raises on a malformed port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or "@" in parts.netloc:
        return False
    host = parts.hostname
    if not host:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in _PRIVATE_NETS)


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
    if not is_private_url(url):
        print("refusing non-private push url", file=sys.stderr)
        return 2
    req = build_request(url, 1 if ns.action == "fire" else 0)
    with urllib.request.urlopen(req, timeout=5) as r:
        print(f"alert-drill {ns.action}: HTTP {r.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
