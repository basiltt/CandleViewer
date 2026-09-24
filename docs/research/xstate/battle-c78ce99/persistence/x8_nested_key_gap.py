# -*- coding: utf-8 -*-
"""X8 -- is the nested-key gap (X7/B) BEHAVIOURAL, not just cosmetic?

STANDALONE. Neutral cwd.

#216 fixed the TOP level only. A state node reads the same key names, so
this proves the SAME class of silent-default bug one level down: build a
machine whose state carries a one-character-typo'd `entry` / `invoke` /
`after` / `always` and show the behaviour is silently GONE, with
`strict_config=True` and `"strictConfig": true` both set -- i.e. the
caller who opted in to the strictest setting #216 offers still gets no
signal.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

KIND = os.environ.get("XS_SVC", "async")


def cap():
    log = logging.getLogger("xstate_statemachine")
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.WARNING)
    log.setLevel(logging.WARNING)
    log.addHandler(h)
    return log, h, buf


async def probe(label, good_key, bad_key, node, ctx_key, drive):
    log, h, buf = cap()
    results = {}
    try:
        for key, tag in ((good_key, "correct"), (bad_key, "typo")):
            spec = {
                "id": "nk",
                "strictConfig": True,
                "initial": "a",
                "context": {ctx_key: 0},
                "states": {
                    "a": {key: json.loads(json.dumps(node))},
                    "b": {"type": "final"},
                },
            }

            def mark(i, c, e, a):  # noqa: ANN001
                c[ctx_key] += 1

            async def sa(i, c, e):  # noqa: ANN001
                await asyncio.sleep(0)
                return 1

            def sd(i, c, e):  # noqa: ANN001
                return 1

            before = buf.getvalue()
            m = create_machine(
                spec,
                logic=MachineLogic(
                    actions={"mark": mark},
                    services={"s": sa if KIND == "async" else sd},
                ),
                strict_config=True,
            )
            warned = len(buf.getvalue()) > len(before)
            clock = SimulatedClock()
            i = Interpreter(m, clock=clock)
            await i.start()
            await asyncio.sleep(0.02)
            await drive(i, clock)
            results[tag] = (i.context[ctx_key], sorted(i.current_state_ids),
                            warned)
            if i.status == "running":
                await i.stop()
    finally:
        log.removeHandler(h)
    g, t = results["correct"], results["typo"]
    lost = g[0] != t[0] or g[1] != t[1]
    print(f"   {label:26s} correct={g[0]},{g[1]}  typo({bad_key})={t[0]},{t[1]}"
          f"  warned={t[2]}  -> BEHAVIOUR LOST SILENTLY="
          f"{'YES' if lost and not t[2] else 'no'}")


async def noop(i, clock):  # noqa: ANN001
    await asyncio.sleep(0.02)


async def tick(i, clock):  # noqa: ANN001
    await clock.increment(50)
    await asyncio.sleep(0.02)


async def main():
    print(f"X8 kind={KIND}  (strictConfig:true AND strict_config=True)")
    print("=== nested state-node key typos ===")
    await probe("entry -> Entry", "entry", "Entry", ["mark"], "n", noop)
    await probe("after -> After", "after", "After",
                {"10": {"target": "b", "actions": "mark"}}, "n", tick)
    await probe("always -> Always", "always", "Always",
                [{"target": "b", "actions": "mark"}], "n", noop)
    await probe("exit -> Exit", "exit", "Exit", ["mark"], "n", noop)
    await probe("invoke -> Invoke", "invoke", "Invoke",
                {"id": "k", "src": "s",
                 "onDone": {"target": "b", "actions": "mark"}}, "n", noop)
    print("\n   NOTE: #216 / KNOWN_MACHINE_KEYS is applied to the TOP-LEVEL "
          "config only (validation.validate_top_level_keys is called once\n"
          "   from factory.create_machine); `states.<id>` nodes are parsed "
          "by StateNode.__init__ with plain .get() lookups and no key check.")


asyncio.run(main())
