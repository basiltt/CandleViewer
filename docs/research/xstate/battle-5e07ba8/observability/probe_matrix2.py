"""
Observability probe #2: snapshot drift, dormant-invoke restore, stop-with-
pending-queue, and "can we enumerate every live interpreter / get health
signals" for xstate-statemachine @ 5e07ba8.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python probe_matrix2.py
"""
import asyncio
import json
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    SnapshotDriftError,
)


def probe_snapshot_drift():
    cfg1 = {"id": "m_drift", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    machine1 = create_machine(cfg1, logic=MachineLogic())
    interp1 = SyncInterpreter(machine1).start()
    snap = json.dumps(interp1.get_persisted_snapshot())

    # Structurally different machine, same id: add a guard.
    cfg2 = {
        "id": "m_drift",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "guard": "g"}}}, "b": {}},
    }
    machine2 = create_machine(cfg2, logic=MachineLogic(guards={"g": lambda c, e: True}))

    print("=== snapshot drift (structural hash changed) ===")
    try:
        SyncInterpreter.from_snapshot(snap, machine2)
        print("  no exception raised (unexpected)")
    except SnapshotDriftError as e:
        print(f"  SnapshotDriftError: {e}")

    # Different machine_id entirely.
    cfg3 = {"id": "totally_different", "initial": "a", "states": {"a": {}}}
    machine3 = create_machine(cfg3, logic=MachineLogic())
    print("=== snapshot drift (different machine_id) ===")
    try:
        SyncInterpreter.from_snapshot(snap, machine3)
        print("  no exception raised (unexpected)")
    except SnapshotDriftError as e:
        print(f"  SnapshotDriftError: {e}")

    print("=== verify_machine_hash=False escape hatch ===")
    restored = SyncInterpreter.from_snapshot(snap, machine2, verify_machine_hash=False)
    print(f"  restored ok, status={restored.status}, state={restored.current_state_ids}")


async def probe_dormant_invoke_restore():
    async def slow_service(interp, ctx, ev):
        await asyncio.sleep(100)
        return "done"

    cfg = {
        "id": "m_dormant",
        "initial": "a",
        "states": {"a": {"invoke": {"src": "slow_service", "id": "svc"}}},
    }
    logic = MachineLogic(services={"slow_service": slow_service})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    snap = json.dumps(interp.get_persisted_snapshot())
    await interp.stop()

    print("\n=== restore of dormant invokes (static rebuild, restart_services=False) ===")
    restored = Interpreter.from_snapshot(snap, machine)
    print(f"  status={restored.status}")
    print(f"  has_dormant_invocations={restored.has_dormant_invocations}")
    print(f"  pending_invocations={restored.pending_invocations()}")
    # No live service: sending an event that would need the child to answer
    # just sits there -- the dormant invoke never produces done/error.
    print(f"  restart_services=True re-invokes -> ", end="")
    restored2 = Interpreter.from_snapshot(snap, machine, restart_services=True)
    await restored2.start()
    await asyncio.sleep(0.05)
    print(f"has_dormant_invocations={restored2.has_dormant_invocations}")
    await restored2.stop()


async def probe_stop_with_pending_queue():
    cfg = {"id": "m_stop_pending", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    machine = create_machine(cfg, logic=MachineLogic())
    interp = Interpreter(machine)
    await interp.start()
    for i in range(5):
        interp.send(f"X{i}", wait=False)
    print("\n=== stop() with pending queue, drain=False (default) ===")
    print(f"  pending_events before stop: {len(interp.pending_events)}")
    await interp.stop()
    print(f"  status after stop: {interp.status}")

    machine2 = create_machine(cfg, logic=MachineLogic())
    interp2 = Interpreter(machine2)
    await interp2.start()
    for i in range(5):
        interp2.send(f"X{i}", wait=False)
    print("=== stop(drain=True) ===")
    await interp2.stop(drain=True)
    print(f"  status after drain-stop: {interp2.status}, pending after: {len(interp2.pending_events)}")


def probe_enumerate_interpreters():
    print("\n=== can we enumerate every live interpreter process-wide? ===")
    import xstate_statemachine as xsm
    has_registry = any(
        "registry" in name.lower() or "system" in name.lower() for name in dir(xsm)
    )
    print(f"  module-level exports containing 'registry'/'system': "
          f"{[n for n in dir(xsm) if 'egistry' in n or 'ystem' in n]}")
    print("  ActorSystem is per-hierarchy (rooted at one interpreter's registry); "
          "there is no process-wide registry of every Interpreter/SyncInterpreter "
          "instance ever constructed.")


def probe_visualiser_export():
    cfg = {
        "id": "m_viz",
        "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {"type": "final"}},
    }
    machine = create_machine(cfg, logic=MachineLogic())
    print("\n=== machine JSON / diagram export ===")
    print("  to_mermaid() available:", hasattr(machine, "to_mermaid"))
    print("  to_plantuml() available:", hasattr(machine, "to_plantuml"))
    print("  raw config re-export (to_dict/to_json) available:",
          hasattr(machine, "to_dict") or hasattr(machine, "to_json") or hasattr(machine, "config"))
    mm = machine.to_mermaid()
    print("  mermaid output (first 200 chars):", mm[:200].replace("\n", " | "))


if __name__ == "__main__":
    probe_snapshot_drift()
    asyncio.run(probe_dormant_invoke_restore())
    asyncio.run(probe_stop_with_pending_queue())
    probe_enumerate_interpreters()
    probe_visualiser_export()
    print("\nDONE")
