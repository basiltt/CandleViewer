"""D1 -- replay determinism: 50 runs per engine, full-trace comparison.

Method
------
Build the same machine + the same seeded event script, run it N times on the
async `Interpreter` and N times on the `SyncInterpreter`, every run driven by a
fresh `SimulatedClock` (virtual time -- no wall clock anywhere). After each run
we compare a full digest:

  * user-action call order (including guard evaluations, interleaved),
  * plugin hook order,
  * transition trace (from-config, event, to-config),
  * per-`send` receipt fields (state_ids, changed, error type, deferred),
  * canonical snapshot JSON at fixed checkpoints.

Run:
  python d1_replay.py [--runs 50] [--events 10000]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dmachine import (  # noqa: E402
    Recorder,
    TracePlugin,
    build,
    canon_snapshot,
    make_script,
)
from xstate_statemachine import Interpreter, SyncInterpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CHECKPOINTS = {1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 9999}


def _receipt_row(r):
    if r is None:
        return None
    return (
        tuple(sorted(r.state_ids)),
        bool(r.changed),
        type(r.error).__name__ if r.error is not None else None,
        bool(getattr(r, "deferred", False)),
    )


async def run_async(script, jitter=0.0):
    rec = Recorder()
    clock = SimulatedClock()
    machine = build(rec)
    interp = Interpreter(machine, clock=clock)
    interp.use(TracePlugin(rec))
    await interp.start()
    for k, step in enumerate(script):
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            _, etype, payload = step
            r = await interp.send(etype, wait=True, **payload)
            rec.receipts.append(_receipt_row(r))
        if k in CHECKPOINTS:
            rec.snapshots.append(
                (k, canon_snapshot(interp.get_persisted_snapshot()))
            )
    rec.snapshots.append(
        ("final", canon_snapshot(interp.get_persisted_snapshot()))
    )
    rec.final_context = json.dumps(interp.context, sort_keys=True, default=repr)
    await interp.stop()
    return rec


def run_sync(script):
    rec = Recorder()
    clock = SimulatedClock()
    machine = build(rec)
    interp = SyncInterpreter(machine, clock=clock)
    interp.use(TracePlugin(rec))
    interp.start()
    for k, step in enumerate(script):
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            _, etype, payload = step
            r = interp.send(etype, wait=True, **payload)
            rec.receipts.append(_receipt_row(r))
        if k in CHECKPOINTS:
            rec.snapshots.append(
                (k, canon_snapshot(interp.get_persisted_snapshot()))
            )
    rec.snapshots.append(
        ("final", canon_snapshot(interp.get_persisted_snapshot()))
    )
    rec.final_context = json.dumps(interp.context, sort_keys=True, default=repr)
    interp.stop()
    return rec


def digest_parts(rec):
    d = rec.digest()
    d["context"] = rec.final_context
    # 🔬 D-determinism-1 isolation: the `deferred` field is the 4th tuple
    #    slot. Digest the receipts with and without it, so a divergence can
    #    be attributed to that field alone rather than to real disagreement
    #    about state / changed / error.
    d["receipts_no_deferred"] = [
        r[:3] if r is not None else None for r in rec.receipts
    ]
    return {
        k: hashlib.sha256(
            json.dumps(v, sort_keys=True, default=repr).encode()
        ).hexdigest()
        for k, v in d.items()
    }


def compare(name, digests, raws):
    first = digests[0]
    bad = {}
    for k in first:
        vals = {d[k] for d in digests}
        if len(vals) > 1:
            bad[k] = sorted(vals)
    print(f"[{name}] runs={len(digests)} identical={'YES' if not bad else 'NO'}")
    for k in sorted(first):
        print(f"    {k:22s} {'STABLE' if k not in bad else 'DIVERGENT (%d distinct)' % len(bad[k])}")
    for k, v in bad.items():
        a = raws[0].digest().get(k)
        if k == "context":
            a = raws[0].final_context
        b = None
        for r in raws[1:]:
            rv = r.digest().get(k) if k != "context" else r.final_context
            if (
                hashlib.sha256(
                    json.dumps(rv, sort_keys=True, default=repr).encode()
                ).hexdigest()
                != digests[0][k]
            ):
                b = rv
                break
        if isinstance(a, list) and isinstance(b, list):
            for idx, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"      {k}: first diff at index {idx}: {x!r} != {y!r}")
                    break
            else:
                print(f"      {k}: lengths differ: {len(a)} vs {len(b)}")
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--events", type=int, default=10000)
    args = ap.parse_args()

    script = make_script(args.events)
    n_send = sum(1 for s in script if s[0] == "send")
    n_tick = len(script) - n_send
    print(f"script: {len(script)} steps ({n_send} sends, {n_tick} clock ticks)")

    a_recs = [asyncio.run(run_async(script)) for _ in range(args.runs)]
    a_dig = [digest_parts(r) for r in a_recs]
    ok_a = compare("async x%d" % args.runs, a_dig, a_recs)

    s_recs = [run_sync(script) for _ in range(args.runs)]
    s_dig = [digest_parts(r) for r in s_recs]
    ok_s = compare("sync  x%d" % args.runs, s_dig, s_recs)

    print("\n--- cross-engine (async run 0 vs sync run 0) ---")
    xa, xs = a_dig[0], s_dig[0]
    for k in sorted(xa):
        same = xa[k] == xs[k]
        print(f"  {k:12s} {'SAME' if same else 'DIFFER'}")
    ar, sr = a_recs[0].digest(), s_recs[0].digest()
    ar["context"] = a_recs[0].final_context
    sr["context"] = s_recs[0].final_context
    for k in sorted(ar):
        if xa[k] != xs[k]:
            A, B = ar[k], sr[k]
            if isinstance(A, list) and isinstance(B, list):
                for idx, (x, y) in enumerate(zip(A, B)):
                    if x != y:
                        print(f"    {k}: first diff @ {idx}")
                        print(f"      async: {x!r}")
                        print(f"      sync : {y!r}")
                        break
                else:
                    print(f"    {k}: prefix equal, lengths {len(A)} vs {len(B)}")
            else:
                print(f"    {k}: async={str(A)[:200]}")
                print(f"    {k}: sync ={str(B)[:200]}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d1_replay.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "runs": args.runs,
                "steps": len(script),
                "async_stable": ok_a,
                "sync_stable": ok_s,
                "async_digest": a_dig[0],
                "sync_digest": s_dig[0],
                "trace_len_async": len(a_recs[0].actions),
                "trace_len_sync": len(s_recs[0].actions),
            },
            f,
            indent=2,
        )
    print("\nwrote out/d1_replay.json")


if __name__ == "__main__":
    main()
