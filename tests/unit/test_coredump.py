import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.coredump import (
    NUM_BANKS,
    NUM_CHANNELS,
    THRUST_REGISTER,
    WORDS_PER_BANK,
    CoreDumpPoller,
    decode_agc_word,
    parse_core_dump,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0),
        (1, 1),
        (0o37777, 16383),  # most positive
        (0o77777, 0),  # ones'-complement negative zero
        (0o77776, -1),
        (0o40000, -16383),  # most negative
    ],
)
def test_decode_agc_word(raw: int, expected: int) -> None:
    assert decode_agc_word(raw) == expected


def _write_dump(
    tmp_path: Path,
    channel_values: dict[int, int],
    erasable_values: dict[tuple[int, int], int],
) -> Path:
    channels = [0] * NUM_CHANNELS
    for ch, v in channel_values.items():
        channels[ch] = v
    erasable = [[0] * WORDS_PER_BANK for _ in range(NUM_BANKS)]
    for (bank, word), v in erasable_values.items():
        erasable[bank][word] = v
    lines = [f"{v:06o}" for v in channels]
    for bank in range(NUM_BANKS):
        lines += [f"{v:06o}" for v in erasable[bank]]
    lines += ["0"] * 8  # trailing CPU-state lines parse_core_dump ignores
    path = tmp_path / "core"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_parse_core_dump_round_trips_channels_and_erasable(tmp_path: Path) -> None:
    path = _write_dump(tmp_path, {5: 0o123, 14: 0o10}, {(0, 0o55): 0o12345})
    dump = parse_core_dump(path)
    assert dump.channels[5] == 0o123
    assert dump.channels[14] == 0o10
    assert dump.erasable[0][0o55] == 0o12345


def test_thrust_register_constant_points_at_bank0_055() -> None:
    assert THRUST_REGISTER == (0, 0o55)


def test_erasable_signed_decodes_thrust_register(tmp_path: Path) -> None:
    path = _write_dump(tmp_path, {}, {(0, 0o55): 0o10000})  # 4096, positive
    dump = parse_core_dump(path)
    assert dump.erasable_signed(*THRUST_REGISTER) == 4096


def test_parse_core_dump_rejects_truncated_file(tmp_path: Path) -> None:
    path = tmp_path / "core"
    path.write_text("0\n0\n0\n")
    with pytest.raises(ValueError, match="truncated"):
        parse_core_dump(path)


def test_core_dump_poller_picks_up_updates(tmp_path: Path) -> None:
    async def run() -> None:
        path = _write_dump(tmp_path, {}, {(0, 0o55): 0})
        poller = CoreDumpPoller(path=path, interval_s=0.01)
        poller.start()
        try:
            await asyncio.sleep(0.03)
            assert poller.thrust_register_signed == 0

            _write_dump(tmp_path, {}, {(0, 0o55): 500})
            await asyncio.sleep(0.05)
            assert poller.thrust_register_signed == 500
        finally:
            poller.stop()

    asyncio.run(run())


def test_core_dump_poller_survives_truncated_read(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / "core"
        path.write_text("0\n0\n")  # truncated from the start
        poller = CoreDumpPoller(path=path, interval_s=0.01)
        poller.start()
        try:
            await asyncio.sleep(0.03)
            assert poller.thrust_register_signed is None  # never parses, doesn't crash
        finally:
            poller.stop()

    asyncio.run(run())
