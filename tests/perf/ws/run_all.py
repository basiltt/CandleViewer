"""E17-K01 one-command driver: generate -> measure (Python) -> decode in Chromium -> verdict.

    python tests/perf/ws/run_all.py            # from repo root; offline, seeded, ~2 min

Writes the committed evidence artefact tests/perf/ws/results.json.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "out"
BW_GATE, DEC_GATE = 40.0, 30.0


def pct(base: float, new: float) -> float:
    return (1 - new / base) * 100


def decode_cost_per_s(
    browser: dict[str, Any], frames: dict[str, int], seconds: int
) -> dict[str, Any]:
    """Workspace decode CPU: sum(p50 per-frame us x frames/s) in ms of CPU per second."""
    out: dict[str, float] = {}
    for arm in ("json", "msgpack", "binary"):
        out[arm] = (
            sum(browser[k][arm]["p50_us"] * n / seconds for k, n in frames.items() if k in browser)
            / 1000
        )
    return out


def main() -> int:
    env = {**os.environ, "PYTHONPATH": str(HERE)}
    subprocess.run(
        [sys.executable, str(HERE / "measure.py")], check=True, env=env, stdout=subprocess.DEVNULL
    )
    subprocess.run(["node", str(HERE / "run_browser.mjs"), "--runs=5"], check=True, cwd=ROOT)
    py = json.loads((OUT / "py-results.json").read_text(encoding="utf-8"))
    br = json.loads((OUT / "browser-results.json").read_text(encoding="utf-8"))
    secs = py["seconds"]

    def bw(section: str, arm: str, key: str) -> float:
        return float(py[section][arm][key])

    verdicts: dict[str, Any] = {}
    for section in ("bandwidth_four_pane", "bandwidth_with_heatmap"):
        v: dict[str, Any] = {}
        # Like-for-like payload encoding, no compression on either side.
        v["raw_vs_raw_pct"] = pct(
            bw(section, "json", "raw_kib_s"), bw(section, "binary", "raw_kib_s")
        )
        # As specified by 23-ws 3.5: JSON deflated, binary not deflated.
        v["spec_json_deflate_vs_binary_raw_pct"] = pct(
            bw(section, "json", "deflate_kib_s"), bw(section, "binary", "raw_kib_s")
        )
        # Both deflated (what a stock WS server does for every message).
        v["both_deflated_pct"] = pct(
            bw(section, "json", "deflate_kib_s"), bw(section, "binary", "deflate_kib_s")
        )
        v["msgpack_struct_raw_vs_json_raw_pct"] = pct(
            bw(section, "json", "raw_kib_s"), bw(section, "msgpack", "raw_kib_s")
        )
        verdicts[section] = v

    dec: dict[str, Any] = {}
    fc = py["frames_by_kind"]
    four = {k: n for k, n in fc.items() if k not in ("heatmap",)}
    dec["four_pane_ms_cpu_per_s"] = decode_cost_per_s(br["four_pane"], four, secs)
    dec["with_heatmap_ms_cpu_per_s"] = decode_cost_per_s(br["four_pane"], fc, secs)
    for key in ("four_pane_ms_cpu_per_s", "with_heatmap_ms_cpu_per_s"):
        d = dec[key]
        d["binary_vs_json_pct"] = pct(d["json"], d["binary"])
        d["msgpack_vs_json_pct"] = pct(d["json"], d["msgpack"])
    per_kind = {
        k: {
            "binary_vs_json_p50_pct": pct(v["json"]["p50_us"], v["binary"]["p50_us"]),
            "binary_vs_json_p99_pct": pct(v["json"]["p99_us"], v["binary"]["p99_us"]),
        }
        for k, v in br["four_pane"].items()
    }

    def passed(x: float, gate: float) -> str:
        return "PASS" if x >= gate else "FAIL"

    b4 = verdicts["bandwidth_four_pane"]
    d4 = dec["four_pane_ms_cpu_per_s"]
    gate = {
        "bandwidth_ge_40_raw_vs_raw": passed(b4["raw_vs_raw_pct"], BW_GATE),
        "bandwidth_ge_40_as_specified_3_5": passed(
            b4["spec_json_deflate_vs_binary_raw_pct"], BW_GATE
        ),
        "decode_ge_30_workspace_weighted": passed(d4["binary_vs_json_pct"], DEC_GATE),
    }
    result = {
        "ticket": "E17-K01",
        "gate": {"bandwidth_pct": BW_GATE, "decode_pct": DEC_GATE},
        "machine": {
            "cpu": br["machine"]["cpu"],
            "cpus": br["machine"]["cpuCount"],
            "mem_mb": br["machine"]["totalMemMb"],
            "os": f"{platform.system()} {platform.release()}",
        },
        "versions": {
            "python": platform.python_version(),
            "browser": br["browser"],
            "node": br["node"],
            "msgpack_js": br["msgpack_lib"],
        },
        "python": py,
        "browser": br,
        "verdicts": {
            "bandwidth": verdicts,
            "decode": dec,
            "decode_per_kind": per_kind,
            "gate": gate,
        },
    }
    (HERE / "results.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["verdicts"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
