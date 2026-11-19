import pytest

from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    CredentialReferences,
    MetadataDefaults,
    SubtitleStyle,
    VisualPreset,
)
from core.domain.errors import ChannelValidationError


def valid_draft(**changes) -> ChannelDraft:
    values = {
        "channel_id": "tech_vn",
        "name": "Tech Việt Nam",
        "niche": "technology",
        "language": "vi-VN",
        "content": ContentPreset(
            persona="Giải thích công nghệ rõ ràng",
            tone="informative",
            prompt_template="Viết kịch bản về {input}",
        ),
        "visual": VisualPreset(aspect_ratio="16:9"),
        "audio": AudioPreset(voice="vi-VN-NamMinhNeural"),
        "metadata_defaults": MetadataDefaults(
            title_template="{input}",
            hashtags=("#AI", "ai", "Tech"),
            privacy="private",
        ),
        "credential_refs": CredentialReferences("YT_TECH", "TT_TECH"),
    }
    values.update(changes)
    return ChannelDraft(**values)


def test_channel_draft_normalizes_safe_profile_values() -> None:
    draft = valid_draft()

    assert draft.channel_id == "tech_vn"
    assert draft.metadata_defaults.hashtags == ("AI", "Tech")
    assert draft.visual.aspect_ratio == "16:9"


@pytest.mark.parametrize("channel_id", ["UPPER", "a", "../tech", "tech space"])
def test_channel_id_rejects_unsafe_values(channel_id: str) -> None:
    with pytest.raises(ChannelValidationError):
        valid_draft(channel_id=channel_id)


def test_prompt_template_requires_only_the_input_placeholder() -> None:
    with pytest.raises(ChannelValidationError):
        valid_draft(content=ContentPreset("persona", "tone", "No placeholder"))
    with pytest.raises(ChannelValidationError):
        valid_draft(content=ContentPreset("persona", "tone", "{input} {secret}"))
    with pytest.raises(ChannelValidationError):
        valid_draft(content=ContentPreset("persona", "tone", "{input:>1000}"))


def test_multiline_persona_and_prompt_are_supported() -> None:
    draft = valid_draft(
        content=ContentPreset("Dòng một\nDòng hai", "tone", "Mở đầu\nNội dung: {input}")
    )

    assert "\n" in draft.content.prompt_template


@pytest.mark.parametrize(
    "factory",
    [
        lambda: VisualPreset(aspect_ratio="1:1"),
        lambda: AudioPreset(voice="voice", rate_percent=101),
        lambda: AudioPreset(voice="voice", ducking_db=-31),
        lambda: MetadataDefaults(privacy="friends"),
        lambda: CredentialReferences(youtube_secret_ref="yt-lower"),
    ],
)
def test_nested_presets_reject_values_outside_supported_policy(factory) -> None:
    with pytest.raises(ChannelValidationError):
        factory()


def test_subtitle_font_rejects_filtergraph_characters() -> None:
    with pytest.raises(ChannelValidationError, match="unsafe"):
        SubtitleStyle(font_family="Arial,Alignment=8")
