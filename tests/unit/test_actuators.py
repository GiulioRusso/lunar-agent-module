from luminary_agent.agc.actuators import CH_14, CH_DSALMOUT, CH_PYJETS, CH_ROLLJETS, ActuatorState


def test_pitch_and_roll_jets_pass_through_as_raw_bitmask() -> None:
    a = ActuatorState()
    a.apply_channel(CH_PYJETS, 0b10110101)
    a.apply_channel(CH_ROLLJETS, 0b00001111)
    assert a.pitch_jets == 0b10110101
    assert a.roll_jets == 0b00001111


def test_pitch_jets_masked_to_8_bits() -> None:
    a = ActuatorState()
    a.apply_channel(CH_PYJETS, 0o177777)  # all 15 bits set
    assert a.pitch_jets == 0xFF


def test_engine_on_bit13() -> None:
    a = ActuatorState()
    a.apply_channel(CH_DSALMOUT, 1 << 12)
    assert a.engine_on is True


def test_engine_off_bit14() -> None:
    a = ActuatorState()
    a.engine_on = True
    a.apply_channel(CH_DSALMOUT, 1 << 13)
    assert a.engine_on is False


def test_engine_starts_off() -> None:
    assert ActuatorState().engine_on is False


def test_throttle_strobe_counts_rising_edges_only() -> None:
    a = ActuatorState()
    bit4 = 1 << 3
    a.apply_channel(CH_14, bit4)  # rising edge: 0 -> 1
    a.apply_channel(CH_14, bit4)  # held high: no new edge
    a.apply_channel(CH_14, bit4)  # still held
    assert a.throttle_strobe_count == 1
    a.apply_channel(CH_14, 0)  # falls low
    a.apply_channel(CH_14, bit4)  # rising edge again
    assert a.throttle_strobe_count == 2


def test_unrelated_channel_is_ignored() -> None:
    a = ActuatorState()
    a.apply_channel(0o10, 0o7777)  # DSKY display channel, not ours
    assert a.pitch_jets == 0
    assert a.roll_jets == 0
    assert a.engine_on is False
    assert a.throttle_strobe_count == 0
