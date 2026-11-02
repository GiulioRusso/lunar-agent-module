"""Gimbal-angle (CDU) counts: reading what Luminary wants, and seeding the registers.

Each CDU register counts a full revolution in 2**15 = 32768 pulses (0.010986 deg each; the same
scale sensors.CDU_SCALE_RAD is built from). Luminary's desired gimbal angles for a maneuver are in
THETAD (= CPHI, CTHETA, CPSI, erasable 0321-0323), one word each, ones'-complement counts in the
same units -- confirmed against a live AGC: THETAD = (-47, 9792, 35) counts shows on the DSKY
(V50 N18) as a 107.57 degree pitch, and 9792 * 360/32768 = 107.58.

Seeding the registers at the desired burn attitude makes P63's automatic maneuver (R60LEM) a
no-op. That is a stepping stone to ignition, NOT attitude dynamics: nothing here rotates a
vehicle.

CDU = "Coupling Data Unit": the box that turned the IMU's gimbal angles (the orientation of the
LM relative to the gyro-stabilised platform) into counter pulses for the AGC. 3 axes -> X, Y, Z.
"""

from __future__ import annotations

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import CoreDump, decode_agc_word
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.registers import REG_CDUX, REG_CDUY, REG_CDUZ
from luminary_agent.agc.symbols import SymbolTable

COUNTS_PER_REV = 1 << 15  # 32768 counts = 360 degrees
CDU_REGISTERS = (REG_CDUX, REG_CDUY, REG_CDUZ)


def desired_gimbal_counts(dump: CoreDump, symbols: SymbolTable) -> tuple[int, int, int]:
    """Luminary's THETAD as signed counts (X, Y, Z)."""
    words = dump.ecadr_words(symbols.ecadr("THETAD"), 3)  # 3 consecutive words from memory
    x, y, z = (decode_agc_word(w) for w in words)
    return x, y, z


def cdu_counts(dump: CoreDump) -> tuple[int, int, int]:
    """Present CDU register contents, as signed counts (registers are 2's-complement mod 2**15)."""
    out = []
    for reg in CDU_REGISTERS:
        raw = dump.erasable[0][reg]
        # Two's complement mod 2**15: the upper half of the range means negative.
        out.append(raw - COUNTS_PER_REV if raw >= COUNTS_PER_REV // 2 else raw)
    return out[0], out[1], out[2]


async def seed_cdus(
    client: AgcClient,
    agc: AgcProcess,
    target: tuple[int, int, int],
    chunk_steps: int = 50_000,
    max_chunks: int = 40,
) -> None:
    """Drive the three CDU registers from their present values to `target` counts.

    Sends fast PCDU/MCDU pulses (a 107 degree slew is ~9.8k pulses, ~1.5 s of AGC time), then
    steps the AGC until yaAGC's CDU FIFO has drained *and the registers read `target`*. Returning
    earlier would hand back a half-slewed attitude: an early version read Y = 7966 of 9792.
    """
    present = cdu_counts(await agc.coredump())
    for reg, now, want in zip(CDU_REGISTERS, present, target, strict=True):
        # Shortest way round the circle, in [-16384, 16384): 350 -> 10 deg is +20, not -340.
        delta = (want - now + COUNTS_PER_REV // 2) % COUNTS_PER_REV - COUNTS_PER_REV // 2
        await client.send_cdu_pulses(reg, delta, fast=True)
    # Let the AGC run (and yaAGC drain its pulse queue) until the registers read the target.
    for _ in range(max_chunks):
        await agc.step(chunk_steps)
        if cdu_counts(await agc.coredump()) == target:
            return
    raise TimeoutError(
        f"CDU registers never reached {target}; last {cdu_counts(await agc.coredump())}"
    )
