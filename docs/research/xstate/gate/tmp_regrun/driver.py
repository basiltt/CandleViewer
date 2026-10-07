import subprocess, sys, time, json, os

PY = r"<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

base = r"<workspace>/CandleViewer/docs/research/xstate"
scripts = [l.strip() for l in open(os.path.join(base, "gate/tmp_regrun/scriptlist.txt"), encoding="utf-8") if l.strip()]

results = []
t0 = time.time()
for s in scripts:
    path = os.path.join(base, s)
    start = time.time()
    try:
        p = subprocess.run([PY, path], cwd=base, env=env, capture_output=True, text=True, timeout=120)
        status = "PASS" if p.returncode == 0 else "FAIL"
        tail = (p.stdout[-400:] + p.stderr[-400:]) if status == "FAIL" else ""
    except subprocess.TimeoutExpired:
        status = "TIMEOUT"
        tail = ""
    dur = time.time() - start
    results.append({"script": s, "status": status, "seconds": round(dur, 2), "tail": tail})
    print(f"{status:8s} {dur:6.2f}s  {s}")

json.dump(results, open(os.path.join(base, "gate/tmp_regrun/results.json"), "w", encoding="utf-8"), indent=1)
print("TOTAL", round(time.time() - t0, 1), "s")
