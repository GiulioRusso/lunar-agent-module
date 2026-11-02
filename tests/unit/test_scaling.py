"""Unit tests for agc/scaling.py (AGC fixed-point single/double precision and B-scaling).
GOLDEN holds (value, scale, words) triples that the real assembler produced: the ground truth.

Run alone: `uv run pytest tests/unit/test_scaling.py -v`.
"""

import math

import pytest

from luminary_agent.agc.scaling import (
    dp_decode,
    dp_encode,
    dp_from_value,
    dp_to_value,
    sp_from_value,
    sp_to_value,
)

# (value, B-exponent, (high, low)) -- copied from a real yaYUL listing of Luminary099, where
# the assembler encoded each `2DEC value Bn` constant. This is ground truth for the format.
GOLDEN = [
    (1_738_090.0, 29, (0o00065, 0o01265)),  # RSUBM
    (6_373_338.0, 29, (0o00302, 0o17755)),  # ERAD
    (6_378_166.0, 29, (0o00302, 0o24533)),  # RSUBE
    (384_402_000.0, 29, (0o26723, 0o00450)),  # RSUBEM
    (-13_554.26363, 27, (0o77776, 0o53032)),  # 2J3RE/J2, a negative
]


@pytest.mark.parametrize(("value", "b", "words"), GOLDEN)
def test_encoder_reproduces_the_assemblers_words(
    value: float, b: int, words: tuple[int, int]
) -> None:
    high, low = dp_from_value(value, b)
    # Rounding of the last bit may differ by one count; anything more is a format error.
    got = (high << 14) + low if high < 0o40000 else -(((0o77777 ^ high) << 14) + (0o77777 ^ low))
    want_h, want_l = words
    want = (
        (want_h << 14) + want_l
        if want_h < 0o40000
        else -(((0o77777 ^ want_h) << 14) + (0o77777 ^ want_l))
    )
    assert abs(got - want) <= 1, f"{value} B{b}: got {(high, low)}, assembler wrote {words}"


@pytest.mark.parametrize(("value", "b", "words"), GOLDEN)
def test_decoder_inverts_the_assemblers_words(value: float, b: int, words: tuple[int, int]) -> None:
    resolution = 2.0**b / 2.0**28
    assert math.isclose(dp_to_value(*words, b), value, abs_tol=2 * resolution)


def test_round_trip_is_within_one_lsb() -> None:
    for f in (0.0, 1e-9, 0.5, -0.5, 0.123456789, -0.987654321):
        assert abs(dp_decode(*dp_encode(f)) - f) <= 1 / 2**28


def test_negative_is_bitwise_not_of_both_words() -> None:
    hi, lo = dp_encode(0.25)
    nhi, nlo = dp_encode(-0.25)
    assert (nhi, nlo) == (0o77777 ^ hi, 0o77777 ^ lo)


def test_overflow_is_an_error() -> None:
    with pytest.raises(OverflowError):
        dp_encode(1.0)


# Single-precision `DEC` constants, as encoded by yaYUL (value, B-exponent, word).
SP_GOLDEN = [
    (-30.30, 5, 0o41545),  # APSVEX:  DEC -3030 E-2 B-5   (a negative)
    (24.0, 14, 0o00030),  # THRESH1: DEC 24 B-14
    (3841.0, 14, 0o07401),  # FMAXODD: DEC +3841 B-14
    (3467.0, 14, 0o06613),  # FMAXPOS: DEC +3467 B-14
]


@pytest.mark.parametrize(("value", "b", "word"), SP_GOLDEN)
def test_sp_encoder_reproduces_the_assemblers_word(value: float, b: int, word: int) -> None:
    got = sp_from_value(value, b)
    assert abs(got - word) <= 1, f"{value} B{b}: got {got:#o}, assembler wrote {word:#o}"


@pytest.mark.parametrize(("value", "b", "word"), SP_GOLDEN)
def test_sp_decoder_inverts_the_assemblers_word(value: float, b: int, word: int) -> None:
    assert math.isclose(sp_to_value(word, b), value, abs_tol=2.0**b / 2**14)


def test_refsmmat_identity_is_stored_as_one_half() -> None:
    from luminary_agent.agc.landing_setup import IDENTITY, refsmmat_words

    words = refsmmat_words(IDENTITY)
    assert len(words) == 18
    assert dp_to_value(words[0], words[1], 1) == 1.0  # element (0,0)
    assert dp_to_value(words[2], words[3], 1) == 0.0  # element (0,1)
    assert dp_to_value(words[8], words[9], 1) == 1.0  # element (1,1): row-major position 4
    assert dp_from_value(1.0, 1) == (0o20000, 0)  # 1.0 stored as the fraction 0.5


def test_refsmbit_is_bit_13_of_flagwrd3() -> None:
    from luminary_agent.agc.landing_setup import REFSMBIT_MASK

    assert REFSMBIT_MASK == 0o10000  # "10000 FOR REFSMMAT GOOD" (PADLOADS.agc), bit 13, 1-based


def test_dp_words_with_disagreeing_signs_decode_as_hi_times_2_14_plus_lo() -> None:
    """Luminary's TIG, read from a live AGC mid-computation: high word +2, low word negative.
    Its true value is 32391 cs = 323.91 s (= TDEC1 349.9 s - ZOOMTIME 26 s, per DDUMGOOD);
    a decoder that trusts the high word's sign alone reads it as ~651 s.
    """
    value = dp_to_value(0o2, 0o77206, 28)
    assert value == 2 * 16384 - 377 == 32391
    assert math.isclose(value / 100.0, 323.91)


def test_agreeing_sign_words_are_unchanged_by_the_signed_decoder() -> None:
    for f in (0.0, 1e-9, 0.5, -0.5, 0.123456789, -0.987654321):
        assert abs(dp_decode(*dp_encode(f)) - f) <= 1 / 2**28
