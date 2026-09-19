"""Spacecraft hardware discretes the AGC reads on input channels 30-33.

Ground truth: external/virtualagc/Luminary099/INPUT_OUTPUT_CHANNEL_BIT_DESCRIPTIONS.agc.
All bits in channels 30-33 are *inverted as sensed by the program*: a 0 means the signal is
present. So a "present" flag here becomes a cleared bit in the word we write. Polarity
confirmed in R02BOTH, which treats IMODES30 bit 9 == 0 as "IMU operating".

Only the discretes Luminary's landing programs actually look at are named; everything else
stays absent (1). yaAGC boots with channel 30 = 037777 (bit 15, stable-member temperature
in limits, present) and 31-33 all absent, so an untouched AGC believes the IMU is off.
"""

from __future__ import annotations

from dataclasses import dataclass

ALL_ABSENT = 0o77777


def _bit(n: int) -> int:
    """Channel bit numbers in the AGC documentation are 1-based from the LSB."""
    return 1 << (n - 1)


@dataclass
class Discretes:
    # --- channel 30 -------------------------------------------------------------
    abort_with_descent_stage: bool = False  # bit 1
    engine_armed: bool = True  # bit 3
    abort_with_ascent_stage: bool = False  # bit 4
    auto_throttle: bool = True  # bit 5 -- computer control of the descent engine
    imu_operate: bool = True  # bit 9 -- IMU operating with no malfunction
    lm_computer_has_control: bool = True  # bit 10 -- LGC (not AGS) has control
    imu_cage: bool = False  # bit 11
    imu_cdu_fail: bool = False  # bit 12
    imu_fail: bool = False  # bit 13
    iss_turn_on_requested: bool = False  # bit 14
    imu_temperature_in_limits: bool = True  # bit 15
    # --- channel 33 -------------------------------------------------------------
    lr_range_data_good: bool = False  # bit 5
    lr_position_1: bool = False  # bit 6 -- P63 waits for the antenna in position 1
    lr_position_2: bool = False  # bit 7
    lr_velocity_data_good: bool = False  # bit 8
    lr_range_low_scale: bool = False  # bit 9
    pipa_fail: bool = False  # bit 13

    def channel_30(self) -> int:
        present = int(
            (self.abort_with_descent_stage and _bit(1))
            | (self.engine_armed and _bit(3))
            | (self.abort_with_ascent_stage and _bit(4))
            | (self.auto_throttle and _bit(5))
            | (self.imu_operate and _bit(9))
            | (self.lm_computer_has_control and _bit(10))
            | (self.imu_cage and _bit(11))
            | (self.imu_cdu_fail and _bit(12))
            | (self.imu_fail and _bit(13))
            | (self.iss_turn_on_requested and _bit(14))
            | (self.imu_temperature_in_limits and _bit(15))
        )
        return ALL_ABSENT & ~present

    def channel_31(self) -> int:
        return ALL_ABSENT  # no hand-controller or mode-switch input

    def channel_32(self) -> int:
        return ALL_ABSENT  # no thrusters disabled, no PRO key held

    def channel_33(self) -> int:
        present = int(
            (self.lr_range_data_good and _bit(5))
            | (self.lr_position_1 and _bit(6))
            | (self.lr_position_2 and _bit(7))
            | (self.lr_velocity_data_good and _bit(8))
            | (self.lr_range_low_scale and _bit(9))
            | (self.pipa_fail and _bit(13))
        )
        return ALL_ABSENT & ~present

    def channel_words(self) -> dict[int, int]:
        return {
            0o30: self.channel_30(),
            0o31: self.channel_31(),
            0o32: self.channel_32(),
            0o33: self.channel_33(),
        }
