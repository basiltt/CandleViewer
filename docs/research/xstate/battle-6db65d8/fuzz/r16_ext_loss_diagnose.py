"""R16 -- diagnose r15's EXT_LOST: is the external priority event DROPPED, or
merely UNHANDLED in the state the machine happened to be in?

r15's soak reported EXT_LOST=11026 with ext_drop_hook=0. The soak's charts put
the `EXT` handler on some states but not on deep nested leaves (`b2` inside
`always_into_invoke`), so an EXT that lands while the machine sits there is
correctly unhandled, not lost.

Method: build ONE shape per kind where EXT is handled in EVERY state (root
handler on a flat chart) and re-measure. If loss goes to 0, r15's number is a
harness artefact; if it persists, it is the D8-fuzz-2 shed.
"""
import asyncio, logging, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)


class Drops(PluginBase):
    def __init__(self):
        self.d = {}
        self.unhandled = 0

    def on_event_dropped(self, interp, event, reason=None, **kw):
        k = f"{reason}:{getattr(event, 'type', event)}"
        self.d[k] = self.d.get(k, 0) + 1


async def async_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def plain_svc(i, c, e):
    return {"ok": 1}


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


def bump(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


def chart(kind, i=0):
    """ROOT-level EXT handler => handled in EVERY configuration."""
    base = {
        "id": f"m{i}",
        "context": {"n": 0, "ext": 0},
        "maxIterations": 50,
        # root handler: reachable from every descendant
        "on": {"EXT": {"actions": ["extbump"]}},
    }
    if kind == "rollback_ondone":
        base |= {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": "b"}},
                "b": {"invoke": {"id": "s", "src": "svc", "onDone": {"target": "c"}}},
                "c": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}},
            },
        }
    elif kind == "always_into_invoke":
        base |= {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": "b"}},
                "b": {
                    "always": {"target": "b2", "guard": "g"},
                    "initial": "b2",
                    "states": {
                        "b2": {
                            "invoke": {
                                "id": "s",
                                "src": "svc",
                                "onDone": {"target": f"#m{i}.a"},
                            }
                        }
                    },
                },
            },
        }
    else:  # plain
        base |= {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
                "b": {"on": {"GO": "a"}},
            },
        }
    return base


async def trial(kind, async_svc, n=4000):
    dr = Drops()
    L = MachineLogic(
        services={"svc": async_svc and globals()["async_svc"] or plain_svc},
        actions={"bump": bump, "extbump": extbump},
        guards={"g": lambda c, e: True},
    )
    it = Interpreter(create_machine(chart(kind), logic=L))
    it.use(dr)
    await asyncio.wait_for(it.start(), 10)
    sent = 0
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        sent += 1
        await asyncio.sleep(0)
    await asyncio.sleep(0.5)
    applied = (it.context or {}).get("ext", 0)
    shed = sum(v for k, v in dr.d.items() if k.endswith(":EXT"))
    await it.stop()
    lost = sent - applied
    k = "asyncdef" if async_svc else "plaindef"
    print(
        f"  {kind:<20} svc={k}: EXT sent={sent} applied={applied} "
        f"LOST={lost} ({100*lost/max(sent,1):.2f}%) shed_hook={shed} drops={dr.d} "
        f"=> {'PASS' if lost == 0 else 'LOSS'}"
    )


async def main():
    print(
        "EXT handled at the ROOT (every configuration) -- any loss is a real drop.\n"
    )
    for kind in ("plain", "rollback_ondone", "always_into_invoke"):
        for a in (False, True):
            await trial(kind, a)


asyncio.run(main())
