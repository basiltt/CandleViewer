"""#232: a `def` action that drops its `wait=True` receipt gets a
RuntimeWarning.  Where does it surface, what does it say, and what happens
under `-W error` INSIDE asyncio?

Modes (env MODE):
  drop     -- def action calls send(wait=True) and drops the result
  handout  -- def action hands the receipt to ensure_future  (must be SILENT)
  result   -- def action calls .result() on it               (must be SILENT)
  cb       -- def action attaches add_done_callback          (must be SILENT)
"""
import asyncio, gc, json, os, sys, warnings
from xstate_statemachine import Interpreter, MachineLogic, create_machine

MODE = os.environ.get("MODE", "drop")

CFG = {"id": "rw", "initial": "a", "context": {"log": []},
       "states": {"a": {"entry": ["probe"],
                        "on": {"B": {"actions": ["note"]}}}}}

def build():
    def note(i, c, e, a):
        c["log"].append(e.type)

    def probe(i, c, e, a):              # SYNCHRONOUS action -- the #232 case
        r = i.send("B", wait=True)
        if MODE == "handout":
            asyncio.ensure_future(r)
        elif MODE == "result":
            try:
                r.result()
            except Exception:
                pass
        elif MODE == "cb":
            try:
                r.add_done_callback(lambda f: None)
            except Exception:
                pass
        # MODE == "drop": the receipt is dropped on the floor

    return create_machine(CFG, logic=MachineLogic(actions={"probe": probe,
                                                           "note": note}))

async def main():
    caught = []
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        i = Interpreter(build())
        await i.start()
        await asyncio.sleep(0.2)
        log = list(i.context["log"])
        await i.stop()
        del i
        for _ in range(3):
            gc.collect()
            await asyncio.sleep(0.02)
        caught = [{"category": x.category.__name__, "msg": str(x.message),
                   "file": os.path.basename(str(x.filename)),
                   "line": x.lineno} for x in w]
    rw = [c for c in caught if c["category"] == "RuntimeWarning"]
    print(json.dumps({"mode": MODE, "log": log, "n_warnings": len(caught),
                      "runtime_warnings": rw,
                      "other": [c for c in caught
                                if c["category"] != "RuntimeWarning"]},
                     indent=1))

asyncio.run(main())
