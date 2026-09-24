---
description: Scaffold a statechart (machine JSON + bindings + contract test) from a B1-B20 catalogue entry.
argument-hint: <B-number e.g. B1>
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(pytest:*), Bash(ruff:*), Bash(mypy:*), Bash(uv run:*), Bash(python:*)
---
# /statechart-new $ARGUMENTS

Delegate to the `statechart-author` agent (model: opus). Rules: `.claude/rules/21-statecharts.md`.

1. Read `docs/plan/28-statechart-catalogue.md`: §1.2 (out-of-scope), §1.3, §1.3b, §1.3c, and entry `## $ARGUMENTS`
   (subsections .1 Contract through .8 Implementation notes). Read `docs/plan/29-statechart-adoption-plan.md` §1.
   If the entry does not exist or is a hot-path concern (C-2.20), stop and report.
2. Let `NN` = zero-padded number, `<name>` = snake_case entry name. Create:
   - `services/api/candleviewer/statechart/machines/BNN.<name>.machine.json` — copy states/events/transitions from the
     normative contract; root keys `"id"`, `"strictConfig": true`, `"onUnhandled": "defer"`, `"maxIterations": 500`;
     add ordered unguarded audit arms where a guarded transition may be denied.
   - `services/api/candleviewer/statechart/bindings/bNN_<name>.py` — a `MachineLogic` with one function per guard
     (pure, sync), action (async coroutine), service (async) named in the contract, each with a docstring citing the
     catalogue subsection, body `raise NotImplementedError` unless the ticket asks for the implementation.
     No `xstate_statemachine` import (hook enforced).
   - Event schemas for every event added to `CV_EVENT_SCHEMAS` in `statechart/config.py`.
   - `services/api/tests/xstate_contract/test_bNN_<name>.py` — one test per transition, one hypothesis property per
     invariant, snapshot/restore round trip, refused-overflow and unhandled-event (defer) behaviour. Build via
     `candleviewer.statechart.build("BNN")` only.
3. Register the machine in `registry.py`; regenerate `machines/machine_hashes.lock`.
4. Run the statechart lint, `pytest services/api/tests/xstate_contract -k bNN`, ruff, mypy. Tests for unimplemented
   bindings are expected to fail — mark them `xfail(strict=True, reason="<ticket key>")`.
5. Print the file list, the transition/invariant coverage table, and the follow-up tickets needed.
