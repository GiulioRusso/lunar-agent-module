"""Unit tests for agc/registers.py: counter-increment packets (channel 0x80 | register, value =
increment type), one packet per pulse, sign selecting PINC/MINC or PCDU/MCDU.

Run alone: `uv run pytest tests/unit/test_registers.py -v`.
"""

from luminary_agent.agc.channels import decode_packet
from luminary_agent.agc.registers import (
    MCDU,
    MINC,
    PCDU,
    PINC,
    REG_PIPAX,
    cdu_pulse_packets,
    counter_increment_packet,
    pipa_pulse_packets,
)


def test_counter_increment_packet_sets_0x80_bit_and_masks_register() -> None:
    packet = counter_increment_packet(REG_PIPAX, PINC)
    channel, value, u_bit = decode_packet(packet)
    assert channel == 0x80 | REG_PIPAX
    assert value == PINC
    assert u_bit is False


def test_pipa_pulse_packets_positive_uses_pinc() -> None:
    packets = pipa_pulse_packets(REG_PIPAX, 3)
    assert len(packets) == 3
    for p in packets:
        channel, value, _ = decode_packet(p)
        assert channel == 0x80 | REG_PIPAX
        assert value == PINC


def test_pipa_pulse_packets_negative_uses_minc() -> None:
    packets = pipa_pulse_packets(REG_PIPAX, -2)
    assert len(packets) == 2
    for p in packets:
        _, value, _ = decode_packet(p)
        assert value == MINC


def test_pipa_pulse_packets_zero_sends_nothing() -> None:
    assert pipa_pulse_packets(REG_PIPAX, 0) == []


def test_cdu_pulse_packets_use_pcdu_mcdu_not_pinc_minc() -> None:
    pos = cdu_pulse_packets(REG_PIPAX, 1)
    neg = cdu_pulse_packets(REG_PIPAX, -1)
    assert decode_packet(pos[0])[1] == PCDU
    assert decode_packet(neg[0])[1] == MCDU
