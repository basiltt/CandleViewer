"""Dashboard lint (E04-S01): fails on metrics missing from the E04-T03 catalogue.

A panel querying a typo'd metric renders an empty graph that reads as "healthy",
so every metric token in every query is checked against the catalogue.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = Path(__file__).resolve().parent / "dashboards"
RULES = ROOT / "infra/prometheus"
CATALOGUE = ROOT / "services/api/candleviewer/observability/metrics_catalogue.py"
HEALTH = ROOT / "services/api/candleviewer/observability/health_metrics.py"
INGESTION = ROOT / "services/api/candleviewer/ingestion/metrics.py"
DATASOURCE_UID = "cv-prometheus"
#: Metrics exported by Prometheus/Alertmanager/process collectors, not the catalogue.
EXTERNAL = {
    "process_cpu_seconds_total",
    "process_resident_memory_bytes",
    "prometheus_rule_group_last_duration_seconds",
    "alertmanager_notifications_failed_total",
    "ALERTS",
    # E49-T02 push-model metrics (tools/ga_defects via pushgateway), not app-catalogue metrics.
    "push_time_seconds",
    "ga_defects_open",
    "ga_defects_open_by_component",
    "ga_defects_arrived_7d",
    "ga_defects_closed_7d",
    "ga_defects_untriaged",
    "ga_defects_sla_state",
    "ga_defect_age_days_bucket",
    "ga_defect_forecast_days_to_zero",
    "design_qa_findings_open",
}
_FUNCS = {
    "sum",
    "by",
    "rate",
    "increase",
    "histogram_quantile",
    "changes",
    "label_values",
    "le",
    "and",
    "or",
    "without",
    "on",
    "topk",
    "avg",
    "max",
    "min",
}
_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")


def catalogue_names() -> set[str]:
    names = set(
        re.findall(r'^\s+_s\(\s*"(\w+)"', CATALOGUE.read_text("utf-8"), re.MULTILINE)
    )
    names |= set(
        re.findall(
            r'^\s+"(health_component_state|build_info)"',
            HEALTH.read_text("utf-8"),
            re.MULTILINE,
        )
    )
    names |= {"build_info", "health_component_state"}
    # E08-T06: the declaration-first ingestion registry owns the ingestion and
    # adapter series (`_g("name", ...)` / `_c(...)` / `_h(...)` in SPECS).
    names |= set(
        re.findall(r'^\s+_[cgh]\(\s*"(\w+)"', INGESTION.read_text("utf-8"), re.MULTILINE)
    )
    # Brittle regex scraping must never silently degrade to "everything unknown/known".
    if len(names) < 10:
        raise RuntimeError(
            f"metric catalogue scrape looks broken: only {len(names)} names found"
        )
    return names


def recorded_rules(rules_dir: Path = RULES) -> set[str]:
    """Names of every `record:` rule under infra/prometheus (E04-T06 contract)."""
    out: set[str] = set()
    for f in rules_dir.rglob("*.yml"):
        out |= set(re.findall(r"^\s*-?\s*record:\s*(\S+)", f.read_text("utf-8"), re.M))
    return out


def metrics_in(expr: str) -> set[str]:
    stripped = re.sub(r'"[^"]*"', '""', expr)
    stripped = re.sub(r"\[[^\]]*\]", "", stripped)
    stripped = re.sub(r"\b(by|without|on)\s*\([^)]*\)", "", stripped)
    out = set()
    for m in _NAME.finditer(stripped):
        tok, end = m.group(0), m.end()
        nxt = stripped[end : end + 1]
        if (
            tok in _FUNCS
            or tok.startswith("$")
            or nxt == "("
            or re.fullmatch(r"\d.*", tok)
        ):
            continue
        if stripped[max(0, m.start() - 1) : m.start()] in ("{", ",") or nxt in (
            "=",
            "!",
            "~",
        ):
            continue
        out.add(tok)
    return out


def _base(name: str) -> str:
    return re.sub(r"_(bucket|count|sum)$", "", name)


def lint_dashboard(
    path: Path, known: set[str], rules: set[str] | None = None
) -> list[str]:
    rules = recorded_rules() if rules is None else rules
    d = json.loads(path.read_text("utf-8"))
    errs: list[str] = []
    for volatile in ("id", "version", "iteration"):
        if volatile in d:
            errs.append(f"{path.name}: volatile field '{volatile}' must be stripped")
    if d.get("schemaVersion") != 39:
        errs.append(f"{path.name}: schemaVersion must be pinned to 39")
    if not any(v.get("name") == "env" for v in d.get("templating", {}).get("list", [])):
        errs.append(f"{path.name}: missing env template variable")
    for p in d["panels"]:
        if p["type"] in ("row", "text"):
            continue
        title = p.get("title", "?")
        if not p.get("title") or not p["fieldConfig"]["defaults"].get("unit"):
            errs.append(f"{path.name}: panel '{title}' needs title and unit")
        if not p["fieldConfig"]["defaults"].get("thresholds", {}).get("steps"):
            errs.append(f"{path.name}: panel '{title}' has no thresholds")
        if p["datasource"].get("uid") != DATASOURCE_UID:
            errs.append(f"{path.name}: panel '{title}' uses undeclared datasource uid")
        for t in p["targets"]:
            expr = t["expr"]
            # Env filter is required whenever ANY catalogue metric is queried; only
            # queries made purely of external metrics are exempt (no substring bypass).
            if (
                any(m not in EXTERNAL for m in metrics_in(expr))
                and 'env="$env"' not in expr
            ):
                errs.append(f"{path.name}: panel '{title}' query lacks env filter")
            if re.search(r"\[\d+[smh]\]", expr):
                errs.append(
                    f"{path.name}: panel '{title}' uses a fixed range; use $__rate_interval"
                )
            for m in metrics_in(expr):
                if m.startswith("cv:"):
                    # Recording rules must exist in infra/prometheus once any are defined.
                    if rules and m not in rules:
                        errs.append(
                            f"{path.name}: panel '{title}' references recording "
                            f"rule '{m}' not defined in infra/prometheus"
                        )
                    continue
                if m not in EXTERNAL and _base(m) not in known:
                    errs.append(
                        f"{path.name}: panel '{title}' references unknown metric '{m}'"
                    )
    return errs


def lint(dash_dir: Path = DASH, rules_dir: Path = RULES) -> list[str]:
    known = catalogue_names()
    rules = recorded_rules(rules_dir)
    files = sorted(dash_dir.glob("*.json"))
    errs = [] if len(files) == 7 else [f"expected 7 dashboards, found {len(files)}"]
    for f in files:
        errs += lint_dashboard(f, known, rules)
    return errs


if __name__ == "__main__":
    # --strict is the CI mode; behaviour is already strict (kept explicit for the workflow).
    problems = lint()
    print("\n".join(problems) or "dashboards ok")
    sys.exit(1 if problems else 0)
