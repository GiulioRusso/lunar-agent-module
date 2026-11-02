"""Agent progress remains visible while the simulator waits, and survives replay."""

from __future__ import annotations

import gzip
import json
import queue
from pathlib import Path
from typing import Any

from viz_records import decision, tick

from luminary_agent.viz.live import LiveFeed, LiveReader
from luminary_agent.viz.native_app import Player, screenshot
from luminary_agent.viz.replay import load_episode


def test_live_progress_and_committed_details(tmp_path: Path) -> None:
    channel: queue.Queue[Any] = queue.Queue()
    feed, reader = LiveFeed(0, 4000, channel), LiveReader(channel)
    feed.publish_tick(tick(t=9))
    reader.poll()
    event = {
        "t": 9,
        "stage": "planning",
        "model": "fixture/no-llm",
        "calls": 1,
        "summary": "Requesting decision",
    }
    feed.publish_agent_status(event)
    frame = reader.poll()[-1]
    assert frame.t_s == 9 and frame.agent_stage == "planning"
    record = decision() | {
        "agent": {
            "model": "fixture/no-llm",
            "calls": 1,
            "tokens": 42,
            "evidence": ["Radar 500 m"],
            "risks": ["Radar disagreement"],
            "plan": "Recheck altitude",
            "path": ["observe", "propose", "validate", "commit"],
        },
        "rationale": "Keep current guidance",
        "execution": {"status": "applied"},
    }
    feed.publish_decision(record)
    frame = reader.poll()[-1]
    assert frame.agent_stage == "applied" and frame.agent_evidence == ("Radar 500 m",)
    assert len(frame.decision_history) == 1 and frame.agent_tokens == 42
    assert "Radar 498.00 m / AGC 510.00 m" in frame.decision_observation
    log = tmp_path / "episode.jsonl.gz"
    records = [
        {"type": "header"},
        tick(t=9) | {"type": "tick"},
        event | {"type": "agent_status"},
        record | {"type": "decision"},
        tick(t=15) | {"type": "tick"},
        record | {"type": "decision", "t": 15},
    ]
    with gzip.open(log, "wt") as stream:
        for item in records:
            stream.write(json.dumps(item) + "\n")
    episode = load_episode(log)
    assert episode.frames[0].agent_evidence == frame.agent_evidence
    player = Player(episode.frames)
    player.step_decision(1)
    assert player.t_s == 15 and player.paused
    player.step_decision(-1)
    assert player.t_s == 9
    out = tmp_path / "inspect.png"
    screenshot(episode, 15, out, inspect=True)
    assert out.stat().st_size > 1000
