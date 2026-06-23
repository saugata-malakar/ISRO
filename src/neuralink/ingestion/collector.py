"""Async ingestion loop (README §8 ingestion).

Consumes events from an in-process queue (a real SNMP/syslog source could be
dropped in behind :meth:`Collector.submit`), normalises each one, persists it to
the encrypted store, and fans it out to registered async handlers (the
orchestrator hooks in here).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from neuralink.config import get_settings
from neuralink.ingestion.normaliser import normalise_event
from neuralink.ingestion.store import EventStore
from neuralink.schemas import NetworkEvent
from neuralink.simulator import Simulator

Handler = Callable[[NetworkEvent], Awaitable[None]]
_SENTINEL = object()


class Collector:
    def __init__(self, store: EventStore | None = None, settings=None) -> None:
        self.settings = settings or get_settings()
        self.store = store or EventStore()
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=self.settings.ingestion.queue_maxsize)
        self.handlers: list[Handler] = []
        self.ingested = 0

    def add_handler(self, handler: Handler) -> None:
        self.handlers.append(handler)

    async def submit(self, event: NetworkEvent) -> None:
        await self.queue.put(event)

    async def close(self) -> None:
        await self.queue.put(_SENTINEL)  # type: ignore[arg-type]

    async def run(self) -> None:
        """Consume until a sentinel is received. Backpressure-safe: one slow
        handler won't drop events; the queue absorbs bursts up to maxsize."""
        while True:
            item = await self.queue.get()
            if item is _SENTINEL:
                self.queue.task_done()
                break
            event = normalise_event(item)
            self.store.add_event(event)
            self.ingested += 1
            for handler in self.handlers:
                await handler(event)
            self.queue.task_done()


async def drive_simulator(
    collector: Collector, sim: Simulator, ticks: int, live: bool = False
) -> None:
    """Producer: push a simulator's events into the collector, then close it."""
    tick_s = collector.settings.simulator.tick_seconds
    for _tick, batch in sim.iter_ticks(ticks):
        for ev in batch:
            await collector.submit(ev)
        if live:
            await asyncio.sleep(tick_s)
    await collector.close()


def ingest_batch(events: list[NetworkEvent], store: EventStore | None = None) -> EventStore:
    """Synchronous helper: normalise + persist a list of events. Returns the store."""
    store = store or EventStore()
    for ev in events:
        store.add_event(normalise_event(ev))
    return store


async def collect_simulator(
    sim: Simulator, ticks: int, store: EventStore | None = None, live: bool = False
) -> EventStore:
    """Convenience: wire a collector to a simulator, run both, return the store."""
    collector = Collector(store=store)
    consumer = asyncio.create_task(collector.run())
    await drive_simulator(collector, sim, ticks, live=live)
    await consumer
    return collector.store
