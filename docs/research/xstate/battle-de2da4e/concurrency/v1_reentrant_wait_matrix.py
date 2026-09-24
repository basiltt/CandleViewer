"""v1 (@de2da4e) -- STANDALONE. #219 ReentrantWaitError semantics matrix.

Cells (both action kinds; async engine unless noted):
  A self_await          action awaits i.send(..., wait=True) on ITSELF
  B sync_self           SyncInterpreter parity -- must raise too
  C ensure_future       receipt handed out via ensure_future, awaited AFTER
                        the action returned -- must RESOLVE, not raise
  D child_to_parent     child action awaits parent.send(wait=True)
  E parent_to_child     parent action awaits child.send(wait=True)
  F after_handler       action reached from an `after`-fired event awaits
                        its own send(wait=True)
  G entry_descent       action on the INITIAL descent (start()) -- #215 path
  H external_wait       a NON-action caller awaits send(wait=True) -- control,
                        must resolve normally
  I concurrent_100      100 concurrent actions each using the ensure_future
                        pattern -- all receipts resolve, no hang, no leak

Watchdog: every cell is wrapped in asyncio.wait_for(20s). A HANG is a
defect (that is what #219 exists to prevent).

Run: python v1_reentrant_wait_matrix.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import ReentrantWaitError

WATCHDOG = 20.0
ROWS: List[Dict[str, Any]] = []
FAILS: List[str] = []


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {
        "probe": name,
        "py": ".".join(map(str, sys.version_info[:3])),
        **data,
    }
    txt = json.dumps(data, indent=2, default=str)
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".json"),
        "w",
    ) as fh:
        fh.write(txt)
    print(txt)


def cfg(mid: str = "v1") -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "idle",
        "context": {"n": 0},
        "states": {
            "idle": {"entry": ["boom"], "on": {"GO": "done", "PONG": "done"}},
            "done": {"entry": ["tick"]},
        },
    }


def cfg_after(mid: str = "v1f") -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "wait",
        "context": {"n": 0},
        "states": {
            "wait": {"after": {"10": "hot"}},
            "hot": {"entry": ["boom"], "on": {"GO": "done"}},
            "done": {"entry": ["tick"]},
        },
    }


def cfg_plain(mid: str) -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "idle",
        "context": {"n": 0},
        "states": {
            "idle": {"on": {"GO": "done"}},
            "done": {"entry": ["tick"]},
        },
    }


# 🧭 HARNESS NOTE (not a library property). On the ASYNC engine a plain
#    `def` action cannot `await` anything -- there is no language form for
#    it. So every cell whose attack IS "await a receipt in-step" has no
#    `def` counterpart on the async engine; those cells are recorded
#    "N/A_sync_action_cannot_await" and the `def` side of that attack is
#    carried by cell B, which runs the SyncInterpreter (where the same
#    shape is a blocking call and #219 must still refuse it). Cells C and I
#    (`ensure_future`, which needs no await at the issue site) DO have a
#    real `def` form and are run on both kinds.
NEEDS_AWAIT = "N/A_sync_action_cannot_await"


def mk_logic(kind: str, boom, tick, sync_boom=None):
    """Wrap into `def` or `async def` actions.

    `boom` is a coroutine function used for the `async def` kind.
    `sync_boom` (optional) is the plain-callable form for the `def` kind;
    when absent the `def` kind is not expressible (see NEEDS_AWAIT).
    """
    if kind == "def":
        fn = sync_boom or (lambda *a: None)

        def _boom(i, ctx, e, ad):  # noqa: ANN001
            fn(i, ctx, e, ad)

        def _tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"boom": _boom, "tick": _tick})

    async def _aboom(i, ctx, e, ad):  # noqa: ANN001
        r = boom(i, ctx, e, ad)
        if asyncio.iscoroutine(r) or isinstance(r, asyncio.Future):
            await r

    async def _atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"boom": _aboom, "tick": _atick})


def record(cell: str, kind: str, **kw: Any) -> None:
    ROWS.append({"cell": cell, "kind": kind, **kw})


async def cell_A_self_await(kind: str) -> None:
    """An `async def` action awaits send(wait=True) on itself."""
    if kind == "def":
        record("A_self_await", kind, seen=NEEDS_AWAIT, ok=True)
        return
    seen: List[str] = []

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        try:
            await i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")
        except Exception as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)

    m = create_machine(cfg("v1a"), logic=mk_logic(kind, boom, None))
    i = Interpreter(m)
    try:
        await asyncio.wait_for(i.start(), WATCHDOG)
        hung = False
    except asyncio.TimeoutError:
        hung = True
    await i.stop()
    ok = (seen == ["ReentrantWaitError"]) and not hung
    record("A_self_await", kind, seen=seen, hung=hung, ok=ok)
    if not ok:
        FAILS.append(f"A_self_await/{kind}: seen={seen} hung={hung}")


def cell_B_sync_self(kind: str) -> None:
    """Sync engine parity: the same shape must raise, not hang."""
    seen: List[str] = []

    def boom(i, ctx, e, ad):  # noqa: ANN001
        try:
            i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")
        except Exception as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)

    def _boom(i, ctx, e, ad):  # noqa: ANN001
        boom(i, ctx, e, ad)

    logic = MachineLogic(
        actions={
            "boom": _boom,
            "tick": lambda i, c, e, a: c.__setitem__("n", c.get("n", 0) + 1),
        }
    )
    m = create_machine(cfg("v1b"), logic=logic)
    i = SyncInterpreter(m)
    box: List[Any] = []
    t = threading.Thread(target=lambda: box.append(i.start()), daemon=True)
    t.start()
    t.join(WATCHDOG)
    hung = t.is_alive()
    ok = (seen == ["ReentrantWaitError"]) and not hung
    record("B_sync_self", "def", seen=seen, hung=hung, ok=ok)
    if not ok:
        FAILS.append(f"B_sync_self: seen={seen} hung={hung}")


async def cell_C_ensure_future(kind: str) -> None:
    """#219 says the receipt may still be HANDED OUT and awaited later."""
    holder: Dict[str, Any] = {}
    seen: List[str] = []

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        try:
            holder["fut"] = asyncio.ensure_future(i.send("GO", wait=True))
            seen.append("HANDED_OUT")
        except Exception as exc:  # noqa: BLE001
            seen.append("ISSUE:" + type(exc).__name__)

    def sboom(i, ctx, e, ad):  # noqa: ANN001  -- `def` form, no await
        try:
            holder["fut"] = asyncio.ensure_future(i.send("GO", wait=True))
            seen.append("HANDED_OUT")
        except Exception as exc:  # noqa: BLE001
            seen.append("ISSUE:" + type(exc).__name__)

    m = create_machine(cfg("v1c"), logic=mk_logic(kind, boom, None, sboom))
    i = Interpreter(m)
    hung = False
    outcome = "n/a"
    try:
        await asyncio.wait_for(i.start(), WATCHDOG)
        fut = holder.get("fut")
        if fut is None:
            outcome = "NO_RECEIPT"
        else:
            try:
                await asyncio.wait_for(fut, 5.0)
                outcome = "RESOLVED"
            except asyncio.TimeoutError:
                outcome = "TIMEOUT"
            except ReentrantWaitError:
                outcome = "ReentrantWaitError"
            except Exception as exc:  # noqa: BLE001
                outcome = type(exc).__name__
    except asyncio.TimeoutError:
        hung = True
    n = i.context.get("n")
    await i.stop()
    ok = (outcome == "RESOLVED") and not hung and seen == ["HANDED_OUT"]
    record("C_ensure_future", kind, seen=seen, outcome=outcome, n=n,
           hung=hung, ok=ok)
    if not ok:
        FAILS.append(f"C_ensure_future/{kind}: {seen} {outcome} hung={hung}")


async def _spawn_pair(kind: str, mid_p: str, mid_c: str):
    """Two independent interpreters; 'child'/'parent' by role only."""
    seen: List[str] = []
    holder: Dict[str, Any] = {}

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        other = holder.get("other")
        if other is None:
            seen.append("NO_PEER")
            return
        try:
            await asyncio.wait_for(other.send("GO", wait=True), 5.0)
            seen.append("RESOLVED")
        except asyncio.TimeoutError:
            seen.append("TIMEOUT")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")
        except Exception as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)

    peer = Interpreter(create_machine(cfg_plain(mid_c),
                                      logic=mk_logic(kind, boom, None)))
    await peer.start()
    holder["other"] = peer
    actor = Interpreter(create_machine(cfg(mid_p),
                                       logic=mk_logic(kind, boom, None)))
    return actor, peer, seen


async def cell_DE_cross_actor(kind: str, label: str) -> None:
    """An action on interpreter X awaits wait=True on a DIFFERENT
    interpreter Y. Must RESOLVE (the guard is per-interpreter)."""
    if kind == "def":
        record(label, kind, seen=NEEDS_AWAIT, ok=True)
        return
    actor, peer, seen = await _spawn_pair(kind, label + "p", label + "c")
    hung = False
    try:
        await asyncio.wait_for(actor.start(), WATCHDOG)
    except asyncio.TimeoutError:
        hung = True
    peer_state = sorted(peer.current_state_ids)
    await actor.stop()
    await peer.stop()
    ok = seen == ["RESOLVED"] and not hung
    record(label, kind, seen=seen, peer_state=peer_state, hung=hung, ok=ok)
    if not ok:
        FAILS.append(f"{label}/{kind}: seen={seen} hung={hung}")


async def cell_F_after_handler(kind: str) -> None:
    """The action is reached from an `after`-fired event, i.e. OUTSIDE the
    initial descent. The guard must still refuse."""
    if kind == "def":
        record("F_after_handler", kind, seen=NEEDS_AWAIT, ok=True)
        return
    seen: List[str] = []

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        try:
            await i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")
        except Exception as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)

    m = create_machine(cfg_after("v1f"),
                       logic=mk_logic(kind, boom, None))
    i = Interpreter(m)
    hung = False
    try:
        await asyncio.wait_for(i.start(), WATCHDOG)
        for _ in range(200):
            if seen:
                break
            await asyncio.sleep(0.02)
    except asyncio.TimeoutError:
        hung = True
    states = sorted(i.current_state_ids)
    await i.stop()
    ok = seen == ["ReentrantWaitError"] and not hung
    record("F_after_handler", kind, seen=seen, states=states, hung=hung, ok=ok)
    if not ok:
        FAILS.append(f"F_after_handler/{kind}: seen={seen} hung={hung}")


async def cell_H_external_wait(kind: str) -> None:
    """Control: a NON-action caller awaits wait=True. Must resolve."""
    m = create_machine(cfg_plain("v1h"),
                       logic=mk_logic(kind, lambda *a: None, None))
    i = Interpreter(m)
    await i.start()
    outcome = "n/a"
    try:
        await asyncio.wait_for(i.send("GO", wait=True), 5.0)
        outcome = "RESOLVED"
    except asyncio.TimeoutError:
        outcome = "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        outcome = type(exc).__name__
    n = i.context.get("n")
    await i.stop()
    ok = outcome == "RESOLVED" and n == 1
    record("H_external_wait", kind, outcome=outcome, n=n, ok=ok)
    if not ok:
        FAILS.append(f"H_external_wait/{kind}: {outcome} n={n}")


async def cell_I_concurrent_100(kind: str) -> None:
    """100 interpreters, each action using the ensure_future pattern.
    Every receipt must resolve; nothing may hang."""
    N = 100
    holders: List[Dict[str, Any]] = []
    issues: List[str] = []

    async def make(idx: int):
        holder: Dict[str, Any] = {}
        holders.append(holder)

        async def boom(i, ctx, e, ad):  # noqa: ANN001
            try:
                holder["fut"] = asyncio.ensure_future(i.send("GO", wait=True))
            except Exception as exc:  # noqa: BLE001
                issues.append(type(exc).__name__)

        def sboom(i, ctx, e, ad):  # noqa: ANN001  -- `def` form
            try:
                holder["fut"] = asyncio.ensure_future(i.send("GO", wait=True))
            except Exception as exc:  # noqa: BLE001
                issues.append(type(exc).__name__)

        m = create_machine(f"v1i{idx}" and cfg(f"v1i{idx}"),
                           logic=mk_logic(kind, boom, None, sboom))
        i = Interpreter(m)
        await i.start()
        return i

    hung = False
    resolved = 0
    others: List[str] = []
    interps: List[Any] = []
    try:
        interps = await asyncio.wait_for(
            asyncio.gather(*(make(k) for k in range(N))), WATCHDOG
        )
        futs = [h["fut"] for h in holders if "fut" in h]
        done = await asyncio.wait_for(
            asyncio.gather(*futs, return_exceptions=True), 10.0
        )
        for r in done:
            if isinstance(r, BaseException):
                others.append(type(r).__name__)
            else:
                resolved += 1
    except asyncio.TimeoutError:
        hung = True
    ns = sorted({i.context.get("n") for i in interps})
    for i in interps:
        await i.stop()
    ok = resolved == N and not hung and not issues and not others
    record("I_concurrent_100", kind, resolved=resolved, issues=issues,
           other_exceptions=sorted(set(others)), n_values=ns, hung=hung, ok=ok)
    if not ok:
        FAILS.append(
            f"I_concurrent_100/{kind}: resolved={resolved} "
            f"issues={issues} others={set(others)} hung={hung}"
        )


async def main() -> int:
    for kind in ("def", "async def"):
        await cell_A_self_await(kind)
        await cell_C_ensure_future(kind)
        await cell_DE_cross_actor(kind, "D_child_to_parent")
        await cell_DE_cross_actor(kind, "E_parent_to_child")
        await cell_F_after_handler(kind)
        await cell_H_external_wait(kind)
        await cell_I_concurrent_100(kind)
    cell_B_sync_self("def")
    emit(
        "v1_reentrant_wait_matrix",
        {
            "watchdog_s": WATCHDOG,
            "rows": ROWS,
            "failures": FAILS,
            "verdict": "DEFECT" if FAILS else "CLEAN",
        },
    )
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
