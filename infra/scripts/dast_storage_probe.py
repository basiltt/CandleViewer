"""E07-X02 DAST probe: traversal payloads against storage read routes, and
data-store ports must not be reachable through the app origin (SR-047/048/097)."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.parse
import urllib.request

PAYLOADS = ["../../etc/passwd", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "/etc/passwd", "..%5c..%5cx"]
ROUTES = ["/v1/replay/sessions/{p}", "/v1/storage/datasets/{p}"]
LEAK_MARKERS = (b"root:x:", b"[boot loader]", b"Traceback")


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - http(s) only, loopback
            return r.status, r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, e.read(4096)


def run(base: str) -> list[str]:
    if not base.startswith(("http://127.0.0.1", "http://localhost")):
        return [f"refusing non-loopback target {base}"]
    problems: list[str] = []
    for route in ROUTES:
        for p in PAYLOADS:
            status, body = _get(base + route.format(p=urllib.parse.quote(p, safe="%")))
            if status == 200 or any(m in body for m in LEAK_MARKERS):
                problems.append(f"{route} payload {p!r}: status {status} (SR-097)")
    for port_path in ("/:5432", "/:9000", "/:8812"):
        status, _ = _get(base + port_path)
        if status == 200:
            problems.append(f"data-store port reachable via app origin: {port_path} (SR-048)")
    return problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    found = run(ap.parse_args().base)
    print("\n".join(found) or "dast storage probe clean")
    sys.exit(1 if found else 0)
