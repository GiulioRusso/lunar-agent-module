"""A full descent verifies that action records, surface coordinates and scoring agree."""

from __future__ import annotations

import asyncio
import gzip
import json
import math
from pathlib import Path

import pytest

from luminary_agent.agc.process import artifacts_present
from luminary_agent.eval.run_episode import run
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.surface import MOON_RATE_RAD_S
from luminary_agent.viz.replay import load_episode

pytestmark = pytest.mark.skipif(not artifacts_present(), reason="run make agc first")


def test_full_scripted_descent_records_consistent_score_and_decisions(tmp_path: Path) -> None:
    log = tmp_path / "descent.jsonl.gz"
    result = asyncio.run(run(1, 0, 31200, tmp_path / "work", log, "scripted"))
    assert result["result"]["outcome"] == "touchdown"
    assert result["result"]["fallback_count"] == 0
    with gzip.open(log, "rt") as stream:
        records = [json.loads(line) for line in stream]
    ticks = [r for r in records if r["type"] == "tick"]
    decisions = [r for r in records if r["type"] == "decision"]
    final = ticks[-1]
    expected_speed = math.hypot(
        final["vt_ms"] - MOON_RATE_RAD_S * (R_MOON + final["h_m"]), final["zdot_ms"]
    )
    assert result["score"]["horizontal_ms"] == pytest.approx(expected_speed)
    expected_error = math.hypot(final["target_downrange_m"], final["z_m"])
    assert result["score"]["target_error_m"] == pytest.approx(expected_error)
    assert all("valid_until_s" in d["intent"] and "source" in d for d in decisions)
    assert any(d["obs"]["previous_action"] is not None for d in decisions)
    episode = load_episode(log)
    assert episode.frames[-1].target_error_m == pytest.approx(expected_error)
    assert episode.frames[-1].rationale
