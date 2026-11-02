"""Launch and drive a yaAGC process in either clock mode (CODE_REVIEW.md Sec.3.1).

realtime -- `--nodebug`: the AGC free-runs against the wall clock. State beyond the
            socket is visible only via the periodic `--dump-time` core-dump file.
stepped  -- debugger enabled, stdin/stdout are a pipe. The AGC executes only when told to
            (`STEP <octal n>`), blocking at the `(agc)` prompt in between. Blocked time is
            cancelled out of yaAGC's wall-clock accounting by SimUpdateTime(), which the
            debugger calls on every command (verified: a 5 s pause advanced the AGC by
            the same ~1.6k cycles as no pause). `COREDUMP <file>` snapshots all state at
            the pause boundary.

Stepped mode was paced 1:1 to wall-clock while running -- the step loop only executed while
`CycleCount < DesiredCycles`, and `SimSleep()` napped 10 ms whenever the clock tick had not
advanced. Measured: ~17 ms of fixed cost per `STEP` and a hard ceiling of 1.0x real time
whatever the step size. `--free-run` (patches/yaagc-free-run.patch, applied to the pinned
submodule at build time) drops that gate: the AGC then runs as fast as the host allows and the
*caller* sets the pace with its STEP commands. The AGC's own sense of time is unaffected, because
TIME1/TIME2 come from counter interrupts the engine generates per cycle, not from the wall clock.
The flight software is untouched; only the emulator's host-side pacing is.

Primer (Python-only reader):
  * A *child process* is another program started from Python (here the C emulator yaAGC). We
    talk to it through its stdin/stdout "pipes" -- like typing into a terminal and reading the
    answer -- using asyncio.create_subprocess_exec, the async twin of subprocess.Popen.
  * yaAGC also opens TCP *ports* (numbered network endpoints on 127.0.0.1 = this machine). The
    AgcClient (client.py) connects to one to exchange I/O-channel data. This class only uses
    the port number to tell yaAGC which ones to open, and in realtime mode to wait until open.
  * `async`/`await`: cooperative concurrency. While one coroutine waits on the pipe, others
    (e.g. the socket reader in client.py) run. Everything happens in one thread.
  * Octal: the AGC world counts in base 8. Python writes it `0o17` (= 15) and formats with
    f"{n:o}". The yaAGC debugger expects octal numbers.
"""

from __future__ import annotations

import asyncio
import socket
import time
from pathlib import Path
from typing import Literal

from luminary_agent.agc import handshake
from luminary_agent.agc.build import rope_bin_path, yaagc_path
from luminary_agent.agc.coredump import CoreDump, parse_core_dump

Mode = Literal["realtime", "stepped"]  # a type alias: only these two strings are valid

PROMPT = b"(agc) "  # what the yaAGC debugger prints when it is waiting for the next command
DEFAULT_ROPE = rope_bin_path()


def artifacts_present() -> bool:
    """True once `make agc` has built the emulator and the rope (tests skip otherwise)."""
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
        resume_from: Path | None = None,
        free_run: bool = True,
    ) -> None:
        self.resume_from = resume_from
        self.free_run = free_run
        self.workdir = workdir
        self.mode = mode
        self.port = port
        self.rope = rope
        self.dump_time_s = dump_time_s
        self._proc: asyncio.subprocess.Process | None = None  # set by start()

    async def start(self) -> None:
        """Launch yaAGC and wait until it is ready (debugger prompt, or port open)."""
        # Build the command line, e.g.:
        #   yaAGC --port=19797 --quiet --free-run --no-resume MAIN.agc.bin
        # --port: first TCP port to listen on (it opens ~10 consecutive ones from there)
        # --no-resume: boot from power-on instead of a saved core file
        args = [str(yaagc_path()), f"--port={self.port}", "--quiet"]
        if self.free_run and self.mode == "stepped":
            args.append("--free-run")
        if self.resume_from is None:
            args.append("--no-resume")
        if self.mode == "realtime":
            args += ["--nodebug", f"--dump-time={self.dump_time_s}"]
        args.append(str(self.rope))  # positional arg 1: the flight-software binary
        if self.resume_from is not None:  # positional arg 2: a core file to resume from
            args.append(str(self.resume_from.resolve()))
        self.workdir.mkdir(parents=True, exist_ok=True)  # yaAGC writes its core files here
        # Stepped mode: we type debugger commands on stdin and read replies from stdout.
        # Realtime mode: nothing to say to it, so its stdio goes to /dev/null (discarded).
        piped = self.mode == "stepped"
        devnull = asyncio.subprocess.DEVNULL
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.workdir,
            stdin=asyncio.subprocess.PIPE if piped else devnull,
            stdout=asyncio.subprocess.PIPE if piped else devnull,
            stderr=asyncio.subprocess.STDOUT if piped else devnull,  # merge errors into stdout
        )
        if self.mode == "stepped":
            await self._read_until_prompt()  # first "(agc) " prompt = booted and paused
        else:
            # _wait_for_port uses blocking time.sleep; run it in a worker thread so the event
            # loop is not frozen meanwhile.
            await asyncio.to_thread(self._wait_for_port)

    def _wait_for_port(self, timeout_s: float = 5.0) -> None:
        """Poll every 50 ms until something accepts TCP connections on self.port."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # connect_ex returns 0 on success, an error code otherwise (no exception).
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.05)
        raise TimeoutError(f"yaAGC never opened port {self.port}")

    async def _read_until_prompt(self, timeout_s: float = 60.0) -> str:
        """Read yaAGC's stdout up to the next "(agc) " prompt; return the text before it."""
        assert self._proc is not None and self._proc.stdout is not None
        raw = await asyncio.wait_for(self._proc.stdout.readuntil(PROMPT), timeout_s)
        return raw[: -len(PROMPT)].decode(errors="replace")

    async def _command(self, text: str, timeout_s: float = 60.0) -> str:
        """Type one debugger command, wait for the prompt, return yaAGC's reply.

        With a client attached, the handshake (handshake.py) makes the exchange deterministic:
        STEP carries the client's byte count so yaAGC first waits for every channel packet we
        already sent; after the reply we also wait for the end-of-command marker on the socket.
        """
        assert self.mode == "stepped", "debugger commands need stepped mode"
        assert self._proc is not None and self._proc.stdin is not None
        hs = handshake.lookup(self.port)  # None: no client attached (or an unpatched yaAGC)
        before = 0 if hs is None else hs.syncs
        if hs is not None and text.startswith("STEP"):
            text += f" {hs.bytes_sent}"  # yaAGC waits until this many bytes have arrived
        self._proc.stdin.write((text + "\n").encode())  # like typing the line + Enter
        await self._proc.stdin.drain()  # wait until the bytes actually left our buffer
        reply = await self._read_until_prompt(timeout_s)
        if hs is not None:
            await hs.wait_after(before)  # the end-of-command marker: all its output is read
        return reply

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

    async def save_state(self, path: Path) -> Path:
        """Write a resumable checkpoint. The dump is the same file yaAGC itself resumes from, so
        `AgcProcess(..., resume_from=path)` continues from exactly this point (registers,
        erasable, channels, cycle counter). Stepped mode only: the AGC is quiescent here.
        """
        await self._command("COREDUMP snapshot.core")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((self.workdir / "snapshot.core").read_bytes())
        return path

    async def close(self) -> None:
        """Stop yaAGC: polite SIGTERM first, SIGKILL if it has not exited within 5 s."""
        if self._proc is None:
            return
        if self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 5.0)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()

    # `async with AgcProcess(...) as agc:` calls __aenter__ on entry and __aexit__ on exit
    # (even on an exception), so the child process is never left running.
    async def __aenter__(self) -> AgcProcess:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
