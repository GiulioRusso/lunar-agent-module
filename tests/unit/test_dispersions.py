from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.scenarios.dispersions import FAULT_WINDOW_S, Dispersion, sample


def test_sample_is_deterministic_and_seed_dependent() -> None:
    assert sample(3, 2) == sample(3, 2)
    assert sample(3, 2) != sample(4, 2)


def test_tiers_bound_the_dispersion() -> None:
    for seed in range(50):
        d = sample(seed, 1)
        assert abs(d.thrust_scale - 1) <= 0.005 and d.dh0_m == 0.0
        assert abs(sample(seed, 3).dh0_m) <= 100.0


def test_apply_and_engine() -> None:
    d = Dispersion(thrust_scale=0.9, mass_scale=1.1, dh0_m=50.0, dvt0_ms=1.0, dvh0_ms=-1.0)
    s = d.apply(PlanarState(1000.0, 5.0, 2.0, 30.0, 100.0))
    assert (s.h_m, s.hdot_ms, s.xdot_ms) == (1050.0, 1.0, 31.0)
    assert abs(s.mass_kg - 110.0) < 1e-9
    assert abs(d.engine().f_max_n / DescentEngine().f_max_n - 0.9) < 1e-12


def test_propellant_shortfall_only_reduces_and_sets_dry_mass() -> None:
    for seed in range(50):
        d = sample(seed, 3)
        assert 0.84 <= d.propellant_scale <= 1.0
    assert Dispersion().dry_mass_kg == 6_800.0


def test_the_in_flight_thrust_fault_is_tiered_bounded_and_inside_the_approach() -> None:
    assert all(sample(seed, 1).thrust_fault_at_s == 0.0 for seed in range(50))
    for seed in range(50):
        for tier, worst in ((2, 0.94), (3, 0.85)):
            d = sample(seed, tier)
            assert FAULT_WINDOW_S[0] <= d.thrust_fault_at_s <= FAULT_WINDOW_S[1]
            assert worst <= d.thrust_fault_scale <= 1.0


def test_a_faulted_engine_loses_exactly_the_drawn_thrust() -> None:
    d = Dispersion(thrust_scale=0.98, thrust_fault_scale=0.9)
    assert abs(d.engine(faulted=True).f_max_n / d.engine().f_max_n - 0.9) < 1e-12
