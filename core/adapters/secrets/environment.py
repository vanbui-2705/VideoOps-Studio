"""Resolve validated credential prefixes from a read-only environment mapping."""

from __future__ import annotations

import os
from collections.abc import Mapping

from core.application.channel_ports import (
    CredentialStatus,
    TikTokCredential,
    YoutubeCredential,
)
from core.domain.channel_models import (
    CredentialReferences,
    validate_credential_reference,
)
from core.domain.errors import CredentialUnavailable

_YOUTUBE_FIELDS = (
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
)
_TIKTOK_FIELDS = ("TIKTOK_SESSION",)


class EnvironmentSecretResolver:
    """Read provider bundles without offering enumeration or write operations."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment if environment is not None else os.environ

    def status(self, references: CredentialReferences) -> CredentialStatus:
        youtube_missing = self._missing(references.youtube_secret_ref, _YOUTUBE_FIELDS)
        tiktok_missing = self._missing(references.tiktok_secret_ref, _TIKTOK_FIELDS)
        return CredentialStatus(
            youtube_configured=bool(references.youtube_secret_ref)
            and not youtube_missing,
            tiktok_configured=bool(references.tiktok_secret_ref) and not tiktok_missing,
            missing_youtube_fields=youtube_missing,
            missing_tiktok_fields=tiktok_missing,
        )

    def resolve_youtube(self, reference: str) -> YoutubeCredential:
        prefix = self._validated(reference)
        values = self._bundle(prefix, _YOUTUBE_FIELDS)
        if values is None:
            raise CredentialUnavailable("YouTube credential bundle is incomplete")
        return YoutubeCredential(*values)

    def resolve_tiktok(self, reference: str) -> TikTokCredential:
        prefix = self._validated(reference)
        values = self._bundle(prefix, _TIKTOK_FIELDS)
        if values is None:
            raise CredentialUnavailable("TikTok credential bundle is incomplete")
        return TikTokCredential(values[0])

    def _missing(
        self, reference: str | None, fields: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not reference:
            return ()
        prefix = self._validated(reference)
        return tuple(
            field
            for field in fields
            if not self._environment.get(f"{prefix}_{field}", "").strip()
        )

    def _bundle(self, prefix: str, fields: tuple[str, ...]) -> tuple[str, ...] | None:
        values = tuple(
            self._environment.get(f"{prefix}_{field}", "").strip() for field in fields
        )
        return values if all(values) else None

    @staticmethod
    def _validated(reference: str) -> str:
        validated = validate_credential_reference(reference)
        if validated is None:
            raise CredentialUnavailable("Credential reference is missing")
        return validated
