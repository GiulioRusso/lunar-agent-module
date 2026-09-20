from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.surface import (
    MOON_RATE_RAD_S,
    horizontal_speed_relative_to_surface,
)
from luminary_agent.sim.manual_control import ManualController


def _land(state: PlanarState) -> PlanarState:
    pilot, engine = ManualController(), DescentEngine()
    for _ in range(int(400 / DT_S)):
        throttle, pitch = pilot.control(state)
        state = step(state, Control(throttle, pitch), engine, DT_S)
        if state.h_m <= 0.0:
            break
    return state


def test_lands_softly_from_fast_high_start() -> None:
    v_surface = MOON_RATE_RAD_S * (R_MOON + 150.0)
    end = _land(PlanarState(150.0, 0.0, -6.0, v_surface + 12.0, 7800.0))
    assert end.h_m <= 0.0
    assert abs(end.hdot_ms) <= 3.0
    assert abs(horizontal_speed_relative_to_surface(end)) <= 1.2
