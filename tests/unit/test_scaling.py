import math

import pytest

from luminary_agent.agc.scaling import dp_decode, dp_encode, dp_from_value, dp_to_value

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
