"""asyncio edge: UDP socket + service loop driving the sans-IO core."""

import asyncio
import time

from .enet.peer_core import EnetPeerCore


class UdpTransport(asyncio.DatagramProtocol):
    def __init__(self, on_datagram):
        self._on_datagram = on_datagram
        self.transport: asyncio.DatagramTransport | None = None
        self.error: Exception | None = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self._on_datagram(data)

    def error_received(self, exc):
        self.error = exc

    def connection_lost(self, exc):
        self.transport = None

    def send(self, data: bytes) -> None:
        if self.transport is not None:
            self.transport.sendto(data)

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None


class ServiceLoop:
    """Owns the monotonic clock and pumps the peer core at a fixed rate."""

    def __init__(self, core: EnetPeerCore, transport: UdpTransport,
                 interval_ms: int = 33):
        self.core = core
        self.transport = transport
        self.interval = interval_ms / 1000
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def now_ms(self) -> int:
        return int(time.monotonic() * 1000)

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    def flush(self) -> None:
        for datagram in self.core.take_outgoing():
            self.transport.send(datagram)

    async def _run(self) -> None:
        # Absolute deadlines rather than sleep(interval): Windows timers drift
        # by ~15 ms per wait, which would halve the effective send rate.
        deadline = time.monotonic()
        while not self._stop.is_set():
            self.core.tick(self.now_ms())
            self.flush()
            deadline += self.interval
            delay = deadline - time.monotonic()
            if delay < 0:
                deadline = time.monotonic()
                delay = 0
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay or 0.001)
            except (asyncio.TimeoutError, TimeoutError):
                pass
