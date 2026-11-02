"""Unit tests for plant/discretes.py. Remember the inverted logic: a *present* signal is a
*cleared* (0) bit, so `& (1 << n) == 0` means "bit n+1 is asserted".

Run alone: `uv run pytest tests/unit/test_discretes.py -v`.
"""

from luminary_agent.plant.discretes import ALL_ABSENT, Discretes


def test_defaults_boot_state_matches_yaagc_for_untouched_channels() -> None:
    d = Discretes()
    assert d.channel_32() == ALL_ABSENT


def test_default_is_the_dap_mode_switch_in_auto() -> None:
    d = Discretes()
    assert d.channel_31() & (1 << 13) == 0  # bit 14 present: AUTO
    assert d.channel_31() & (1 << 12) != 0  # bit 13 absent: not ATT HOLD
    # ...and nothing that looks like a hand-controller command.
    assert d.channel_31() | (1 << 13) == ALL_ABSENT


def test_dap_can_be_taken_out_of_auto() -> None:
    assert Discretes(dap_auto=False).channel_31() == ALL_ABSENT


def test_present_signal_is_a_cleared_bit() -> None:
    d = Discretes(imu_operate=True)
    assert d.channel_30() & (1 << 8) == 0  # bit 9 == 0 -> IMU operating
    d = Discretes(imu_operate=False)
    assert d.channel_30() & (1 << 8) != 0


def test_yaagc_boot_value_of_ch30_is_reproduced_by_temp_only() -> None:
    only_temp = Discretes(
        engine_armed=False, auto_throttle=False, imu_operate=False, lm_computer_has_control=False
    )
    assert only_temp.channel_30() == 0o37777  # what yaAGC reports on connect


def test_abort_and_fail_flags_assert_when_set() -> None:
    d = Discretes(abort_with_descent_stage=True, imu_fail=True)
    assert d.channel_30() & 1 == 0  # bit 1 present
    assert d.channel_30() & (1 << 12) == 0  # bit 13 present


def test_lr_position_1_lives_on_channel_33_bit_6() -> None:
    assert Discretes().channel_33() == ALL_ABSENT
    assert Discretes(lr_position_1=True).channel_33() == ALL_ABSENT & ~(1 << 5)


def test_channel_words_addresses_are_30_to_33_octal() -> None:
    assert set(Discretes().channel_words()) == {0o30, 0o31, 0o32, 0o33}
