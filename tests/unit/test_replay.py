from pathlib import Path

from viz_records import decision, tick

from luminary_agent.plant.terrain import Hazard, Surface
from luminary_agent.sim.recorder import Recorder
from luminary_agent.viz.replay import dry_mass_kg, load_episode


def write_log(path: Path, n: int = 100, **header: object) -> None:
    with Recorder(path, {"policy": "null", "tier": 2, "seed": 4, "site_x_m": 900.0} | header) as r:
        for i in range(n):
            r.tick(tick(t=i * 0.02, x_m=900.0 + i))
            if i == 50:
                r.event(decision("command"))
        r.landing({"score": {"landed": True, "soft_touchdown": True, "mission_success": False}})


def test_frames_are_thinned_and_end_on_the_last_tick(tmp_path: Path) -> None:
    log = tmp_path / "ep.jsonl.gz"
    write_log(log)
    ep = load_episode(log, hz=10.0)  # 100 ticks over ~2 s -> ~20 frames
    assert 18 <= len(ep.frames) <= 24
    assert ep.frames[0].t_s == 0.0 and ep.frames[-1].t_s == 99 * 0.02
    assert ep.frames[-1].downrange_m == 99.0  # relative to the header's site
    assert ep.title == "policy=null | tier=2 | seed=4"
    assert ep.landing is not None and ep.landing["score"]["mission_success"] is False


def test_decisions_reach_the_frames_that_follow_them(tmp_path: Path) -> None:
    log = tmp_path / "ep.jsonl.gz"
    write_log(log)
    ep = load_episode(log)
    before, after = ep.frames[ep.index_at(0.5)], ep.frames[ep.index_at(1.5)]
    assert before.decisions == 0 and after.decisions == 1 and after.intent.startswith("command")


def test_index_at_is_the_last_frame_not_after_t(tmp_path: Path) -> None:
    log = tmp_path / "ep.jsonl.gz"
    write_log(log)
    ep = load_episode(log)
    assert ep.index_at(-5.0) == 0 and ep.index_at(1e9) == len(ep.frames) - 1
    assert all(ep.frames[ep.index_at(t)].t_s <= t for t in (0.31, 0.77, 1.5))


def test_surface_and_dry_mass_come_from_the_header(tmp_path: Path) -> None:
    log = tmp_path / "ep.jsonl.gz"
    surface = Surface(3, hazards=(Hazard("crater", 10.0, 20.0, 5.0),))
    write_log(log, surface=surface.as_dict(), dispersion={"propellant_scale": 0.9})
    ep = load_episode(log)
    assert ep.surface == surface
    assert dry_mass_kg(ep.header) == 15_000.0 - 8_200.0 * 0.9
    assert ep.frames[0].fuel_kg == 0.0  # 7,500 kg is below this episode's dry mass (7,620 kg)
    assert dry_mass_kg({}) == 6_800.0


def test_a_log_without_a_header_is_refused(tmp_path: Path) -> None:
    import gzip

    bad = tmp_path / "bad.jsonl.gz"
    with gzip.open(bad, "wt") as fh:
        fh.write('{"type":"tick"}\n')
    try:
        load_episode(bad)
    except (ValueError, KeyError):
        return
    raise AssertionError("a log with no header must not load")
