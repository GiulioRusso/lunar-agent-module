import multiprocessing
import queue

from viz_records import decision, tick

from luminary_agent.viz import live
from luminary_agent.viz.live import LiveFeed, LiveReader


def pair(size: int = live.BACKLOG) -> tuple[LiveFeed, LiveReader, queue.Queue[object]]:
    q: queue.Queue[object] = queue.Queue(size)
    return LiveFeed(0.0, 6_800.0, q), LiveReader(q), q


def test_ticks_are_thinned_to_the_publish_rate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    feed, reader, _ = pair()
    now = [100.0]
    monkeypatch.setattr("luminary_agent.viz.live.time.monotonic", lambda: now[0])
    for i in range(1_000):  # ~1,000 ticks in one wall second
        now[0] = 100.0 + i / 1_000
        feed.publish_tick(tick(t=i * 0.02))
    assert 18 <= len(reader.poll()) <= 22 and reader.poll() == []  # ~20 Hz, and poll drains


def test_a_slow_window_loses_the_oldest_frames_not_the_newest(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    feed, reader, _ = pair(size=100)
    now = [0.0]
    monkeypatch.setattr("luminary_agent.viz.live.time.monotonic", lambda: now[0])
    for i in range(150):
        now[0] += 1.0
        feed.publish_tick(tick(t=float(i)))
    frames = reader.poll()
    assert len(frames) == 100 and frames[-1].t_s == 149.0 and frames[0].t_s == 50.0


def test_decisions_shape_later_frames_and_the_end_is_reported() -> None:
    feed, reader, _ = pair()
    for _ in range(5):
        feed.publish_decision(decision("command"))
    feed.publish_tick(tick())
    assert reader.poll()[0].decisions == 5 and reader.summary is None
    feed.publish_end({"landed": True})
    assert reader.poll() == [] and reader.summary == {"landed": True}


def test_the_feed_works_across_a_process_boundary() -> None:
    """The real `luminary fly` channel: frames pickle, and the child's queue flushes on exit."""
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue(live.BACKLOG)
    p = ctx.Process(target=_child, args=(q,))
    p.start()
    reader, frames = LiveReader(q), []
    while reader.summary is None:
        frames += reader.poll()
    p.join()
    assert len(frames) == 1 and frames[0].intent == "hold" and reader.summary == {"landed": True}


def _child(q: object) -> None:
    feed = LiveFeed(0.0, 6_800.0, q)  # type: ignore[arg-type]
    feed.publish_decision(decision("hold"))
    feed.publish_tick(tick())
    feed.publish_end({"landed": True})
