"""E12-T04 golden comparison: recorded fixture day, every builder kind, byte-for-byte (BI-4).

Two checks per golden spec, both reporting through the plain-text comparator
(`bar <i> field <f>: expected <x> actual <y>`):
1. production builder vs the independent reference implementation, every field;
2. production builder vs the committed golden file (`packages/fixtures/golden/bars/determinism/`).
Goldens are never regenerated here; see `bench/bar_determinism/regen_goldens.py`.
"""

from __future__ import annotations

import json

import pytest

from bench.bar_determinism import comparator, goldens, invariants, reference
from bench.bar_determinism.generator import TICK
from candleviewer.bars.rows import BUILD_VERSIONS
from candleviewer.exchange.base.models import TradeEvent

_TAPE: list[TradeEvent] = []


def tape() -> list[TradeEvent]:
    if not _TAPE:
        _TAPE.extend(goldens.load_tape())
    return _TAPE


@pytest.mark.parametrize("label", list(goldens.GOLDEN_SPECS))
def test_golden_day_matches_reference_byte_for_byte(label: str) -> None:
    spec = goldens.GOLDEN_SPECS[label]
    got = invariants.run(invariants.make_builder, spec, tape())
    want = reference.build(spec, "BTCUSDT", tape(), TICK).bars
    assert got, label
    diffs = comparator.compare(want, got)
    assert not diffs, f"{label} vs reference:\n{comparator.render(diffs)}"


@pytest.mark.parametrize("label", list(goldens.GOLDEN_SPECS))
def test_golden_day_matches_committed_golden_file(label: str) -> None:
    got = goldens.render(goldens.GOLDEN_SPECS[label], tape())
    diffs = comparator.compare_lines(goldens.read(label), got)
    assert not diffs, f"{goldens.path(label).name}:\n{comparator.render(diffs)}"


@pytest.mark.parametrize("label", list(goldens.GOLDEN_SPECS))
def test_golden_day_satisfies_every_invariant(label: str) -> None:
    v = invariants.check(label, goldens.GOLDEN_SPECS[label], tape(), seed=0, cuts=5)
    assert not v, invariants.report(v)


def test_golden_manifest_pins_fixture_build_versions_and_spec_hashes() -> None:
    m = goldens.load_manifest()
    assert m["fixture_sha256"] == goldens.fixture_sha256(), "the fixture day changed"
    assert m["build_versions"] == BUILD_VERSIONS, (
        "BUILD_VERSIONS moved without regenerating the goldens in the same commit"
    )
    assert m["specs"] == {k: s.spec_hash for k, s in goldens.GOLDEN_SPECS.items()}
    assert str(m["reason"]).strip()
    assert sorted(p.stem for p in goldens.GOLDEN_DIR.glob("*.jsonl")) == sorted(
        goldens.GOLDEN_SPECS
    )


def test_fixture_day_is_public_market_data_only() -> None:
    """Security note: no auth/private frames, keys, signatures or account identifiers."""
    raw = goldens.FIXTURE.read_text(encoding="utf-8")
    for frame in raw.splitlines():
        doc = json.loads(frame)
        assert set(doc) <= {"topic", "type", "ts", "data"}
        assert doc["topic"].startswith("publicTrade.")
        for rec in doc["data"]:
            assert set(rec) <= {"T", "s", "S", "v", "p", "L", "i", "BT"}
    for needle in ("auth", "apiKey", "api_key", "sign", "uid", "userId", "accountId", "order"):
        assert needle not in raw


def test_regen_refuses_under_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.bar_determinism import regen_goldens

    monkeypatch.setenv("CI", "true")
    assert regen_goldens.main(["--write", "--reason", "x"]) == 2


def test_regen_is_a_no_op_when_goldens_are_current(monkeypatch: pytest.MonkeyPatch) -> None:
    from bench.bar_determinism import regen_goldens

    monkeypatch.delenv("CI", raising=False)
    assert regen_goldens.main([]) == 0


def test_regen_refuses_changed_output_without_build_version_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bench.bar_determinism import regen_goldens

    monkeypatch.delenv("CI", raising=False)
    real = goldens.render
    monkeypatch.setattr(goldens, "render", lambda s, t: real(s, t)[:-1])  # "changed output"
    monkeypatch.setattr(goldens, "write", lambda *_a: pytest.fail("must not write"))
    assert regen_goldens.main(["--write", "--reason", "legit change"]) == 2
    assert regen_goldens.main([]) == 1  # dry run reports the change, writes nothing
