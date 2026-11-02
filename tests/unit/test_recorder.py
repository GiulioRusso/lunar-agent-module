"""Unit tests for sim/recorder.py: the gzipped JSONL episode log (header required, ticks round-
trip, provenance fields present). Files are written to pytest's per-test `tmp_path` folder.

Run alone: `uv run pytest tests/unit/test_recorder.py -v`.
"""

import gzip
from pathlib import Path

import pytest

from luminary_agent.sim.recorder import Recorder, provenance, read_episode


def test_round_trip_header_and_ticks(tmp_path: Path) -> None:
    path = tmp_path / "ep.jsonl.gz"
    with Recorder(path, {"seed": 7, "policy": "null", "clock": "stepped"}) as rec:
        rec.tick({"t": 0.00, "h": 15_000.0})
        rec.tick({"t": 0.02, "h": 14_999.9})
    header, ticks = read_episode(path)
    assert header["seed"] == 7
    assert header["policy"] == "null"
    assert header["format"] == 1
    assert list(ticks) == [
        {"type": "tick", "t": 0.00, "h": 15_000.0},
        {"type": "tick", "t": 0.02, "h": 14_999.9},
    ]


def test_refuses_to_start_without_a_header(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="header"):
        Recorder(tmp_path / "ep.jsonl.gz", {})


def test_file_is_actually_gzipped_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "ep.jsonl.gz"
    with Recorder(path, {"seed": 1}) as rec:
        rec.tick({"t": 0.0})
    lines = gzip.open(path, "rt").read().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith('{"type":"header"')


def test_read_rejects_file_without_header(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl.gz"
    with gzip.open(path, "wt") as fh:
        fh.write('{"type":"tick","t":0}\n')
    with pytest.raises(ValueError, match="header"):
        read_episode(path)


def test_ticks_stream_without_loading_everything(tmp_path: Path) -> None:
    path = tmp_path / "ep.jsonl.gz"
    with Recorder(path, {"seed": 1}) as rec:
        for i in range(1000):
            rec.tick({"i": i})
    _, ticks = read_episode(path)
    assert next(ticks)["i"] == 0
    assert next(ticks)["i"] == 1


def test_provenance_includes_agc_patch_and_scenario_fingerprints() -> None:
    p = provenance({"tier": 3, "seed": 0})
    for key in (
        "git_sha",
        "git_dirty",
        "virtualagc_commit",
        "virtualagc_dirty",
        "patch_sha256",
        "patch_set_sha256",
        "virtualagc_diff_sha256",
        "yaagc_sha256",
        "rope_sha256",
        "listing_sha256",
        "scenario_sha256",
    ):
        assert key in p
    assert "yaagc-free-run.patch" in p["patch_sha256"]
    assert p["scenario_sha256"]


def test_landing_record_round_trips_and_is_absent_when_not_written(tmp_path: Path) -> None:
    from luminary_agent.sim.recorder import read_landing

    path = tmp_path / "ep.jsonl.gz"
    with Recorder(path, {"policy": "null"}) as rec:
        rec.tick({"i": 0})
    assert read_landing(path) is None
    with Recorder(path, {"policy": "null"}) as rec:
        rec.landing({"score": {"mission_success": False}, "assessment": {"slope_deg": 3.0}})
    assert read_landing(path) == {
        "type": "landing",
        "score": {"mission_success": False},
        "assessment": {"slope_deg": 3.0},
    }
