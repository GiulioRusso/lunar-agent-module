"""Summarise a results directory of episode JSONs: per-tier safe-landing rate and medians.

python -m luminary_agent.eval.report results/logs/demo
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def summarize(directory: Path) -> str:
    by_tier: dict[int, list[dict[str, float | bool]]] = defaultdict(list)
    for f in sorted(directory.glob("t*_s*.json")):
        r = json.loads(f.read_text())
        by_tier[r["tier"]].append(r["score"])
    lines = ["tier  n  safe  median_vz  median_vh  median_site_m  median_fuel_kg"]
    for tier, scores in sorted(by_tier.items()):
        med = {k: statistics.median(float(s[k]) for s in scores) for k in scores[0] if k != "safe"}
        safe = sum(1 for s in scores if s["safe"])
        lines.append(
            f"{tier:>4} {len(scores):>2} {safe:>5}  {med['vertical_ms']:>9.2f}  "
            f"{med['horizontal_ms']:>9.2f}  {med['site_error_m']:>13.0f}  {med['fuel_kg']:>14.0f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(Path(sys.argv[1])))
