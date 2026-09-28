"""Tailscale-only reachability guard (E09-T04, US-ONB-008).

Fail-closed network-boundary controls that keep CandleViewer off the public
internet, independent of and enforced *before* authentication:

- `cidr.CidrAllowList` — in-memory prefix matcher for the configured
  Tailscale CIDR(s) plus loopback (IPv4/IPv6, mapped addresses).
- `binding_check.BindingSelfCheck` — enumerates the process's actual bound
  listening addresses (never trusts the configured bind string) and reports
  whether any of them are a public wildcard bind (`0.0.0.0` / `::`) or fall
  outside the configured mesh/loopback CIDR allow-list.
- `binding_check.apply_self_check_result` — wires one self-check outcome
  end to end: trips/clears `ReadOnlyGate` and sets `net_binding_safe`.
- `read_only_gate.ReadOnlyGate` — process-wide, single-flag degraded-mode
  switch consulted by the OMS validator; cannot be bypassed by any route.
- `middleware.MeshOnlyMiddleware` — ASGI middleware rejecting off-mesh
  requests with a generic 403 before any credential is evaluated, for both
  REST and the WS upgrade.
- `audit.AuditSink` — narrow protocol this module emits
  `net.off_mesh_request` events through; a `NullAuditSink` no-op default and
  an `InMemoryAuditSink` test double are provided. The real audit module
  (owned by its own ticket, C-3.3) wires a concrete sink in the composition
  root once it lands.
- `metrics.net_binding_safe` — the `net_binding_safe` Prometheus gauge.
- `host_sockets.real_socket_enumerator` — the `psutil`-backed enumerator the
  composition root wires into `BindingSelfCheck` in production.
- `scheduler.MeshSelfCheckScheduler` — supervises the hourly re-check
  (drift-after-resume, AC5) using the exact same `apply_self_check_result`
  path as the boot check.

See `docs/plan/backlog/E09-T04` and `20-architecture.md` "WSL hazards".
"""

from __future__ import annotations

__all__ = [
    "AuditSink",
    "BindingCheckResult",
    "BindingSelfCheck",
    "CidrAllowList",
    "InMemoryAuditSink",
    "MeshOnlyMiddleware",
    "MeshSelfCheckScheduler",
    "NullAuditSink",
    "ReadOnlyGate",
    "apply_self_check_result",
    "net_binding_safe",
    "real_socket_enumerator",
]

from .audit import AuditSink, InMemoryAuditSink, NullAuditSink
from .binding_check import BindingCheckResult, BindingSelfCheck, apply_self_check_result
from .cidr import CidrAllowList
from .host_sockets import real_socket_enumerator
from .metrics import net_binding_safe
from .middleware import MeshOnlyMiddleware
from .read_only_gate import ReadOnlyGate
from .scheduler import MeshSelfCheckScheduler
