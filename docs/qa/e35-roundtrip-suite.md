# E35-Q02 — Rule IR round-trip property suite and 30-rule corpus gate

Owner: QA (E35-Q02, issue #1001). Plan context: [`e35-rule-engine-test-plan.md`](e35-rule-engine-test-plan.md)
(BB-001-07, BB-006-*). Contract: [ADR-0026](../plan/27-adrs/ADR-0026-rule-ir-canonicalisation.md),
[`24-internal-schemas.md` §11](../plan/24-internal-schemas.md).

## What it guards

A lossy round trip could silently change what an armed rule does, so the suite is a **security control**
and a required CI lane (`rule-roundtrip`) for every PR touching `services/api/candleviewer/rules/ir/**`,
`rules/compiler/**`, `rules/errors.py`, the suite itself or the corpus.

| Part | File (`services/api/tests/rules/roundtrip/`) | Budget |
|---|---|---|
| Property suite: ≥10 000 generated documents, full hop chain | `test_property_roundtrip.py`, `shard.py`, `strategies.py`, `chain.py` | < 4 min (≈2 min on 8 workers) |
| Corpus gate: 30 hand-authored rules vs golden hashes, both directions | `test_corpus_gate.py`, fixtures `tests/fixtures/rule_corpus/` | < 30 s (≈3 s) |
| Lossy hop / presentation / regression tests | `test_lossy_hop.py` | seconds |
| Mutation sanity check (unsorted-keys defect) | `test_mutation_sanity.py` | shrink < 60 s (≈5 s) |

## The hop chain

`chain.full_chain(doc)`: wire (every mapping's key order reversed) → IR → **node** → IR → **form** → IR,
then form → node → IR. At every hop the canonical hash must be unchanged and the `graph_layout`
presentation block must survive untouched (the compiler may only add `node_only_constructs`). For a
document the form editor cannot represent, `to_form_model` must raise `FormUnrepresentableError`
(named, lists every reason); returning a document there fails the chain.

## Generator

`strategies.py` produces documents that `Rule.model_validate` accepts (schema-valid, not necessarily
sensible — the validator has its own suite). It is biased toward the hard cases: shared sub-expressions
(re-used node bodies), `n_of`, booleans at the 32-child bound, temporal nodes wrapping booleans, and
arithmetic nested in arithmetic (plus the 8-operand bound). Two thirds of the budget use the full grammar,
one third the form subset, so the form hop is exercised on thousands of documents per run.

## Running it

```bash
cd services/api
uv run pytest tests/rules/roundtrip -q --no-cov -s -m "not roundtrip"   # corpus + mutation + lossy
uv run pytest tests/rules/roundtrip -q --no-cov -s -m roundtrip         # the 10 000-document run
```

Environment: `CV_ROUNDTRIP_EXAMPLES` (default 10000), `CV_ROUNDTRIP_SEED` (default random; always
printed as `[roundtrip] seed=…`), `CV_ROUNDTRIP_WORKERS` (default CPU count, max 8), `CV_ROUNDTRIP_DB`
(default `services/api/.hypothesis/roundtrip`, cached by CI so a failure found once replays every run).

**Reproducing a CI failure:** export the printed base seed and the same `CV_ROUNDTRIP_EXAMPLES` /
`CV_ROUNDTRIP_WORKERS`; Hypothesis also prints a `@reproduce_failure` blob for the shrunk example.

## Golden drift (a human decision)

A change that alters any corpus hash fails `test_corpus_rule_is_hash_stable_both_directions`. If the
change is intended (e.g. an `IR_HASH_VERSION` bump with an upcaster), regenerate with a written reason:

```bash
uv run python -m tests.rules.roundtrip.update_goldens --reason "<why the hash legitimately changed>"
```

The reason is stored in `golden_hashes.json` (a test asserts it is non-empty) and **must be copied into
the PR body**; reviewers reject golden updates without it.

## Corpus

30 rules: the eight built-in system rules (§11.8), the ADR-0007 worked examples (breakeven after 1R,
ATR trailing, cancel-if-spread-too-wide, daily-loss lockout) and templates-gallery style rules. Every
corpus rule passes the semantic validator. `test_corpus_covers_the_whole_vocabulary` asserts coverage of
all 13 triggers, all 15 comparison operators, all four boolean and four temporal ops, nested arithmetic,
a shared sub-expression, all 25 action types and all five scope levels. Public perpetual symbols only;
no real account ids or credentials.

## Defects found while building the suite (fixed in the same PR)

1. **Graph hop reordered actions** — `compile_graph` emitted actions in node-id sort order, so ids like
   `a10`/`a2` (or `b`/`a`) swapped execution order and changed the hash. Severity P1 (action order is
   semantic under `on_error=abort_remaining`). Layer that should have caught it: compiler unit tests.
   Regression: `test_action_order_survives_the_graph_hop_with_unsorted_ids`.
2. **Form hop dropped the presentation block** — `to_form_model` popped `graph_layout`. Severity P3
   (presentation only, hash unaffected). Regression: `test_presentation_block_survives_form_and_graph_hops`.
3. **Unnamed lossy-hop error** — `to_form_model` raised a bare `ValueError`; now
   `FormUnrepresentableError` (still a `ValueError` subclass for existing callers).

## Results (local run, 2026-10-04)

| Scenario | Result |
|---|---|
| Ten thousand generated documents round-trip | PASS — 10 000 documents, 8 workers, ≈118 s |
| The thirty-rule corpus is hash-stable both directions | PASS — 30/30, ≈3 s |
| A lossy hop fails loudly | PASS |
| A canonicalisation defect is caught | PASS — caught and shrunk in ≈5 s |
| Golden drift requires a human decision | PASS (gate + reason check) |
