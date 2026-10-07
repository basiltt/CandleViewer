"""R13 regression sweep: run every historical repro/probe script under v0.9.0."""
import concurrent.futures as cf
import glob
import json
import os
import subprocess
import sys
import time

PY = r"<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
ROOT = r"<workspace>/CandleViewer/docs/research/xstate"
CWD = r"<home>"
CAP = 120

PATTERNS = [
    "issues/verify-*/*.py",
    "issues/new-0.8.0/repro/*.py",
    "issues/new-main/repro/*.py",
    "issues/post-*/new/repro/*.py",
    "probes/*.py",
    "probes/main-*/*.py",
]


def collect():
    out = []
    for pat in PATTERNS:
        for p in glob.glob(os.path.join(ROOT, pat)):
            n = p.replace("\\", "/")
            if "__pycache__" in n or "/refute" in n or "/refuted/" in n:
                continue
            out.append(n)
    return sorted(set(out))


def run(path):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            [PY, path], cwd=CWD, env=env, timeout=CAP,
            capture_output=True, text=True, errors="replace",
        )
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = "TIMEOUT", "", ""
    el = time.perf_counter() - t0
    tail = (out or "")[-1500:] + "\n--STDERR--\n" + (err or "")[-1500:]
    return {
        "path": path.replace(ROOT + "/", ""),
        "rc": rc,
        "status": "PASS" if rc == 0 else ("TIMEOUT" if rc == "TIMEOUT" else "FAIL"),
        "seconds": round(el, 2),
        "tail": tail,
    }


def main():
    scripts = collect()
    print(f"[sweep] {len(scripts)} scripts", flush=True)
    res = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(run, scripts), 1):
            res.append(r)
            if i % 50 == 0:
                print(f"[sweep] {i}/{len(scripts)}", flush=True)
    outp = os.path.join(ROOT, "gate", "sweep-r13.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    n = {}
    for r in res:
        n[r["status"]] = n.get(r["status"], 0) + 1
    print("[sweep] totals", n)
    print("[sweep] wrote", outp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
