"""THROWAWAY spike tests. Scenario names mirror E35-K01 acceptance criteria."""
from __future__ import annotations

import json
import time
from typing import Any

import canon
import corpus
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------- generator strategy (bounded by JSON-schema limits) ----------
ids = st.integers(1, 10_000).map(lambda i: f"n{i}")
nums = st.one_of(
    st.integers(-10**6, 10**6).map(str),
    st.decimals(min_value=-10**6, max_value=10**6, places=6, allow_nan=False).map(str),
)
leaf = st.builds(lambda i, v: {"node_id": i, "type": "compare", "op": ">",
                               "left": {"metric": "price"}, "right": {"const": v}}, ids, nums)
cond = st.recursive(leaf, lambda c: st.builds(
    lambda i, t, ch: {"node_id": i, "type": t, "children": ch}, ids,
    st.sampled_from(["all_of", "any_of"]), st.lists(c, min_size=1, max_size=4)), max_leaves=32)
actions = st.lists(st.builds(lambda i: {"node_id": i, "type": "notify", "channel": "ui"}, ids),
                   min_size=1, max_size=10)
layout = st.dictionaries(ids, st.fixed_dictionaries({"x": st.integers(), "y": st.integers()}),
                         max_size=5)
docs = st.builds(lambda c, a, lay: {"schema_version": 1, "condition": c, "actions": a,
                                    "limits": {"max_fires": 1},
                                    "presentation": {"graph_layout": lay}}, cond, actions, layout)


def shuffle_keys(o: Any, rnd: Any) -> Any:
    if isinstance(o, dict):
        ks = list(o)
        rnd.shuffle(ks)
        return {k: shuffle_keys(o[k], rnd) for k in ks}
    if isinstance(o, list):
        return [shuffle_keys(v, rnd) for v in o]
    return o


def roundtrip(d: Any, rnd: Any) -> Any:
    return canon.parse_ir(json.dumps(shuffle_keys(d, rnd), indent=rnd.choice([None, 2])))


S = dict(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@settings(**S)
@given(docs, st.randoms(use_true_random=False))
def test_reserialisation_and_key_order_stable(d: Any, rnd: Any) -> None:
    assert canon.ir_hash(d) == canon.ir_hash(roundtrip(d, rnd))


@settings(**S)
@given(docs, layout)
def test_presentation_excluded(d: Any, lay: Any) -> None:
    e = json.loads(json.dumps(d))
    e["presentation"] = {"graph_layout": lay, "editor": "graph"}
    assert canon.ir_hash(d) == canon.ir_hash(e)


@settings(**S)
@given(docs)
def test_idempotent_on_canonical_bytes(d: Any) -> None:
    once = canon.canon_jcs_decstr(d)
    assert canon.canon_jcs_decstr(canon.parse_ir(once.decode())) == once


# ---------- acceptance scenarios ----------
def test_scenario_number_normalisation_is_unambiguous() -> None:
    a = canon.parse_ir('{"v": 1.50, "w": 1e3, "z": -0.0, "q": 10E-1}')
    b = canon.parse_ir('{"w": 1000, "v": 1.5, "z": 0, "q": 1}')
    for s in canon.STRATEGIES:
        if s == "jcs_float":
            continue  # float strategy is shown lossy below
        assert canon.ir_hash(a, s) == canon.ir_hash(b, s)
    assert canon.dec_str(canon.parse_ir("1E+3")) == "1000"


def test_jcs_float_loses_decimal_fidelity() -> None:
    x = canon.parse_ir('{"p": 0.1000000000000000055511151231257827}')
    y = canon.parse_ir('{"p": 0.1}')
    assert canon.ir_hash(x, "jcs_float") == canon.ir_hash(y, "jcs_float")  # collision!
    assert canon.ir_hash(x, "jcs_decstr") != canon.ir_hash(y, "jcs_decstr")


def test_corpus_all_strategies_stable() -> None:
    c = corpus.corpus()
    assert len(c) >= 20
    for name, text in c:
        base = canon.parse_ir(text)
        shuffled = canon.parse_ir(json.dumps(dict(reversed(list(json.loads(text).items())))))
        for s in canon.STRATEGIES:
            assert canon.ir_hash(base, s) == canon.ir_hash(shuffled, s), (name, s)


def test_scenario_node_ref_traceability_renumbering_is_unsafe() -> None:
    """Insert a node at the front: DFS renumbering shifts every later id, so a stored node_ref
    would point at a different node. Author-assigned ids (excluded from nothing, only hashed
    via renumbered view) keep stable references in the *stored* IR."""
    v1 = {"condition": {"node_id": "A", "children": [{"node_id": "B"}, {"node_id": "C"}]}}
    v2 = {"condition": {"node_id": "A", "children": [{"node_id": "NEW"}, {"node_id": "B"},
                                                      {"node_id": "C"}]}}
    m1, m2 = canon.renumber(v1), canon.renumber(v2)
    assert m1["condition"]["children"][0]["node_id"] == m2["condition"]["children"][0]["node_id"]
    # n2 meant B in v1 but means NEW in v2 -> renumbered ids are NOT a safe node_ref
    assert v1["condition"]["children"][0]["node_id"] == "B"
    # B is n2 in v1 but n3 in v2; n3 meant C in v1 -> a stored renumbered ref mis-highlights
    assert m1["condition"]["children"][0]["node_id"] == "n2"  # B in v1
    assert m2["condition"]["children"][1]["node_id"] == "n3"  # B in v2
    assert m1["condition"]["children"][1]["node_id"] == "n3"  # C in v1


def test_scenario_isomorphic_author_ids_hash_equal() -> None:
    a = {"condition": {"node_id": "x", "children": [{"node_id": "y"}]}}
    b = {"condition": {"node_id": "p", "children": [{"node_id": "q"}]}}
    assert canon.ir_hash(a) == canon.ir_hash(b)


def test_scenario_generator_catches_unsorted_keys_bug_fast() -> None:
    """Mutation: canonicaliser that forgets sort_keys. Property suite must fail and shrink < 60 s."""
    def broken(d: Any) -> str:
        import hashlib
        return hashlib.sha256(canon.canon_jcs_decstr(d, sort_keys=False)).hexdigest()

    failure: dict[str, Any] = {}

    @settings(max_examples=300, deadline=None, database=None,
              suppress_health_check=list(HealthCheck))
    @given(docs, st.randoms(use_true_random=False))
    def prop(d: Any, rnd: Any) -> None:
        try:
            assert broken(d) == broken(roundtrip(d, rnd))
        except AssertionError:
            failure["doc"] = d
            raise

    t = time.perf_counter()
    raised = False
    try:
        prop()
    except AssertionError:
        raised = True
    assert raised, "mutated canonicaliser was NOT detected"
    assert time.perf_counter() - t < 60
    # shrunk example is small
    assert len(json.dumps(failure["doc"])) < 1500
    print("shrunk:", json.dumps(failure["doc"]))
