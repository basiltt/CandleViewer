"""E40-T02 property: no IR tree containing an action node ever compiles (hypothesis fuzz).

Strategy: generate a *valid* condition tree, then graft an action node (any E35 action type,
optionally under a look-alike key) at a random position - root key, inside `variables`, as an
operand, as a logical child, under metric params. The compiler must refuse every one.
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.alerts.compiler import ACTION_TYPES, AlertCompiler
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.rules.vocabulary import default_registry

COMPILER = AlertCompiler(default_registry())
_METRICS = ["price", "spread_bps", "delta", "cvd"]

operands = st.recursive(
    st.one_of(
        st.builds(lambda m: {"metric": m}, st.sampled_from(_METRICS)),
        st.builds(lambda c: {"const": c}, st.integers(-(10**6), 10**6)),
    ),
    lambda inner: st.builds(
        lambda op, ops: {"node_id": "x", "op": op, "operands": ops},
        st.sampled_from(["add", "sub", "max", "min"]),
        st.lists(inner, min_size=1, max_size=3),
    ),
    max_leaves=6,
)
comparisons = st.builds(
    lambda op, left, right: {"node_id": "c", "op": op, "left": left, "right": right},
    st.sampled_from(["gt", "gte", "lt", "lte"]),
    operands,
    operands,
)
conditions = st.recursive(
    comparisons,
    lambda inner: st.one_of(
        st.builds(
            lambda op, ch: {"node_id": "b", "op": op, "children": ch},
            st.sampled_from(["all_of", "any_of"]),
            st.lists(inner, min_size=1, max_size=3),
        ),
        st.builds(
            lambda ch: {"node_id": "t", "op": "sustained_for", "child": ch, "window_ms": 1000},
            inner,
        ),
    ),
    max_leaves=6,
)
actions = st.builds(
    lambda t, nid: {"node_id": nid, "type": t, "params": {"side": "buy"}},
    st.sampled_from(sorted(ACTION_TYPES)),
    st.sampled_from(["a1", "act", "c"]),
)
action_keys = st.sampled_from(["actions", "Actions", "\u0430ctions", "then", "action", "do"])


def _graft(cond: dict[str, Any], act: dict[str, Any], where: int, key: str) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "ir_version": 1,
        "trigger": {"type": "on_price_update"},
        "conditions": cond,
    }
    if where == 0:
        doc[key] = [act]
    elif where == 1:
        doc["variables"] = {"v": act}
    elif where == 2:
        doc["conditions"] = {"node_id": "g", "op": "any_of", "children": [cond, act]}
    elif where == 3:
        doc["conditions"] = {"node_id": "g", "op": "gt", "left": act, "right": {"const": 1}}
    elif where == 4:
        doc["conditions"] = {
            "node_id": "g",
            "op": "gt",
            "left": {"metric": "price", "params": {key: act}},
            "right": {"const": 1},
        }
    else:
        doc["trigger"] = {"type": "on_price_update", key: act}
    return doc


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(conditions, actions, st.integers(0, 5), action_keys)
def test_no_tree_containing_an_action_node_ever_compiles(
    cond: dict[str, Any], act: dict[str, Any], where: int, key: str
) -> None:
    doc = _graft(cond, act, where, key)
    try:
        COMPILER.compile(doc)
    except AlertIrInvalid as exc:
        assert exc.reason in ("action_node", "too_large")
    else:  # pragma: no cover - this branch is the bug the property hunts for
        raise AssertionError(f"action-bearing IR compiled: {doc!r}")


@settings(max_examples=200, deadline=None)
@given(conditions)
def test_generated_action_free_trees_pass_the_structural_walk(cond: dict[str, Any]) -> None:
    doc = {"ir_version": 1, "trigger": {"type": "on_price_update"}, "conditions": cond}
    try:
        COMPILER.compile(doc)
    except AlertIrInvalid as exc:  # semantic (units) refusals are fine; structural ones are not
        assert exc.reason not in ("action_node", "too_large"), exc.issues
