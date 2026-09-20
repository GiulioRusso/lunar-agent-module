"""Episode log -> one self-contained HTML replay (side elevation + instrument readouts).

Playback of the recorded log only: no AGC, no physics. Usage:
    python -m luminary_agent.viz.replay episode.jsonl.gz out.html [--hz 10]

The terrain is cosmetic (a fixed synthetic profile so height above ground is visible); the
ground the plant actually uses is the altitude-0 line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.surface import MOON_RATE_RAD_S
from luminary_agent.sim.recorder import read_decisions, read_episode

FIELDS = ("t", "h_m", "x_m", "z_m", "hdot_ms", "vh_rel", "mass_kg", "thrust_n", "pitch_deg")
DSKY_FIELDS = ("mode", "prog", "verb", "noun", "r1", "r2", "r3")  # after FIELDS in each row

PAGE = (Path(__file__).parent / "replay.html").read_text()


def _row(tick: dict[str, Any]) -> list[Any]:
    d = tick["dsky"]
    vh_rel = tick["vt_ms"] - MOON_RATE_RAD_S * (R_MOON + tick["h_m"])
    values = [tick[k] for k in ("t", "h_m", "x_m", "z_m", "hdot_ms")]
    values += [vh_rel] + [tick[k] for k in ("mass_kg", "thrust_n", "pitch_deg")]
    dsky = [d[k] for k in ("prog", "verb", "noun", "r1", "r2", "r3")]
    return [round(v, 3) for v in values] + [tick.get("mode", "auto")] + dsky


def _collapse(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive repeats of the same intent and outcome collapse to the first."""
    out: list[dict[str, Any]] = []
    for r in decisions:
        key = (r["intent"], r["applied"])
        if out and out[-1]["key"] == key:
            continue
        out.append(
            {"key": key, "t": r["t"], "kind": r["intent"]["kind"], "params": r["intent"]["params"],
             "applied": r["applied"], "latency_s": r["latency_s"], "alarms": r["obs"]["alarms"]}
        )  # fmt: skip
    return out


def build(episode: Path, out: Path, hz: float = 10.0) -> None:
    header, ticks = read_episode(episode)
    rows = [_row(t) for t in ticks]
    dt = rows[1][0] - rows[0][0]
    stride = max(1, round(1.0 / (hz * dt)))
    decisions = read_decisions(episode)
    # [t, radar altitude, AGC altitude] at every decision (None: no radar lock / not displayed)
    altitudes = [
        [r["t"], r["obs"].get("radar_altitude_m"), r["obs"].get("agc_altitude_m")]
        for r in decisions
    ]
    title = " | ".join(f"{k}={header[k]}" for k in ("policy", "tier", "seed") if k in header)
    page = (
        PAGE.replace("__TITLE__", title or "episode")
        .replace("__FIELDS__", json.dumps(list(FIELDS) + list(DSKY_FIELDS)))
        .replace("__DATA__", json.dumps(rows[::stride], separators=(",", ":")))
        .replace("__DEC__", json.dumps(_collapse(decisions), separators=(",", ":")))
        .replace("__ALT__", json.dumps(altitudes, separators=(",", ":")))
        .replace("__HZ__", str(1.0 / (stride * dt)))
    )
    out.write_text(page)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--hz", type=float, default=10.0)
    a = ap.parse_args()
    build(a.episode, a.out, a.hz)
