"""Browser-safe channel projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.application.channel_ports import CredentialStatus
from core.domain.channel_models import ChannelDraft, ChannelProfile
from core.domain.models import Platform


@dataclass(frozen=True, slots=True)
class ChannelSummary:
    channel_id: str
    name: str
    revision: int
    enabled: bool
    available_targets: tuple[Platform, ...]


@dataclass(frozen=True, slots=True)
class ChannelProfileView:
    profile: ChannelDraft
    revision: int
    created_at: datetime
    updated_at: datetime
    credential_status: CredentialStatus

    @property
    def channel_id(self) -> str:
        return self.profile.channel_id

    @property
    def name(self) -> str:
        return self.profile.name


def project_channel(
    profile: ChannelProfile, status: CredentialStatus
) -> ChannelProfileView:
    return ChannelProfileView(
        profile=profile.draft,
        revision=profile.revision,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        credential_status=status,
    )
