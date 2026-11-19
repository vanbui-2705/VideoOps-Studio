"""Immutable, secret-free channel profile values."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from string import Formatter

from core.domain.errors import ChannelValidationError

_CHANNEL_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_CREDENTIAL_REF = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def _required(value: str, label: str, *, maximum: int = 500) -> str:
    cleaned = value.strip()
    has_unsafe_control = any(
        ord(char) < 32 and char not in {"\n", "\r", "\t"} for char in cleaned
    )
    if not cleaned or len(cleaned) > maximum or has_unsafe_control:
        raise ChannelValidationError(f"{label} is invalid")
    return cleaned


def _validate_template(value: str, *, require_input: bool = False) -> str:
    cleaned = _required(value, "Template", maximum=4000)
    try:
        parsed = tuple(Formatter().parse(cleaned))
        fields = {name for _, name, _, _ in parsed if name is not None}
    except ValueError as exc:
        raise ChannelValidationError("Template syntax is invalid") from exc
    if fields - {"input"}:
        raise ChannelValidationError("Template contains an unsupported placeholder")
    if any(format_spec or conversion for _, _, format_spec, conversion in parsed):
        raise ChannelValidationError("Template formatting options are unsupported")
    if require_input and "input" not in fields:
        raise ChannelValidationError("Prompt template requires {input}")
    return cleaned


def validate_credential_reference(reference: str | None) -> str | None:
    if reference is None or not reference.strip():
        return None
    cleaned = reference.strip()
    if not _CREDENTIAL_REF.fullmatch(cleaned):
        raise ChannelValidationError("Credential reference is invalid")
    return cleaned


@dataclass(frozen=True, slots=True)
class ContentPreset:
    persona: str
    tone: str
    prompt_template: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "persona", _required(self.persona, "Persona", maximum=2000)
        )
        object.__setattr__(self, "tone", _required(self.tone, "Tone", maximum=100))
        object.__setattr__(
            self,
            "prompt_template",
            _validate_template(self.prompt_template, require_input=True),
        )


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    font_family: str = "Arial"
    font_size: int = 48
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 2
    position: str = "bottom"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "font_family", _required(self.font_family, "Font", maximum=100)
        )
        if not re.fullmatch(r"[A-Za-z0-9 _-]+", self.font_family):
            raise ChannelValidationError("Subtitle font contains unsafe characters")
        if not 12 <= self.font_size <= 120:
            raise ChannelValidationError("Subtitle font size is invalid")
        if self.position not in {"top", "center", "bottom"}:
            raise ChannelValidationError("Subtitle position is invalid")
        if not 0 <= self.outline_width <= 10:
            raise ChannelValidationError("Subtitle outline width is invalid")
        for color in (self.primary_color, self.outline_color):
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                raise ChannelValidationError("Subtitle color is invalid")


@dataclass(frozen=True, slots=True)
class VisualPreset:
    aspect_ratio: str = "16:9"
    stock_keywords: tuple[str, ...] = ()
    stock_provider_preferences: tuple[str, ...] = ()
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)

    def __post_init__(self) -> None:
        if self.aspect_ratio not in {"16:9", "9:16"}:
            raise ChannelValidationError("Aspect ratio is unsupported")
        object.__setattr__(
            self,
            "stock_keywords",
            tuple(
                _required(value, "Stock keyword", maximum=80)
                for value in self.stock_keywords
            ),
        )
        object.__setattr__(
            self,
            "stock_provider_preferences",
            tuple(
                _required(value, "Stock provider", maximum=40)
                for value in self.stock_provider_preferences
            ),
        )


@dataclass(frozen=True, slots=True)
class AudioPreset:
    voice: str
    rate_percent: int = 0
    bgm_ref: str | None = None
    ducking_db: float = -12.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "voice", _required(self.voice, "Voice", maximum=128))
        if not -50 <= self.rate_percent <= 100:
            raise ChannelValidationError("Voice rate is invalid")
        if not -30 <= self.ducking_db <= 0:
            raise ChannelValidationError("Ducking level is invalid")
        if self.bgm_ref is not None:
            object.__setattr__(
                self, "bgm_ref", _required(self.bgm_ref, "BGM reference", maximum=128)
            )


@dataclass(frozen=True, slots=True)
class MetadataDefaults:
    title_template: str = "{input}"
    description_template: str = ""
    hashtags: tuple[str, ...] = ()
    category_id: str = "28"
    privacy: str = "private"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title_template", _validate_template(self.title_template)
        )
        if self.description_template:
            object.__setattr__(
                self,
                "description_template",
                _validate_template(self.description_template),
            )
        if self.privacy not in {"private", "unlisted", "public"}:
            raise ChannelValidationError("Privacy is invalid")
        normalized: list[str] = []
        seen: set[str] = set()
        for hashtag in self.hashtags:
            clean = _required(hashtag.lstrip("#"), "Hashtag", maximum=50)
            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)
        if len(normalized) > 30:
            raise ChannelValidationError("Too many hashtags")
        object.__setattr__(self, "hashtags", tuple(normalized))


@dataclass(frozen=True, slots=True)
class CredentialReferences:
    youtube_secret_ref: str | None = None
    tiktok_secret_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "youtube_secret_ref",
            validate_credential_reference(self.youtube_secret_ref),
        )
        object.__setattr__(
            self,
            "tiktok_secret_ref",
            validate_credential_reference(self.tiktok_secret_ref),
        )


@dataclass(frozen=True, slots=True)
class ChannelDraft:
    channel_id: str
    name: str
    niche: str
    language: str
    content: ContentPreset
    visual: VisualPreset
    audio: AudioPreset
    metadata_defaults: MetadataDefaults = field(default_factory=MetadataDefaults)
    credential_refs: CredentialReferences = field(default_factory=CredentialReferences)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not _CHANNEL_ID.fullmatch(self.channel_id):
            raise ChannelValidationError("Channel ID is invalid")
        object.__setattr__(
            self, "name", _required(self.name, "Channel name", maximum=120)
        )
        object.__setattr__(self, "niche", _required(self.niche, "Niche", maximum=120))
        if not _LANGUAGE.fullmatch(self.language):
            raise ChannelValidationError("Language is invalid")


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    draft: ChannelDraft
    revision: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ChannelValidationError("Channel revision must be positive")

    @property
    def channel_id(self) -> str:
        return self.draft.channel_id

    @property
    def name(self) -> str:
        return self.draft.name

    @property
    def enabled(self) -> bool:
        return self.draft.enabled
