# Meta-issue #26 — round-6 refresh (draft, not posted)

**Comment body for the adoption meta-issue.**

---

## Round 6 — `main` @ `cec108b` (merge of PR #164, unreleased 0.8.1)

Sixth pass of the adoption audit. 26 issues verified, full regression sweep (238
standalone scripts + an 89-check gate), library suite + coverage, benchmarks, diff review
`3ed3099..cec108b`, 8 battle tracks re-run with new attacks aimed specifically at this
round's fixes, 20 contract machines driven end-to-end, then triage, dedupe and an
**independent adversarial refutation of every Blocker and High we were about to file**.

`__version__` still reports `0.8.0` on this tree — everything below is keyed on the
commit.

### The 26 issues

**24 closed. 1 partial (#122). 1 not fixed (#157).**

Two of the 24 carry a documented scope caveat rather than a complaint: **#144** is fixed
and pinned on `SyncInterpreter` (the same cycle is unbounded on `Interpreter` — filed
separately, not as a reopen), and **#161** validates dict-event *key shape* only, by
design.

Three signals that looked like regressions were **stale artefacts in our own harness**,
and we want to say so plainly: #134's repro (stale detection), #159's repro (a substring
match), and `LC-01` (asserts the pre-#145 `status == "error"` — the code is right and the
`plugins.py` docstring is the stale thing). Our scripts, our fix.

### Quality signals

```
suite     : 3399 passed / 13 skipped / 0 failed   (9m02s, +77 vs 3ed3099)
coverage  : 92.77%  against the new 90% floor from #163  (+2.77 headroom)
hashseed  : PYTHONHASHSEED 1 vs 2 -> 98/98 identical, no order sensitivity
bench     : raw send 238k ev/s; 500-order fill p95 0.057 ms; policy ratios in-band
regressions: 3 confirmed (after-lateness, stop() receipts) — all Medium
```

The persistence and concurrency tracks are the headline good news. #142/#143 landed
**one** legality predicate — exactly one leaf per region — on **both** the write and read
sides, with the read side provably reusing the write-side function. At scale: torn
parallel snapshots go from **27.4 % to 0 %**, 2 000 events snapshot-and-restored at every
quiescent point give 2000/2000, and a 350-machine random-parallel property produces 1 217
snapshots with zero illegal configurations. That is the fix we asked for two rounds ago,
done at the root rather than at the reproducer. It lets us retire a standing constraint
that banned parallel regions on our order path.

### New defects: 2 Blocker · 2 High · 7 Medium · 9 Low

Refutation moved **6 of 10** Blocker/High candidates **down**, and none up. We would
rather file eight accurate findings than twenty loud ones.

### The one pattern worth your time

**Three of this round's four candidate Blockers are "fixed on the engine the issue was
filed against."**

| | async `Interpreter` | sync `SyncInterpreter` |
|---|---|---|
| `always` into a child with a completed `invoke` | **hangs for ever**, core pegged | returns in 0.04 s, `RunawayChainError` |
| two-state invoke cycle | 3 983 laps, silent, `error=None` | trips at 500, `Receipt.error` set |
| `rollback` + `invoke.onDone` | 2 859 invocations in 2.0 s, unbounded | 2 invocations, quiescent |

All three trace to the same place. `interpreter.py:1427`:

```python
if self._raise_depth > limit and not is_system_event(event):
```

comment: *"The sync engine spares these by construction; mirror that here."* On this
commit `sync_interpreter.py:770-828` (#94) spares a completion only **at the moment of
the trip** and drops it thereafter. The async exemption is unconditional, so a cycle made
of engine completions is **never charged** — not merely over budget. Plus #144's
termination rule ("a chain ends only when nothing self-generated remains queued") never
made it from `sync_interpreter.py` into `interpreter.py::_run_event_loop`.

**One change closes all three.**

### The suggestion we care most about

**Add an `Interpreter` / `SyncInterpreter` parity test class**: a handful of pathological
configurations, asserting both engines reach the same terminal disposition. Three of our
four candidate Blockers would have been caught by it at authoring time, before review.
We think it is worth more to this project than any individual fix in this batch, and we
will contribute ours if that is useful.

### Adoption status

**DEFER on our order path; GO on everything else.** Non-order machines start on the
library now — that half of our work drove **zero** new library defects across 46 control
scenarios and 9 snapshot-every-macrostep runs. The order path waits on the async
termination change, which is the only thing between this build and
"adopt with constraints" for us: with the two Blockers closed our open-High count is 2,
inside our bar of 5, both with enforced mitigations.

### Before tagging 0.8.1

1. Bump `__version__` — six rounds, six reports that have had to say "key on the commit".
2. The async termination change above, plus the parity test class.
3. Fix the snapshot in-flight guard's predicate: `base_interpreter.py:1306` uses
   `_step_in_flight() and not _configuration_is_legal()`, and in an entry **or exit**
   action window the configuration is legal while context is half-applied, so the guard is
   inert for every action window in a non-parallel machine. Watch the collision:
   `on_transition` is documented as a safe snapshot site but runs inside the in-flight
   window.
4. Unify `_configuration_is_legal()` and `_active_leaf_present()` — they disagree about a
   root with zero child states, and two definitions of one invariant in one file is the
   shape that reopened #142.
5. Small ones: observable loop-side `RAISE` refusals; decrement the threadsafe counter in
   a done-callback; expose `service_pool_size=`; the `plugins.py:201-202` docstring
   (`"fail"` → `"stopped"`, not `"error"`); and the three docs that currently disagree
   about whether engine completions are cut by the budget
   (`getting-started.md:462` vs `core-concepts.md:639` vs `api/index.md:1786`).

Full detail in the individual issues. Happy to run any of it again on request.
