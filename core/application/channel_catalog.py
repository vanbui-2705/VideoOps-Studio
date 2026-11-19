"""Channel profile application service and Module 2 reader adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.application.channel_ports import ChannelRepository, SecretResolver
from core.application.channel_views import (
    ChannelProfileView,
    ChannelSummary,
    project_channel,
)
from core.application.ports import ChannelSnapshot, Clock
from core.domain.channel_models import ChannelDraft
from core.domain.errors import (
    ChannelAdministrationDisabled,
    ChannelProfileNotFound,
)


@dataclass(frozen=True, slots=True)
class SaveChannelRequest:
    profile: ChannelDraft
    expected_revision: int | None = None
    actor_id: str | None = None
    change_reason: str | None = None


class ChannelCatalog(Protocol):
    def list(self) -> tuple[ChannelSummary, ...]: ...

    def get(self, channel_id: str) -> ChannelProfileView: ...

    def save(self, request: SaveChannelRequest) -> ChannelProfileView: ...


class DefaultChannelCatalog:
    """Coordinate safe profile views, secret availability, and admin policy."""

    def __init__(
        self,
        repository: ChannelRepository,
        secrets: SecretResolver,
        clock: Clock,
        *,
        admin_enabled: bool = False,
    ) -> None:
        self._repository = repository
        self._secrets = secrets
        self._clock = clock
        self._admin_enabled = admin_enabled

    @property
    def admin_enabled(self) -> bool:
        return self._admin_enabled

    def list(self) -> tuple[ChannelSummary, ...]:
        return tuple(
            ChannelSummary(
                channel_id=profile.channel_id,
                name=profile.name,
                revision=profile.revision,
                enabled=profile.enabled,
                available_targets=(
                    self._secrets.status(
                        profile.draft.credential_refs
                    ).available_targets
                    if profile.enabled
                    else ()
                ),
            )
            for profile in self._repository.list()
        )

    def get(self, channel_id: str) -> ChannelProfileView:
        profile = self._repository.get(channel_id)
        if profile is None:
            raise ChannelProfileNotFound(channel_id)
        return project_channel(
            profile, self._secrets.status(profile.draft.credential_refs)
        )

    def save(self, request: SaveChannelRequest) -> ChannelProfileView:
        if not self._admin_enabled:
            raise ChannelAdministrationDisabled(
                "Channel administration is disabled for this deployment"
            )
        profile = self._repository.save(
            request.profile,
            request.expected_revision,
            self._clock.now(),
            actor_id=request.actor_id,
            change_reason=request.change_reason,
        )
        return project_channel(
            profile, self._secrets.status(profile.draft.credential_refs)
        )

    def get_snapshot(self, channel_id: str) -> ChannelSnapshot | None:
        profile = self._repository.get(channel_id)
        if profile is None or not profile.enabled:
            return None
        status = self._secrets.status(profile.draft.credential_refs)
        return ChannelSnapshot(
            channel_id=profile.channel_id,
            display_name=profile.name,
            revision=profile.revision,
            available_targets=status.available_targets,
        )
