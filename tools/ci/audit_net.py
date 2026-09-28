#!/usr/bin/env python3
"""`make audit-net` (E09-T04, `docs/plan/20-architecture.md` "WSL hazards"
paragraph): CI-on-host check that this machine's real listening sockets
are all mesh-only.

Reuses the exact same `BindingSelfCheck` + `CidrAllowList` the running
process wires into its boot/hourly self-check (`candleviewer.net`), so a
pass here means the same check the app performs on its own would also
pass, and a failure surfaces before deploy rather than only in the
running process's read-only degradation.

Exit code 0 = every listening socket is loopback or inside a configured
mesh CIDR. Exit code 1 = a public/off-mesh binding was found (printed to
stderr) — CI-on-host treats this as a failing job.
"""

from __future__ import annotations

import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from candleviewer.net.binding_check import BindingSelfCheck  # noqa: E402
from candleviewer.net.cidr import CidrAllowList  # noqa: E402
from candleviewer.net.host_sockets import real_socket_enumerator  # noqa: E402
from candleviewer.settings import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    allow_list = CidrAllowList(list(settings.mesh_cidrs))
    check = BindingSelfCheck(
        address_enumerator=real_socket_enumerator(),
        allow_list=allow_list,
    )
    result = check.run()

    if result.safe:
        print("audit-net: OK — every listening socket is mesh-only.")
        return 0

    print(
        f"audit-net: FAIL — {result.reason_code}: {result.reason_text}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
