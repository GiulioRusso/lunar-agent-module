"""Episode log: gzipped JSONL, one line per tick (APOLLO_AGENT_PLAN.md Sec.3.2).

Line 1 is a header describing what produced the log (scenario seed, policy, model/prompt
hashes, git SHA, clock mode, ...); every following line is one tick. A log that cannot say
what produced it is worthless within a week, so `Recorder` refuses to start without a
header. Replay is playback of this file -- no AGC, no physics, no model calls.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

FORMAT_VERSION = 1


class Recorder:
    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        if not header:
            raise ValueError("an episode log needs a non-empty header")
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = gzip.open(path, "wt", encoding="utf-8")
        self._write({"type": "header", "format": FORMAT_VERSION, **header})

    def _write(self, obj: dict[str, Any]) -> None:
        self._fh.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def tick(self, record: dict[str, Any]) -> None:
        self._write({"type": "tick", **record})

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_episode(path: Path) -> tuple[dict[str, Any], Iterator[dict[str, Any]]]:
    """Return (header, iterator over tick records). The iterator streams; a long episode is
    never held in memory.
    """
    fh = gzip.open(path, "rt", encoding="utf-8")
    first = fh.readline()
    if not first:
        fh.close()
        raise ValueError(f"{path} is empty")
    header = json.loads(first)
    if header.get("type") != "header":
        fh.close()
        raise ValueError(f"{path} does not start with a header line")

    def ticks() -> Iterator[dict[str, Any]]:
        with fh:
            for line in fh:
                record = json.loads(line)
                if record.get("type") == "tick":
                    yield record

    return header, ticks()
