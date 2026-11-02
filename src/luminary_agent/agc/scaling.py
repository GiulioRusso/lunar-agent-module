"""AGC double-precision numbers and B-scaling.

A DP value is a signed 28-bit fraction held in two 15-bit words, both in ones' complement:
the high word carries the sign and the top 14 magnitude bits, the low word the bottom 14,
and a negative number is the bitwise NOT of *both* words. Physical quantities are stored as
fractions of a full scale: "X B-n" means the stored fraction is X / 2**n. Examples used by
the state vector (Luminary's ORBITAL_INTEGRATION.agc): lunar-sphere position metres B-27,
velocity metres/centisecond B-5, time centiseconds B-28.

Validated against constants the assembler itself encoded (tests/unit/test_scaling.py), taken
from a real yaYUL listing -- not against the author's memory of the format.

Why fractions? The AGC had no floating point. Every number is a fixed-point fraction between
-1 and +1, and the programmer remembers ("B-27") that the real value is fraction * 2**27.
Example: 1000 m of position at B-27 is stored as 1000 / 2**27 = 0.00000745...
    to_fraction(1000, 27) -> 7.45e-6 -> dp_encode -> (high word, low word)
"sp" = single precision (1 word, 14 bits + sign), "dp" = double precision (2 words, 28 + sign).
`^` is XOR: `WORD_MASK ^ x` flips all 15 bits of x (the ones'-complement negation).
"""

from __future__ import annotations

WORD_MASK = 0o77777  # 15 ones
_HALF = 0o40000  # ones' complement sign bit of a 15-bit word
_DP_SCALE = 1 << 28  # a DP fraction has 28 magnitude bits


def sp_encode(fraction: float) -> int:
    """Encode a fraction in [-1, 1) as one AGC word (14 magnitude bits, ones' complement)."""
    magnitude = round(abs(fraction) * (1 << 14))
    if magnitude >= 1 << 14:
        raise OverflowError(f"fraction {fraction} does not fit a single-precision word")
    return WORD_MASK ^ magnitude if fraction < 0 else magnitude


def sp_decode(word: int) -> float:
    """Inverse of sp_encode: one AGC word -> fraction."""
    negative = word >= _HALF
    magnitude = (WORD_MASK ^ word) if negative else word
    return (-1 if negative else 1) * magnitude / (1 << 14)


def sp_from_value(value: float, b: int) -> int:
    """Physical value at scale B<b> -> one AGC word."""
    return sp_encode(to_fraction(value, b))


def sp_to_value(word: int, b: int) -> float:
    """One AGC word at scale B<b> -> physical value."""
    return from_fraction(sp_decode(word), b)


def dp_encode(fraction: float) -> tuple[int, int]:
    """Encode a fraction in [-1, 1) as (high, low) AGC words."""
    magnitude = round(abs(fraction) * _DP_SCALE)
    if magnitude >= _DP_SCALE:
        raise OverflowError(f"fraction {fraction} does not fit a 28-bit DP word")
    # Split 28 bits: top 14 in the high word, bottom 14 (0x3FFF = 14 ones) in the low word.
    high, low = magnitude >> 14, magnitude & 0x3FFF
    if fraction < 0:
        high, low = WORD_MASK ^ high, WORD_MASK ^ low
    return high, low


def _signed(word: int) -> int:
    """One 15-bit ones'-complement word as a signed integer."""
    return word - WORD_MASK if word >= _HALF else word


def dp_decode(high: int, low: int) -> float:
    """Decode (high, low) AGC words to a fraction.

    The value is high * 2**14 + low with each word signed independently. The words of a
    normalised number agree in sign, but the AGC does not keep them that way between
    operations (TPAGREE forces agreement when a program needs it), and a value read out of
    erasable mid-computation can have a positive high word and a negative low word -- as
    Luminary's TIG does: (0o2, 0o77206) is 2*16384 - 377 = 32391, not a huge negative number.
    """
    return (_signed(high) * (1 << 14) + _signed(low)) / _DP_SCALE


def to_fraction(value: float, b: int) -> float:
    """Physical value -> stored fraction for a quantity scaled B<b> (value / 2**b)."""
    return value / 2.0**b


def from_fraction(fraction: float, b: int) -> float:
    """Stored fraction -> physical value (fraction * 2**b)."""
    return fraction * 2.0**b


def dp_from_value(value: float, b: int) -> tuple[int, int]:
    """Physical value at scale B<b> -> (high, low) AGC words."""
    return dp_encode(to_fraction(value, b))


def dp_to_value(high: int, low: int, b: int) -> float:
    """(high, low) AGC words at scale B<b> -> physical value."""
    return from_fraction(dp_decode(high, low), b)
