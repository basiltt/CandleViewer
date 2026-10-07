import subprocess, sys, os, json, time, glob

PY = r"<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
ROOT = r"<workspace>/CandleViewer/docs/research/xstate"

DIRS = [
    "issues/verify-main-6db65d8",
    "issues/verify-main-f28719c",
    "issues/new-0.8.0/repro",
    "issues/new-main/repro",
    "issues/post-6db65d8/new/repro",
    "probes",
]

def collect():
    files = []
    for d in DIRS:
        full = os.path.join(ROOT, d)
        if not os.path.isdir(full):
            continue
        for f in sorted(glob.glob(os.path.join(full, "*.py"))):
            if "__pycache__" in f:
                continue
            files.append(f)
    # probes/main-*/*.py
    for sub in glob.glob(os.path.join(ROOT, "probes", "main-*")):
        if os.path.isdir(sub) and "refute" not in sub:
            for f in sorted(glob.glob(os.path.join(sub, "*.py"))):
                files.append(f)
    return files

def run_one(path, timeout=60):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    t0 = time.time()
    try:
        p = subprocess.run([PY, path], capture_output=True, text=True, timeout=timeout, env=env, errors="replace")
        dt = time.time() - t0
        return {"rc": p.returncode, "timeout": False, "dt": dt,
                "tail": (p.stdout[-800:] + p.stderr[-800:])}
    except subprocess.TimeoutExpired:
        dt = time.time() - t0
        return {"rc": None, "timeout": True, "dt": dt, "tail": "TIMEOUT"}

def main():
    files = collect()
    out_path = os.path.join(ROOT, "gate", "r9_regression_raw.json")
    results = {}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            results = json.load(fh)
    for f in files:
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        if rel in results:
            continue
        print("RUN", rel, flush=True)
        r = run_one(f)
        results[rel] = r
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)
        print("  ->", "TIMEOUT" if r["timeout"] else r["rc"], flush=True)

if __name__ == "__main__":
    main()
