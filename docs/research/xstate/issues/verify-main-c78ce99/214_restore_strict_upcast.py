"""R10-05 (STANDALONE): the restore path bypasses `strict`, and a 0.8.0-era
persisted `after` record is now silently REFUSED rather than demoted.

Two symptoms, one code path.

(a) `_check_strict` runs at the `send()` call site
    (base_interpreter.py:1767), but the restore path re-enqueues via
    `_enqueue_restored` -> `_put_inbox` (interpreter.py:1499-1500), bypassing
    it. So an undeclared event restored from `pending_events` is accepted under
    `strict: True`, contradicting the restore contract documented at
    events.py:403-414.

(b) MIGRATION CLIFF. A record written by 0.8.0 has `kind: "after"` (the v2
    shape, so the v1 name-based fallback does not catch it) but NO `engine`
    flag. #203's new provenance gate then refuses it -- and the deadline is
    DROPPED rather than demoted: no raise, no WARNING, nothing on `last_error`,
    and `has_dormant_timers` does not cover it because the event was already in
    the persisted inbox rather than awaiting re-arm.

The security direction of #203 is right. The failure mode is not: a refused
restored DEADLINE must be loud.

Exit 0 = strict gates restored events AND the pre-0.8.1 record is loud.
Exit 1 = either symptom present.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

# `t.wait` carries a 60-SECOND deadline. Nothing legitimate can fire it inside
# this script's runtime, so reaching `t.late` means a forged/unvetted record
# drove it, and staying in `t.wait` after a restore that CARRIED a fired record
# means the deadline was silently dropped.
CFG = {
    "id": "t",
    "initial": "wait",
    "strict": True,
    "states": {
        "wait": {"after": {60000: "late"}},
        "late": {},
    },
}


def _build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def _restore(blob: dict) -> dict:
    interp = Interpreter.from_snapshot(json.dumps(blob), _build())
    await interp.start()
    await asyncio.sleep(0.35)
    out = {
        "states": sorted(interp.current_state_ids),
        "last_error": type(getattr(interp, "last_error", None)).__name__,
        "status": getattr(interp, "status", None),
    }
    await interp.stop()
    return out


async def main() -> int:
    bad = 0

    # Baseline blob at quiescence.
    live = Interpreter(_build())
    await live.start()
    await asyncio.sleep(0.05)
    base = live.get_persisted_snapshot()
    await live.stop()

    # --- (a) strict is not applied to restored events ---------------------
    b = json.loads(json.dumps(base))
    b["pending_events"] = [{"kind": "event", "type": "BOGUS", "payload": {}}]
    r = await _restore(b)
    leaked = r["last_error"] == "NoneType" and r["status"] == "running"
    print(f"(a) strict:True + restored undeclared 'BOGUS' -> "
          f"status={r['status']} last_error={r['last_error']} states={r['states']}")
    print(f"    {'<-- ACCEPTED, strict bypassed' if leaked else 'refused (ok)'}")
    bad += 1 if leaked else 0

    # --- (b) pre-0.8.1 `after` record: refused, and SILENTLY --------------
    b2 = json.loads(json.dumps(base))
    # Exactly what 0.8.0 wrote: kind=="after", NO "engine" flag.
    b2["pending_events"] = [
        {"kind": "after", "type": "after.60000.t.wait", "payload": {}}
    ]
    r2 = await _restore(b2)
    dropped_silently = (
        r2["states"] == ["t.wait"]
        and r2["last_error"] == "NoneType"
    )
    print(f"(b) pre-0.8.1 `after` record restored -> states={r2['states']} "
          f"last_error={r2['last_error']}")
    print(f"    {'<-- DEADLINE DROPPED SILENTLY' if dropped_silently else 'loud (ok)'}")
    bad += 1 if dropped_silently else 0

    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok", f"({bad}/2 symptoms)")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 40.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
