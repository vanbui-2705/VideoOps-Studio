"""Worker handler for verified zero-retention cleanup."""

from __future__ import annotations

from collections.abc import Callable

from core.application.ports import QueuedWork
from core.application.purge import PurgeCoordinator


class PurgeHandler:
    def __init__(self, coordinator: PurgeCoordinator) -> None:
        self._coordinator = coordinator

    def handle(self, work: QueuedWork, heartbeat: Callable[[], None]):
        return self._coordinator.execute(work, heartbeat)
