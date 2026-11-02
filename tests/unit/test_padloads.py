"""Unit tests for agc/padloads.py (parsing the pad-load catalogue), first on a small inline
SAMPLE, then (TestRealCatalogue) on the real file in the submodule -- skipped via
`pytest.mark.skipif` if the submodule is not checked out.

Run alone: `uv run pytest tests/unit/test_padloads.py -v`.
"""

import math

import pytest

from luminary_agent.agc.padloads import PADLOADS_PATH, load_padloads, parse_padloads
from luminary_agent.agc.scaling import dp_to_value, sp_to_value

# A DP word at B-24 resolves 2**24 / 2**28 = 0.0625 -- the tightest honest tolerance.
RES_B24 = 2.0**24 / 2**28

SAMPLE = """
# RBRFG    (6D)   P(I)     (R-OFG)         LUNAR LANDING TARGET PARAMETERS (  METERS )
#          +0     2DEC*   +2.92362643 E+ 3 B-24 *
#          +2     2DEC*   +0.00000000 E+ 0 B-24 *    23A LUMAR LANDING PGM
#          +4     2DEC*   -1.00839629 E+ 4 B-24 *
#
# LOWCRIT  (1D)   P(I)                     LUNAR LANDING TARGET PARAMETERS (2.7 LBS/BIT)
#                 1OCT    04251
#
# THRESHX  (1D)   P(I)                     SOMETHING ELSE
#                 1DEC     5050  B-16                   SUNLITER # 147
"""


def test_double_precision_entry_decodes_back_to_its_documented_value() -> None:
    e = parse_padloads(SAMPLE)["RBRFG"]
    assert len(e.words) == e.length == 6
    # B-24: stored fraction is value / 2**24 -- decode with the same exponent, not a guess.
    assert math.isclose(dp_to_value(e.words[0], e.words[1], 24), 2923.62643, abs_tol=RES_B24)
    assert dp_to_value(e.words[2], e.words[3], 24) == 0.0
    assert math.isclose(dp_to_value(e.words[4], e.words[5], 24), -10083.9629, abs_tol=RES_B24)


def test_octal_entry_is_taken_verbatim() -> None:
    assert parse_padloads(SAMPLE)["LOWCRIT"].words == (0o04251,)


def test_single_precision_decimal_entry() -> None:
    e = parse_padloads(SAMPLE)["THRESHX"]
    assert math.isclose(sp_to_value(e.words[0], 16), 5050.0, abs_tol=2.0**16 / 2**14)


def test_trailing_comment_digits_are_not_read_as_values() -> None:
    # "SUNLITER # 147" must not contribute a word or change the value.
    assert len(parse_padloads(SAMPLE)["THRESHX"].words) == 1


def test_landing_flag() -> None:
    entries = parse_padloads(SAMPLE)
    assert entries["RBRFG"].is_landing and not entries["THRESHX"].is_landing


@pytest.mark.skipif(not PADLOADS_PATH.exists(), reason="virtualagc submodule not checked out")
class TestRealCatalogue:
    def test_parses_every_entry_with_the_declared_word_count(self) -> None:
        entries = load_padloads()
        assert len(entries) >= 100
        bad = {n: (e.length, len(e.words)) for n, e in entries.items() if e.length != len(e.words)}
        # A handful of entries are documented as structures, not flat word lists; the point is
        # that the landing ones -- the ones we load -- all parse to their declared length.
        landing_bad = {n: v for n, v in bad.items() if entries[n].is_landing}
        # TLAND is documented only as "launch date dependent" (no value): the scenario sets it.
        assert landing_bad == {"TLAND": (2, 0)}, landing_bad

    def test_braking_targets_match_the_documented_values(self) -> None:
        e = load_padloads()["RBRFG"]
        assert math.isclose(dp_to_value(e.words[0], e.words[1], 24), 2923.62643, abs_tol=RES_B24)
        assert math.isclose(dp_to_value(e.words[4], e.words[5], 24), -10083.9629, abs_tol=RES_B24)


def test_landing_mode_selects_the_matching_value_line() -> None:
    text = """
# RPCRTIME (1D)   P(I)                     LUNAR LANDING TARGET PARAMETERS (300 SECONDS )
#                 DEC     +5   E2 B-17  (TWO-PHASE LANDING MODE)  LUM MEMO
#                 DEC     +300 E2 B-17  (ONE-PHASE LANDING MODE)     #45
"""
    one = parse_padloads(text, "ONE-PHASE")["RPCRTIME"].words
    two = parse_padloads(text, "TWO-PHASE")["RPCRTIME"].words
    assert len(one) == len(two) == 1 and one != two
    # +300 E2 B-17 -> 30000 / 2**17 as a fraction of one word
    assert math.isclose(sp_to_value(one[0], 17), 30_000.0, abs_tol=2.0**17 / 2**14)
    assert math.isclose(sp_to_value(two[0], 17), 500.0, abs_tol=2.0**17 / 2**14)


def test_unknown_landing_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="landing_mode"):
        parse_padloads(SAMPLE, "THREE-PHASE")
