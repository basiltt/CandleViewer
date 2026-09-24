"""Adversarial: shared MachineNode (A8 mandate) vs mutation of transition.target_str; debug ergonomics."""
import asyncio, logging, json, io, contextlib
from xstate_statemachine import create_machine, Interpreter, MachineLogic

M={"id":"o","type":"parallel","context":{"n":0},
 "states":{
  "life":{"initial":"a","states":{
     "a":{"on":{"E":{"target":"#o.life.b"}}},
     "b":{"on":{"E":{"target":"#o.life.a"}}}}},
  "prot":{"initial":"p","states":{"p":{"on":{"F":{"target":"#o.prot.q"}}},"q":{}}}}}

async def main():
    logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
    m=create_machine(M,logic=MachineLogic())
    # A8 mandates sharing the node across 500 interpreters. Confirm no cross-talk.
    xs=[await Interpreter(m).start() for _ in range(200)]
    await asyncio.gather(*[x.send("E") for x in xs[:100]])
    await asyncio.sleep(0.2)
    moved=sum(1 for x in xs[:100] if "o.life.b" in x.current_state_ids)
    still=sum(1 for x in xs[100:] if "o.life.a" in x.current_state_ids)
    print(f"[shared_node] 200 interpreters on one MachineNode: 100 sent E -> {moved}/100 moved; "
          f"{still}/100 untouched -> {'no cross-talk' if moved==100 and still==100 else 'CROSS-TALK'}")
    # debug ergonomics: what does an operator actually see?
    x=xs[0]
    print(f"\n[debug_ergonomics]")
    print(f"   current_state_ids = {sorted(x.current_state_ids)}   <- flat set, no hierarchy (LC-22)")
    print(f"   matches('life')   = {x.matches('life')}")
    print(f"   matches('life.b') = {x.matches('life.b')}")
    snap=json.loads(x.get_snapshot())
    print(f"   snapshot keys     = {sorted(snap.keys())}")
    print(f"   snapshot has NO: schema version, machine hash, timestamp, event history, pending queue")
    # what happens on an unknown event / typo'd event name
    buf=io.StringIO()
    h=logging.StreamHandler(buf); lg=logging.getLogger("xstate_statemachine")
    lg.setLevel(logging.DEBUG); lg.addHandler(h)
    await x.send("EE")  # typo
    await asyncio.sleep(0.1)
    lg.removeHandler(h); lg.setLevel(logging.CRITICAL)
    out=buf.getvalue()
    print(f"\n[typo_event] sent 'EE' (typo for 'E'): state={sorted(x.current_state_ids)} status={x.status}")
    print(f"   log evidence lines mentioning 'EE': {sum(1 for l in out.splitlines() if 'EE' in l)}")
    print(f"   -> a typo'd event name is indistinguishable from a legitimately-unhandled event.")
    for y in xs: await y.stop()
asyncio.run(main())
