import json
from pathlib import Path

from luminary_agent.eval.report import summarize
from luminary_agent.eval.sets import DEV, FROZEN


def test_sets_sizes_and_disjoint_seeds() -> None:
    assert len(FROZEN) == 60 and len(DEV) == 15
    assert not {s for _, s in FROZEN} & {s for _, s in DEV}


def test_summarize_counts_soft_touchdowns_per_tier(tmp_path: Path) -> None:
    def result(soft_touchdown: bool, vz: float, decisions: int, vetoes: int) -> str:
        s = {
            "landed": True,
            "soft_touchdown": soft_touchdown,
            "mission_success": "not_scored",
            "vertical_ms": vz,
            "horizontal_ms": 0.4,
            "target_error_m": 100,
            "fuel_kg": 500,
        }
        r = {"decisions": decisions, "safety_veto_count": vetoes, "fallback_count": 0}
        return json.dumps({"tier": 2, "score": s, "result": r})

    (tmp_path / "t2_s0.json").write_text(result(True, 0.5, 3, 1))
    (tmp_path / "t2_s1.json").write_text(result(False, 5.5, 5, 3))
    row = summarize(tmp_path).splitlines()[1].split()
    assert row[:4] == ["2", "2", "1", "0+2ns"]
    assert float(row[4]) == 3.0
    assert row[-3:] == ["4", "2", "0"]


def test_summarize_reports_scored_mission_success(tmp_path: Path) -> None:
    def result(mission: bool) -> str:
        s = {
            "landed": True, "soft_touchdown": True, "mission_success": mission,
            "vertical_ms": 0.5, "horizontal_ms": 0.1, "target_error_m": 30, "fuel_kg": 500,
        }  # fmt: skip
        return json.dumps({"tier": 1, "score": s, "result": {}})

    (tmp_path / "t1_s0.json").write_text(result(True))
    (tmp_path / "t1_s1.json").write_text(result(False))
    assert summarize(tmp_path).splitlines()[1].split()[:4] == ["1", "2", "2", "1"]


def test_compare_builds_one_table_over_configurations(tmp_path: Path) -> None:
    from luminary_agent.eval.report import compare

    def episode(root: Path, name: str, tier: int, seed: int, mission: object, vetoes: int) -> None:
        d = root / name
        d.mkdir(exist_ok=True)
        s = {
            "landed": True, "soft_touchdown": True, "mission_success": mission,
            "vertical_ms": 0.5, "horizontal_ms": 0.1, "target_error_m": 40.0 * (seed + 1),
            "fuel_kg": 500.0,
        }  # fmt: skip
        r = {"decisions": 10, "safety_veto_count": vetoes, "fallback_count": 0}
        (d / f"t{tier}_s{seed}.json").write_text(
            json.dumps({"tier": tier, "score": s, "result": r})
        )

    for seed, ok in ((0, True), (1, False), (2, True)):
        episode(tmp_path, "scripted", 1, seed, ok, 0)
    episode(tmp_path, "null", 3, 0, "not_scored", 4)
    rows = compare(tmp_path).splitlines()
    assert rows[0].startswith("| config | tier |") and len(rows) == 4
    null, scripted = rows[2].split("|"), rows[3].split("|")
    assert [c.strip() for c in scripted[1:6]] == ["scripted", "1", "3", "3/3", "2/3"]
    assert scripted[6].strip() == "80"  # median target error
    assert null[5].strip() == "not scored" and null[9].strip() == "4"
