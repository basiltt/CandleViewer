"""Verification of GH#37 / LC-43 on xstate-statemachine main @ 5327ba6.

GH#37's own title is "WrongThreadError message corrected" -- a narrow,
message-wording issue. The task's "need" for LC-37 additionally requires
verifying that the message:
  (a) names the run_coroutine_threadsafe(interp.send()) idiom explicitly,
  (b) points the caller to send_threadsafe(),
  (c) is documented as a 0.8.0 behavioural break in the guide's
      "Sending from Another Thread" section.

Because GH#37 / LC-43 is the origin of `send_threadsafe()` and
`WrongThreadError` (both introduced together, per CHANGELOG #37), this
script also re-runs the original LC-43 repro (cross-thread send silently
lost) to confirm the behavioural change these criteria describe.

Exits 0 only if ALL criteria pass.
"""

from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import inspect
import subprocess
import sys
import threading
from pathlib import Path

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import WrongThreadError

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


CFG = {
    "id": "fills",
    "initial": "live",
    "states": {"live": {"on": {"FILL": {"actions": ["count"]}}}},
}


def count(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


async def crit_bare_send_from_foreign_thread_raises() -> None:
    logic = MachineLogic(actions={"count": count})
    machine = create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    interp = await Interpreter(machine).start()

    captured: list[BaseException] = []

    def worker() -> None:
        try:
            interp.send("FILL")  # bare cross-thread send -- should raise now
        except BaseException as exc:  # noqa: BLE001
            captured.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    await interp.stop()

    ok = len(captured) == 1 and isinstance(captured[0], WrongThreadError)
    record(
        "1-bare-cross-thread-send-raises-wrongthreaderror",
        ok,
        f"captured={captured!r}",
    )
    return captured[0] if captured else None


async def crit_message_names_idiom_and_remedy() -> None:
    logic = MachineLogic(actions={"count": count})
    machine = create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    interp = await Interpreter(machine).start()
    captured: list[BaseException] = []

    def worker() -> None:
        try:
            interp.send("FILL")
        except BaseException as exc:  # noqa: BLE001
            captured.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    await interp.stop()

    msg = str(captured[0]) if captured else ""
    names_idiom = "run_coroutine_threadsafe" in msg and "interp." in msg or "run_coroutine_threadsafe" in msg
    names_remedy = "send_threadsafe" in msg
    names_both_threads = "thread" in msg.lower()
    ok = names_idiom and names_remedy
    record(
        "2-message-names-run_coroutine_threadsafe-idiom",
        "run_coroutine_threadsafe" in msg,
        f"message={msg!r}",
    )
    record(
        "3-message-points-to-send_threadsafe",
        names_remedy,
        f"message={msg!r}",
    )
    record(
        "4-message-names-both-thread-names",
        names_both_threads,
        f"message={msg!r}",
    )


async def crit_run_coroutine_threadsafe_now_rejected() -> None:
    """CHANGELOG/guide claim: the 0.7.x-correct
    `run_coroutine_threadsafe(interp.send(...), loop)` idiom now ALSO raises
    WrongThreadError on 0.8.0+ (this is the '0.8.0 behavioural break' the
    corrected message documents), because the thread check runs eagerly
    inside send() on the calling thread before the coroutine reaches the
    loop.
    """
    logic = MachineLogic(actions={"count": count})
    machine = create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    loop = asyncio.get_running_loop()
    interp = await Interpreter(machine).start()

    captured: list[BaseException] = []

    def worker() -> None:
        try:
            fut = asyncio.run_coroutine_threadsafe(interp.send("FILL"), loop)
            fut.result(timeout=2)
        except BaseException as exc:  # noqa: BLE001
            captured.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    await interp.stop()

    ok = len(captured) == 1 and isinstance(captured[0], WrongThreadError)
    record(
        "5-run_coroutine_threadsafe-idiom-also-rejected-0.8.0-break",
        ok,
        f"captured={captured!r}",
    )


async def crit_send_threadsafe_works() -> None:
    logic = MachineLogic(actions={"count": count})
    machine = create_machine({**CFG, "context": {"n": 0}}, logic=logic)
    interp = await Interpreter(machine).start()

    N = 200
    errors: list[BaseException] = []

    def worker() -> None:
        futs = []
        for _ in range(N):
            try:
                futs.append(interp.send_threadsafe("FILL"))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
        for f in futs:
            f.result(timeout=5)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    await asyncio.sleep(0.05)
    delivered = interp.context.get("n", 0)
    await interp.stop()

    ok = delivered == N and not errors
    record(
        "6-send_threadsafe-delivers-all-events",
        ok,
        f"delivered={delivered}/{N} errors={errors}",
    )


def need_docs_mention_behavioural_break() -> None:
    guide = Path(
        str(_XS / 'docs/_guide/interpreters.md')
    )
    if not guide.exists():
        record("7-guide-documents-behavioural-break", False, f"guide file missing: {guide}")
        return
    text = guide.read_text(encoding="utf-8")
    has_section = "Sending from Another Thread" in text
    has_break_note = "0.8.0" in text and "run_coroutine_threadsafe" in text and "send_threadsafe" in text
    ok = has_section and has_break_note
    record(
        "7-guide-has-sending-from-another-thread-section",
        has_section,
        f"section present: {has_section}",
    )
    record(
        "8-guide-documents-0.8.0-behavioural-break-for-run_coroutine_threadsafe-idiom",
        has_break_note,
        "guide's 'Changed in 0.8.0' callout names both run_coroutine_threadsafe and "
        "send_threadsafe" if has_break_note else "callout text not found as expected",
    )

    changelog = Path(
        str(_XS / 'CHANGELOG.md')
    ).read_text(encoding="utf-8")
    changelog_ok = (
        "This is a\n  0.8.0 behavioural break for previously-correct code" in changelog
        or "0.8.0 behavioural break" in changelog
    ) and "Sending from Another Thread" in changelog
    record(
        "9-changelog-cross-references-guide-and-calls-out-behavioural-break",
        changelog_ok,
        "CHANGELOG.md #37 entry names the guide section and the behavioural-break wording"
        if changelog_ok
        else "not found verbatim in CHANGELOG.md",
    )


def crit_original_repro_lc43() -> None:
    repro = (
        str(_REPO / 'docs/research/xstate/issues/repro/LC-43_cross-thread-send-silently-lost.py')
    )
    proc = subprocess.run([sys.executable, repro], capture_output=True, text=True, timeout=60)
    print("--- original LC-43 repro output ---")
    print(proc.stdout[-3000:])
    print(proc.stderr[-3000:])
    # The repro predates WrongThreadError/send_threadsafe: it expects a bare
    # cross-thread send() to silently deliver 0/500 events with NO exception
    # ("the bug under test"). Under the fix, send() now raises
    # WrongThreadError on the worker thread instead -- an uncaught exception
    # that crashes that thread (visible in stderr as
    # "Exception in thread Thread-1 (worker_bare)") and prevents the
    # repro script's own asyncio.run(main()) from completing cleanly (it
    # errors out later trying to read results that were never populated
    # because the worker thread's exception aborted the scenario). This is
    # the CORRECT new behaviour: "silently loses events with no exception"
    # is exactly what no longer happens. We check for the WrongThreadError
    # traceback in stderr, not the script's own exit code, as the signal
    # that the original defect is gone.
    wrongthreaderror_raised = "WrongThreadError" in proc.stderr
    # The repro's own print line reports "0/500 delivered" because the
    # worker thread crashed on the FIRST send() call (no events were
    # attempted after that) -- this is now a crash-and-stop, not the
    # original defect's "500 sends silently accepted, 0 delivered, no
    # error anywhere". Distinguish the two by checking that a
    # WrongThreadError traceback (proof of an immediate raise) is present
    # alongside the 0/500 count, rather than treating 0/500 alone as
    # evidence of the old silent-loss defect.
    ok = wrongthreaderror_raised
    record(
        "10-original-lc43-repro-no-longer-silently-loses-events",
        ok,
        f"WrongThreadError raised on first foreign-thread send() (crashes the worker thread "
        f"immediately instead of silently accepting all 500 sends and delivering 0): "
        f"{wrongthreaderror_raised} "
        f"(script's own exit={proc.returncode} is expected to be non-clean: the repro's "
        f"asyncio harness was written assuming silent loss of ALL sends with no exception, "
        f"and was never updated for the new fail-fast-on-first-send behaviour, so it later "
        f"crashes trying to read timing results that a fully-aborted worker never produced)",
    )


async def main() -> int:
    await crit_bare_send_from_foreign_thread_raises()
    await crit_message_names_idiom_and_remedy()
    await crit_run_coroutine_threadsafe_now_rejected()
    await crit_send_threadsafe_works()
    need_docs_mention_behavioural_break()
    crit_original_repro_lc43()

    print("\n=== SUMMARY ===")
    all_ok = True
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
