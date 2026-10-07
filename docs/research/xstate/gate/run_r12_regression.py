"""Round-11 regression driver: run every pinned script, record status.

Resumable (skips scripts already in results.json). Parallel worker pool.
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time

PY = r"<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
BASE = r"<workspace>/CandleViewer/docs/research/xstate"
NEUTRAL = r"<home>"
OUT = os.path.join(BASE, "gate", "r12_regression_raw.json")
LIST = os.path.join(BASE, "gate", "r12_scriptlist.txt")

ENV = dict(os.environ)
ENV["PYTHONIOENCODING"] = "utf-8"
ENV["PYTHONUTF8"] = "1"


def run_one(rel, timeout=120):
    path = os.path.join(BASE, rel)
    t0 = time.time()
    try:
        p = subprocess.run(
            [PY, path], cwd=NEUTRAL, env=ENV, capture_output=True,
            text=True, timeout=timeout, errors="replace",
        )
        status = "PASS" if p.returncode == 0 else "FAIL"
        tail = "" if status == "PASS" else (p.stdout[-1500:] + "\n--STDERR--\n" + p.stderr[-1500:])
        return rel, {"status": status, "rc": p.returncode,
                     "seconds": round(time.time() - t0, 2), "tail": tail}
    except subprocess.TimeoutExpired:
        return rel, {"status": "TIMEOUT", "rc": None,
                     "seconds": round(time.time() - t0, 2), "tail": "TIMEOUT"}


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    scripts = [l.strip() for l in open(LIST, encoding="utf-8") if l.strip()]
    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT, encoding="utf-8"))
    todo = [s for s in scripts if s not in results]
    print(f"{len(todo)} to run ({len(results)} cached), {workers} workers", flush=True)
    done = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_one, s) for s in todo]
        for fut in cf.as_completed(futs):
            rel, r = fut.result()
            results[rel] = r
            done += 1
            if r["status"] != "PASS":
                print(f"  {r['status']:8s} {rel}", flush=True)
            if done % 25 == 0:
                json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1)
                print(f"  ... {done}/{len(todo)}  {time.time()-t0:.0f}s", flush=True)
    json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1)
    n = len(results)
    from collections import Counter
    print("TOTALS", Counter(v["status"] for v in results.values()), n,
          f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
