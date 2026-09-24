import logging, threading, copy, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter
from gen_config import make_logic

POLICY = {"actionErrorPolicy":"rollback","onUnhandled":"error","guardErrorPolicy":"raise",
          "strictTargets":True,"strict":True,"spawnBlockingTimeout":5000}

NESTED = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}

SINGLE = {"id":"m","initial":"a","states":{"a":{
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}}}}}

SINGLE_COMPOUND = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{}}}}}

INNER_ONLY = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}

def probe(name, cfg, policy=False, maxit=None, secs=5):
    cfg = copy.deepcopy(cfg)
    if policy: cfg.update(POLICY)
    if maxit: cfg["maxIterations"] = maxit
    out={}
    try:
        it = SyncInterpreter(create_machine(cfg, logic=make_logic(sync=True)))
    except BaseException as e:
        print(f"  {name:<28} build-error {type(e).__name__}: {str(e)[:90]}"); return
    def run():
        try: out["ok"]=sorted(it.current_state_ids) if it.start() or True else None
        except BaseException as e: out["exc"]=f"{type(e).__name__}: {str(e)[:100]}"
    th=threading.Thread(target=run,daemon=True); th.start(); th.join(secs)
    print(f"  {name:<28} policy={policy} maxit={maxit!r:>6} alive={th.is_alive()} {out}")

print("baseline shapes:")
probe("nested (claimed)", NESTED)
probe("single atomic self-onDone", SINGLE)
probe("single compound self-onDone", SINGLE_COMPOUND)
probe("inner-only onDone->ancestor", INNER_ONLY)
print("with mandatory policy block:")
probe("nested +policy", NESTED, policy=True)
probe("single atomic +policy", SINGLE, policy=True)
probe("nested +policy +maxit50", NESTED, policy=True, maxit=50)
