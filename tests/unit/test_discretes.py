from luminary_agent.plant.discretes import ALL_ABSENT, Discretes


def test_defaults_boot_state_matches_yaagc_for_untouched_channels() -> None:
    d = Discretes()
    assert d.channel_31() == ALL_ABSENT
    assert d.channel_32() == ALL_ABSENT


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
