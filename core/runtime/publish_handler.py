"""Thin worker handlers for initial publication and reconciliation."""

from __future__ import annotations

from collections.abc import Callable

from core.application.ports import QueuedWork
from core.application.publish_coordinator import PublishCoordinator


class PublishTargetHandler:
    def __init__(
        self, coordinator: PublishCoordinator, *, reconcile: bool = False
    ) -> None:
        self._coordinator = coordinator
        self._reconcile = reconcile

    def handle(self, work: QueuedWork, heartbeat: Callable[[], None]):
        if self._reconcile:
            return self._coordinator.reconcile(work, heartbeat)
        return self._coordinator.execute(work, heartbeat)
