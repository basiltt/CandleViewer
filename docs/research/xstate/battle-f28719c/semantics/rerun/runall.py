"""Re-run the prior semantics suite on f28719c, both service lanes."""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
MODS = ["n1_persistence", "n2_concurrency", "n3_semantics", "n4_determinism",
        "n5_fuzz_obs_sec", "n7_chain_owed", "n8_persist_sem_sec",
        "n9_livelock_determinism", "na_determinism_obs", "nb_observability",
        "s1_persistence_hooks", "s2_concurrency_obs", "s3_fuzz_livelock",
        "s4_semantics_det_sec"]

def run(mod, lane):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8=1 and "1",
               PYTHONPATH=HERE)
    if lane == "async":
        code = f"import asyncify, runpy; runpy.run_module({mod!r}, run_name='__main__')"
    else:
        code = f"import runpy; runpy.run_module({mod!r}, run_name='__main__')"
    t = time.time()
    try:
        p = subprocess.run([PY, "-c", code], cwd=HERE, env=env,
                           capture_output=True, text=True, timeout=115)
        rc, out = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out = "TIMEOUT", (e.stdout or b"").decode("utf8", "replace")
    fails = [l for l in out.splitlines() if l.startswith(("[FAIL", "[ERROR"))]
    return {"mod": mod, "lane": lane, "rc": rc, "secs": round(time.time() - t, 1),
            "fails": fails, "tail": out[-1500:]}

if __name__ == "__main__":
    only = sys.argv[1:] or MODS
    res = []
    for m in only:
        for lane in ("def", "async"):
            r = run(m, lane)
            res.append(r)
            print(f"{m:26} {lane:5} rc={r['rc']} {r['secs']}s fails={len(r['fails'])}")
            for f in r["fails"]:
                print("   ", f[:160])
    os.makedirs(os.path.join(HERE, "..", "results"), exist_ok=True)
    with open(os.path.join(HERE, "..", "results", "rerun.json"), "a",
              encoding="utf-8") as fh:
        for r in res:
            fh.write(json.dumps(r) + "\n")
