"""Infrastructure-neutral ports and safe values for channel management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from core.domain.channel_models import (
    ChannelDraft,
    ChannelProfile,
    CredentialReferences,
)
from core.domain.models import Platform


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    youtube_configured: bool = False
    tiktok_configured: bool = False
    missing_youtube_fields: tuple[str, ...] = ()
    missing_tiktok_fields: tuple[str, ...] = ()

    @property
    def available_targets(self) -> tuple[Platform, ...]:
        targets: list[Platform] = []
        if self.youtube_configured:
            targets.append(Platform.YOUTUBE)
        if self.tiktok_configured:
            targets.append(Platform.TIKTOK)
        return tuple(targets)


@dataclass(frozen=True, slots=True)
class YoutubeCredential:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TikTokCredential:
    session_value: str = field(repr=False)


class SecretResolver(Protocol):
    def status(self, references: CredentialReferences) -> CredentialStatus: ...

    def resolve_youtube(self, reference: str) -> YoutubeCredential: ...

    def resolve_tiktok(self, reference: str) -> TikTokCredential: ...


class ChannelRepository(Protocol):
    def list(self) -> tuple[ChannelProfile, ...]: ...

    def get(self, channel_id: str) -> ChannelProfile | None: ...

    def get_revision(self, channel_id: str, revision: int) -> ChannelProfile | None: ...

    def save(
        self,
        draft: ChannelDraft,
        expected_revision: int | None,
        now: datetime,
        *,
        actor_id: str | None = None,
        change_reason: str | None = None,
    ) -> ChannelProfile: ...
