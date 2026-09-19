"""Launch and drive a yaAGC process in either clock mode (APOLLO_AGENT_PLAN.md Sec.3.1).

realtime -- `--nodebug`: the AGC free-runs against the wall clock. State beyond the
            socket is visible only via the periodic `--dump-time` core-dump file.
stepped  -- debugger enabled, stdin/stdout are a pipe. The AGC executes only when told to
            (`STEP <octal n>`), blocking at the `(agc)` prompt in between. Blocked time is
            cancelled out of yaAGC's wall-clock accounting by SimUpdateTime(), which the
            debugger calls on every command (verified: a 5 s pause advanced the AGC by
            the same ~1.6k cycles as no pause). `COREDUMP <file>` snapshots all state at
            the pause boundary.

Stepped mode is paced 1:1 to wall-clock while running (the step loop only executes while
CycleCount < DesiredCycles): pausing is free, going faster than real time is not on offer.
"""

from __future__ import annotations

import asyncio
import socket
import time
from pathlib import Path
from typing import Literal

from luminary_agent.agc.build import VIRTUALAGC, yaagc_path
from luminary_agent.agc.coredump import CoreDump, parse_core_dump

Mode = Literal["realtime", "stepped"]

PROMPT = b"(agc) "
DEFAULT_ROPE = VIRTUALAGC / "Luminary099" / "MAIN.agc.bin"


def artifacts_present() -> bool:
    return yaagc_path().exists() and DEFAULT_ROPE.exists()


class AgcProcess:
    """One yaAGC child process. Use as `async with AgcProcess(workdir, mode=...) as agc:`."""

    def __init__(
        self,
        workdir: Path,
        mode: Mode = "stepped",
        port: int = 19797,
        rope: Path = DEFAULT_ROPE,
        dump_time_s: int = 1,
    ) -> None:
        self.workdir = workdir
        self.mode = mode
        self.port = port
        self.rope = rope
        self.dump_time_s = dump_time_s
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        args = [str(yaagc_path()), f"--port={self.port}", "--no-resume", "--quiet"]
        if self.mode == "realtime":
            args += ["--nodebug", f"--dump-time={self.dump_time_s}"]
        args.append(str(self.rope))
        self.workdir.mkdir(parents=True, exist_ok=True)
        piped = self.mode == "stepped"
        devnull = asyncio.subprocess.DEVNULL
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.workdir,
            stdin=asyncio.subprocess.PIPE if piped else devnull,
            stdout=asyncio.subprocess.PIPE if piped else devnull,
            stderr=asyncio.subprocess.STDOUT if piped else devnull,
        )
        if self.mode == "stepped":
            await self._read_until_prompt()
        else:
            await asyncio.to_thread(self._wait_for_port)

    def _wait_for_port(self, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.05)
        raise TimeoutError(f"yaAGC never opened port {self.port}")

    async def _read_until_prompt(self, timeout_s: float = 60.0) -> str:
        assert self._proc is not None and self._proc.stdout is not None
        raw = await asyncio.wait_for(self._proc.stdout.readuntil(PROMPT), timeout_s)
        return raw[: -len(PROMPT)].decode(errors="replace")

    async def _command(self, text: str, timeout_s: float = 60.0) -> str:
        assert self.mode == "stepped", "debugger commands need stepped mode"
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write((text + "\n").encode())
        await self._proc.stdin.drain()
        return await self._read_until_prompt(timeout_s)

    async def step(self, instructions: int) -> str:
        """Run exactly `instructions` AGC instructions, then pause. Returns the debugger's
        stop report, whose first line names the flight-software source line reached
        (e.g. "ADVAN () at EXECUTIVE.agc:475").
        """
        if instructions < 1:
            raise ValueError("instructions must be >= 1")
        return await self._command(f"STEP {instructions:o}")  # the debugger reads octal

    async def coredump(self) -> CoreDump:
        """Snapshot all AGC state at the current pause point (~15 ms)."""
        await self._command("COREDUMP snapshot.core")
        return parse_core_dump(self.workdir / "snapshot.core")

    async def close(self) -> None:
        if self._proc is None:
            return
        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 5.0)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()

    async def __aenter__(self) -> AgcProcess:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
