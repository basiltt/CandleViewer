# -*- coding: utf-8 -*-
"""Generate post-3ed3099/comments/<N>.md from verify-main-3ed3099/*.result.md."""
import glob, json, os, re, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
VER = os.path.normpath(os.path.join(HERE, "..", "verify-main-3ed3099"))
OUT = os.path.join(HERE, "comments")
os.makedirs(OUT, exist_ok=True)

CLOSED = "91 99 102 103 104 105 106 107 108 109 110 111 112 113 114 115 116 117 119 120 121 123 124 126 127 128 129 130 131 132 135 136 137 138".split()
PARTIAL = "118 122 125 133 134".split()

SHORT = {
 "91": "alias-ambiguity guard fires for its own documented example",
 "99": "`SyncInterpreter` delivers `onError` for a failed invoked child",
 "102": "mid-macrostep snapshot is refused with a typed error",
 "103": "`SyncInterpreter.start()` no longer hangs on the cross-region `always` shape",
 "104": "`OverflowPolicy.BLOCK` delivers fire-and-forget `send()`",
 "105": "external `send()` is no longer charged to the chain budget",
 "106": "`Receipt.deferred` no longer keys on `id(event)`",
 "107": "the priority (timer) lane is persisted",
 "108": "root-targeting transitions are rejected at build time",
 "109": "`done.invoke` carries the child's `output`, not its context",
 "110": "malformed snapshots are refused with `SnapshotCorruptError`",
 "111": "`_detach()` preserves engine provenance under `wait=True`",
 "112": "a settle-budget trip is observable and leaves a legal configuration",
 "113": "malformed events raise the typed `InvalidEventError`",
 "114": "run-loop death is published; pending receipts no longer hang",
 "115": "`SimulatedClock` settler leak closed by `_detach()`",
 "116": "sync/async plain-invoke completion timing parity",
 "117": "`from_snapshot(clock=...)` accepted on both engines",
 "119": "`Receipt.deferred` arity break declared as breaking in the CHANGELOG",
 "120": "the async trip spares engine completion events",
 "121": "`create_machine()` no longer mutates duck-typed logic",
 "123": "`SyncInterpreter.send()` fires `on_event_dropped(reason='not_running')`",
 "124": "sync/async init `on_transition` hook parity",
 "126": "`LoggingInspector` redacts denylisted keys",
 "127": "`async def` hook overrides are surfaced; `on_plugin_error` added",
 "128": "`after` timers re-armed on restore; `has_dormant_timers` added",
 "129": "`stop()` fires `on_event_dropped` for abandoned events",
 "130": "`escalate()` routes to the parent's `onError`",
 "131": "non-JSON pending event data fails loudly with `SnapshotSerializationError`",
 "132": "ambiguous bare `stateIn` name is rejected, not suffix-matched",
 "135": "`status` is not a liveness signal between `from_snapshot()` and `start()` — documented",
 "136": "self-referential config raises `InvalidConfigError`, not `RecursionError`",
 "137": "`is_system_event` / `system_event` exported and documented",
 "138": "engine provenance survives `deepcopy` and `pickle`",
 "118": "`AfterEvent` lateness telemetry on snapshot round-trip",
 "122": "`SyncInterpreter.tick()` and chained due deadlines",
 "125": "deferred replay as its own macrostep",
 "133": "unresolved `sendTo` / `forwardTo` target drops",
 "134": "`on_resolve_error` plugin hook for unresolved transition targets",
}

# Round-5 follow-on note for the three issues whose invariant is filed separately.
INVARIANT = {
 "102": ("<R5-01>",
   "The acceptance criteria above are met **as written**, and we are confirming this "
   "issue closed on that basis. Separately, our round-5 battle-test found that the "
   "guard behind them is an *any-leaf* test rather than a per-region configuration-"
   "legality test: `base_interpreter.py:1112` accepts a snapshot as long as **some** "
   "atomic state is active, so a parallel machine mid-transition in one region "
   "snapshots with that whole region absent, and the macrostep also stays open while "
   "entry actions run. That is the invariant behind this issue rather than the "
   "reproducer this issue named, so we have filed it as a **new** issue, "
   "<R5-01>, rather than reopening this one."),
 "103": ("<R5-04>",
   "The acceptance criteria above are met **as written**, including the O(1) "
   "budget-trip criterion, and we are confirming this issue closed on that basis. "
   "Separately, our round-5 fuzz track found a different shape that still does not "
   "terminate: nested invokes whose `onDone` targets their common compound ancestor "
   "livelock `SyncInterpreter.start()`, with `sync_interpreter.py:802-807` resetting "
   "the chain counters so that no value of `maxIterations` (`None`, `10`, `1000`) "
   "bounds it. That is the invariant behind this issue rather than the reproducer "
   "this issue named, so we have filed it as a **new** issue, <R5-04>, "
   "rather than reopening this one."),
 "110": ("<R5-02>",
   "The acceptance criteria above are met **as written** — every field this issue "
   "named is now refused with `SnapshotCorruptError` — and we are confirming it "
   "closed on that basis. Separately, our round-5 persistence and concurrency tracks "
   "found that `check_shape()` validates field *shapes* but never configuration "
   "*legality*: a truncated `configuration` such as `['fz']` (ancestor retained, leaf "
   "deleted) satisfies the emptiness guard at `persistence.py:186`, and "
   "`base_interpreter.py:1442` then prefers `configuration` over the still-correct "
   "`state_ids`, restoring a `running` machine with zero active leaves that is "
   "permanently inert. Fields outside the named set (`version`, `history`, `actors`, "
   "`system`, `deferred`) also still leak raw `TypeError`/`AttributeError`/`ValueError`. "
   "Those are the invariant behind this issue rather than the reproducers it named, so "
   "we have filed them as **new** issues, <R5-02> and <R5-03>, rather than "
   "reopening this one."),
}

# Unmet sub-criteria quoted verbatim for the five partials, with the surviving gap.
REOPEN = {
 "118": {
   "quote": "| 3 | A v1-style record with no `scheduled_for`/`fired_at` keys restores them as `None`, not `0.0` | ✗ |\n"
            "| 5 | `tests/test_events_persistence.py::test_after_event_missing_lateness_fields_restore_as_none` | ✗ — no such test, equivalent, or behaviour exists |",
   "gap": "The primary defect is fixed: `persist_event` writes `scheduled_for`/`fired_at` "
          "for `kind == \"after\"` records (`events.py:334-335`) and `restore_event` reads "
          "them back exactly (`events.py:385-386`), so real lateness telemetry now survives "
          "every round-trip this library itself performs. What is not implemented is the "
          "*absent-value* half of criterion 3. `restore_event` defaults with "
          "`float(record.get(\"scheduled_for\", 0.0))`, so a `\"after\"`-kind record that is "
          "missing the keys — hand-written, or written by a third party or a future writer — "
          "restores as `0.0`, which is an affirmative claim of \"fired exactly on time\", "
          "not an \"unknown\". `float(None)` raises, so a `None` default was never wired in. "
          "No test covers the missing-keys-on-a-v2-record case.\n\n"
          "This is narrow and low-severity — it is unreachable through this library's own "
          "persist→restore path. We are reopening only because a lateness number that reads "
          "`0.0` when the truth is \"we do not know\" is the kind of telemetry that gets "
          "trusted downstream. Making the fields `Optional[float]` defaulting to `None`, and "
          "having `lateness_ms` return `None` when either is `None`, would close it.",
 },
 "122": {
   "quote": "| 1 | `SyncInterpreter.tick()`, called once after all deadlines in a chain are due, reaches the same terminal state the async engine reaches after an equivalent wall-clock wait | ✓ for the zero-delay (`after: 0`) chain the fix targets; ✗ for the original repro's real-delay (`after: 50`×3) construction |\n"
            "| 2 | Test … covering the 3-stage ack/retry/escalate ladder shape | ✗ — the actual test covers a 3-stage **zero-delay** `a->b->c->d` chain, not the real-delay ladder shape the criterion names |\n"
            "| 3 | `repro/R4-27_sync_tick_chained_deadlines.py` exits 0 once fixed | ✗ — still exits 1 |",
   "gap": "`tick()` now loops (`sync_interpreter.py:1341-1367`), pumping timers and draining "
          "until a pump delivers nothing, which genuinely fixes the zero-delay chain. The "
          "shape this issue was filed on — the 3-stage `after: 50` ack/retry/escalate ladder — "
          "still needs three `tick()` calls with real waits between them, and "
          "`repro/R4-27_sync_tick_chained_deadlines.py` still exits 1 unchanged.\n\n"
          "We recognise this may be intended: with a `RealClock`, deadline 2 is genuinely not "
          "due when deadline 1 fires, and no synchronous call can honestly advance wall time. "
          "If that is the decision, the right close is a documentation one — state in the "
          "`tick()` docstring and the timers guide that `tick()` drains **all deadlines that "
          "are due at the current clock reading**, that chained real-delay deadlines therefore "
          "require one `tick()` per deadline (or a `SimulatedClock`), and update this issue's "
          "criterion 1 accordingly. As written, criterion 1's \"called once after all deadlines "
          "in a chain are due\" is unmet for the case the issue names, so we are reopening for "
          "that decision rather than asserting a defect.",
 },
 "125": {
   "quote": "| 1 | `repro/R4-30_deferred_replay_folds_receipt.py` exits 0 | ✗ still exits 1 (script uses `SyncInterpreter`) |\n"
            "| 2 | New test asserts ARM's receipt reflects only ARM's transition | ✓ … but this test only exercises the **async** `Interpreter`, not `SyncInterpreter` |",
   "gap": "The fix is engine-asymmetric. On the async `Interpreter` it is correct: "
          "`interpreter.py:1431` resolves the triggering event's receipt **before** "
          "`_replay_pending` re-queues the deferred events (`:1432-1440`, `:1521-1537`), so "
          "`ARM`'s receipt reports `['m_defer_replay.b']` — its own transition only.\n\n"
          "`SyncInterpreter` has no equivalent split. `send()` "
          "(`sync_interpreter.py:507-541`) appends the event, calls `_process_event_queue()` — "
          "which drains the *entire* queue including deferred events re-queued at the head via "
          "`extendleft` (`:809-818`) — and only then builds the `Receipt` from "
          "`self.current_state_ids` (`:534-541`). There is no per-macrostep receipt boundary "
          "on this engine, so the replayed event's effect still folds into the triggering "
          "event's receipt: `send(\"ARM\", wait=True)` returns `m_defer_replay.c`, byte-identical "
          "to the pre-fix behaviour.\n\n"
          "The new test `TestReplayIsItsOwnMacrostep::test_arm_receipt_reports_arm_transition_only` "
          "covers the async engine only, so the gap is also untested. Anyone using "
          "`SyncInterpreter` receipts for per-event audit attribution is still exposed to the "
          "original defect.",
 },
 "133": {
   "quote": "| 2 | The analogous `forwardTo` unresolved-target path gets the same treatment | ✗ **NOT FIXED** |\n"
            "| 5 | `tests/test_sendto_drops.py::test_unresolved_forwardto_fires_on_event_dropped` | ✗ not present, and would fail if it existed |",
   "gap": "The `sendTo` half is fixed and we are happy with it: the `SEND_TO` branch at "
          "`base_interpreter.py:2941-2967` fires `on_event_dropped` with the distinct reason "
          "`\"unresolved_target\"` (a different string from the `\"sendto_unresolved\"` we "
          "proposed, which is fine — it is distinct and documented).\n\n"
          "The `forwardTo` branch was not given the same treatment. It still only "
          "`logger.warning`s and returns: no `on_event_dropped`, no soft error, no "
          "`last_error`. That is the same silent-drop surface this issue was filed against, on "
          "the sibling action, and criterion 2 named it explicitly. Note that this is also the "
          "second round in which a fix landed on one of a pair of sibling code paths — the "
          "cheapest close here is to route both branches through one shared "
          "`_report_unresolved_target()` helper so the pair cannot drift again.\n\n"
          "One more thing worth deciding while this is open: an unresolved target is a "
          "*configuration* error, not a runtime condition, so `last_error` arguably ought to "
          "be set too, not just a hook fired.",
 },
 "134": {
   "quote": "| 2 | `_execute_transition` calls `on_resolve_error` on every registered plugin when target resolution fails | **PARTIAL** — implemented and called on the **async** `Interpreter` engine (`interpreter.py:1410`, `_report_resolve_error`); **not implemented on `SyncInterpreter`** |\n"
            "| 4 | `repro/R4-36_no_resolve_error_hook.py` exits 0 | ✗ **exits 1** — the repro uses `SyncInterpreter`, which is exactly the unfixed path |",
   "gap": "`PluginBase.on_resolve_error` exists with a no-op default (criterion 1 met; the "
          "signature is `(self, interpreter, error, event)` rather than the "
          "`(self, interpreter, transition, error)` we proposed, which is fine by us — please "
          "just pin it in the docs before release, since a hook signature is API).\n\n"
          "The hook is only ever *called* from the async engine. `_report_resolve_error` is "
          "invoked at `interpreter.py:1410`; `sync_interpreter.py` contains no call to it "
          "anywhere, so a `SyncInterpreter` with an unresolvable target still fails silently as "
          "far as plugins are concerned. The issue's own repro targets the sync engine and "
          "still exits 1.\n\n"
          "A plugin hook that fires on one engine and not the other is worse than no hook, "
          "because an audit plugin registered on both will show a clean record for the sync "
          "one. The fix is presumably to hoist the `_report_resolve_error` call into the shared "
          "`base_interpreter` resolution path so both engines inherit it, as was done for #31's "
          "`StateNotFoundError` raise.",
 },
}


def script_for(n):
    hits = [os.path.basename(p) for p in glob.glob(os.path.join(VER, "%s_*.py" % n))]
    return hits[0] if hits else None


def parse(n):
    txt = open(os.path.join(VER, "%s.result.md" % n), encoding="utf-8").read()
    rows = [l for l in txt.split("\n") if l.startswith("|")]
    # keep the first contiguous table block
    tbl, started = [], False
    for l in txt.split("\n"):
        if l.startswith("|"):
            tbl.append(l); started = True
        elif started:
            break
    m = re.search(r"##\s*Fix location[^\n]*\n+(.*?)(?=\n##|\Z)", txt, re.S)
    fix = ""
    if m:
        blk = m.group(1)
        # keep the leading prose paragraph, plus one fenced code block if the
        # paragraph ends on a colon (the citation is inside the block).
        paras = re.split(r"\n\s*\n", blk.strip())
        fix = paras[0].strip()
        if fix.endswith(":") and len(paras) > 1 and paras[1].lstrip().startswith("```"):
            code = paras[1].rstrip()
            if code.count("```") == 1:
                code += "\n```"
            fix = fix + "\n\n" + code
    return tbl, fix


HDR = ("Verified on main @ `3ed3099` (pre-0.8.1), as part of our adoption audit (#26). "
       "Build identified **by commit** — `__version__` still reports `0.8.0` on this tree, "
       "so nothing here should be keyed on the version string. CPython 3.13.7, Windows 11. "
       "Verification script: `issues/verify-main-3ed3099/%s`.")

FOOT = ("No regressions against any prior verification set or our probe baseline. "
        "Full suite on this commit: **3 322 passed / 13 skipped / 0 failed**, coverage **90 %**.")

written = []

for n in CLOSED:
    tbl, fix = parse(n)
    sc = script_for(n)
    parts = []
    parts.append("# Comment for issue #%s — %s\n" % (n, SHORT[n]))
    parts.append("**Action:** comment")
    parts.append("**Disposition:** CONFIRM CLOSED (all acceptance criteria met)\n")
    parts.append("---\n")
    parts.append(HDR % (sc if sc else "(no script — documentation/CHANGELOG criteria, verified by reading the tree)"))
    parts.append("")
    parts.append("\n".join(tbl))
    parts.append("")
    if fix:
        parts.append("**Fix located at:**\n")
        parts.append(fix)
        parts.append("")
    if n in INVARIANT:
        _, para = INVARIANT[n]
        parts.append(para)
        parts.append("")
    parts.append(FOOT)
    parts.append("")
    parts.append("**Disposition: confirming closed.**")
    body = "\n".join(parts).rstrip() + "\n"
    p = os.path.join(OUT, "%s.md" % n)
    open(p, "w", encoding="utf-8", newline="\n").write(body)
    written.append((n, "comment"))

for n in PARTIAL:
    tbl, fix = parse(n)
    sc = script_for(n)
    d = REOPEN[n]
    parts = []
    parts.append("# Comment for issue #%s — %s\n" % (n, SHORT[n]))
    parts.append("**Action:** comment + reopen (narrow)")
    parts.append("**Disposition:** PARTIAL — the main defect is fixed; one acceptance criterion is unmet by code\n")
    parts.append("---\n")
    parts.append(HDR % sc)
    parts.append("")
    parts.append("Most of this issue is genuinely closed. We are reopening it **narrowly**, for "
                 "the sub-criterion below only — not for wording, test-file paths or naming.\n")
    parts.append("## Full criteria table\n")
    parts.append("\n".join(tbl))
    parts.append("")
    parts.append("## The unmet sub-criterion, quoted\n")
    parts.append("> " + d["quote"].replace("\n", "\n> "))
    parts.append("")
    parts.append("## What is still open\n")
    parts.append(d["gap"])
    parts.append("")
    if fix:
        parts.append("**Fix located at:**\n")
        parts.append(fix)
        parts.append("")
    parts.append(FOOT)
    parts.append("")
    parts.append("**Disposition: reopening narrowly for the criterion quoted above.** Everything "
                 "else in this issue we consider closed, and we are happy for it to be re-closed "
                 "the moment that one item lands (or, where noted, is explicitly decided against "
                 "in the docs).")
    body = "\n".join(parts).rstrip() + "\n"
    p = os.path.join(OUT, "%s.md" % n)
    open(p, "w", encoding="utf-8", newline="\n").write(body)
    written.append((n, "comment+reopen"))

print("wrote %d comment files" % len(written))
