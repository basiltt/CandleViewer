# -*- coding: utf-8 -*-
"""STANDALONE (#207): a chain cut that strands an invocation is observable.

Same B1-shaped rollback + invoke.onDone storm as r1, but here we assert the
round-9 observability surface: RunawayChainError.stranded, the
PluginBase.on_invocation_stranded hook, has_dormant_invocations and
pending_invocations().  CV=async|def selects the service kind.
stdlib + xstate_statemachine only; every helper inlined.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

STYLE = os.environ.get("CV", "async")
MAXIT = int(os.environ.get("MAXIT", "10"))

CFG = {
    "id": "order", "initial": "submitting",
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "maxIterations": MAXIT, "context": {},
    "states": {
        "submitting": {
            "invoke": {"id": "po", "src": "place_order",
                       "onDone": {"target": "#order.submitted"},
                       "onError": {"target": "#order.unknown"}},
            "on": {"ABORT": {"target": "#order.unknown"}}},
        "submitted": {"entry": ["adopt_ack"]},
        "unknown": {"type": "final"},
    },
}

CALLS = []


class Hooks(PluginBase):
    def __init__(self):
        self.stranded = []
        self.dropped = []
        self.errors = []

    def on_invocation_stranded(self, i, state_id, invoke_id, error):
        self.stranded.append((state_id, invoke_id, type(error).__name__))

    def on_event_dropped(self, i, e, reason):
        self.dropped.append((getattr(e, "type", "?"), reason))

    def on_error(self, i, e):
        self.errors.append(type(e).__name__)


def adopt_ack(i, c, e, a):
    raise RuntimeError("boom:adopt_ack")


def svc_def(i, c, e):
    CALLS.append(1)
    return {"ok": True}


async def svc_async(i, c, e):
    CALLS.append(1)
    return {"ok": True}


async def main():
    logic = MachineLogic(
        actions={"adopt_ack": adopt_ack},
        services={"place_order": svc_def if STYLE == "def" else svc_async},
        strict=True)
    m = create_machine(CFG, logic=logic, strict_targets=True)
    i = Interpreter(m, clock=SimulatedClock())
    p = Hooks()
    i.use(p)
    await i.start()
    # Wait for convergence rather than sampling at a fixed instant (#210).
    prev, stable = -1, 0
    for _ in range(300):
        await asyncio.sleep(0.02)
        if len(CALLS) == prev:
            stable += 1
            if stable >= 25:
                break
        else:
            stable = 0
        prev = len(CALLS)

    le = getattr(i, "last_error", None)
    strandattr = getattr(le, "stranded", "<no-attr>")
    dormant = getattr(i, "has_dormant_invocations", "<no-attr>")
    try:
        pend = [(x.state_id, x.invoke_id) for x in i.pending_invocations()]
    except Exception as e:
        pend = "raised:%r" % (e,)
    print("style=%s maxIterations=%d arms=%d states=%s" %
          (STYLE, MAXIT, len(CALLS), sorted(i.current_state_ids)))
    print("  last_error=%s stranded=%s" % (type(le).__name__, strandattr))
    print("  hook_fired=%s dormant=%s pending=%s" % (p.stranded, dormant, pend))
    print("  on_error=%s dropped_reasons=%s i.error=%r status=%s" %
          (p.errors, sorted({r for _, r in p.dropped}), i.error, i.status))

    # Responsiveness after the cut: ABORT must still be accepted.
    await i.send("ABORT")
    await asyncio.sleep(0.2)
    after = sorted(i.current_state_ids)
    print("  after_ABORT=%s" % (after,))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        print("stop:", repr(e))

    bad = []
    if not p.stranded:
        bad.append("on_invocation_stranded never fired")
    if strandattr in ("<no-attr>", None, [], ()):
        bad.append("RunawayChainError.stranded empty/absent")
    if dormant is not True:
        bad.append("has_dormant_invocations=%r" % (dormant,))
    if after != ["order.unknown"]:
        bad.append("unresponsive after cut: %s" % (after,))
    print("  VERDICT=%s" % ("OK" if not bad else "UNSAFE:" + "; ".join(bad)))
    sys.exit(1 if bad else 0)


asyncio.run(main())
