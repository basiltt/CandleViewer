# Independent recheck: #220 (unknown-key check recurses into every level)

## Method
Standalone repros, neutral cwd, checking: nested-state typo (3 levels deep, the
exact repro from the changelog), transition-level typo (`gaurd`), invoke +
`onDone`-level typo (`traget`), parallel-region typo, and false-positive probes for
`x-` prefix / `meta` / `description` / `tags` at root AND state level simultaneously.

## Results
- `m.r2.y.z: {"entyr": [...], "onn": {...}}` (3 levels deep): default mode logs one
  WARNING naming the full path and both keys with "did you mean" hints; machine
  still builds (silently ignoring the typo'd keys, as before — WARNING is
  advisory). `strict_config=True` raises `InvalidConfigError` with the same message
  instead of building.
- Transition-level typo `{"target": "b", "gaurd": "g"}` under `on.GO`: caught, path
  reported as `m.a on['GO']: 'gaurd' (did you mean 'guard'?)`.
- Invoke `onDone`-level typo `{"traget": "b"}`: caught, path reported as
  `m.a invoke[0] onDone: 'traget' (did you mean 'target'?)`.
- Parallel region (`type: parallel`, two `states` children each with nested
  `states`): a typo (`awlays`) inside a parallel region's leaf state is caught —
  the recursion is type-agnostic and doesn't special-case parallel vs compound.
- False-positive check: `meta`, `x-custom`, `description`, `tags`, `x-foo` present
  simultaneously at BOTH the root and a state, with a genuine typo also present at
  the state's transition level — the metadata keys did not trigger any finding;
  only the genuine typo (`gaurd`) was reported. No false positives from metadata
  keys at any level.

## Verdict
**220 | VERIFIED FIX — no defect | unknown-key check recurses into every state
(any depth, any type including parallel), every transition body (`on`/`always`/
`after`/`onDone`), and every invoke (+ its `onDone`/`onError`), naming the full
path; metadata keys (`x-`, `meta`, `description`, `tags`) are accepted everywhere
with no false positives; `strict_config=True` upgrades to `InvalidConfigError`.**
