"""Decode of the RCS jet, engine on/off, and throttle-update-strobe channels.

Ground truth: external/virtualagc/Luminary099/INPUT_OUTPUT_CHANNEL_BIT_DESCRIPTIONS.agc
(the LM's own channel bit documentation, transcribed from the original hardcopy):
  CHANNEL 5   PYJETS   -- pitch RCS jet control, bits 1-8
  CHANNEL 6   ROLLJETS -- roll RCS jet control, bits 1-8
  CHANNEL 11  DSALMOUT -- bit 13 ENGINE ON, bit 14 ENGINE OFF (momentary relay pulses)
  CHANNEL 14  CHAN14   -- bit 4 THRUST DRIVE ACTIVITY (strobed once per guidance cycle
                           when THROTTLE_CONTROL_ROUTINES.agc writes a new throttle
                           command -- see coredump.py for why the value itself isn't here)

Jet bits aren't decoded past a raw bitmask: the 3-DoF planar plant this is wired to has
no attitude dynamics yet, so there's nothing to map individual jets onto until 6-DoF.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CH_PYJETS = 0o5
CH_ROLLJETS = 0o6
CH_DSALMOUT = 0o11
CH_14 = 0o14

BIT13 = 1 << 12  # ENGINE ON
BIT14 = 1 << 13  # ENGINE OFF
BIT4 = 1 << 3  # THRUST DRIVE ACTIVITY


@dataclass
class ActuatorState:
    pitch_jets: int = 0  # raw 8-bit PYJETS pattern
    roll_jets: int = 0  # raw 8-bit ROLLJETS pattern
    engine_on: bool = False
    throttle_strobe_count: int = 0  # rising edges of CHAN14 bit 4 seen so far
    _last_strobe: bool = field(default=False, init=False, repr=False)

    def apply_channel(self, channel: int, value: int) -> None:
        if channel == CH_PYJETS:
            self.pitch_jets = value & 0xFF
        elif channel == CH_ROLLJETS:
            self.roll_jets = value & 0xFF
        elif channel == CH_DSALMOUT:
            if value & BIT13:
                self.engine_on = True
            if value & BIT14:
                self.engine_on = False
        elif channel == CH_14:
            strobe = bool(value & BIT4)
            if strobe and not self._last_strobe:
                self.throttle_strobe_count += 1
            self._last_strobe = strobe
