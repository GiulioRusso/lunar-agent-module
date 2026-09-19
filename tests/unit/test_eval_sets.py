import json
from pathlib import Path

from luminary_agent.eval.report import summarize
from luminary_agent.eval.sets import DEV, FROZEN


def test_sets_sizes_and_disjoint_seeds() -> None:
    assert len(FROZEN) == 60 and len(DEV) == 15
    assert not {s for _, s in FROZEN} & {s for _, s in DEV}


def test_summarize_counts_safe_per_tier(tmp_path: Path) -> None:
    def score(safe: bool, vz: float) -> str:
        s = {"landed": True, "safe": safe, "vertical_ms": vz, "horizontal_ms": 0.4}
        return json.dumps({"tier": 2, "score": {**s, "site_error_m": 100, "fuel_kg": 500}})

    (tmp_path / "t2_s0.json").write_text(score(True, 0.5))
    (tmp_path / "t2_s1.json").write_text(score(False, 5.5))
    row = summarize(tmp_path).splitlines()[1].split()
    assert row[:3] == ["2", "2", "1"] and float(row[3]) == 3.0
