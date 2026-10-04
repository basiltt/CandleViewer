"""E04-X02 AC5: render the REAL Alertmanager template for a page alert whose labels and
annotations carry secret-shaped values and assert none survives into the payload.

Two layers:
* `test_template_redaction_rules_*` applies the template's own `reReplaceAll` pipelines
  (extracted from `cv.tmpl`, RE2-compatible) in Python - runs everywhere.
* `test_amtool_render_*` renders with the pinned `amtool` image (integration, needs docker;
  the same render is also a step in `_job-py.yml`).
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
AM_DIR = REPO / "infra" / "alertmanager"
TMPL = (AM_DIR / "templates" / "cv.tmpl").read_text(encoding="utf-8")
BASE = json.loads((AM_DIR / "tests" / "data" / "grouped_page.json").read_text(encoding="utf-8"))
AM_IMAGE = (
    "prom/alertmanager:v0.27.0"
    "@sha256:e13b6ed5cb929eeaee733479dce55e10eb3bc2e9c4586c705a4e8da41e5eacf5"
)

# Assembled at runtime: no secret-shaped literal sits in the repo.
KEY = "AKIA" + "Zq9Xw3Lm" + "Pv7Rt2Yb" + "Nc4Hd"
JWT = ".".join(
    ["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiJhYmNkZWYxMjM0NTYifQ", "c2lnbmF0dXJlMTIzNDU2Nzg5"]
)
KV = "api_secret=" + "Zq9" + "x" * 20 + "AbCd"
SHAPES = (KEY, JWT, "Zq9" + "x" * 20 + "AbCd")


def _poisoned() -> dict[str, Any]:
    d: dict[str, Any] = copy.deepcopy(BASE)
    evil = {"component": KEY, "env": JWT}
    d["groupLabels"].update(evil)
    d["commonLabels"].update({**evil, "severity": "page"})
    d["commonAnnotations"]["summary"] = f"Unknown orders {KV} {KEY} {JWT}"
    d["commonAnnotations"]["runbook_url"] = f"docs/x.md#a?token={KEY}&k={JWT}"
    d["groupLabels"]["alertname"] = f"Oms{KV}"
    for a in d["alerts"]:
        a["labels"].update({"api_key": KEY, "session_token": JWT})
        a["annotations"]["description"] = KV
    return d


def _apply_pipeline(value: str, expr: str) -> str:
    for pat in re.findall(r"reReplaceAll `([^`]+)` \"\[redacted\]\"", expr):
        value = re.sub(
            pat.replace("(?i)", ""),
            "[redacted]",
            value,
            flags=re.IGNORECASE if "(?i)" in pat else 0,
        )
    return value


_FIELD_RE = (
    r"\{\{ \.(Group|Common)(Labels|Annotations)\.(\w+)"
    r"((?: \| reReplaceAll `[^`]+` \"\[redacted\]\")*) \}\}"
)


def _render_python(data: dict[str, Any]) -> str:
    """Evaluate each `{{ .Group|Common... | reReplaceAll ... }}` field of cv.title/cv.body."""
    out: list[str] = []
    for m in re.finditer(
        _FIELD_RE,
        TMPL,
    ):
        src = data[m.group(1).lower() + m.group(2)]
        out.append(_apply_pipeline(str(src[m.group(3)]), m.group(4)))
    return "\n".join(out)


def test_template_redaction_rules_leave_no_secret_shape() -> None:
    rendered = _render_python(_poisoned())
    assert "[redacted]" in rendered
    for shape in SHAPES:
        assert shape not in rendered
    assert "api_secret=" not in rendered and "token=" not in rendered


def test_template_every_interpolation_is_redacted() -> None:
    fields = re.findall(r"\{\{ \.(?:Group|Common)(?:Labels|Annotations)\.\w+.*?\}\}(?!\})", TMPL)
    plain = [f for f in fields if "reReplaceAll" not in f]
    assert len(fields) >= 7
    # only the PAGE/TICKET severity switch (an `eq` comparison, not output) may be unredacted
    assert all("eq .CommonLabels.severity" in f for f in plain), plain


@pytest.mark.integration
def test_amtool_render_poisoned_page_alert_has_no_secret(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker unavailable; amtool render also runs in _job-py.yml")
    fixture = tmp_path / "poisoned.json"
    fixture.write_text(json.dumps(_poisoned()), encoding="utf-8")
    tmp_path.chmod(0o755)  # amtool runs as `nobody` inside the container
    fixture.chmod(0o644)
    text = '{{ template "cv.title" . }} | {{ template "cv.body" . }}'
    res = subprocess.run(  # noqa: S603  # fixed argv, pinned image, no shell
        [
            docker,
            "run",
            "--rm",
            "--entrypoint",
            "amtool",
            "-v",
            f"{AM_DIR}:/etc/alertmanager:ro",
            "-v",
            f"{tmp_path}:/data:ro",
            AM_IMAGE,
            "template",
            "render",
            "--template.glob=/etc/alertmanager/templates/*.tmpl",
            "--template.data=/data/poisoned.json",
            f"--template.text={text}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    for shape in SHAPES:
        assert shape not in res.stdout
    assert "[PAGE]" in res.stdout and "Occurrences: 3" in res.stdout
