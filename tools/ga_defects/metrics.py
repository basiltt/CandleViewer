"""Prometheus exposition text and pushgateway transport for the GA defect metrics.

Metric names (all pushed under job ``ga_defects``; the pushgateway adds ``push_time_seconds``):

* ``ga_defects_open{severity}``            open type/bug issues by P0..P3
* ``ga_defects_open_by_component{component}``
* ``ga_defects_arrived_7d`` / ``ga_defects_closed_7d``  rolling 7-day counts
* ``ga_defects_untriaged``                 open bugs without the ``triaged`` label
* ``ga_defects_sla_state{severity,state}`` at-risk / breached counts (E49-T01 labels)
* ``ga_defect_age_days_bucket{severity,le}`` cumulative age histogram
* ``ga_defect_forecast_days_to_zero{method}`` absent (never 0 or NaN) when undefined
* ``design_qa_findings_open{severity}``    from the E49-D01 ledger
"""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

AGE_BUCKETS = (1, 3, 7, 14, 28)
JOB = "ga_defects"
Transport = Callable[[str, bytes], None]


class PushError(Exception):
    """Pushgateway unreachable after retries; callers must fail loudly (dashboard goes stale)."""


@dataclass
class DefectSnapshot:
    open_by_severity: dict[str, int] = field(default_factory=dict)
    open_by_component: dict[str, int] = field(default_factory=dict)
    arrived_7d: int = 0
    closed_7d: int = 0
    untriaged: int = 0
    sla: dict[tuple[str, str], int] = field(default_factory=dict)
    ages_days: dict[str, list[float]] = field(default_factory=dict)
    forecast_days: dict[str, int] = field(default_factory=dict)


def _lab(**kw: str) -> str:
    return "{" + ",".join(f'{k}="{v}"' for k, v in kw.items()) + "}"


def render_defects(s: DefectSnapshot) -> str:
    out: list[str] = []
    for sev, n in sorted(s.open_by_severity.items()):
        out.append(f"ga_defects_open{_lab(severity=sev)} {n}")
    for comp, n in sorted(s.open_by_component.items()):
        out.append(f"ga_defects_open_by_component{_lab(component=comp)} {n}")
    out += [
        f"ga_defects_arrived_7d {s.arrived_7d}",
        f"ga_defects_closed_7d {s.closed_7d}",
        f"ga_defects_untriaged {s.untriaged}",
    ]
    for (sev, state), n in sorted(s.sla.items()):
        out.append(f"ga_defects_sla_state{_lab(severity=sev, state=state)} {n}")
    for sev, ages in sorted(s.ages_days.items()):
        for le in (*AGE_BUCKETS, "+Inf"):
            n = sum(1 for a in ages if le == "+Inf" or a <= float(le))
            out.append(f"ga_defect_age_days_bucket{_lab(severity=sev, le=str(le))} {n}")
    for method, d in sorted(s.forecast_days.items()):
        out.append(f"ga_defect_forecast_days_to_zero{_lab(method=method)} {d}")
    return "\n".join(out) + "\n"


def render_ledger(open_by_severity: dict[str, int]) -> str:
    return (
        "\n".join(
            f"design_qa_findings_open{_lab(severity=sev)} {n}"
            for sev, n in sorted(open_by_severity.items())
        )
        + "\n"
    )


def http_transport(url: str, body: bytes) -> None:  # pragma: no cover - real network
    req = urllib.request.Request(url, data=body, method="PUT")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def push(
    base_url: str,
    job: str,
    text: str,
    transport: Transport = http_transport,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """PUT (replace) the job group; exponential backoff, then raise PushError."""
    url = f"{base_url.rstrip('/')}/metrics/job/{job}"
    for i in range(attempts):
        try:
            transport(url, text.encode("utf-8"))
            return
        except OSError as exc:  # URLError/HTTPError/timeouts are OSError subclasses
            if i == attempts - 1:
                raise PushError(f"pushgateway unreachable: {exc}") from exc
            sleep(2**i)
