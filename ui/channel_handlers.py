"""Pure browser-safe handlers for the Channel Profile workspace."""

from __future__ import annotations

from typing import Any

from core.application.channel_catalog import ChannelCatalog, SaveChannelRequest
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    CredentialReferences,
    MetadataDefaults,
    VisualPreset,
)
from core.domain.errors import ChannelRevisionConflict, WorkflowError


def list_channel_choices(
    catalog: ChannelCatalog | Any | None,
    *,
    enabled_only: bool = False,
) -> tuple[list[tuple[str, str]], str]:
    if catalog is None:
        return [], "ChannelCatalog not configured"
    try:
        summaries = catalog.list()
    except Exception:  # noqa: BLE001 - browser boundary redacts infrastructure errors
        return [], "Channel backend unavailable"
    choices = [
        (summary.name, summary.channel_id)
        for summary in summaries
        if summary.enabled or not enabled_only
    ]
    noun = "profile" if len(choices) == 1 else "profiles"
    return choices, f"{len(choices)} {noun} available"


def load_channel_form(catalog: ChannelCatalog | Any, channel_id: str | None):
    if not channel_id:
        return _empty_form("Select a Channel Profile")
    try:
        view = catalog.get(channel_id)
    except Exception:  # noqa: BLE001 - browser boundary returns a fixed safe message
        return _empty_form("Channel profile unavailable")
    draft = view.profile
    status = view.credential_status
    missing = status.missing_youtube_fields + status.missing_tiktok_fields
    credential_text = (
        f"YouTube: {'configured' if status.youtube_configured else 'missing'} · "
        f"TikTok: {'configured' if status.tiktok_configured else 'missing'}"
    )
    if missing:
        credential_text += f" · Required: {', '.join(missing)}"
    return (
        draft.channel_id,
        draft.name,
        draft.niche,
        draft.language,
        draft.content.persona,
        draft.content.tone,
        draft.content.prompt_template,
        draft.visual.aspect_ratio,
        draft.audio.voice,
        draft.audio.rate_percent,
        draft.audio.bgm_ref or "",
        draft.audio.ducking_db,
        draft.metadata_defaults.title_template,
        draft.metadata_defaults.description_template,
        ", ".join(draft.metadata_defaults.hashtags),
        draft.metadata_defaults.category_id,
        draft.metadata_defaults.privacy,
        draft.credential_refs.youtube_secret_ref or "",
        draft.credential_refs.tiktok_secret_ref or "",
        draft.enabled,
        view.revision,
        credential_text,
    )


def save_channel_form(
    catalog: ChannelCatalog | Any,
    channel_id: str,
    name: str,
    niche: str,
    language: str,
    persona: str,
    tone: str,
    prompt_template: str,
    aspect_ratio: str,
    voice: str,
    rate_percent: int,
    bgm_ref: str,
    ducking_db: float,
    title_template: str,
    description_template: str,
    hashtags: str,
    category_id: str,
    privacy: str,
    youtube_secret_ref: str,
    tiktok_secret_ref: str,
    enabled: bool,
    expected_revision: int | None,
) -> tuple[str, int | None]:
    try:
        draft = ChannelDraft(
            channel_id=channel_id,
            name=name,
            niche=niche,
            language=language,
            content=ContentPreset(persona, tone, prompt_template),
            visual=VisualPreset(aspect_ratio),
            audio=AudioPreset(
                voice,
                int(rate_percent),
                bgm_ref.strip() or None,
                float(ducking_db),
            ),
            metadata_defaults=MetadataDefaults(
                title_template=title_template,
                description_template=description_template,
                hashtags=tuple(
                    item.strip() for item in hashtags.split(",") if item.strip()
                ),
                category_id=category_id,
                privacy=privacy,
            ),
            credential_refs=CredentialReferences(
                youtube_secret_ref.strip() or None,
                tiktok_secret_ref.strip() or None,
            ),
            enabled=enabled,
        )
        view = catalog.save(
            SaveChannelRequest(
                draft,
                expected_revision=int(expected_revision)
                if expected_revision is not None
                else None,
            )
        )
        return f"Saved {view.channel_id} revision {view.revision}", view.revision
    except ChannelRevisionConflict:
        return (
            "Profile changed in another session; reload before saving",
            expected_revision,
        )
    except WorkflowError as exc:
        return f"Cannot save profile ({type(exc).__name__})", expected_revision
    except Exception:  # noqa: BLE001 - redact infrastructure details at browser boundary
        return "Channel backend unavailable", expected_revision


def _empty_form(status: str):
    return (
        "",
        "",
        "",
        "vi-VN",
        "",
        "",
        "",
        "16:9",
        "",
        0,
        "",
        -12,
        "{input}",
        "",
        "",
        "28",
        "private",
        "",
        "",
        True,
        None,
        status,
    )
