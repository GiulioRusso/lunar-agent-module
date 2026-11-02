"""Resolve Luminary symbol names to addresses from the assembler listing.

The listing (saved by build.assemble) ends with a symbol table whose entries look like
    4657,E:   REFSMMAT     E3,1733      erasable, switched bank 3, address 01733
    2004,E:   FLAGWRD3        0077      erasable, unswitched, address 077
    5851,C:   THRUST       0000055      an EQUALS constant / register number
    3740,F:   FASTCHNG     31,3740      fixed memory (not used here)

ECADR -- the erasable address format the update program (P27) and DSKY expect -- is
    bank * 0400 + (address & 0377)
for switched erasable (`E<bank>,<addr>`), and simply the address for unswitched erasable
(0-01377), which the same formula gives with bank = address >> 8. Derived from the way P27's
UPEND71 splits an ECADR (`TS EBANK` for the bank, `MASK LOW8` for the offset).

Why: the Python code never hard-codes "the altitude lives at address 1234". It asks
`symbols.ecadr("HCALC")` and the address comes from the assembler's own output, so it is always
right for the rope actually built.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# One symbol-table entry: "<line>,<kind>:  <NAME>  <address>" (see the examples above).
_ENTRY = re.compile(r"\s(\d+),([EFC]):\s+(\S+)\s+(\S+)")
_BANKED = re.compile(r"^E(\d),([0-7]+)$")
_PLAIN_OCTAL = re.compile(r"^[0-7]+$")


@dataclass(frozen=True)
class Symbol:
    """One named address or constant from the listing."""

    name: str
    kind: str  # "E" erasable, "F" fixed, "C" constant/equate
    bank: int | None
    value: int  # octal-parsed address (E/F) or constant (C)


class SymbolTable:
    """Name -> Symbol lookup. `"X" in table` works thanks to __contains__."""

    def __init__(self, symbols: dict[str, Symbol]) -> None:
        self._symbols = symbols

    def __contains__(self, name: str) -> bool:
        return name in self._symbols

    def constant(self, name: str) -> int:
        """Value of an EQUALS constant (register numbers such as THRUST, bit masks)."""
        sym = self._get(name, "C")
        return sym.value

    def ecadr(self, name: str) -> int:
        """ECADR (bank * 256 + offset) of an erasable variable, e.g. ecadr("THETAD")."""
        sym = self._get(name, "E")
        bank = sym.bank if sym.bank is not None else sym.value >> 8
        return bank * 0o400 + (sym.value & 0o377)

    def _get(self, name: str, kind: str) -> Symbol:
        """Look up `name` and insist it is of `kind` (clear errors instead of wrong addresses)."""
        try:
            sym = self._symbols[name]
        except KeyError:
            raise KeyError(f"no symbol {name!r} in the listing") from None
        if sym.kind != kind:
            raise KeyError(f"symbol {name!r} is kind {sym.kind!r}, not {kind!r}")
        return sym


def parse_listing(text: str) -> SymbolTable:
    """Build a SymbolTable from the whole listing text (only E and C entries are kept)."""
    symbols: dict[str, Symbol] = {}
    for _, kind, name, raw in _ENTRY.findall(text):
        banked = _BANKED.match(raw)
        if kind == "E" and banked:
            sym = Symbol(name, kind, int(banked.group(1)), int(banked.group(2), 8))
        elif kind in ("E", "C") and _PLAIN_OCTAL.match(raw):
            sym = Symbol(name, kind, None, int(raw, 8))
        else:
            continue  # fixed-memory entries and anything we don't consume
        symbols.setdefault(name, sym)  # keep the first definition if a name repeats
    return SymbolTable(symbols)


def load_symbols(path: Path) -> SymbolTable:
    """Read and parse a listing file (build.listing_path())."""
    return parse_listing(path.read_text())
