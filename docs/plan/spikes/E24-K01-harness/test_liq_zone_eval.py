import liq_zone_eval as e


def test_evaluate_is_deterministic() -> None:
    days = [e.make_day("x", 1, False), e.make_day("y", 3, True)]
    assert e.evaluate(days) == e.evaluate(days)


def test_zones_a_symmetric_around_reference() -> None:
    d = e.make_day("x", 1, False)
    z = sorted(e.zones_a(d))
    assert len(z) == 2 * len(e.TIERS)
    assert abs((z[0] + z[-1]) / 2 - d.ref) < 1e-6


def test_rates_complement() -> None:
    r = e.evaluate([e.make_day("x", 2, False)])
    for v in r.values():
        assert abs(v["hit_rate"] + v["false_positive_rate"] - 1) < 1e-3


def test_cost_b_reports_chosen_method() -> None:
    c = e.cost_ms_b(e.make_day("x", 1, False), reps=2)
    assert c["events"] > 0 and c["full_recompute_ms"] > 0
