"""E35-Q02: a hop that cannot represent a document fails loudly; presentation survives hops."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.rules.compiler import to_form_model, to_graph_model
from candleviewer.rules.errors import FormUnrepresentableError
from candleviewer.rules.ir import Rule, ir_hash, parse_ir_json
from tests.rules.roundtrip.chain import HopMismatch, full_chain, to_form, to_node

CORPUS = Path(__file__).parents[2] / "fixtures/rule_corpus"
GRAPH_ONLY = {
    "28_shared_atr_band.json": "fans out",
    "21_chase_limit_on_imbalance.json": "n_of",
    "09_atr_trailing_stop.json": "arithmetic",
    "22_iceberg_accumulation.json": "occurred_within",
}


def _load(name: str) -> Rule:
    return parse_ir_json((CORPUS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(("name", "construct"), sorted(GRAPH_ONLY.items()))
def test_lossy_hop_form_hop_raises_named_unrepresentable_error(name: str, construct: str) -> None:
    """Scenario: A lossy hop fails loudly."""
    ir = _load(name)
    with pytest.raises(FormUnrepresentableError) as exc:
        to_form_model(ir)
    assert any(construct in r for r in exc.value.reasons)
    assert isinstance(exc.value, ValueError)  # back-compatible with existing callers


def test_lossy_hop_graph_hop_still_round_trips_graph_only_rules() -> None:
    for name in GRAPH_ONLY:
        ir = _load(name)
        assert ir_hash(to_node(ir)) == ir_hash(ir)
        assert full_chain(ir) == ir_hash(ir)


def test_lossy_hop_chain_rejects_a_form_hop_that_silently_drops_a_construct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the form decompiler ever returned a document for a graph-only rule, the chain fails."""
    import tests.rules.roundtrip.chain as chain

    monkeypatch.setattr(chain, "to_form_model", lambda ir: {"lossy": True})
    with pytest.raises(HopMismatch, match="emitted a document"):
        full_chain(_load("21_chase_limit_on_imbalance.json"))


def test_presentation_block_survives_form_and_graph_hops() -> None:
    layout = {"positions": {"c1": {"x": 10, "y": 20}}, "zoom": 2}
    ir = _load("05_sys_stale_feed_block.json").model_copy(update={"graph_layout": layout})
    assert to_form(ir).graph_layout == layout
    assert to_node(ir).graph_layout == layout
    assert to_graph_model(ir)["graph_layout"] == layout


def test_presentation_change_is_detected_by_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    import tests.rules.roundtrip.chain as chain

    real = chain.to_form

    def dropping(ir: Rule) -> Rule:
        return real(ir).model_copy(update={"graph_layout": None})

    monkeypatch.setattr(chain, "to_form", dropping)
    ir = _load("05_sys_stale_feed_block.json").model_copy(update={"graph_layout": {"zoom": 1}})
    with pytest.raises(HopMismatch, match="presentation"):
        full_chain(ir)


def test_action_order_survives_the_graph_hop_with_unsorted_ids() -> None:
    """Regression (found by E35-Q02): ids a10 < a2 used to reorder actions across the graph hop."""
    ir = _load("02_sys_daily_loss_lockout.json")
    acts = tuple(
        a.model_copy(update={"node_id": nid})
        for a, nid in zip(ir.actions, ("a2", "a10"), strict=True)
    )
    ir = ir.model_copy(update={"actions": acts})
    assert [a.type for a in to_node(ir).actions] == [a.type for a in ir.actions]
    assert ir_hash(to_node(ir)) == ir_hash(ir)
