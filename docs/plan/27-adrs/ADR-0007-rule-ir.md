# ADR-0007 — A single rule IR shared by the form editor and the node-graph editor

- Status: **decided**
- Date: 2026-09-14
- Deciders: Owner (decision #11), Architect, Backend lead, Product designer (rules)
- Consulted: `docs/research/09-execution-risk-tools.md` §4, §6b, §7, `docs/research/23-views-and-screens.md` view 16, `docs/research/22-architecture-options.md` §6
- Related: `docs/plan/24-internal-schemas.md`, ADR-0006

## Context and problem statement

The owner requires **both** a form/condition-list editor and a visual node-graph editor in v1, and rules must round-trip between them. Two editors naturally tempt two representations, which would guarantee divergence: a rule built in the graph would behave differently from the "same" rule built in the form, and the engine would have to implement two evaluators.

## Decision drivers

- Round-trip fidelity is an owner requirement, not a nice-to-have.
- Rules place and modify real orders; their semantics must be exactly specified and testable.
- Rules must be versioned, auditable and replayable against recorded history (auto-backtest on save).
- The metric vocabulary spans plain series (`atr`, `ema`, `swing_high`) and order-flow heuristics (`iceberg_present_at_level`, `in_stop_hunt_zone`, `tape_speed_zscore`) that carry an `estimated` flag.

## Considered options

1. **One canonical IR; both editors are compilers to it and decompilers from it.**
2. **Two native formats with a converter between them.**
3. **A scripting language (Python/Lua sandbox) as the canonical form**, with the editors generating script.

## Decision outcome

**Chosen: option 1.**

The IR is a typed, versioned, side-effect-free expression tree, fully specified in `24-internal-schemas.md`. Shape:

```
RuleIR {
  id, version, name, enabled, mode: armed | simulate,
  scope   { symbols[], accounts[], applies_to: open_positions | pending_orders | account },
  trigger { type: on_price_update | on_bar_close | on_order_fill | on_timer | on_indicator,
            timeframe?, debounce_ms },
  condition: Expr,              // tree of And/Or/Not/Compare/Arith/MetricRef/Literal
  actions: Action[],            // ordered, each with once / cooldown_s / only_tighten flags
  limits  { max_fires_per_minute, max_fires_per_day, cooldown_s },
  meta    { created_by, created_at, source_editor, layout? }   // layout = graph node positions
}
```

Binding rules:

1. **`condition` is pure.** Evaluation has no side effects and no ordering dependence; all effects live in `actions`. This makes evaluation testable and safely re-runnable in simulate mode.
2. **Every metric is typed and unit-tagged** in the `MetricRegistry` (price / ratio / percent / duration / count / enum), and the compiler rejects unit-incoherent comparisons (`atr(14) > 5 %` is a compile error unless an explicit conversion is present).
3. **The graph editor's visual layout lives in `meta.layout`** and is ignored by the evaluator. A rule authored in the form editor and opened in the graph editor gets an auto-layout; a rule authored in the graph and opened in the form renders as a nested condition list. Round-trip is therefore **semantically lossless** and cosmetically best-effort — this is the explicit contract shown to users.
4. **Graphs must be acyclic and must reduce to a single boolean condition plus an ordered action list.** The node editor is a visual syntax for the same IR, not a dataflow engine; cycles and multiple sinks are compile errors with a clear message.
5. **Rules are immutable once saved**; editing creates a new `version`. Audit records reference `(rule_id, version)` so a firing can always be explained against the exact logic that ran.
6. **Stale metrics suspend evaluation.** If any metric required by a condition is stale (its feed is disconnected), the rule does not fire and the suspension is recorded — silence is safer than acting on stale data.
7. **Safety clamps are in the IR, not the UI.** `only_tighten` on stop modifications is the default; widening a stop requires an explicit `allow_widen: true`, which requires the Owner role and is audited. No rule may remove the native exchange SL (ADR-0008).
8. **Rate limits are per rule**: `max_fires_per_minute` / `max_fires_per_day`; breaching auto-disarms the rule with a critical notification (failure mode F13).

Action vocabulary: `place_order`, `modify_stop_loss`, `modify_take_profit`, `cancel_order`, `move_to_breakeven`, `scale_out`, `scale_in`, `flatten_all_positions`, `halt_new_orders`, `resume_new_orders`, `send_notification`, `log_journal_tag`, `reduce_leverage`, `widen_stop`, `arm_chase_limit`, `start_iceberg_slice`.

### Consequences

Positive:
- One evaluator, one test suite, one audit format — and a guarantee the two editors cannot drift.
- Rules become data: versionable, diffable, exportable, replayable against recorded history for auto-backtest.
- The typed metric registry catches a whole class of user errors at save time rather than at fire time with money on the line.

Negative / risks:
- The node editor cannot expose arbitrary dataflow constructs users may expect from tools like Kryll. Accepted and communicated: the graph is a visual syntax for conditions and actions.
- Layout round-tripping is cosmetic-only. Accepted and stated in the UI.
- IR versioning requires migrations when the vocabulary grows. Mitigated by a `version` field with explicit upcasters and a test that loads every historical fixture rule.

### Why not the alternatives

- **Two native formats with a converter**: converters between two evolving formats are where semantics go to die; every vocabulary addition would need two implementations and a bidirectional mapping.
- **A scripting language**: maximally expressive and the worst fit for this product — sandboxing user code that places real orders is a serious security problem, non-programmers are the target users, and static analysis for safety clamps (`only_tighten`, rate limits) becomes intractable.

## Validation

- Property test: for every rule in the fixture corpus, `to_graph(compile(form)) → compile → IR` equals the original IR, and symmetrically from the graph side.
- Golden tests: each documented example rule (break-even after 1R, ATR trailing, cancel-if-spread-too-wide, daily-loss lockout) evaluated against recorded fixtures produces the expected action plan.
- Safety tests: no compiled rule can produce an action plan that removes a native SL or widens a stop without `allow_widen` plus Owner role.

## Related

- [ADR-0026](ADR-0026-rule-ir-canonicalisation.md) - canonical form, `ir_hash`, `node_id` handling and fuzz strategy (E35-K01).
