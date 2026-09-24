"""Q5b - PYTHONHASHSEED sweep driver (records the result of the loop run
in the report). Determinism must not depend on str/dict hash ordering.

Run: for s in 0 1 7 12345 99991; PYTHONHASHSEED=$s python q5b_...
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

from common import emit

SEEDS = ["0", "1", "7", "12345", "99991"]
SNIP = (
    "import asyncio,sys,json;sys.path.insert(0,'.');"
    "import q5_determinism_sentinel as q;"
    "a=asyncio.run(q.trace_async());s=q.trace_sync();"
    "print(json.dumps({'async_laps':a[1],'async_trip':a[2],'async_n':a[3],"
    "'sync_laps':s[1],'sync_trip':s[2],'sync_n':s[3],"
    "'engines_same_trace':a[0]==s[0],'trace_len':len(a[0])}))"
)


def main() -> int:
    rows = {}
    for seed in SEEDS:
        env = dict(os.environ, PYTHONHASHSEED=seed,
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        p = subprocess.run(
            [sys.executable, "-c", SNIP],
            capture_output=True, text=True, env=env, timeout=90,
        )
        line = [x for x in p.stdout.strip().splitlines() if x.startswith("{")]
        rows[seed] = json.loads(line[-1]) if line else {"error": p.stderr[-300:]}
    vals = {json.dumps(v, sort_keys=True) for v in rows.values()}
    ok = len(vals) == 1 and all(v.get("engines_same_trace") for v in rows.values())
    emit("q5b_hashseed_sweep", {
        "seeds": SEEDS, "per_seed": rows,
        "distinct_outcomes": len(vals),
        "result": "PASS" if ok else "FAIL",
    })
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
