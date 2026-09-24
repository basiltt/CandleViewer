"""G-18: (a) send_threadsafe honours the forged `system` flag the same way
(the #78 strict guard is bypassed too); (b) `_cancel_state_tasks` detaches
the completion listener by comparing `fn.__name__ == "_on_child_terminal"`
-- and the SPAWN path (interpreter.py:1548) registers a DIFFERENT closure
with the SAME name, so a spawned child of the same parent would be
mis-detached if it ever landed in `_invoked_children`."""
import asyncio, threading
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

STRICT = {"id": "t", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}

async def main():
    it = await Interpreter(create_machine(STRICT, logic=MachineLogic()), strict=True).start()
    res = {}
    def worker():
        for lbl, e in (("plain ", Event("NOPE")), ("forged", Event("NOPE", system=True))):
            try:
                it.send_threadsafe(e).result(2); res[lbl] = "ACCEPTED"
            except Exception as exc: res[lbl] = type(exc).__name__
    t = threading.Thread(target=worker); t.start()
    while t.is_alive(): await asyncio.sleep(0.01)
    t.join()
    print("a) send_threadsafe strict plain :", res["plain "])
    print("a) send_threadsafe strict forged:", res["forged"], " <-- same bypass as send()")
    await it.stop()

    # (b) both listener closures share the name the detach filter matches
    import inspect
    from xstate_statemachine import interpreter as I
    src = inspect.getsource(I)
    n = src.count("def _on_child_terminal(")
    print(f"b) closures named '_on_child_terminal' in interpreter.py: {n} "
          f"(spawn path :1548, invoke path :1955); detach filter at :1604-1608 "
          f"matches by __name__ only")

asyncio.run(main())
