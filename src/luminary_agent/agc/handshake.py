"""Deterministic ordering between the two paths to yaAGC.

The AGC is driven over two unordered paths: channel packets over TCP (`AgcClient`) and debugger
commands over the stdin pipe (`AgcProcess`). Without help, whether a packet sent before a `STEP`
was seen before or after it depends on scheduling, and what the client had read when a step
returned depends on it too: identical episodes diverged under load (5 copies of one episode gave
2 or 3 different results). `patches/yaagc-free-run.patch` adds the two barriers this module
counts for:

  * `STEP n B`: yaAGC waits until the B bytes the client has sent in total have arrived;
  * after every command yaAGC puts a marker packet (channel 0377) on the socket, ahead of the
    prompt; the client counts them, and the process waits for the marker before it returns.

One `Handshake` per yaAGC port is shared by the client and the process on it.

Why it is needed, in plain terms: we speak to yaAGC through two different "doors" -- the stdin
pipe (commands like STEP) and a TCP socket (data packets). Each door is ordered on its own, but
nothing orders one against the other. So "send packet, then STEP" could reach the AGC as "STEP,
then packet". The byte counter and the marker below are the two receipts that restore the order.

`asyncio.Event` is a flag coroutines can wait on: `set()` wakes the waiters, `clear()` re-arms.
"""

from __future__ import annotations

import asyncio

SYNC_CHANNEL = 0o377  # 255: an unused channel number the patched yaAGC uses as the marker
SYNC_TIMEOUT_S = 2.0  # how long to wait for a marker before assuming an unpatched yaAGC


class Handshake:
    """Counters shared by one AgcClient (writes/reads the socket) and one AgcProcess (stdin)."""

    def __init__(self) -> None:
        self.bytes_sent = 0  # total bytes the client has written to the socket
        self.syncs = 0  # markers the client has read
        self.enabled = True  # false once a marker failed to come (an unpatched yaAGC)
        self._arrived = asyncio.Event()

    def marker_seen(self) -> None:
        """Called by the client's socket reader each time a marker packet arrives."""
        self.syncs += 1
        self._arrived.set()

    async def wait_after(self, before: int) -> None:
        """Return once a marker newer than `before` has been read. A yaAGC that never sends one
        (not built from the patch) costs one timeout, then the handshake switches itself off."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SYNC_TIMEOUT_S
        while self.syncs <= before:
            self._arrived.clear()
            if self.syncs > before:  # re-check after clear(): a marker may have just landed
                break
            try:
                await asyncio.wait_for(self._arrived.wait(), max(0.0, deadline - loop.time()))
            except TimeoutError:
                self.enabled = False
                return


# Module-level registry: port number -> its Handshake. The client and the process never hold a
# reference to each other; they meet here through the port they share.
_BY_PORT: dict[int, Handshake] = {}


def register(port: int) -> Handshake:
    """The client calls this when it connects: a fresh handshake for that port."""
    _BY_PORT[port] = handshake = Handshake()
    return handshake


def lookup(port: int) -> Handshake | None:
    """The process asks: is a client attached on this port (and is the handshake still on)?"""
    handshake = _BY_PORT.get(port)
    return handshake if handshake is not None and handshake.enabled else None


def unregister(port: int) -> None:
    """The client calls this when it closes."""
    _BY_PORT.pop(port, None)
