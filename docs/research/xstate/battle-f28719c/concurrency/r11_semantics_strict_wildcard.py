"""R11 - SEMANTICS: 5-way receipt matrix and the strict+wildcard matrix.

A) guard-crash / denied / deferred / unhandled / error-kill must produce
   five DISTINCT `(changed, denied, error)` signatures on the async engine
   (#170 gives three; #189 adds the error kill).
B) #190: a `"*"` handler must NOT defeat `strict`. Four cells:
     declared        -> accepted
     undeclared      -> refused by strict
     wildcard-only   -> strict still refuses the undeclared NAME
     raise-of-undeclared (validator's dispatch question)
Both engines, both service kinds.
"""

from __future__ import annotations

import asyncio

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
    emit,
    make_service,
)


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def boom(ctx, e):  # guard that CRASHES  # noqa: ANN001
    raise RuntimeError("guard exploded")


def never(ctx, e):  # guard that DENIES  # noqa: ANN001
    return False


SEM = {
    "id": "r11",
    "initial": "idle",
    "context": {"n": 0},
    "guardErrorPolicy": "raise",
    "onUnhandled": "defer",
    "states": {
        "idle": {
            "on": {
                "OK": {"actions": ["bump"]},
                "DENIED": {"target": "other", "guard": "never"},
                "CRASH": {"target": "other", "guard": "boom"},
                "DEFERME": {"target": "other", "guard": "never"},
            }
        },
        "other": {},
    },
}

KILL = {
    "id": "r11k",
    "initial": "idle",
    "context": {"n": 0},
    "onUnhandled": "error",
    "states": {"idle": {"on": {"OK": {"actions": ["bump"]}}}},
}


def mk(cfg, kind):  # noqa: ANN001
    return create_machine(
        cfg,
        logic=MachineLogic(
            actions={"bump": bump},
            guards={"boom": boom, "never": never},
            services={"s": make_service(kind)},
        ),
    )


def sig(rec, exc) -> str:
    if exc is not None:
        return f"raised:{type(exc).__name__}"
    if rec is None:
        return "None(sync)"
    return (
        f"changed={getattr(rec,'changed',None)},"
        f"denied={getattr(rec,'denied',None)},"
        f"error={type(getattr(rec,'error',None)).__name__}"
    )


async def matrix_a(kind: str) -> dict:
    rows = {}
    i = Interpreter(mk(SEM, kind))
    await asyncio.wait_for(i.start(), 10)
    for ev in ("OK", "DENIED", "CRASH", "UNKNOWN_EVENT"):
        try:
            r = await asyncio.wait_for(i.send(ev, wait=True), 5)
            rows[ev] = sig(r, None)
        except Exception as exc:  # noqa: BLE001
            rows[ev] = sig(None, exc)
    await asyncio.wait_for(i.stop(), 20)
    # error kill on its own machine (it terminates the interpreter)
    k = Interpreter(mk(KILL, kind))
    await asyncio.wait_for(k.start(), 10)
    try:
        r = await asyncio.wait_for(k.send("NOPE", wait=True), 5)
        rows["ERROR_KILL"] = sig(r, None)
    except Exception as exc:  # noqa: BLE001
        rows["ERROR_KILL"] = sig(None, exc)
    try:
        await asyncio.wait_for(k.stop(), 20)
    except Exception:  # noqa: BLE001
        pass
    return {"engine": "async", "kind": kind, "signatures": rows,
            "distinct": len(set(rows.values())), "cells": len(rows)}


def matrix_a_sync(kind: str) -> dict:
    if kind == "async def":
        return {"engine": "sync", "kind": kind, "signatures": "N/A", "distinct": 0}
    rows = {}
    i = SyncInterpreter(mk(SEM, kind))
    i.start()
    for ev in ("OK", "DENIED", "CRASH", "UNKNOWN_EVENT"):
        try:
            r = i.send(ev)
            rows[ev] = sig(r, None)
        except Exception as exc:  # noqa: BLE001
            rows[ev] = sig(None, exc)
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    k = SyncInterpreter(mk(KILL, kind))
    k.start()
    try:
        r = k.send("NOPE")
        rows["ERROR_KILL"] = sig(r, None)
    except Exception as exc:  # noqa: BLE001
        rows["ERROR_KILL"] = sig(None, exc)
    try:
        k.stop()
    except Exception:  # noqa: BLE001
        pass
    return {"engine": "sync", "kind": kind, "signatures": rows,
            "distinct": len(set(rows.values())), "cells": len(rows)}


# ------------------------------------------------------------ strict/wildcard
def strict_cfg(variant: str) -> dict:
    if variant == "declared":
        on = {"KNOWN": {"actions": ["bump"]}}
    elif variant == "wildcard_only":
        on = {"*": {"actions": ["bump"]}}
    else:  # declared_plus_wildcard
        on = {"KNOWN": {"actions": ["bump"]}, "*": {"actions": ["bump"]}}
    return {
        "id": "r11s",
        "initial": "idle",
        "context": {"n": 0},
        "strict": True,
        "states": {"idle": {"on": on}},
    }


async def strict_matrix(kind: str) -> list:
    rows = []
    for variant in ("declared", "wildcard_only", "declared_plus_wildcard"):
        for ev in ("KNOWN", "UNDECLARED"):
            for engine in ("async", "sync"):
                if engine == "sync" and kind == "async def":
                    continue
                m = mk(strict_cfg(variant), kind)
                try:
                    if engine == "async":
                        i = Interpreter(m)
                        await asyncio.wait_for(i.start(), 10)
                        try:
                            r = await asyncio.wait_for(i.send(ev, wait=True), 5)
                            out = sig(r, None)
                        except Exception as exc:  # noqa: BLE001
                            out = sig(None, exc)
                        await asyncio.wait_for(i.stop(), 20)
                    else:
                        i = SyncInterpreter(m)
                        i.start()
                        try:
                            r = i.send(ev)
                            out = sig(r, None)
                        except Exception as exc:  # noqa: BLE001
                            out = sig(None, exc)
                        i.stop()
                except Exception as exc:  # noqa: BLE001
                    out = f"setup:{type(exc).__name__}"
                rows.append(
                    {"variant": variant, "event": ev, "engine": engine,
                     "kind": kind, "outcome": out,
                     "strict_should_refuse": ev == "UNDECLARED"}
                )
    return rows


async def main() -> int:
    a = [await matrix_a(k) for k in ("def", "async def")]
    a += [matrix_a_sync(k) for k in ("def",)]
    s = []
    for k in ("def", "async def"):
        s += await strict_matrix(k)
    bad = []
    for r in a:
        if r["engine"] == "async" and r["distinct"] != r["cells"]:
            bad.append((r["engine"], r["kind"],
                        f"only {r['distinct']}/{r['cells']} distinct signatures"))
    wildcard_defeats_strict = [
        r for r in s
        if r["strict_should_refuse"]
        and "wildcard" in r["variant"]
        and "raised" not in r["outcome"]
        and "error=Unhandled" not in r["outcome"]
        and "error=Strict" not in r["outcome"]
    ]
    emit(
        "r11_semantics_strict_wildcard",
        {
            "receipt_matrix": a,
            "strict_wildcard_matrix": s,
            "receipt_failures": bad,
            "wildcard_defeats_strict": wildcard_defeats_strict,
            "result": "FAIL" if bad or wildcard_defeats_strict else "PASS",
        },
    )
    return 1 if bad or wildcard_defeats_strict else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
