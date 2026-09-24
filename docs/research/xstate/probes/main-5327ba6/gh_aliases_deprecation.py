"""G/H — snake_case<->camelCase alias resolution and the deprecation warning.

G1  BOTH fetch_data and fetchData registered, config needs fetchData
    -> must raise InvalidConfigError (ambiguous)
G2  same, but the two names are bound to the SAME callable -> must NOT raise
G3  only fetchData registered, config says fetch_data
G4  only fetch_data registered, config says fetchData
G5  exact-name precedence: both an exact 'logHTTPStatus' and an alias
    'log_http_status' registered -> exact must win
G6  acronym / digits / non-identifier names
G7  an ACTION and a GUARD with the same normalized name -- collision?
G8  ambiguity that the machine does NOT reference: silent or raised?
G9  three-way ambiguity (fetch_data / fetchData / FETCH-DATA)
G10 alias resolution mutates the shared MachineLogic registry -- does
    building a second machine from the same logic object see the aliases?
G11 services and guards go through the same path

H1  DeprecationWarning: machine 1 sets actionErrorPolicy explicitly, machine
    2 does not -> does machine 2 still warn in the same process?
H2  once-per-process: two default machines -> exactly one warning
H3  does a machine that never has a failing action warn at all?
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.exceptions import InvalidConfigError  # noqa: E402

PY = sys.executable


def cfg(action_name: str, mid: str = "g") -> dict:
    return {
        "id": mid,
        "initial": "a",
        "context": {"hit": None},
        "states": {"a": {"on": {"GO": {"actions": [action_name]}}}},
    }


def tagger(tag):
    def fn(i, c, e, a):
        c["hit"] = tag

    return fn


def _build(action_name, registry):
    try:
        create_machine(cfg(action_name), logic=MachineLogic(actions=dict(registry)))
        return "built"
    except InvalidConfigError as exc:
        return f"InvalidConfigError"
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


async def _run(action_name, registry):
    m = create_machine(cfg(action_name), logic=MachineLogic(actions=dict(registry)))
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.08)
    hit = i.context["hit"]
    await i.stop()
    return hit


# --------------------------------------------------------------- G1
@_h.probe("G1", "fetch_data AND fetchData both registered (different fns)",
          "InvalidConfigError")
def g1():
    return _build("fetchData", {"fetch_data": tagger("snake"), "fetchData": tagger("camel")})


# --------------------------------------------------------------- G2
@_h.probe("G2", "both names bound to the SAME callable -> no ambiguity", "built")
def g2():
    fn = tagger("same")
    return _build("fetchData", {"fetch_data": fn, "fetchData": fn})


# --------------------------------------------------------------- G3
@_h.probe("G3", "only fetchData registered, config says fetch_data", "camel")
async def g3():
    return await _run("fetch_data", {"fetchData": tagger("camel")})


# --------------------------------------------------------------- G4
@_h.probe("G4", "only fetch_data registered, config says fetchData", "snake")
async def g4():
    return await _run("fetchData", {"fetch_data": tagger("snake")})


# --------------------------------------------------------------- G5
@_h.probe("G5", "exact name wins over an alias", "EXACT")
async def g5():
    return await _run(
        "logHTTPStatus",
        {"logHTTPStatus": tagger("EXACT"), "log_http_status": tagger("ALIAS")},
    )


# --------------------------------------------------------------- G6
@_h.probe(
    "G6",
    "acronyms / digits / non-identifier config names bind to snake_case",
    {"logHTTPStatus": "a", "fetchUserV2": "b", "fetch-data": "c",
     "inline:m.a#entry[0]": "d"},
)
async def g6():
    reg = {
        "log_http_status": tagger("a"),
        "fetch_user_v2": tagger("b"),
        "fetch_data": tagger("c"),
        "inline_m_a_entry_0": tagger("d"),
    }
    out = {}
    for name in ("logHTTPStatus", "fetchUserV2", "fetch-data", "inline:m.a#entry[0]"):
        out[name] = await _run(name, reg)
    return out


# --------------------------------------------------------------- G7
@_h.probe(
    "G7",
    "an ACTION and a GUARD with the same normalized name do not collide",
    {"hit": "ACTION", "guard_called": True},
)
async def g7():
    calls = []

    def is_ready(c, e):
        calls.append("guard")
        return True

    def action_fn(i, c, e, a):
        c["hit"] = "ACTION"

    config = {
        "id": "g7",
        "initial": "a",
        "context": {"hit": None},
        "states": {
            "a": {"on": {"GO": {"actions": ["isReady"], "cond": "is_ready"}}}
        },
    }
    m = create_machine(
        config,
        logic=MachineLogic(actions={"is_ready": action_fn}, guards={"isReady": is_ready}),
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.08)
    out = {"hit": i.context["hit"], "guard_called": bool(calls)}
    await i.stop()
    return out


# --------------------------------------------------------------- G8
@_h.probe("G8", "ambiguity the machine does NOT reference is silent", "built")
def g8():
    return _build(
        "somethingElse",
        {
            "somethingElse": tagger("x"),
            "fetch_data": tagger("snake"),
            "fetchData": tagger("camel"),
        },
    )


# --------------------------------------------------------------- G9
@_h.probe("G9", "three-way ambiguity", "InvalidConfigError")
def g9():
    return _build(
        "fetchData",
        {
            "fetch_data": tagger("1"),
            "fetchData": tagger("2"),
            "FETCH-DATA": tagger("3"),
        },
    )


# --------------------------------------------------------------- G10
@_h.probe(
    "G10",
    "resolve_aliases MUTATES the shared logic registry (leaks across machines)",
    "DOCUMENT",
)
def g10():
    logic = MachineLogic(actions={"fetch_data": tagger("snake")})
    create_machine(cfg("fetchData", "m1"), logic=logic)
    keys_after_first = sorted(logic.actions)
    # A second, unrelated machine reuses the same logic object. Does it now
    # see a key that was never registered by the caller?
    leaked = "fetchData" in logic.actions
    # And can a LATER ambiguity now be masked, because the alias is an
    # "exact" key by the time the second machine is built?
    logic.actions["fetchData"] = tagger("camel-different")
    try:
        create_machine(cfg("fetchData", "m2"), logic=logic)
        second = "built(no-ambiguity-raised)"
    except InvalidConfigError:
        second = "InvalidConfigError"
    return {
        "keys_after_first_build": keys_after_first,
        "alias_leaked_into_registry": leaked,
        "second_build": second,
    }


# --------------------------------------------------------------- G11
@_h.probe("G11", "guards and services alias too", {"guard": True, "service": True})
async def g11():
    seen = {"guard": False, "service": False}

    def check_limit(c, e):
        seen["guard"] = True
        return True

    async def fetch_quote(i, c, e):
        seen["service"] = True
        return 1

    config = {
        "id": "g11",
        "initial": "a",
        "context": {},
        "states": {
            "a": {"on": {"GO": {"target": "b", "cond": "checkLimit"}}},
            "b": {"invoke": {"id": "q", "src": "fetchQuote", "onDone": {"target": "c"}}},
            "c": {"type": "final"},
        },
    }
    m = create_machine(
        config,
        logic=MachineLogic(
            guards={"check_limit": check_limit}, services={"fetch_quote": fetch_quote}
        ),
    )
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.2)
    await i.stop()
    return seen


# =============================================================== H
_H_SCRIPT = textwrap.dedent(
    """
    import asyncio, warnings, sys
    from xstate_statemachine import Interpreter, MachineLogic, create_machine

    def boom(i, c, e, a):
        raise RuntimeError("boom")

    def cfg(mid, policy=None):
        c = {"id": mid, "initial": "a", "context": {},
             "states": {"a": {"on": {"GO": {"actions": ["boom"]}}}}}
        if policy:
            c["actionErrorPolicy"] = policy
        return c

    async def fire(mid, policy):
        m = create_machine(cfg(mid, policy), logic=MachineLogic(actions={"boom": boom}))
        i = Interpreter(m)
        await i.start()
        try:
            await i.send("GO")
        except Exception:
            pass
        await asyncio.sleep(0.1)
        try:
            await i.stop()
        except Exception:
            pass

    async def main():
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            for mid, pol in SEQ:
                await fire(mid, pol)
            names = [str(w.message)[:40] for w in rec
                     if w.category is DeprecationWarning
                     and "actionErrorPolicy" in str(w.message)]
        print(len(names))
        for n in names:
            print("  ", n)

    asyncio.run(main())
    """
)


def _h_run(seq: str) -> str:
    src = f"SEQ = {seq}\n" + _H_SCRIPT
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([PY, "-c", src], capture_output=True, text=True, env=env, timeout=120)
    return (r.stdout.strip().splitlines() or [r.stderr[-300:]])[0]


@_h.probe(
    "H1",
    "machine 1 sets the policy explicitly, machine 2 does not: does m2 warn?",
    "1",
)
def h1():
    return _h_run('[("m1", "rollback"), ("m2", None)]')


@_h.probe("H2", "two DEFAULT machines -> exactly one warning per process", "1")
def h2():
    return _h_run('[("m1", None), ("m2", None)]')


@_h.probe("H3", "a default machine whose actions never fail: warns at all?", "0")
def h3():
    src = textwrap.dedent(
        """
        import asyncio, warnings
        from xstate_statemachine import Interpreter, MachineLogic, create_machine
        def ok(i, c, e, a):
            pass
        async def main():
            with warnings.catch_warnings(record=True) as rec:
                warnings.simplefilter("always")
                m = create_machine(
                    {"id": "q", "initial": "a", "context": {},
                     "states": {"a": {"on": {"GO": {"actions": ["ok"]}}}}},
                    logic=MachineLogic(actions={"ok": ok}))
                i = Interpreter(m); await i.start()
                await i.send("GO"); await asyncio.sleep(0.1); await i.stop()
                n = [w for w in rec if w.category is DeprecationWarning
                     and "actionErrorPolicy" in str(w.message)]
            print(len(n))
        asyncio.run(main())
        """
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([PY, "-c", src], capture_output=True, text=True, env=env, timeout=120)
    return (r.stdout.strip().splitlines() or [r.stderr[-300:]])[0]


@_h.probe(
    "H4",
    "ALL machines set the policy explicitly -> no warning (no false alarm)",
    "0",
)
def h4():
    return _h_run('[("m1", "rollback"), ("m2", "fail"), ("m3", "continue")]')


if __name__ == "__main__":
    warnings.simplefilter("ignore", DeprecationWarning)
    _h.main("gh_aliases_deprecation")
