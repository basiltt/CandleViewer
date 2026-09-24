"""#227 + #230 property: a strict refusal on the restored `scheduled_sends`
lane leaves a CONSISTENT machine, and `from_snapshot(plugins=)` sees the
refusal exactly once.

Each case: build a strict machine, arm 1-3 real deadlines, snapshot, then
forge 0-3 EXTRA `scheduled_sends` records with undeclared event types (and
some with declared types but a schema-violating payload).  Restore with a
counting plugin, start, and assert:
  * every DECLARED record still fires exactly once
  * every UNDECLARED record fires zero times
  * on_invalid_event fires exactly once per refused record
  * last_error is set iff at least one refusal happened
  * the machine is running and reaches a settled state
"""
import asyncio, json, os, random
from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,
                                 create_machine)

DECLARED = ["T0", "T1", "T2"]

def spec(schema):
    st = {"a": {"on": {t: {"actions": ["fire"]} for t in DECLARED}}}
    cfg = {"id": "sp", "initial": "a", "context": {"fired": []},
           "strict": True, "states": st}
    return cfg


def _require_int_n(payload):
    """`event_schemas` values are CALLABLES (or objects with `.validate`),
    not JSON-Schema dicts -- a dict is invoked and raises TypeError, which
    the library reports as a payload refusal for every event."""
    if not isinstance(payload.get("n"), int):
        raise ValueError("n must be an int")


SCHEMAS = {t: _require_int_n for t in DECLARED}

def build(kind, schema):
    if kind == "def":
        def fire(i, c, e, a):
            c["fired"].append(e.type)
    else:
        async def fire(i, c, e, a):
            c["fired"].append(e.type)
    # schemas are registered through `create_machine(event_schemas=)`,
    # NOT through an "events" key in the config dict.
    return create_machine(json.loads(json.dumps(spec(schema))),
                          logic=MachineLogic(actions={"fire": fire}),
                          event_schemas=SCHEMAS if schema else None)

class Counter(PluginBase):
    def __init__(self):
        self.invalid = []
        self.inits = 0
    def on_interpreter_start(self, interpreter):
        self.inits += 1
    def on_invalid_event(self, interpreter, error, event=None):
        self.invalid.append(getattr(event, "type", str(event)))

async def one(rnd, kind):
    schema = rnd.random() < 0.4
    good = [rnd.choice(DECLARED) for _ in range(rnd.randint(1, 3))]
    bad_types = [f"NOPE{n}" for n in range(rnd.randint(0, 3))]
    bad_payload = ([rnd.choice(DECLARED)] if (schema and rnd.random() < 0.5)
                   else [])
    blob = {"version": 3, "status": "running",
            "state_ids": ["sp.a"], "context": {"fired": []},
            "machine_hash": None}
    # take a real snapshot to get the true envelope shape
    i = Interpreter(build(kind, schema))
    await i.start()
    b = i.get_persisted_snapshot()
    blob = json.loads(b) if isinstance(b, str) else b
    await i.stop()
    recs = []
    for n, t in enumerate(good):
        recs.append({"type": t, "payload": {"n": 1}, "remaining_ms": 25.0,
                     "send_id": f"g{n}"})
    for n, t in enumerate(bad_types):
        recs.append({"type": t, "payload": {"n": 1}, "remaining_ms": 25.0,
                     "send_id": f"b{n}"})
    for n, t in enumerate(bad_payload):
        recs.append({"type": t, "payload": {"n": "not-an-int"},
                     "remaining_ms": 25.0, "send_id": f"p{n}"})
    blob["scheduled_sends"] = recs
    blob["context"] = {"fired": []}
    pl = Counter()
    k = Interpreter.from_snapshot(json.dumps(blob), build(kind, schema),
                                  verify_machine_hash=False, plugins=[pl])
    await k.start()
    # `last_error` is a PER-STEP read (documented): the refusals happen
    # inside start(), and the first good deadline that lands clears it.
    # Read it in the correct window.
    err_at_start = k.last_error
    await asyncio.sleep(0.25)
    fired = list(k.context["fired"])
    status = k.status
    await k.stop()
    n_refused = len(bad_types) + len(bad_payload)
    problems = []
    from collections import Counter as C
    want = C(good)
    if C(fired) != want:
        problems.append(f"fired {sorted(fired)} want {sorted(good)}")
    if any(f.startswith("NOPE") for f in fired):
        problems.append("undeclared type was admitted")
    if len(pl.invalid) != n_refused:
        problems.append(f"on_invalid_event {len(pl.invalid)} != {n_refused}")
    if n_refused and err_at_start is None:
        problems.append("refusal did not reach last_error at start()")
    if not n_refused and err_at_start is not None:
        problems.append(f"spurious last_error {err_at_start!r}")
    if status != "running":
        problems.append(f"status {status}")
    return problems

async def main():
    kind = os.environ.get("XS_SVC", "async")
    N = int(os.environ.get("N", "320"))
    rnd = random.Random(int(os.environ.get("SEED", "99")))
    fails = []
    for n in range(N):
        p = await one(rnd, kind)
        if p:
            fails.append({"case": n, "problems": p})
        if len(fails) > 5:
            break
    print(json.dumps({"kind": kind, "N": N, "n_fail": len(fails),
                      "fails": fails[:5],
                      "VERDICT": "PASS" if not fails else "FAIL"}, indent=1))

asyncio.run(main())
