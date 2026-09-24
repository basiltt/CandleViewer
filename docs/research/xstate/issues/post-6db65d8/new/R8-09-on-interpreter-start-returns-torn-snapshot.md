---
r8: R8-09
title: "Bug: `get_persisted_snapshot()` from the `on_interpreter_start` hook returns a torn blob (`status:\"running\"`, empty configuration) — 600/600, both engines"
labels: [bug, severity/medium, area/persistence]
severity: Medium
engines: both engines
service_kinds: n/a
repro_script: repro/R8-09_on_interpreter_start_torn_snapshot.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

`get_persisted_snapshot()` called from the `on_interpreter_start` plugin hook returns a
**torn blob** — `status: "running"` with an empty configuration — on both engines, 600/600.

## Reproduction (`6db65d8`)

`repro/R8-09_on_interpreter_start_torn_snapshot.py`: 300 iterations per engine, 600/600
torn. #182 correctly closed the initial-descent window (the `_processing` flag now covers
the whole descent and `on_action_execute`, and both engines refuse there — we verified that
separately and it holds). This hook is one short of that coverage.

## Suggested fix

Bring `on_interpreter_start` inside the same in-flight window #182 established, so the
snapshot API refuses there exactly as it now does from `on_action_execute`.

## Impact

Low blast radius but a sharp edge: a plugin that persists on startup — a perfectly natural
thing for an audit or recovery plugin to do — writes a blob that describes a running
machine with no active state. Our own wrapper is defended against this by a
never-snapshot-before-the-post-start-settle rule, which we have to keep specifically
because of this hook.

## Verification

2026-09-21, python 3.13.7, commit 6db65d8. Run with `PYTHONPATH` including
`battle-6db65d8/concurrency` so `common2` resolves (repro file unchanged).

`repro/R8-09_on_interpreter_start_torn_snapshot.py` — exit 1, `"result": "FAIL"`, 3/3 rows
torn (async `def`, async `async def`, sync `def`): every row from `on_interpreter_start`
shows `status: "running"`, `state_ids: []`, `configuration: []`, while the live, post-start
`healthy_state_ids` for the same interpreter is non-empty (`['r3b.a']` / `['r3b.b']`). The
torn blob also refuses to restore (`AttributeError`), so it is not merely torn but unusable —
consistent with the front-matter's "600/600, both engines" characterisation of the
underlying defect (this minimal repro uses 3 iterations, one per engine/kind combination, not
300; the register's 600/600 count is from the fuller probe, not reproduced verbatim here).
