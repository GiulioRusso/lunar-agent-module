"""Summarise a results directory of episode JSONs: touchdown metrics and provenance-aware counts.

python -m luminary_agent.eval.report results/logs/demo
python -m luminary_agent.eval.report --compare results/logs/dev   # one table, every config
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def summarize(directory: Path) -> str:
    by_tier: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for f in sorted(directory.glob("t*_s*.json")):
        r = json.loads(f.read_text())
        result = r.get("result", {})
        score = r["score"]
        by_tier[r["tier"]].append(
            {
                **score,
                "target_error_m": score.get("target_error_m", score.get("site_error_m", 0.0)),
                # decisions = policy consultations (one LLM call each in Track B); vetoes =
                # safety-monitor overrides. Both are headline metrics, so they live in the table.
                "decisions": result.get("decisions", 0),
                "safety_vetoes": result.get("safety_veto_count", len(result.get("vetoes", []))),
                "fallbacks": result.get("fallback_count", result.get("fallbacks", 0)),
            }
        )
    lines = [
        "tier  n  soft  mission_success  median_vz  median_vh  median_target_m  "
        "median_fuel_kg  dec  veto  fallback"
    ]
    for tier, scores in sorted(by_tier.items()):
        numeric = (
            "vertical_ms",
            "horizontal_ms",
            "target_error_m",
            "fuel_kg",
            "decisions",
            "safety_vetoes",
            "fallbacks",
        )
        med = {k: statistics.median(float(s[k]) for s in scores) for k in numeric}
        soft = sum(1 for s in scores if s.get("soft_touchdown", s.get("safe", False)))
        mission_true = sum(1 for s in scores if s.get("mission_success") is True)
        mission_not_scored = sum(1 for s in scores if s.get("mission_success") == "not_scored")
        mission = f"{mission_true}" + (f"+{mission_not_scored}ns" if mission_not_scored else "")
        lines.append(
            f"{tier:>4} {len(scores):>2} {soft:>5}  {mission:>15}  "
            f"{med['vertical_ms']:>9.2f}  {med['horizontal_ms']:>9.2f}  "
            f"{med['target_error_m']:>15.0f}  {med['fuel_kg']:>14.0f}  "
            f"{med['decisions']:>3.0f}  {med['safety_vetoes']:>4.0f}  {med['fallbacks']:>8.0f}"
        )
    return "\n".join(lines)


def _rows(directory: Path) -> dict[int, list[dict[str, Any]]]:
    by_tier: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for f in sorted(directory.glob("t*_s*.json")):
        r = json.loads(f.read_text())
        res = r.get("result", {})
        by_tier[r["tier"]].append(
            {
                **r["score"],
                "decisions": res.get("decisions", 0),
                "vetoes": res.get("safety_veto_count", 0),
                "fallbacks": res.get("fallback_count", 0),
            }
        )
    return by_tier


def compare(root: Path) -> str:
    """One Markdown table over every result directory under `root` (one per policy / safety
    setting): the baseline comparison. `mission` counts only episodes where it was scored."""
    lines = [
        "| config | tier | n | soft touchdown | mission success | median target m | "
        "median fuel kg | median decisions | median vetoes | median fallbacks |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        for tier, rows in sorted(_rows(directory).items()):

            def med(key: str, rows: list[dict[str, Any]] = rows) -> float:
                return statistics.median(float(r[key]) for r in rows)

            scored = [r for r in rows if r["mission_success"] != "not_scored"]
            mission = (
                f"{sum(r['mission_success'] is True for r in scored)}/{len(scored)}"
                if scored
                else "not scored"
            )
            soft = sum(bool(r["soft_touchdown"]) for r in rows)
            lines.append(
                f"| {directory.name} | {tier} | {len(rows)} | {soft}/{len(rows)} | {mission} | "
                f"{med('target_error_m'):.0f} | {med('fuel_kg'):.0f} | {med('decisions'):.0f} | "
                f"{med('vetoes'):.0f} | {med('fallbacks'):.0f} |"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.argv[1] == "--compare":
        print(compare(Path(sys.argv[2])))
    else:
        print(summarize(Path(sys.argv[1])))
