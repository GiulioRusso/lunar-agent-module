from luminary_agent.plant.radar import Radar
from luminary_agent.scenarios.dispersions import sample


def test_dropout_band_and_determinism() -> None:
    r = Radar(dropout_hi_m=300.0, dropout_lo_m=150.0, seed=1)
    assert r.altitude(200.0, 10.0) is None
    assert r.altitude(500.0, 10.0) == r.altitude(500.0, 10.0)
    assert abs(r.altitude(500.0, 10.0) - 500.0) < 30.0  # type: ignore[operator]


def test_bias_shifts_the_reading() -> None:
    r = Radar(bias_frac=0.05, noise_frac=0.0, noise_m=0.0)
    assert abs((r.altitude(1000.0, 0.0) or 0.0) - 1050.0) < 1e-9


def test_only_tier_3_has_a_dead_band_and_other_draws_unchanged() -> None:
    assert sample(0, 2).radar.dropout_hi_m == 0.0
    d = sample(0, 3).radar
    assert 250.0 <= d.dropout_hi_m <= 400.0 and d.dropout_lo_m < d.dropout_hi_m
    assert abs(sample(0, 3).thrust_scale - 1.0) <= 0.03  # unchanged stream


def test_dispersion_serialises_to_json() -> None:
    import json
    from dataclasses import asdict

    assert json.loads(json.dumps(asdict(sample(3, 3))))["radar"]["seed"] == 3
