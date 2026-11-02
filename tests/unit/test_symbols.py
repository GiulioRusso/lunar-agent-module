"""Unit tests for agc/symbols.py on a SAMPLE copied from a real assembler listing (plus, if
`make agc` has been run, the full real listing).

Run alone: `uv run pytest tests/unit/test_symbols.py -v`.
"""

import pytest

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.symbols import load_symbols, parse_listing

# Lines copied verbatim from a real yaYUL listing of Luminary099 (symbol-table section).
SAMPLE = (
    "  4657,E:   REFSMMAT     E3,1733  \t\t  4611,E:   RDSP         E5,1434\n"
    "  2004,E:   FLAGWRD3        0077  \t\t  5851,C:   THRUST       0000055\n"
    "  4656,C:   REFSMFLG     0000057  \t\t  1914,F:   FASTCHNG     31,3740\n"
    "  5907,E:   TLAND        E5,1400\n"
)


def test_switched_erasable_ecadr_is_bank_times_0400_plus_offset() -> None:
    t = parse_listing(SAMPLE)
    assert t.ecadr("REFSMMAT") == 3 * 0o400 + 0o333
    assert t.ecadr("TLAND") == 5 * 0o400 + 0  # first word of bank 5's window


def test_unswitched_erasable_ecadr_is_the_address() -> None:
    assert parse_listing(SAMPLE).ecadr("FLAGWRD3") == 0o77


def test_equate_constants() -> None:
    t = parse_listing(SAMPLE)
    assert t.constant("THRUST") == 0o55
    assert t.constant("REFSMFLG") == 0o57


def test_fixed_memory_symbols_are_not_indexed() -> None:
    assert "FASTCHNG" not in parse_listing(SAMPLE)


def test_kind_mismatch_is_an_error_not_a_silent_wrong_address() -> None:
    t = parse_listing(SAMPLE)
    with pytest.raises(KeyError, match="kind"):
        t.ecadr("THRUST")  # an equate, not an erasable location
    with pytest.raises(KeyError, match="no symbol"):
        t.ecadr("NOSUCHTHING")


@pytest.mark.skipif(not listing_path().exists(), reason="Luminary099 not assembled -- `make agc`")
def test_real_listing_matches_hand_checked_addresses() -> None:
    t = load_symbols(listing_path())
    assert t.constant("THRUST") == 0o55  # cross-checked against ERASABLE_ASSIGNMENTS.agc
    assert t.constant("PIPAX") == 0o37  # and against yaAGC's RegPIPAX
    assert t.ecadr("REFSMMAT") == 0o1733  # bank 3: 3*0o400 + 0o333 happens to equal the address
