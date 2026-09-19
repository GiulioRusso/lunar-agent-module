"""Parse the pad-load catalogue in external/virtualagc/Luminary069/PADLOADS.agc.

That file documents every mission-pad-loaded erasable parameter: a header line
`# NAME (nD) P(x) ... description`, then value lines such as
    #  +0   2DEC*   +2.92362643 E+ 3 B-24 *
    #        1OCT    04251
    #        1DEC    +3841  B-14
The directives are the assembler's own, so encoding follows the assembler: `2DEC` is a
double-precision fraction, `1DEC`/`DEC` single precision, `1OCT`/`OCT` a raw octal word, and
`value E<n> B<b>` means value * 10**n stored as a fraction of 2**b (validated against
assembler output in tests/unit/test_scaling.py).

CAVEAT, kept deliberately loud: this is **Luminary 69** -- Apollo 10's flight software. The
guidance family is the same as Luminary 99's (Apollo 11) but the *values* are Apollo 10's
sample loads. Using them gives a consistent nominal scenario; it is not "Apollo 11's pad
load" and must never be described as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from luminary_agent.agc.build import VIRTUALAGC
from luminary_agent.agc.scaling import dp_from_value, sp_from_value

PADLOADS_PATH = VIRTUALAGC / "Luminary069" / "PADLOADS.agc"

_HEADER = re.compile(r"^#\s+(\S+)\s+\((\d+)D\)\s+(\S+)\s+(.*)$")
_VALUE = re.compile(r"^#\s+(?:\+(\d+)\s+)?(?P<dir>1OCT|OCT|1DEC|DEC|2DEC\*?|6DEC)\b(?P<rest>.*)$")
_NUMBER = re.compile(r"[+-]?\s*(?:\d+\.?\d*|\.\d+)")
_EXP = re.compile(r"\bE\s*([+-]?\s*\d+)")
_SCALE = re.compile(r"\bB\s*([+-]?\s*\d+)")


@dataclass(frozen=True)
class PadLoad:
    name: str
    length: int  # words, as declared in the header
    kind: str  # e.g. "P(I)" pad-loaded invariant, "P(U)" uplinked
    description: str
    words: tuple[int, ...]

    @property
    def is_landing(self) -> bool:
        return "LUNAR LANDING" in self.description


def _clean(token: str) -> str:
    return token.replace(" ", "")


def _encode(directive: str, rest: str) -> list[int]:
    rest = rest.lstrip("*")  # `2DEC*`: the regex's \b can leave the star on the value side
    if directive in ("1OCT", "OCT"):
        m = re.match(r"\s*([0-7]+)", rest)
        return [int(m.group(1), 8)] if m else [0]
    if directive == "6DEC":
        return [0] * 6  # a zeroed list (LUMINARY LIST, INT. INIT.)

    # Strip trailing free-text so its digits can't be mistaken for values.
    scale_m = _SCALE.search(rest)
    exp_m = _EXP.search(rest)
    # Assembler "B-24" means fraction = value * 2**-24, i.e. scaling.py's b = +24.
    # With no B scale the assembler stores an integer: 14 fractional bits for one word,
    # 28 for two (`1DEC 2600` is the word 2600; `2DEC 34573411` is that integer in 28 bits).
    default_b = 28 if directive.startswith("2DEC") else 14
    scale = -int(_clean(scale_m.group(1))) if scale_m else default_b
    exponent = int(_clean(exp_m.group(1))) if exp_m else 0
    head = rest[: min(m.start() for m in (scale_m, exp_m) if m)] if (scale_m or exp_m) else rest
    num_m = _NUMBER.match(head.lstrip())
    value = float(_clean(num_m.group(0))) * 10.0**exponent if num_m else 0.0
    if directive.startswith("2DEC"):
        return list(dp_from_value(value, scale))
    return [sp_from_value(value, scale)]


LANDING_MODES = ("ONE-PHASE", "TWO-PHASE")


def parse_padloads(text: str, landing_mode: str = "ONE-PHASE") -> dict[str, PadLoad]:
    """Parse the catalogue. Some entries list one value per landing mode (Apollo 10 flew the
    two-phase mode, Apollo 11's landing used the one-phase mode); lines tagged for the other
    mode are skipped. Untagged lines always apply.
    """
    if landing_mode not in LANDING_MODES:
        raise ValueError(f"landing_mode must be one of {LANDING_MODES}")
    other = next(m for m in LANDING_MODES if m != landing_mode)
    entries: dict[str, PadLoad] = {}
    current: tuple[str, int, str, str] | None = None
    words: list[int] = []

    def flush() -> None:
        if current is not None and current[0] not in entries:
            name, length, kind, desc = current
            entries[name] = PadLoad(name, length, kind, desc.strip(), tuple(words))

    for line in text.splitlines():
        header = _HEADER.match(line)
        if header:
            flush()
            words = []
            current = (header.group(1), int(header.group(2)), header.group(3), header.group(4))
            continue
        if current is None:
            continue
        value = _VALUE.match(line)
        if value and f"{other} LANDING MODE" not in line:
            words += _encode(value.group("dir"), value.group("rest"))
    flush()
    return entries


def load_padloads(
    path: Path = PADLOADS_PATH, landing_mode: str = "ONE-PHASE"
) -> dict[str, PadLoad]:
    return parse_padloads(path.read_text(errors="replace"), landing_mode)
