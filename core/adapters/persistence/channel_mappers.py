"""Lossless, secret-free channel profile JSONB mapping."""

from __future__ import annotations

from typing import Any

from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    CredentialReferences,
    MetadataDefaults,
    SubtitleStyle,
    VisualPreset,
)


def channel_draft_to_dict(draft: ChannelDraft) -> dict[str, Any]:
    style = draft.visual.subtitle_style
    return {
        "channel_id": draft.channel_id,
        "name": draft.name,
        "niche": draft.niche,
        "language": draft.language,
        "enabled": draft.enabled,
        "content": {
            "persona": draft.content.persona,
            "tone": draft.content.tone,
            "prompt_template": draft.content.prompt_template,
        },
        "visual": {
            "aspect_ratio": draft.visual.aspect_ratio,
            "stock_keywords": list(draft.visual.stock_keywords),
            "stock_provider_preferences": list(draft.visual.stock_provider_preferences),
            "subtitle_style": {
                "font_family": style.font_family,
                "font_size": style.font_size,
                "primary_color": style.primary_color,
                "outline_color": style.outline_color,
                "outline_width": style.outline_width,
                "position": style.position,
            },
        },
        "audio": {
            "voice": draft.audio.voice,
            "rate_percent": draft.audio.rate_percent,
            "bgm_ref": draft.audio.bgm_ref,
            "ducking_db": draft.audio.ducking_db,
        },
        "metadata_defaults": {
            "title_template": draft.metadata_defaults.title_template,
            "description_template": draft.metadata_defaults.description_template,
            "hashtags": list(draft.metadata_defaults.hashtags),
            "category_id": draft.metadata_defaults.category_id,
            "privacy": draft.metadata_defaults.privacy,
        },
        "credential_refs": {
            "youtube_secret_ref": draft.credential_refs.youtube_secret_ref,
            "tiktok_secret_ref": draft.credential_refs.tiktok_secret_ref,
        },
    }


def channel_draft_from_dict(data: dict[str, Any]) -> ChannelDraft:
    visual = data["visual"]
    style = visual["subtitle_style"]
    audio = data["audio"]
    metadata = data["metadata_defaults"]
    references = data["credential_refs"]
    return ChannelDraft(
        channel_id=data["channel_id"],
        name=data["name"],
        niche=data["niche"],
        language=data["language"],
        content=ContentPreset(**data["content"]),
        visual=VisualPreset(
            aspect_ratio=visual["aspect_ratio"],
            stock_keywords=tuple(visual["stock_keywords"]),
            stock_provider_preferences=tuple(visual["stock_provider_preferences"]),
            subtitle_style=SubtitleStyle(**style),
        ),
        audio=AudioPreset(
            voice=audio["voice"],
            rate_percent=audio["rate_percent"],
            bgm_ref=audio["bgm_ref"],
            ducking_db=audio["ducking_db"],
        ),
        metadata_defaults=MetadataDefaults(
            title_template=metadata["title_template"],
            description_template=metadata["description_template"],
            hashtags=tuple(metadata["hashtags"]),
            category_id=metadata["category_id"],
            privacy=metadata["privacy"],
        ),
        credential_refs=CredentialReferences(**references),
        enabled=data["enabled"],
    )
