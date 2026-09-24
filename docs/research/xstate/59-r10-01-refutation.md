# R10-01 adversarial refutation — engine-event provenance is type identity

**Target:** R10-01 (filed **Blocker**, LIBRARY-DEFECT) — "`done`/`error`/`after`
forgeable 7 ways in-process and via `restore_event`".
**Library:** `_ref/xstate-statemachine` @ `19cb1f1` (unreleased 0.8.1).
**Verdict: DOWNGRADE — Blocker → Low (hardening / defence-in-depth).**

## 1. The reported behaviour reproduces exactly as filed

Re-ran every named repro from neutral cwd `C:/Users/basil`, both service kinds
where applicable:

| repro | result |
|---|---|
| `battle-19cb1f1/fuzz/n1_after_forgery.py` | 4/5 FORGED (V2 import path, V3 `type(held)`, V4 pickle, V5 forged record); **V1 public `AfterEvent` correctly REFUSED (`UnknownEventError`)** |
| `battle-19cb1f1/concurrency/t1_after_provenance_forgery.py` | FAIL 8/8 |
| `battle-19cb1f1/concurrency/s6_restore_event_forgery_minimal.py` | FAIL — forged `engine:true` record drove `onDone` |
| `battle-19cb1f1/persistence/u2_after_forgery.py` | FAIL C/D; **controls B and G refused** |
| `battle-19cb1f1/semantics/repro/d10_sem_1_after_replace.py` | REPRODUCED both kinds |

Nothing here is a measurement artefact and nothing is convergence-sensitive
(the R9-03 pattern does not apply — there is no polling in these probes; the
forged event is accepted synchronously on `send`). Source reads at
`events.py:281-283, 414, 555-565, 579, 604-615` and `base_interpreter.py:4624`
are accurate as written.

**What is wrong is not the observation. It is the severity, which rests on an
implicit claim that a trust boundary is crossed. It is not.**

## 2. Every vector partitions into two classes, and neither crosses a boundary

### Class A — vectors requiring attacker-controlled Python in the interpreter's process

V2 (`from ...events import engine_after`), V3 (`type(held_event)(...)`),
V4 (pickle round-trip), D (`events._EngineAfter`), and the `_replace` vector in
`d10_sem_1_after_replace.py` all share one premise: the adversary executes
arbitrary Python in-process (an import, an action body, a plugin hook).

Control run — plain registered action, **no private import, no forgery, no
event of any kind**:

```
plain user action: {'ctx': {'n': 999}, 'interp': True} {'z.late'}
```

and directly on a live interpreter:

```
in-process reach: ['_active_state_nodes', '_enter_states', '_exit_states', ...]
context mutated directly: {'n': 999}
```

An adversary with that premise already writes context arbitrarily, holds the
`Interpreter`, and can call `_enter_states` / `_exit_states` outright. Forging
an `AfterEvent` is a strictly *weaker* capability than what the premise grants
for free. There is no privilege escalation because there is no intra-process
privilege boundary in CPython to escalate across — the same argument that makes
"a Python library cannot defend against its own caller" true for every
sandboxless library. A per-interpreter nonce (the fix direction R10-01
proposes) does not change this: an in-process adversary reads the nonce off the
interpreter with the same reach that imports `engine_after`.

### Class B — the `restore_event` / snapshot vector

V5, C, and `s6_restore_event_forgery_minimal.py` require the adversary to write
the persisted blob. The library states the boundary explicitly at
`events.py:414`:

> "A caller who can write arbitrary snapshot records already controls
> `state_ids` and `context` outright (#185), so this is the correct trust
> boundary."

I tested that claim rather than accepting it. Hand-editing a snapshot with **no
event forgery at all**:

```
RESTORED: {'z.late'} {'n': 999} running
```

(`state_ids` + `configuration` + `value` + `context` edited consistently; an
inconsistent edit is caught by `SnapshotCorruptError`, which only forces the
forger to be tidy.) The blob writer reaches the post-timer state with poisoned
context directly. The `"engine": true` flag grants **zero additional
capability** over what that same writer already holds. Snapshots are
untrusted-input-shaped and must be integrity-protected by the embedder
regardless — that is already carried as a constraint in our register (#185
class), not a new finding.

## 3. Documented, and the named boundary holds

`docs/api/index.md:1185-1201` documents this design verbatim, including the
exact properties R10-01 calls the forgery primitive:

> "The engine mints its own completions through private subclasses (identical
> to the public class under `isinstance`, equality, `_replace`, pickle and
> `deepcopy`); a persisted engine completion round-trips … with its provenance
> intact (`"engine": true` on the record), while a hand-written record restores
> as user traffic."

The threat #195/#203 claim to close is **name/shape-based confusion from
outside the process**: an event arriving over a queue, an API, or a
hand-authored record that *looks* like a completion. That boundary holds in
every probe — V1, B and G (public `AfterEvent`, record without the flag) are
refused under `strict:True` + `onUnhandled:"error"`, and the genuine-invocation
outstanding check at `base_interpreter.py:4633+` still gates completions. No
run in this pass shows an externally-supplied, non-code-executing input driving
an `after` or an `onDone`.

`is_system_event`/`system_event` are the exported surface; `engine_after` /
`engine_done` / `engine_error` are **not** re-exported from the package root
(verified: `['is_system_event', 'system_event']`), so they are not part of the
documented API — reaching them is already Class A.

## 4. Residual defect (why Low, not REFUTED)

Real, but hardening-grade:

1. `engine_*` factories are module-scope names without an underscore prefix in
   a public module. Cheap fix: prefix them, or gate on a module-private token.
2. `restore_event` trusts a plaintext boolean. An embedder who signs only part
   of the blob could be surprised; the docs should say "sign the whole
   snapshot" rather than relying on the #185 reasoning being read.
3. `_replace` re-typing a genuine event is the least intuitive of the set and
   deserves an explicit doc line.

None of these let an adversary do anything an in-process or blob-writing
adversary cannot already do. Severity **Low**; no adoption constraint change
beyond what CV constraints already require (integrity-protect snapshots; treat
in-process plugin/action code as trusted).

## 5. Knock-on

R10-01 was ranked #1 in `58-r10-findings-register.md` and that register claims
"one fix retires the top of this list". That ranking should be revised: the
top-of-list Blocker is not a Blocker, and the "security half" framing of the
adjacent items should be re-read under the two-class partition above.
