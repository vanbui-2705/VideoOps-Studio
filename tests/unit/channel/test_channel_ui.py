from datetime import UTC, datetime

from core.application.channel_ports import CredentialStatus
from core.application.channel_views import ChannelProfileView, ChannelSummary
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    CredentialReferences,
    VisualPreset,
)
from core.domain.models import Platform
from ui.channel_handlers import list_channel_choices, load_channel_form


class FakeCatalog:
    def __init__(self) -> None:
        now = datetime(2026, 11, 16, tzinfo=UTC)
        draft = ChannelDraft(
            "tech_vn",
            "Tech Việt Nam",
            "technology",
            "vi-VN",
            ContentPreset("persona", "tone", "{input}"),
            VisualPreset(),
            AudioPreset("voice"),
            credential_refs=CredentialReferences("YT_TECH"),
        )
        self.view = ChannelProfileView(
            draft,
            2,
            now,
            now,
            CredentialStatus(youtube_configured=True),
        )

    def list(self):
        return (
            ChannelSummary("tech_vn", "Tech Việt Nam", 2, True, (Platform.YOUTUBE,)),
        )

    def get(self, channel_id):
        return self.view


def test_channel_handlers_return_browser_safe_profile_values() -> None:
    catalog = FakeCatalog()

    choices, status = list_channel_choices(catalog)
    form = load_channel_form(catalog, "tech_vn")

    assert choices == [("Tech Việt Nam", "tech_vn")]
    assert "1 profile" in status
    assert form[0] == "tech_vn"
    assert form[-2] == 2
    assert form[-1] == "YouTube: configured · TikTok: missing"
    assert "VIDEOOPS_TEST_SECRET_9f37" not in repr(form)


def test_channel_list_failure_returns_safe_unavailable_state() -> None:
    class BrokenCatalog:
        def list(self):
            raise RuntimeError("database password=VIDEOOPS_TEST_SECRET_9f37")

    choices, status = list_channel_choices(BrokenCatalog())

    assert choices == []
    assert status == "Channel backend unavailable"
    assert "VIDEOOPS_TEST_SECRET_9f37" not in status
