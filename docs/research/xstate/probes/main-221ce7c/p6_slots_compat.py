"""L-6 probe: __slots__ on the interpreters -- does anything that used to
work now raise AttributeError?

BaseInterpreter.__slots__ deliberately keeps "__dict__", so ad-hoc
attributes still work. The real risk is subtler: a slot declared in BOTH a
base and a subclass shadows, and a name declared in __slots__ AND assigned
in __init__ of a different class in the MRO. Also check that a plugin can
still stash state on an interpreter, and that pickling/copying still work.
"""

import copy

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CONFIG = {"id": "p6", "initial": "a", "states": {"a": {}}}


def main() -> None:
    m = create_machine(CONFIG, logic=MachineLogic())

    for cls in (Interpreter, SyncInterpreter):
        i = cls(m)
        name = cls.__name__

        # 1. ad-hoc attribute (plugins, test spies)
        try:
            i.my_plugin_state = {"k": 1}
            ok_adhoc = i.my_plugin_state == {"k": 1}
        except AttributeError as exc:
            ok_adhoc = f"AttributeError: {exc}"
        print(f"[{name}] ad-hoc attribute: {ok_adhoc}")

        # 2. duplicate slot names across the MRO (memory waste + shadowing)
        seen: dict[str, list[str]] = {}
        for k in cls.__mro__:
            for s in getattr(k, "__slots__", ()):
                seen.setdefault(s, []).append(k.__name__)
        dupes = {s: ks for s, ks in seen.items() if len(ks) > 1}
        print(f"[{name}] duplicated slots across MRO: {dupes or 'none'}")

        # 3. every attribute __init__ actually sets is either a slot or
        #    lands in __dict__ (i.e. the slots list is not stale/incomplete)
        slotnames = {s for s in seen if not s.startswith("__")}
        in_dict = set(vars(i))
        leaked = in_dict - slotnames
        print(f"[{name}] attrs falling back to __dict__ (slot list misses): "
              f"{sorted(leaked) or 'none'}")

        # 4. subclassing still works
        class Sub(cls):  # type: ignore[valid-type,misc]
            __slots__ = ("extra",)

        s = Sub(m)
        s.extra = 1
        print(f"[{name}] subclass with own slots: ok")

        # 5. copy
        try:
            copy.copy(i)
            print(f"[{name}] copy.copy: ok")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] copy.copy: {type(exc).__name__}: {exc}")


main()
