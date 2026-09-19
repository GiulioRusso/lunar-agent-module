"""AGC double-precision numbers and B-scaling.

A DP value is a signed 28-bit fraction held in two 15-bit words, both in ones' complement:
the high word carries the sign and the top 14 magnitude bits, the low word the bottom 14,
and a negative number is the bitwise NOT of *both* words. Physical quantities are stored as
fractions of a full scale: "X B-n" means the stored fraction is X / 2**n. Examples used by
the state vector (Luminary's ORBITAL_INTEGRATION.agc): lunar-sphere position metres B-27,
velocity metres/centisecond B-5, time centiseconds B-28.

Validated against constants the assembler itself encoded (tests/unit/test_scaling.py), taken
from a real yaYUL listing -- not against the author's memory of the format.
"""

from __future__ import annotations

WORD_MASK = 0o77777
_HALF = 0o40000  # ones' complement sign bit of a 15-bit word
_DP_SCALE = 1 << 28


def dp_encode(fraction: float) -> tuple[int, int]:
    """Encode a fraction in [-1, 1) as (high, low) AGC words."""
    magnitude = round(abs(fraction) * _DP_SCALE)
    if magnitude >= _DP_SCALE:
        raise OverflowError(f"fraction {fraction} does not fit a 28-bit DP word")
    high, low = magnitude >> 14, magnitude & 0x3FFF
    if fraction < 0:
        high, low = WORD_MASK ^ high, WORD_MASK ^ low
    return high, low


def dp_decode(high: int, low: int) -> float:
    """Decode (high, low) AGC words to a fraction."""
    negative = high >= _HALF
    if negative:
        high, low = WORD_MASK ^ high, WORD_MASK ^ low
    return (-1 if negative else 1) * ((high << 14) + low) / _DP_SCALE


def to_fraction(value: float, b: int) -> float:
    """Physical value -> stored fraction for a quantity scaled B<b> (value / 2**b)."""
    return value / 2.0**b


def from_fraction(fraction: float, b: int) -> float:
    return fraction * 2.0**b


def dp_from_value(value: float, b: int) -> tuple[int, int]:
    return dp_encode(to_fraction(value, b))


def dp_to_value(high: int, low: int, b: int) -> float:
    return from_fraction(dp_decode(high, low), b)
