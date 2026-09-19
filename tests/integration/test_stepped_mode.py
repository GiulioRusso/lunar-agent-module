"""v3's load-bearing claim (APOLLO_AGENT_PLAN.md Sec.3.1): the whole simulation can be paused
while the agent thinks, with no time skip on resume. Verified against a real yaAGC.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import AGC_CYCLES_PER_SECOND
from luminary_agent.agc.dsky import DskyState
from luminary_agent.agc.process import AgcProcess, artifacts_present

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def _mission_time_cs(dsky: DskyState) -> int | None:
    """N65 shows HRS / MIN / SEC.CC in R1 / R2 / R3 (R3 in centiseconds)."""
    if dsky.r1 is None or dsky.r2 is None or dsky.r3 is None:
        return None
    return dsky.r1 * 360_000 + dsky.r2 * 6_000 + dsky.r3


def test_long_pause_does_not_fast_forward_the_agc(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19811) as agc:
            await agc.step(20_000)  # get past boot
            before = (await agc.coredump()).cycle_counter
            await asyncio.sleep(3.0)  # AGC blocked at the prompt for 3 s of wall-clock
            await agc.step(1_000)
            after = (await agc.coredump()).cycle_counter

            advanced = after - before
            # 1000 instructions is ~1.6k cycles. Without SimUpdateTime cancelling the pause,
            # yaAGC would burn the missed 3 s (~256k cycles) on resume.
            assert 0 < advanced < 10_000, f"AGC advanced {advanced} cycles across a 3 s pause"

    asyncio.run(run())


def test_paused_world_is_frozen_and_stepping_advances_it_exactly(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19812) as agc:
            await agc.step(20_000)
            async with AgcClient(port=19812) as client:
                # A keycode sits in channel 015 until Luminary's KEYRUPT handler reads it; the
                # next write would overwrite it. So keys must be interleaved with stepping.
                for key in ["VERB", "1", "6", "ENTR", "NOUN", "6", "5", "ENTR"]:
                    await client.press_key(key)
                    await agc.step(3_000)
                for _ in range(200):
                    await agc.step(2_000)
                    await asyncio.sleep(0.01)  # let the socket reader drain
                    if _mission_time_cs(client.dsky) is not None:
                        break
                t_paused = _mission_time_cs(client.dsky)
                assert t_paused is not None, "N65 never rendered while stepping"

                await asyncio.sleep(2.0)  # 2 s of wall-clock with the AGC paused
                assert _mission_time_cs(client.dsky) == t_paused, "display moved during a pause"

                cycles_before = (await agc.coredump()).cycle_counter
                for _ in range(20):
                    await agc.step(5_000)
                await asyncio.sleep(0.05)
                cycles_after = (await agc.coredump()).cycle_counter
                t_after = _mission_time_cs(client.dsky)
                assert t_after is not None

                agc_elapsed_cs = (cycles_after - cycles_before) / AGC_CYCLES_PER_SECOND * 100
                shown_elapsed_cs = t_after - t_paused
                # The mission timer must have advanced by what the AGC actually executed
                # (display granularity + one pending update => allow a little slack).
                assert abs(shown_elapsed_cs - agc_elapsed_cs) < 25, (
                    f"display advanced {shown_elapsed_cs} cs, AGC executed {agc_elapsed_cs:.0f} cs"
                )

    asyncio.run(run())


def test_stepped_clock_keeps_plant_time_and_agc_time_together(tmp_path: Path) -> None:
    from luminary_agent.sim.clock import SteppedClock

    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19813) as agc:
            await agc.step(20_000)
            clock = SteppedClock(agc, calibrate_every_s=0.5)
            await clock.start()
            worst = 0.0
            for _ in range(150):  # 3 s of 50 Hz ticks
                await clock.advance(0.02)
                worst = max(worst, abs(clock.drift_s))
            final = (await agc.coredump()).cycle_counter
            agc_s = (final - clock._origin_cycles) / AGC_CYCLES_PER_SECOND

            assert abs(agc_s - clock.sim_time_s) < 0.05, (
                f"plant {clock.sim_time_s:.3f}s vs AGC {agc_s:.3f}s"
            )
            assert worst < 0.05, f"worst intra-run drift {worst:.3f}s"
            assert 1.3 < clock.cycles_per_instruction < 2.0  # calibrated, not left at default

    asyncio.run(run())


def test_a_saved_state_resumes_exactly_where_it_left_off(tmp_path: Path) -> None:
    """Checkpoint/resume (the AGC half of "save the simulation"): load a word through the real
    update program, save, kill the process, start a new one from the checkpoint. The word must
    survive and the AGC clock must continue from the saved cycle count, not restart.
    """
    from luminary_agent.agc.uplink import Updater

    async def run() -> None:
        saved = tmp_path / "checkpoint.core"
        async with AgcProcess(tmp_path / "a", mode="stepped", port=19814) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19814) as client:
                await Updater(agc, client).v71(0o55, [0o12345])
            await agc.save_state(saved)
            cycles_at_save = (await agc.coredump()).cycle_counter

        async with AgcProcess(tmp_path / "b", mode="stepped", port=19815, resume_from=saved) as agc:
            resumed = await agc.coredump()
            assert resumed.erasable[0][0o55] == 0o12345
            assert resumed.cycle_counter == cycles_at_save
            await agc.step(20_000)
            assert (await agc.coredump()).cycle_counter > cycles_at_save  # and it runs on

    asyncio.run(run())
