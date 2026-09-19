"""4-byte channel packet encode/decode for yaAGC's socket I/O protocol.

Ground truth: external/virtualagc/yaAGC/agc_utilities.c (FormIoPacket / ParseIoPacket).
Not derived from any doc -- read straight from the C source that implements the wire format.

Packet layout (4 bytes), channel in [0, 0xff], value in [0, 0x7fff]:
    byte0 = 00UCCCCC   (signature 00, u-bit, top 5 bits of an 8-bit channel number)
    byte1 = 01cccVVV   (signature 01, low 3 bits of channel, top 3 bits of value)
    byte2 = 10VVVVVV   (signature 10, middle 6 bits of value)
    byte3 = 11VVVVVV   (signature 11, low 6 bits of value)

Channel is 8 bits, not the 9 (0x1ff) that FormIoPacket's own range check allows: bit 0x20
of byte0 is reserved for the u-bit (ParseIoPacket masks byte0 with 0x1F before shifting),
so on the wire a channel above 0xff would alias into the u-bit and corrupt on decode.
FormIoPacket's wider bound is dead code in practice -- every real AGC channel is <=0377
octal (255) -- so we enforce the tighter, round-trip-safe bound here instead of copying
a check that would silently mis-encode.

The u-bit sets a per-channel mask on yaAGC's side rather than writing the channel
directly -- see ChannelInput in SocketAPI.c.
"""

from __future__ import annotations

MAX_CHANNEL = 0xFF
MAX_VALUE = 0x7FFF


def encode_packet(channel: int, value: int, u_bit: bool = False) -> bytes:
    """Encode a channel write as a 4-byte packet (mirrors FormIoPacket, plus the u-bit)."""
    if not (0 <= channel <= MAX_CHANNEL):
        raise ValueError(f"channel {channel!r} out of range [0, {MAX_CHANNEL:#x}]")
    if not (0 <= value <= MAX_VALUE):
        raise ValueError(f"value {value!r} out of range [0, {MAX_VALUE:#x}]")
    u = 0x20 if u_bit else 0
    b0 = (channel >> 3) | u
    b1 = 0x40 | ((channel << 3) & 0x38) | ((value >> 12) & 0x07)
    b2 = 0x80 | ((value >> 6) & 0x3F)
    b3 = 0xC0 | (value & 0x3F)
    return bytes((b0, b1, b2, b3))


def decode_packet(packet: bytes) -> tuple[int, int, bool]:
    """Decode a 4-byte packet to (channel, value, u_bit) (mirrors ParseIoPacket).

    Raises ValueError if the packet's signature bits don't match the protocol.
    """
    if len(packet) != 4:
        raise ValueError(f"packet must be 4 bytes, got {len(packet)}")
    b0, b1, b2, b3 = packet
    if b0 & 0xC0 != 0x00:
        raise ValueError(f"bad signature in byte 0: {b0:#04x}")
    if b1 & 0xC0 != 0x40:
        raise ValueError(f"bad signature in byte 1: {b1:#04x}")
    if b2 & 0xC0 != 0x80:
        raise ValueError(f"bad signature in byte 2: {b2:#04x}")
    if b3 & 0xC0 != 0xC0:
        raise ValueError(f"bad signature in byte 3: {b3:#04x}")
    channel = ((b0 & 0x1F) << 3) | ((b1 >> 3) & 0x07)
    value = ((b1 << 12) & 0x7000) | ((b2 << 6) & 0x0FC0) | (b3 & 0x003F)
    u_bit = bool(b0 & 0x20)
    return channel, value, u_bit
