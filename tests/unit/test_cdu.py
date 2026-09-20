import math

from luminary_agent.agc.cdu import COUNTS_PER_REV
from luminary_agent.agc.channels import decode_packet
from luminary_agent.agc.registers import MCDU_FAST, PCDU_FAST, REG_CDUX, cdu_pulse_packets
from luminary_agent.plant.sensors import CDU_SCALE_RAD


def test_full_revolution_is_2_to_the_15_counts() -> None:
    assert COUNTS_PER_REV == 32768


def test_scale_agrees_with_the_imu_models_cdu_pulse_size() -> None:
    assert math.isclose(math.radians(360.0 / COUNTS_PER_REV), CDU_SCALE_RAD)


def test_the_thetad_seen_on_a_live_agc_is_the_displayed_pitch() -> None:
    # THETAD = (-47, 9792, 35); the DSKY (V50 N18) showed pitch 107.57 deg for the middle one.
    assert math.isclose(9792 * 360.0 / COUNTS_PER_REV, 107.57, abs_tol=0.02)


def test_fast_cdu_pulses_use_the_fast_increment_types() -> None:
    (pos,) = cdu_pulse_packets(REG_CDUX, 1, fast=True)
    (neg,) = cdu_pulse_packets(REG_CDUX, -1, fast=True)
    assert decode_packet(pos)[1] == PCDU_FAST == 0o21
    assert decode_packet(neg)[1] == MCDU_FAST == 0o23
