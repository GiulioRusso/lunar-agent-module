"""Unit tests for agc/dsky.py: turning channel-010 segment codes back into PROG/VERB/NOUN and
R1-R3 numbers, including yaDSKY2's two-bit sign rule. `_channel_010` builds a channel word
(tag | left code << 5 | right code, plus the 0x0400 sign bit) the way the AGC would send it.

Run alone: `uv run pytest tests/unit/test_dsky.py -v`.
"""

from luminary_agent.agc.dsky import DskyState


def _channel_010(tag: int, left_code: int, right_code: int, minus: bool = False) -> int:
    value = tag | (left_code << 5) | right_code
    if minus:
        value |= 0x0400
    return value


def test_program_display() -> None:
    dsky = DskyState()
    # PROG "63": left digit code 19 -> 7... use 0 and 21 for "9","0" style check instead.
    dsky.apply_channel(0o10, _channel_010(0x5800, 29, 27))  # codes 29->8, 27->3
    assert dsky.program_number == 83


def test_verb_noun_display_matches_gate0_sequence() -> None:
    dsky = DskyState()
    # VERB "16" -> left digit '1' (code 3), right digit '6' (code 28)
    dsky.apply_channel(0o10, _channel_010(0x5000, 3, 28))
    assert dsky.verb_number == 16
    # NOUN "65" -> left digit '6' (code 28), right digit '5' (code 30)
    dsky.apply_channel(0o10, _channel_010(0x4800, 28, 30))
    assert dsky.noun_number == 65


def test_register_1_unsigned_five_digits() -> None:
    dsky = DskyState()
    dsky.apply_channel(0o10, _channel_010(0x4000, 0, 21))  # R1D1 blank(0) side unused, right=0
    dsky.apply_channel(0o10, _channel_010(0x3800, 21, 3))  # R1D2,R1D3 = 0,1
    dsky.apply_channel(0o10, _channel_010(0x3000, 25, 27))  # R1D4,R1D5 = 2,3
    assert dsky.r1_digits == [0, 0, 1, 2, 3]
    assert dsky.r1 == 123


def test_blank_digit_leaves_register_undetermined() -> None:
    dsky = DskyState()
    dsky.apply_channel(0o10, _channel_010(0x3800, 0, 3))  # left blank (code 0), right = 1
    assert dsky.r1 is None


def test_comp_acty_discrete_on_channel_011() -> None:
    dsky = DskyState()
    assert dsky.comp_acty is False
    dsky.apply_channel(0o11, 0o2)
    assert dsky.comp_acty is True
    dsky.apply_channel(0o11, 0o0)
    assert dsky.comp_acty is False


def test_sign_bit1_alone_reads_negative() -> None:
    dsky = DskyState()
    dsky.apply_channel(0o10, _channel_010(0x4000, 0, 21))  # R1D1 = 0
    dsky.apply_channel(0o10, _channel_010(0x3800, 21, 21))  # R1D2,D3 = 0,0, sign bit clear
    dsky.apply_channel(
        0o10, _channel_010(0x3000, 3, 21, minus=True)
    )  # R1D4,D5 = "1","0", sets sign bit 1
    assert dsky.r1_sign == 1
    assert dsky.r1 == -10


def test_sign_bit2_takes_priority_over_bit1() -> None:
    dsky = DskyState()
    dsky.apply_channel(0o10, _channel_010(0x4000, 0, 21))  # R1D1 = 0
    dsky.apply_channel(0o10, _channel_010(0x3800, 21, 21, minus=True))  # R1D2,D3 sets sign bit 2
    dsky.apply_channel(
        0o10, _channel_010(0x3000, 3, 21, minus=True)
    )  # R1D4,D5 = "1","0", sets sign bit 1
    assert dsky.r1_sign == 3
    assert dsky.r1 == 10  # bit 2 (from the higher digit pair) wins, per yaDSKY2's draw order
