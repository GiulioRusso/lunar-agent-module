"""Episode log: gzipped JSONL, one line per tick (APOLLO_AGENT_PLAN.md Sec.3.2).

Line 1 is a header describing what produced the log (scenario seed, policy, model/prompt
hashes, git SHA, clock mode, ...); every following line is one tick. A log that cannot say
what produced it is worthless within a week, so `Recorder` refuses to start without a
header. Replay is playback of this file -- no AGC, no physics, no model calls.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from collections.abc import Iterator
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from luminary_agent.agc import build as agc_build

FORMAT_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[3]


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

    def event(self, record: dict[str, Any]) -> None:
        """An agent decision (type "decision"), interleaved with ticks in time order."""
        self._write({"type": "decision", **record})

    def landing(self, record: dict[str, Any]) -> None:
        """The final verdict (type "landing"): why the touchdown is or is not a mission success."""
        self._write({"type": "landing", **record})

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


def read_decisions(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        records = (json.loads(line) for line in fh)
        return [r for r in records if r.get("type") == "decision"]


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_json(value: Any) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def provenance(scenario: Any | None = None) -> dict[str, Any]:
    """Fingerprint the code, AGC artifacts and scenario that produced a JSONL episode.

    `free_run_patch_mode` documents the current compromise when the VirtualAGC submodule is
    already dirty: the log still carries both committed patch hashes and the actual submodule diff
    hash, so the run is attributable without pretending the submodule was immutable.
    """

    def git(cwd: Path, *args: str) -> str:
        try:
            r = subprocess.run(
                ("git", *args),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout.strip()

    def git_bytes(cwd: Path, *args: str) -> bytes:
        try:
            r = subprocess.run(
                ("git", *args),
                cwd=cwd,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return b""
        return r.stdout

    patch_files = sorted(agc_build.PATCHES.glob("*.patch"))
    patch_hashes = {p.name: _sha256_file(p) for p in patch_files}
    patch_set = "".join(f"{name}:{patch_hashes[name]}\n" for name in sorted(patch_hashes))
    submodule_status = git(agc_build.VIRTUALAGC, "status", "--porcelain")
    virtualagc_diff = git_bytes(agc_build.VIRTUALAGC, "diff", "--binary")
    scenario_json = _canonical_json(scenario) if scenario is not None else ""

    return {
        "git_sha": git(REPO_ROOT, "rev-parse", "HEAD"),
        "git_dirty": bool(git(REPO_ROOT, "status", "--porcelain")),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "virtualagc_commit": git(agc_build.VIRTUALAGC, "rev-parse", "HEAD"),
        "virtualagc_dirty": bool(submodule_status),
        "virtualagc_status": submodule_status.splitlines(),
        "free_run_patch_mode": (
            "build-cache-worktree"
            if agc_build.source_dir() != agc_build.VIRTUALAGC
            else "submodule-dirty-diff-hashed"
        ),
        "patch_sha256": patch_hashes,
        "patch_set_sha256": hashlib.sha256(patch_set.encode()).hexdigest(),
        "virtualagc_diff_sha256": hashlib.sha256(virtualagc_diff).hexdigest(),
        "yaagc_sha256": _sha256_file(agc_build.yaagc_path()),
        "rope_sha256": _sha256_file(agc_build.rope_bin_path()),
        "listing_sha256": _sha256_file(agc_build.listing_path()),
        "scenario_sha256": (
            hashlib.sha256(scenario_json.encode()).hexdigest() if scenario_json else ""
        ),
    }


def read_landing(path: Path) -> dict[str, Any] | None:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            record: dict[str, Any] = json.loads(line)
            if record.get("type") == "landing":
                return record
    return None
