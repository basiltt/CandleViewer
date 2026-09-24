"""N2 -- #204 SCXML §6.1 `statesToInvoke` matrix, both engines, both kinds.

#204: invoke arms only after eventless transitions settle. A state entered
and exited within ONE macrostep must NEVER submit its service.

Cells (each x {def, async def} x {sync, async} engine):
  A  always      -- entered, an `always` rolls forward out of it
  B  rollback    -- entry action raises under actionErrorPolicy:"rollback"
  C  parallel    -- sibling region reaches final -> onDone exits the region
                    that just armed, in the same settle
  D  history     -- always into a state with an invoke that an always
                    immediately leaves again (deep chain)
  E  control     -- state entered and STAYS: the service MUST run (this is
                    the regression guard for the fix)

Oracle: `submitted` counter incremented INSIDE the service body. A/B/C/D
must be 0; E must be 1.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

SUB = {"n": 0}


def svc_def(i, c, e):
    SUB["n"] += 1
    return {"ok": True}


async def svc_async(i, c, e):
    SUB["n"] += 1
    await asyncio.sleep(0)
    return {"ok": True}


def boom(i, c, e, a=None):
    raise RuntimeError("entry action fails -> rollback")


def noop(i, c, e, a=None):
    pass


INV = {"id": "job", "src": "svc", "onDone": {"target": "#done"}}


def cfg_always():
    return {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"GO": "t"}},
            "t": {"invoke": dict(INV), "always": {"target": "u"}},
            "u": {},
            "done": {"id": "done", "type": "final"},
        },
    }


def cfg_rollback():
    return {
        "id": "m",
        "initial": "s",
        "actionErrorPolicy": "rollback",
        "states": {
            "s": {"on": {"GO": "t"}},
            "t": {"entry": ["boom"], "invoke": dict(INV)},
            "done": {"id": "done", "type": "final"},
        },
    }


def cfg_parallel():
    return {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"GO": "p"}},
            "p": {
                "type": "parallel",
                "onDone": {"target": "u"},
                "states": {
                    "r1": {
                        "initial": "a",
                        "states": {
                            "a": {
                                "invoke": dict(INV),
                                "always": {"target": "f"},
                            },
                            "f": {"type": "final"},
                        },
                    },
                    "r2": {
                        "initial": "a",
                        "states": {
                            "a": {"always": {"target": "f"}},
                            "f": {"type": "final"},
                        },
                    },
                },
            },
            "u": {},
            "done": {"id": "done", "type": "final"},
        },
    }


def cfg_chain():
    return {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"GO": "t"}},
            "t": {"always": {"target": "v"}},
            "v": {"invoke": dict(INV), "always": {"target": "w"}},
            "w": {"invoke": dict(INV), "always": {"target": "x"}},
            "x": {},
            "done": {"id": "done", "type": "final"},
        },
    }


def cfg_control():
    return {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {"on": {"GO": "t"}},
            "t": {"invoke": dict(INV)},
            "done": {"id": "done", "type": "final"},
        },
    }


CASES = [
    ("A always roll-forward", cfg_always, 0),
    ("B rollback entry", cfg_rollback, 0),
    ("C parallel sibling final", cfg_parallel, 0),
    ("D always chain x2", cfg_chain, 0),
    ("E control (stays)", cfg_control, 1),
]


def logic(kind):
    return MachineLogic(
        actions={"boom": boom, "noop": noop},
        services={"svc": svc_def if kind == "def" else svc_async},
    )


async def run_async(cfgf, kind):
    SUB["n"] = 0
    m = create_machine(cfgf(), logic=logic(kind))
    it = Interpreter(m)
    await it.start()
    try:
        await it.send("GO")
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.15)
    n = SUB["n"]
    ids = list(it.current_state_ids)
    await it.stop()
    return n, ids


def run_sync(cfgf, kind):
    SUB["n"] = 0
    m = create_machine(cfgf(), logic=logic(kind))
    it = SyncInterpreter(m)
    it.start()
    try:
        it.send("GO")
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "NotSupportedError":
            return None, ["NotSupportedError"]
    n = SUB["n"]
    ids = list(it.current_state_ids)
    it.stop()
    return n, ids


async def main():
    print("N2 -- SCXML 6.1 statesToInvoke matrix (#204)")
    print("   submitted counter is incremented INSIDE the service body")
    print()
    fails = []
    for name, cfgf, expect in CASES:
        for kind in ("def", "async def"):
            na, ia = await run_async(cfgf, kind)
            ns, is_ = run_sync(cfgf, kind)
            oka = na == expect
            oks = ns is None or ns == expect
            tag = "PASS" if (oka and oks) else "FAIL"
            print(
                f"  {name:<26} {kind:<9} expect={expect}  "
                f"async_submitted={na} {ia}  sync_submitted={ns} {is_}"
                f"  => {tag}"
            )
            if not oka:
                fails.append(f"{name}/{kind}/async engine (got {na})")
            if not oks:
                fails.append(f"{name}/{kind}/sync engine (got {ns})")
    print()
    print(f"FAILING CELLS = {len(fails)}")
    for f in fails:
        print(f"   - {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
