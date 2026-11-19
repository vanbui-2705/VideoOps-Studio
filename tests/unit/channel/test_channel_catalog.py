from datetime import UTC, datetime

import pytest

from core.application.channel_catalog import DefaultChannelCatalog, SaveChannelRequest
from core.application.channel_ports import CredentialStatus
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    CredentialReferences,
    VisualPreset,
)
from core.domain.errors import ChannelAdministrationDisabled
from core.domain.models import Platform


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self, profile: ChannelProfile) -> None:
        self.profile = profile

    def list(self):
        return (self.profile,)

    def get(self, channel_id):
        return self.profile if self.profile.channel_id == channel_id else None

    def save(self, draft, expected_revision, now, **kwargs):
        self.profile = ChannelProfile(
            draft,
            1 if expected_revision is None else expected_revision + 1,
            self.profile.created_at,
            now,
        )
        return self.profile


class FakeSecrets:
    def status(self, references):
        return CredentialStatus(youtube_configured=True)


def _profile(*, enabled: bool = True) -> ChannelProfile:
    now = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    draft = ChannelDraft(
        "tech_vn",
        "Tech Việt Nam",
        "technology",
        "vi-VN",
        ContentPreset("persona", "informative", "Write about {input}"),
        VisualPreset("16:9"),
        AudioPreset("vi-VN-NamMinhNeural"),
        credential_refs=CredentialReferences(youtube_secret_ref="YT_TECH"),
        enabled=enabled,
    )
    return ChannelProfile(draft, 3, now, now)


def test_catalog_projects_safe_views_and_channel_snapshot() -> None:
    catalog = DefaultChannelCatalog(
        FakeRepository(_profile()), FakeSecrets(), FixedClock(), admin_enabled=False
    )

    summary = catalog.list()[0]
    view = catalog.get("tech_vn")
    snapshot = catalog.get_snapshot("tech_vn")

    assert summary.available_targets == (Platform.YOUTUBE,)
    assert view.credential_status.youtube_configured is True
    assert snapshot is not None
    assert snapshot.display_name == "Tech Việt Nam"
    assert snapshot.revision == 3
    assert snapshot.available_targets == (Platform.YOUTUBE,)
    assert not hasattr(view, "client_secret")


def test_disabled_channel_is_not_available_to_video_workflow() -> None:
    catalog = DefaultChannelCatalog(
        FakeRepository(_profile(enabled=False)),
        FakeSecrets(),
        FixedClock(),
        admin_enabled=False,
    )

    assert catalog.get_snapshot("tech_vn") is None


def test_save_is_enforced_by_application_admin_policy() -> None:
    profile = _profile()
    disabled = DefaultChannelCatalog(
        FakeRepository(profile), FakeSecrets(), FixedClock(), admin_enabled=False
    )
    enabled = DefaultChannelCatalog(
        FakeRepository(profile), FakeSecrets(), FixedClock(), admin_enabled=True
    )
    request = SaveChannelRequest(profile.draft, expected_revision=3)

    with pytest.raises(ChannelAdministrationDisabled):
        disabled.save(request)
    assert enabled.save(request).revision == 4
