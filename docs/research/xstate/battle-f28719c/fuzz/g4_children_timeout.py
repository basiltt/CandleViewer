"""G4 -- NEW ATTACK: children_timeout is per child, not N*D (#194 / #181).

50 INVOKED CHILD MACHINES whose entry action takes D_entry, parent started
with children_timeout=T.  The round-8 claim: the bound is per child, so
N coroutine children settle in ~D_entry, and the WARNING fires whenever the
allowance was exceeded -- INCLUDING the single-threaded `def` case a bound
cannot pre-empt.

Measured: start() wall time, and whether a WARNING was emitted.
Both child-entry kinds (`def` / `async def`).

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, copy, logging, time, warnings

warnings.simplefilter("ignore")
from xstate_statemachine import Interpreter, MachineLogic, create_machine

N = 50
D_ENTRY = 0.10
T = 0.20

CHILD = {
    "id": "kid",
    "initial": "w",
    "states": {"w": {"entry": ["slow"], "on": {"X": "d"}}, "d": {"type": "final"}},
}


def parent_cfg(n):
    states = {}
    for k in range(n):
        states[f"r{k}"] = {
            "initial": "s",
            "states": {"s": {"invoke": {"id": f"c{k}", "src": "kid"}}},
        }
    return {"id": "p", "type": "parallel", "states": states}


class Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, r):
        if r.levelno >= logging.WARNING:
            self.msgs.append(r.getMessage())


async def run(kind):
    if kind == "def":

        def slow(i, c, e, a=None):
            time.sleep(D_ENTRY)

    else:

        async def slow(i, c, e, a=None):  # noqa: F811
            await asyncio.sleep(D_ENTRY)

    logging.disable(logging.NOTSET)
    lg = logging.getLogger("xstate_statemachine")
    lg.setLevel(logging.WARNING)
    cap = Cap()
    lg.addHandler(cap)

    child_logic = MachineLogic(actions={"slow": slow})
    child_machine = create_machine(copy.deepcopy(CHILD), logic=child_logic)
    logic = MachineLogic(services={"kid": child_machine}, actions={"slow": slow})
    m = create_machine(copy.deepcopy(parent_cfg(N)), logic=logic)

    t0 = time.perf_counter()
    it = Interpreter(m)
    await it.start(children_timeout=T)
    el = time.perf_counter() - t0
    await it.stop()
    lg.removeHandler(cap)

    relevant = [x for x in cap.msgs if "children_timeout" in x]
    per_child = el < (D_ENTRY * 3 + T)
    aggregate = el >= (N * D_ENTRY * 0.7)
    shape = "per-child(~D)" if per_child else ("AGGREGATE(~N*D)" if aggregate else "between")
    print(
        f"  {kind:10s} N={N} D_entry={D_ENTRY}s T={T}s -> start()={el:.2f}s "
        f"[{shape}]  WARNINGs={len(relevant)} "
        f"=> bound={'PASS' if per_child else 'FAIL'} "
        f"warn={'PASS' if relevant else 'FAIL(silent overrun)'}"
    )
    if relevant:
        print(f"      {relevant[0][:150]}")
    logging.disable(logging.CRITICAL)


async def main():
    print("G4 -- children_timeout: per child, or N*D? (50 invoked children)")
    for k in ("async def", "def"):
        await run(k)


asyncio.run(main())
