"""Unit tests for agc/state_vector.py: the 15-word P27 layout, the LM/Moon flag, units
(velocity stored per centisecond) and an encode/decode round trip.

Run alone: `uv run pytest tests/unit/test_state_vector.py -v`.
"""

import math

from luminary_agent.agc.scaling import dp_encode
from luminary_agent.agc.state_vector import (
    SV_WORDS,
    UPSVFLAG_CSM_MOON,
    UPSVFLAG_LM_MOON,
    StateVector,
)


def _sv() -> StateVector:
    return StateVector(r_m=(1_752_400.0, 0.0, 0.0), v_ms=(-3.0, 1_683.6, 0.0), t_cs=12_345.0)


def test_p27_state_vector_is_exactly_15_words() -> None:
    assert len(_sv().words()) == SV_WORDS == 15


def test_flag_marks_lm_on_the_lunar_sphere() -> None:
    flag = _sv().words()[0]
    assert flag == UPSVFLAG_LM_MOON == 0o77775
    # negative (LM) with |value| == 2 (lunar sphere), in ones' complement
    assert 0o77777 ^ flag == 2


def test_words_round_trip_through_decode() -> None:
    sv = _sv()
    w = sv.words()
    back = StateVector.from_words(w[1:7], w[7:13], w[13:15])
    assert all(math.isclose(a, b, abs_tol=1.0) for a, b in zip(back.r_m, sv.r_m, strict=True))
    assert all(math.isclose(a, b, abs_tol=0.01) for a, b in zip(back.v_ms, sv.v_ms, strict=True))
    assert math.isclose(back.t_cs, sv.t_cs, abs_tol=1.0)


def test_velocity_is_stored_per_centisecond() -> None:
    hi, lo = dp_encode(1_683.6 / 100.0 / 2**5)
    assert _sv().words()[9:11] == [hi, lo]


def test_csm_and_lm_differ_only_in_the_flag_word() -> None:
    lm, csm = _sv().words(UPSVFLAG_LM_MOON), _sv().words(UPSVFLAG_CSM_MOON)
    assert lm[1:] == csm[1:]
    assert csm[0] == 0o00002  # positive = CSM, |2| = lunar sphere
    assert 0o77777 ^ lm[0] == csm[0]  # LM is exactly its ones'-complement negative
