"""Asyncio TCP client for yaAGC's channel I/O socket protocol.

yaAGC opens several equivalent listening ports starting at --port (default 19697,
19797 by LM convention -- see APOLLO_AGENT_PLAN.md Sec.3); any client connecting to any
one of them sees every channel write broadcast to it and can write channels back
(SocketAPI.c: ChannelRoutineGeneric opens MAX_CLIENTS identical server sockets). One
connection is therefore enough for both DSKY keying and reading back the display.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from luminary_agent.agc import handshake
from luminary_agent.agc.actuators import ActuatorState
from luminary_agent.agc.channels import decode_packet, encode_packet
from luminary_agent.agc.dsky import KEYCODE, DskyState
from luminary_agent.agc.registers import cdu_pulse_packets, pipa_pulse_packets


class AgcClient:
    """One socket connection to a running yaAGC, with a background reader that keeps
    a DskyState (channel 010/011) and an ActuatorState (channels 5/6/11/14) in sync
    with every channel write seen. The DPS throttle magnitude is not among them -- see
    coredump.py for why, and CoreDumpPoller for how to read it anyway.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 19797) -> None:
        self.host = host
        self.port = port
        self.dsky = DskyState()
        self.actuators = ActuatorState()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self.handshake = handshake.register(port)

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        self._read_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        handshake.unregister(self.port)
        if self._read_task is not None:
            self._read_task.cancel()
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while True:
            packet = await self._reader.readexactly(4)
            if packet == b"\xff\xff\xff\xff":
                continue  # yaAGC's periodic liveness probe, not a channel write
            try:
                channel, value, _u_bit = decode_packet(packet)
            except ValueError:
                continue
            if channel == handshake.SYNC_CHANNEL:  # yaAGC's end-of-command marker
                self.handshake.marker_seen()
                continue
            self.dsky.apply_channel(channel, value)
            self.actuators.apply_channel(channel, value)

    def _write(self, packet: bytes) -> None:
        assert self._writer is not None
        self._writer.write(packet)
        self.handshake.bytes_sent += len(packet)  # yaAGC waits for these before it steps

    async def write_channel(self, channel: int, value: int, u_bit: bool = False) -> None:
        assert self._writer is not None
        self._write(encode_packet(channel, value, u_bit))
        await self._writer.drain()

    async def write_channels(self, words: Mapping[int, int]) -> None:
        """Write several channels at once (e.g. Discretes.channel_words())."""
        assert self._writer is not None
        for channel, value in words.items():
            self._write(encode_packet(channel, value))
        await self._writer.drain()

    async def press_key(self, key: str) -> None:
        """Press a DSKY key (e.g. "VERB", "1", "ENTR") -- writes its keycode to channel 015."""
        await self.write_channel(0o15, KEYCODE[key])

    async def key_sequence(self, keys: list[str], delay_s: float = 0.1) -> None:
        for key in keys:
            await self.press_key(key)
            await asyncio.sleep(delay_s)

    async def send_pipa_pulses(self, register: int, pulse_count: int) -> None:
        """Feed one IMU sample's worth of PIPA pulses (see sensors.Imu.sample) into
        the AGC as PINC/MINC counter-increment writes on `register`.
        """
        await self._send_packets(pipa_pulse_packets(register, pulse_count))

    async def send_cdu_pulses(self, register: int, pulse_count: int, fast: bool = False) -> None:
        """As send_pipa_pulses, but PCDU/MCDU for a CDU angle register (`fast`: 6400 pps)."""
        await self._send_packets(cdu_pulse_packets(register, pulse_count, fast))

    async def _send_packets(self, packets: list[bytes]) -> None:
        assert self._writer is not None
        for packet in packets:
            self._write(packet)
        if packets:
            await self._writer.drain()

    async def __aenter__(self) -> AgcClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
