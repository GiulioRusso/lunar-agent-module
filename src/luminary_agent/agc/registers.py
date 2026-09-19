"""Counter-register increments: how the plant's IMU model (PIPA/CDU pulses) actually
reaches the AGC.

Ground truth: external/virtualagc/yaAGC/agc_engine.h (the Reg* constants) and
agc_engine.c:UnprogrammedIncrement/SocketAPI.c:ChannelInput. A counter increment is a
channel write like any other, but with bit 0x80 of the channel number set and the
register number in the low 7 bits; the packet's "value" field is then not a channel
value but an IncType selecting the operation:
    PINC (0) / MINC (2)  -- 1's-complement +1/-1, used by PIPA registers
    PCDU (1) / MCDU (3)  -- 2's-complement +1/-1, used by CDU registers (rate-limited by
                             yaAGC's internal FIFO to model real CDU bandwidth limits)
ChannelInput masks the register back down with `Counter &= 0x7f` before dispatching, so
the 0x80 bit is purely a marker, not part of the register number.
"""

from __future__ import annotations

from luminary_agent.agc.channels import encode_packet

REG_CDUX = 0o32
REG_CDUY = 0o33
REG_CDUZ = 0o34
REG_PIPAX = 0o37
REG_PIPAY = 0o40
REG_PIPAZ = 0o41

PINC = 0
PCDU = 1
MINC = 2
MCDU = 3
# Fast CDU increments (agc_engine.c:PushCduFifo): the same operations, drained from yaAGC's CDU
# FIFO at 6400 pulses/s instead of 400. Same-direction runs are stored as one FIFO entry, so a
# long slew cannot overflow it; only direction changes consume entries.
PCDU_FAST = 0o21
MCDU_FAST = 0o23

COUNTER_CHANNEL_BIT = 0x80


def counter_increment_packet(register: int, inc_type: int) -> bytes:
    """One counter-increment packet: channel = 0x80 | register, value = IncType."""
    return encode_packet(COUNTER_CHANNEL_BIT | register, inc_type)


def counter_increment_packets(
    register: int, pulse_count: int, positive_inc: int, negative_inc: int
) -> list[bytes]:
    """`pulse_count` single-pulse packets (sign picks PINC/MINC or PCDU/MCDU)."""
    inc_type = positive_inc if pulse_count >= 0 else negative_inc
    return [counter_increment_packet(register, inc_type) for _ in range(abs(pulse_count))]


def pipa_pulse_packets(register: int, pulse_count: int) -> list[bytes]:
    return counter_increment_packets(register, pulse_count, PINC, MINC)


def cdu_pulse_packets(register: int, pulse_count: int, fast: bool = False) -> list[bytes]:
    if fast:
        return counter_increment_packets(register, pulse_count, PCDU_FAST, MCDU_FAST)
    return counter_increment_packets(register, pulse_count, PCDU, MCDU)
