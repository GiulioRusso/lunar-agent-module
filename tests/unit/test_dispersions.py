from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.scenarios.dispersions import Dispersion, sample


def test_sample_is_deterministic_and_seed_dependent() -> None:
    assert sample(3, 2) == sample(3, 2)
    assert sample(3, 2) != sample(4, 2)


def test_tiers_bound_the_dispersion() -> None:
    for seed in range(50):
        d = sample(seed, 1)
        assert abs(d.thrust_scale - 1) <= 0.005 and d.dh0_m == 0.0
        assert abs(sample(seed, 3).dh0_m) <= 30.0


def test_apply_and_engine() -> None:
    d = Dispersion(thrust_scale=0.9, mass_scale=1.1, dh0_m=50.0, dvt0_ms=1.0, dvh0_ms=-1.0)
    s = d.apply(PlanarState(1000.0, 5.0, 2.0, 30.0, 100.0))
    assert (s.h_m, s.hdot_ms, s.xdot_ms) == (1050.0, 1.0, 31.0)
    assert abs(s.mass_kg - 110.0) < 1e-9
    assert abs(d.engine().f_max_n / DescentEngine().f_max_n - 0.9) < 1e-12


def test_propellant_shortfall_only_reduces_and_sets_dry_mass() -> None:
    for seed in range(50):
        d = sample(seed, 3)
        assert 0.91 <= d.propellant_scale <= 1.0
    assert Dispersion().dry_mass_kg == 6_800.0
