import pytest

from luminary_agent.agc.channels import decode_packet, encode_packet


@pytest.mark.parametrize(
    ("channel", "value", "u_bit"),
    [
        (0, 0, False),
        (0o15, 17, False),  # VERB keycode on the DSKY keyboard channel
        (0o10, 0x5800 | (21 << 5) | 21, False),  # PROG display showing "00"
        (0xFF, 0x7FFF, True),
        (0o32, 0o20000, False),  # PRO key discrete
    ],
)
def test_round_trip(channel: int, value: int, u_bit: bool) -> None:
    packet = encode_packet(channel, value, u_bit)
    assert len(packet) == 4
    assert decode_packet(packet) == (channel, value, u_bit)


def test_encode_matches_hand_computed_bytes() -> None:
    # Channel 015 (VERB keycode, value 17), no u-bit: hand-computed from FormIoPacket's bit math.
    # byte0 = 015>>3 = 001 = 0x01
    # byte1 = 0x40 | ((015<<3)&0x38) | ((17>>12)&0x07) = 0x40 | 0x28 | 0 = 0x68
    # byte2 = 0x80 | ((17>>6)&0x3F) = 0x80
    # byte3 = 0xC0 | (17&0x3F) = 0xD1
    assert encode_packet(0o15, 17) == bytes((0x01, 0x68, 0x80, 0xD1))


def test_decode_rejects_bad_signature() -> None:
    with pytest.raises(ValueError, match="signature"):
        decode_packet(bytes((0xFF, 0xFF, 0xFF, 0xFF)))  # yaAGC's liveness probe, not a channel


def test_decode_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="4 bytes"):
        decode_packet(bytes((0, 0, 0)))


@pytest.mark.parametrize("channel", [-1, 0x100])
def test_encode_rejects_out_of_range_channel(channel: int) -> None:
    with pytest.raises(ValueError, match="channel"):
        encode_packet(channel, 0)


@pytest.mark.parametrize("value", [-1, 0x8000])
def test_encode_rejects_out_of_range_value(value: int) -> None:
    with pytest.raises(ValueError, match="value"):
        encode_packet(0, value)
