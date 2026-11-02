"""Regression cases for coordinate consistency, action authority and evaluation integrity."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_agent_interface import _executor, _obs
from viz_records import decision, tick

from luminary_agent.eval import run_set
from luminary_agent.eval.score import score
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.surface import MOON_RATE_RAD_S, site_position_m
from luminary_agent.plant.terrain import Surface
from luminary_agent.policies.base import Intent, command, hold, validate_intent
from luminary_agent.policies.runner import DecisionRunner
from luminary_agent.safety.monitor import SafetyMonitor
from luminary_agent.sim.descent import DescentResult, _consult, observe
from luminary_agent.sim.manual_control import ManualController
from luminary_agent.sim.observation import Observation
from luminary_agent.viz.view_model import FrameBuilder


@pytest.mark.parametrize("elapsed", [-100.0, 0.0, 100.0])
def test_comoving_lander_keeps_target_error_at_different_landing_times(elapsed: float) -> None:
    site = 0.5
    x = site_position_m(site * R_MOON, elapsed)
    state = PlanarState(0.0, x, -0.5, MOON_RATE_RAD_S * R_MOON, 7500.0)
    result = DescentResult(
        "touchdown", 1000 + elapsed, state, site_angle_rad=site, site_elapsed_s=elapsed
    )
    assert result.downrange_error_m == pytest.approx(0)
    assert result.horizontal_relative_ms == pytest.approx(0)
    assert score(result, surface=Surface(0)).mission_success is True


def test_observation_and_view_use_the_same_moving_site_as_scoring() -> None:
    elapsed = 100.0
    x = site_position_m(1000.0, elapsed) + 40
    state = PlanarState(200, x, -1, 4.6, 7500)
    sim: Any = SimpleNamespace(state=state, z_m=0, thrust_n=10000, dry_mass_kg=6800)
    client: Any = SimpleNamespace(
        dsky=SimpleNamespace(program_number=64, noun_number=64, verb_number=6, r1=0, r2=0, r3=1000)
    )
    from luminary_agent.plant.radar import Radar

    obs = observe(
        sim, client, "manual", 1100, [], Radar(), Surface(0), 1000, 1000, "ok: prior action"
    )
    assert obs.target_downrange_m == pytest.approx(40)
    assert obs.previous_action == "ok: prior action"
    assert obs.instrument_model == "ideal_state_with_faulted_radar"
    frame = FrameBuilder(1000, 6800).tick(tick(x_m=x, target_downrange_m=40))
    assert frame.downrange_m == obs.target_downrange_m


def test_cross_range_velocity_prevents_false_soft_touchdown() -> None:
    state = PlanarState(0, 0, -0.5, MOON_RATE_RAD_S * R_MOON, 7500)
    result = DescentResult("touchdown", 1000, state, lateral_velocity_ms=2.0)
    sc = score(result, surface=Surface(0))
    assert sc.horizontal_ms == pytest.approx(2)
    assert not sc.soft_touchdown and sc.mission_success is False


def test_safety_authority_latches_between_logs_and_through_sensor_loss() -> None:
    monitor = SafetyMonitor()
    obs = replace(_obs(mode="manual", alt=10), vertical_ms=-8)
    assert monitor.check(obs) is not None
    assert monitor.active
    later = replace(obs, t_s=100.5, alarms=(0o1202,))
    assert monitor.check(later) is None  # logging is suppressed; authority is not
    assert monitor.active
    blind = replace(later, t_s=101, radar_altitude_m=None, agc_altitude_m=None)
    monitor.check(blind)
    assert monitor.active
    restored = replace(obs, t_s=106, vertical_ms=-1)
    release = monitor.check(restored)
    assert release is not None and release.release and not monitor.active


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "fast", True, None])
def test_malformed_horizontal_commands_never_mutate_controller(bad: Any) -> None:
    ex, _, _ = _executor()
    ex.sim.manual = ex.controller.control
    rejected = asyncio.run(ex.apply(Intent("command", {"horizontal_ms": bad}, 101)))
    assert rejected.startswith("rejected")
    assert ex.controller.horizontal_ms == 0
    assert ex.last_result == rejected
    controller = ManualController()
    with pytest.raises(ValueError):
        controller.set_targets(-1, bad)
    assert controller.descent_rate_ms is None


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), 99, 100, 161, True])
def test_intent_validity_must_be_finite_future_and_bounded(deadline: float) -> None:
    with pytest.raises(ValueError):
        validate_intent(hold(deadline), 100)


def test_unknown_parameters_rejected_and_safety_does_not_replace_policy_targets() -> None:
    ex, _, _ = _executor()
    ex.sim.manual = ex.controller.control
    assert asyncio.run(ex.apply(Intent("command", {"typo": 4}, 101))).startswith("rejected")
    asyncio.run(ex.apply(command(101, -2, 1)))
    asyncio.run(ex.apply(command(105, -1, 0), safety=True))
    assert ex.policy_targets == (-2, 1, 0)


class BrokenPolicy:
    name = "broken"

    def reset(self) -> None:
        pass

    def decide(self, obs: Observation, t_s: float) -> Intent:
        raise ValueError("malformed reply")


def test_policy_error_logs_fallback_and_quarantines_policy() -> None:
    ex, _, _ = _executor()
    ex.sim.manual = ex.controller.control
    records: list[dict[str, Any]] = []
    sim: Any = SimpleNamespace(recorder=SimpleNamespace(event=records.append), live=None)
    runner = DecisionRunner(BrokenPolicy())
    intent = asyncio.run(_consult(runner, ex, sim, _obs(mode="manual"), "heartbeat", []))
    assert intent.kind == "command" and runner.disabled and runner.failures == 1
    assert records[0]["source"] == "fallback"
    assert "ValueError" in records[0]["rationale"]
    assert records[0]["intent"]["valid_until_s"] == 105


def test_policy_timeout_returns_without_waiting_for_worker() -> None:
    release = threading.Event()

    class SlowPolicy(BrokenPolicy):
        def decide(self, obs: Observation, t_s: float) -> Intent:
            release.wait(2)
            return hold(t_s + 1)

    async def run() -> None:
        runner = DecisionRunner(SlowPolicy(), timeout_s=0.01)
        with pytest.raises(TimeoutError):
            await runner.decide(_obs())

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_batch_refuses_stale_configuration_without_launching_episode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_set, "evaluation_fingerprint", lambda _: "new")
    path = tmp_path / "t1_s0.json"
    path.write_text(json.dumps({"evaluation_fingerprint": "old"}))
    with pytest.raises(ValueError, match="incompatible cached result"):
        asyncio.run(run_set.one(1, 0, 20000, tmp_path, "scripted"))
    path.write_text(json.dumps({"evaluation_fingerprint": "new", "score": {}}))
    assert asyncio.run(run_set.one(1, 0, 20000, tmp_path, "scripted"))["score"] == {}


def test_decision_inspector_preserves_rationale_time_result_and_source() -> None:
    builder = FrameBuilder(0, 6800)
    rec = decision("command")
    rec.update(
        t=10.5,
        rationale="Choose a slower descent to retain braking margin.",
        latency_s=0.12,
        source="policy",
    )
    intent = rec["intent"]
    assert isinstance(intent, dict)
    intent["valid_until_s"] = 12.5
    builder.decision(rec)
    frame = builder.tick(tick())
    assert frame.rationale == rec["rationale"]
    assert frame.decision_t_s == 10.5 and frame.decision_valid_until_s == 12.5
    assert math.isclose(frame.decision_latency_s, 0.12)


def test_evaluation_fingerprint_covers_dirty_source_and_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from luminary_agent.sim import recorder

    monkeypatch.setattr(recorder, "REPO_ROOT", tmp_path)
    source = tmp_path / "src/luminary_agent/policy.py"
    source.parent.mkdir(parents=True)
    source.write_text("a = 1\n")
    config = {"policy": "scripted", "safety": True}
    before = recorder.evaluation_fingerprint(config)
    source.write_text("a = 2\n")
    after = recorder.evaluation_fingerprint(config)
    assert before != after
    assert after != recorder.evaluation_fingerprint(config | {"safety": False})


def test_snapshot_hashes_rope_contents_even_with_same_size_and_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from luminary_agent.agc import build, padloads
    from luminary_agent.sim.landing_scenario import DescentScenario
    from luminary_agent.sim.snapshot import snapshot_key

    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"test")
    monkeypatch.setattr(build, "yaagc_path", lambda: artifact)
    monkeypatch.setattr(build, "listing_path", lambda: artifact)
    monkeypatch.setattr(padloads, "PADLOADS_PATH", artifact)
    rope = tmp_path / "rope.bin"
    rope.write_bytes(b"abcd")
    timestamp = rope.stat()
    before = snapshot_key(DescentScenario(), rope)
    rope.write_bytes(b"efgh")
    os.utime(rope, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    assert before != snapshot_key(DescentScenario(), rope)


def test_last_decision_is_visible_live_and_in_replay_without_another_tick(tmp_path: Path) -> None:
    import queue

    from luminary_agent.sim.recorder import Recorder
    from luminary_agent.viz.live import LiveFeed, LiveReader
    from luminary_agent.viz.replay import load_episode

    channel: queue.Queue[Any] = queue.Queue()
    feed, reader = LiveFeed(0, 6800, channel), LiveReader(channel)
    rec = decision("hold")
    rec.update(t=10.0, rationale="Final contact assessment.")
    feed.publish_tick(tick(t=10))
    reader.poll()
    feed.publish_decision(rec)
    assert reader.poll()[-1].rationale == "Final contact assessment."
    path = tmp_path / "flight.jsonl.gz"
    with Recorder(path, {"policy": "scripted"}) as recorder:
        recorder.tick(tick(t=10))
        recorder.event(rec)
    assert load_episode(path).frames[-1].rationale == "Final contact assessment."
