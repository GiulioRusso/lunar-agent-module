"""Programmatic DSKY: keycodes for channel 015 input, decode of the 7-segment
display data that yaAGC streams out on channel 010.

Ground truth for keycodes: external/virtualagc/yaDSKY2/yaDSKY2.cpp, the on_*Button_pressed
handlers, each of which calls OutputKeycode(N) on channel 015.

Ground truth for the 7-segment code table: the Virtual AGC developer documentation
(channel 010 format AAAABCCCCCDDDDD), cross-checked against yaDSKY2's SevenSegmentFilenames
table, which is NULL for every code not in this table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KEYCODE = {
    "0": 16,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "VERB": 17,
    "NOUN": 31,
    "PLUS": 26,
    "MINUS": 27,
    "CLR": 30,
    "KEY_REL": 25,
    "ENTR": 28,
    "RSET": 18,
}

# 5-bit segment code -> displayed digit, or None for blank. Codes not present here are
# invalid on real hardware (yaDSKY2 treats them as a decode error).
SEVEN_SEGMENT = {
    0: None,
    3: 1,
    15: 4,
    19: 7,
    21: 0,
    25: 2,
    27: 3,
    28: 6,
    29: 8,
    30: 5,
    31: 9,
}

# Channel 010 bits 14-11 (AAAA, "Value & 0x7800"): which digit pair this write addresses.
_PROG = 0x5800
_VERB = 0x5000
_NOUN = 0x4800
_R1D1 = 0x4000
_R1D23 = 0x3800
_R1D45 = 0x3000
_R2D12 = 0x2800
_R2D34 = 0x2000
_R2D5_R3D1 = 0x1800
_R3D23 = 0x1000
_R3D45 = 0x0800


@dataclass
class DskyState:
    """Decoded display state, updated in place as channel 010/011 writes arrive."""

    program: list[int | None] = field(default_factory=lambda: [None, None])
    verb: list[int | None] = field(default_factory=lambda: [None, None])
    noun: list[int | None] = field(default_factory=lambda: [None, None])
    r1_digits: list[int | None] = field(default_factory=lambda: [None] * 5)
    r2_digits: list[int | None] = field(default_factory=lambda: [None] * 5)
    r3_digits: list[int | None] = field(default_factory=lambda: [None] * 5)
    r1_sign: int = 0  # bit 0 = minus seen, bit 1 = plus seen (plus wins, per yaDSKY2)
    r2_sign: int = 0
    r3_sign: int = 0
    comp_acty: bool = False

    def _register(self, tag: int) -> tuple[list[int | None], int, int] | None:
        """Map an AAAA tag to (digit list, left index, right index)."""
        return {
            _R1D23: (self.r1_digits, 1, 2),
            _R1D45: (self.r1_digits, 3, 4),
            _R2D12: (self.r2_digits, 0, 1),
            _R2D34: (self.r2_digits, 2, 3),
            _R3D23: (self.r3_digits, 1, 2),
            _R3D45: (self.r3_digits, 3, 4),
        }.get(tag)

    def _digits_to_int(self, digits: list[int | None]) -> int | None:
        if any(d is None for d in digits):
            return None
        return int("".join(str(d) for d in digits))

    @property
    def r1(self) -> int | None:
        v = self._digits_to_int(self.r1_digits)
        return None if v is None else (-v if self.r1_sign == 1 else v)

    @property
    def r2(self) -> int | None:
        v = self._digits_to_int(self.r2_digits)
        return None if v is None else (-v if self.r2_sign == 1 else v)

    @property
    def r3(self) -> int | None:
        v = self._digits_to_int(self.r3_digits)
        return None if v is None else (-v if self.r3_sign == 1 else v)

    @property
    def program_number(self) -> int | None:
        return self._digits_to_int(self.program)

    @property
    def verb_number(self) -> int | None:
        return self._digits_to_int(self.verb)

    @property
    def noun_number(self) -> int | None:
        return self._digits_to_int(self.noun)

    def apply_channel(self, channel: int, value: int) -> None:
        """Fold one channel-output packet into this display state.

        Only channels 010 (7-segment digits) and 011 (COMP ACTY discrete) are handled --
        everything else yaDSKY2 uses is annunciator lamps, out of scope for Gate 0.
        """
        if channel == 0o10:
            self._apply_channel_010(value)
        elif channel == 0o11:
            self.comp_acty = bool(value & 0o2)

    def _apply_channel_010(self, value: int) -> None:
        tag = value & 0x7800
        left = SEVEN_SEGMENT.get((value >> 5) & 0x1F)
        right = SEVEN_SEGMENT.get(value & 0x1F)

        if tag == _PROG:
            self.program[0], self.program[1] = left, right
            return
        if tag == _VERB:
            self.verb[0], self.verb[1] = left, right
            return
        if tag == _NOUN:
            self.noun[0], self.noun[1] = left, right
            return
        if tag == _R1D1:
            self.r1_digits[0] = right
            return
        if tag == _R2D5_R3D1:
            self.r2_digits[4], self.r3_digits[0] = left, right
            return

        reg = self._register(tag)
        if reg is None:
            return
        digits, li, ri = reg
        digits[li], digits[ri] = left, right
        if tag in (_R1D23, _R1D45):
            self.r1_sign = _update_sign(self.r1_sign, tag, _R1D23, _R1D45, value)
        if tag in (_R2D12, _R2D34):
            self.r2_sign = _update_sign(self.r2_sign, tag, _R2D12, _R2D34, value)
        if tag in (_R3D23, _R3D45):
            self.r3_sign = _update_sign(self.r3_sign, tag, _R3D23, _R3D45, value)


def _sign_set(value: int) -> bool:
    return bool(value & 0x0400)


def _update_sign(current: int, tag: int, hi_tag: int, lo_tag: int, value: int) -> int:
    """Track the two-bit R{n}Sign accumulator yaDSKY2 keeps (bit1 from the higher
    digit pair's write, bit0 from the lower pair's), so a later '+' still shows
    the sign until both digit pairs report the opposite.
    """
    bit = 2 if tag == hi_tag else 1
    if _sign_set(value):
        return current | bit
    return current & ~bit
