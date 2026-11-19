"""Validated provider-neutral story content and provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.domain.errors import DomainValidationError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, label: str, maximum: int) -> str:
    cleaned = value.strip()
    unsafe = any(
        ord(character) < 32 and character not in {"\n", "\r", "\t"}
        for character in cleaned
    )
    if not cleaned or len(cleaned) > maximum or unsafe:
        raise DomainValidationError(f"{label} is invalid")
    return cleaned


class StorySource(str, Enum):
    USER_SCRIPT = "USER_SCRIPT"
    LLM = "LLM"


@dataclass(frozen=True, slots=True)
class ScriptScene:
    order: int
    narration: str
    visual_keywords: tuple[str, ...]
    visual_direction: str | None = None

    def __post_init__(self) -> None:
        if self.order < 1:
            raise DomainValidationError("Scene order must be positive")
        object.__setattr__(
            self, "narration", _text(self.narration, "Scene narration", 10000)
        )
        normalized: list[str] = []
        seen: set[str] = set()
        for keyword in self.visual_keywords:
            clean = _text(keyword, "Visual keyword", 80)
            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)
        if not normalized or len(normalized) > 10:
            raise DomainValidationError("Scene visual keywords are invalid")
        object.__setattr__(self, "visual_keywords", tuple(normalized))
        if self.visual_direction is not None:
            object.__setattr__(
                self,
                "visual_direction",
                _text(self.visual_direction, "Visual direction", 500),
            )


@dataclass(frozen=True, slots=True)
class SuggestedMetadata:
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _text(self.title, "Suggested title", 200))
        if len(self.description) > 5000:
            raise DomainValidationError("Suggested description is too long")
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in self.tags:
            clean = _text(tag.lstrip("#"), "Suggested tag", 50)
            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)
        object.__setattr__(self, "tags", tuple(normalized))


@dataclass(frozen=True, slots=True)
class ScriptProvenance:
    source: StorySource
    prompt_version: str
    prompt_hash: str
    input_hash: str
    generated_at: datetime
    provider: str | None = None
    model: str | None = None
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        _text(self.prompt_version, "Prompt version", 100)
        if not _SHA256.fullmatch(self.prompt_hash) or not _SHA256.fullmatch(
            self.input_hash
        ):
            raise DomainValidationError("Story provenance hash is invalid")
        if self.generated_at.tzinfo is None:
            raise DomainValidationError("Story generation time must be timezone-aware")
        if self.source is StorySource.LLM and not (self.provider and self.model):
            raise DomainValidationError("LLM provenance requires provider and model")
        if self.source is StorySource.USER_SCRIPT and (self.provider or self.model):
            raise DomainValidationError("User script provenance cannot name a provider")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise DomainValidationError("Input token usage is invalid")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise DomainValidationError("Output token usage is invalid")


@dataclass(frozen=True, slots=True)
class ScriptDraft:
    language: str
    title: str
    narration: str
    scenes: tuple[ScriptScene, ...]
    suggested_metadata: SuggestedMetadata
    provenance: ScriptProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", _text(self.language, "Language", 16))
        object.__setattr__(self, "title", _text(self.title, "Story title", 200))
        object.__setattr__(
            self, "narration", _text(self.narration, "Narration", 100000)
        )
        if not self.scenes or len(self.scenes) > 100:
            raise DomainValidationError("Story scene count is invalid")
        if tuple(scene.order for scene in self.scenes) != tuple(
            range(1, len(self.scenes) + 1)
        ):
            raise DomainValidationError("Story scene order must be contiguous")


def validate_story_limits(
    draft: ScriptDraft,
    *,
    min_characters: int,
    max_characters: int,
    max_scenes: int = 100,
    max_keywords_per_scene: int = 10,
) -> None:
    """Apply deployment policy after structural domain validation."""
    if not min_characters <= len(draft.narration) <= max_characters:
        raise DomainValidationError("Story narration length is outside policy")
    if len(draft.scenes) > max_scenes:
        raise DomainValidationError("Story has too many scenes")
    if any(
        len(scene.visual_keywords) > max_keywords_per_scene for scene in draft.scenes
    ):
        raise DomainValidationError("Story scene has too many keywords")
